# SAMPLE PROMPT TEMPLATE / MẪU PROMPT / 提示词模板 (`token-context-mcp` v0.3.10)

> 🌐 **Ngôn ngữ / Languages / 语言版本**:
> - [🇻🇳 PHẦN 1: TIẾNG VIỆT](#phần-1-tiếng-việt)
> - [🇬🇧 PART 2: ENGLISH SECTION](#part-2-english-section)
> - [🇨🇳 第三部分：简体中文 (CHINESE SECTION)](#第三部分简体中文-chinese-section)
>
> Mẫu prompt chuẩn với cơ chế **Thích ứng Linh hoạt (MCP-First & Graceful Source Fallback)** và **Sổ Bằng Chứng Kiểm Chứng ("Lá Phổi" — Evidence Ledger mặc định BẬT)** cho AI Agent dùng `token-context-mcp`: danh sách 23 tool đầy đủ (`10` lõi + `11` mở rộng gồm `trajectory_record` thuộc nhóm `memory_state` + `2` admin), ranh giới rõ ràng giữa Sổ Bằng Chứng (`ledger.sqlite`) và Bộ Nhớ Chia Sẻ (`memory.sqlite`), quy ước `prior_evidence` / `recheck_from` và Write Gate G1–G6 để tránh `stale_file` / `empty_signature`, giúp truy xuất tiết kiệm token mà **không bao giờ tự khóa (non-blocking)**.
>
> Đối chiếu với bản **v0.3.10**: `TOOL_CATALOG` (`src/token_context_mcp/discovery/catalog.py`), `ledger/` ("Lá Phổi"), `kernel/` (Cordis Waterfall), `retrieve/service.py`, `retrieve/batch.py`, `server.py`, `memory/service.py`, `memory/store.py`, `security/access_control.py`. Placeholder: `{{REPO_NAME}}`, `{{USER_TASK}}`, `{{AGENT_ID}}`.

---

# PHẦN 1: TIẾNG VIỆT

## 1. Danh sách tool

Server đăng ký 21 tool tiêu chuẩn (10 lõi + 11 mở rộng), thêm 2 tool admin nếu bật (`--enable-admin-tools`) thành 23 tool. Các tool mở rộng phụ thuộc vào cấu hình `enable_extensions = true` trong `repos.toml`. Sổ Bằng Chứng (`[ledger].enabled = true` trong `repos.toml`) **mặc định BẬT** để tự động gắn `prior_evidence` vào phản hồi của `get_repo_map(query=...)` và `search_source(query=...)`.

### 1.1 Tool lõi (10 tool, luôn có)

| Nhóm | Tool | Dùng khi | Tham số chính (`*` = bắt buộc) |
| :--- | :--- | :--- | :--- |
| `repository_admin` | `list_repositories` | Lấy `repo_id` hợp lệ. Gọi đầu tiên khi chưa chắc `repo_id` | không có |
| `repository_admin` | `get_index_status` | Kiểm tra snapshot (độ mới, số file/symbol, path đã đổi từ lúc index) | `repo_id*` |
| `code_navigation` | `get_repo_map` | Định hướng trong repo lạ: symbol xếp hạng PageRank theo ngân sách token (trả kèm `prior_evidence` khi có `query`) | `repo_id*`, `query`, `budget_tokens`, `format`, `profile` |
| `code_navigation` | `find_symbols` | Tìm symbol theo tên hoặc qualified name, trả `symbol_id` và vị trí | `repo_id*`, `pattern*` (hỗ trợ `*` `?`), `kind`, `limit` |
| `code_navigation` | `search_source` | Tìm full-text FTS5 theo nội dung thân hàm/code, xếp theo symbol bao quanh (trả kèm `prior_evidence`) | `repo_id*`, `query*`, `profile`, `limit`, `expand` |
| `code_navigation` | `get_file_skeleton` | Xem khung một file (import, chữ ký, lược bỏ thân hàm) thay cho đọc cả file | `repo_id*`, `path*`, `include_private` |
| `impact_analysis` | `get_symbol_context` | Gói nguồn có giới hạn của một symbol và láng giềng trong đồ thị | `repo_id*`, `symbol_id*`, `depth`, `include_body`, `body_offset_line` |
| `impact_analysis` | `get_impact_slice` | Duyệt caller/callee quan sát được từ một symbol (ứng viên ảnh hưởng) | `repo_id*`, `symbol_id*`, `direction`, `depth`, `min_confidence` |
| `impact_analysis` | `get_module_dependents` | Quan hệ import của một module hoặc path: ai import nó, nó import gì | `repo_id*`, `module` hoặc `path` |
| `impact_analysis` | `inspect_symbol` | Tool gộp một lượt: resolve symbol, định nghĩa, đồ thị 1-hop tức thời | `repo_id*`, `query*`, `view`, `budget_tokens` |

### 1.2 Tool mở rộng (11 tool, cần `enable_extensions = true`)

| Nhóm | Tool | Dùng khi | Tham số chính (`*` = bắt buộc) |
| :--- | :--- | :--- | :--- |
| `tool_discovery` | `list_available_tools` | Xem catalog gọn, nhóm theo category | `category` |
| `tool_discovery` | `search_tools` | Tìm tool theo từ khóa tiếng Anh, trả `relevance_score` | `query*`, `limit` (mặc định 3) |
| `tool_discovery` | `get_tool_schema` | Lấy JSON schema đầy đủ của đúng một tool khi cần | `tool_name*` |
| `shared_memory` | `memory_search` | Tìm full-text trong `memory.sqlite` khi chưa biết khóa | `query*`, `scope`, `namespace`, `limit` (mặc định 5) |
| `shared_memory` | `memory_get` | Đọc đúng một mục trong `memory.sqlite` khi đã biết khóa | `key*`, `scope`, `namespace`, `session_id` |
| `shared_memory` | `memory_put` | Lưu kết luận, trạng thái sau khi sửa code, checkpoint chuyển giao giữa các agent | `key*`, `value*`, `scope`, `namespace`, `ttl`, `session_id` |
| `shared_memory` | `memory_consolidate` | Gộp tối đa 500 mục cũ nhất thành một bản tổng hợp ở `global` | `scope`, `namespace`, `target_key`, `prune_transient` |
| `shared_memory` | `memory_lock` | Khóa mềm (soft-mutex) một tài nguyên có thời hạn khi nhiều agent cùng sửa | `resource_key*`, `agent_id*`, `timeout_sec` (60) |
| `shared_memory` | `memory_unlock` | Nhả khóa mình đang giữ | `resource_key*`, `agent_id` |
| `sampling_inference` | `sample_summarize` | Nén văn bản lớn thành JSON ngắn (dùng model local nếu có, không thì trích xuất AST xác định) | `text*`, `intent`, `max_tokens` (512), `target_symbols` |
| `memory_state` | `trajectory_record` | Ghi thẻ bằng chứng đường đi đã xác minh (`answers`, `steps`, `decoys`) trên file `fresh` vào Sổ Bằng Chứng ("Lá Phổi") | `repo_id*`, `query*`, `answers*`, `steps`, `decoys`, `agent_id` |

> **Lưu ý `sample_summarize`:** Máy có LLM cục bộ (Ollama) trả `backend` là `ollama_gpu` hoặc `ollama_cpu`. Máy không có LLM trả `backend` là `heuristic_fallback` (`engine` là `deterministic_ast_extractor`) và không báo lỗi. Ở nhánh fallback, chỉ dựa vào `critical_constraints` (có `verbatim_quote` và `line`) và đối chiếu với mã nguồn.
>
> **Lưu ý `trajectory_record`:** Tool này thuộc nhóm `memory_state` và **không** nhận tham số `ttl_days` (thời hạn thẻ được cấu hình ở phía server qua `[ledger].ttl_days = 28` trong `repos.toml`). Mọi đầu vào đều phải qua Cổng Kiểm Chứng G1–G6 (đòi hỏi file ở trạng thái `fresh`).

### 1.3 Tool admin (2 tool, cần `enable_extensions` và `enable_admin_tools`)

`agent_control` (nhóm `security_governance`: `status`, `pause`, `resume`, `block`, `unblock`, `set_policy`, `revoke_locks`, `emergency_halt`, `emergency_resume`, cần `admin_token`) và `audit_logs` (`limit`, `agent_id`, `status`). Dành cho người vận hành, không đưa vào prompt của agent làm việc.

### 1.4 Chuỗi gọi & Chuyển tiếp linh hoạt hay gặp

| Chuỗi | Lý do |
| :--- | :--- |
| `get_repo_map(query=...)` hoặc `search_source(query=...)` (`prior_evidence`) → `get_symbol_context` / `inspect_symbol` → `trajectory_record` *(trước khi sửa code, trên file `fresh`)* | Đọc gợi ý đã kiểm chứng trước khi search rộng (`find_symbols` **không** trả `prior_evidence`). Nếu `recheck_from` là số nguyên `k`, giữ tiền tố `1..k-1` và kiểm chứng lại từ bước `k` |
| `list_repositories` → `get_index_status` | Xác định `repo_id` ngắn và kiểm tra độ mới của snapshot |
| `find_symbols` → `get_symbol_context` hoặc `get_impact_slice` | Hai tool sau cần `symbol_id` (`inspect_symbol` nhận tên trực tiếp, không cần) |
| `inspect_symbol` / `get_file_skeleton` → *(Đọc trực tiếp vùng dòng file nếu cần sửa)* | Dùng MCP khoanh vùng nhanh, sau đó đọc trực tiếp đoạn code nếu bị cắt hoặc cần ngữ cảnh dòng liền kề |
| `memory_search` hoặc `memory_get` → (xác minh bằng `inspect_symbol` hoặc mã nguồn) → `memory_put` | Nhớ lại, đối chiếu với mã thực tế, rồi cập nhật kết luận hoặc trạng thái sau chỉnh sửa |
| `memory_lock` → sửa → `memory_unlock` | Khóa phối hợp khi có nhiều agent cùng sửa một module |

## 2. Quy ước Memory & Sổ Bằng Chứng ("Lá Phổi")

### 2.1 Bộ nhớ chia sẻ (`memory.sqlite`)

Các mục được lưu bền trong `memory.sqlite` cạnh `repos.toml`, nên agent ở phiên sau đọc lại được. Quy ước đề xuất:

| Loại thông tin | `scope` | `namespace` | `key` | `ttl` (giây) |
| :--- | :--- | :--- | :--- | :--- |
| Checkpoint tiến độ của một agent | `session` | `<agent_id>` | `task.progress` | 3600 |
| Kết luận về mã (bug, trạng thái sau sửa, cấu hình ngoài AST) | `project` | `repo:<REPO_NAME>` | `<module>.<chu_de>` | 604800 (7 ngày) |
| Quyết định kiến trúc lâu dài | `project` | `repo:<REPO_NAME>` | `decision.<chu_de>` | 0 (không hết hạn) |
| Bản tổng hợp (do `memory_consolidate` tự ghi) | `global` | trống | `project_architectural_insights` | không hết hạn |

`value` nên là JSON nhỏ, gồm con trỏ và kết luận: `{"finding": "...", "where": "path:line", "symbol_id": "...", "status": "open|fixed"}`.

Những điểm cần lưu ý:

1. `scope` chỉ là nhãn phân vùng (`session`, `project`, `global`), không tự cô lập theo phiên hay theo agent. Muốn cô lập thì dùng `namespace` hoặc `session_id`.
2. `memory_get` phải khớp đủ `scope`, `namespace` và `key`, thiếu một thứ là `not_found`. `memory_search` bỏ trống `namespace` thì tìm ở mọi namespace.
3. `memory_get` và `memory_put` đều hỗ trợ `session_id`: khi `scope="session"` và bỏ trống `namespace`, server tự động map vào namespace tương ứng để cô lập theo session.
4. `memory_search` nối mọi từ khóa FTS5 bằng AND và trả luôn `value`. Dùng 1–3 từ khóa ngắn gọn và `limit` nhỏ.
5. `ttl` mặc định 86400 giây (1 ngày). `ttl=0` (hoặc `<= 0` / `null`) là không hết hạn.
6. Key tối đa 256 byte, value tối đa 1 MB. Không lưu bí mật (API key, mật khẩu) hay toàn bộ thân hàm dài vào memory.
7. `memory_consolidate` đọc tối đa **500** mục cũ nhất còn hiệu lực của `scope` (có thể lọc theo `namespace`) và ghi bản tổng hợp vào `scope="global"`. Giữ `prune_transient=false` làm mặc định để không mất chi tiết gốc.
8. `memory_lock` trả ngay `acquired: true/false` kèm `held_by` và `remaining_sec`. Khóa chỉ là quy ước phối hợp giữa các agent, tự hết hạn sau `timeout_sec`.
9. `memory_unlock` luôn truyền đúng `agent_id` đã dùng để khóa. `agent_id` hợp lệ: chữ, số, `_`, `-`, tối đa 64 ký tự.

### 2.2 Sổ Bằng Chứng Kiểm Chứng ("Lá Phổi" — `ledger.sqlite`)

"Lá Phổi" (`ledger.sqlite` cạnh `repos.toml`) **không phải** bản sao của `memory.sqlite`. Phân tách ranh giới rõ ràng như sau:

| Cơ chế | Dùng để lưu gì? | Điều kiện & Thời điểm ghi | Cách đọc lại |
| :--- | :--- | :--- | :--- |
| **`trajectory_record`** *(Lá Phổi — `ledger.sqlite`)* | Đường đi điều hướng đã xác minh trên AST (`answers`, `steps`, `decoys`) gắn SHA-256 thân hàm | Chỉ nhận symbol thuộc file **`fresh`**. Ghi **ngay sau khi xác minh đường đi và TRƯỚC khi sửa file**, ở tác vụ chỉ đọc, hoặc sau khi re-index lại repo thành `fresh` | Tự động đính kèm trong `data.prior_evidence` của `get_repo_map(query=...)` và `search_source(query=...)` |
| **`memory_put`** *(Bộ nhớ chia sẻ — `memory.sqlite`)* | Kết luận bug, lý do thiết kế, trạng thái **sau khi sửa code** (khi file đã `stale`), cấu hình ngoài AST (`.toml`, `.yaml`, `.env`, `.md`) | Ghi tự do mọi lúc (kể cả khi file đã sửa và chuyển sang `stale`, hoặc file không có AST) | Đọc chủ động bằng `memory_get` hoặc `memory_search` |

#### Quy tắc Cổng Ghi G1–G6 (Write Gate) của `trajectory_record`:
1. **Chữ ký `query` phải dùng từ khóa ASCII (`[a-zA-Z0-9_]+`):** Server tách từ khóa bằng regex ASCII, stem và bỏ stopword; bộ khớp lúc đọc đòi hỏi tối thiểu **`answer_min_overlap >= 2`** và **`answer_jaccard_min >= 0.6`**. Luôn truyền **`>= 2` từ khóa tiếng Anh hoặc tên symbol không dấu** khớp với cụm từ bạn dùng khi gọi `get_repo_map(query=...)` / `search_source(query=...)`. *(Truyền thuần tiếng Việt có dấu hoặc chữ tượng hình sẽ bị lỗi `empty_signature`!)*
2. **Định dạng & giới hạn chặt chẽ từng trường:**
   - `answers` *(bắt buộc, tối đa **8** mục)*: `"<canonical_symbol_id>@<line>"` (`start_line <= line <= end_line`). Bắt buộc ít nhất **1** answer qua kiểm chứng; nếu không cả thẻ bị `status: "rejected"` (`card_id: null`).
   - `steps` *(tùy chọn, tối đa **12** mục)*: `"<from_symbol_id>><to_symbol_id>@<line>"`, trong đó `from != to`, `line` nằm trong phạm vi của `from_symbol`, VÀ **Gate G4**: tên định danh ngắn của `to_symbol` (`to_sym.name`) bắt buộc phải xuất hiện nguyên văn trên đúng dòng `line` đó trong file nguồn (nếu không sẽ bị từ chối với lý do `evidence_mismatch`).
   - `decoys` *(tùy chọn, tối đa **8** mục)*: `"<symbol_id>!<reason_code>"` (hoặc `"<from_symbol_id>><to_symbol_id>!no_reference"` để được kiểm chứng `source_verified`). `reason_code` **CHỈ** được chọn trong 4 giá trị cố định: **`no_reference`**, **`test_only`**, **`wrapper_only`**, **`unrelated`** *(viết tự do sẽ bị từ chối `invalid_reason_code`)*.
3. **Bẫy `stale_file` khi sửa code:** Gate G3 kiểm tra độ tươi từng file nguồn và từ chối (`reason: "stale_file"`) nếu file đã sửa mà chưa re-index. Vì vậy: **ghi `trajectory_record` TRƯỚC khi sửa file** (khi file vẫn `fresh`); **SAU khi sửa file**, ghi kết luận/trạng thái đã sửa vào `memory_put` — tuyệt đối không lặp lại `trajectory_record` vào file vừa sửa (`stale`).
4. **Định danh & giới hạn tốc độ:** Truyền `agent_id="{{AGENT_ID}}"` (khớp `TOKEN_CONTEXT_AGENT_ID` nếu server có đặt). Giới hạn: **10 lượt gọi/phút mỗi `agent_id`** (`limit_exceeded`).

#### Vòng đời thẻ & Cơ chế đọc `prior_evidence` / `recheck_from`:
- **Vòng đời thẻ:** Lần ghi đầu tạo thẻ `asserted` (`confirmations=1`). Khi một phiên (`run_id`) độc lập thứ 2 xác nhận cùng `answers`, thẻ nâng cấp lên `confirmed` (mở khóa `decoys` và lớp overlay xếp hạng). Nếu hai `run_id` ghi `answers` mâu thuẫn nhau (hoặc một answer đụng vào decoy cũ), thẻ chuyển sang `conflicted` và ngừng phục vụ. **Không bao giờ ghi giả thuyết chưa kiểm chứng.**
- **Khi đọc (`get_repo_map` với `query` khác rỗng & `search_source`):**
  - `find_symbols` **không** trả `prior_evidence`.
  - Trường `status` trong `prior_evidence` là `"asserted"` (kèm cảnh báo `prior_evidence_unconfirmed`, `decoys: []`) hoặc `"confirmed"` (kèm `decoys` nếu `match >= 0.8`).
  - `answers` (`[[symbol_id, path, line, "valid"], ...]`): nếu toàn bộ answer đã đổi thân hàm trên đĩa, server tự chuyển thẻ sang `retired` và ẩn `prior_evidence`.
  - `recheck_from`: là `null` nếu mọi bước `steps` đều còn hợp lệ trên đĩa; hoặc là **số nguyên 1-based `k`** chỉ đúng bước đầu tiên bị thay đổi/mất đồng bộ — agent giữ nguyên tiền tố `1..k-1` trong `steps` và chỉ kiểm chứng lại từ bước `k` trở đi.

## 3. Mẫu Prompt Dùng Trực Tiếp Cho AI Agent (Thiết kế Thích ứng & Mềm mỏng)

### 3.0 Mẫu Prompt Siêu Gọn — Khuyến nghị mặc định (Lean Selective MCP)

*(Mẫu mặc định tối giản cho Antigravity, Cursor, Claude Code hoặc CLI — dưới 400 token prompt, có sẵn 5 chữ ký tool để bỏ qua đọc file schema `.json` và chống đọc trùng cả file.)*

```markdown
Repo: {{REPO_NAME}} | Agent: {{AGENT_ID}}
Task: {{USER_TASK}}

Quy tắc (file ngoài AST/stale đọc thẳng; trích path:line):
1. Chọn lọc:
   - Có path: bỏ list_repositories/get_repo_map/search_source; gọi get_file_skeleton(repo_id, path, max_tokens=1024) xem chữ ký, hoặc read_file file ngắn (<300 dòng) cần full code.
   - Chưa rõ vị trí/hành vi/truy vết: gọi 1 MCP tool (search_source, inspect_symbol, get_impact_slice), budget 1024-1536.
2. Chống đọc trùng:
   - Nếu get_file_skeleton/inspect_symbol trả freshness="fresh" & truncated=false và đủ ý, DỪNG—cấm read_file cả file; thiếu chỉ đọc 20-60 dòng.
3. Zero-Ritual Budget:
   - Không lặp get_index_status (tool đã trả freshness). Tối đa 1 lần get_repo_map(budget_tokens=1024) khi chưa rõ repo. trajectory_record/memory_put chỉ dùng đa phiên/khi yêu cầu (bỏ ở Q&A).
4. 5-Tool Cheat-Sheet (gọi thẳng, bỏ qua .json schema trừ khi lỗi):
   - search_source(repo_id, query, profile="locate", max_tokens=1280, limit=15)
   - get_file_skeleton(repo_id, path, include_private=false, max_tokens=1536)
   - inspect_symbol(repo_id, query, view="full", budget_tokens=1536)
   - get_impact_slice(repo_id, symbol_id, direction="both", depth=2, max_tokens=1536)
   - get_repo_map(repo_id, query=None, budget_tokens=1024, format="compact")
```

### 3.1 Máy có LLM cục bộ (Ollama GPU/CPU)

*(Copy khối bên dưới, điền `{{REPO_NAME}}`, `{{USER_TASK}}`, và `{{AGENT_ID}}` (khớp `TOKEN_CONTEXT_AGENT_ID` nếu server có đặt, hoặc để `agent_1` khi chỉ có một agent) rồi gửi cho Agent)*

```markdown
Bạn là kỹ sư phần mềm chuyên nghiệp. Bạn có quyền truy cập vào MCP server `token-context-mcp` cùng các công cụ đọc/sửa file của môi trường làm việc.

THÔNG TIN ĐẦU VÀO (INPUT):
- Repository: {{REPO_NAME}} (ưu tiên dùng `repo_id` ngắn đã đăng ký)
- Định danh của bạn: {{AGENT_ID}} (khớp `TOKEN_CONTEXT_AGENT_ID` nếu server có đặt; dùng cho khóa, memory và `trajectory_record`)
- Yêu cầu nhiệm vụ: {{USER_TASK}}

NGUYÊN TẮC CỐT LÕI (LINH HOẠT & KHÔNG TỰ KHÓA):
1. Ưu tiên MCP để định vị, chủ động đọc Source khi cần (MCP-First, Graceful Source Fallback):
   - Luôn ưu tiên dùng các tool của `token-context-mcp` (`get_repo_map`, `find_symbols`, `search_source`, `get_file_skeleton`, `inspect_symbol`) làm la bàn định vị nhanh để tiết kiệm token, tránh đọc mù toàn bộ kho mã.
   - TUY NHIÊN, tuyệt đối KHÔNG tự đánh dấu `blocked` hay dừng nhiệm vụ sớm nếu MCP không trả về đủ thông tin! Hãy chủ động chuyển sang đọc trực tiếp file mã nguồn (ưu tiên đọc theo khoảng dòng hoặc đường dẫn đã khoanh vùng) khi:
     a) File cần xem là file cấu hình/tài liệu/script chưa được index AST (`.toml`, `.yaml`, `.json`, `.md`, `.sql`, `.sh`...) hoặc file mới tạo;
     b) Kết quả từ MCP bị cắt (`truncated=true`), có cạnh mơ hồ (`ambiguous`), snapshot ở trạng thái `stale`, hoặc tìm không thấy symbol;
     c) Bạn cần xem chính xác các dòng lệnh liền kề trong file để thực hiện chỉnh sửa/patch an toàn.
2. Phân biệt Memory (`memory_*`) và Lá Phổi (`trajectory_record` / `prior_evidence`), lấy Mã nguồn làm chân lý:
   - Tra cứu `memory_*` để kế thừa kết luận cũ và kiểm tra `prior_evidence` từ `get_repo_map(query=...)` / `search_source(query=...)`, nhưng luôn kiểm chứng lại với mã nguồn hiện tại.
   - Lá Phổi (`trajectory_record`) chỉ chấp nhận bằng chứng đã xác minh trên file **`fresh`** — KHÔNG bao giờ ghi đoán mò, và KHÔNG ép ghi vào file đã sửa (`stale`). Kết luận sau khi sửa code hoặc kiến thức ngoài AST thì lưu vào `memory_put`.
3. Phân biệt "Dừng Bảo Mật" và "Tự Phục Hồi Kỹ Thuật":
   - CHỈ dừng hẳn và báo người dùng khi gặp lỗi cấm quyền tường minh: `HALT_BY_USER` hoặc `ACCESS_DENIED` (không tự ý đổi `agent_id` để lách). `admin` là id dành riêng, không tự khai.
   - Với mọi lỗi kỹ thuật khác (sai `repo_id`, `budget_out_of_range`, `stale_file`, timeout, hoặc thiếu tool mở rộng): hãy tự điều chỉnh tham số (gọi `list_repositories()`, giảm `budget_tokens`, bỏ qua ghi ledger cho file `stale`) hoặc chuyển sang đọc trực tiếp mã nguồn để hoàn thành công việc.

QUY TRÌNH THỰC HIỆN MƯỢT MÀ:
0. Khám phá tool (tùy chọn, chỉ gọi khi chưa rõ tên hoặc tham số tool):
   - Dùng `search_tools(query="<từ khóa tiếng Anh sát tên tool>", limit=2)` hoặc `list_available_tools(category="<nhóm>")` (ví dụ `memory_state` cho `trajectory_record`). Nếu không có nhóm tool này (`enable_extensions = false`), đi thẳng sang Bước 1.
1. Kiểm tra trạng thái nhẹ nhàng (Pre-flight):
   - Chưa chắc `repo_id` thì gọi `list_repositories()`. Sau đó kiểm tra `get_index_status(repo_id="{{REPO_NAME}}")`.
   - Nếu snapshot là `fresh`: yên tâm khai thác đồ thị và Lá Phổi. Nếu là `stale`: vẫn dùng kết quả đồ thị làm gợi ý ban đầu, đối chiếu trực tiếp file nguồn thay đổi và không gọi `trajectory_record` cho file nằm trong `pending_paths`.
2. Nhớ lại từ Shared Memory (nếu bật `memory_*`):
   - Kiểm tra `memory_get(key="task.progress", scope="session", namespace="{{AGENT_ID}}")` và `memory_search(query="<1-3 từ khóa chính>", scope="project", limit=5)`. Nếu `not_found` hoặc 0 kết quả thì sang ngay Bước 3.
3. Định vị & Tham vấn Lá Phổi (`prior_evidence`):
   - Gọi `get_repo_map(repo_id="{{REPO_NAME}}", query="<>=2 từ khóa ASCII/tên symbol>")` và/hoặc `search_source(repo_id="{{REPO_NAME}}", query="<>=2 từ khóa ASCII/tên symbol>", profile="locate")` — lưu ý chỉ hai tool này mới trả về `data.prior_evidence` (`find_symbols` không trả).
   - Nếu có `data.prior_evidence`: kiểm tra trước khi tìm kiếm rộng:
     * Nhảy thẳng vào `get_symbol_context(repo_id="{{REPO_NAME}}", symbol_id="<id_tu_answers>")` hoặc `inspect_symbol` để xác minh `answers`.
     * Nếu `warnings` chứa `prior_evidence_unconfirmed` (`status: "asserted"`): vẫn kiểm chứng độc lập trên mã nguồn trước khi tin dùng.
     * Nếu `recheck_from` là số nguyên `k`: giữ nguyên tiền tố `steps[0..k-2]` đã kiểm chứng và chỉ kiểm tra lại từ bước `k` trở đi.
     * Tránh các mục đã liệt kê trong `decoys` (khi `status: "confirmed"`).
   - Kết hợp `find_symbols(repo_id="{{REPO_NAME}}", pattern="<Ten*>")` và `get_file_skeleton(repo_id="{{REPO_NAME}}", path="<đường/dẫn>")` nếu cần. Với file cấu hình/chưa index, dùng tool đọc file của môi trường.
4. Kiểm tra chi tiết & Đọc mã nguồn (Deep Inspection):
   - Gọi `inspect_symbol(repo_id="{{REPO_NAME}}", query="<ten_symbol>", view="full")` để lấy chữ ký, thân hàm và quan hệ 1-hop trong một lượt.
   - Khi thân hàm dài bị cắt (`truncated_lines`) hoặc trước khi sửa file: đọc tiếp qua `get_symbol_context(..., include_body=true, body_offset_line=...)` hoặc đọc trực tiếp khoảng dòng trên file nguồn.
5. Phân tích tác động (Impact & Dependencies):
   - Khi thay đổi chữ ký hàm hoặc logic dùng chung: gọi `get_impact_slice(repo_id="{{REPO_NAME}}", symbol_id="<id>", direction="callers", depth=2)` và/hoặc `get_module_dependents`.
6. Cập nhật Lá Phổi (`trajectory_record`) TRƯỚC khi sửa file (khi các file liên quan còn `fresh`):
   - Nếu bật `trajectory_record` và bạn đã xác minh được đường đi đúng trên các file còn `fresh`, hãy gọi NGAY trước khi chỉnh sửa file (hoặc cuối lượt với tác vụ chỉ đọc):
     `trajectory_record(repo_id="{{REPO_NAME}}", query="<>=2 từ khóa ASCII tiếng Anh/tên symbol khớp truy vấn>", answers=["<canonical_symbol_id>@<line>"], steps=["<from_symbol_id>><to_symbol_id>@<line>"], decoys=["<symbol_id>!<no_reference|test_only|wrapper_only|unrelated>"], agent_id="{{AGENT_ID}}")`
   - Lưu ý: `steps` phải có tên ngắn của `to_symbol` nằm đúng dòng `<line>`; `decoys` chỉ dùng 1 trong 4 mã lý do hợp lệ; chỉ truyền các tham số chuẩn như trên. Bỏ qua nếu file mục tiêu đã `stale`.
7. Nén ngữ cảnh lớn (tùy chọn):
   - Khi gặp log hoặc kết quả quá dài, có thể gọi `sample_summarize(text="<...>", intent="<mục tiêu>", max_tokens=512)`. Nếu trả về `backend: heuristic_fallback`, chỉ sử dụng phần `critical_constraints` và đối chiếu với mã thật.
8. Phối hợp khóa và chỉnh sửa (khi cần sửa code):
   - Nếu dùng `memory_lock`: gọi `memory_lock(resource_key="<module/file>", agent_id="{{AGENT_ID}}", timeout_sec=120)`. Nếu `acquired: false`, hoàn thành phân tích/chuẩn bị patch trước rồi thử khóa lại; sửa xong nhớ `memory_unlock`. Chạy test liên quan nếu môi trường cho phép.
9. Ghi nhớ hậu chỉnh sửa (`memory_put`):
   - Sau khi sửa file (lúc này file đã `stale` với snapshot cũ): KHÔNG gọi lại `trajectory_record` lên các file đã sửa (sẽ bị từ chối `stale_file` trừ khi repo đã được re-index lại thành `fresh`). Thay vào đó, lưu kết luận và trạng thái fix vào `memory_put(key="<module>.<chu_de>", value={"finding": "...", "where": "path:line", "symbol_id": "...", "status": "fixed"}, scope="project", namespace="repo:{{REPO_NAME}}", ttl=604800)`.

XỬ LÝ LINH HOẠT KHI TOOL HẠN CHẾ:
- Không có `search_tools` / `memory_*` / `trajectory_record` (`enable_extensions = false`): bỏ qua các bước mở rộng, dùng 10 tool lõi kết hợp đọc/sửa file tiêu chuẩn (vẫn đọc `prior_evidence` nếu `[ledger].enabled = true`).
- Lỗi `POLICY_VIOLATION` (agent ở chế độ `READ_ONLY`): bỏ qua các lệnh ghi (`memory_put`, `memory_lock`, `memory_unlock`, `memory_consolidate`, `sample_summarize`, `trajectory_record`), trình bày trực tiếp kết quả và bản patch đề xuất trong phản hồi.
- Lỗi `HALT_BY_USER` hoặc `ACCESS_DENIED`: dừng ngay lập tức và thông báo rõ cho người dùng.

QUY CÁCH PHẢN HỒI (OUTPUT FORMAT):
- Ngắn gọn, rõ ràng, tập trung giải quyết dứt điểm yêu cầu:
  1. [Vấn đề / Mục tiêu cốt lõi]: Tóm tắt trong 1-2 câu.
  2. [Vị trí mã nguồn]: Đường dẫn file và dòng code cụ thể (`file_path:line`).
  3. [Giải pháp / Thay đổi đã thực hiện]: Khối code/patch ngắn gọn kèm lý do kỹ thuật.
  4. [Tác động & Kiểm chứng]: Các symbol/module liên quan và kết quả kiểm tra (qua MCP, đọc source hoặc chạy test).
  5. [Memory & Ledger]: Key `memory_*` đã tra/ghi + trạng thái `prior_evidence` (`hit` / `recheck_from`) & `trajectory_record` (hoặc lý do bỏ qua như `stale_file` / `READ_ONLY`).
  6. [Trạng thái]: "Hoàn thành" (hoặc "Cần làm rõ" nếu yêu cầu nghiệp vụ của người dùng còn thiếu thông tin).
```

### 3.2 Máy không có LLM cục bộ (CPU thuần / Deterministic)

*(Dùng khối này cho máy không có Ollama cục bộ. Mọi bước kiểm tra — bao gồm cả Sổ Bằng Chứng ("Lá Phổi") — đều hoàn toàn xác định dựa trên SQLite, AST, SHA-256 và mã nguồn thực tế, kết hợp cơ chế fallback đọc source mượt mà để không bao giờ bị kẹt ở trạng thái `blocked`.)*

```markdown
Bạn là kỹ sư phần mềm chuyên nghiệp có quyền truy cập vào MCP server `token-context-mcp` cùng các công cụ đọc/sửa file của môi trường. Máy này KHÔNG có LLM cục bộ cho MCP server: tuyệt đối không gọi `sample_summarize`. Mọi kết luận (kể cả Sổ Bằng Chứng "Lá Phổi") đều xác định hoàn toàn dựa trên kết quả tool và mã nguồn thực tế.

THÔNG TIN ĐẦU VÀO (INPUT):
- Repository: {{REPO_NAME}}
- Định danh của bạn: {{AGENT_ID}} (khớp `TOKEN_CONTEXT_AGENT_ID` nếu có đặt)
- Yêu cầu nhiệm vụ: {{USER_TASK}}

NGUYÊN TẮC CỐT LÕI (XÁC ĐỊNH, LINH HOẠT & KHÔNG TỰ KHÓA):
1. Kết hợp nhịp nhàng MCP và Mã nguồn thực tế:
   - Dùng `token-context-mcp` (`get_repo_map`, `find_symbols`, `search_source`, `get_file_skeleton`, `inspect_symbol`) trước tiên để định vị nhanh symbol và tiết kiệm token.
   - Khi cần đọc toàn bộ thân hàm bị cắt, kiểm tra file cấu hình ngoài chỉ mục AST, hoặc khi snapshot `stale` / lệnh MCP báo lỗi: hãy chủ động đọc trực tiếp vùng file mã nguồn tương ứng. Tuyệt đối KHÔNG dừng sớm hay báo `blocked` chỉ vì một thông tin chưa có sẵn trong kết quả MCP.
2. Bằng chứng xác thực & Lá Phổi ("Evidence Ledger"):
   - Bằng chứng hợp lệ gồm kết quả trả về từ MCP tool HOẶC mã nguồn bạn đã đọc trực tiếp trong phiên.
   - Tận dụng `prior_evidence` từ `get_repo_map(query=...)` / `search_source(query=...)` và ghi `trajectory_record` trên file **`fresh` trước khi sửa**; mọi kết luận hậu chỉnh sửa (`stale`) hoặc ngoài AST thì lưu qua `memory_put`. Không ghi đoán mò.
3. Phân biệt "Dừng Bảo Mật" và "Tự Phục Hồi Kỹ Thuật":
   - CHỈ dừng hẳn khi gặp `HALT_BY_USER` hoặc `ACCESS_DENIED`.
   - Với lỗi tham số (`unknown_repo_id`, `budget_out_of_range`), `stale_file` hoặc timeout: tự sửa lại tham số (gọi `list_repositories()`, giảm budget), bỏ qua ghi ledger cho file `stale`, hoặc đọc file trực tiếp để hoàn thành nhiệm vụ.

QUY TRÌNH THỰC HIỆN:
1. Kiểm tra trạng thái (Pre-flight):
   - Chỉ gọi `list_repositories()` nếu chưa rõ `repo_id`, và gọi `get_index_status(repo_id="{{REPO_NAME}}")` **tối đa 1 lần mỗi session nếu cần** (mọi MCP tool khác đều đã trả `freshness`). Ghi nhận `fresh`/`stale` và `pending_paths` để đối chiếu source và tránh ghi `trajectory_record` vào file `stale`.
2. Nhớ lại từ Shared Memory (nếu có `memory_*`):
   - Tra `memory_get(key="task.progress", scope="session", namespace="{{AGENT_ID}}")` và `memory_search(query="<1-3 từ khóa>", scope="project", limit=5)`. Không có thì bỏ qua ngay.
3. Định vị mã nguồn & Kiểm tra `prior_evidence` (Locate & Lungs):
   - Khi chưa rõ bố cục repo, gọi `get_repo_map(repo_id="{{REPO_NAME}}", query="<>=2 từ khóa ASCII/tên symbol>", budget_tokens=1024)` (dùng `1024` thay cho `4096`) hoặc `search_source(repo_id="{{REPO_NAME}}", query="<>=2 từ khóa ASCII/tên symbol>", profile="locate")` (chỉ hai tool này trả `data.prior_evidence`).
   - Nếu có `prior_evidence`: ưu tiên xác minh trực tiếp `answers` qua `get_symbol_context` / `inspect_symbol`; nếu gặp `prior_evidence_unconfirmed` (`asserted`), tự kiểm tra độc lập; nếu `recheck_from` là `k`, giữ tiền tố `1..k-1` và kiểm chứng từ bước `k`. Tránh `decoys` khi thẻ `confirmed`.
   - Dùng `find_symbols(repo_id="{{REPO_NAME}}", pattern="<Ten*>")` và `get_file_skeleton(repo_id="{{REPO_NAME}}", path="<đường/dẫn>")` khi cần; đọc trực tiếp file ngoài AST.
4. Kiểm tra chi tiết & Chống đọc trùng (Deep Inspection & Anti-Double-Read):
   - Gọi `inspect_symbol(repo_id="{{REPO_NAME}}", query="<ten_symbol>", view="full")`.
   - **Quy tắc chống đọc trùng (Anti-Double-Read):** Nếu `get_file_skeleton` hoặc `inspect_symbol` trả về `freshness="fresh"` và `truncated=false` đã đủ trả lời, **KHÔNG đọc lại cả file**; nếu cần xem thêm dòng liền kề hoặc thân hàm bị cắt, chỉ đọc một dải dòng hẹp (`20–60` dòng) qua `read_file` hoặc `get_symbol_context(..., include_body=true, body_offset_line=...)`.
5. Phân tích tác động (Impact):
   - Gọi `get_impact_slice(repo_id="{{REPO_NAME}}", symbol_id="<id>", direction="callers", depth=2)` và/hoặc `get_module_dependents`.
6. Ghi Lá Phổi (`trajectory_record`) có điều kiện TRƯỚC khi sửa file (nếu bật & file còn `fresh`):
   - **Bỏ qua** trên Q&A chỉ đọc một lượt ngắn gọn; chỉ ghi khi cần lưu bằng chứng xuyên phiên hoặc trước khi sửa code trên mã nguồn còn `fresh`:
     `trajectory_record(repo_id="{{REPO_NAME}}", query="<>=2 từ khóa ASCII/tên symbol>", answers=["<canonical_symbol_id>@<line>"], steps=["<from_symbol_id>><to_symbol_id>@<line>"], decoys=["<symbol_id>!<no_reference|test_only|wrapper_only|unrelated>"], agent_id="{{AGENT_ID}}")`
   - Đảm bảo tên ngắn của `to_symbol` xuất hiện đúng tại dòng `<line>` của `steps`. Nếu file đã `stale`, bỏ qua bước này.
7. Thực hiện thay đổi & Kiểm chứng xác định:
   - Nếu nhiều agent cùng chạy và bật `memory_lock`, khóa trước khi ghi và mở khóa ngay sau khi xong.
   - Đảm bảo mọi `file:line` nêu trong câu trả lời đều đã được xác thực qua kết quả MCP hoặc qua việc đọc trực tiếp file mã nguồn.
   - Nếu có sửa mã và môi trường cho phép chạy test, hãy chạy test liên quan và ghi rõ kết quả thực tế.
8. Ghi nhớ hậu chỉnh sửa (nếu có `memory_put`):
   - Lưu kết luận ngắn gọn (đặc biệt kết quả/trạng thái sau khi đã sửa file khiến file thành `stale`) vào `memory_put` để các phiên sau tái sử dụng. Không gọi lại `trajectory_record` trên file vừa sửa khi chưa re-index.

XỬ LÝ KHI TOOL HẠN CHẾ:
- Nếu bị `POLICY_VIOLATION` (`READ_ONLY`): bỏ qua `memory_put`, `memory_lock`, `memory_unlock`, `memory_consolidate`, `trajectory_record` và xuất trực tiếp patch đề xuất.

QUY CÁCH PHẢN HỒI (OUTPUT FORMAT):
  1. [Vấn đề / Mục tiêu cốt lõi]: Tóm tắt 1-2 câu.
  2. [Vị trí mã nguồn]: Đường dẫn file và dòng code (`file_path:line`).
  3. [Giải pháp / Thay đổi]: Khối code/patch ngắn gọn kèm giải thích.
  4. [Tác động & Kiểm chứng xác định]: Các symbol liên quan và cách đã xác minh (qua MCP tool / đọc file nguồn / chạy test).
  5. [Memory & Ledger]: Key `memory_*` đã dùng/cập nhật + trạng thái `prior_evidence` & `trajectory_record` (hoặc lý do bỏ qua).
  6. [Trạng thái]: "Hoàn thành" (hoặc lý do cụ thể nếu cần thêm thông tin từ người dùng).
```

### 3.3 Mẫu Prompt Gọn Cho Các Lượt Tiếp Theo Trong Cùng Session (Follow-up Turns)

> 💡 **Tối ưu Context Window**: Sau khi Agent đã được khởi tạo bằng prompt đầy đủ ở Lượt 1 (Turn 1), trong các lượt tiếp theo (Turn 2, Turn 3...) của cùng một phiên làm việc, **tuyệt đối KHÔNG gửi lại toàn bộ prompt dài**. Việc nhồi lại toàn bộ prompt sẽ lãng phí hàng nghìn token input không cần thiết và đẩy trôi ngữ cảnh quan trọng.
> Chỉ cần dùng mẫu siêu gọn dưới đây để nhắc lại nguyên tắc gọi tool, chu trình Lá Phổi (`prior_evidence` / `trajectory_record`) và giữ cấu trúc phản hồi chuẩn hóa:

*(Dùng cho Turn 2 trở đi trong cùng session làm việc)*:

```markdown
TIẾP TỤC NHIỆM VỤ (SESSION FOLLOW-UP):
- Repository: {{REPO_NAME}} | Agent: {{AGENT_ID}}
- Nhiệm vụ lượt này: {{USER_TASK}}

NGUYÊN TẮC HOẠT ĐỘNG:
1. Ưu tiên MCP có chọn lọc & Chống đọc trùng: Dùng `get_repo_map(budget_tokens=1024)` (chỉ nếu cần), `search_source`, `find_symbols`, `inspect_symbol`, `get_file_skeleton`; không gọi lặp `get_index_status` (mọi tool đều trả `freshness`). Nếu `get_file_skeleton` / `inspect_symbol` trả `fresh` và `truncated=false` đã đủ trả lời, **KHÔNG đọc lại cả file**; nếu cần, chỉ đọc dải dòng hẹp (`20–60` dòng).
2. Chu trình Lá Phổi (Lungs) có điều kiện: Khi gọi `get_repo_map(query=...)` / `search_source(query=...)`, tận dụng `prior_evidence` (giữ tiền tố `1..k-1` và kiểm chứng từ `recheck_from=k` nếu có). Chỉ gọi `trajectory_record` (`>=2` từ khóa ASCII, mã decoy hợp lệ, `agent_id="{{AGENT_ID}}"`) khi lưu bằng chứng xuyên phiên hoặc trước khi sửa file `fresh` — **bỏ qua** trên Q&A chỉ đọc một lượt ngắn.
3. Fallback & Lưu hậu chỉnh sửa: Nếu thân hàm bị cắt, file ngoài AST, hoặc snapshot `stale`, đọc trực tiếp dải dòng liên quan (không báo blocked). Sau khi sửa file (`stale`) hoặc với kết luận ngoài AST, lưu vào `memory_put` (không gọi `trajectory_record` lên file chưa re-index) và chạy test liên quan.

QUY CÁCH PHẢN HỒI (OUTPUT FORMAT):
1. [Vấn đề / Mục tiêu]: Tóm tắt 1-2 câu.
2. [Vị trí mã nguồn]: `file_path:line`.
3. [Giải pháp / Thay đổi]: Khối code/patch ngắn gọn kèm giải thích.
4. [Tác động & Kiểm chứng]: Symbol liên quan và bằng chứng xác minh (MCP/đọc file/test).
5. [Memory & Ledger]: Key `memory_*` và trạng thái `prior_evidence` / `trajectory_record` (hoặc lý do bỏ qua).
6. [Trạng thái]: "Hoàn thành" (hoặc lý do cụ thể nếu cần làm rõ).
```

## 4. Ví dụ chạy thật

Cấu trúc phản hồi dưới đây lấy từ lần chạy thật `MemoryService`, `search_tools`, `LedgerService` và quy trình kết hợp đọc mã nguồn.

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
  ... xác nhận logic ở src/auth/tokens.py:88 đúng như mô tả ...

Bước 4b: Linh hoạt đọc file cấu hình ngoài AST index (.env.example)
  -> File `.env.example` không phải là file code AST trong `find_symbols`.
  -> Thay vì báo blocked, Agent chủ động đọc trực tiếp file `.env.example` để kiểm tra biến `REFRESH_TOKEN_TTL_DAYS=7`.

Bước 8-9: Sửa src/auth/tokens.py (file thành `stale`) rồi ghi trạng thái sau sửa vào memory_put
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

### Ví dụ 5: Vòng đời Lá Phổi — Đọc `prior_evidence` + `recheck_from`, ghi `trajectory_record` lúc `fresh`, hậu chỉnh sửa dùng `memory_put`

```text
Bước 3: Định vị bằng search_source (trả về thẻ prior_evidence có sẵn)
> search_source(repo_id="myrepo", query="refresh token revoke", profile="locate")
< {
    "ledger_rev": 1,
    "warnings": ["prior_evidence_unconfirmed"],
    "data": {
      "prior_evidence": {
        "ledger_rev": 1,
        "match": 1.0,
        "status": "asserted",
        "answers": [["python:src/auth/tokens.py:TokenManager.revoke_old:a1b2c3d4", "src/auth/tokens.py", 88, "valid"]],
        "steps": [["TokenManager.refresh", "TokenManager.build_pair", "src/auth/tokens.py", 65, "valid"]],
        "decoys": [],
        "recheck_from": 2
      },
      "matches": [...]
    }
  }
  -> Cảnh báo `prior_evidence_unconfirmed` báo thẻ mới ở trạng thái `asserted`; `recheck_from: 2` cho thấy bước 1 vẫn hợp lệ trên đĩa, bước 2 đã lệch.

Bước 4: Giữ tiền tố bước 1, nhảy thẳng vào get_symbol_context để kiểm chứng bước 2 & answer trên file `fresh`
> get_symbol_context(repo_id="myrepo", symbol_id="python:src/auth/tokens.py:TokenManager.revoke_old:a1b2c3d4", depth=1, include_body=true)
  -> Xác nhận dòng 72 trong TokenManager.refresh gọi `self.revoke_old(...)` và hàm revoke_old nằm tại dòng 88.

Bước 6: Ghi nhận lại vào Lá Phổi TRƯỚC KHI SỬA FILE (khi src/auth/tokens.py vẫn `fresh`)
> trajectory_record(
    repo_id="myrepo",
    query="refresh token revoke",
    answers=["python:src/auth/tokens.py:TokenManager.revoke_old:a1b2c3d4@88"],
    steps=["python:src/auth/tokens.py:TokenManager.refresh:e5f6a7b8>python:src/auth/tokens.py:TokenManager.revoke_old:a1b2c3d4@72"],
    decoys=["python:src/auth/helpers.py:format_token_ttl:9c0d1e2f!wrapper_only"],
    agent_id="agent_1"
  )
< {"schema_version": "1.0", "repo_id": "myrepo", "data": {"card_id": 1, "status": "confirmed", "ledger_rev": 2, "verified_count": 3, ...}}
  -> Do một `run_id` khác xác nhận lại đúng `answers`, thẻ được nâng cấp từ `asserted` lên `confirmed`!

Bước 8-9: Sửa file src/auth/tokens.py -> file chuyển sang `stale` so với index
  -> Không gọi `trajectory_record` lên src/auth/tokens.py lúc này (Gate G3 sẽ từ chối `stale_file`).
  -> Ghi kết luận đã sửa vào `memory_put`:
> memory_put(key="auth_module.refresh_token", scope="project", namespace="repo:myrepo", ttl=604800,
              value={"finding": "TokenManager.refresh da goi revoke_old dung", "where": "src/auth/tokens.py:72", "status": "fixed"})
```

## 5. Hướng Dẫn Chọn Mức Độ Suy Luận (Reasoning Level / Thinking Budget)

| Mức suy luận | Nhóm mô hình gợi ý | Dạng tác vụ phù hợp | Lý do kỹ thuật |
| :--- | :--- | :--- | :--- |
| **MỨC THẤP**<br>*(Low / Minimal)* | Mô hình nhỏ, nhanh (Haiku, Gemini Flash/Hydrogen, GPT mini) | • Tra cứu vị trí hàm, class, interface (`find_symbols`)<br>• Kiểm tra trạng thái index (`get_index_status`)<br>• Đọc lại kết luận đã lưu (`memory_get`) hoặc theo dấu `prior_evidence` khớp sẵn<br>• Giải thích đoạn code ngắn hoặc sửa lỗi nhỏ trong 1 hàm | Không cần suy luận đa bước; server đã cung cấp sẵn vị trí và thông tin chính xác. |
| **MỨC TRUNG BÌNH**<br>*(Medium / Standard)* | Mô hình tiêu chuẩn (Sonnet, Gemini Neon/Pro, GPT tiêu chuẩn) | • Thêm tính năng trong 1-2 module<br>• Refactor nội bộ không đổi public API<br>• Sửa bug nghiệp vụ kết hợp `inspect_symbol`, `get_impact_slice`, đọc file nguồn và cập nhật `trajectory_record`<br>• Viết unit test cho các hàm cụ thể | Cần xâu chuỗi thông tin giữa 2-4 lượt gọi tool và đối chiếu memory/ledger với mã nguồn. |
| **MỨC CAO**<br>*(High / Extended / Deep)* | Mô hình suy luận sâu (Opus, Gemini Neon High/XHigh, Extended Thinking, OpenAI o-series) | • Debug lỗi phức tạp (race condition, memory leak, deadlock)<br>• Tái cấu trúc kiến trúc lớn có quan hệ phụ thuộc rộng (`get_module_dependents`)<br>• Điều phối nhiều agent sửa chung một repo (`memory_lock`, `memory_consolidate`) | Đòi hỏi tạo giả thuyết, suy luận đa nhánh và duyệt đồ thị tác động sâu trên toàn hệ thống. |

---

# PART 2: ENGLISH SECTION

## 1. Tool List

The server registers 21 standard tools (10 core + 11 extension), plus 2 admin tools when enabled (`--enable-admin-tools`) for 23 total. Extension tools require `enable_extensions = true` in `repos.toml`. The Verified Evidence Ledger (`[ledger].enabled = true` in `repos.toml`) is **ON by default**, automatically attaching verified `prior_evidence` hints to `get_repo_map(query=...)` and `search_source(query=...)`.

### 1.1 Core tools (10 tools, always available)

| Category | Tool | Use when | Main parameters (`*` = required) |
| :--- | :--- | :--- | :--- |
| `repository_admin` | `list_repositories` | Get a valid short `repo_id`. Call first when unsure of the `repo_id` | none |
| `repository_admin` | `get_index_status` | Check the snapshot (freshness, file/symbol counts, paths changed since indexing) | `repo_id*` |
| `code_navigation` | `get_repo_map` | Orient in an unfamiliar repo: symbols ranked by PageRank within a token budget (returns `prior_evidence` when `query` is set) | `repo_id*`, `query`, `budget_tokens`, `format`, `profile` |
| `code_navigation` | `find_symbols` | Find symbols by name or qualified name; returns `symbol_id` and location | `repo_id*`, `pattern*` (supports `*` `?`), `kind`, `limit` |
| `code_navigation` | `search_source` | Full-text FTS5 search over code bodies, ranked by enclosing symbol (returns `prior_evidence`) | `repo_id*`, `query*`, `profile`, `limit`, `expand` |
| `code_navigation` | `get_file_skeleton` | See a file's outline (imports, signatures, bodies elided) instead of reading the whole file | `repo_id*`, `path*`, `include_private` |
| `impact_analysis` | `get_symbol_context` | Bounded source packet for one symbol plus its graph neighbourhood | `repo_id*`, `symbol_id*`, `depth`, `include_body`, `body_offset_line` |
| `impact_analysis` | `get_impact_slice` | Traverse observed caller/callee edges from a symbol (candidate impact) | `repo_id*`, `symbol_id*`, `direction`, `depth`, `min_confidence` |
| `impact_analysis` | `get_module_dependents` | Import relationships of a module or path: who imports it, what it imports | `repo_id*`, `module` or `path` |
| `impact_analysis` | `inspect_symbol` | One-turn composite: resolve the symbol, definition, immediate 1-hop graph | `repo_id*`, `query*`, `view`, `budget_tokens` |

### 1.2 Extension tools (11 tools, need `enable_extensions = true`)

| Category | Tool | Use when | Main parameters (`*` = required) |
| :--- | :--- | :--- | :--- |
| `tool_discovery` | `list_available_tools` | Compact catalog grouped by category | `category` |
| `tool_discovery` | `search_tools` | Find a tool by English keywords; returns `relevance_score` | `query*`, `limit` (default 3) |
| `tool_discovery` | `get_tool_schema` | Full JSON schema of one specific tool when needed | `tool_name*` |
| `shared_memory` | `memory_search` | Full-text search in `memory.sqlite` when you do not know the key | `query*`, `scope`, `namespace`, `limit` (default 5) |
| `shared_memory` | `memory_get` | Read one entry in `memory.sqlite` when you know the exact key | `key*`, `scope`, `namespace`, `session_id` |
| `shared_memory` | `memory_put` | Store conclusions, post-edit fix status, checkpoints, hand-off data between agents | `key*`, `value*`, `scope`, `namespace`, `ttl`, `session_id` |
| `shared_memory` | `memory_consolidate` | Merge up to 500 oldest entries into one `global` summary | `scope`, `namespace`, `target_key`, `prune_transient` |
| `shared_memory` | `memory_lock` | Time-limited soft-mutex lock on a resource when several agents edit | `resource_key*`, `agent_id*`, `timeout_sec` (60) |
| `shared_memory` | `memory_unlock` | Release a lock you hold | `resource_key*`, `agent_id` |
| `sampling_inference` | `sample_summarize` | Compress large text into short JSON (local model if available, otherwise deterministic AST extraction) | `text*`, `intent`, `max_tokens` (512), `target_symbols` |
| `memory_state` | `trajectory_record` | Record a verified navigation card (`answers`, `steps`, `decoys`) from `fresh` files into the Evidence Ledger ("Lungs") | `repo_id*`, `query*`, `answers*`, `steps`, `decoys`, `agent_id` |

> **Note on `sample_summarize`:** A machine with a local LLM (Ollama) returns `backend` `ollama_gpu` or `ollama_cpu`. A machine without an LLM returns `backend` `heuristic_fallback` (`engine` `deterministic_ast_extractor`) with no error. On that fallback branch, rely on `critical_constraints` (with `verbatim_quote` and `line`) and verify against the source code.
>
> **Note on `trajectory_record`:** This tool lives in category `memory_state` and does **not** accept a `ttl_days` parameter (card TTL is a server-side setting under `[ledger].ttl_days = 28` in `repos.toml`). All submissions pass through Write Gate G1–G6 (which requires `fresh` indexed files).

### 1.3 Admin tools (2 tools, need `enable_extensions` and `enable_admin_tools`)

`agent_control` (`security_governance`: `status`, `pause`, `resume`, `block`, `unblock`, `set_policy`, `revoke_locks`, `emergency_halt`, `emergency_resume`, requires `admin_token`) and `audit_logs` (`limit`, `agent_id`, `status`). Reserved for operators.

### 1.4 Common Call Chains & Adaptive Transitions

| Chain | Reason |
| :--- | :--- |
| `get_repo_map(query=...)` or `search_source(query=...)` (`prior_evidence`) → `get_symbol_context` / `inspect_symbol` → `trajectory_record` *(before editing, on `fresh` files)* | Check verified hints before broad searches (`find_symbols` does **not** return `prior_evidence`). If `recheck_from` is integer `k`, keep prefix `1..k-1` and re-verify from step `k` onward |
| `list_repositories` → `get_index_status` | Get a short `repo_id` and check snapshot freshness |
| `find_symbols` → `get_symbol_context` or `get_impact_slice` | The latter two need a `symbol_id` (`inspect_symbol` takes a name directly) |
| `inspect_symbol` / `get_file_skeleton` → *(Targeted native file read when editing)* | Use MCP to localize rapidly, then read exact surrounding file lines if truncated or needed for safe patching |
| `memory_search` or `memory_get` → (verify with `inspect_symbol` or source) → `memory_put` | Recall, verify against real code, then update conclusions or post-edit status |
| `memory_lock` → edit → `memory_unlock` | Coordinate concurrent edits across multiple agents |

## 2. Memory & Verified Evidence Ledger ("Lungs") Conventions

### 2.1 Shared Memory (`memory.sqlite`)

Entries are persisted in `memory.sqlite` next to `repos.toml`. Suggested conventions:

| Kind of information | `scope` | `namespace` | `key` | `ttl` (seconds) |
| :--- | :--- | :--- | :--- | :--- |
| One agent's progress checkpoint | `session` | `<agent_id>` | `task.progress` | 3600 |
| Conclusions about code (bugs, post-edit status, non-AST configs) | `project` | `repo:<REPO_NAME>` | `<module>.<topic>` | 604800 (7 days) |
| Long-lived architecture decisions | `project` | `repo:<REPO_NAME>` | `decision.<topic>` | 0 (never expires) |
| Consolidated summary (written by `memory_consolidate`) | `global` | empty | `project_architectural_insights` | never expires |

`value` should be compact JSON holding pointers and conclusions: `{"finding": "...", "where": "path:line", "symbol_id": "...", "status": "open|fixed"}`.

Key notes:

1. `scope` is a partition label (`session`, `project`, `global`); use `namespace` or `session_id` to isolate entries per agent or repository.
2. `memory_get` requires matching `scope`, `namespace`, and `key`. `memory_search` with an empty `namespace` searches across all namespaces.
3. Both `memory_get` and `memory_put` accept `session_id` (when `scope='session'` and `namespace` is empty, the server automatically isolates under that session).
4. `memory_search` joins FTS5 keywords with AND and returns `value` inline. Use 1–3 short keywords and a small `limit`.
5. `ttl` defaults to 86400 seconds (1 day). `ttl=0` (or `<= 0` / `null`) means never expires.
6. Keys are at most 256 bytes and values at most 1 MB. Never store secrets or full function bodies in memory.
7. `memory_consolidate` merges up to **500** oldest active entries of a `scope` (optionally filtered by `namespace`) into `scope="global"`. Keep `prune_transient=false` by default.
8. `memory_lock` returns `acquired: true/false` immediately with `held_by` and `remaining_sec`. Locks expire automatically after `timeout_sec`.
9. `memory_unlock` must pass the same `agent_id` used to acquire the lock (`agent_id` must match `^[a-zA-Z0-9_-]{1,64}$`).

### 2.2 Verified Evidence Ledger ("Lungs" — `ledger.sqlite`)

The Evidence Ledger (`ledger.sqlite` next to `repos.toml`) serves a distinct role from `memory.sqlite`:

| Mechanism | What to store | Conditions & Write Timing | How it is read |
| :--- | :--- | :--- | :--- |
| **`trajectory_record`** *(Lungs — `ledger.sqlite`)* | Source-verified AST navigation cards (`answers`, `steps`, `decoys`) backed by disk body SHA-256 | Accepts ONLY symbols in **`fresh`** files. Call **once paths are verified and BEFORE editing those files**, on read-only investigations, or after re-indexing returns files to `fresh` | Automatically attached in `data.prior_evidence` on `get_repo_map(query=...)` and `search_source(query=...)` |
| **`memory_put`** *(Shared Memory — `memory.sqlite`)* | Bug findings, design rationale, **post-edit fix status** (when edited files become `stale`), and non-AST files (`.toml`, `.yaml`, `.env`, `.md`) | Writable anytime (including after files are edited / `stale` or outside AST coverage) | Explicitly queried via `memory_get` or `memory_search` |

#### Write Gate G1–G6 Rules (`trajectory_record`):
1. **ASCII Query Signature (`signature.py`):** Tokenization matches `[a-zA-Z0-9_]+`, applies Porter stemming, and strips stopwords. Read matching requires **`answer_min_overlap >= 2`** and **`answer_jaccard_min >= 0.6`**. Always pass **`>= 2` meaningful ASCII English/code-identifier keywords** in `query` matching how you query `get_repo_map(query=...)` / `search_source(query=...)`. *(Non-ASCII-only text yields `empty_signature`!)*
2. **Strict Item Formats & Limits (`gate.py`):**
   - `answers` *(required, max **8**)*: `"<canonical_symbol_id>@<line>"` (`start_line <= line <= end_line`). At least **1** answer must verify or the entire card gets `status: "rejected"` (`card_id: null`).
   - `steps` *(optional, max **12**)*: `"<from_symbol_id>><to_symbol_id>@<line>"` (`from != to`, `line` inside `from_symbol`'s line span, AND **Gate G4**: `to_sym.name` short identifier must literally appear on that exact disk line, else `evidence_mismatch`).
   - `decoys` *(optional, max **8**)*: `"<symbol_id>!<reason_code>"` (or `"<from_symbol_id>><to_symbol_id>!no_reference"` for `source_verified` validation). `reason_code` **MUST** be one of the 4 fixed enum values: **`no_reference`**, **`test_only`**, **`wrapper_only`**, **`unrelated`** *(free text fails with `invalid_reason_code`)*.
3. **Freshness Timing Rule (`stale_file` trap):** Gate G3 verifies disk freshness per file and rejects un-reindexed modified files with `reason: "stale_file"`. Always call `trajectory_record` **while target files are `fresh` — BEFORE editing them**; **after editing**, record conclusions in `memory_put` rather than retrying `trajectory_record` on `stale` files.
4. **Identity & Rate Limit:** Pass `agent_id="{{AGENT_ID}}"` (matching `TOKEN_CONTEXT_AGENT_ID` if set). Rate limit is **10 calls/min per `agent_id`** (`limit_exceeded`).

#### Card Lifecycle & Read-Time `prior_evidence` / `recheck_from`:
- **Lifecycle:** First verified submission creates `asserted` (`confirmations=1`). A second independent `run_id` recording identical `answers` promotes the card to `confirmed` (enabling `decoys` and ranking overlay). Disagreeing `answers` across runs (or an answer colliding with an existing decoy) flip the card to `conflicted` (no longer served). **Never record unverified guesses.**
- **Read-Time (`get_repo_map` with non-empty `query`, and `search_source`):**
  - `find_symbols` does **not** return `prior_evidence`.
  - `prior_evidence.status` is either `"asserted"` (emits warning `prior_evidence_unconfirmed` and `decoys: []`) or `"confirmed"` (includes `decoys` when `match >= 0.8`).
  - `answers` (`[[symbol_id, path, line, "valid"], ...]`): if all answers changed on disk, the server auto-retires the card (`retired`) and omits `prior_evidence`.
  - `recheck_from`: `null` when all `steps` verify cleanly, or a **1-based integer `k`** pointing to the first changed/missing step — preserve verified prefix `1..k-1` and re-verify starting from step `k`.

## 3. Agent Prompt Templates (Adaptive & Non-Blocking Design)

### 3.0 Lean Selective Prompt — Recommended Default

*(Recommended lightweight default for daily Antigravity, Cursor, Claude Code, or CLI sessions — under 400 prompt tokens, with inline 5-tool signatures to skip `.json` schema reads and prevent whole-file double-reads.)*

```markdown
Repo: {{REPO_NAME}} | Agent: {{AGENT_ID}}
Task: {{USER_TASK}}

Rules (Lean Selective MCP; read unindexed/stale files directly; cite path:line):
1. Selective Dispatch:
   - Exact file path given: skip list_repositories/get_repo_map/search_source. Use get_file_skeleton(repo_id, path, max_tokens=1024) for interface/signatures, or read_file for short files (<300 lines) needing full implementation.
   - Unknown location / behavior / cross-module trace: call 1 MCP tool (search_source, inspect_symbol, or get_impact_slice) with budget 1024-1536.
2. Anti-Double-Read:
   - If get_file_skeleton or inspect_symbol returns freshness="fresh" & truncated=false and answers the task, STOP—do NOT read_file the whole file. Read ONLY a 20-60 line window if finer detail is needed.
3. Zero-Ritual Budget:
   - Do not repeat get_index_status (tools already return freshness). Call get_repo_map(budget_tokens=1024) at most once only if repo layout is unknown. trajectory_record/memory_put are opt-in (multi-session or requested; skip on one-shot Q&A).
4. 5-Tool Cheat-Sheet (call directly; skip .json schema files unless error):
   - search_source(repo_id, query, profile="locate", max_tokens=1280, limit=15)
   - get_file_skeleton(repo_id, path, include_private=false, max_tokens=1536)
   - inspect_symbol(repo_id, query, view="full", budget_tokens=1536)
   - get_impact_slice(repo_id, symbol_id, direction="both", depth=2, max_tokens=1536)
   - get_repo_map(repo_id, query=None, budget_tokens=1024, format="compact")
```

### 3.1 Machine with a local LLM (Ollama GPU/CPU)

*(Copy the block below, fill in `{{REPO_NAME}}`, `{{USER_TASK}}`, and `{{AGENT_ID}}`, then send it to the agent)*

```markdown
You are an expert software engineer with access to the `token-context-mcp` server alongside your workspace's standard file reading and editing tools.

INPUT:
- Repository: {{REPO_NAME}} (prefer the registered short `repo_id`)
- Your identifier: {{AGENT_ID}} (must match `TOKEN_CONTEXT_AGENT_ID` when configured on the server; used for locks, memory, and `trajectory_record`)
- Task: {{USER_TASK}}

CORE PRINCIPLES (ADAPTIVE & NON-BLOCKING):
1. MCP-First for Localization, Seamless Source Fallback for Execution:
   - Always prioritize `token-context-mcp` tools (`get_repo_map`, `find_symbols`, `search_source`, `get_file_skeleton`, `inspect_symbol`) first to orient rapidly and save 60-95% of tokens instead of blindly scanning the entire repository.
   - HOWEVER, NEVER mark your task as `blocked` or stop prematurely if an MCP call does not return everything you need! Smoothly fall back to targeted direct file reads (reading specific line ranges or files using your environment's file/search tools) whenever:
     a) The target is a configuration, script, or documentation file outside the AST index (`.toml`, `.yaml`, `.json`, `.md`, `.sql`, `.sh`, etc.) or a newly created file;
     b) MCP results are `truncated`, have `ambiguous` edges, report a `stale` snapshot, or return 0 symbol matches;
     c) You need exact surrounding lines in the source file to craft and apply a clean code patch safely.
2. Separate Memory (`memory_*`) from the Lungs (`trajectory_record` / `prior_evidence`), and Treat Source Code as Truth:
   - Check `memory_*` for leads and inspect `prior_evidence` from `get_repo_map(query=...)` / `search_source(query=...)`, but always verify against current source code.
   - The Lungs (`trajectory_record`) only accept verified paths on **`fresh`** files—NEVER record unverified guesses and NEVER force `trajectory_record` onto already-edited `stale` files. Store post-edit conclusions and non-AST findings in `memory_put`.
3. Distinguish "Hard Security Stops" from "Soft Technical Recovery":
   - ONLY stop immediately and report to the user on explicit administrative blocks: `HALT_BY_USER` or `ACCESS_DENIED` (never spoof `agent_id` or claim `admin`).
   - For any technical error (`unknown_repo_id`, `budget_out_of_range`, `stale_file`, timeout, or unavailable extension tools): self-recover by adjusting parameters (e.g., call `list_repositories()` for short ID, lower `budget_tokens`, skip ledger writes for `stale` files) or fall back to reading workspace files directly to complete the task.

SMOOTH WORKFLOW:
0. Tool discovery (optional, only when unsure which tool fits):
   - Call `search_tools(query="<English keywords close to tool names>", limit=2)` or `list_available_tools(category="<group>")` (note `trajectory_record` is under `memory_state`). If extension tools are disabled, proceed directly to Step 1.
1. Lightweight Pre-flight:
   - Call `list_repositories()` if unsure of `repo_id`, then `get_index_status(repo_id="{{REPO_NAME}}")`.
   - If `fresh`: rely on graph tools and the Lungs confidently. If `stale`: use graph results as candidate leads, cross-check `pending_paths` directly on disk, and skip `trajectory_record` on those stale files.
2. Recall Shared Memory (when `memory_*` tools are enabled):
   - Check `memory_get(key="task.progress", scope="session", namespace="{{AGENT_ID}}")` and `memory_search(query="<1-3 keywords>", scope="project", limit=5)`. On `not_found` or 0 matches, move immediately to Step 3.
3. Orient & Consult the Lungs (`prior_evidence`):
   - Call `get_repo_map(repo_id="{{REPO_NAME}}", query="<>=2 ASCII/symbol keywords>")` and/or `search_source(repo_id="{{REPO_NAME}}", query="<>=2 ASCII/symbol keywords>", profile="locate")`—note only these two attach `data.prior_evidence` (`find_symbols` does not).
   - If `data.prior_evidence` is present, inspect it BEFORE broad searches:
     * Jump straight to `get_symbol_context(repo_id="{{REPO_NAME}}", symbol_id="<id_from_answers>")` or `inspect_symbol` to verify `answers`.
     * If `warnings` contains `prior_evidence_unconfirmed` (`status: "asserted"`), verify independently against source before relying on it.
     * If `recheck_from` is integer `k`, keep the verified prefix `steps[0..k-2]` and re-verify starting from step `k`.
     * Avoid entries listed in `decoys` (present when `status: "confirmed"`).
   - Combine with `find_symbols(repo_id="{{REPO_NAME}}", pattern="<Name*>")` and `get_file_skeleton(repo_id="{{REPO_NAME}}", path="<path/to/file>")` as needed, or read unindexed configs directly.
4. Deep Inspection & Targeted Source Reading:
   - Call `inspect_symbol(repo_id="{{REPO_NAME}}", query="<symbol_name>", view="full")` for a one-turn packet (signature, body, 1-hop callers/callees).
   - If the body is truncated (`truncated_lines`) or before editing a file: read additional windows via `get_symbol_context(..., include_body=true, body_offset_line=...)` or read the exact line span directly from the source file.
5. Impact & Dependencies:
   - When modifying shared logic or signatures: call `get_impact_slice(repo_id="{{REPO_NAME}}", symbol_id="<id>", direction="callers", depth=2)` and/or `get_module_dependents`. Spot-check critical callers if ambiguous edges are reported.
6. Record Verified Lungs Evidence BEFORE Editing (while target files are `fresh`):
   - When `trajectory_record` is enabled and you have verified the path on `fresh` files, call it NOW before editing (or at the end of read-only tasks):
     `trajectory_record(repo_id="{{REPO_NAME}}", query="<>=2 ASCII English/symbol keywords matching lookup>", answers=["<canonical_symbol_id>@<line>"], steps=["<from_symbol_id>><to_symbol_id>@<line>"], decoys=["<symbol_id>!<no_reference|test_only|wrapper_only|unrelated>"], agent_id="{{AGENT_ID}}")`
   - Rules: in `steps`, `to_symbol`'s short name must appear verbatim on `<line>`; `decoys` must use one of the 4 valid reason codes; pass only the listed parameters. Skip if target files are already `stale`.
7. Distill (optional):
   - For large text blocks or logs, call `sample_summarize(text="<...>", intent="<goal>", max_tokens=512)`. If `backend: heuristic_fallback` is returned, rely on `critical_constraints` and verify against the code.
8. Coordinate Locks & Apply Edits:
   - In multi-agent runs with `memory_lock` available: call `memory_lock(resource_key="<module or file>", agent_id="{{AGENT_ID}}", timeout_sec=120)`. If `acquired: false`, prepare your analysis/patch first and retry before writing; release immediately with `memory_unlock` when done. Run relevant tests when permitted.
9. Post-Edit Write-Back (`memory_put`):
   - Once files are edited, they become `stale` relative to the index: do NOT retry `trajectory_record` on modified files unless the repo has been re-indexed back to `fresh`. Instead, persist conclusions and fix status via `memory_put(key="<module>.<topic>", value={"finding": "...", "where": "path:line", "symbol_id": "...", "status": "fixed"}, scope="project", namespace="repo:{{REPO_NAME}}", ttl=604800)`.

WHEN TOOLS ARE RESTRICTED:
- No `search_tools` / `memory_*` / `trajectory_record` (`enable_extensions = false`): skip extension steps and combine the 10 core MCP tools with standard file reads/edits (still read `prior_evidence` when `[ledger].enabled = true`).
- `POLICY_VIOLATION` (`READ_ONLY` agent): skip write/restricted tools (`memory_put`, `memory_lock`, `memory_unlock`, `memory_consolidate`, `sample_summarize`, `trajectory_record`) and include your findings and patches directly in your response.
- `HALT_BY_USER` or `ACCESS_DENIED`: stop immediately and inform the user.

OUTPUT FORMAT:
- Concise, precise, and solution-oriented:
  1. [Core Issue / Goal]: 1-2 clear summary sentences.
  2. [Location]: Exact file paths and line ranges (`path/to/file:line`).
  3. [Solution / Changes]: Minimal code diff or applied changes with brief rationale.
  4. [Impact & Verification]: Affected symbols/modules and how you verified them (via MCP, direct source read, or tests).
  5. [Memory & Ledger]: `memory_*` keys read/updated + `prior_evidence` (`hit` / `recheck_from`) & `trajectory_record` status (or skip reason such as `stale_file` / `READ_ONLY`).
  6. [Status]: "Done" (or "Needs Clarification" only if user requirements are genuinely ambiguous).
```

### 3.2 Machine without a local LLM (Pure CPU / Deterministic)

*(Use this block on machines without a local Ollama model. Every check—including the Verified Evidence Ledger ("Lungs")—is 100% deterministic over SQLite, AST, SHA-256, and direct source reading, so tasks never stall in a `blocked` state.)*

```markdown
You are an expert software engineer with access to the `token-context-mcp` server and your workspace's file reading/editing tools. This machine has NO local LLM for the MCP server: do not call `sample_summarize`. Every check—including the Verified Evidence Ledger ("Lungs")—is deterministic, grounded in tool outputs and actual source code.

INPUT:
- Repository: {{REPO_NAME}}
- Your identifier: {{AGENT_ID}} (must match `TOKEN_CONTEXT_AGENT_ID` when set)
- Task: {{USER_TASK}}

CORE PRINCIPLES (DETERMINISTIC, ADAPTIVE & NON-BLOCKING):
1. Synergy Between MCP and Direct Source Code:
   - Use `token-context-mcp` (`get_repo_map`, `find_symbols`, `search_source`, `get_file_skeleton`, `inspect_symbol`) first to localize symbols quickly and save tokens.
   - Whenever you need full truncated bodies, need to inspect unindexed config/script files, or encounter a `stale` snapshot or MCP error: smoothly read the target source files directly. NEVER abort early or mark the task `blocked` simply because an item was not in the MCP index.
2. Deterministic Evidence & the Lungs:
   - Valid evidence includes both `token-context-mcp` tool outputs AND source code lines you read directly during this session.
   - Reuse `prior_evidence` from `get_repo_map(query=...)` / `search_source(query=...)` and call `trajectory_record` on **`fresh` files BEFORE editing**; store post-edit (`stale`) conclusions and non-AST findings in `memory_put`. Never record guesses.
3. Distinguish "Hard Security Stops" from "Soft Technical Recovery":
   - ONLY halt on `HALT_BY_USER` or `ACCESS_DENIED`.
   - On parameter errors (`unknown_repo_id`, `budget_out_of_range`), `stale_file`, or timeouts: fix the parameters (`list_repositories()`, reduce budget), skip ledger writes on `stale` files, or read workspace source files directly to finish the job.

WORKFLOW:
1. Pre-flight:
   - Call `list_repositories()` only if unsure of `repo_id`, and call `get_index_status(repo_id="{{REPO_NAME}}")` **at most once per session if needed** (all other MCP tool responses already carry `freshness`). Note `fresh`/`stale` and `pending_paths` so you cross-check modified files and avoid calling `trajectory_record` on stale files.
2. Recall Shared Memory (if `memory_*` is enabled):
   - Check `memory_get(key="task.progress", scope="session", namespace="{{AGENT_ID}}")` and `memory_search(query="<1-3 keywords>", scope="project", limit=5)`. Skip if unavailable or empty.
3. Orient, Locate & Check `prior_evidence` (Lungs):
   - Only if repo layout is unknown, call `get_repo_map(repo_id="{{REPO_NAME}}", query="<>=2 ASCII/symbol keywords>", budget_tokens=1024)` (use `1024` instead of `4096`) or `search_source(repo_id="{{REPO_NAME}}", query="<>=2 ASCII/symbol keywords>", profile="locate")` (only these two return `data.prior_evidence`).
   - If `prior_evidence` hits: verify `answers` directly via `get_symbol_context` / `inspect_symbol`; treat `prior_evidence_unconfirmed` (`asserted`) cautiously; on `recheck_from = k`, keep prefix `1..k-1` and re-verify from step `k`. Skip `decoys` when `confirmed`.
   - Also use `find_symbols(repo_id="{{REPO_NAME}}", pattern="<Name*>")` and `get_file_skeleton(repo_id="{{REPO_NAME}}", path="<path/to/file>")`, or read unindexed files directly.
4. Deep Inspection & Anti-Double-Read:
   - Call `inspect_symbol(repo_id="{{REPO_NAME}}", query="<symbol_name>", view="full")`.
   - **Anti-Double-Read Rule:** If `get_file_skeleton` or `inspect_symbol` returns `freshness="fresh"` and `truncated=false` and answers the task, **do NOT re-read the whole file**; if extra context is needed, read only a narrow line range (`20–60` lines) via `read_file` or `get_symbol_context(..., include_body=true, body_offset_line=...)`.
5. Impact:
   - Call `get_impact_slice(repo_id="{{REPO_NAME}}", symbol_id="<id>", direction="callers", depth=2)` and/or `get_module_dependents`.
6. Conditionally Record Verified Lungs Evidence BEFORE Editing (if enabled & files are `fresh`):
   - **Skip** on short read-only single-turn Q&A; use when persisting verified evidence across sessions or before editing `fresh` files:
     `trajectory_record(repo_id="{{REPO_NAME}}", query="<>=2 ASCII/symbol keywords>", answers=["<canonical_symbol_id>@<line>"], steps=["<from_symbol_id>><to_symbol_id>@<line>"], decoys=["<symbol_id>!<no_reference|test_only|wrapper_only|unrelated>"], agent_id="{{AGENT_ID}}")`
   - Ensure `to_symbol`'s short name appears on `<line>` in `steps`. Skip if target files are `stale`.
7. Apply Changes & Deterministic Verification:
   - Coordinate with `memory_lock` / `memory_unlock` if multiple agents are editing concurrently.
   - Ensure every `file:line` cited is verified via MCP output or direct source reading.
   - When code is modified and the environment permits, run the relevant test command and record the actual result.
8. Post-Edit Write-Back (if `memory_put` is enabled):
   - Store concise conclusions (especially post-edit fix status after edited files become `stale`) in `memory_put`. Do not retry `trajectory_record` on un-reindexed edited files.

WHEN TOOLS ARE RESTRICTED:
- On `POLICY_VIOLATION` (`READ_ONLY`): skip `memory_put`, `memory_lock`, `memory_unlock`, `memory_consolidate`, and `trajectory_record`; present findings and patches inline.

OUTPUT FORMAT:
  1. [Core Issue / Goal]: 1-2 summary sentences.
  2. [Location]: Exact file paths and line ranges (`path/to/file:line`).
  3. [Solution / Changes]: Minimal code diff or applied changes with rationale.
  4. [Impact & Deterministic Checks]: Affected symbols and verification results (MCP / direct source read / test execution).
  5. [Memory & Ledger]: `memory_*` keys used/updated + `prior_evidence` & `trajectory_record` status (or skip reason).
  6. [Status]: "Done" (or specific reason if user input is needed).
```

### 3.3 Compact Prompt for Subsequent Turns in the Same Session (Follow-up Turns)

> 💡 **Context Window Optimization**: Once the agent has been initialized with the full prompt in Turn 1, **DO NOT re-send the full prompt** in subsequent turns (Turn 2, Turn 3, etc.) of the same session. Replaying the full prompt wastes thousands of prompt tokens and prematurely exhausts your context window.
> Use this lightweight reminder prompt which preserves the tool dispatch constraints, the Lungs cycle (`prior_evidence` / `trajectory_record`), and standardized output format:

*(Use for Turn 2+ within the same active session)*:

```markdown
SESSION FOLLOW-UP TASK:
- Repository: {{REPO_NAME}} | Agent: {{AGENT_ID}}
- Task for this turn: {{USER_TASK}}

OPERATIONAL CONSTRAINTS:
1. Selective MCP & Anti-Double-Read: Use `get_repo_map(budget_tokens=1024)` (only if needed), `search_source`, `find_symbols`, `inspect_symbol`, `get_file_skeleton`; do NOT repeat `get_index_status` (every tool returns `freshness`). If `get_file_skeleton` / `inspect_symbol` returns `fresh` & `truncated=false` and suffices, **do NOT re-read the whole file**; read only a narrow line range (`20–60` lines) if extra lines are needed.
2. Conditional Lungs cycle: Inspect `prior_evidence` on `get_repo_map(query=...)` / `search_source(query=...)` (keep prefix `1..k-1` and re-verify from `recheck_from=k` if set). Call `trajectory_record` (`>=2` ASCII keywords, valid decoy enum, `agent_id="{{AGENT_ID}}"`) when persisting multi-session evidence or before editing verified `fresh` files — **skip** on short read-only single-turn Q&A.
3. Seamless fallback & post-edit memory: Read only relevant line spans directly if bodies are truncated, outside AST, or `stale` (never report blocked). After editing (`stale`) or for non-AST findings, update `memory_put` (do not call `trajectory_record` on un-reindexed edited files) and run relevant tests.

OUTPUT FORMAT:
1. [Core Issue / Goal]: 1-2 summary sentences.
2. [Location]: `path/to/file:line`.
3. [Solution / Changes]: Minimal patch or applied changes with rationale.
4. [Impact & Verification]: Affected symbols and validation method (MCP / direct source read / test execution).
5. [Memory & Ledger]: `memory_*` keys and `prior_evidence` / `trajectory_record` status (or skip reason).
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
  ... confirms src/auth/tokens.py:88 matches the lead ...

Step 4b: Seamless fallback for unindexed config file (.env.example)
  -> `.env.example` is not an AST code file in `find_symbols`.
  -> Instead of stopping as blocked, the agent reads `.env.example` directly and verifies `REFRESH_TOKEN_TTL_DAYS=7`.

Step 8-9: Edit src/auth/tokens.py (now `stale`) and write the updated fix status back via memory_put
> memory_put(key="auth_module.refresh_token", scope="project", namespace="repo:myrepo", ttl=604800,
              value={"finding": "refresh_token() revokes old token + TTL verified", "where": "src/auth/tokens.py:88", "status": "fixed"})
< {"status": "stored", "scope": "project", "namespace": "repo:myrepo", "key": "auth_module.refresh_token", "ttl": 604800, "expires_at": ...}
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

### Example 5: Lungs Lifecycle — Read `prior_evidence` + `recheck_from`, `trajectory_record` while `fresh`, `memory_put` post-edit

```text
Step 3: Orient with search_source (returns matching prior_evidence card)
> search_source(repo_id="myrepo", query="refresh token revoke", profile="locate")
< {
    "ledger_rev": 1,
    "warnings": ["prior_evidence_unconfirmed"],
    "data": {
      "prior_evidence": {
        "ledger_rev": 1,
        "match": 1.0,
        "status": "asserted",
        "answers": [["python:src/auth/tokens.py:TokenManager.revoke_old:a1b2c3d4", "src/auth/tokens.py", 88, "valid"]],
        "steps": [["TokenManager.refresh", "TokenManager.build_pair", "src/auth/tokens.py", 65, "valid"]],
        "decoys": [],
        "recheck_from": 2
      },
      "matches": [...]
    }
  }
  -> `prior_evidence_unconfirmed` indicates `status: "asserted"`; `recheck_from: 2` means step 1 is valid on disk and step 2 needs re-verification.

Step 4: Keep step 1 prefix, jump straight to get_symbol_context to verify step 2 & answer on fresh files
> get_symbol_context(repo_id="myrepo", symbol_id="python:src/auth/tokens.py:TokenManager.revoke_old:a1b2c3d4", depth=1, include_body=true)
  -> Confirms line 72 in TokenManager.refresh calls `self.revoke_old(...)` and `revoke_old` is defined at line 88.

Step 6: Record verified path into the Lungs BEFORE editing (while src/auth/tokens.py is still `fresh`)
> trajectory_record(
    repo_id="myrepo",
    query="refresh token revoke",
    answers=["python:src/auth/tokens.py:TokenManager.revoke_old:a1b2c3d4@88"],
    steps=["python:src/auth/tokens.py:TokenManager.refresh:e5f6a7b8>python:src/auth/tokens.py:TokenManager.revoke_old:a1b2c3d4@72"],
    decoys=["python:src/auth/helpers.py:format_token_ttl:9c0d1e2f!wrapper_only"],
    agent_id="agent_1"
  )
< {"schema_version": "1.0", "repo_id": "myrepo", "data": {"card_id": 1, "status": "confirmed", "ledger_rev": 2, "verified_count": 3, ...}}
  -> Independent corroboration promotes the card from `asserted` to `confirmed`!

Step 8-9: Edit src/auth/tokens.py -> file becomes `stale` against the snapshot
  -> Do NOT call `trajectory_record` on src/auth/tokens.py after editing (Gate G3 rejects with `stale_file`).
  -> Persist post-edit resolution via `memory_put`:
> memory_put(key="auth_module.refresh_token", scope="project", namespace="repo:myrepo", ttl=604800,
              value={"finding": "TokenManager.refresh now calls revoke_old", "where": "src/auth/tokens.py:72", "status": "fixed"})
```

## 5. Reasoning Level Selection Guide

| Reasoning Level | Recommended Model Tier | Suitable Task Types | Technical Rationale |
| :--- | :--- | :--- | :--- |
| **LOW**<br>*(Minimal Thinking)* | Small, fast models (Haiku-class, Gemini Flash/Hydrogen, GPT mini) | • Quick symbol definitions or signature lookup (`find_symbols`)<br>• Index freshness sanity checks (`get_index_status`)<br>• Re-reading a stored conclusion (`memory_get`) or following a matching `prior_evidence` anchor<br>• Local syntax or lint fixes in a single function | Single-hop factual queries where the tool answer supplies exact truth immediately. |
| **MEDIUM**<br>*(Default Thinking)* | Standard models (Sonnet-class, Gemini Neon/Pro, standard GPT) | • Scoped feature implementations (1-2 modules)<br>• Internal refactoring preserving public interfaces<br>• Business-logic bug fixes combining `inspect_symbol`, `get_impact_slice`, source reads, and `trajectory_record`<br>• Writing unit tests for target symbols | Requires synthesizing facts across 2-4 tool turns and cross-checking memory/ledger against code. |
| **HIGH**<br>*(Deep Reasoning)* | Deep-reasoning models (Opus-class, Gemini Neon High/XHigh, Extended Thinking, OpenAI o-series) | • Complex bug hunting (race conditions, async deadlocks)<br>• System-wide architecture overhauls with large fan-out (`get_module_dependents`)<br>• Coordinating several agents on one repository (`memory_lock`, `memory_consolidate`) | Requires multi-branch hypothesis generation, constraint checking, and deep graph traversal. |

---

# 第三部分：简体中文 (CHINESE SECTION)

## 1. 工具列表 (Tool List)

服务器默认注册 21 个标准工具（10 个核心 + 11 个扩展），启用管理员模式（`--enable-admin-tools`）时额外提供 2 个治理工具（共 23 个）。扩展工具需在 `repos.toml` 中设置 `enable_extensions = true`。可验证证据账本（`repos.toml` 中的 `[ledger].enabled = true`）**默认开启**，会自动将核验后的 `prior_evidence` 提示附带到 `get_repo_map(query=...)` 和 `search_source(query=...)` 的返回中。

### 1.1 核心检索工具（10 个，始终可用）

| 分类 | 工具名称 | 适用场景 | 主要参数（`*` = 必填） |
| :--- | :--- | :--- | :--- |
| `repository_admin` | `list_repositories` | 获取合法的短 `repo_id`。不确定 `repo_id` 时首先调用 | 无 |
| `repository_admin` | `get_index_status` | 检查索引快照状态（新鲜度、文件/符号数量、自索引以来变更的路径） | `repo_id*` |
| `code_navigation` | `get_repo_map` | 在陌生代码库中快速全局定向：在 Token 预算内按 PageRank 排序返回核心符号（传入 `query` 时附带 `prior_evidence`） | `repo_id*`, `query`, `budget_tokens`, `format`, `profile` |
| `code_navigation` | `find_symbols` | 按名称或限定名（支持 `*`、`?` 通配符）查找符号，返回 `symbol_id` 与位置 | `repo_id*`, `pattern*`, `kind`, `limit` |
| `code_navigation` | `search_source` | 基于 FTS5 对函数体/源码进行全文搜索，按外围符号聚合排序（附带 `prior_evidence`） | `repo_id*`, `query*`, `profile`, `limit`, `expand` |
| `code_navigation` | `get_file_skeleton` | 查看文件骨架（导入、类与函数签名，省略函数体），替代整文件读取 | `repo_id*`, `path*`, `include_private` |
| `impact_analysis` | `get_symbol_context` | 获取单个符号及其调用图邻域的受控源码包 | `repo_id*`, `symbol_id*`, `depth`, `include_body`, `body_offset_line` |
| `impact_analysis` | `get_impact_slice` | 遍历符号的调用者/被调用者（影响面候选集分析） | `repo_id*`, `symbol_id*`, `direction`, `depth`, `min_confidence` |
| `impact_analysis` | `get_module_dependents` | 分析模块或文件的导入依赖关系：谁导入了它、它导入了什么 | `repo_id*`, `module` 或 `path` |
| `impact_analysis` | `inspect_symbol` | 单轮复合神器：一次调用完成符号解析、定义提取与 1 跳调用图分析 | `repo_id*`, `query*`, `view`, `budget_tokens` |

### 1.2 扩展智能体工具（11 个，需 `enable_extensions = true`）

| 分类 | 工具名称 | 适用场景 | 主要参数（`*` = 必填） |
| :--- | :--- | :--- | :--- |
| `tool_discovery` | `list_available_tools` | 按分类查看精简工具目录 | `category` |
| `tool_discovery` | `search_tools` | 用英文关键词按意图检索工具，返回 `relevance_score` | `query*`, `limit`（默认 3） |
| `tool_discovery` | `get_tool_schema` | 按需获取指定工具的完整 JSON Schema | `tool_name*` |
| `shared_memory` | `memory_search` | 在未知键名（Key）时对 `memory.sqlite` 进行全文检索 | `query*`, `scope`, `namespace`, `limit`（默认 5） |
| `shared_memory` | `memory_get` | 已知精确键名时从 `memory.sqlite` 读取单条记忆 | `key*`, `scope`, `namespace`, `session_id` |
| `shared_memory` | `memory_put` | 存储代码分析结论、改后修复状态、任务检查点及多智能体交接状态 | `key*`, `value*`, `scope`, `namespace`, `ttl`, `session_id` |
| `shared_memory` | `memory_consolidate` | 将最多 500 条最早的活跃记忆合并为 `global` 架构洞察摘要 | `scope`, `namespace`, `target_key`, `prune_transient` |
| `shared_memory` | `memory_lock` | 多智能体并发修改同一资源时申请带超时（TTL）的软互斥锁 | `resource_key*`, `agent_id*`, `timeout_sec` (60) |
| `shared_memory` | `memory_unlock` | 释放当前智能体持有的互斥锁 | `resource_key*`, `agent_id` |
| `sampling_inference` | `sample_summarize` | 将长文本/大段代码压缩为结构化 JSON（优先用本地 Ollama 模型，无模型时自动降级为确定性 AST 提取） | `text*`, `intent`, `max_tokens` (512), `target_symbols` |
| `memory_state` | `trajectory_record` | 将在 `fresh` 文件上核验过的路径证据（`answers`、`steps`、`decoys`）记入证据账本（“肺部 / Lungs”） | `repo_id*`, `query*`, `answers*`, `steps`, `decoys`, `agent_id` |

> **关于 `sample_summarize` 的说明：** 配备本地 LLM（Ollama）的机器会返回 `backend: ollama_gpu` 或 `ollama_cpu`；无本地 LLM 的机器会自动返回 `backend: heuristic_fallback`（`engine: deterministic_ast_extractor`）且不会报错。在降级模式下，请仅采信 `critical_constraints`（含源码原句引用 `verbatim_quote` 与行号 `line`）并结合源码核对。
>
> **关于 `trajectory_record` 的说明：** 该工具属于 `memory_state` 分类，**不**接收 `ttl_days` 参数（卡片过期天数通过服务端 `repos.toml` 中的 `[ledger].ttl_days = 28` 统一配置）。所有写入均须通过写入门控 G1–G6（要求相关文件处于 `fresh` 状态）。

### 1.3 治理与审计工具（2 个，需同时启用 `enable_extensions` 与 `enable_admin_tools`）

`agent_control`（`security_governance`：支持 `status`、`pause`、`resume`、`block`、`unblock`、`set_policy`、`revoke_locks`、`emergency_halt`、`emergency_resume`，需 `admin_token`）与 `audit_logs`（`limit`、`agent_id`、`status`）。仅供管理员运维使用。

### 1.4 常用调用链与平滑降级组合

| 调用链 | 技术原因 |
| :--- | :--- |
| `get_repo_map(query=...)` 或 `search_source(query=...)`（`prior_evidence`）→ `get_symbol_context` / `inspect_symbol` → `trajectory_record` *（改码前、基于 `fresh` 文件）* | 广域搜索前先核对 `prior_evidence`（注意 `find_symbols` **不会**返回 `prior_evidence`）。若 `recheck_from` 为整数 `k`，保留前 `1..k-1` 步并从第 `k` 步起复核 |
| `list_repositories` → `get_index_status` | 先获取合法的短 `repo_id`，再检查快照新鲜度 |
| `find_symbols` → `get_symbol_context` 或 `get_impact_slice` | 后两个工具需要 `symbol_id`（而 `inspect_symbol` 可直接传入符号名） |
| `inspect_symbol` / `get_file_skeleton` → *（按需直接读取目标文件行区间）* | 先用 MCP 极速定位并省去 90% 无关读取，若遇代码截断或需修改文件，平滑切换至读取目标源文件 |
| `memory_search` / `memory_get` →（用 `inspect_symbol` 或源码核验）→ `memory_put` | 唤醒历史记忆，与最新源码核对无误后更新结论或改后状态 |
| `memory_lock` → 修改代码 → `memory_unlock` | 多智能体协同编辑时的安全互斥闭环 |

## 2. 记忆库与可验证证据账本（“肺部 / Lungs”）规范

### 2.1 共享记忆库 (`memory.sqlite`)

记忆条目持久化在 `repos.toml` 同级目录的 `memory.sqlite` 中，支持跨会话复用。推荐规范如下：

| 信息类型 | `scope` | `namespace` | `key` | `ttl`（秒） |
| :--- | :--- | :--- | :--- | :--- |
| 单个智能体的任务进度检查点 | `session` | `<agent_id>` | `task.progress` | 3600 |
| 代码分析结论（Bug 根因、改后状态、AST 外配置） | `project` | `repo:<REPO_NAME>` | `<module>.<topic>` | 604800（7 天） |
| 长期架构决策 | `project` | `repo:<REPO_NAME>` | `decision.<topic>` | 0（永不过期） |
| 汇总洞察（由 `memory_consolidate` 生成） | `global` | 空 | `project_architectural_insights` | 永不过期 |

`value` 应为精简 JSON，仅存位置指针与核心结论：`{"finding": "...", "where": "path:line", "symbol_id": "...", "status": "open|fixed"}`。

关键注意事项：

1. `scope` 仅作为分区标签（`session`、`project`、`global`），本身不会按会话隔离；需配合 `namespace` 或 `session_id` 实现隔离。
2. `memory_get` 必须同时匹配 `scope`、`namespace` 与 `key`，任一缺失均返回 `not_found`；`memory_search` 留空 `namespace` 时可跨全部命名空间搜索。
3. `memory_get` 与 `memory_put` 均支持 `session_id`：当 `scope="session"` 且 `namespace` 为空时，服务端会自动映射并隔离到该会话。
4. `memory_search` 将多个 FTS5 关键词以 AND 连接并直接内联返回 `value`，建议使用 1–3 个精简关键词及较小的 `limit`。
5. `ttl` 默认为 86400 秒（1 天）；设为 `0`（或 `<= 0` / `null`）表示永不过期。
6. Key 上限 256 字节，Value 上限 1 MB。切勿在记忆库中存储完整函数体或敏感凭据（API Key、密码、Token）。
7. `memory_consolidate` 最多读取指定 `scope`（可选按 `namespace` 过滤）中最早的 **500** 条活跃记录并写入 `scope="global"`。建议保持默认 `prune_transient=false`，避免误删原始细节条目。
8. `memory_lock` 会立即返回 `acquired: true/false` 及 `held_by`、`remaining_sec`，并在 `timeout_sec` 后自动释放过期锁。
9. `memory_unlock` 必须传入加锁时所用的同一 `agent_id`（合法格式：`^[a-zA-Z0-9_-]{1,64}$`）。

### 2.2 可验证证据账本（“肺部 / Lungs” — `ledger.sqlite`）

证据账本（`repos.toml` 同级的 `ledger.sqlite`）与 `memory.sqlite` 分工明确，切勿混用：

| 机制 | 适合存储的内容 | 写入条件与时机 | 读取方式 |
| :--- | :--- | :--- | :--- |
| **`trajectory_record`** *（肺部 — `ledger.sqlite`）* | 经磁盘 SHA-256 与 AST 核验过的代码导航证据卡（`answers`、`steps`、`decoys`） | **仅接收 `fresh` 文件中的符号**。应在**核实路径后、动手改码之前**写入，或在只读调研任务、重新建索引恢复 `fresh` 后写入 | 在调用 `get_repo_map(query=...)` 与 `search_source(query=...)` 时自动附带于 `data.prior_evidence` |
| **`memory_put`** *（共享记忆 — `memory.sqlite`）* | Bug 结论、设计取舍、**修改代码后的修复状态**（文件变为 `stale` 后）、非 AST 配置文件结论（`.toml`、`.yaml`、`.env`、`.md`） | 随时可写（包括改码后文件变为 `stale` 或 AST 未索引文件） | 通过 `memory_get` 或 `memory_search` 主动检索 |

#### `trajectory_record` 写入门控 G1–G6 规则：
1. **必须使用 ASCII 查询词构建签名（`signature.py`）：** 服务端仅按 `[a-zA-Z0-9_]+` 提取词干并去停用词；读取匹配要求 **`answer_min_overlap >= 2`** 且 **`answer_jaccard_min >= 0.6`**。`query` 中**必须包含 `>= 2` 个有意义的英文/符号标识符 ASCII 关键词**，并与调用 `get_repo_map(query=...)` / `search_source(query=...)` 时的关键词保持一致。*（纯中文或带重音符号文本会直接触发 `empty_signature` 报错！）*
2. **严格字段格式与数量上限（`gate.py`）：**
   - `answers` *（必填，最多 **8** 条）*：`"<canonical_symbol_id>@<line>"`（须满足 `start_line <= line <= end_line`）。至少有 **1** 条通过校验，否则整张卡片返回 `status: "rejected"`（`card_id: null`）。
   - `steps` *（可选，最多 **12** 条）*：`"<from_symbol_id>><to_symbol_id>@<line>"`（须 `from != to`、`line` 位于 `from_symbol` 行跨度内，且 **门控 G4**：`to_symbol` 的短标识符名称 `to_sym.name` 必须原字面出现在磁盘该行中，否则返回 `evidence_mismatch`）。
   - `decoys` *（可选，最多 **8** 条）*：`"<symbol_id>!<reason_code>"`（或 `"<from_symbol_id>><to_symbol_id>!no_reference"` 以触发 `source_verified` 校验）。`reason_code` **只能**取 4 个固定枚举值之一：**`no_reference`**、**`test_only`**、**`wrapper_only`**、**`unrelated`** *（自由文本会被拒为 `invalid_reason_code`）*。
3. **修改代码时的 `stale_file` 陷阱：** 门控 G3 会检查每个文件的新鲜度，若文件已被修改且尚未重新建索引，将直接拒绝（`reason: "stale_file"`）。因此：**务必在修改文件之前（`fresh` 时）调用 `trajectory_record`；修改文件之后，应将修复结论写入 `memory_put`，切勿对 `stale` 文件重复重试 `trajectory_record`。**
4. **身份与限流：** 显式传入 `agent_id="{{AGENT_ID}}"`（若设置 `TOKEN_CONTEXT_AGENT_ID` 则须一致）。限流为 **每 `agent_id` 每分钟 10 次**（超限报 `limit_exceeded`）。

#### 卡片生命周期与 `prior_evidence` / `recheck_from` 读取语义：
- **生命周期：** 首次核验写入状态为 `asserted`（`confirmations=1`）。第二个独立 `run_id` 写入相同 `answers` 时晋升为 `confirmed`（解锁 `decoys` 与排序加权）。若不同 `run_id` 对同一查询签名写出冲突的 `answers`（或答案命中旧诱饵），卡片将转为 `conflicted` 并停止返回。**严禁写入未经核实的猜测。**
- **读取时（仅限非空 `query` 的 `get_repo_map` 与 `search_source`）：**
  - `find_symbols` **不**返回 `prior_evidence`。
  - `prior_evidence.status` 为 `"asserted"`（伴随警告 `prior_evidence_unconfirmed` 且 `decoys: []`）或 `"confirmed"`（在 `match >= 0.8` 时包含 `decoys`）。
  - `answers`（`[[symbol_id, path, line, "valid"], ...]`）：若所有答案函数体均已在磁盘变更，服务端会自动将其置为 `retired` 并省略 `prior_evidence`。
  - `recheck_from`：当所有 `steps` 均有效时为 `null`；若为 **从 1 开始的整数 `k`**，代表第 `k` 步在磁盘上已变更或失效——智能体应保留 `1..k-1` 前缀并仅从第 `k` 步起重新核验。

## 3. 智能体提示词模板（自适应、柔性防卡死设计）

### 3.0 极简按需路由模板 — 默认推荐 (Lean Selective MCP)

*(推荐用于 Antigravity、Cursor、Claude Code 或 CLI 日常会话的默认模板——Prompt 低于 400 Token，内联 5 个核心工具签名以跳过 `.json` Schema 读取，并防止重复整读源码文件。)*

```markdown
仓库: {{REPO_NAME}} | Agent: {{AGENT_ID}}
任务: {{USER_TASK}}

规则（非 AST/stale 文件直读；标注 path:line）:
1. 按需选路:
   - 已知路径：跳过 list_repositories/get_repo_map/search_source；查签名用 get_file_skeleton(repo_id, path, max_tokens=1024)，短文件(<300行)需全量实现直调 read_file。
   - 未知位置/行为/跨模块：调 1 个 MCP 工具 (search_source/inspect_symbol/get_impact_slice)，预算 1024-1536。
2. 禁止重读:
   - 若 get_file_skeleton/inspect_symbol 返回 freshness="fresh" & truncated=false 且够用，停——勿 read_file 整文件；需细节仅读 20-60 行。
3. 零仪式预算:
   - 勿重复 get_index_status（工具自带 freshness）。结构未知最多 1 次 get_repo_map(budget_tokens=1024)。trajectory_record/memory_put 仅跨会话/要求时用（单轮跳过）。
4. 5 工具速查（直调，报错外勿读 .json schema）:
   - search_source(repo_id, query, profile="locate", max_tokens=1280, limit=15)
   - get_file_skeleton(repo_id, path, include_private=false, max_tokens=1536)
   - inspect_symbol(repo_id, query, view="full", budget_tokens=1536)
   - get_impact_slice(repo_id, symbol_id, direction="both", depth=2, max_tokens=1536)
   - get_repo_map(repo_id, query=None, budget_tokens=1024, format="compact")
```

### 3.1 配备本地 LLM 的环境（Ollama GPU/CPU）

*(复制下方代码块，替换 `{{REPO_NAME}}`、`{{USER_TASK}}` 与 `{{AGENT_ID}}` 后发送给智能体)*

```markdown
你是一位资深软件工程师，可同时调用 `token-context-mcp` 服务器工具以及当前工作区的文件读写与搜索工具。

输入信息 (INPUT):
- 目标代码库: {{REPO_NAME}}（优先使用已注册的短 `repo_id`）
- 你的身份标识: {{AGENT_ID}}（若服务端配置了 `TOKEN_CONTEXT_AGENT_ID` 则必须保持一致，用于互斥锁、记忆库与 `trajectory_record`）
- 任务目标: {{USER_TASK}}

核心原则（MCP 优先、源码平滑兜底、绝不提前卡死）:
1. MCP 导航优先，源码读取平滑兜底 (MCP-First, Seamless Source Fallback):
   - 始终优先使用 `token-context-mcp` 工具（`get_repo_map`、`find_symbols`、`search_source`、`get_file_skeleton`、`inspect_symbol`）进行快速定位，以节省 60%–95% 的 Token，避免盲目扫描整个代码库。
   - 【重要】当 MCP 工具未能返回足够信息时，绝不要将任务标记为 `blocked` 或提前终止！遇到以下任一情况时，请平滑切换至工作区原生文件读取/搜索工具（优先按已定位的文件路径或行号区间精准读取）：
     a) 目标文件属于未纳入 AST 索引的配置文件、脚本或文档（如 `.toml`、`.yaml`、`.json`、`.md`、`.sql`、`.sh` 等）或新建文件；
     b) MCP 返回结果存在截断（`truncated=true`）、模糊边（`ambiguous`）、快照过期（`stale`）或未匹配到符号；
     c) 在修改代码前，你需要查看目标函数周边的完整上下文行以确保补丁（Patch）语法安全。
2. 区分共享记忆（`memory_*`）与证据账本（“肺部” `trajectory_record` / `prior_evidence`），真实源码才是唯一真理:
   - 先查 `memory_*` 并核对 `get_repo_map(query=...)` / `search_source(query=...)` 返回的 `prior_evidence`，但动手前必须与当前源码核实。
   - “肺部”（`trajectory_record`）只接收 **`fresh`** 文件上的已核验路径——严禁记录未核实的猜测，也不要对改码后已变 `stale` 的文件强行写入。改码后的结论与非 AST 信息写入 `memory_put`。
3. 区分“安全熔断”与“技术自愈”:
   - 仅在遇到管理员明确授权拦截（`HALT_BY_USER` 或 `ACCESS_DENIED`）时立即停止并向用户报告（切勿伪造 `agent_id` 或冒用 `admin`）。
   - 遇到任何常规技术错误（如 `unknown_repo_id`、`budget_out_of_range`、`stale_file`、超时或扩展工具未开启）：请主动自愈（调用 `list_repositories()` 获取短 ID、下调 `budget_tokens`、跳过 `stale` 文件的账本写入），或直接读取工作区源文件继续完成任务。

平滑执行流程 (WORKFLOW):
0. 工具发现（可选，仅在不清楚工具名称或参数时调用）:
   - 调用 `search_tools(query="<贴近工具名的英文关键词>", limit=2)` 或 `list_available_tools(category="<分类>")`（注：`trajectory_record` 位于 `memory_state`）。若扩展工具未启用，直接进入步骤 1。
1. 轻量级预检 (Pre-flight):
   - 若不确定 `repo_id`，先调 `list_repositories()`，再调 `get_index_status(repo_id="{{REPO_NAME}}")`。
   - 若快照为 `fresh`，可充分信赖调用图与肺部证据；若为 `stale`，将图结果作为候选线索，对 `pending_paths` 变更文件直接读源码核实，且不要对这些 stale 文件调用 `trajectory_record`。
2. 唤醒共享记忆（若启用了 `memory_*`）:
   - 检查 `memory_get(key="task.progress", scope="session", namespace="{{AGENT_ID}}")` 及 `memory_search(query="<1-3 个核心词>", scope="project", limit=5)`。未找到则立即进入步骤 3。
3. 定位定向与检索肺部证据（`prior_evidence`）:
   - 调用 `get_repo_map(repo_id="{{REPO_NAME}}", query="<>=2 个 ASCII/符号关键词>")` 和/或 `search_source(repo_id="{{REPO_NAME}}", query="<>=2 个 ASCII/符号关键词>", profile="locate")`——仅这两个工具会返回 `data.prior_evidence`（`find_symbols` 不返回）。
   - 若命中 `data.prior_evidence`，请在广域搜索前先核对：
     * 直接用 `get_symbol_context(repo_id="{{REPO_NAME}}", symbol_id="<answers中的id>")` 或 `inspect_symbol` 核验答案。
     * 若 `warnings` 含 `prior_evidence_unconfirmed`（`status: "asserted"`），必须自行对源码复核后再采信。
     * 若 `recheck_from` 为整数 `k`，保留 `steps[0..k-2]` 有效前缀，仅从第 `k` 步起重新核验。
     * 避开 `decoys` 中已排除的诱饵符号（`status: "confirmed"` 时提供）。
   - 按需配合 `find_symbols(repo_id="{{REPO_NAME}}", pattern="<Name*>")` 与 `get_file_skeleton(repo_id="{{REPO_NAME}}", path="<文件路径>")`；非索引配置文件直接用原生工具读取。
4. 深度检查与按需源码读取 (Deep Inspection):
   - 调用 `inspect_symbol(repo_id="{{REPO_NAME}}", query="<符号名>", view="full")` 单轮获取签名、函数体与 1 跳调用关系。
   - 若函数体较长被截断（`truncated_lines`）或准备编辑文件：通过 `get_symbol_context(..., include_body=true, body_offset_line=...)` 分页读取，或直接读取源文件的对应行区间。
5. 影响面与依赖分析 (Impact & Dependencies):
   - 修改共享逻辑或函数签名时：调用 `get_impact_slice(repo_id="{{REPO_NAME}}", symbol_id="<id>", direction="callers", depth=2)` 及 `get_module_dependents`。
6. 在修改文件之前记录肺部证据（`trajectory_record`，仅当目标文件仍为 `fresh`）:
   - 若启用了 `trajectory_record` 且已在 `fresh` 文件上完成核验，请在修改文件前（或只读任务结束时）调用：
     `trajectory_record(repo_id="{{REPO_NAME}}", query="<>=2 个英文/标识符 ASCII 关键词>", answers=["<canonical_symbol_id>@<line>"], steps=["<from_symbol_id>><to_symbol_id>@<line>"], decoys=["<symbol_id>!<no_reference|test_only|wrapper_only|unrelated>"], agent_id="{{AGENT_ID}}")`
   - 规则：`steps` 的目标短名称必须出现在对应 `<line>` 行源码中；`decoys` 必须使用 4 种合法原因码之一；仅传入以上标准参数。若目标文件已 `stale` 则跳过。
7. 上下文压缩（可选）:
   - 遇到超长日志或代码段时，可调用 `sample_summarize(text="<...>", intent="<目标>", max_tokens=512)`。若返回 `backend: heuristic_fallback`，仅采信 `critical_constraints` 并核对源码。
8. 协同加锁与代码修改:
   - 多智能体并发且启用 `memory_lock` 时：修改前调用 `memory_lock(resource_key="<模块或文件>", agent_id="{{AGENT_ID}}", timeout_sec=120)`；若 `acquired: false`，先完成分析与补丁准备，稍后重试加锁；修改完毕立即 `memory_unlock`。环境允许时运行相关测试。
9. 改码后结论写回（`memory_put`）:
   - 修改代码后，对应文件相对旧快照已成为 `stale`：切勿对未重新建索引的已改文件重复调用 `trajectory_record`（会报 `stale_file`）。请将修复状态与结论存入 `memory_put(key="<module>.<topic>", value={"finding": "...", "where": "path:line", "symbol_id": "...", "status": "fixed"}, scope="project", namespace="repo:{{REPO_NAME}}", ttl=604800)`。

工具受限时的柔性处理:
- 未发现 `search_tools` / `memory_*` / `trajectory_record`（`enable_extensions = false`）：跳过扩展步骤，组合使用 10 个核心检索工具与原生文件读写工具（`[ledger].enabled = true` 时仍可读取 `prior_evidence`）。
- 遇到 `POLICY_VIOLATION`（只读策略 `READ_ONLY`）：跳过写入/受限工具（`memory_put`、`memory_lock`、`memory_unlock`、`memory_consolidate`、`sample_summarize`、`trajectory_record`），直接在回复中输出分析结论与代码补丁。
- 遇到 `HALT_BY_USER` 或 `ACCESS_DENIED`：立即停止并告知用户。

回复格式要求 (OUTPUT FORMAT):
- 简洁、准确、以最终解决问题为导向：
  1. [核心问题 / 目标]：1-2 句话概括。
  2. [源码位置]：精确的文件路径与行号区间（`path/to/file:line`）。
  3. [解决方案 / 代码变更]：精简的代码补丁或修改说明。
  4. [影响面与核验]：受影响的符号/模块，以及核验方式（MCP 工具 / 直接读取源码 / 运行测试）。
  5. [记忆库与账本]：读取或更新的 `memory_*` Key + `prior_evidence`（命中 / `recheck_from`）及 `trajectory_record` 状态（或跳过原因如 `stale_file` / `READ_ONLY`）。
  6. [状态]：“已完成”（仅当用户业务需求本身不明确需追问时填“待确认”）。
```

### 3.2 无本地 LLM 的环境（纯 CPU / 确定性模式）

*(适用于未安装本地 Ollama 的机器。包括可验证证据账本（“肺部”）在内的全部校验均 100% 基于确定性的 SQLite、AST、SHA-256 与真实源码，具备平滑的源码读取兜底机制，绝不因工具缺省而卡在 `blocked` 状态。)*

```markdown
你是一位资深软件工程师，可同时调用 `token-context-mcp` 服务器工具与工作区文件读写工具。当前机器未配置 MCP 本地 LLM：请勿调用 `sample_summarize`。包括可验证证据账本（“肺部 / Lungs”）在内的所有分析与校验均基于工具输出与真实源码确定性完成。

输入信息 (INPUT):
- 目标代码库: {{REPO_NAME}}
- 你的身份标识: {{AGENT_ID}}（若服务端设置了 `TOKEN_CONTEXT_AGENT_ID` 则必须一致）
- 任务目标: {{USER_TASK}}

核心原则（确定性核验、柔性兜底、绝不提前卡死）:
1. MCP 检索与原生源码读取协同配合:
   - 优先调用 `token-context-mcp`（`get_repo_map`、`find_symbols`、`search_source`、`get_file_skeleton`、`inspect_symbol`）快速定位符号，节省 Token。
   - 当需要查看被截断的完整函数体、检查 AST 索引外的配置文件，或遇到快照 `stale` / MCP 报错时：请主动直接读取目标源文件。绝不要因为某个文件或符号不在 MCP 索引中就提前停止或报错 `blocked`。
2. 确定性证据与肺部账本原则:
   - 有效证据包括 `token-context-mcp` 的返回结果，以及你在本轮会话中直接读取的源码内容。
   - 复用 `get_repo_map(query=...)` / `search_source(query=...)` 中的 `prior_evidence` 线索并在改码前对 `fresh` 文件写入 `trajectory_record`；改码后（`stale`）或 AST 外的结论写入 `memory_put`。严禁写入未核验的猜测。
3. 区分“安全熔断”与“技术自愈”:
   - 仅在遇到 `HALT_BY_USER` 或 `ACCESS_DENIED` 时停止。
   - 遇到参数错误（`unknown_repo_id`、`budget_out_of_range`）、`stale_file` 或超时：自动修正参数（调用 `list_repositories()`、调低预算）、跳过对 `stale` 文件的账本写入，或直接读取工作区源文件完成任务。

执行流程 (WORKFLOW):
1. 预检 (Pre-flight):
   - 仅在不确定 `repo_id` 时调用 `list_repositories()`，且全会话**最多调用 1 次** `get_index_status(repo_id="{{REPO_NAME}}")`（其他 MCP 工具均已返回 `freshness`）。记录 `fresh`/`stale` 状态与 `pending_paths`，以便对变更文件读源码核对并避免向 stale 文件写入 `trajectory_record`。
2. 唤醒共享记忆（若启用了 `memory_*`）:
   - 查询 `memory_get(key="task.progress", scope="session", namespace="{{AGENT_ID}}")` 与 `memory_search(query="<1-3 个关键词>", scope="project", limit=5)`。无结果则直接跳过。
3. 定位源码并核对 `prior_evidence`（肺部）:
   - 仅在未知仓库结构时调用 `get_repo_map(repo_id="{{REPO_NAME}}", query="<>=2 个 ASCII/符号关键词>", budget_tokens=1024)`（使用 `1024` 替代 `4096`）或 `search_source(repo_id="{{REPO_NAME}}", query="<>=2 个 ASCII/符号关键词>", profile="locate")`（仅这两个工具返回 `data.prior_evidence`）。
   - 若命中 `prior_evidence`：优先通过 `get_symbol_context` / `inspect_symbol` 核验 `answers`；遇到 `prior_evidence_unconfirmed`（`asserted`）时独立复核；若 `recheck_from` 为 `k`，保留 `1..k-1` 前缀并从第 `k` 步起复核。卡片为 `confirmed` 时避开 `decoys`。
   - 配合 `find_symbols(repo_id="{{REPO_NAME}}", pattern="<Name*>")` 与 `get_file_skeleton(repo_id="{{REPO_NAME}}", path="<路径>")`；非索引文件直接读取。
4. 深度检查与防重复整读 (Deep Inspection & Anti-Double-Read):
   - 调用 `inspect_symbol(repo_id="{{REPO_NAME}}", query="<符号名>", view="full")`。
   - **禁止重读规则 (Anti-Double-Read)：** 若 `get_file_skeleton` 或 `inspect_symbol` 返回 `freshness="fresh"` 且 `truncated=false` 并已足够作答，**切勿再对整文件执行全量读取**；若需补充细节，仅通过 `read_file` 或 `get_symbol_context(..., include_body=true, body_offset_line=...)` 读取窄行区间（`20–60` 行）。
5. 影响面分析 (Impact):
   - 调用 `get_impact_slice(repo_id="{{REPO_NAME}}", symbol_id="<id>", direction="callers", depth=2)` 和/或 `get_module_dependents`。
6. 在修改代码前按需记录肺部证据（若已启用且文件处于 `fresh`）:
   - 短单轮只读问答**跳过此步**；仅在需要跨会话沉淀证据或修改 `fresh` 文件之前调用：
     `trajectory_record(repo_id="{{REPO_NAME}}", query="<>=2 个英文/符号 ASCII 关键词>", answers=["<canonical_symbol_id>@<line>"], steps=["<from_symbol_id>><to_symbol_id>@<line>"], decoys=["<symbol_id>!<no_reference|test_only|wrapper_only|unrelated>"], agent_id="{{AGENT_ID}}")`
   - 确保 `steps` 中 `to_symbol` 的短名称出现在该行源码中；若相关文件已是 `stale` 则跳过。
7. 执行修改与确定性核验:
   - 多智能体并发且启用 `memory_lock` 时，修改前加锁、修改后解锁。
   - 确保回复中引用的每一处 `file:line` 均已通过 MCP 工具或直接读取源码核实。
   - 若修改了代码且环境允许，运行相关测试命令并记录真实测试结果。
8. 改码后写回共享记忆（若启用了 `memory_put`）:
   - 将精简结论（尤其是改码使文件变为 `stale` 后的修复状态）存入 `memory_put`。未重新建索引前不要对已修改文件重试 `trajectory_record`。

工具受限处理:
- 若遇到 `POLICY_VIOLATION`（`READ_ONLY`）：跳过 `memory_put`、`memory_lock`、`memory_unlock`、`memory_consolidate` 与 `trajectory_record`，直接在回复中给出补丁方案。

回复格式要求 (OUTPUT FORMAT):
  1. [核心问题 / 目标]：1-2 句话总结。
  2. [源码位置]：精确的文件路径与行号（`path/to/file:line`）。
  3. [解决方案 / 代码变更]：精简的代码补丁与技术说明。
  4. [影响面与确定性核验]：受影响符号及核验结果（MCP 工具 / 直接读取源码 / 测试运行结果）。
  5. [记忆库与账本]：读取或更新的 `memory_*` Key + `prior_evidence` 与 `trajectory_record` 状态（或跳过原因）。
  6. [状态]：“已完成”（或需用户补充业务信息的具体说明）。
```

### 3.3 会话后续轮次精简提示词模板 (Subsequent / Follow-up Turns)

> 💡 **上下文窗口优化策略**: 在同一个对话会话中，智能体已在第 1 轮（Turn 1）接收了完整的系统指令与工具规范。在后续轮次（Turn 2、3……）中，**严禁盲目机械地重放全量长篇提示词**，否则将白白浪费数千输入 Token 并挤占有效上下文。
> 此时仅需发送如下超精简提示词，即可牢牢锁定工具调用约束、肺部闭环（`prior_evidence` / `trajectory_record`）与标准化输出结构：

*(适用于同一会话内的第 2 轮及后续轮次)*:

```markdown
会话后续任务 (SESSION FOLLOW-UP):
- 目标代码库: {{REPO_NAME}} | 智能体标识: {{AGENT_ID}}
- 本轮任务目标: {{USER_TASK}}

继续遵守核心原则:
1. 按需选路与防重复整读：按需使用 `get_repo_map(budget_tokens=1024)`（仅未知结构时）、`search_source`、`find_symbols`、`inspect_symbol`、`get_file_skeleton`；勿重复调用 `get_index_status`（工具均自带 `freshness`）。若 `get_file_skeleton` / `inspect_symbol` 返回 `fresh` 且 `truncated=false` 并已足够，**切勿重读整文件**；如需更多行，仅读取窄行区间（`20–60` 行）。
2. 按需肺部闭环（Lungs）：在 `get_repo_map(query=...)` / `search_source(query=...)` 中优先核查 `prior_evidence`（有 `recheck_from=k` 则保留 `1..k-1` 并从第 `k` 步起复核）。仅在跨会话调查或修改 `fresh` 文件前调用 `trajectory_record`（`>=2` 个 ASCII 关键词、合法 decoy 枚举、`agent_id="{{AGENT_ID}}"`）——短单轮只读问答**跳过**。
3. 兜底与改后记忆：遇截断、AST 外配置或快照 `stale` 时直接读取对应行区间，绝不擅自卡死或报 blocked。改码后（`stale`）或 AST 外的结论通过 `memory_put` 保存（勿对未重索引的已改文件调 `trajectory_record`），并运行相关测试。

回复格式要求 (OUTPUT FORMAT):
1. [核心问题 / 目标]：1-2 句话概括。
2. [源码位置]：`path/to/file:line`。
3. [解决方案 / 代码变更]：精简代码补丁与技术说明。
4. [影响面与核验]：受影响符号及核验依据（工具输出 / 源码核对 / 测试结果）。
5. [记忆库与账本]：`memory_*` Key 及 `prior_evidence` / `trajectory_record` 状态（或跳过原因）。
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
  ... 确认 src/auth/tokens.py:88 逻辑与线索一致 ...

步骤 4b：对未纳入 AST 索引的配置文件（.env.example）平滑兜底
  -> `.env.example` 不在 `find_symbols` 的 AST 符号表中。
  -> 智能体不会停止或报 blocked，而是直接读取 `.env.example` 文件，核实 `REFRESH_TOKEN_TTL_DAYS=7`。

步骤 8-9：修改 src/auth/tokens.py（文件变成 `stale`）后将最新修复状态写回 memory_put
> memory_put(key="auth_module.refresh_token", scope="project", namespace="repo:myrepo", ttl=604800,
              value={"finding": "refresh_token() 已吊销旧 token 并核验 TTL", "where": "src/auth/tokens.py:88", "status": "fixed"})
< {"status": "stored", "scope": "project", "namespace": "repo:myrepo", "key": "auth_module.refresh_token", "ttl": 604800, "expires_at": ...}
```

### 示例 2：锁已被其他智能体持有时的平滑处理（不死锁）

```text
> memory_lock(resource_key="auth_module", agent_id="agent_2", timeout_sec=120)
< {"status": "locked", "acquired": false, "resource_key": "auth_module", "held_by": "agent_1", "remaining_sec": 45.0}
  -> 暂不覆盖文件。Agent_2 继续阅读分析源码、准备好补丁与单元测试，待 `remaining_sec` 过期后重试加锁并完成写入。

（修改完成后）
> memory_unlock(resource_key="auth_module", agent_id="agent_2")
< {"status": "released", "resource_key": "auth_module"}
```

### 示例 3：动态发现工具并直接调用（步骤 0）

```text
> search_tools(query="search memory previous findings", limit=2)
< {"matches_found": 2, "tools": [
    {"name": "memory_search", "category": "shared_memory", "relevance_score": 9.0,
     "quick_parameters": {"query": "string (required)", "scope": "...", "namespace": "...", "limit": "integer (default: 5)"}, ...},
    {"name": "search_source", "relevance_score": 4.5, ...}]}
  -> 选中 `memory_search` 并依据 `quick_parameters` 直接调用，无需额外再花一轮拉取 Schema。
```

### 示例 4：使用 `sample_summarize` 压缩长上下文后存入记忆库

```text
> sample_summarize(
    text="class PaymentGateway:\n    def process(self, amount, currency):\n        if amount <= 0:\n            raise ValueError('Invalid amount')\n        ...",
    intent="分析支付交易约束与异常处理逻辑",
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

### 示例 5：肺部全流程 — 读取 `prior_evidence` + `recheck_from`、`fresh` 时写 `trajectory_record`、改码后用 `memory_put`

```text
步骤 3：使用 search_source 定向（命中有既有证据卡）
> search_source(repo_id="myrepo", query="refresh token revoke", profile="locate")
< {
    "ledger_rev": 1,
    "warnings": ["prior_evidence_unconfirmed"],
    "data": {
      "prior_evidence": {
        "ledger_rev": 1,
        "match": 1.0,
        "status": "asserted",
        "answers": [["python:src/auth/tokens.py:TokenManager.revoke_old:a1b2c3d4", "src/auth/tokens.py", 88, "valid"]],
        "steps": [["TokenManager.refresh", "TokenManager.build_pair", "src/auth/tokens.py", 65, "valid"]],
        "decoys": [],
        "recheck_from": 2
      },
      "matches": [...]
    }
  }
  -> `prior_evidence_unconfirmed` 提示卡片尚处于 `asserted`；`recheck_from: 2` 表明第 1 步在磁盘上仍有效，第 2 步需要复核。

步骤 4：保留第 1 步前缀，直接调 get_symbol_context 在 fresh 文件上核验第 2 步与答案
> get_symbol_context(repo_id="myrepo", symbol_id="python:src/auth/tokens.py:TokenManager.revoke_old:a1b2c3d4", depth=1, include_body=true)
  -> 核实 TokenManager.refresh 第 72 行调用 `self.revoke_old(...)`，且 `revoke_old` 定义位于第 88 行。

步骤 6：在修改文件之前（src/auth/tokens.py 仍为 `fresh`）写回肺部账本
> trajectory_record(
    repo_id="myrepo",
    query="refresh token revoke",
    answers=["python:src/auth/tokens.py:TokenManager.revoke_old:a1b2c3d4@88"],
    steps=["python:src/auth/tokens.py:TokenManager.refresh:e5f6a7b8>python:src/auth/tokens.py:TokenManager.revoke_old:a1b2c3d4@72"],
    decoys=["python:src/auth/helpers.py:format_token_ttl:9c0d1e2f!wrapper_only"],
    agent_id="agent_1"
  )
< {"schema_version": "1.0", "repo_id": "myrepo", "data": {"card_id": 1, "status": "confirmed", "ledger_rev": 2, "verified_count": 3, ...}}
  -> 经另一独立 `run_id` 复核同一 `answers`，卡片从 `asserted` 晋升为 `confirmed`！

步骤 8-9：修改 src/auth/tokens.py -> 相对快照文件变为 `stale`
  -> 此时不要再对 src/auth/tokens.py 调用 `trajectory_record`（门控 G3 会拒为 `stale_file`）。
  -> 改为通过 `memory_put` 持久化改后结论：
> memory_put(key="auth_module.refresh_token", scope="project", namespace="repo:myrepo", ttl=604800,
              value={"finding": "TokenManager.refresh 已正确调用 revoke_old", "where": "src/auth/tokens.py:72", "status": "fixed"})
```

## 5. 推理级别选择指南 (Reasoning Level Selection Guide)

| 推理级别 | 推荐模型档位 | 适用任务类型 | 技术依据 |
| :--- | :--- | :--- | :--- |
| **低 (LOW)**<br>*(轻量思考)* | 轻量高速模型（Haiku、Gemini Flash/Hydrogen、GPT mini） | • 快速查找函数/类定义位置（`find_symbols`）<br>• 检查索引健康状态（`get_index_status`）<br>• 按已知 Key 读取记忆（`memory_get`）或沿命中 `prior_evidence` 核查<br>• 单个函数内的语法修复或代码片段解释 | 单跳事实查询，工具返回结果即包含完整准确答案。 |
| **中 (MEDIUM)**<br>*(标准思考)* | 标准主力模型（Sonnet、Gemini Neon/Pro、标准 GPT） | • 跨 1-2 个模块的功能开发<br>• 保持公共 API 不变的内部重构<br>• 结合 `inspect_symbol`、`get_impact_slice`、源码读取与 `trajectory_record` 修复业务 Bug<br>• 为目标符号编写单元测试 | 需要串联 2-4 轮工具调用，并将历史记忆/证据账本与最新源码交叉核对。 |
| **高 (HIGH)**<br>*(深度推理)* | 深度推理模型（Opus、Gemini Neon High/XHigh、Extended Thinking、OpenAI o 系列） | • 排查复杂疑难 Bug（竞态条件、异步死锁、内存泄漏）<br>• 具有广泛依赖扇出的大型架构重构（`get_module_dependents`）<br>• 多智能体协同修改同一代码库（`memory_lock`、`memory_consolidate`） | 需要多分支假设推演、严格约束校验以及深度依赖图遍历。 |
