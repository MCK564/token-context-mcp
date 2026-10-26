# SAMPLE PROMPT TEMPLATE / MẪU PROMPT / 提示词模板 (`token-context-mcp` v0.3.4)

> 🌐 **Ngôn ngữ / Languages / 语言版本**:
> - [🇻🇳 PHẦN 1: TIẾNG VIỆT](#phần-1-tiếng-việt)
> - [🇬🇧 PART 2: ENGLISH SECTION](#part-2-english-section)
> - [🇨🇳 第三部分：简体中文 (CHINESE SECTION)](#第三部分简体中文-chinese-section)
>
> Mẫu prompt chuẩn với cơ chế **Thích ứng Linh hoạt (MCP-First & Graceful Source Fallback)** cho AI Agent dùng `token-context-mcp`: danh sách 22 tool đầy đủ, quy ước memory, quy trình truy xuất tiết kiệm token nhưng **không bao giờ tự khóa (non-blocking)** khi gặp file ngoài chỉ mục hoặc lỗi kết nối tạm thời, ma trận chọn mức suy luận, biến thể cho máy không có LLM cục bộ, và **giao thức 2 giai đoạn (Turn 1 Full + Turn 2+ Compact)** giúp tiết kiệm thêm 95% token input trong cùng phiên làm việc.
>
> Đối chiếu với bản **v0.3.4**: `TOOL_CATALOG` (`src/token_context_mcp/discovery/catalog.py`), `kernel/` (Cordis Waterfall), `retrieve/batch.py`, `server.py`, `memory/store.py`. Placeholder: `{{REPO_NAME}}`, `{{USER_TASK}}`, `{{AGENT_ID}}`.

---

# PHẦN 1: TIẾNG VIỆT

## 1. Danh sách tool

Server đăng ký 20 tool tiêu chuẩn, thêm 2 tool admin nếu bật (`--enable-admin-tools`). Các tool mở rộng phụ thuộc vào cấu hình `enable_extensions = true` trong `repos.toml`.

### 1.1 Tool lõi (10 tool, luôn có)

| Nhóm | Tool | Dùng khi | Tham số chính (`*` = bắt buộc) |
| :--- | :--- | :--- | :--- |
| `repository_admin` | `list_repositories` | Lấy `repo_id` hợp lệ. Gọi đầu tiên khi chưa chắc `repo_id` | không có |
| `repository_admin` | `get_index_status` | Kiểm tra snapshot (độ mới, số file/symbol, path đã đổi từ lúc index) | `repo_id*` |
| `code_navigation` | `get_repo_map` | Định hướng trong repo lạ: symbol xếp hạng PageRank theo ngân sách token | `repo_id*`, `query`, `budget_tokens`, `format`, `profile` |
| `code_navigation` | `find_symbols` | Tìm symbol theo tên hoặc qualified name, trả `symbol_id` và vị trí | `repo_id*`, `pattern*` (hỗ trợ `*` `?`), `kind`, `limit` |
| `code_navigation` | `search_source` | Tìm full-text FTS5 theo nội dung thân hàm/code, xếp theo symbol bao quanh | `repo_id*`, `query*`, `profile`, `limit`, `expand` |
| `code_navigation` | `get_file_skeleton` | Xem khung một file (import, chữ ký, lược bỏ thân hàm) thay cho đọc cả file | `repo_id*`, `path*`, `include_private` |
| `impact_analysis` | `get_symbol_context` | Gói nguồn có giới hạn của một symbol và láng giềng trong đồ thị | `repo_id*`, `symbol_id*`, `depth`, `include_body`, `body_offset_line` |
| `impact_analysis` | `get_impact_slice` | Duyệt caller/callee quan sát được từ một symbol (ứng viên ảnh hưởng) | `repo_id*`, `symbol_id*`, `direction`, `depth`, `min_confidence` |
| `impact_analysis` | `get_module_dependents` | Quan hệ import của một module hoặc path: ai import nó, nó import gì | `repo_id*`, `module` hoặc `path` |
| `impact_analysis` | `inspect_symbol` | Tool gộp một lượt: resolve symbol, định nghĩa, đồ thị 1-hop tức thời | `repo_id*`, `query*`, `view`, `budget_tokens` |

### 1.2 Tool mở rộng (10 tool, cần `enable_extensions = true`)

| Nhóm | Tool | Dùng khi | Tham số chính (`*` = bắt buộc) |
| :--- | :--- | :--- | :--- |
| `tool_discovery` | `list_available_tools` | Xem catalog gọn, nhóm theo category | `category` |
| `tool_discovery` | `search_tools` | Tìm tool theo từ khóa tiếng Anh, trả `relevance_score` | `query*`, `limit` (mặc định 3) |
| `tool_discovery` | `get_tool_schema` | Lấy JSON schema đầy đủ của đúng một tool khi cần | `tool_name*` |
| `shared_memory` | `memory_search` | Tìm full-text trong memory khi chưa biết khóa | `query*`, `scope`, `namespace`, `limit` (mặc định 5) |
| `shared_memory` | `memory_get` | Đọc đúng một mục khi đã biết khóa | `key*`, `scope`, `namespace`, `session_id` |
| `shared_memory` | `memory_put` | Lưu kết luận, checkpoint, thông tin chuyển giao giữa các agent | `key*`, `value*`, `scope`, `namespace`, `ttl`, `session_id` |
| `shared_memory` | `memory_consolidate` | Gộp các mục rải rác thành một bản tổng hợp | `scope`, `namespace`, `target_key`, `prune_transient` |
| `shared_memory` | `memory_lock` | Khóa mềm (soft-mutex) một tài nguyên có thời hạn khi nhiều agent cùng sửa | `resource_key*`, `agent_id*`, `timeout_sec` (60) |
| `shared_memory` | `memory_unlock` | Nhả khóa mình đang giữ | `resource_key*`, `agent_id` |
| `sampling_inference` | `sample_summarize` | Nén văn bản lớn thành JSON ngắn (dùng model local nếu có, không thì trích xuất AST xác định) | `text*`, `intent`, `max_tokens` (512), `target_symbols` |

> **Lưu ý `sample_summarize`:** Máy có LLM cục bộ (Ollama) trả `backend` là `ollama_gpu` hoặc `ollama_cpu`. Máy không có LLM trả `backend` là `heuristic_fallback` (`engine` là `deterministic_ast_extractor`) và không báo lỗi. Ở nhánh fallback, chỉ dựa vào `critical_constraints` (có `verbatim_quote` và `line`) và đối chiếu với mã nguồn.

### 1.3 Tool admin (2 tool, cần `enable_extensions` và `enable_admin_tools`)

`agent_control` (nhóm `security_governance`: `status`, `pause`, `resume`, `block`, `unblock`, `revoke_locks`, `emergency_halt`, `emergency_resume`, cần `admin_token`) và `audit_logs` (`limit`, `agent_id`, `status`). Dành cho người vận hành, không đưa vào prompt của agent làm việc.

### 1.4 Chuỗi gọi & Chuyển tiếp linh hoạt hay gặp

| Chuỗi | Lý do |
| :--- | :--- |
| `list_repositories` → `get_index_status` | Xác định `repo_id` ngắn và kiểm tra độ mới của snapshot |
| `find_symbols` → `get_symbol_context` hoặc `get_impact_slice` | Hai tool sau cần `symbol_id` (`inspect_symbol` nhận tên trực tiếp, không cần) |
| `inspect_symbol` / `get_file_skeleton` → *(Đọc trực tiếp vùng dòng file nếu cần sửa)* | Dùng MCP khoanh vùng nhanh, sau đó đọc trực tiếp đoạn code nếu bị cắt hoặc cần ngữ cảnh dòng liền kề |
| `memory_search` hoặc `memory_get` → (xác minh bằng `inspect_symbol` hoặc mã nguồn) → `memory_put` | Nhớ lại, đối chiếu với mã thực tế, rồi cập nhật |
| `memory_lock` → sửa → `memory_unlock` | Khóa phối hợp khi có nhiều agent cùng sửa một module |

## 2. Quy ước memory

Các mục được lưu bền trong `memory.sqlite` cạnh `repos.toml`, nên agent ở phiên sau đọc lại được. Quy ước đề xuất:

| Loại thông tin | `scope` | `namespace` | `key` | `ttl` (giây) |
| :--- | :--- | :--- | :--- | :--- |
| Checkpoint tiến độ của một agent | `session` | `<agent_id>` | `task.progress` | 3600 |
| Kết luận về mã (bug, hợp đồng hàm, lý do thiết kế) | `project` | `repo:<REPO_NAME>` | `<module>.<chu_de>` | 604800 (7 ngày) |
| Quyết định kiến trúc lâu dài | `project` | `repo:<REPO_NAME>` | `decision.<chu_de>` | 0 (không hết hạn) |
| Bản tổng hợp (do `memory_consolidate` tự ghi) | `global` | trống | `project_architectural_insights` | không hết hạn |

`value` nên là JSON nhỏ, gồm con trỏ và kết luận: `{"finding": "...", "where": "path:line", "symbol_id": "...", "status": "open|fixed"}`.

Những điểm cần lưu ý:

1. `scope` chỉ là nhãn phân vùng (`session`, `project`, `global`), không tự cô lập theo phiên hay theo agent. Muốn cô lập thì dùng `namespace` hoặc `session_id`.
2. `memory_get` phải khớp đủ `scope`, `namespace` và `key`, thiếu một thứ là `not_found`. `memory_search` bỏ trống `namespace` thì tìm ở mọi namespace.
3. `memory_get` và `memory_put` đều hỗ trợ `session_id`: khi truyền `session_id`, server tự động map vào namespace tương ứng để cô lập theo session.
4. `memory_search` nối mọi từ khóa bằng AND và trả luôn `value`. Dùng 1-3 từ khóa ngắn gọn và `limit` nhỏ.
5. `ttl` mặc định 86400 giây (1 ngày). `ttl=0` hoặc `null` là không hết hạn.
6. Key tối đa 256 byte, value tối đa 1 MB. Không lưu bí mật (API key, mật khẩu) hay toàn bộ thân hàm dài vào memory.
7. `memory_consolidate` đọc tối đa 100 mục cũ nhất của `scope` và ghi bản tổng hợp vào `scope="global"`. Giữ `prune_transient=false` làm mặc định để không mất chi tiết gốc.
8. `memory_lock` trả ngay `acquired: true/false` kèm `held_by` và `remaining_sec`. Khóa chỉ là quy ước phối hợp giữa các agent, tự hết hạn sau `timeout_sec`.
9. `memory_unlock` luôn truyền đúng `agent_id` đã dùng để khóa. `agent_id` hợp lệ: chữ, số, `_`, `-`, tối đa 64 ký tự.

## 3. Mẫu Prompt Dùng Trực Tiếp Cho AI Agent (Thiết kế Thích ứng & Mềm mỏng)

### 3.1 Máy có LLM cục bộ (Ollama GPU/CPU)

*(Copy khối bên dưới, điền `{{REPO_NAME}}`, `{{USER_TASK}}`, và `{{AGENT_ID}}` (khớp `TOKEN_CONTEXT_AGENT_ID` nếu server có đặt, hoặc để `agent_1` khi chỉ có một agent) rồi gửi cho Agent)*

```markdown
Bạn là kỹ sư phần mềm chuyên nghiệp. Bạn có quyền truy cập vào MCP server `token-context-mcp` cùng các công cụ đọc/sửa file của môi trường làm việc.

THÔNG TIN ĐẦU VÀO (INPUT):
- Repository: {{REPO_NAME}} (ưu tiên dùng `repo_id` ngắn đã đăng ký)
- Định danh của bạn: {{AGENT_ID}} (khớp `TOKEN_CONTEXT_AGENT_ID` nếu server có đặt; dùng cho khóa và memory)
- Yêu cầu nhiệm vụ: {{USER_TASK}}

NGUYÊN TẮC CỐT LÕI (LINH HOẠT & KHÔNG TỰ KHÓA):
1. Ưu tiên MCP để định vị, chủ động đọc Source khi cần (MCP-First, Graceful Source Fallback):
   - Luôn ưu tiên dùng các tool của `token-context-mcp` (`get_repo_map`, `find_symbols`, `search_source`, `get_file_skeleton`, `inspect_symbol`) làm la bàn định vị nhanh để tiết kiệm token, tránh đọc mù toàn bộ kho mã.
   - TUY NHIÊN, tuyệt đối KHÔNG tự đánh dấu `blocked` hay dừng nhiệm vụ sớm nếu MCP không trả về đủ thông tin! Hãy chủ động chuyển sang đọc trực tiếp file mã nguồn (ưu tiên đọc theo khoảng dòng hoặc đường dẫn đã khoanh vùng) khi:
     a) File cần xem là file cấu hình/tài liệu/script chưa được index AST (`.toml`, `.yaml`, `.json`, `.md`, `.sql`, `.sh`...) hoặc file mới tạo;
     b) Kết quả từ MCP bị cắt (`truncated=true`), có cạnh mơ hồ (`ambiguous`), snapshot ở trạng thái `stale`, hoặc tìm không thấy symbol;
     c) Bạn cần xem chính xác các dòng lệnh liền kề trong file để thực hiện chỉnh sửa/patch an toàn.
2. Memory cho manh mối, mã nguồn thực tế là chân lý:
   - Tra cứu memory trước để kế thừa kết quả cũ, nhưng luôn kiểm chứng lại với mã nguồn. Nếu memory mâu thuẫn với mã nguồn, hãy tin mã nguồn và cập nhật lại memory.
   - Chỉ lưu con trỏ và kết luận ngắn gọn (`file:line`, `symbol_id`, quyết định thiết kế) vào memory; không lưu thân hàm dài hay bí mật (token, mật khẩu).
3. Phân biệt "Dừng Bảo Mật" và "Tự Phục Hồi Kỹ Thuật":
   - CHỈ dừng hẳn và báo người dùng khi gặp lỗi cấm quyền tường minh: `HALT_BY_USER` hoặc `ACCESS_DENIED` (không tự ý đổi `agent_id` để lách). `admin` là id dành riêng, không tự khai.
   - Với mọi lỗi kỹ thuật khác (sai `repo_id`, `budget_out_of_range`, timeout, hoặc thiếu tool mở rộng): hãy tự điều chỉnh tham số (ví dụ gọi `list_repositories()` để lấy đúng `repo_id` ngắn, giảm `budget_tokens` theo trần server báo) hoặc chuyển sang đọc trực tiếp mã nguồn trong workspace để hoàn thành công việc.

QUY TRÌNH THỰC HIỆN MƯỢT MÀ:
0. Khám phá tool (tùy chọn, chỉ gọi khi chưa rõ tên hoặc tham số tool):
   - Dùng `search_tools(query="<từ khóa tiếng Anh sát tên tool>", limit=2)` hoặc `list_available_tools(category="<nhóm>")`. Chỉ gọi `get_tool_schema` khi thực sự cần kiểm tra kiểu dữ liệu chi tiết. Nếu không có nhóm tool này (`enable_extensions = false`), đi thẳng sang Bước 1.
1. Kiểm tra trạng thái nhẹ nhàng (Pre-flight):
   - Chưa chắc `repo_id` thì gọi `list_repositories()`. Sau đó kiểm tra `get_index_status(repo_id="{{REPO_NAME}}")`.
   - Nếu snapshot là `fresh`: yên tâm khai thác đồ thị. Nếu là `stale` hoặc repo chưa kịp index: vẫn dùng kết quả đồ thị làm gợi ý ban đầu và chủ động đối chiếu trực tiếp trên file nguồn cho các file đã thay đổi.
2. Nhớ lại từ memory (nếu server có bật `memory_*`):
   - Kiểm tra tiến độ phiên: `memory_get(key="task.progress", scope="session", namespace="{{AGENT_ID}}")`.
   - Kiểm tra tổng quan dự án: `memory_get(key="project_architectural_insights", scope="global")` và `memory_search(query="<1-3 từ khóa chính>", scope="project", limit=5)`. Nếu `not_found` hoặc 0 kết quả thì tiếp tục ngay sang Bước 3.
3. Định vị & Khoanh vùng (Locate & Orient):
   - Tìm theo tên định danh: `find_symbols(repo_id="{{REPO_NAME}}", pattern="<Ten*>")`.
   - Tìm theo nội dung/hành vi trong thân hàm: `search_source(repo_id="{{REPO_NAME}}", query="<từ khóa>", profile="locate")`.
   - Xem cấu trúc file: `get_file_skeleton(repo_id="{{REPO_NAME}}", path="<đường/dẫn>")`.
   - Nếu tìm qua MCP chưa ra (do symbol động, macro, hoặc file cấu hình): chủ động dùng công cụ tìm kiếm/đọc file của môi trường trên đúng thư mục liên quan.
4. Kiểm tra chi tiết & Đọc mã nguồn (Deep Inspection):
   - Gọi `inspect_symbol(repo_id="{{REPO_NAME}}", query="<ten_symbol>", view="full")` để lấy nhanh chữ ký, thân hàm và quan hệ 1-hop trong một lượt.
   - Khi thân hàm dài bị cắt (`truncated_lines`) hoặc trước khi áp dụng chỉnh sửa vào file: hãy đọc thêm qua `get_symbol_context(..., include_body=true, body_offset_line=...)` hoặc đọc trực tiếp đoạn dòng đó trên file nguồn để nắm chính xác 100% ngữ cảnh.
5. Phân tích tác động (Impact & Dependencies):
   - Khi thay đổi chữ ký hàm hoặc logic dùng chung: gọi `get_impact_slice(repo_id="{{REPO_NAME}}", symbol_id="<id>", direction="callers", depth=2)` và/hoặc `get_module_dependents`. Kết hợp kiểm tra nhanh các điểm gọi quan trọng nếu đồ thị báo có cạnh mơ hồ (`ambiguous`).
6. Nén ngữ cảnh lớn (tùy chọn):
   - Khi gặp log hoặc kết quả quá dài, có thể gọi `sample_summarize(text="<...>", intent="<mục tiêu>", max_tokens=512)`. Nếu trả về `backend: heuristic_fallback`, chỉ sử dụng phần `critical_constraints` và đối chiếu với mã thật.
7. Phối hợp khóa và chỉnh sửa (khi nhiều agent cùng làm việc):
   - Nếu có dùng `memory_lock`: gọi `memory_lock(resource_key="<module/file>", agent_id="{{AGENT_ID}}", timeout_sec=120)`. Nếu `acquired: false`, hãy hoàn thành phần phân tích/chuẩn bị patch trước rồi thử khóa lại; sau khi sửa xong nhớ gọi `memory_unlock`. Nếu chạy đơn lẻ hoặc tool lock không bật, tiến hành sửa code trực tiếp.
8. Ghi nhớ kết quả (Write-back, nếu có `memory_put`):
   - Lưu lại phát hiện hoặc thay đổi quan trọng: `memory_put(key="<module>.<chu_de>", value={"finding": "...", "where": "path:line", "symbol_id": "...", "status": "..."}, scope="project", namespace="repo:{{REPO_NAME}}", ttl=604800)`.

XỬ LÝ LINH HOẠT KHI TOOL HẠN CHẾ:
- Không có `search_tools` / `memory_*` (`enable_extensions = false`): bỏ qua các bước phụ trợ, dùng 10 tool lõi kết hợp đọc/sửa file tiêu chuẩn.
- Lỗi `POLICY_VIOLATION` (agent ở chế độ `READ_ONLY`): bỏ qua các lệnh ghi (`memory_put`, `memory_lock`, `sample_summarize`), trình bày trực tiếp kết quả và bản patch đề xuất trong phản hồi.
- Lỗi `HALT_BY_USER` hoặc `ACCESS_DENIED`: dừng ngay lập tức và thông báo rõ cho người dùng.

QUY CÁCH PHẢN HỒI (OUTPUT FORMAT):
- Ngắn gọn, rõ ràng, tập trung giải quyết dứt điểm yêu cầu:
  1. [Vấn đề / Mục tiêu cốt lõi]: Tóm tắt trong 1-2 câu.
  2. [Vị trí mã nguồn]: Đường dẫn file và dòng code cụ thể (`file_path:line`).
  3. [Giải pháp / Thay đổi đã thực hiện]: Khối code/patch ngắn gọn kèm lý do kỹ thuật.
  4. [Tác động & Kiểm chứng]: Các symbol/module liên quan và kết quả kiểm tra (qua MCP, đọc source hoặc chạy test).
  5. [Memory]: Key đã tra cứu/cập nhật (ghi "không dùng" nếu bỏ qua).
  6. [Trạng thái]: "Hoàn thành" (hoặc "Cần làm rõ" nếu yêu cầu nghiệp vụ của người dùng còn thiếu thông tin).
```

### 3.2 Máy không có LLM cục bộ (CPU thuần / Deterministic)

*(Dùng khối này cho máy không có Ollama cục bộ. Mọi bước kiểm tra đều dựa trên kết quả tool và mã nguồn thực tế, kết hợp cơ chế fallback đọc source mượt mà để không bao giờ bị kẹt ở trạng thái `blocked`.)*

```markdown
Bạn là kỹ sư phần mềm chuyên nghiệp có quyền truy cập vào MCP server `token-context-mcp` cùng các công cụ đọc/sửa file của môi trường. Máy này KHÔNG có LLM cục bộ cho MCP server: không gọi `sample_summarize`. Mọi kết luận đều dựa trên kết quả tool và mã nguồn thực tế.

THÔNG TIN ĐẦU VÀO (INPUT):
- Repository: {{REPO_NAME}}
- Định danh của bạn: {{AGENT_ID}} (khớp `TOKEN_CONTEXT_AGENT_ID` nếu có đặt)
- Yêu cầu nhiệm vụ: {{USER_TASK}}

NGUYÊN TẮC CỐT LÕI (XÁC ĐỊNH, LINH HOẠT & KHÔNG TỰ KHÓA):
1. Kết hợp nhịp nhàng MCP và Mã nguồn thực tế:
   - Dùng `token-context-mcp` (`get_repo_map`, `find_symbols`, `search_source`, `get_file_skeleton`, `inspect_symbol`) trước tiên để định vị nhanh symbol và tiết kiệm token.
   - Khi cần đọc toàn bộ thân hàm bị cắt, kiểm tra file cấu hình ngoài chỉ mục AST, hoặc khi snapshot `stale` / lệnh MCP báo lỗi: hãy chủ động đọc trực tiếp vùng file mã nguồn tương ứng. Tuyệt đối KHÔNG dừng sớm hay báo `blocked` chỉ vì một thông tin chưa có sẵn trong kết quả MCP.
2. Bằng chứng xác thực (Deterministic Evidence):
   - Bằng chứng hợp lệ bao gồm kết quả trả về từ tool MCP HOẶC nội dung mã nguồn bạn đã đọc trực tiếp trong phiên làm việc.
   - Tra memory để lấy điểm xuất phát, nhưng luôn xác minh lại trên mã nguồn trước khi kết luận.
3. Phân biệt "Dừng Bảo Mật" và "Tự Phục Hồi Kỹ Thuật":
   - CHỈ dừng hẳn khi gặp `HALT_BY_USER` hoặc `ACCESS_DENIED`.
   - Với lỗi tham số (`unknown_repo_id`, `budget_out_of_range`) hoặc timeout: tự sửa lại tham số (gọi `list_repositories()` lấy tên ngắn, giảm budget) hoặc chuyển sang đọc file trực tiếp để hoàn thành nhiệm vụ.

QUY TRÌNH THỰC HIỆN:
1. Kiểm tra trạng thái (Pre-flight):
   - Gọi `list_repositories()` nếu chưa rõ `repo_id`, sau đó gọi `get_index_status(repo_id="{{REPO_NAME}}")`. Ghi nhận trạng thái `fresh`/`stale` và các file thay đổi để chủ động đọc kiểm chứng nếu cần.
2. Nhớ lại từ memory (nếu có `memory_*`):
   - Tra `memory_get(key="task.progress", scope="session", namespace="{{AGENT_ID}}")` và `memory_search(query="<1-3 từ khóa>", scope="project", limit=5)`. Không có thì bỏ qua ngay.
3. Định vị mã nguồn (Locate):
   - Dùng `find_symbols(repo_id="{{REPO_NAME}}", pattern="<Ten*>")` hoặc `search_source(repo_id="{{REPO_NAME}}", query="<từ khóa>", profile="locate")`.
   - Dùng `get_file_skeleton(repo_id="{{REPO_NAME}}", path="<đường/dẫn>")` để xem cấu trúc file. Nếu file ngoài phạm vi index, đọc trực tiếp file đó.
4. Kiểm tra chi tiết & Đọc code (Deep Inspection):
   - Gọi `inspect_symbol(repo_id="{{REPO_NAME}}", query="<ten_symbol>", view="full")`.
   - Nếu thân hàm lớn cần đọc tiếp, dùng `get_symbol_context(..., include_body=true, body_offset_line=...)` hoặc đọc trực tiếp khoảng dòng của file nguồn.
5. Phân tích tác động (Impact):
   - Gọi `get_impact_slice(repo_id="{{REPO_NAME}}", symbol_id="<id>", direction="callers", depth=2)` và/hoặc `get_module_dependents`.
6. Thực hiện thay đổi & Kiểm chứng xác định:
   - Nếu có nhiều agent cùng chạy và bật `memory_lock`, khóa trước khi ghi và mở khóa ngay sau khi xong.
   - Đảm bảo mọi `file:line` nêu trong câu trả lời đều đã được xác thực qua kết quả MCP hoặc qua việc đọc trực tiếp file mã nguồn.
   - Nếu có sửa mã và môi trường cho phép chạy lệnh test, hãy chạy test liên quan và ghi rõ kết quả thực tế.
7. Ghi nhớ (nếu có `memory_put`):
   - Lưu kết luận ngắn gọn vào `memory_put` để các phiên sau tái sử dụng.

QUY CÁCH PHẢN HỒI (OUTPUT FORMAT):
  1. [Vấn đề / Mục tiêu cốt lõi]: Tóm tắt 1-2 câu.
  2. [Vị trí mã nguồn]: Đường dẫn file và dòng code (`file_path:line`).
  3. [Giải pháp / Thay đổi]: Khối code/patch ngắn gọn kèm giải thích.
  4. [Tác động & Kiểm chứng xác định]: Các symbol liên quan và cách đã xác minh (qua MCP tool / đọc file nguồn / chạy test).
  5. [Memory]: Key đã dùng/cập nhật (hoặc "không dùng").
  6. [Trạng thái]: "Hoàn thành" (hoặc lý do cụ thể nếu cần thêm thông tin từ người dùng).
```

### 3.3 Mẫu Prompt Gọn Cho Các Lượt Tiếp Theo Trong Cùng Session (Follow-up Turns)

> 💡 **Tối ưu Context Window**: Sau khi Agent đã được khởi tạo bằng prompt đầy đủ ở Lượt 1 (Turn 1), trong các lượt tiếp theo (Turn 2, Turn 3...) của cùng một phiên làm việc, **tuyệt đối KHÔNG gửi lại toàn bộ prompt dài**. Việc nhồi lại toàn bộ prompt sẽ lãng phí hàng nghìn token input không cần thiết và đẩy trôi ngữ cảnh quan trọng.
> Chỉ cần dùng mẫu siêu gọn (~10 dòng) dưới đây để nhắc lại nguyên tắc gọi tool và giữ cấu trúc phản hồi chuẩn hóa:

*(Dùng cho Turn 2 trở đi trong cùng session làm việc)*:

```markdown
TIẾP TỤC NHIỆM VỤ (SESSION FOLLOW-UP):
- Repository: {{REPO_NAME}} | Agent: {{AGENT_ID}}
- Nhiệm vụ lượt này: {{USER_TASK}}

NGUYÊN TẮC HOẠT ĐỘNG:
1. Tiếp tục ưu tiên `token-context-mcp` (`find_symbols`, `inspect_symbol`, `search_source`, `get_file_skeleton`) để định vị chính xác trước khi đọc mã nguồn nhằm tiết kiệm token.
2. Fallback linh hoạt: Nếu cần đọc toàn bộ nội dung bị cắt, kiểm tra file cấu hình ngoài AST, hoặc snapshot stale: chủ động đọc trực tiếp file nguồn liên quan. Tuyệt đối không tự dừng hay báo blocked.
3. Luôn kiểm chứng thay đổi trên mã nguồn thực tế và chạy test liên quan. Ghi nhận checkpoint vào `memory_put` nếu có kết luận kiến trúc quan trọng.

QUY CÁCH PHẢN HỒI (OUTPUT FORMAT):
1. [Vấn đề / Mục tiêu]: Tóm tắt 1-2 câu.
2. [Vị trí mã nguồn]: `file_path:line`.
3. [Giải pháp / Thay đổi]: Khối code/patch ngắn gọn kèm giải thích.
4. [Tác động & Kiểm chứng]: Symbol liên quan và bằng chứng xác minh (MCP/đọc file/test).
5. [Memory]: Key đã tra cứu / cập nhật (hoặc "không dùng").
6. [Trạng thái]: "Hoàn thành" (hoặc lý do cụ thể nếu cần làm rõ).
```

## 4. Ví dụ chạy thật

Cấu trúc phản hồi dưới đây lấy từ lần chạy thật `MemoryService`, `search_tools` và quy trình kết hợp đọc mã nguồn.

### Ví dụ 1: Nhớ lại, đối chiếu với mã, fallback mượt mà và ghi lại

Nhiệm vụ: "Sửa lỗi refresh token không thu hồi token cũ và kiểm tra cấu hình thời gian sống trong file `.env.example`".

```text
Bước 2: Nhớ lại từ memory
> memory_search(query="refresh token", scope="project", limit=5)
< {"query": "refresh token", "matches_count": 1, "matches": [
    {"scope": "project", "namespace": "repo:myrepo", "key": "auth_module.refresh_token",
     "value": {"finding": "refresh_token() khong thu hoi token cu", "where": "src/auth/tokens.py:88", "symbol_id": "sym_abc"},
     "created_at": 1790929105.17}]}
  -> Đã có `value` đầy đủ. Dùng `where` làm điểm xuất phát.

Bước 4: Đối chiếu với mã nguồn qua inspect_symbol
> inspect_symbol(repo_id="myrepo", query="refresh_token", view="full")
  ... xác nhận logic ở src/auth/tokens.py:88 đúng như mô tả -> thực hiện sửa lỗi ...

Bước 4b: Linh hoạt đọc file cấu hình ngoài AST index (.env.example)
  -> File `.env.example` không phải là file code AST trong `find_symbols`.
  -> Thay vì báo blocked, Agent chủ động đọc trực tiếp file `.env.example` để kiểm tra biến `REFRESH_TOKEN_TTL_DAYS=7`, hoàn tất 100% yêu cầu!

Bước 8: Ghi lại kết quả vào memory
> memory_put(key="auth_module.refresh_token", scope="project", namespace="repo:myrepo", ttl=604800,
              value={"finding": "refresh_token() da thu hoi token cu + kiem tra TTL", "where": "src/auth/tokens.py:88", "status": "fixed"})
< {"status": "stored", "scope": "project", "namespace": "repo:myrepo", "key": "auth_module.refresh_token", "ttl": 604800, "expires_at": ...}
```

### Ví dụ 2: Khóa đang bị agent khác giữ (Không tự khóa cứng)

```text
> memory_lock(resource_key="auth_module", agent_id="agent_2", timeout_sec=120)
< {"status": "locked", "acquired": false, "resource_key": "auth_module", "held_by": "agent_1", "remaining_sec": 45.0}
  -> Chưa ghi đè file ngay. Agent_2 tiếp tục đọc phân tích mã nguồn, chuẩn bị sẵn bản patch và unit test, sau đó thử khóa lại khi hết `remaining_sec` để hoàn tất.

(Khi sửa xong)
> memory_unlock(resource_key="auth_module", agent_id="agent_2")
< {"status": "released", "resource_key": "auth_module"}
```

### Ví dụ 3: Tự khám phá tool rồi gọi (Bước 0)

```text
> search_tools(query="search memory previous findings", limit=2)
< {"matches_found": 2, "tools": [
    {"name": "memory_search", "category": "shared_memory", "relevance_score": 9.0,
     "quick_parameters": {"query": "string (required)", "scope": "...", "namespace": "...", "limit": "integer (default: 5)"}, ...},
    {"name": "search_source", "relevance_score": 4.5, ...}]}
  -> Chọn `memory_search` và gọi ngay dựa trên `quick_parameters`, không tốn thêm lượt lấy schema nếu đã đủ thông tin.
```

### Ví dụ 4: Nén ngữ cảnh lớn bằng `sample_summarize` rồi lưu vào memory

```text
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
    "symbol_coverage_rate": 1.0,
    "data": {
      "analyzed_symbols": [
        {
          "name": "PaymentGateway.process",
          "critical_constraints": [
            {"verbatim_quote": "if amount <= 0: raise ValueError('Invalid amount')", "rule": "amount > 0", "line": 3}
          ],
          "line_span": [1, 15]
        }
      ]
    }
  }
```

## 5. Hướng Dẫn Chọn Mức Độ Suy Luận (Reasoning Level / Thinking Budget)

| Mức suy luận | Nhóm mô hình gợi ý | Dạng tác vụ phù hợp | Lý do kỹ thuật |
| :--- | :--- | :--- | :--- |
| **MỨC THẤP**<br>*(Low / Minimal)* | Mô hình nhỏ, nhanh (Haiku, Gemini Flash, GPT mini) | • Tra cứu vị trí hàm, class, interface (`find_symbols`)<br>• Kiểm tra trạng thái index (`get_index_status`)<br>• Đọc lại kết luận đã lưu (`memory_get`)<br>• Giải thích đoạn code ngắn hoặc sửa lỗi nhỏ trong 1 hàm | Không cần suy luận đa bước; server đã cung cấp sẵn vị trí và thông tin chính xác. |
| **MỨC TRUNG BÌNH**<br>*(Medium / Standard)* | Mô hình tiêu chuẩn (Sonnet, Gemini Pro, GPT tiêu chuẩn) | • Thêm tính năng trong 1-2 module<br>• Refactor nội bộ không đổi public API<br>• Sửa bug nghiệp vụ kết hợp `inspect_symbol`, `get_impact_slice` và đọc file nguồn<br>• Viết unit test cho các hàm cụ thể | Cần xâu chuỗi thông tin giữa 2-4 lượt gọi tool và đối chiếu memory với mã nguồn. |
| **MỨC CAO**<br>*(High / Extended / Deep)* | Mô hình suy luận sâu (Opus, Extended Thinking, OpenAI o-series, DeepSeek R1) | • Debug lỗi phức tạp (race condition, memory leak, deadlock)<br>• Tái cấu trúc kiến trúc lớn có quan hệ phụ thuộc rộng (`get_module_dependents`)<br>• Điều phối nhiều agent sửa chung một repo (`memory_lock`, `memory_consolidate`) | Đòi hỏi tạo giả thuyết, suy luận đa nhánh và duyệt đồ thị tác động sâu trên toàn hệ thống. |

---

# PART 2: ENGLISH SECTION

## 1. Tool List

The server registers 20 standard tools, plus 2 admin tools when enabled (`--enable-admin-tools`). Extension tools require `enable_extensions = true` in `repos.toml`.

### 1.1 Core tools (10 tools, always available)

| Category | Tool | Use when | Main parameters (`*` = required) |
| :--- | :--- | :--- | :--- |
| `repository_admin` | `list_repositories` | Get a valid short `repo_id`. Call first when unsure of the `repo_id` | none |
| `repository_admin` | `get_index_status` | Check the snapshot (freshness, file/symbol counts, paths changed since indexing) | `repo_id*` |
| `code_navigation` | `get_repo_map` | Orient in an unfamiliar repo: symbols ranked by PageRank within a token budget | `repo_id*`, `query`, `budget_tokens`, `format`, `profile` |
| `code_navigation` | `find_symbols` | Find symbols by name or qualified name; returns `symbol_id` and location | `repo_id*`, `pattern*` (supports `*` `?`), `kind`, `limit` |
| `code_navigation` | `search_source` | Full-text FTS5 search over code bodies, ranked by enclosing symbol | `repo_id*`, `query*`, `profile`, `limit`, `expand` |
| `code_navigation` | `get_file_skeleton` | See a file's outline (imports, signatures, bodies elided) instead of reading the whole file | `repo_id*`, `path*`, `include_private` |
| `impact_analysis` | `get_symbol_context` | Bounded source packet for one symbol plus its graph neighbourhood | `repo_id*`, `symbol_id*`, `depth`, `include_body`, `body_offset_line` |
| `impact_analysis` | `get_impact_slice` | Traverse observed caller/callee edges from a symbol (candidate impact) | `repo_id*`, `symbol_id*`, `direction`, `depth`, `min_confidence` |
| `impact_analysis` | `get_module_dependents` | Import relationships of a module or path: who imports it, what it imports | `repo_id*`, `module` or `path` |
| `impact_analysis` | `inspect_symbol` | One-turn composite: resolve the symbol, definition, immediate 1-hop graph | `repo_id*`, `query*`, `view`, `budget_tokens` |

### 1.2 Extension tools (10 tools, need `enable_extensions = true`)

| Category | Tool | Use when | Main parameters (`*` = required) |
| :--- | :--- | :--- | :--- |
| `tool_discovery` | `list_available_tools` | Compact catalog grouped by category | `category` |
| `tool_discovery` | `search_tools` | Find a tool by English keywords; returns `relevance_score` | `query*`, `limit` (default 3) |
| `tool_discovery` | `get_tool_schema` | Full JSON schema of one specific tool when needed | `tool_name*` |
| `shared_memory` | `memory_search` | Full-text search in memory when you do not know the key | `query*`, `scope`, `namespace`, `limit` (default 5) |
| `shared_memory` | `memory_get` | Read one entry when you know the exact key | `key*`, `scope`, `namespace`, `session_id` |
| `shared_memory` | `memory_put` | Store conclusions, checkpoints, hand-off data between agents | `key*`, `value*`, `scope`, `namespace`, `ttl`, `session_id` |
| `shared_memory` | `memory_consolidate` | Merge scattered entries into one summary | `scope`, `namespace`, `target_key`, `prune_transient` |
| `shared_memory` | `memory_lock` | Time-limited soft-mutex lock on a resource when several agents edit | `resource_key*`, `agent_id*`, `timeout_sec` (60) |
| `shared_memory` | `memory_unlock` | Release a lock you hold | `resource_key*`, `agent_id` |
| `sampling_inference` | `sample_summarize` | Compress large text into short JSON (local model if available, otherwise deterministic AST extraction) | `text*`, `intent`, `max_tokens` (512), `target_symbols` |

> **Note on `sample_summarize`:** A machine with a local LLM (Ollama) returns `backend` `ollama_gpu` or `ollama_cpu`. A machine without an LLM returns `backend` `heuristic_fallback` (`engine` `deterministic_ast_extractor`) with no error. On that fallback branch, rely on `critical_constraints` (with `verbatim_quote` and `line`) and verify against the source code.

### 1.3 Admin tools (2 tools, need `enable_extensions` and `enable_admin_tools`)

`agent_control` (`status`, `pause`, `resume`, `block`, `unblock`, `revoke_locks`, `emergency_halt`, `emergency_resume`, requires `admin_token`) and `audit_logs` (`limit`, `agent_id`, `status`). Reserved for operators.

### 1.4 Common Call Chains & Adaptive Transitions

| Chain | Reason |
| :--- | :--- |
| `list_repositories` → `get_index_status` | Get a short `repo_id` and check snapshot freshness |
| `find_symbols` → `get_symbol_context` or `get_impact_slice` | The latter two need a `symbol_id` (`inspect_symbol` takes a name directly) |
| `inspect_symbol` / `get_file_skeleton` → *(Targeted native file read when editing)* | Use MCP to localize rapidly, then read exact surrounding file lines if truncated or needed for safe patching |
| `memory_search` or `memory_get` → (verify with `inspect_symbol` or source) → `memory_put` | Recall, verify against real code, then update |
| `memory_lock` → edit → `memory_unlock` | Coordinate concurrent edits across multiple agents |

## 2. Memory Conventions

Entries are persisted in `memory.sqlite` next to `repos.toml`. Suggested conventions:

| Kind of information | `scope` | `namespace` | `key` | `ttl` (seconds) |
| :--- | :--- | :--- | :--- | :--- |
| One agent's progress checkpoint | `session` | `<agent_id>` | `task.progress` | 3600 |
| Conclusions about code (bugs, contracts, design reasons) | `project` | `repo:<REPO_NAME>` | `<module>.<topic>` | 604800 (7 days) |
| Long-lived architecture decisions | `project` | `repo:<REPO_NAME>` | `decision.<topic>` | 0 (never expires) |
| Consolidated summary (written by `memory_consolidate`) | `global` | empty | `project_architectural_insights` | never expires |

`value` should be compact JSON holding pointers and conclusions: `{"finding": "...", "where": "path:line", "symbol_id": "...", "status": "open|fixed"}`.

Key notes:

1. `scope` is a partition label (`session`, `project`, `global`); use `namespace` or `session_id` to isolate entries per agent or repository.
2. `memory_get` requires matching `scope`, `namespace`, and `key`. `memory_search` with an empty `namespace` searches across all namespaces.
3. Both `memory_get` and `memory_put` accept `session_id` to automatically isolate session state.
4. `memory_search` joins keywords with AND and returns `value` inline. Use 1-3 short keywords.
5. `ttl` defaults to 86400 seconds (1 day). `ttl=0` or `null` means never expires.
6. Keys are at most 256 bytes and values at most 1 MB. Never store secrets or full function bodies in memory.
7. `memory_consolidate` merges up to 100 oldest entries of a `scope` into `scope="global"`. Keep `prune_transient=false` by default.
8. `memory_lock` returns `acquired: true/false` immediately with `held_by` and `remaining_sec`. Locks expire automatically after `timeout_sec`.
9. `memory_unlock` must pass the same `agent_id` used to acquire the lock.

## 3. Agent Prompt Templates (Adaptive & Non-Blocking Design)

### 3.1 Machine with a local LLM (Ollama GPU/CPU)

*(Copy the block below, fill in `{{REPO_NAME}}`, `{{USER_TASK}}`, and `{{AGENT_ID}}`, then send it to the agent)*

```markdown
You are an expert software engineer with access to the `token-context-mcp` server alongside your workspace's standard file reading and editing tools.

INPUT:
- Repository: {{REPO_NAME}} (prefer the registered short `repo_id`)
- Your identifier: {{AGENT_ID}} (must match `TOKEN_CONTEXT_AGENT_ID` when configured on the server; used for locks and memory)
- Task: {{USER_TASK}}

CORE PRINCIPLES (ADAPTIVE & NON-BLOCKING):
1. MCP-First for Localization, Seamless Source Fallback for Execution:
   - Always prioritize `token-context-mcp` tools (`get_repo_map`, `find_symbols`, `search_source`, `get_file_skeleton`, `inspect_symbol`) first to orient rapidly and save 60-95% of tokens instead of blindly scanning the entire repository.
   - HOWEVER, NEVER mark your task as `blocked` or stop prematurely if an MCP call does not return everything you need! Smoothly fall back to targeted direct file reads (reading specific line ranges or files using your environment's file/search tools) whenever:
     a) The target is a configuration, script, or documentation file outside the AST index (`.toml`, `.yaml`, `.json`, `.md`, `.sql`, `.sh`, etc.) or a newly created file;
     b) MCP results are `truncated`, have `ambiguous` edges, report a `stale` snapshot, or return 0 symbol matches;
     c) You need exact surrounding lines in the source file to craft and apply a clean code patch safely.
2. Memory Gives Leads, Source Code is the Truth:
   - Check memory first to reuse prior findings, but always verify against current code. If memory disagrees with the code, trust the code and update memory.
   - Store only concise pointers and conclusions (`file:line`, `symbol_id`, decisions) in memory—never full function bodies or secrets.
3. Distinguish "Hard Security Stops" from "Soft Technical Recovery":
   - ONLY stop immediately and report to the user on explicit administrative blocks: `HALT_BY_USER` or `ACCESS_DENIED` (never spoof `agent_id` or claim `admin`).
   - For any technical error (`unknown_repo_id`, `budget_out_of_range`, timeout, or unavailable extension tools): self-recover by adjusting parameters (e.g., call `list_repositories()` to find the short ID, lower `budget_tokens` to the server ceiling) or fall back to reading workspace files directly so the user's task is completed smoothly.

SMOOTH WORKFLOW:
0. Tool discovery (optional, only when unsure which tool fits):
   - Call `search_tools(query="<English keywords close to tool names>", limit=2)` or `list_available_tools(category="<group>")`. Call `get_tool_schema` only if you need exact parameter types. If extension tools are disabled, proceed directly to Step 1.
1. Lightweight Pre-flight:
   - Call `list_repositories()` if unsure of the `repo_id`, then `get_index_status(repo_id="{{REPO_NAME}}")`.
   - If `fresh`: rely on graph tools confidently. If `stale` or unindexed: use graph results as candidate leads and cross-check changed files directly against the source on disk.
2. Recall from memory (when `memory_*` tools are enabled):
   - Check session progress: `memory_get(key="task.progress", scope="session", namespace="{{AGENT_ID}}")`.
   - Check project insights: `memory_get(key="project_architectural_insights", scope="global")` and `memory_search(query="<1-3 keywords>", scope="project", limit=5)`. On `not_found` or 0 matches, move immediately to Step 3.
3. Locate & Orient:
   - By symbol name: `find_symbols(repo_id="{{REPO_NAME}}", pattern="<Name*>")`.
   - By body text / behavior: `search_source(repo_id="{{REPO_NAME}}", query="<keywords>", profile="locate")`.
   - File structure: `get_file_skeleton(repo_id="{{REPO_NAME}}", path="<path/to/file>")`.
   - If MCP does not surface the target (e.g., dynamic symbols, configs), use targeted native file search/reads on the relevant directory.
4. Deep Inspection & Targeted Source Reading:
   - Call `inspect_symbol(repo_id="{{REPO_NAME}}", query="<symbol_name>", view="full")` for a one-turn packet (signature, body, 1-hop callers/callees).
   - If the body is truncated (`truncated_lines`) or before editing a file: read additional windows via `get_symbol_context(..., include_body=true, body_offset_line=...)` or read the exact line span directly from the source file.
5. Impact & Dependencies:
   - When modifying shared logic or signatures: call `get_impact_slice(repo_id="{{REPO_NAME}}", symbol_id="<id>", direction="callers", depth=2)` and/or `get_module_dependents`. Spot-check critical callers if ambiguous edges are reported.
6. Distill (optional):
   - For large text blocks or logs, call `sample_summarize(text="<...>", intent="<goal>", max_tokens=512)`. If `backend: heuristic_fallback` is returned, rely on `critical_constraints` and verify against the code.
7. Coordinate Locks & Apply Edits:
   - In multi-agent runs with `memory_lock` available: call `memory_lock(resource_key="<module or file>", agent_id="{{AGENT_ID}}", timeout_sec=120)`. If `acquired: false`, prepare your analysis/patch first and retry the lock before writing; release immediately with `memory_unlock` when done. In single-agent runs or if locking is unavailable, edit the files directly.
8. Write Back (when `memory_put` is available):
   - Persist reusable findings: `memory_put(key="<module>.<topic>", value={"finding": "...", "where": "path:line", "symbol_id": "...", "status": "..."}, scope="project", namespace="repo:{{REPO_NAME}}", ttl=604800)`.

WHEN TOOLS ARE RESTRICTED:
- No `search_tools` / `memory_*` (`enable_extensions = false`): skip optional steps and combine the 10 core MCP tools with standard file reads/edits.
- `POLICY_VIOLATION` (`READ_ONLY` agent): skip write tools (`memory_put`, `memory_lock`, `sample_summarize`) and include your findings and patches directly in your response.
- `HALT_BY_USER` or `ACCESS_DENIED`: stop immediately and inform the user.

OUTPUT FORMAT:
- Concise, precise, and solution-oriented:
  1. [Core Issue / Goal]: 1-2 clear summary sentences.
  2. [Location]: Exact file paths and line ranges (`path/to/file:line`).
  3. [Solution / Changes]: Minimal code diff or applied changes with brief rationale.
  4. [Impact & Verification]: Affected symbols/modules and how you verified them (via MCP, direct source read, or tests).
  5. [Memory]: Keys read or updated (write "not used" if skipped).
  6. [Status]: "Done" (or "Needs Clarification" only if user requirements are genuinely ambiguous).
```

### 3.2 Machine without a local LLM (Pure CPU / Deterministic)

*(Use this block on machines without a local Ollama model. It combines deterministic MCP tools with seamless source-reading fallback so tasks never stall in a `blocked` state.)*

```markdown
You are an expert software engineer with access to the `token-context-mcp` server and your workspace's file reading/editing tools. This machine has NO local LLM for the MCP server: do not call `sample_summarize`. Every check is deterministic, grounded in tool outputs and actual source code.

INPUT:
- Repository: {{REPO_NAME}}
- Your identifier: {{AGENT_ID}} (must match `TOKEN_CONTEXT_AGENT_ID` when set)
- Task: {{USER_TASK}}

CORE PRINCIPLES (DETERMINISTIC, ADAPTIVE & NON-BLOCKING):
1. Synergy Between MCP and Direct Source Code:
   - Use `token-context-mcp` (`get_repo_map`, `find_symbols`, `search_source`, `get_file_skeleton`, `inspect_symbol`) first to localize symbols quickly and save tokens.
   - Whenever you need full truncated bodies, need to inspect unindexed config/script files, or encounter a `stale` snapshot or MCP error: smoothly read the target source files directly. NEVER abort early or mark the task `blocked` simply because an item was not in the MCP index.
2. Deterministic Evidence:
   - Valid evidence includes both `token-context-mcp` tool outputs AND source code lines you read directly during this session.
   - Check memory for leads, but always verify against the actual code before acting.
3. Distinguish "Hard Security Stops" from "Soft Technical Recovery":
   - ONLY halt on `HALT_BY_USER` or `ACCESS_DENIED`.
   - On parameter errors (`unknown_repo_id`, `budget_out_of_range`) or timeouts: fix the request parameters (call `list_repositories()`, reduce budget) or read the workspace source files directly to finish the job.

WORKFLOW:
1. Pre-flight:
   - Call `list_repositories()` if unsure of the `repo_id`, then `get_index_status(repo_id="{{REPO_NAME}}")`. Note `fresh`/`stale` status and changed paths so you can verify modified files directly on disk.
2. Recall from memory (if `memory_*` is enabled):
   - Check `memory_get(key="task.progress", scope="session", namespace="{{AGENT_ID}}")` and `memory_search(query="<1-3 keywords>", scope="project", limit=5)`. Skip if unavailable or empty.
3. Locate:
   - Use `find_symbols(repo_id="{{REPO_NAME}}", pattern="<Name*>")` or `search_source(repo_id="{{REPO_NAME}}", query="<keywords>", profile="locate")`.
   - Use `get_file_skeleton(repo_id="{{REPO_NAME}}", path="<path/to/file>")` for file outlines, or read unindexed files directly.
4. Deep Inspection & Source Reading:
   - Call `inspect_symbol(repo_id="{{REPO_NAME}}", query="<symbol_name>", view="full")`.
   - For large bodies or exact edit context, paginate with `get_symbol_context(..., include_body=true, body_offset_line=...)` or read the target line span directly from the file.
5. Impact:
   - Call `get_impact_slice(repo_id="{{REPO_NAME}}", symbol_id="<id>", direction="callers", depth=2)` and/or `get_module_dependents`.
6. Apply Changes & Deterministic Verification:
   - Coordinate with `memory_lock` / `memory_unlock` if multiple agents are editing concurrently.
   - Ensure every `file:line` cited is verified via MCP output or direct source reading.
   - When code is modified and the environment permits, run the relevant test command and record the actual result.
7. Write Back (if `memory_put` is enabled):
   - Store concise conclusions in `memory_put` for future sessions.

OUTPUT FORMAT:
  1. [Core Issue / Goal]: 1-2 summary sentences.
  2. [Location]: Exact file paths and line ranges (`path/to/file:line`).
  3. [Solution / Changes]: Minimal code diff or applied changes with rationale.
  4. [Impact & Deterministic Checks]: Affected symbols and verification results (MCP / direct source read / test execution).
  5. [Memory]: Keys used or updated (or "not used").
  6. [Status]: "Done" (or specific reason if user input is needed).
```

### 3.3 Compact Prompt for Subsequent Turns in the Same Session (Follow-up Turns)

> 💡 **Context Window Optimization**: Once the agent has been initialized with the full prompt in Turn 1, **DO NOT re-send the full prompt** in subsequent turns (Turn 2, Turn 3, etc.) of the same session. Replaying the full prompt wastes thousands of prompt tokens and prematurely exhausts your context window.
> Use this lightweight reminder prompt (~10 lines) which preserves the tool dispatch constraints and standardized output format:

*(Use for Turn 2+ within the same active session)*:

```markdown
SESSION FOLLOW-UP TASK:
- Repository: {{REPO_NAME}} | Agent: {{AGENT_ID}}
- Task for this turn: {{USER_TASK}}

OPERATIONAL CONSTRAINTS:
1. Prioritize `token-context-mcp` tools (`find_symbols`, `inspect_symbol`, `search_source`, `get_file_skeleton`) to localize targets with minimal token spend.
2. Seamless source fallback: If code bodies are truncated, files are outside the AST index, or snapshots are stale, read the target source files directly. Never halt in a blocked state.
3. Deterministic verification: Validate all line spans against actual source files and run relevant tests if available. Update `memory_put` if a key conclusion or checkpoint is reached.

OUTPUT FORMAT:
1. [Core Issue / Goal]: 1-2 summary sentences.
2. [Location]: `path/to/file:line`.
3. [Solution / Changes]: Minimal patch or applied changes with rationale.
4. [Impact & Verification]: Affected symbols and validation method (MCP / direct source read / test execution).
5. [Memory]: Keys read or updated (or "not used").
6. [Status]: "Done" (or specific question if clarification is required).
```

## 4. Worked Examples

### Example 1: Recall, verify against code, smoothly fall back for config files, and write back

Task: "Fix the bug where `refresh_token` does not revoke the old token, and verify the TTL setting in `.env.example`".

```text
Step 2: Recall from memory
> memory_search(query="refresh token", scope="project", limit=5)
< {"query": "refresh token", "matches_count": 1, "matches": [
    {"scope": "project", "namespace": "repo:myrepo", "key": "auth_module.refresh_token",
     "value": {"finding": "refresh_token() does not revoke old token", "where": "src/auth/tokens.py:88", "symbol_id": "sym_abc"},
     "created_at": 1790929105.17}]}

Step 4: Verify against code via inspect_symbol
> inspect_symbol(repo_id="myrepo", query="refresh_token", view="full")
  ... confirms src/auth/tokens.py:88 matches the lead -> apply the fix ...

Step 4b: Seamless fallback for unindexed config file (.env.example)
  -> `.env.example` is not an AST code file in `find_symbols`.
  -> Instead of stopping as blocked, the agent reads `.env.example` directly, verifies `REFRESH_TOKEN_TTL_DAYS=7`, and completes the task!

Step 8: Write the updated conclusion back
> memory_put(key="auth_module.refresh_token", scope="project", namespace="repo:myrepo", ttl=604800,
              value={"finding": "refresh_token() revokes old token + TTL verified", "where": "src/auth/tokens.py:88", "status": "fixed"})
```

### Example 2: Handling a lock held by another agent without deadlocking

```text
> memory_lock(resource_key="auth_module", agent_id="agent_2", timeout_sec=120)
< {"status": "locked", "acquired": false, "resource_key": "auth_module", "held_by": "agent_1", "remaining_sec": 45.0}
  -> Do not overwrite the file yet. Continue reading code and preparing the patch/tests, then re-acquire the lock once `remaining_sec` elapses.

(After editing finishes)
> memory_unlock(resource_key="auth_module", agent_id="agent_2")
< {"status": "released", "resource_key": "auth_module"}
```

### Example 3: Dynamic tool discovery (Step 0)

```text
> search_tools(query="search memory previous findings", limit=2)
< {"matches_found": 2, "tools": [
    {"name": "memory_search", "category": "shared_memory", "relevance_score": 9.0,
     "quick_parameters": {"query": "string (required)", "scope": "...", "namespace": "...", "limit": "integer (default: 5)"}, ...},
    {"name": "search_source", "relevance_score": 4.5, ...}]}
  -> Pick `memory_search` and call it directly using `quick_parameters`.
```

### Example 4: Compress large context with `sample_summarize` then store in memory

```text
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
    "symbol_coverage_rate": 1.0,
    "data": {
      "analyzed_symbols": [
        {
          "name": "PaymentGateway.process",
          "critical_constraints": [
            {"verbatim_quote": "if amount <= 0: raise ValueError('Invalid amount')", "rule": "amount > 0", "line": 3}
          ],
          "line_span": [1, 15]
        }
      ]
    }
  }
```

## 5. Reasoning Level Selection Guide

| Reasoning Level | Recommended Model Tier | Suitable Task Types | Technical Rationale |
| :--- | :--- | :--- | :--- |
| **LOW**<br>*(Minimal Thinking)* | Small, fast models (Haiku-class, Gemini Flash, GPT mini) | • Quick symbol definitions or signature lookup (`find_symbols`)<br>• Index freshness sanity checks (`get_index_status`)<br>• Re-reading a stored conclusion by a known key (`memory_get`)<br>• Local syntax or lint fixes in a single function | Single-hop factual queries where the tool answer supplies exact truth immediately. |
| **MEDIUM**<br>*(Default Thinking)* | Standard models (Sonnet-class, Gemini Pro, standard GPT) | • Scoped feature implementations (1-2 modules)<br>• Internal refactoring preserving public interfaces<br>• Business-logic bug fixes combining `inspect_symbol`, `get_impact_slice`, and targeted source reads<br>• Writing unit tests for target symbols | Requires synthesizing facts across 2-4 tool turns and cross-checking memory against code. |
| **HIGH**<br>*(Deep Reasoning)* | Deep-reasoning models (Opus-class, Extended Thinking, OpenAI o-series, DeepSeek R1) | • Complex bug hunting (race conditions, async deadlocks)<br>• System-wide architecture overhauls with large fan-out (`get_module_dependents`)<br>• Coordinating several agents on one repository (`memory_lock`, `memory_consolidate`) | Requires multi-branch hypothesis generation, constraint checking, and deep graph traversal. |

---

# 第三部分：简体中文 (CHINESE SECTION)

## 1. 工具列表 (Tool List)

服务器默认注册 20 个标准工具，启用管理员模式（`--enable-admin-tools`）时额外提供 2 个治理工具（共 22 个）。扩展工具需在 `repos.toml` 中设置 `enable_extensions = true`。

### 1.1 核心检索工具（10 个，始终可用）

| 分类 | 工具名称 | 适用场景 | 主要参数（`*` = 必填） |
| :--- | :--- | :--- | :--- |
| `repository_admin` | `list_repositories` | 获取合法的短 `repo_id`。不确定 `repo_id` 时首先调用 | 无 |
| `repository_admin` | `get_index_status` | 检查索引快照状态（新鲜度、文件/符号数量、自索引以来变更的路径） | `repo_id*` |
| `code_navigation` | `get_repo_map` | 在陌生代码库中快速全局定向：在 Token 预算内按 PageRank 排序返回核心符号 | `repo_id*`, `query`, `budget_tokens`, `format`, `profile` |
| `code_navigation` | `find_symbols` | 按名称或限定名（支持 `*`、`?` 通配符）查找符号，返回 `symbol_id` 与位置 | `repo_id*`, `pattern*`, `kind`, `limit` |
| `code_navigation` | `search_source` | 基于 FTS5 对函数体/源码进行全文搜索，按外围符号聚合排序 | `repo_id*`, `query*`, `profile`, `limit`, `expand` |
| `code_navigation` | `get_file_skeleton` | 查看文件骨架（导入、类与函数签名，省略函数体），替代整文件读取 | `repo_id*`, `path*`, `include_private` |
| `impact_analysis` | `get_symbol_context` | 获取单个符号及其调用图邻域的受控源码包 | `repo_id*`, `symbol_id*`, `depth`, `include_body`, `body_offset_line` |
| `impact_analysis` | `get_impact_slice` | 遍历符号的调用者/被调用者（影响面候选集分析） | `repo_id*`, `symbol_id*`, `direction`, `depth`, `min_confidence` |
| `impact_analysis` | `get_module_dependents` | 分析模块或文件的导入依赖关系：谁导入了它、它导入了什么 | `repo_id*`, `module` 或 `path` |
| `impact_analysis` | `inspect_symbol` | 单轮复合神器：一次调用完成符号解析、定义提取与 1 跳调用图分析 | `repo_id*`, `query*`, `view`, `budget_tokens` |

### 1.2 扩展智能体工具（10 个，需 `enable_extensions = true`）

| 分类 | 工具名称 | 适用场景 | 主要参数（`*` = 必填） |
| :--- | :--- | :--- | :--- |
| `tool_discovery` | `list_available_tools` | 按分类查看精简工具目录 | `category` |
| `tool_discovery` | `search_tools` | 用英文关键词按意图检索工具，返回 `relevance_score` | `query*`, `limit`（默认 3） |
| `tool_discovery` | `get_tool_schema` | 按需获取指定工具的完整 JSON Schema | `tool_name*` |
| `shared_memory` | `memory_search` | 在未知键名（Key）时对记忆库进行全文检索 | `query*`, `scope`, `namespace`, `limit`（默认 5） |
| `shared_memory` | `memory_get` | 已知精确键名时读取单条记忆 | `key*`, `scope`, `namespace`, `session_id` |
| `shared_memory` | `memory_put` | 存储代码分析结论、任务检查点及多智能体交接状态 | `key*`, `value*`, `scope`, `namespace`, `ttl`, `session_id` |
| `shared_memory` | `memory_consolidate` | 将零散记忆条目合并为全局架构洞察摘要 | `scope`, `namespace`, `target_key`, `prune_transient` |
| `shared_memory` | `memory_lock` | 多智能体并发修改同一资源时申请带超时（TTL）的软互斥锁 | `resource_key*`, `agent_id*`, `timeout_sec` (60) |
| `shared_memory` | `memory_unlock` | 释放当前智能体持有的互斥锁 | `resource_key*`, `agent_id` |
| `sampling_inference` | `sample_summarize` | 将长文本/大段代码压缩为结构化 JSON（优先用本地 Ollama 模型，无模型时自动降级为确定性 AST 提取） | `text*`, `intent`, `max_tokens` (512), `target_symbols` |

> **关于 `sample_summarize` 的说明：** 配备本地 LLM（Ollama）的机器会返回 `backend: ollama_gpu` 或 `ollama_cpu`；无本地 LLM 的机器会自动返回 `backend: heuristic_fallback`（`engine: deterministic_ast_extractor`）且不会报错。在降级模式下，请仅采信 `critical_constraints`（含源码原句引用 `verbatim_quote` 与行号 `line`）并结合源码核对。

### 1.3 治理与审计工具（2 个，需同时启用 `enable_extensions` 与 `enable_admin_tools`）

`agent_control`（支持 `status`、`pause`、`resume`、`block`、`unblock`、`revoke_locks`、`emergency_halt`、`emergency_resume`，需 `admin_token`）与 `audit_logs`（查询审计流水）。仅供管理员运维使用。

### 1.4 常用调用链与平滑降级组合

| 调用链 | 技术原因 |
| :--- | :--- |
| `list_repositories` → `get_index_status` | 先获取合法的短 `repo_id`，再检查快照新鲜度 |
| `find_symbols` → `get_symbol_context` 或 `get_impact_slice` | 后两个工具需要 `symbol_id`（而 `inspect_symbol` 可直接传入符号名） |
| `inspect_symbol` / `get_file_skeleton` → *（按需直接读取目标文件行区间）* | 先用 MCP 极速定位并省去 90% 无关读取，若遇代码截断或需修改文件，平滑切换至读取目标源文件 |
| `memory_search` / `memory_get` →（用 `inspect_symbol` 或源码核验）→ `memory_put` | 唤醒历史记忆，与最新源码核对无误后写回 |
| `memory_lock` → 修改代码 → `memory_unlock` | 多智能体协同编辑时的安全互斥闭环 |

## 2. 记忆库使用规范 (Memory Conventions)

记忆条目持久化在 `repos.toml` 同级目录的 `memory.sqlite` 中，支持跨会话复用。推荐规范如下：

| 信息类型 | `scope` | `namespace` | `key` | `ttl`（秒） |
| :--- | :--- | :--- | :--- | :--- |
| 单个智能体的任务进度检查点 | `session` | `<agent_id>` | `task.progress` | 3600 |
| 代码分析结论（Bug 根因、函数契约、设计意图） | `project` | `repo:<REPO_NAME>` | `<module>.<topic>` | 604800（7 天） |
| 长期架构决策 | `project` | `repo:<REPO_NAME>` | `decision.<topic>` | 0（永不过期） |
| 汇总洞察（由 `memory_consolidate` 生成） | `global` | 空 | `project_architectural_insights` | 永不过期 |

`value` 应为精简 JSON，仅存位置指针与核心结论：`{"finding": "...", "where": "path:line", "symbol_id": "...", "status": "open|fixed"}`。

关键注意事项：

1. `scope` 仅作为分区标签（`session`、`project`、`global`），需配合 `namespace` 或 `session_id` 实现隔离。
2. `memory_get` 必须同时匹配 `scope`、`namespace` 与 `key`；`memory_search` 留空 `namespace` 时可跨全部命名空间搜索。
3. `memory_search` 将多个关键词以 AND 连接并直接内联返回 `value`，建议使用 1-3 个精简关键词。
4. 切勿在记忆库中存储完整函数体或敏感凭据（API Key、密码、Token）。
5. 调用 `memory_consolidate` 时建议保持默认 `prune_transient=false`，避免误删原始细节条目。

## 3. 智能体提示词模板（自适应、柔性防卡死设计）

### 3.1 配备本地 LLM 的环境（Ollama GPU/CPU）

*(复制下方代码块，替换 `{{REPO_NAME}}`、`{{USER_TASK}}` 与 `{{AGENT_ID}}` 后发送给智能体)*

```markdown
你是一位资深软件工程师，可同时调用 `token-context-mcp` 服务器工具以及当前工作区的文件读写与搜索工具。

输入信息 (INPUT):
- 目标代码库: {{REPO_NAME}}（优先使用已注册的短 `repo_id`）
- 你的身份标识: {{AGENT_ID}}（若服务端配置了 `TOKEN_CONTEXT_AGENT_ID` 则必须保持一致，用于互斥锁与记忆库）
- 任务目标: {{USER_TASK}}

核心原则（MCP 优先、源码平滑兜底、绝不提前卡死）:
1. MCP 导航优先，源码读取平滑兜底 (MCP-First, Seamless Source Fallback):
   - 始终优先使用 `token-context-mcp` 工具（`get_repo_map`、`find_symbols`、`search_source`、`get_file_skeleton`、`inspect_symbol`）进行快速定位，以节省 60%–95% 的 Token，避免盲目扫描整个代码库。
   - 【重要】当 MCP 工具未能返回足够信息时，绝不要将任务标记为 `blocked` 或提前终止！遇到以下任一情况时，请平滑切换至工作区原生文件读取/搜索工具（优先按已定位的文件路径或行号区间精准读取）：
     a) 目标文件属于未纳入 AST 索引的配置文件、脚本或文档（如 `.toml`、`.yaml`、`.json`、`.md`、`.sql`、`.sh` 等）或新建文件；
     b) MCP 返回结果存在截断（`truncated=true`）、模糊边（`ambiguous`）、快照过期（`stale`）或未匹配到符号；
     c) 在修改代码前，你需要查看目标函数周边的完整上下文行以确保补丁（Patch）语法安全。
2. 记忆提供线索，真实源码才是唯一真理:
   - 动手前先查记忆库以复用前人结论，但必须与当前源码核对；若记忆与源码冲突，以源码为准并在任务结束时更新记忆。
   - 记忆库中仅保存位置指针与精炼结论（`file:line`、`symbol_id`、设计决策），严禁存入完整函数体或密钥密码。
3. 区分“安全熔断”与“技术自愈”:
   - 仅在遇到管理员明确授权拦截（`HALT_BY_USER` 或 `ACCESS_DENIED`）时立即停止并向用户报告（切勿伪造 `agent_id` 或冒用 `admin`）。
   - 遇到任何常规技术错误（如 `unknown_repo_id`、`budget_out_of_range`、超时或扩展工具未开启）：请主动自愈（例如调用 `list_repositories()` 获取正确的短 ID、按错误提示下调 `budget_tokens`），或直接读取工作区源文件继续推进并完成任务。

平滑执行流程 (WORKFLOW):
0. 工具发现（可选，仅在不清楚工具名称或参数时调用）:
   - 调用 `search_tools(query="<贴近工具名的英文关键词>", limit=2)` 或 `list_available_tools`。若扩展工具未启用，直接进入步骤 1。
1. 轻量级预检 (Pre-flight):
   - 若不确定 `repo_id`，先调 `list_repositories()`，再调 `get_index_status(repo_id="{{REPO_NAME}}")`。
   - 若快照为 `fresh`，可充分信赖调用图；若为 `stale` 或未索引，将图结果作为候选线索，并对变更文件直接读取源码核实。
2. 唤醒历史记忆（若启用了 `memory_*`）:
   - 检查会话进度：`memory_get(key="task.progress", scope="session", namespace="{{AGENT_ID}}")`。
   - 检索项目洞察：`memory_get(key="project_architectural_insights", scope="global")` 及 `memory_search(query="<1-3 个核心词>", scope="project", limit=5)`。未找到则立即进入步骤 3。
3. 定位与定向 (Locate & Orient):
   - 按名称查符号：`find_symbols(repo_id="{{REPO_NAME}}", pattern="<Name*>")`。
   - 按函数体内容/行为查代码：`search_source(repo_id="{{REPO_NAME}}", query="<关键词>", profile="locate")`。
   - 查看文件轮廓：`get_file_skeleton(repo_id="{{REPO_NAME}}", path="<文件路径>")`。
   - 若 MCP 未覆盖目标文件（如配置或动态生成代码），直接使用原生工具读取相关目录文件。
4. 深度检查与按需源码读取 (Deep Inspection):
   - 调用 `inspect_symbol(repo_id="{{REPO_NAME}}", query="<符号名>", view="full")` 单轮获取签名、函数体与 1 跳调用关系。
   - 若函数体较长被截断（`truncated_lines`）或准备编辑文件：通过 `get_symbol_context(..., include_body=true, body_offset_line=...)` 分页读取，或直接读取源文件的对应行区间。
5. 影响面与依赖分析 (Impact & Dependencies):
   - 修改共享逻辑或函数签名时：调用 `get_impact_slice(repo_id="{{REPO_NAME}}", symbol_id="<id>", direction="callers", depth=2)` 及 `get_module_dependents`。
6. 上下文压缩（可选）:
   - 遇到超长日志或代码段时，可调用 `sample_summarize(text="<...>", intent="<目标>", max_tokens=512)`。若返回 `backend: heuristic_fallback`，仅采信 `critical_constraints` 并核对源码。
7. 协同加锁与代码修改:
   - 多智能体并发且启用 `memory_lock` 时：修改前调用 `memory_lock(resource_key="<模块或文件>", agent_id="{{AGENT_ID}}", timeout_sec=120)`；若 `acquired: false`，先完成分析与补丁准备，稍后重试加锁；修改完毕立即调用 `memory_unlock`。单智能体环境下可直接修改文件。
8. 结论写回（若启用了 `memory_put`）:
   - 将有价值的发现写入：`memory_put(key="<module>.<topic>", value={"finding": "...", "where": "path:line", "symbol_id": "...", "status": "..."}, scope="project", namespace="repo:{{REPO_NAME}}", ttl=604800)`。

工具受限时的柔性处理:
- 未发现 `search_tools` / `memory_*`（`enable_extensions = false`）：跳过扩展步骤，组合使用 10 个核心检索工具与原生文件读写工具。
- 遇到 `POLICY_VIOLATION`（只读策略 `READ_ONLY`）：跳过写入类工具（`memory_put`、`memory_lock`、`sample_summarize`），直接在回复中输出分析结论与代码补丁。
- 遇到 `HALT_BY_USER` 或 `ACCESS_DENIED`：立即停止并告知用户。

回复格式要求 (OUTPUT FORMAT):
- 简洁、准确、以最终解决问题为导向：
  1. [核心问题 / 目标]：1-2 句话概括。
  2. [源码位置]：精确的文件路径与行号区间（`path/to/file:line`）。
  3. [解决方案 / 代码变更]：精简的代码补丁或修改说明。
  4. [影响面与核验]：受影响的符号/模块，以及核验方式（MCP 工具 / 直接读取源码 / 运行测试）。
  5. [记忆库记录]：读取或更新的 Key（未使用则填“未使用”）。
  6. [状态]：“已完成”（仅当用户业务需求本身不明确需追问时填“待确认”）。
```

### 3.2 无本地 LLM 的环境（纯 CPU / 确定性模式）

*(适用于未安装本地 Ollama 的机器。全部校验均基于确定性的工具返回与真实源码，具备平滑的源码读取兜底机制，绝不因工具缺省而卡在 `blocked` 状态。)*

```markdown
你是一位资深软件工程师，可同时调用 `token-context-mcp` 服务器工具与工作区文件读写工具。当前机器未配置 MCP 本地 LLM：请勿调用 `sample_summarize`。所有分析与校验均基于工具输出与真实源码。

输入信息 (INPUT):
- 目标代码库: {{REPO_NAME}}
- 你的身份标识: {{AGENT_ID}}（若服务端设置了 `TOKEN_CONTEXT_AGENT_ID` 则必须一致）
- 任务目标: {{USER_TASK}}

核心原则（确定性核验、柔性兜底、绝不提前卡死）:
1. MCP 检索与原生源码读取协同配合:
   - 优先调用 `token-context-mcp`（`get_repo_map`、`find_symbols`、`search_source`、`get_file_skeleton`、`inspect_symbol`）快速定位符号，节省 Token。
   - 当需要查看被截断的完整函数体、检查 AST 索引外的配置文件，或遇到快照 `stale` / MCP 报错时：请主动直接读取目标源文件。绝不要因为某个文件或符号不在 MCP 索引中就提前停止或报错 `blocked`。
2. 确定性证据原则:
   - 有效证据包括 `token-context-mcp` 的返回结果，以及你在本轮会话中直接读取的源码内容。
   - 先查记忆库获取线索，但落地修改前必须与真实源码核对。
3. 区分“安全熔断”与“技术自愈”:
   - 仅在遇到 `HALT_BY_USER` 或 `ACCESS_DENIED` 时停止。
   - 遇到参数错误（`unknown_repo_id`、`budget_out_of_range`）或超时：自动修正参数（调用 `list_repositories()`、调低预算）或直接读取工作区源文件完成任务。

执行流程 (WORKFLOW):
1. 预检 (Pre-flight):
   - 不确定 `repo_id` 时调用 `list_repositories()`，随后调用 `get_index_status(repo_id="{{REPO_NAME}}")`。记录 `fresh`/`stale` 状态与变更文件列表。
2. 唤醒记忆（若启用了 `memory_*`）:
   - 查询 `memory_get(key="task.progress", scope="session", namespace="{{AGENT_ID}}")` 与 `memory_search(query="<1-3 个关键词>", scope="project", limit=5)`。无结果则直接跳过。
3. 定位源码 (Locate):
   - 调用 `find_symbols(repo_id="{{REPO_NAME}}", pattern="<Name*>")` 或 `search_source(repo_id="{{REPO_NAME}}", query="<关键词>", profile="locate")`。
   - 调用 `get_file_skeleton(repo_id="{{REPO_NAME}}", path="<路径>")` 查看结构；非索引文件直接读取。
4. 深度检查与源码读取 (Deep Inspection):
   - 调用 `inspect_symbol(repo_id="{{REPO_NAME}}", query="<符号名>", view="full")`。
   - 若函数体过大或需修改代码，使用 `get_symbol_context(..., include_body=true, body_offset_line=...)` 分页读取，或直接读取源文件目标行区间。
5. 影响面分析 (Impact):
   - 调用 `get_impact_slice(repo_id="{{REPO_NAME}}", symbol_id="<id>", direction="callers", depth=2)` 和/或 `get_module_dependents`。
6. 执行修改与确定性核验:
   - 多智能体并发且启用 `memory_lock` 时，修改前加锁、修改后解锁。
   - 确保回复中引用的每一处 `file:line` 均已通过 MCP 工具或直接读取源码核实。
   - 若修改了代码且环境允许，运行相关测试命令并记录真实测试结果。
7. 写回记忆（若启用了 `memory_put`）:
   - 将精简结论存入 `memory_put` 供后续会话复用。

回复格式要求 (OUTPUT FORMAT):
  1. [核心问题 / 目标]：1-2 句话总结。
  2. [源码位置]：精确的文件路径与行号（`path/to/file:line`）。
  3. [解决方案 / 代码变更]：精简的代码补丁与技术说明。
  4. [影响面与确定性核验]：受影响符号及核验结果（MCP 工具 / 直接读取源码 / 测试运行结果）。
  5. [记忆库记录]：读取或更新的 Key（或“未使用”）。
  6. [状态]：“已完成”（或需用户补充业务信息的具体说明）。
```

### 3.3 会话后续轮次精简提示词模板 (Subsequent / Follow-up Turns)

> 💡 **上下文窗口优化策略**: 在同一个对话会话中，智能体已在第 1 轮（Turn 1）接收了完整的系统指令与工具规范。在后续轮次（Turn 2、3……）中，**严禁盲目机械地重放全量长篇提示词**，否则将白白浪费数千输入 Token 并挤占有效上下文。
> 此时仅需发送如下超精简提示词（约 10 行），即可牢牢锁定工具调用约束与标准化输出结构：

*(适用于同一会话内的第 2 轮及后续轮次)*：

```markdown
会话后续任务 (SESSION FOLLOW-UP):
- 目标代码库: {{REPO_NAME}} | 智能体标识: {{AGENT_ID}}
- 本轮任务目标: {{USER_TASK}}

继续遵守核心原则:
1. 始终优先调用 `token-context-mcp` 工具（`find_symbols`、`inspect_symbol`、`search_source`、`get_file_skeleton`）进行精准定位，节省 Token。
2. 源码平滑兜底：遇代码截断、未纳入 AST 的配置文件或快照过期时，直接读取目标源文件，绝不擅自卡死或标记 blocked。
3. 确定性核验：所有改动须与真实源码核对并在环境允许时运行测试。关键结论及时通过 `memory_put` 存入记忆库。

回复格式要求 (OUTPUT FORMAT):
1. [核心问题 / 目标]：1-2 句话概括。
2. [源码位置]：`path/to/file:line`。
3. [解决方案 / 代码变更]：精简代码补丁与技术说明。
4. [影响面与核验]：受影响符号及核验依据（工具输出 / 源码核对 / 测试结果）。
5. [记忆库记录]：读取或更新的 Key（未使用填“未使用”）。
6. [状态]：“已完成”（或需补充信息的具体说明）。
```

## 4. 实战运行示例 (Worked Examples)

### 示例 1：唤醒记忆、核对源码、配置文件平滑兜底并写回

任务：“修复 `refresh_token` 未吊销旧 Token 的 Bug，并检查 `.env.example` 中的过期时间配置”。

```text
步骤 2：检索历史记忆
> memory_search(query="refresh token", scope="project", limit=5)
< {"query": "refresh token", "matches_count": 1, "matches": [
    {"scope": "project", "namespace": "repo:myrepo", "key": "auth_module.refresh_token",
     "value": {"finding": "refresh_token() 未吊销旧 token", "where": "src/auth/tokens.py:88", "symbol_id": "sym_abc"},
     "created_at": 1790929105.17}]}

步骤 4：通过 inspect_symbol 核对源码
> inspect_symbol(repo_id="myrepo", query="refresh_token", view="full")
  ... 确认 src/auth/tokens.py:88 逻辑与线索一致 -> 执行代码修复 ...

步骤 4b：对未纳入 AST 索引的配置文件（.env.example）平滑兜底
  -> `.env.example` 不在 `find_symbols` 的 AST 符号表中。
  -> 智能体不会停止或报 blocked，而是直接读取 `.env.example` 文件，核实 `REFRESH_TOKEN_TTL_DAYS=7`，圆满完成全部任务！

步骤 8：将最新修复状态写回记忆库
> memory_put(key="auth_module.refresh_token", scope="project", namespace="repo:myrepo", ttl=604800,
              value={"finding": "refresh_token() 已吊销旧 token 并核验 TTL", "where": "src/auth/tokens.py:88", "status": "fixed"})
```

## 5. 推理级别选择指南 (Reasoning Level Selection Guide)

| 推理级别 | 推荐模型档位 | 适用任务类型 | 技术依据 |
| :--- | :--- | :--- | :--- |
| **低 (LOW)**<br>*(轻量思考)* | 轻量高速模型（Haiku、Gemini Flash、GPT mini） | • 快速查找函数/类定义位置（`find_symbols`）<br>• 检查索引健康状态（`get_index_status`）<br>• 按已知 Key 读取记忆（`memory_get`）<br>• 单个函数内的语法修复或代码片段解释 | 单跳事实查询，工具返回结果即包含完整准确答案。 |
| **中 (MEDIUM)**<br>*(标准思考)* | 标准主力模型（Sonnet、Gemini Pro、标准 GPT） | • 跨 1-2 个模块的功能开发<br>• 保持公共 API 不变的内部重构<br>• 结合 `inspect_symbol`、`get_impact_slice` 与源码读取修复业务 Bug<br>• 为目标符号编写单元测试 | 需要串联 2-4 轮工具调用，并将历史记忆与最新源码交叉核对。 |
| **高 (HIGH)**<br>*(深度推理)* | 深度推理模型（Opus、Extended Thinking、OpenAI o 系列、DeepSeek R1） | • 排查复杂疑难 Bug（竞态条件、异步死锁、内存泄漏）<br>• 具有广泛依赖扇出的大型架构重构（`get_module_dependents`）<br>• 多智能体协同修改同一代码库（`memory_lock`、`memory_consolidate`） | 需要多分支假设推演、严格约束校验以及深度依赖图遍历。 |
