# Abbreviation & Terminology Guide / Cẩm Nang Thuật Ngữ & Viết Tắt

This guide provides formal definitions, architectural context, and rationale for all abbreviations, compiler techniques, and graph analysis mechanisms implemented in `token-context-mcp`.

---

## 1. Compiler & Program Analysis Terminology (Thuật Ngữ Trình Biên Dịch & Phân Tích Mã Nguồn)

### AST (Abstract Syntax Tree) — Cây Cú Pháp Trừu Tượng
- **Definition**: A hierarchical tree representation of the abstract syntactic structure of source code. Unlike CSTs, ASTs omit purely lexical tokens such as punctuation, semicolons, brackets, and comments, focusing on semantic constructs (function calls, variable declarations, assignments, binary operations).
- **In token-context-mcp**: Extracted calls (`CallRecord`) and syntax nodes are obtained from Tree-sitter parsers to map precise callers, callees, and argument sites.

### CST (Concrete Syntax Tree / Parse Tree) — Cây Cú Pháp Cụ Thể
- **Definition**: A complete, high-fidelity tree containing every single character and token in the source code, including trivia (whitespaces, indentation, commas, and parentheses).
- **In token-context-mcp**: Tree-sitter parses files into concrete syntax nodes. We preserve byte offsets (`start_byte`, `end_byte`) to slice exact symbol bodies without re-encoding text.

### SSA (Static Single Assignment) & Pseudo-SSA
- **Definition**: A property of an intermediate representation where every variable is assigned exactly once, and every variable is defined before it is used.
- **Pseudo-SSA Heuristic**: Full SSA in compilers (like LLVM) requires phi-nodes ($\phi$) across control-flow joins. In `token-context-mcp`, **Pseudo-SSA** is a lightweight intra-procedural heuristic:
  1. Tracks assignment frequency per variable name within a function body.
  2. If a variable is assigned exactly once (`count == 1`) as an instantiation (`worker = Worker()`), it is attributed a single static type.
  3. If reassigned multiple times (`count >= 2`) or assigned inside conditional branches, it is flagged as **tainted** (`is_tainted=True`), preventing false positive edge attributions.

### CHA (Class Hierarchy Analysis) — Phân Tích Phân Cấp Lớp
- **Definition**: A whole-program call-graph construction algorithm that uses class inheritance relationships to resolve virtual/inherited method dispatches.
- **In token-context-mcp**: Extracted during symbol discovery into the `class_hierarchy` table (`class_symbol_id`, `parent_name`, `parent_symbol_id`). When `self.method()` or `instance.method()` is invoked, CHA traverses ancestors recursively via BFS/MRO to locate inherited methods across files without requiring full type checkers.

### MRO (Method Resolution Order) — Thứ Tự Phân Giải Phương Thức
- **Definition**: The linear order in which a language looks up methods and attributes on inheritance trees (e.g. C3 linearization in Python).
- **In token-context-mcp**: Simplified ancestor traversal following declared class hierarchies to match receiver calls against base classes.

### Type Narrowing (Thu Hẹp Kiểu)
- **Definition**: A flow-sensitive typing technique where a variable with a broad or dynamic type is refined to a more specific type within a guarded control-flow block (e.g., inside an `if isinstance(v, Class)` branch or pattern-matching `match v: case Class()`).
- **In token-context-mcp**: Implemented via **Scoped Type Stacking**. Inside an `isinstance` or `case` branch, the parser pushes a narrowed scope frame up to maximum depth 12. Calls on the narrowed variable within that branch are untainted and bound to the specific type with high confidence.

### Flow-Sensitive Analysis (Phân Tích Nhạy Theo Luồng Dữ Liệu)
- **Definition**: Program analysis that takes into account the order of statements and execution branches, rather than considering the entire function as a single unordered bag of expressions.

---

## 2. Graph Resolution & Indexing (Đồ Thị & Phân Giải Chỉ Mục)

### Lexical Graph (Đồ Thị Từ Vựng & Cú Pháp)
- **Definition**: A directed graph representing relationships (calls, references, inheritance) derived through syntactic AST analysis and lexical scoping, rather than full runtime evaluation or whole-program compilation.

### Resolved vs. Ambiguous Edges
- **Resolved Edge (`status="resolved"`)**: An edge where the target symbol (or external stub) has been uniquely identified with high confidence ($\ge 0.75$).
- **Ambiguous Edge (`status="ambiguous"`)**: An edge where multiple candidates exist (e.g. polymorphic methods sharing identical names across unrelated modules) or where receiver type is tainted/unknown. Assigned confidence $0.10$ to prevent hallucinations in downstream LLM agents.

### Circuit Breaker (Bộ Ngắt Mạch Thời Gian)
- **Definition**: A defensive timeout mechanism that limits execution time per file (e.g. $30\text{ ms}$) during AST edge resolution. Large generated files (e.g., protobuf, swagger clients $>5,000$ lines) trigger the breaker, converting remaining unparsed calls to ambiguous edges rather than freezing the indexing pipeline.

### Virtual External Stubs (Stub Ngoại Vi Ảo)
- **Definition**: Pre-compiled, in-memory/SQLite-persisted metadata records describing popular 3rd-party and standard library packages (`pydantic`, `unittest`, `requests`, `fastapi`, `pytest`, `builtins`).
- **Tree-Shaking**: Only stubs for packages actually imported by the repository are indexed into the repo's SQLite store, avoiding database bloat while resolving calls like `self.assertEqual(...)` or `requests.get(...)` with $0.90$ confidence.

### SCIP (Source Code Intelligence Protocol) & LSIF
- **Definition**: Standardized index formats (developed by Sourcegraph) for emitting rich code navigation data (definitions, references, hover) across development tools.

---

## 3. Systems, Architecture & Standards (Kiến Trúc Hệ Thống & Giao Thức)

### MCP (Model Context Protocol)
- **Definition**: An open standard protocol created by Anthropic allowing AI assistants and LLMs to securely interact with local or remote context sources, tools, and prompts over standard input/output (`stdio`) or SSE transports.

### LSP (Language Server Protocol)
- **Definition**: A JSON-RPC protocol developed by Microsoft connecting code editors to language servers that provide autocomplete, go-to-definition, and diagnostics.
- **Zero-LSP Invariant in token-context-mcp**: We intentionally do NOT run background LSP server processes (such as Pyright, TypeScript Server, or Rust Analyzer) because they consume massive RAM ($1\text{--}4\text{ GB}$), require persistent daemons, and suffer startup latencies. `token-context-mcp` delivers sub-millisecond retrieval from an immutable, lightweight SQLite file.

### PyO3 & Rust Fast-Path
- **Definition**: Rust bindings for the Python interpreter. Used in `token-context-mcp` as an optional compiled acceleration engine for AST traversal, while maintaining a pure Python fallback guard for universal portability.

### FTS5 (Full-Text Search 5)
- **Definition**: An SQLite virtual table module providing full-text indexing, BM25 ranking, and tokenized substring queries across indexed symbol signatures and bodies.

### IPC (Inter-Process Communication)
- **Definition**: Mechanisms for processes to exchange data. `token-context-mcp` communicates with client AI agents (Claude Desktop, Cursor, Antigravity, VS Code) using JSON-RPC via standard I/O pipes (`stdio`).

---

## 4. Confidence Score Scale Reference (Thang Đo Điểm Tin Cậy)

| Score ($\ge$) | Status | Backend | Scope Evidence | Description |
|---|---|---|---|---|
| **0.95** | `resolved` | `lexical` | `same_class` | Method called on `self` within the same class definition. |
| **0.90** | `resolved` | `virtual_stub` | `stub:*` | External library call resolved against curated virtual stub catalog. |
| **0.90** | `resolved` | `lexical` | `exact_receiver_type` / `cha_inherited` | Resolved via single-assignment inferred type or class hierarchy. |
| **0.85** | `resolved` | `lexical` | `same_file` / `import_match` | Resolved to an explicit imported symbol or same-file function. |
| **0.75** | `resolved` | `lexical` | `same_package` / `import_module` | Resolved to a package sibling. |
| **0.40** | `resolved` | `lexical` | `global` | Unique repository-wide symbol match without direct import. |
| **0.10** | `ambiguous` | `lexical` | `*_ambiguous` / `tainted` / `timeout` | Multiple candidates, reassigned receiver, or circuit breaker timeout. |
