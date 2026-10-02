# SAMPLE PROMPT TEMPLATE / MẪU PROMPT CHO `token-context-mcp`

> File mẫu prompt chuẩn kèm các placeholder, quy trình truy xuất tối ưu token và ma trận lựa chọn mức độ suy luận (Reasoning Effort Matrix) song ngữ **Tiếng Việt & Tiếng Anh**.

---

# PHẦN 1: TIẾNG VIỆT

## 1. Mẫu Prompt Dùng Trực Tiếp Cho AI Agent

*(Bạn có thể copy trực tiếp khối bên dưới, điền thông tin vào 2 placeholder `{{REPO_NAME}}` và `{{USER_TASK}}` rồi gửi cho Agent)*

```markdown
Bạn là trợ lý lập trình chuyên nghiệp. Bạn có quyền truy cập vào MCP server `token-context-mcp`.

THÔNG TIN ĐẦU VÀO (INPUT):
- Repository: {{REPO_NAME}} (đã được đánh chỉ mục và có trạng thái "fresh")
- Yêu cầu nhiệm vụ: {{USER_TASK}}

QUY TRÌNH XỬ LÝ VỚI TOKEN-CONTEXT MCP SERVER:
0. Khám phá tool trước, rồi mới chọn tool và làm việc (Tool Discovery):
   - Chỉ cần làm khi bạn chưa biết chính xác tool nào phù hợp. Biết rồi thì đi thẳng sang bước 1.
   - 0.1 Tìm tool: gọi `search_tools(query="<mô tả việc cần làm bằng tiếng Anh>", limit=2)`. Muốn xem toàn cảnh thì gọi `list_available_tools(category="<nhóm>")` một lần; các nhóm hiện có: `repository_admin`, `code_navigation`, `impact_analysis`, `shared_memory`, `tool_discovery`, `sampling_inference`.
   - 0.2 Chọn tool: lấy kết quả có `relevance_score` cao nhất. Đọc `quick_parameters`, `prerequisites` (tool phải gọi trước) và `recommended_followups` (tool nên gọi sau). Nếu `quick_parameters` đã đủ để gọi thì bỏ qua 0.3.
   - 0.3 Lấy schema chỉ khi cần: gọi `get_tool_schema(tool_name="<tool đã chọn>")` khi cần kiểu dữ liệu chính xác, giá trị `enum` hoặc giá trị mặc định, hoặc khi lần gọi trước bị báo sai tham số. Không lấy schema của tool khác "để phòng xa".
   - 0.4 Gọi đúng tool đã chọn. Mỗi tool chỉ khám phá một lần trong phiên; nhớ kết quả để các lượt sau gọi thẳng.
   - Nếu server không có `search_tools` (cần `enable_extensions = true` trong `repos.toml`), bỏ qua bước 0 và dùng 10 tool lõi ở các bước dưới.
1. Xác thực trạng thái (Pre-flight Check):
   - Gọi `get_index_status(repo_id="{{REPO_NAME}}")` để xác nhận snapshot là `fresh` (schema 2.4) trước khi truy vấn sâu.
2. Định vị mã nguồn (Locate & Orient):
   - Sử dụng `search_source` (với profile="locate") hoặc `find_symbols` để khoanh vùng file và symbol liên quan.
   - Tránh đọc toàn bộ file hoặc quét mù cả codebase.
3. Kiểm tra chi tiết tiết kiệm token (Deep Inspection):
   - Dùng `inspect_symbol(repo_id="{{REPO_NAME}}", query="<ten_symbol>", view="full")` để nhận trọn vẹn context packet (chữ ký hàm, định nghĩa, quan hệ caller/callee) trong một lượt gọi thay vì dùng `read_file`.
4. Phân tích tác động (Impact & Dependencies):
   - Khi chỉnh sửa logic hoặc đổi chữ ký hàm, gọi `get_impact_slice` (cần `symbol_id` lấy từ `find_symbols` hoặc `inspect_symbol`) hoặc `get_module_dependents` để kiểm tra các module bị ảnh hưởng.
5. Tổng hợp hoặc nén (Optional Sampling):
   - Nếu ngữ cảnh quá lớn, gọi `sample_summarize` để trích xuất ràng buộc cốt lõi.
6. Phối hợp nhiều agent (chỉ khi có agent khác cùng sửa repo):
   - Tìm tool bằng bước 0 (ví dụ `search_tools(query="lock shared resource mutex")`), khóa tài nguyên bằng `memory_lock` trước khi sửa và nhớ gọi `memory_unlock` ngay khi xong.

QUY CÁCH PHẢN HỒI (OUTPUT FORMAT):
- Ngắn gọn, súc tích, đi thẳng vào giải pháp kỹ thuật.
- Cấu trúc phản hồi:
  1. [Vấn đề / Mục tiêu cốt lõi]: Tóm tắt trong 1-2 câu.
  2. [Vị trí mã nguồn]: Đường dẫn file và dòng code cụ thể (`file_path:line`).
  3. [Giải pháp / Thay đổi]: Khối code ngắn gọn kèm giải thích ngắn.
  4. [Tác động]: Danh sách symbol hoặc module bị ảnh hưởng trực tiếp (nếu có).
```

### Ví dụ: agent tự tìm tool rồi mới gọi (bước 0 chạy thật)

Agent cần khóa một module để tránh đụng với agent khác. Nó không đọc trước schema của cả 20 tool, chỉ đi theo ba bước:

```text
Bước 1: tìm tool để khóa tài nguyên
> search_tools(query="lock shared resource mutex", limit=2)
< {"query": "lock shared resource mutex", "matches_found": 2, "tools": [
    {"name": "memory_lock", "category": "shared_memory", "relevance_score": 8.0,
     "summary": "Acquire a timed mutex lock on a resource to coordinate multi-agent actions without collisions.",
     "quick_parameters": {"resource_key": "string (required)", "agent_id": "string (required)", "timeout_sec": "integer (default: 60)"},
     "recommended_followups": [], "prerequisites": []},
    {"name": "memory_unlock", "relevance_score": 3.5, "prerequisites": ["memory_lock"], ...}]}
  -> Chọn `memory_lock` (điểm cao nhất). `memory_unlock` là tool phải gọi sau khi xong việc.

Bước 2: lấy schema chi tiết của tool đã chọn (cần khi muốn kiểu dữ liệu và giá trị mặc định chính xác)
> get_tool_schema(tool_name="memory_lock")
< {"status": "success", "tool_name": "memory_lock", "category": "shared_memory",
   "parameters_summary": {...}, "schema": { ...JSON schema đầy đủ: resource_key, agent_id, timeout_sec... }}

Bước 3: gọi đúng tool, không tốn token cho schema của các tool không dùng
> memory_lock(resource_key="auth_module", agent_id="agent_1", timeout_sec=120)
  ... sửa mã trong auth_module ...
> memory_unlock(resource_key="auth_module", agent_id="agent_1")
```

Ví dụ thứ hai, cho việc đọc mã: `search_tools(query="find callers and impact analysis", limit=3)` trả về `get_impact_slice` (5.0), `find_symbols` (4.5), `search_source` (3.5). `get_impact_slice` có `prerequisites: ["find_symbols"]`, nên agent gọi `find_symbols` để lấy `symbol_id` trước rồi mới gọi `get_impact_slice`.

> **Lưu ý:** điểm số và thứ tự là của bản hiện tại (`TOOL_CATALOG` trong `src/token_context_mcp/discovery/catalog.py`) và có thể đổi khi catalog đổi. Các tool khám phá (`list_available_tools`, `search_tools`, `get_tool_schema`) và nhóm `shared_memory` chỉ có khi `enable_extensions = true`.

---

## 2. Hướng Dẫn Chọn Mức Độ Suy Luận (Reasoning Level / Thinking Budget)

Tùy theo độ phức tạp của nhiệm vụ, hãy chọn mức suy luận tương ứng:

| Mức suy luận | Mô hình gợi ý | Dạng tác vụ phù hợp | Lý do kỹ thuật |
| :--- | :--- | :--- | :--- |
| **MỨC THẤP**<br>*(Low / Minimal)* | Claude 3.5 Haiku, Gemini Flash, GPT-4o-mini | • Tra cứu vị trí hàm, class, interface (`find_symbols`)<br>• Kiểm tra trạng thái index (`get_index_status`)<br>• Giải thích đoạn code ngắn đã biết vị trí cụ thể<br>• Sửa lỗi chính tả, cú pháp, format trong 1 hàm | Không cần suy luận đa bước; MCP server đã cung cấp sẵn vị trí và thông tin chính xác. |
| **MỨC TRUNG BÌNH**<br>*(Medium / Standard)* | Claude 3.7 Sonnet, Gemini Pro, GPT-4o | • Thêm tính năng mới trong 1-2 module<br>• Refactor hàm/class nội bộ không đổi public API<br>• Sửa bug nghiệp vụ kết hợp `inspect_symbol` và impact analysis<br>• Viết unit test cho các hàm cụ thể | Cần xâu chuỗi thông tin giữa 2-4 lượt gọi công cụ MCP để đề xuất giải pháp đồng bộ. |
| **MỨC CAO**<br>*(High / Extended / Deep)* | Claude 3.7 Thinking, OpenAI o1/o3, DeepSeek R1 | • Debug lỗi tiềm ẩn (race condition, memory leak, deadlock)<br>• Tái cấu trúc kiến trúc lớn có quan hệ phụ thuộc rộng (`get_module_dependents`)<br>• Thiết kế API / giao thức mới cho toàn bộ thư viện<br>• Phân tích trade-off kiến trúc sâu giữa nhiều giải pháp | Đòi hỏi tạo giả thuyết, suy luận đa nhánh và duyệt đồ thị tác động sâu trên toàn hệ thống. |

---

# PHẦN 2: TIẾNG ANH (ENGLISH SECTION)

## 1. Agent Prompt Template

```markdown
You are an expert software engineer with access to the `token-context-mcp` server.

INPUT:
- Repository: {{REPO_NAME}} (already indexed and confirmed "fresh")
- Task: {{USER_TASK}}

MCP SERVER RETRIEVAL WORKFLOW:
0. Tool Discovery first: find the tool, pick it, then work.
   - Only needed when you do not already know which tool fits. If you do, go straight to step 1.
   - 0.1 Find: call `search_tools(query="<what you need, in English>", limit=2)`. For an overview call `list_available_tools(category="<group>")` once; the groups are `repository_admin`, `code_navigation`, `impact_analysis`, `shared_memory`, `tool_discovery`, `sampling_inference`.
   - 0.2 Choose: take the result with the highest `relevance_score`. Read `quick_parameters`, `prerequisites` (tools to call first) and `recommended_followups` (tools to call next). If `quick_parameters` is enough to make the call, skip 0.3.
   - 0.3 Fetch the schema only when needed: call `get_tool_schema(tool_name="<chosen tool>")` when you need exact types, `enum` values or defaults, or after a call was rejected for bad arguments. Never fetch the schema of a tool you did not choose.
   - 0.4 Call the chosen tool. Discover each tool once per session and remember it so later turns call it directly.
   - If the server has no `search_tools` (it needs `enable_extensions = true` in `repos.toml`), skip step 0 and use the 10 core tools in the steps below.
1. Pre-flight Status Verification:
   - Run `get_index_status(repo_id="{{REPO_NAME}}")` to ensure the snapshot is `fresh` (schema 2.4).
2. Locate & Orient:
   - Call `search_source` (with profile="locate") or `find_symbols` to pinpoint relevant candidates.
   - Avoid crawling or reading whole source files indiscriminately.
3. Token-Efficient Deep Inspection:
   - Run `inspect_symbol(repo_id="{{REPO_NAME}}", query="<symbol_name>", view="full")` to receive the target packet (definition, callee/caller signatures, relations) in a single turn.
4. Impact & Dependency Bounds:
   - If proposing code changes, invoke `get_impact_slice` (it needs a `symbol_id` from `find_symbols` or `inspect_symbol`) or `get_module_dependents` to evaluate backward compatibility and affected callers.
5. Context Distillation (Optional):
   - Use `sample_summarize` when bounded constraint extraction is needed for large files.
6. Multi-agent coordination (only when other agents edit the same repository):
   - Find the tool with step 0 (for example `search_tools(query="lock shared resource mutex")`), lock the resource with `memory_lock` before editing, and call `memory_unlock` as soon as you are done.

OUTPUT FORMAT:
- Concise, precise, and directly actionable.
- Response Structure:
  1. [Core Issue / Goal]: 1-2 clear summary sentences.
  2. [Location]: Exact file paths and line ranges (`path/to/file:line`).
  3. [Solution / Patch]: Minimal code diff or replacement chunk with brief rationale.
  4. [Impact]: Verified affected symbols or modules.
```

### Example: an agent finds its own tool, then calls it (step 0 as it really runs)

The agent must lock a module so it does not collide with another agent. It does not read the schemas of all 20 tools, only these three steps:

```text
Step 1: find a tool to lock a resource
> search_tools(query="lock shared resource mutex", limit=2)
< {"query": "lock shared resource mutex", "matches_found": 2, "tools": [
    {"name": "memory_lock", "category": "shared_memory", "relevance_score": 8.0,
     "summary": "Acquire a timed mutex lock on a resource to coordinate multi-agent actions without collisions.",
     "quick_parameters": {"resource_key": "string (required)", "agent_id": "string (required)", "timeout_sec": "integer (default: 60)"},
     "recommended_followups": [], "prerequisites": []},
    {"name": "memory_unlock", "relevance_score": 3.5, "prerequisites": ["memory_lock"], ...}]}
  -> Pick `memory_lock` (highest score). `memory_unlock` is the tool to call when the work is done.

Step 2: fetch the detailed schema of the chosen tool (when exact types and defaults are needed)
> get_tool_schema(tool_name="memory_lock")
< {"status": "success", "tool_name": "memory_lock", "category": "shared_memory",
   "parameters_summary": {...}, "schema": { ...full JSON schema: resource_key, agent_id, timeout_sec... }}

Step 3: call exactly that tool, with no tokens spent on the schemas of tools it never uses
> memory_lock(resource_key="auth_module", agent_id="agent_1", timeout_sec=120)
  ... edit the code in auth_module ...
> memory_unlock(resource_key="auth_module", agent_id="agent_1")
```

A second example, for reading code: `search_tools(query="find callers and impact analysis", limit=3)` returns `get_impact_slice` (5.0), `find_symbols` (4.5) and `search_source` (3.5). `get_impact_slice` has `prerequisites: ["find_symbols"]`, so the agent calls `find_symbols` first to get a `symbol_id`, then `get_impact_slice`.

> **Note:** the scores and ranking come from the current `TOOL_CATALOG` (`src/token_context_mcp/discovery/catalog.py`) and can change when the catalog changes. The discovery tools (`list_available_tools`, `search_tools`, `get_tool_schema`) and the `shared_memory` group exist only when `enable_extensions = true`.

---

## 2. Reasoning Level Selection Guide

| Reasoning Level | Recommended Models | Suitable Task Types | Technical Rationale |
| :--- | :--- | :--- | :--- |
| **LOW**<br>*(Minimal Thinking)* | Flash / Haiku / Fast models | • Quick symbol definitions or signature lookup (`find_symbols`)<br>• Index freshness sanity checks (`get_index_status`)<br>• Local syntax or linting corrections<br>• Simple localized documentation lookups | Single-hop factual queries where MCP tool answers supply exact truth immediately. |
| **MEDIUM**<br>*(Default Thinking)* | Sonnet / Pro / Standard models | • Scoped feature implementations (1-2 files)<br>• Business logic bug fixes using `inspect_symbol` + impact slice<br>• Internal refactoring preserving public interfaces<br>• Writing unit tests for target symbols | Requires synthesizing facts across 2-4 MCP tool turns without deep graph recursion. |
| **HIGH**<br>*(Deep Reasoning)* | O1 / Extended Thinking models | • Non-deterministic bug hunting (race conditions, async deadlocks)<br>• System-wide architecture overhauls with large fan-out<br>• Critical security audit and cross-layer migrations<br>• Complex algorithmic design with trade-off analysis | Requires multi-branch hypothesis generation, constraint checking, and deep graph traversal. |
