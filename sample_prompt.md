# SAMPLE PROMPT TEMPLATE / MẪU PROMPT CHO `token-context-mcp`

> Mẫu prompt chuẩn cho AI Agent dùng `token-context-mcp`: danh sách tool đầy đủ, quy ước memory, quy trình truy xuất tiết kiệm token (khám phá tool → nhớ lại từ memory → định vị → kiểm tra → phân tích tác động → khóa và sửa → ghi nhớ) và ma trận chọn mức suy luận. Song ngữ **Tiếng Việt & Tiếng Anh**, hai phần có cùng cấu trúc.
>
> Đối chiếu với bản 0.3.3: `TOOL_CATALOG` (`src/token_context_mcp/discovery/catalog.py`), `server.py`, `memory/store.py`. Placeholder: `{{REPO_NAME}}`, `{{USER_TASK}}`, `{{AGENT_ID}}`.

---

# PHẦN 1: TIẾNG VIỆT

## 1. Danh sách tool

Server đăng ký 20 tool, thêm 2 tool admin nếu bật. Tool có mặt hay không tùy cấu hình trong `repos.toml`.

### 1.1 Tool lõi (10 tool, luôn có)

| Nhóm | Tool | Dùng khi | Tham số chính (`*` = bắt buộc) |
| :--- | :--- | :--- | :--- |
| `repository_admin` | `list_repositories` | Lấy `repo_id` hợp lệ. Gọi đầu tiên khi chưa chắc `repo_id` | không có |
| `repository_admin` | `get_index_status` | Kiểm tra snapshot (độ mới, số file/symbol, path đã đổi từ lúc index) trước khi tin đồ thị | `repo_id*` |
| `code_navigation` | `get_repo_map` | Định hướng trong repo lạ: symbol xếp hạng theo ngân sách token | `repo_id*`, `query`, `budget_tokens`, `format`, `profile` |
| `code_navigation` | `find_symbols` | Tìm symbol theo tên hoặc qualified name, trả `symbol_id` và vị trí | `repo_id*`, `pattern*` (hỗ trợ `*` `?`), `kind`, `limit` |
| `code_navigation` | `search_source` | Tìm full-text theo nội dung code, xếp theo symbol bao quanh; profile `locate` kèm caller/callee lân cận | `repo_id*`, `query*`, `profile`, `limit`, `expand` |
| `code_navigation` | `get_file_skeleton` | Xem khung một file (import, chữ ký, bỏ thân hàm) thay cho đọc cả file | `repo_id*`, `path*`, `include_private` |
| `impact_analysis` | `get_symbol_context` | Gói nguồn có giới hạn của một symbol và láng giềng trong đồ thị | `repo_id*`, `symbol_id*`, `depth`, `include_body`, `body_offset_line` |
| `impact_analysis` | `get_impact_slice` | Duyệt caller/callee quan sát được từ một symbol (ứng viên ảnh hưởng, không phải toàn bộ blast radius) | `repo_id*`, `symbol_id*`, `direction`, `depth`, `min_confidence` |
| `impact_analysis` | `get_module_dependents` | Quan hệ import của một module hoặc path: ai import nó, nó import gì | `repo_id*`, `module` hoặc `path` |
| `impact_analysis` | `inspect_symbol` | Tool gộp một lượt: resolve symbol, định nghĩa, đồ thị tức thời. Dùng trước khi sửa symbol | `repo_id*`, `query*`, `view`, `budget_tokens` |

### 1.2 Tool mở rộng (10 tool, cần `enable_extensions = true`)

| Nhóm | Tool | Dùng khi | Tham số chính (`*` = bắt buộc) |
| :--- | :--- | :--- | :--- |
| `tool_discovery` | `list_available_tools` | Xem catalog gọn, nhóm theo category | `category` |
| `tool_discovery` | `search_tools` | Tìm tool theo từ khóa tiếng Anh, trả `relevance_score` | `query*`, `limit` (mặc định 3) |
| `tool_discovery` | `get_tool_schema` | Lấy JSON schema đầy đủ của đúng một tool | `tool_name*` |
| `shared_memory` | `memory_search` | Tìm full-text trong memory khi chưa biết khóa | `query*`, `scope`, `namespace`, `limit` (mặc định 5) |
| `shared_memory` | `memory_get` | Đọc đúng một mục khi đã biết khóa | `key*`, `scope`, `namespace`, `session_id` |
| `shared_memory` | `memory_put` | Lưu kết luận, checkpoint, thông tin chuyển giao giữa các agent | `key*`, `value*`, `scope`, `namespace`, `ttl`, `session_id` |
| `shared_memory` | `memory_consolidate` | Gộp các mục rải rác thành một bản tổng hợp | `scope`, `namespace`, `target_key`, `prune_transient` |
| `shared_memory` | `memory_lock` | Khóa một tài nguyên có thời hạn khi nhiều agent cùng sửa | `resource_key*`, `agent_id*`, `timeout_sec` (60) |
| `shared_memory` | `memory_unlock` | Nhả khóa mình đang giữ | `resource_key*`, `agent_id` |
| `sampling_inference` | `sample_summarize` | Nén văn bản lớn thành JSON ngắn (dùng model local nếu có, không thì trích xuất xác định) | `text*`, `intent`, `max_tokens` (512), `target_symbols` |

### 1.3 Tool admin (2 tool, cần `enable_extensions` và `enable_admin_tools`)

`agent_control` (nhóm `security_governance`: `status`, `pause`, `resume`, `block`, `unblock`, `revoke_locks`, `emergency_halt`, `emergency_resume`, cần `admin_token`) và `audit_logs` (`limit`, `agent_id`, `status`). Dành cho người vận hành, không đưa vào prompt của agent làm việc.

### 1.4 Chuỗi gọi hay gặp

| Chuỗi | Lý do |
| :--- | :--- |
| `list_repositories` → `get_index_status` | Có `repo_id` rồi mới kiểm tra snapshot |
| `find_symbols` → `get_symbol_context` hoặc `get_impact_slice` | Hai tool sau cần `symbol_id` (`inspect_symbol` nhận tên trực tiếp, không cần) |
| `memory_search` hoặc `memory_get` → (xác minh bằng `inspect_symbol`) → `memory_put` | Nhớ lại, đối chiếu với mã, rồi cập nhật |
| `memory_lock` → sửa → `memory_unlock` | Khóa luôn đi kèm nhả khóa |
| `get_impact_slice` hoặc `inspect_symbol` → `sample_summarize` → `memory_put` | Nén kết quả lớn rồi lưu bản gọn |

## 2. Quy ước memory

Các mục được lưu bền trong `memory.sqlite` cạnh `repos.toml`, nên agent ở phiên sau đọc lại được. Quy ước đề xuất:

| Loại thông tin | `scope` | `namespace` | `key` | `ttl` (giây) |
| :--- | :--- | :--- | :--- | :--- |
| Checkpoint tiến độ của một agent | `session` | `<agent_id>` | `task.progress` | 3600 |
| Kết luận về mã (bug, hợp đồng hàm, lý do thiết kế) | `project` | `repo:<REPO_NAME>` | `<module>.<chu_de>` | 604800 (7 ngày) |
| Quyết định kiến trúc lâu dài | `project` | `repo:<REPO_NAME>` | `decision.<chu_de>` | 0 (không hết hạn) |
| Bản tổng hợp (do `memory_consolidate` tự ghi) | `global` | trống | `project_architectural_insights` | không hết hạn |

`value` nên là JSON nhỏ, gồm con trỏ và kết luận: `{"finding": "...", "where": "path:line", "symbol_id": "...", "status": "open|fixed"}`.

Những điểm dễ sai (đã kiểm tra trên mã nguồn):

1. `scope` chỉ là nhãn phân vùng (`session`, `project`, `global`), không tự cô lập theo phiên hay theo agent. Muốn cô lập thì dùng `namespace`.
2. `memory_get` phải khớp đủ `scope`, `namespace` và `key`, thiếu một thứ là `not_found`. `memory_search` bỏ trống `namespace` thì tìm ở mọi namespace.
3. `memory_get` và `memory_put` đều hỗ trợ `session_id`: khi truyền `session_id`, server tự động map vào namespace tương ứng để cô lập theo session. Ngoài ra bạn có thể dùng `namespace` tường minh để quản lý phân vùng.
4. `memory_search` nối mọi từ khóa bằng AND, không xếp hạng (chỉ cắt theo `limit`) và trả luôn `value`. Dùng 1-3 từ khóa và `limit` nhỏ.
5. `ttl` mặc định 86400 giây (1 ngày). `ttl=0` hoặc `null` là không hết hạn. Mục hết hạn không được trả về.
6. Key tối đa 256 byte, value tối đa 1 MB. Chuỗi giống bí mật bị che khi lưu, nhưng vẫn đừng lưu bí mật hay thân hàm.
7. `memory_consolidate` đọc tối đa 100 mục cũ nhất của `scope` (mọi namespace) và luôn ghi bản tổng hợp vào `scope="global"`. Gọi khi kết thúc việc lớn. Giữ `prune_transient=false` làm mặc định: bản tổng hợp là bản nén nên mất chi tiết, còn `prune_transient=true` xóa hẳn các mục nguồn ở mọi namespace của `scope` đó.
8. `memory_lock` không chờ: nếu người khác đang giữ, nó trả ngay `acquired: false` kèm `held_by` và `remaining_sec`. Gọi lại cùng `agent_id` thì gia hạn. Khóa tự hết hạn sau `timeout_sec` và chỉ là quy ước giữa các agent dùng server này, không chặn việc ghi file.
9. `memory_unlock` bỏ trống `agent_id` thì lấy từ biến môi trường `TOKEN_CONTEXT_AGENT_ID` hoặc `anonymous`. Luôn truyền đúng `agent_id` đã dùng để khóa. `agent_id` hợp lệ: chữ, số, `_`, `-`, tối đa 64 ký tự.

## 3. Mẫu Prompt Dùng Trực Tiếp Cho AI Agent

*(Copy khối bên dưới, điền `{{REPO_NAME}}`, `{{USER_TASK}}`, và `{{AGENT_ID}}` (khớp `TOKEN_CONTEXT_AGENT_ID` nếu server có đặt, hoặc để `agent_1` khi chỉ có một agent) rồi gửi cho Agent)*

```markdown
Bạn là trợ lý lập trình chuyên nghiệp. Bạn có quyền truy cập vào MCP server `token-context-mcp`.

THÔNG TIN ĐẦU VÀO (INPUT):
- Repository: {{REPO_NAME}} (đã được đánh chỉ mục)
- Định danh của bạn: {{AGENT_ID}} (khớp `TOKEN_CONTEXT_AGENT_ID` của tiến trình server nếu có đặt; dùng cho khóa và memory)
- Yêu cầu nhiệm vụ: {{USER_TASK}}

NGUYÊN TẮC:
- Memory cho manh mối, mã nguồn là chân lý. Tra memory trước để khỏi làm lại việc cũ, nhưng đối chiếu với mã trước khi dựa vào. Mâu thuẫn thì tin mã.
- Lấy đúng thứ cần: dùng tool của server thay cho đọc nguyên file. Khám phá mỗi tool một lần trong phiên.
- Chỉ lưu con trỏ và kết luận (`file:line`, `symbol_id`, quyết định), không lưu thân hàm hay bí mật (token, mật khẩu).
- Nếu có `TOKEN_CONTEXT_AGENT_ID`, KHÔNG truyền `agent_id` khác giá trị đó (server sẽ từ chối). `admin` là id dành riêng, không tự khai.
- Gặp `HALT_BY_USER` hoặc `ACCESS_DENIED`: dừng lại và báo người dùng, không đổi `agent_id` để né. Một call token-context lỗi/timeout: dừng, báo lỗi, không tự đi tìm repo thủ công; gọi tuần tự thay vì song song nếu nghi nghẽn.
- Tool nào không có hoặc bị từ chối thì bỏ bước đó và nói rõ trong phản hồi (xem "KHI TOOL KHÔNG DÙNG ĐƯỢC").

QUY TRÌNH:
0. Khám phá tool (chỉ khi chưa biết tool nào phù hợp; biết rồi thì đi thẳng sang bước 1):
   - Tìm: `search_tools(query="<việc cần làm, tiếng Anh, dùng từ gần tên tool như memory search, memory lock, impact analysis>", limit=2)`. Muốn xem toàn cảnh thì gọi `list_available_tools(category="<nhóm>")` một lần. Các nhóm: `repository_admin`, `code_navigation`, `impact_analysis`, `tool_discovery`, `shared_memory`, `sampling_inference`.
   - Chọn: lấy tool có `relevance_score` cao nhất. Đọc `quick_parameters`, `prerequisites` (tool gọi trước) và `recommended_followups` (tool gọi sau). Đủ tham số để gọi thì bỏ bước lấy schema.
   - Lấy schema khi cần: `get_tool_schema(tool_name="<tool đã chọn>")` chỉ khi cần kiểu dữ liệu, `enum` hay giá trị mặc định chính xác, hoặc khi lần gọi trước bị báo sai tham số. Không lấy schema của tool khác để phòng xa.
1. Kiểm tra trạng thái (Pre-flight):
   - Chưa chắc `repo_id` thì gọi `list_repositories()`. Sau đó `get_index_status(repo_id="{{REPO_NAME}}")`: snapshot phải còn mới (`fresh`), xem các path đã đổi từ lúc index. Snapshot cũ thì coi kết quả đồ thị chỉ là ứng viên và kiểm lại bằng mã.
2. Nhớ lại từ memory (Recall), trước khi tìm mã (cần `memory_*`):
   - Việc tiếp nối: `memory_get(key="task.progress", scope="session", namespace="{{AGENT_ID}}")` (hoặc truyền `session_id` tương ứng).
   - Bản tổng hợp sẵn có: `memory_get(key="project_architectural_insights", scope="global")`. `not_found` thì bỏ qua.
   - Kết luận cũ về chủ đề này: `memory_search(query="<1-3 từ khóa: module hoặc symbol>", scope="project", limit=5)`. Từ khóa được nối bằng AND nên ít từ thì rộng hơn. 0 kết quả thì thử đúng một lần với từ khóa ngắn hơn rồi bỏ qua. Để trống `namespace` khi chưa biết nó. Kết quả đã kèm `value` đầy đủ, không cần `memory_get` thêm.
   - Dùng kết quả như manh mối: lấy `where` hoặc `symbol_id` làm điểm bắt đầu cho bước 3-4 và xem `created_at` để biết độ cũ. Mâu thuẫn với mã thì tin mã và cập nhật lại ở bước 8.
3. Định vị mã nguồn (Locate & Orient):
   - `search_source(repo_id="{{REPO_NAME}}", query="<từ khóa>", profile="locate")` hoặc `find_symbols(repo_id="{{REPO_NAME}}", pattern="<Ten*>")` để khoanh vùng file và symbol.
   - Repo còn lạ: `get_repo_map(repo_id="{{REPO_NAME}}", query="<chủ đề>", budget_tokens=<n>)`. Đã biết file: `get_file_skeleton(repo_id="{{REPO_NAME}}", path="<đường/dẫn>")` thay cho đọc cả file.
4. Kiểm tra chi tiết (Deep Inspection):
   - `inspect_symbol(repo_id="{{REPO_NAME}}", query="<ten_symbol>", view="full")` trả trọn gói (chữ ký, thân hàm, caller/callee, test liên quan) trong một lượt. Dùng trước khi sửa symbol. Cần theo một `symbol_id` cụ thể thì dùng `get_symbol_context`. Nếu thân hàm quá lớn so với ngân sách, đọc từng cửa sổ bằng `get_symbol_context(..., include_body=true, body_offset_line=1)` rồi lấy `body_window.next_offset` cho trang sau, đến khi `next_offset` rỗng.
5. Phân tích tác động (Impact & Dependencies):
   - Khi đổi logic hoặc chữ ký: `get_impact_slice(repo_id="{{REPO_NAME}}", symbol_id="<id>", direction="callers", depth=2)` (`symbol_id` lấy từ `find_symbols` hoặc `inspect_symbol`) và/hoặc `get_module_dependents(repo_id="{{REPO_NAME}}", module="<module>")`. Kết quả là ứng viên chứ không phải toàn bộ phạm vi ảnh hưởng. Đọc kỹ cảnh báo về cạnh mơ hồ và kết quả bị cắt bớt.
6. Nén (tùy chọn):
   - Có khối văn bản lớn (log, nhiều packet) thì gọi `sample_summarize(text="<...>", intent="<mục tiêu>", max_tokens=512)` để giữ lại ràng buộc cốt lõi.
7. Khóa khi sửa (chỉ khi có agent khác cùng sửa repo):
   - `memory_lock(resource_key="<module hoặc file>", agent_id="{{AGENT_ID}}", timeout_sec=<dài hơn thời gian sửa>)`. Chỉ sửa khi phản hồi có `acquired: true`. Nếu `acquired: false` thì không sửa: làm việc khác rồi thử lại sau `remaining_sec` giây.
   - Sửa xong gọi ngay `memory_unlock(resource_key="<cùng khóa>", agent_id="{{AGENT_ID}}")` (chỉ chủ lock mới nhả được).
8. Ghi nhớ (Write-back, cần `memory_put`):
   - Kết luận đáng dùng lại: `memory_put(key="<module>.<chu_de>", value={"finding": "...", "where": "path:line", "symbol_id": "...", "status": "..."}, scope="project", namespace="repo:{{REPO_NAME}}", ttl=604800)`. Cùng `key` thì ghi đè, nên muốn cập nhật mục cũ hãy dùng đúng key đó.
   - Việc dài: lưu checkpoint `memory_put(key="task.progress", value={...}, scope="session", namespace="{{AGENT_ID}}", ttl=3600)`.
   - Quyết định kiến trúc lâu dài: `key="decision.<chu_de>"` và `ttl=0` (không hết hạn).
   - Kết thúc việc lớn, hoặc khi `memory_search` trả nhiều mục rời rạc: `memory_consolidate(scope="project", namespace="repo:{{REPO_NAME}}")`, giữ `prune_transient=false`.

KHI TOOL KHÔNG DÙNG ĐƯỢC:
- Không thấy `search_tools` và `memory_*`: server chưa bật `enable_extensions = true`. Bỏ bước 0, 2, 6, 7, 8 và chỉ dùng 10 tool lõi.
- Lỗi `POLICY_VIOLATION` (agent ở chế độ READ_ONLY): vẫn dùng được `memory_get` và `memory_search`, nhưng không dùng được `memory_put`, `memory_lock`, `memory_unlock`, `sample_summarize`. Đưa kết luận vào phản hồi thay vì ghi.
- Lỗi `HALT_BY_USER` hoặc `ACCESS_DENIED`: dừng lại và báo người dùng, không đổi `agent_id` để né.

QUY CÁCH PHẢN HỒI (OUTPUT FORMAT):
- Ngắn gọn, súc tích, đi thẳng vào giải pháp kỹ thuật.
- Cấu trúc phản hồi:
  1. [Vấn đề / Mục tiêu cốt lõi]: Tóm tắt trong 1-2 câu.
  2. [Vị trí mã nguồn]: Đường dẫn file và dòng code cụ thể (`file_path:line`).
  3. [Giải pháp / Thay đổi]: Khối code ngắn gọn kèm giải thích ngắn.
  4. [Tác động]: Danh sách symbol hoặc module bị ảnh hưởng trực tiếp (nếu có).
  5. [Memory]: Key đã dùng (nếu có) và key đã ghi hoặc cập nhật. Ghi "không dùng" nếu bỏ qua.
```

## 4. Ví dụ chạy thật

Cấu trúc phản hồi dưới đây lấy từ lần chạy thật `MemoryService` (store trong RAM) và `search_tools`; nội dung `value` là ví dụ minh họa.

### Ví dụ 1: nhớ lại, đối chiếu với mã, rồi ghi lại

Nhiệm vụ: "Sửa lỗi refresh token không thu hồi token cũ". Một agent trước đó đã để lại kết luận.

```text
Bước 2: nhớ lại
> memory_search(query="refresh token", scope="project", limit=5)
< {"query": "refresh token", "matches_count": 1, "matches": [
    {"scope": "project", "namespace": "repo:myrepo", "key": "auth_module.refresh_token",
     "value": {"finding": "refresh_token() khong thu hoi token cu", "where": "src/auth/tokens.py:88", "symbol_id": "sym_abc"},
     "created_at": 1790929105.17}]}
  -> Đã có `value` đầy đủ nên không cần memory_get. Dùng `where` làm điểm xuất phát.

Bước 4: đối chiếu với mã, không tin memory một cách mù quáng
> inspect_symbol(repo_id="myrepo", query="refresh_token", view="full")
  ... mã vẫn đúng như memory mô tả -> sửa ...

Đọc thẳng khi đã biết khóa: phải đủ cả scope và namespace
> memory_get(key="auth_module.refresh_token", scope="project", namespace="repo:myrepo")
< {"status": "found", "key": "auth_module.refresh_token", "value": {...}, "created_at": ..., "expires_at": null}
> memory_get(key="auth_module.refresh_token", scope="project")
< {"status": "not_found", "namespace": "", "value": null}      <- thiếu namespace nên không thấy

Bước 8: ghi lại kết quả
> memory_put(key="auth_module.refresh_token", scope="project", namespace="repo:myrepo", ttl=604800,
              value={"finding": "refresh_token() khong thu hoi token cu", "where": "src/auth/tokens.py:88", "status": "fixed"})
< {"status": "stored", "scope": "project", "namespace": "repo:myrepo", "key": "auth_module.refresh_token", "ttl": 604800, "expires_at": ...}

Cuối việc lớn: gộp các mục rời rạc
> memory_consolidate(scope="project")
< {"status": "consolidated", "target_key": "project_architectural_insights", "target_scope": "global",
    "source_entries_count": 1, "pruned_keys": [], "insights": {...}}
```

### Ví dụ 2: khóa đang bị agent khác giữ

```text
> memory_lock(resource_key="auth_module", agent_id="agent_2", timeout_sec=120)
< {"status": "locked", "acquired": false, "resource_key": "auth_module", "held_by": "agent_1", "remaining_sec": 120.0}
  -> Chưa được sửa. Làm việc khác (đọc mã, viết test), quay lại sau `remaining_sec` giây rồi khóa lại.

> memory_unlock(resource_key="auth_module", agent_id="agent_2")
< {"status": "not_locked", "message": "Lock on 'auth_module' was not found or is held by another agent", ...}
  -> Không nhả được khóa của người khác. Khóa sẽ tự hết hạn sau `timeout_sec`.

(agent_1 sửa xong)
> memory_unlock(resource_key="auth_module", agent_id="agent_1")
< {"status": "released", "resource_key": "auth_module"}
```

### Ví dụ 3: chưa biết có tool nào, tự khám phá rồi mới gọi (bước 0)

```text
Bước 1: tìm tool để tra kết luận cũ
> search_tools(query="search memory previous findings", limit=2)
< {"matches_found": 2, "tools": [
    {"name": "memory_search", "category": "shared_memory", "relevance_score": 9.0,
     "quick_parameters": {"query": "string (required)", "scope": "...", "namespace": "...", "limit": "integer (default: 5)"}, ...},
    {"name": "search_source", "relevance_score": 4.5, ...}]}
  -> Chọn `memory_search` (điểm cao nhất, đúng việc tra memory). `search_source` là tìm trong mã, không phải memory.

Bước 2: lấy schema chi tiết, chỉ khi cần kiểu dữ liệu và giá trị mặc định chính xác
> get_tool_schema(tool_name="memory_search")
< {"status": "success", "tool_name": "memory_search", "parameters_summary": {...}, "schema": { ...JSON schema đầy đủ... }}

Bước 3: gọi đúng tool, không tốn token cho schema của các tool không dùng
> memory_search(query="refresh token", scope="project", limit=5)
```

Ví dụ cho việc đọc mã: `search_tools(query="find callers and impact analysis", limit=3)` trả về `get_impact_slice` (5.0), `find_symbols` (4.5), `search_source` (3.5). `get_impact_slice` có `prerequisites: ["find_symbols"]`, nên agent gọi `find_symbols` lấy `symbol_id` trước rồi mới gọi `get_impact_slice`.

> **Lưu ý:** `search_tools` khớp theo từ khóa (tên tool, tag, summary), không hiểu ngữ nghĩa. Câu hỏi tự nhiên như "save finding for other agents" có thể không ra tool đúng; hãy dùng từ gần tên tool (`memory save checkpoint`, `memory lock`). Điểm số lấy từ `TOOL_CATALOG` hiện tại và có thể đổi khi catalog đổi.

### Ví dụ 4: nén ngữ cảnh lớn bằng `sample_summarize` rồi lưu vào memory

Khi gặp một file mã nguồn, log lỗi hoặc đồ thị phụ thuộc quá dài, thay vì đưa toàn bộ văn bản thô vào context của Agent hoặc lưu hàng nghìn dòng vào memory, Agent gọi `sample_summarize` để nén có cấu trúc (bảo toàn ràng buộc và trích dẫn mã nguồn thực tế).

```text
Bước 1: nén đoạn mã hoặc log dài
> sample_summarize(
    text="class PaymentGateway:\n    def process(self, amount, currency):\n        if amount <= 0:\n            raise ValueError('Invalid amount')\n        ...",
    intent="Phân tích ràng buộc giao dịch thanh toán và xử lý lỗi",
    max_tokens=512,
    target_symbols=["PaymentGateway.process"]
  )
< {
    "backend": "ollama_gpu",
    "engine": "qwen2.5-coder:7b-instruct-q4_K_M",
    "status": "success",
    "latency_ms": 480,
    "symbol_coverage_rate": 1.0,
    "context_retention_rate": 0.92,
    "data": {
      "intent_alignment": "Phân tích điều kiện đầu vào của giao dịch và xử lý ngoại lệ.",
      "analyzed_symbols": [
        {
          "name": "PaymentGateway.process",
          "responsibility": "Xử lý giao dịch thanh toán với kiểm tra số tiền hợp lệ",
          "critical_constraints": [
            {
              "verbatim_quote": "if amount <= 0: raise ValueError('Invalid amount')",
              "rule": "amount phải lớn hơn 0, nếu không ném ValueError",
              "line": 3
            }
          ],
          "calls_external": [],
          "line_span": [1, 15]
        }
      ],
      "technical_caveats": ["Cần bổ sung retry khi gặp timeout mạng"]
    }
  }
  -> Kết quả đã được guardrail đối chiếu với AST thật (symbol_coverage_rate: 1.0).

Bước 2: lưu cấu trúc nén này vào memory để các agent khác cùng đọc
> memory_put(
    key="payment.gateway_rules",
    scope="project",
    namespace="repo:myrepo",
    ttl=604800,
    value={"rules": "amount > 0 bắt buộc", "symbol": "PaymentGateway.process", "caveat": "chưa có retry"}
  )
< {"status": "stored", "scope": "project", "namespace": "repo:myrepo", "key": "payment.gateway_rules", "ttl": 604800, "expires_at": ...}
```

---

## 5. Hướng Dẫn Chọn Mức Độ Suy Luận (Reasoning Level / Thinking Budget)

Mức suy luận không đổi quy trình ở mục 3, chỉ đổi mức độ lập giả thuyết và kiểm tra chéo. Chọn theo độ phức tạp của nhiệm vụ:

| Mức suy luận | Nhóm mô hình gợi ý | Dạng tác vụ phù hợp | Lý do kỹ thuật |
| :--- | :--- | :--- | :--- |
| **MỨC THẤP**<br>*(Low / Minimal)* | Mô hình nhỏ, nhanh (dòng Haiku, Gemini Flash, GPT mini) | • Tra cứu vị trí hàm, class, interface (`find_symbols`)<br>• Kiểm tra trạng thái index (`get_index_status`)<br>• Đọc lại kết luận đã lưu theo khóa biết trước (`memory_get`)<br>• Giải thích đoạn code ngắn đã biết vị trí, sửa lỗi chính tả hoặc format trong 1 hàm | Không cần suy luận đa bước; server đã cung cấp sẵn vị trí và thông tin chính xác. |
| **MỨC TRUNG BÌNH**<br>*(Medium / Standard)* | Mô hình tiêu chuẩn (dòng Sonnet, Gemini Pro, GPT tiêu chuẩn) | • Thêm tính năng trong 1-2 module<br>• Refactor nội bộ không đổi public API<br>• Sửa bug nghiệp vụ, kết hợp `memory_search`, `inspect_symbol` và `get_impact_slice`<br>• Viết unit test cho các hàm cụ thể | Cần xâu chuỗi thông tin giữa 2-4 lượt gọi tool và đối chiếu memory với mã. |
| **MỨC CAO**<br>*(High / Extended / Deep)* | Mô hình suy luận sâu (Opus hoặc extended thinking, dòng o của OpenAI, DeepSeek R1) | • Debug lỗi tiềm ẩn (race condition, memory leak, deadlock)<br>• Tái cấu trúc kiến trúc lớn có quan hệ phụ thuộc rộng (`get_module_dependents`)<br>• Điều phối nhiều agent sửa chung một repo (`memory_lock`, `memory_consolidate`)<br>• Thiết kế API hoặc giao thức mới, phân tích trade-off sâu | Đòi hỏi tạo giả thuyết, suy luận đa nhánh và duyệt đồ thị tác động sâu trên toàn hệ thống. |

---

# PHẦN 2: TIẾNG ANH (ENGLISH SECTION)

## 1. Tool List

The server registers 20 tools, plus 2 admin tools when enabled. Which tools exist depends on the configuration in `repos.toml`.

### 1.1 Core tools (10 tools, always available)

| Category | Tool | Use when | Main parameters (`*` = required) |
| :--- | :--- | :--- | :--- |
| `repository_admin` | `list_repositories` | Get a valid `repo_id`. Call first when unsure of the `repo_id` | none |
| `repository_admin` | `get_index_status` | Check the snapshot (freshness, file/symbol counts, paths changed since indexing) before trusting the graph | `repo_id*` |
| `code_navigation` | `get_repo_map` | Orient in an unfamiliar repo: symbols ranked within a token budget | `repo_id*`, `query`, `budget_tokens`, `format`, `profile` |
| `code_navigation` | `find_symbols` | Find symbols by name or qualified name; returns `symbol_id` and location | `repo_id*`, `pattern*` (supports `*` `?`), `kind`, `limit` |
| `code_navigation` | `search_source` | Full-text search over code, ranked by enclosing symbol; profile `locate` adds neighbouring callers/callees | `repo_id*`, `query*`, `profile`, `limit`, `expand` |
| `code_navigation` | `get_file_skeleton` | See a file's outline (imports, signatures, bodies elided) instead of reading the whole file | `repo_id*`, `path*`, `include_private` |
| `impact_analysis` | `get_symbol_context` | Bounded source packet for one symbol plus its graph neighbourhood | `repo_id*`, `symbol_id*`, `depth`, `include_body`, `body_offset_line` |
| `impact_analysis` | `get_impact_slice` | Traverse observed caller/callee edges from a symbol (candidate impact, not the full blast radius) | `repo_id*`, `symbol_id*`, `direction`, `depth`, `min_confidence` |
| `impact_analysis` | `get_module_dependents` | Import relationships of a module or path: who imports it, what it imports | `repo_id*`, `module` or `path` |
| `impact_analysis` | `inspect_symbol` | One-turn composite: resolve the symbol, definition, immediate graph. Use before editing a symbol | `repo_id*`, `query*`, `view`, `budget_tokens` |

### 1.2 Extension tools (10 tools, need `enable_extensions = true`)

| Category | Tool | Use when | Main parameters (`*` = required) |
| :--- | :--- | :--- | :--- |
| `tool_discovery` | `list_available_tools` | Compact catalog grouped by category | `category` |
| `tool_discovery` | `search_tools` | Find a tool by English keywords; returns `relevance_score` | `query*`, `limit` (default 3) |
| `tool_discovery` | `get_tool_schema` | Full JSON schema of exactly one tool | `tool_name*` |
| `shared_memory` | `memory_search` | Full-text search in memory when you do not know the key | `query*`, `scope`, `namespace`, `limit` (default 5) |
| `shared_memory` | `memory_get` | Read exactly one entry when you know the key | `key*`, `scope`, `namespace`, `session_id` |
| `shared_memory` | `memory_put` | Store conclusions, checkpoints, hand-off data between agents | `key*`, `value*`, `scope`, `namespace`, `ttl`, `session_id` |
| `shared_memory` | `memory_consolidate` | Merge scattered entries into one summary | `scope`, `namespace`, `target_key`, `prune_transient` |
| `shared_memory` | `memory_lock` | Time-limited lock on a resource when several agents edit | `resource_key*`, `agent_id*`, `timeout_sec` (60) |
| `shared_memory` | `memory_unlock` | Release a lock you hold | `resource_key*`, `agent_id` |
| `sampling_inference` | `sample_summarize` | Compress large text into short JSON (local model if available, otherwise deterministic extraction) | `text*`, `intent`, `max_tokens` (512), `target_symbols` |

### 1.3 Admin tools (2 tools, need `enable_extensions` and `enable_admin_tools`)

`agent_control` (category `security_governance`: `status`, `pause`, `resume`, `block`, `unblock`, `revoke_locks`, `emergency_halt`, `emergency_resume`, needs `admin_token`) and `audit_logs` (`limit`, `agent_id`, `status`). For operators; do not put them in a working agent's prompt.

### 1.4 Common call chains

| Chain | Reason |
| :--- | :--- |
| `list_repositories` → `get_index_status` | Get a `repo_id` before checking the snapshot |
| `find_symbols` → `get_symbol_context` or `get_impact_slice` | The latter two need a `symbol_id` (`inspect_symbol` takes a name directly) |
| `memory_search` or `memory_get` → (verify with `inspect_symbol`) → `memory_put` | Recall, check against the code, then update |
| `memory_lock` → edit → `memory_unlock` | A lock always comes with a release |
| `get_impact_slice` or `inspect_symbol` → `sample_summarize` → `memory_put` | Compress a large result, then store the short version |

## 2. Memory Conventions

Entries are persisted in `memory.sqlite` next to `repos.toml`, so a later session can read them. Suggested conventions:

| Kind of information | `scope` | `namespace` | `key` | `ttl` (seconds) |
| :--- | :--- | :--- | :--- | :--- |
| One agent's progress checkpoint | `session` | `<agent_id>` | `task.progress` | 3600 |
| Conclusions about code (bugs, function contracts, design reasons) | `project` | `repo:<REPO_NAME>` | `<module>.<topic>` | 604800 (7 days) |
| Long-lived architecture decisions | `project` | `repo:<REPO_NAME>` | `decision.<topic>` | 0 (never expires) |
| Consolidated summary (written by `memory_consolidate`) | `global` | empty | `project_architectural_insights` | never expires |

`value` should be small JSON holding pointers and conclusions: `{"finding": "...", "where": "path:line", "symbol_id": "...", "status": "open|fixed"}`.

Easy-to-miss behaviours (verified against the source):

1. `scope` is only a partition label (`session`, `project`, `global`); it does not isolate by session or agent by itself. Use `namespace` to isolate.
2. `memory_get` must match `scope`, `namespace` and `key` exactly, otherwise it returns `not_found`. `memory_search` with no `namespace` searches every namespace.
3. Both `memory_get` and `memory_put` support `session_id`: when passed, the server automatically isolates the entry under that session namespace. You can also explicitly manage partitions via `namespace`.
4. `memory_search` joins all keywords with AND, does not rank (it only cuts at `limit`) and returns the `value` inline. Use 1-3 keywords and a small `limit`.
5. `ttl` defaults to 86400 seconds (1 day). `ttl=0` or `null` means never expires. Expired entries are not returned.
6. Keys are at most 256 bytes and values at most 1 MB. Secret-looking strings are redacted on store, but still do not store secrets or function bodies.
7. `memory_consolidate` reads at most the 100 oldest entries of a `scope` (all namespaces) and always writes the summary into `scope="global"`. Call it at the end of a large task. Keep `prune_transient=false` as the default: the summary is a compression and loses detail, while `prune_transient=true` permanently deletes the source entries in every namespace of that `scope`.
8. `memory_lock` does not wait: if someone else holds the lock it returns `acquired: false` immediately, with `held_by` and `remaining_sec`. Calling it again with the same `agent_id` renews the lock. The lock expires on its own after `timeout_sec` and is only a convention between agents using this server; it does not block file writes.
9. `memory_unlock` with no `agent_id` falls back to the `TOKEN_CONTEXT_AGENT_ID` environment variable, or `anonymous`. Always pass the same `agent_id` you locked with. A valid `agent_id` uses letters, digits, `_` and `-`, at most 64 characters.

## 3. Agent Prompt Template

*(Copy the block below, fill in `{{REPO_NAME}}`, `{{USER_TASK}}` and `{{AGENT_ID}}` (must equal `TOKEN_CONTEXT_AGENT_ID` if configured on the server, or use `agent_1` when there is a single agent), then send it to the agent)*

```markdown
You are an expert software engineer with access to the `token-context-mcp` server.

INPUT:
- Repository: {{REPO_NAME}} (already indexed)
- Your identifier: {{AGENT_ID}} (must equal the server's `TOKEN_CONTEXT_AGENT_ID` when set; used for locks and memory)
- Task: {{USER_TASK}}

PRINCIPLES:
- Memory gives leads, the code is the truth. Check memory first to avoid redoing old work, but verify against the code before relying on it. If they disagree, trust the code.
- Fetch only what you need: use the server's tools instead of reading whole files. Discover each tool once per session.
- Store only pointers and conclusions (`file:line`, `symbol_id`, decisions), never function bodies or secrets (tokens, passwords).
- If `TOKEN_CONTEXT_AGENT_ID` is set, never pass a different `agent_id` (the server rejects it). `admin` is reserved; do not claim it.
- On `HALT_BY_USER` or `ACCESS_DENIED`, stop and tell the user; do not change your `agent_id` to get around it. If a token-context call fails or times out, stop and report; do not hunt for the repository by hand. Prefer sequential calls over parallel ones if the bridge looks congested.
- If a tool is missing or denied, skip that step and say so in your answer (see "WHEN A TOOL IS NOT AVAILABLE").

WORKFLOW:
0. Tool discovery (only when you do not know which tool fits; if you do, go straight to step 1):
   - Find: `search_tools(query="<what you need, in English, using words close to tool names such as memory search, memory lock, impact analysis>", limit=2)`. For an overview call `list_available_tools(category="<group>")` once. Groups: `repository_admin`, `code_navigation`, `impact_analysis`, `tool_discovery`, `shared_memory`, `sampling_inference`.
   - Choose: take the tool with the highest `relevance_score`. Read `quick_parameters`, `prerequisites` (tools to call first) and `recommended_followups` (tools to call next). If the parameters are enough to make the call, skip the schema.
   - Fetch the schema only when needed: `get_tool_schema(tool_name="<chosen tool>")` only when you need exact types, `enum` values or defaults, or after a call was rejected for bad arguments. Never fetch the schema of a tool you did not choose.
1. Pre-flight:
   - If unsure of the `repo_id`, call `list_repositories()`. Then `get_index_status(repo_id="{{REPO_NAME}}")`: the snapshot must be `fresh`; look at the paths changed since indexing. If it is stale, treat graph results as candidates only and re-check against the code.
2. Recall from memory, before searching the code (needs `memory_*`):
   - Continuing earlier work: `memory_get(key="task.progress", scope="session", namespace="{{AGENT_ID}}")` (or pass the matching `session_id`).
   - Existing summary: `memory_get(key="project_architectural_insights", scope="global")`. Skip on `not_found`.
   - Earlier conclusions on this topic: `memory_search(query="<1-3 keywords: module or symbol>", scope="project", limit=5)`. Keywords are joined with AND, so fewer words match more. On 0 results retry exactly once with shorter keywords, then move on. Leave `namespace` empty when you do not know it. Results already include the full `value`, so no extra `memory_get` is needed.
   - Use results as leads: take `where` or `symbol_id` as the starting point for steps 3-4 and check `created_at` for age. If the code disagrees, trust the code and update memory in step 8.
3. Locate & Orient:
   - `search_source(repo_id="{{REPO_NAME}}", query="<keywords>", profile="locate")` or `find_symbols(repo_id="{{REPO_NAME}}", pattern="<Name*>")` to pinpoint files and symbols.
   - Unfamiliar repo: `get_repo_map(repo_id="{{REPO_NAME}}", query="<topic>", budget_tokens=<n>)`. Known file: `get_file_skeleton(repo_id="{{REPO_NAME}}", path="<path/to/file>")` instead of reading the whole file.
4. Deep Inspection:
   - `inspect_symbol(repo_id="{{REPO_NAME}}", query="<symbol_name>", view="full")` returns the whole packet (signature, body, callers/callees, related tests) in one turn. Use it before editing a symbol. Use `get_symbol_context` when you need a specific `symbol_id`. If a body is too large for the budget, read it in windows with `get_symbol_context(..., include_body=true, body_offset_line=1)` and follow `body_window.next_offset` until it is empty.
5. Impact & Dependencies:
   - When changing logic or a signature: `get_impact_slice(repo_id="{{REPO_NAME}}", symbol_id="<id>", direction="callers", depth=2)` (`symbol_id` comes from `find_symbols` or `inspect_symbol`) and/or `get_module_dependents(repo_id="{{REPO_NAME}}", module="<module>")`. Results are candidates, not the full blast radius. Read the warnings about ambiguous edges and truncation.
6. Distill (optional):
   - For a large block of text (logs, many packets) call `sample_summarize(text="<...>", intent="<goal>", max_tokens=512)` to keep the core constraints.
7. Lock while editing (only when other agents edit the same repository):
   - `memory_lock(resource_key="<module or file>", agent_id="{{AGENT_ID}}", timeout_sec=<longer than the edit>)`. Edit only when the response has `acquired: true`. If `acquired: false`, do not edit: do other work and retry after `remaining_sec` seconds.
   - As soon as you finish, call `memory_unlock(resource_key="<same key>", agent_id="{{AGENT_ID}}")` (only the lock holder can release).
8. Write back (needs `memory_put`):
   - A conclusion worth reusing: `memory_put(key="<module>.<topic>", value={"finding": "...", "where": "path:line", "symbol_id": "...", "status": "..."}, scope="project", namespace="repo:{{REPO_NAME}}", ttl=604800)`. The same `key` overwrites, so to update an old entry reuse its exact key.
   - Long tasks: store a checkpoint `memory_put(key="task.progress", value={...}, scope="session", namespace="{{AGENT_ID}}", ttl=3600)`.
   - Long-lived architecture decisions: `key="decision.<topic>"` and `ttl=0` (never expires).
   - At the end of a large task, or when `memory_search` returns many scattered entries: `memory_consolidate(scope="project", namespace="repo:{{REPO_NAME}}")`, keeping `prune_transient=false`.

WHEN A TOOL IS NOT AVAILABLE:
- No `search_tools` and no `memory_*`: the server was not started with `enable_extensions = true`. Skip steps 0, 2, 6, 7, 8 and use only the 10 core tools.
- `POLICY_VIOLATION` error (agent is READ_ONLY): `memory_get` and `memory_search` still work, but `memory_put`, `memory_lock`, `memory_unlock` and `sample_summarize` do not. Put the conclusions in your answer instead of storing them.
- `HALT_BY_USER` or `ACCESS_DENIED` error: stop and tell the user; do not change your `agent_id` to get around it.

OUTPUT FORMAT:
- Concise, precise, and directly actionable.
- Response structure:
  1. [Core Issue / Goal]: 1-2 clear summary sentences.
  2. [Location]: Exact file paths and line ranges (`path/to/file:line`).
  3. [Solution / Patch]: Minimal code diff or replacement chunk with brief rationale.
  4. [Impact]: Verified affected symbols or modules.
  5. [Memory]: Keys used (if any) and keys written or updated. Write "not used" if skipped.
```

## 4. Worked Examples

The response shapes below come from real runs of `MemoryService` (in-RAM store) and `search_tools`; the `value` contents are illustrative.

### Example 1: recall, check against the code, then write back

Task: "Fix the bug where refresh_token does not revoke the old token". An earlier agent left a conclusion.

```text
Step 2: recall
> memory_search(query="refresh token", scope="project", limit=5)
< {"query": "refresh token", "matches_count": 1, "matches": [
    {"scope": "project", "namespace": "repo:myrepo", "key": "auth_module.refresh_token",
     "value": {"finding": "refresh_token() does not revoke the old token", "where": "src/auth/tokens.py:88", "symbol_id": "sym_abc"},
     "created_at": 1790929105.17}]}
  -> The full `value` is already here, so no memory_get is needed. Use `where` as the starting point.

Step 4: check against the code, do not trust memory blindly
> inspect_symbol(repo_id="myrepo", query="refresh_token", view="full")
  ... the code still matches what memory says -> make the fix ...

Read directly when the key is known: scope and namespace must both match
> memory_get(key="auth_module.refresh_token", scope="project", namespace="repo:myrepo")
< {"status": "found", "key": "auth_module.refresh_token", "value": {...}, "created_at": ..., "expires_at": null}
> memory_get(key="auth_module.refresh_token", scope="project")
< {"status": "not_found", "namespace": "", "value": null}      <- namespace missing, so nothing is found

Step 8: write the result back
> memory_put(key="auth_module.refresh_token", scope="project", namespace="repo:myrepo", ttl=604800,
              value={"finding": "refresh_token() does not revoke the old token", "where": "src/auth/tokens.py:88", "status": "fixed"})
< {"status": "stored", "scope": "project", "namespace": "repo:myrepo", "key": "auth_module.refresh_token", "ttl": 604800, "expires_at": ...}

End of a large task: merge the scattered entries
> memory_consolidate(scope="project")
< {"status": "consolidated", "target_key": "project_architectural_insights", "target_scope": "global",
    "source_entries_count": 1, "pruned_keys": [], "insights": {...}}
```

### Example 2: the lock is held by another agent

```text
> memory_lock(resource_key="auth_module", agent_id="agent_2", timeout_sec=120)
< {"status": "locked", "acquired": false, "resource_key": "auth_module", "held_by": "agent_1", "remaining_sec": 120.0}
  -> Not allowed to edit yet. Do other work (read code, write tests), come back after `remaining_sec` seconds and lock again.

> memory_unlock(resource_key="auth_module", agent_id="agent_2")
< {"status": "not_locked", "message": "Lock on 'auth_module' was not found or is held by another agent", ...}
  -> You cannot release someone else's lock. It expires on its own after `timeout_sec`.

(agent_1 finishes editing)
> memory_unlock(resource_key="auth_module", agent_id="agent_1")
< {"status": "released", "resource_key": "auth_module"}
```

### Example 3: the agent does not know which tool exists, so it discovers it first (step 0)

```text
Step 1: find a tool to look up earlier conclusions
> search_tools(query="search memory previous findings", limit=2)
< {"matches_found": 2, "tools": [
    {"name": "memory_search", "category": "shared_memory", "relevance_score": 9.0,
     "quick_parameters": {"query": "string (required)", "scope": "...", "namespace": "...", "limit": "integer (default: 5)"}, ...},
    {"name": "search_source", "relevance_score": 4.5, ...}]}
  -> Pick `memory_search` (highest score, and it is the memory lookup). `search_source` searches the code, not memory.

Step 2: fetch the detailed schema, only when exact types and defaults are needed
> get_tool_schema(tool_name="memory_search")
< {"status": "success", "tool_name": "memory_search", "parameters_summary": {...}, "schema": { ...full JSON schema... }}

Step 3: call exactly that tool, with no tokens spent on the schemas of tools it never uses
> memory_search(query="refresh token", scope="project", limit=5)
```

An example for reading code: `search_tools(query="find callers and impact analysis", limit=3)` returns `get_impact_slice` (5.0), `find_symbols` (4.5) and `search_source` (3.5). `get_impact_slice` has `prerequisites: ["find_symbols"]`, so the agent calls `find_symbols` first to get a `symbol_id`, then `get_impact_slice`.

> **Note:** `search_tools` matches on keywords (tool name, tags, summary), not on meaning. A natural sentence such as "save finding for other agents" may not return the right tool; use words close to tool names (`memory save checkpoint`, `memory lock`). The scores come from the current `TOOL_CATALOG` and can change when the catalog changes.

### Example 4: compress large context with `sample_summarize` then store in memory

When encountering an overly long source file, traceback log, or large dependency packet, instead of dumping thousands of raw lines into the agent context or SQLite memory, the agent calls `sample_summarize` for structured compression (preserving technical constraints and verbatim quotes).

```text
Step 1: compress the large code block or log
> sample_summarize(
    text="class PaymentGateway:\n    def process(self, amount, currency):\n        if amount <= 0:\n            raise ValueError('Invalid amount')\n        ...",
    intent="Analyze payment transaction constraints and error handling",
    max_tokens=512,
    target_symbols=["PaymentGateway.process"]
  )
< {
    "backend": "ollama_gpu",
    "engine": "qwen2.5-coder:7b-instruct-q4_K_M",
    "status": "success",
    "latency_ms": 480,
    "symbol_coverage_rate": 1.0,
    "context_retention_rate": 0.92,
    "data": {
      "intent_alignment": "Validates transaction inputs and handles exceptions.",
      "analyzed_symbols": [
        {
          "name": "PaymentGateway.process",
          "responsibility": "Executes payment transaction with amount validation",
          "critical_constraints": [
            {
              "verbatim_quote": "if amount <= 0: raise ValueError('Invalid amount')",
              "rule": "amount must be greater than 0, otherwise raises ValueError",
              "line": 3
            }
          ],
          "calls_external": [],
          "line_span": [1, 15]
        }
      ],
      "technical_caveats": ["Requires retry handling on network timeout"]
    }
  }
  -> Verified against AST ground truth by guardrails (symbol_coverage_rate: 1.0).

Step 2: store this concise payload in memory for subsequent agent turns
> memory_put(
    key="payment.gateway_rules",
    scope="project",
    namespace="repo:myrepo",
    ttl=604800,
    value={"rules": "amount > 0 required", "symbol": "PaymentGateway.process", "caveat": "no retry yet"}
  )
< {"status": "stored", "scope": "project", "namespace": "repo:myrepo", "key": "payment.gateway_rules", "ttl": 604800, "expires_at": ...}
```

---

## 5. Reasoning Level Selection Guide

The reasoning level does not change the workflow in section 3; it only changes how much hypothesis-building and cross-checking happens. Choose by task complexity:

| Reasoning Level | Recommended Model Tier | Suitable Task Types | Technical Rationale |
| :--- | :--- | :--- | :--- |
| **LOW**<br>*(Minimal Thinking)* | Small, fast models (Haiku-class, Gemini Flash, GPT mini) | • Quick symbol definitions or signature lookup (`find_symbols`)<br>• Index freshness sanity checks (`get_index_status`)<br>• Re-reading a stored conclusion by a known key (`memory_get`)<br>• Local syntax or lint fixes, explaining a short snippet whose location is known | Single-hop factual queries where the tool answer supplies exact truth immediately. |
| **MEDIUM**<br>*(Default Thinking)* | Standard models (Sonnet-class, Gemini Pro, standard GPT) | • Scoped feature implementations (1-2 modules)<br>• Internal refactoring preserving public interfaces<br>• Business-logic bug fixes combining `memory_search`, `inspect_symbol` and `get_impact_slice`<br>• Writing unit tests for target symbols | Requires synthesizing facts across 2-4 tool turns and checking memory against the code. |
| **HIGH**<br>*(Deep Reasoning)* | Deep-reasoning models (Opus-class or extended thinking, OpenAI o-series, DeepSeek R1) | • Non-deterministic bug hunting (race conditions, async deadlocks)<br>• System-wide architecture overhauls with large fan-out (`get_module_dependents`)<br>• Coordinating several agents on one repository (`memory_lock`, `memory_consolidate`)<br>• Critical security audits, complex algorithm or protocol design with trade-off analysis | Requires multi-branch hypothesis generation, constraint checking, and deep graph traversal. |
