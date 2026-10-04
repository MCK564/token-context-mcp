# BÁO CÁO TOÀN DIỆN VỀ LỖI VÀ LỖ HỔNG HỆ THỐNG TOKEN-CONTEXT MCP SERVER

> **Thời gian kiểm toán:** 2026-10-03  
> **Repository:** [`token-context-mcp`](file:///D:/AI/token-context-mcp)  
> **Trạng thái cấp quyền:** Full Admin & Full Access Tools đã được kích hoạt thành công trên máy cho toàn bộ các agents.

---

## I. TỔNG QUAN VÀ TRẠNG THÁI CẤP QUYỀN HỆ THỐNG

### 1. Kích hoạt toàn bộ quyền Admin & Memory Retrieval
- **File cấu hình server:** [`C:\Users\KHA\AppData\Roaming\token-context-mcp\repos.toml`](file:///C:/Users/KHA/AppData/Roaming/token-context-mcp/repos.toml)
  - `enable_extensions = true` (Kích hoạt toàn bộ bộ nhớ chia sẻ `memory_*`, công cụ tự khám phá `discovery/*`, bộ nén/sampling `sample_summarize`).
  - `enable_admin_tools = true` (Kích hoạt các công cụ quản trị `agent_control`, `audit_logs`).
- **File cấu hình client Antigravity MCP:** [`C:\Users\KHA\.gemini\config\mcp_config.json`](file:///C:/Users/KHA/.gemini/config/mcp_config.json)
  - Đã thêm cờ `--enable-admin-tools` vào tham số dòng lệnh khởi động `token_context_mcp`.
  - Đã cấu hình biến môi trường bảo mật `TOKEN_CONTEXT_ADMIN_TOKEN = "4LX4DKNCjOcZhRI36-0J2KvhkgLekJ1mYewE8m1Yj1c"`.
- **Cơ sở dữ liệu quản trị Governance SQLite:** [`governance.sqlite`](file:///C:/Users/KHA/AppData/Roaming/token-context-mcp/governance.sqlite)
  - Đã thiết lập chính sách `FULL_ACCESS` và trạng thái `ACTIVE` cho cả `anonymous` và `admin`.
  - Toàn bộ **22 tools** của server đã được mở khóa và sẵn sàng hoạt động.

---

## II. BẢNG TỔNG HỢP DANH SÁCH BUGS THEO ĐỘ ƯU TIÊN

| Mã Bug | Độ ưu tiên | Module | Tiêu đề lỗi | Tác động chính |
| :--- | :---: | :--- | :--- | :--- |
| **BUG-01** | **P0** | Security / Auth | Rate-limit bypass hoàn toàn qua danh tính `anonymous` | Bất kỳ agent nào không gửi `agent_id` đều được vô hạn request, vô hiệu hóa cơ chế chống DoS/loop runaway. |
| **BUG-02** | **P1** | Security / Auth | Giả mạo danh tính Agent (`agent_id` impersonation) | Agent có thể mạo danh bất kỳ agent nào để cướp lock, ghi đè session memory hoặc giải phóng lock của agent khác. |
| **BUG-03** | **P1** | Security / Admin | Tham số `policy` trong tool `agent_control` bị bỏ qua (Dead code) | Quản trị viên truyền `policy="READ_ONLY"` hoặc `"FULL_ACCESS"` vào `agent_control` nhưng server hoàn toàn không lưu hoặc áp dụng. |
| **BUG-04** | **P1** | Memory / Session | Mất cô lập session: `memory_get` không nhận tham số `session_id` | `memory_put` lưu theo `session_id`, nhưng `memory_get` không có `session_id` khiến dữ liệu phiên không bao giờ truy vấn lại được. |
| **BUG-05** | **P1** | Memory / Lock | Cho phép Agent bất kỳ giải phóng lock của Agent khác qua `memory_unlock` | Thiếu kiểm tra quyền sở hữu lock khi gọi unlock, gây xung đột tài nguyên trong môi trường multi-agent. |
| **BUG-06** | **P1** | Retrieval / Context | Mất toàn bộ body của symbol lớn (`root_body_omitted_budget`) | Khi symbol lớn hơn token budget, server cắt bỏ 100% body mà không cung cấp cơ chế phân trang (paging/windowing). |
| **BUG-07** | **P1** | Index / Windows | Lỗi treo vô tận trong test suite trên Windows (`test_guard.py`) | Lệnh `subprocess.run("git archive ... \| tar ...", shell=True)` treo vĩnh viễn trên Windows `cmd.exe`. |
| **BUG-08** | **P1** | Parser / Treesitter | Lệch offset ký tự khi file nguồn chứa ký tự Unicode đa byte (UTF-8) | Tree-sitter trả byte offset, Python slice theo ký tự khiến việc trích xuất code bị lệch, cắt cụt code hoặc lỗi crash. |
| **BUG-09** | **P2** | Storage / Index | Lỗi xung đột khóa file SQLite trên Windows khi hoán đổi snapshot (`WinError 32`) | Windows không cho phép `os.replace` trên file SQLite khi đang có tiến trình/thread mở kết nối đọc. |
| **BUG-10** | **P2** | Memory / Search | Lọc từ khóa regex trong `memory_search` làm hỏng truy vấn chứa ký tự đặc biệt | `re.findall(r"\w+", query)` tách các định danh như `uuid-123` hay `config.json` thành các từ rời rạc nối bằng AND. |
| **BUG-11** | **P2** | Memory / Consolidate | `memory_consolidate` dọn dẹp nhầm hoặc không dọn dẹp được session entries | Gọi `store.delete(key, scope)` nhưng mặc định `namespace=""`, không xóa được các bản ghi có namespace/session. |
| **BUG-12** | **P2** | Parser / Overload | Trùng lặp `symbol_id` khi hàm bị overload (C#, Java) hoặc định nghĩa theo điều kiện | Hàm cùng tên trong cùng class/file bị sinh trùng ID, ghi đè lẫn nhau trong cơ sở dữ liệu index. |
| **BUG-13** | **P2** | Retrieval / Freshness | Rò rỉ connection trong `ReadConnectionPool` khi index được rebuild | Các thread cũ giữ connection tới snapshot file cũ gây lãng phí RAM và khóa file trên Windows. |
| **BUG-14** | **P3** | Parser / CRLF | Lệch dòng và byte khi file nguồn có định dạng xuống dòng Windows `\r\n` | CRLF làm độ dài byte khác biệt so với số dòng tính toán, có thể gây sai lệch vị trí span hiển thị. |

---

## III. CHI TIẾT NGUYÊN NHÂN VÀ GIẢI PHÁP TỪNG BUG

### BUG-01: Rate-limit bypass hoàn toàn qua danh tính `anonymous`
- **Độ ưu tiên:** `P0 (Critical Security)`
- **Vị trí code:** [`src/token_context_mcp/security/access_control.py:301-312`](file:///D:/AI/token-context-mcp/src/token_context_mcp/security/access_control.py#L301-L312)
- **Nguyên nhân gây ra bug:**
  Trong hàm `check_access`:
  ```python
  now = time.time()
  if effective_agent_id != "anonymous":
      history = self._call_history[effective_agent_id]
      one_min_ago = now - 60.0
      while history and history[0] < one_min_ago:
          history.popleft()
      if len(history) >= self.max_calls_per_minute:
          return False, f"RATE_LIMITED: Agent '{effective_agent_id}' exceeded limit of {self.max_calls_per_minute} calls/min."
      history.append(now)
  ```
  Code cố tình bỏ qua rate limiting nếu `effective_agent_id == "anonymous"`. Tuy nhiên, khi một agent không truyền `agent_id` hoặc truyền `None`, hệ thống tự động gán là `"anonymous"`. Điều này tạo ra một lỗ hổng nghiêm trọng: bất kỳ agent nào muốn bypass giới hạn 120 calls/phút chỉ cần không gửi `agent_id`, dẫn đến nguy cơ DoS server hoặc tiêu tốn tài nguyên hệ thống vô hạn định khi agent gặp vòng lặp lỗi.
- **Giải pháp đề xuất:**
  Áp dụng rate limiting chung cho cả `anonymous` (ví dụ gộp thành một bucket ẩn danh với giới hạn riêng hoặc dùng session/IP/client PID làm định danh).

---

### BUG-02: Giả mạo danh tính Agent (`agent_id` impersonation)
- **Độ ưu tiên:** `P1 (High Security)`
- **Vị trí code:** [`src/token_context_mcp/security/access_control.py:19-36`](file:///D:/AI/token-context-mcp/src/token_context_mcp/security/access_control.py#L19-L36) và [`src/token_context_mcp/server.py:709`](file:///D:/AI/token-context-mcp/src/token_context_mcp/server.py#L709)
- **Nguyên nhân gây ra bug:**
  ```python
  def resolve_effective_agent_id(explicit_agent_id: str | None = None) -> tuple[str, str | None]:
      env_id = os.environ.get("TOKEN_CONTEXT_AGENT_ID")
      if env_id is not None and env_id != "":
          chosen = explicit_agent_id or env_id
      else:
          chosen = explicit_agent_id or "anonymous"
  ```
  `chosen` luôn ưu tiên `explicit_agent_id` do caller tự gửi lên. Không có bất kỳ token hay chữ ký nào xác thực agent đó có thực sự là chủ sở hữu của `agent_id` đó hay không. Một agent thông thường có thể gọi `memory_lock(resource_key="build", agent_id="admin")` hoặc `memory_put(key="state", session_id="victim_session")` để ghi đè dữ liệu của session khác.
- **Giải pháp đề xuất:**
  Nếu môi trường đã định nghĩa `TOKEN_CONTEXT_AGENT_ID`, chỉ cho phép sử dụng `env_id` cố định từ container/process môi trường, hoặc nếu cho phép truyền `explicit_agent_id` thì bắt buộc phải kiểm tra quyền admin hoặc agent secret token.

---

### BUG-03: Tham số `policy` trong tool `agent_control` bị bỏ qua (Dead code)
- **Độ ưu tiên:** `P1 (Functional / Governance)`
- **Vị trí code:** [`src/token_context_mcp/server.py:590-662`](file:///D:/AI/token-context-mcp/src/token_context_mcp/server.py#L590-L662)
- **Nguyên nhân gây ra bug:**
  Khai báo hàm `agent_control`:
  ```python
  def agent_control(
      action: Literal["status", "pause", "resume", "block", "unblock", "revoke_locks", "emergency_halt", "emergency_resume"],
      admin_token: str = "",
      agent_id: str | None = None,
      reason: str = "",
      policy: Literal["FULL_ACCESS", "READ_ONLY", "CUSTOM"] | None = None,
  ) -> CallToolResult:
  ```
  Tuy nhiên, trong toàn bộ khối xử lý `_action()` từ dòng 620 đến 660, biến `policy` **hoàn toàn không được sử dụng ở bất kỳ nhánh nào**!
  Không có action `set_policy`, và các action `resume` hay `unblock` cũng không gọi `access_control.set_agent_policy(agent_id, PolicyProfile(policy))`.
  Hậu quả là quản trị viên truyền `policy` vào công cụ nhưng quyền của agent không bao giờ thay đổi được thông qua MCP tool.
- **Giải pháp đề xuất:**
  Thêm action `"set_policy"` vào danh sách action hoặc áp dụng cập nhật `access_control.set_agent_policy(agent_id, PolicyProfile(policy))` bất cứ khi nào `policy is not None`.

---

### BUG-04: Mất cô lập session: `memory_get` không nhận tham số `session_id`
- **Độ ưu tiên:** `P1 (Critical Data Flow)`
- **Vị trí code:**
  - [`src/token_context_mcp/server.py:483-503`](file:///D:/AI/token-context-mcp/src/token_context_mcp/server.py#L483-L503)
  - [`src/token_context_mcp/memory/service.py:19-36`](file:///D:/AI/token-context-mcp/src/token_context_mcp/memory/service.py#L19-L36)
  - [`src/token_context_mcp/memory/store.py:238, 303`](file:///D:/AI/token-context-mcp/src/token_context_mcp/memory/store.py#L238)
- **Nguyên nhân gây ra bug:**
  Khi agent lưu bộ nhớ bằng `memory_put`:
  ```python
  def memory_put(key, value, scope="session", namespace="", ttl=86400, session_id=None): ...
  ```
  Nếu `scope == "session"` và có truyền `session_id`, `MemoryStore.put` tự động gán `effective_ns = session_id`.
  Tuy nhiên, tool `memory_get` trong `server.py` và `MemoryService`:
  ```python
  def memory_get(key: str, scope: str = "session", namespace: str = "") -> CallToolResult:
      return _wrap(_invoke(lambda: memory_service.memory_get(key=key, scope=scope, namespace=namespace), tool_name="memory_get"))
  ```
  Hoàn toàn không có tham số `session_id`! Khi gọi `memory_get`, `effective_ns` trở thành rỗng `""`. Câu lệnh SQL tìm theo `WHERE scope='session' AND namespace='' AND key=?` sẽ trả về `status: "not_found"`.
  Dẫn tới: **Toàn bộ dữ liệu được lưu theo `session_id` không thể nào truy xuất lại được bằng `memory_get`!**
- **Giải pháp đề xuất:**
  Thêm `session_id: str | None = None` vào `memory_get` trong `server.py` và `MemoryService.memory_get`, đồng thời truyền tiếp vào `MemoryStore.get(..., session_id=session_id)`.

---

### BUG-05: Cho phép Agent bất kỳ giải phóng lock của Agent khác qua `memory_unlock`
- **Độ ưu tiên:** `P1 (Multi-agent Concurrency)`
- **Vị trí code:** [`src/token_context_mcp/server.py:529-537`](file:///D:/AI/token-context-mcp/src/token_context_mcp/server.py#L529-L537) và [`src/token_context_mcp/memory/store.py:463-470`](file:///D:/AI/token-context-mcp/src/token_context_mcp/memory/store.py#L463-L470)
- **Nguyên nhân gây ra bug:**
  Trong `store.py`:
  ```python
  def unlock(self, resource_key: str, agent_id: str) -> bool:
      with self._connection() as conn:
          cur = conn.execute(
              "DELETE FROM locks WHERE resource_key = :key AND agent_id = :agent",
              {"key": resource_key, "agent": agent_id},
          )
          return cur.rowcount > 0
  ```
  Và trong `server.py`:
  ```python
  def memory_unlock(resource_key: str, agent_id: str | None = None) -> CallToolResult:
      effective_id = resolve_effective_agent_id(agent_id)[0]
  ```
  Nếu Agent A đang giữ lock cho tài nguyên `"git_commit"`. Agent B chỉ cần gọi `memory_unlock(resource_key="git_commit", agent_id="AgentA")` là lock của Agent A bị xóa ngay lập tức. Agent B sau đó có thể chiếm lock, phá vỡ tính loại trừ tương hỗ (mutual exclusion).
- **Giải pháp đề xuất:**
  Phải xác thực danh tính thực của agent gọi tool (từ authenticated context / PID / token) thay vì cho phép client tùy ý chỉ định `agent_id` cần unlock.

---

### BUG-06: Mất toàn bộ body của symbol lớn (`root_body_omitted_budget`)
- **Độ ưu tiên:** `P1 (Retrieval Architecture)`
- **Vị trí code:** [`src/token_context_mcp/retrieve/service.py:1500-1517`](file:///D:/AI/token-context-mcp/src/token_context_mcp/retrieve/service.py#L1500-L1517)
- **Nguyên nhân gây ra bug:**
  Khi agent gọi `get_symbol_context(repo_id="token-context", symbol_id=..., include_body=True)` cho một hàm/class dài (ví dụ hàm `build_server` 630 dòng, cần 7386 tokens):
  ```python
  if needed_with_body > packing_budget:
      extra_data["root_body_tokens_needed"] = needed_with_body
      if "root_body_omitted_budget" not in warnings:
          warnings.append("root_body_omitted_budget")
      root_packet = self._symbol_packet(repository.root, store, root_symbol, False, ...)
  ```
  Do ngân sách tối đa bị chặn ở 4096 tokens, hàm này loại bỏ hoàn toàn body và trả về `body_included: false`. Agent không nhận được bất kỳ dòng code nào của thân hàm ngoài chữ ký dòng đầu tiên, đồng thời không có tham số để đọc từng đoạn (phân trang như `start_line`, `line_count`, hoặc offset).
- **Giải pháp đề xuất:**
  Thêm cơ chế cắt phân đoạn hoặc hỗ trợ tham số `line_offset` và `line_limit` trong `get_symbol_context` để khi thân hàm vượt ngân sách, server tự động trích xuất N dòng đầu tiên kèm cảnh báo phân trang thay vì bỏ trắng toàn bộ thân hàm.

---

### BUG-07: Lỗi treo vô tận trong test suite trên Windows (`test_guard.py`)
- **Độ ưu tiên:** `P1 (Platform Compatibility / CI/CD)`
- **Vị trí code:** [`tests/test_guard.py:83`](file:///D:/AI/token-context-mcp/tests/test_guard.py#L83)
- **Nguyên nhân gây ra bug:**
  ```python
  def baseline_copy(sandbox: Path, tmp_path: Path) -> Path:
      dest = tmp_path / "base_src"
      dest.mkdir()
      subprocess.run(f"git archive m12-base src | tar -x -C {dest}", shell=True, cwd=sandbox, check=True)
      return dest / "src"
  ```
  Trên Windows, khi chạy `subprocess.run(..., shell=True)` với pipeline Unix (`| tar ...`), `cmd.exe` không xử lý đúng luồng pipe giữa `git.exe` và `tar.exe`, dẫn tới tiến trình con bị deadlock và treo vĩnh viễn (làm nghẽn toàn bộ quá trình chạy pytest ở mức 34%).
- **Giải pháp đề xuất:**
  Thay thế pipeline `shell=True` bằng việc chạy `git archive -o <zip_file>` rồi giải nén bằng module chuẩn của Python `zipfile.ZipFile` hoặc `shutil.unpack_archive`, tương thích hoàn hảo trên mọi hệ điều hành.

---

### BUG-08: Lệch offset ký tự khi file nguồn chứa ký tự Unicode đa byte (UTF-8)
- **Độ ưu tiên:** `P1 (Data Integrity / Parsing)`
- **Vị trí code:** [`src/token_context_mcp/parse/treesitter.py:1153-1165`](file:///D:/AI/token-context-mcp/src/token_context_mcp/parse/treesitter.py#L1153-L1165) và [`src/token_context_mcp/retrieve/service.py:1979`](file:///D:/AI/token-context-mcp/src/token_context_mcp/retrieve/service.py#L1979)
- **Nguyên nhân gây ra bug:**
  Tree-sitter làm việc trực tiếp trên raw bytes và trả về `node.start_byte` và `node.end_byte`. Trong các file mã nguồn có chứa ký tự tiếng Việt (có dấu), tiếng Nhật, Trung hoặc emoji (chiếm từ 2 đến 4 byte mỗi ký tự), việc cắt chuỗi bằng Python string index `source[start_byte:end_byte]` (thay vì cắt trên mảng bytes rồi mới decode) dẫn đến hiện tượng cắt sai vị trí, làm cụt code, lệch span hoặc gây `UnicodeDecodeError`.
- **Giải pháp đề xuất:**
  Luôn slice trên `raw_bytes = file_path.read_bytes()[start_byte:end_byte]` trước khi gọi `.decode("utf-8", errors="replace")`.

---

### BUG-09: Lỗi xung đột khóa file SQLite trên Windows khi hoán đổi snapshot (`WinError 32`)
- **Độ ưu tiên:** `P2 (Reliability / Windows)`
- **Vị trí code:** [`src/token_context_mcp/index/runner.py:159-175, 465-485`](file:///D:/AI/token-context-mcp/src/token_context_mcp/index/runner.py#L159-L175)
- **Nguyên nhân gây ra bug:**
  Khi hoàn tất index, runner gọi `_atomic_replace` để trỏ pointer sang snapshot mới và xóa file tạm. Trên hệ điều hành Windows, cơ chế chia sẻ file rất khắt khe: nếu một tiến trình server MCP khác (hoặc pool reader) đang mở file `.sqlite-wal` hoặc `.sqlite-shm`, lệnh `os.replace` hoặc `Path.unlink` sẽ ngay lập tức ném ra lỗi `PermissionError: [WinError 32] The process cannot access the file because it is being used by another process`.
- **Giải pháp đề xuất:**
  Bọc các thao tác `unlink` và `replace` trong khối `retry` với exponential backoff (thử lại 3-5 lần sau vài trăm ms), hoặc giải phóng các connection đọc trước khi hoán đổi pointer.

---

### BUG-10: Lọc từ khóa regex trong `memory_search` làm hỏng truy vấn chứa ký tự đặc biệt
- **Độ ưu tiên:** `P2 (Search Accuracy)`
- **Vị trí code:** [`src/token_context_mcp/memory/store.py:366-372`](file:///D:/AI/token-context-mcp/src/token_context_mcp/memory/store.py#L366-L372)
- **Nguyên nhân gây ra bug:**
  ```python
  terms = re.findall(r"\w+", query)
  if not terms:
      return {"query": query, "matches_count": 0, "matches": []}
  formatted_terms = [f'"{term}"' for term in terms]
  fts_query = " AND ".join(formatted_terms)
  ```
  Nếu người dùng tìm kiếm chuỗi như `app-config-v2` hoặc `models.py`, regex `\w+` sẽ tách thành các từ độc lập `["app", "config", "v2"]` và nối thành `"app" AND "config" AND "v2"`. Điều này làm mất đi tính toàn vẹn của chuỗi ký tự ban đầu, không phân biệt được cụm từ chính xác (exact phrase match) và từ đơn lẻ.
- **Giải pháp đề xuất:**
  Bổ sung hỗ trợ cho các chuỗi được đặt trong dấu ngoặc kép hoặc dùng tokenizer bảo toàn các dấu gạch ngang/dấu chấm phổ biến trong tên file và biến kỹ thuật.

---

### BUG-11: `memory_consolidate` dọn dẹp nhầm hoặc không dọn dẹp được session entries
- **Độ ưu tiên:** `P2 (Data Consistency)`
- **Vị trí code:** [`src/token_context_mcp/memory/service.py:124-128`](file:///D:/AI/token-context-mcp/src/token_context_mcp/memory/service.py#L124-L128)
- **Nguyên nhân gây ra bug:**
  Khi `prune_transient=True`:
  ```python
  if prune_transient:
      for e in source_entries:
          self.store.delete(key=e["key"], scope=scope)
          pruned_keys.append(e["key"])
  ```
  Trong khi `self.store.delete` có chữ ký: `delete(self, key: str, scope: str = "session", namespace: str = "")`.
  Nếu `source_entries` ban đầu được tạo với một `namespace` hoặc `session_id` cụ thể, hàm delete sẽ chỉ tìm xóa ở `namespace=""`, dẫn tới việc **không thể xóa được bản ghi nguồn** như mong đợi.
- **Giải pháp đề xuất:**
  Truyền `namespace=e.get("namespace", "")` vào lệnh gọi `self.store.delete`.

---

### BUG-12: Trùng lặp `symbol_id` khi hàm bị overload (C#, Java) hoặc định nghĩa theo điều kiện
- **Độ ưu tiên:** `P2 (Graph Resolution)`
- **Vị trí code:** [`src/token_context_mcp/parse/treesitter.py:826-850`](file:///D:/AI/token-context-mcp/src/token_context_mcp/parse/treesitter.py#L826-L850)
- **Nguyên nhân gây ra bug:**
  Cấu trúc `symbol_id` phụ thuộc vào `f"{language}:{path}:{qualified_name}:{digest}"`. Trong các ngôn ngữ hướng đối tượng tĩnh như C# và Java hỗ trợ method overloading (ví dụ `void Process(int x)` và `void Process(string x)`), cả hai phương thức đều có cùng `qualified_name = "Class.Process"`. Khi lưu vào SQLite với `PRIMARY KEY (symbol_id)` hoặc khi tìm kiếm, hai hàm này bị va chạm (collision), hàm sau ghi đè hàm trước.
- **Giải pháp đề xuất:**
  Đưa chữ ký tham số (parameter types/arities) hoặc số dòng bắt đầu vào seed tạo hash của `symbol_id` đối với các ngôn ngữ tĩnh hỗ trợ nạp chồng phương thức.

---

### BUG-13: Rò rỉ connection trong `ReadConnectionPool` khi index được rebuild
- **Độ ưu tiên:** `P2 (Resource Management)`
- **Vị trí code:** [`src/token_context_mcp/retrieve/service.py:1803-1830`](file:///D:/AI/token-context-mcp/src/token_context_mcp/retrieve/service.py#L1803-L1830) và [`src/token_context_mcp/index/sqlite_store.py:145-180`](file:///D:/AI/token-context-mcp/src/token_context_mcp/index/sqlite_store.py#L145-L180)
- **Nguyên nhân gây ra bug:**
  `ReadConnectionPool` lưu kết nối theo cặp `(thread_id, resolved_path)`. Khi admin chạy lệnh reindex, database path mới được tạo và cập nhật vào `current_pointer`. Hàm `_store` gọi `self._pool.close_db(cached[1])`, nhưng lệnh này chỉ đóng kết nối của thread đang gọi hoặc đóng một phần; các thread worker khác trong pool vẫn có thể giữ tham chiếu connection mở đến file database cũ, dẫn đến rò rỉ bộ nhớ và không giải phóng được dung lượng đĩa cũ.
- **Giải pháp đề xuất:**
  Thêm cơ chế kiểm tra `db_version` hoặc `index_run_id` tự động invalidate toàn bộ connection pool khi phát hiện pointer file thay đổi.

---

### BUG-14: Lệch dòng và byte khi file nguồn có định dạng xuống dòng Windows `\r\n`
- **Độ ưu tiên:** `P3 (Platform Minor)`
- **Vị trí code:** [`src/token_context_mcp/parse/treesitter.py:192-210`](file:///D:/AI/token-context-mcp/src/token_context_mcp/parse/treesitter.py#L192-L210)
- **Nguyên nhân gây ra bug:**
  Khi file mã nguồn được tạo trên Windows với ký tự kết thúc dòng CRLF (`\r\n`), mỗi dòng có thêm byte `\r`. Khi chuyển đổi qua lại giữa số dòng (1-indexed line number) và byte offset mà không chuẩn hóa sang LF (`\n`), các đoạn mã hiển thị trong `inspect_symbol` hoặc `symbol_context` có thể bị lệch 1 dòng hoặc thừa ký tự `\r` gây lỗi hiển thị trên một số MCP client.
- **Giải pháp đề xuất:**
  Chuẩn hóa nội dung file sang Unix line-ending `\n` khi nạp vào parser hoặc tính toán offset bù trừ tương ứng với CRLF.

---

## IV. LỘ TRÌNH VÀ THỨ TỰ ƯU TIÊN SỬA CHỮA (FIX ROADMAP)

1. **Sprint 1 (Khẩn cấp - P0 & P1 Security / Data Flow):**
   - **Sửa BUG-01 & BUG-02:** Siết chặt việc định danh agent, loại bỏ việc miễn trừ rate limiting cho `anonymous`, xác thực danh tính caller.
   - **Sửa BUG-04:** Thêm `session_id` vào `memory_get` để khôi phục khả năng truy xuất dữ liệu phiên cho các agent.
   - **Sửa BUG-05:** Ngăn chặn việc tùy tiện mở khóa của agent khác trong `memory_unlock`.
   - **Sửa BUG-03:** Hoàn thiện nhánh xử lý `policy` trong tool `agent_control`.

2. **Sprint 2 (Quan trọng - P1 Retrieval & CI Compatibility):**
   - **Sửa BUG-06:** Bổ sung cơ chế phân trang windowing cho `get_symbol_context` để không làm mất trắng code của các hàm/class lớn.
   - **Sửa BUG-07:** Thay thế lệnh `tar` pipeline trong `test_guard.py` bằng Python standard library `zipfile` để test suite chạy thông suốt trên Windows.
   - **Sửa BUG-08:** Chuẩn hóa việc slice UTF-8 raw bytes trước khi decode chuỗi.

3. **Sprint 3 (Ổn định hệ thống - P2 & P3):**
   - **Sửa BUG-09:** Thêm retry/backoff cho `os.replace` trên Windows SQLite files.
   - **Sửa BUG-10 & BUG-11:** Cải thiện tokenizer trong `memory_search` và truyền đúng `namespace` trong `memory_consolidate`.
   - **Sửa BUG-12 & BUG-13:** Khắc phục va chạm ID cho phương thức nạp chồng và dọn dẹp connection pool khi switch snapshot.
