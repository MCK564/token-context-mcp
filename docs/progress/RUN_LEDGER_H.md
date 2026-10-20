# RUN LEDGER H: DeepSeek Harness & Plugin Architecture Refactor

**Status**: In Progress  
**Base commit**: `main` (clean baseline)  
**Target Milestone Versions**:  
- v0.3.4 (H0 Golden Baseline + H1 Surgical Bottlenecks)  
- v0.4.0 (H2 Kernel & Composability + H3 Unified ToolSpec Pipeline)  
- v0.5.0 (H4 Ext Seams + H5 Universal AST Skeletonizer)  
- v0.6.0 (H6 Declarative Context Batching)

---

## Phase H0: Golden Contract Safety Net & Baselines

- [x] **H0.1**: Snapshot `tools/list` schema output contract across 4 server configurations (`core`, `+extensions`, `+admin`, `+extensions+admin`) and 2 client profiles (`default`, `gemini_safe`).
  - Added: `tests/golden/test_tools_list_contract.py` (6 test cases, passing in ~2.6s).
- [x] **H0.2**: Snapshot sanitized structured outputs for standard retrieval tools.
  - Added: `tests/golden/test_tool_outputs.py` covering:
    1. `list_repositories`
    2. `get_index_status`
    3. `get_repo_map`
    4. `find_symbols`
    5. `get_file_skeleton`
    6. `search_source`
    7. `get_module_dependents`
    8. `get_symbol_context`
    9. `get_impact_slice`
    10. `inspect_symbol`
- [x] **H0.3**: Baseline dispatch & call_tool benchmark:
  - Benchmark run: 1,000 iterations against local temporary repo
  - `_dispatch_invoke` overhead: **0.0067 ms/call** (149,430 calls/sec)
  - `server.call_tool("list_repositories")` end-to-end: **6.76 ms/call** (147.9 calls/sec with SQLite audit logging)

---

## Phase H1: Surgical Bottleneck Fixes (v0.3.4)

- [x] **H1.1**: AST byte-span body elision in `sampling/skeleton_hybrid.py` (Tree-sitter byte ranges for Python, Java, TS, Go, C# with regex fallback).
- [x] **H1.2**: Thinking-tags `<think>...</think>` sanitization in `sampling/router.py` (prevents Pydantic JSON parse crashes on DeepSeek R1/QwQ models).
- [x] **H1.3**: TOML roundtrip custom sections preservation in `config.py` via `AppConfig.extra`.
- [x] **H1.4**: Remove dead code `WRITE_OR_MUTATING_TOOLS` in `security/access_control.py` + added explicit classification regression test.
- [x] **H1.5**: Backlog E14 fix verified and documented in `docs/BACKLOG.md`.
- [x] **H1.6**: Version bump to `0.3.4` (single-source in pyproject.toml, `__init__.py`, `CHANGELOG.md`, `test_version_single_source.py`) and verified against golden tests.
