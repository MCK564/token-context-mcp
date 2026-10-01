# SỔ TAY XỬ LÝ LỖI KHI LLM / MCP CLIENT KHÔNG GỌI ĐƯỢC MCP SERVER
# (Token Context MCP Troubleshooting & Error Handling Guide)

Tài liệu này tổng hợp toàn bộ các nguyên nhân phổ biến và cách khắc phục triệt để khi LLM Client (Claude Desktop, Cursor, Google Antigravity, VS Code Copilot, Codex CLI, v.v.) không kết nối được hoặc không gọi được các công cụ của `token-context-mcp`.

---

## 1. BẢNG TRA CỨU NHANH THEO TRIỆU CHỨNG

| Triệu chứng lỗi | Nguyên nhân gốc | Cách khắc phục nhanh |
| :--- | :--- | :--- |
| **Server failed to spawn / Exited immediately** | Sai đường dẫn Python của venv hoặc file `.exe` bị khóa | Trỏ trực tiếp đường dẫn tuyệt đối đến file thực thi Python trong `.venv` kèm `-m token_context_mcp serve` |
| **LLM chỉ thấy 1 dòng tóm tắt, không thấy code/JSON** | Client không hỗ trợ `structuredContent` | Thêm cờ `--output-mode text` vào cấu hình khởi chạy server |
| **Lỗi Tool Schema Validation trên Gemini / Antigravity** | Gemini API từ chối schema có `null`, `$ref`, `$defs` | Thêm cờ `--schema-profile gemini_safe` |
| **Tool báo "Repository not found / not registered"** | Repo ID chưa được đăng ký trong `repos.toml` | Chạy lệnh `python -m token_context_mcp register` |
| **Cảnh báo `index_schema_outdated`** | Chỉ mục cũ (< Schema 2.4) | Chạy `python -m token_context_mcp index --all` |
| **SQLite error: `database is locked`** | Có tiến trình giữ khóa WAL hoặc crash chưa giải phóng | Dọn file `-wal`/`-shm` hoặc dùng tính năng VACUUM trong Desktop GUI |
| **Gọi `sample_summarize` bị timeout / quá chậm** | Ollama chạy model 7B trên CPU yếu | Chuyển sang model nhẹ `1.5b` hoặc tắt Ollama để dùng Heuristic fallback |
| **Lệnh kiểm thử hoặc index bị treo ngầm trên Windows** | Git global bật `commit.gpgsign = true` | Tạm thời bypass cờ GPG signing qua biến môi trường |

---

## 2. HƯỚNG DẪN XỬ LÝ CHI TIẾT TỪNG LỖI

---

### LỖI 1: Client Báo "Failed to spawn MCP process" hoặc "Server exited with code 1"

#### Dấu hiệu nhận biết:
- Trên Claude Desktop hoặc Cursor: Biểu tượng MCP báo đỏ (Disconnected).
- Trong log client xuất hiện: `spawn python ENOENT` hoặc `FileNotFoundError` hoặc `PermissionError`.

#### Nguyên nhân:
1. File cấu hình client dùng lệnh `python` toàn cục nhưng trên máy có nhiều bản Python hoặc chưa kích hoạt môi trường ảo.
2. Trên Windows, nếu dùng lệnh `token-context.exe`, hệ điều hành có thể khóa file binary này khi có tiến trình khác đang mở.

#### Giải pháp khắc phục:
Trong file config MCP (ví dụ `claude_desktop_config.json`), **luôn dùng đường dẫn tuyệt đối trỏ thẳng vào Python của `.venv`** và gọi dạng module:

**Trên Windows:**
```json
{
  "mcpServers": {
    "token-context": {
      "command": "D:\\AI\\token-context-mcp\\.venv\\Scripts\\python.exe",
      "args": [
        "-m",
        "token_context_mcp",
        "serve",
        "--output-mode",
        "text"
      ]
    }
  }
}
```

**Trên Linux / macOS:**
```json
{
  "mcpServers": {
    "token-context": {
      "command": "/path/to/token-context-mcp/.venv/bin/python",
      "args": [
        "-m",
        "token_context_mcp",
        "serve",
        "--output-mode",
        "text"
      ]
    }
  }
}
```

---

### LỖI 2: LLM Gọi Được Tool Nhưng Không Nhìn Thấy Nội Dung (Payload Bị Mất)

#### Dấu hiệu nhận biết:
- LLM gọi `inspect_symbol` hoặc `search_source`, tool trả về thành công nhưng LLM trả lời: *"I called the tool but only received a summary line"* hoặc *"No details were returned"*.

#### Nguyên nhân:
MCP Protocol v2 hỗ trợ trường `structuredContent` (mang JSON đầy đủ) song song với trường `content[0].text` (chuỗi văn bản tóm tắt).
- Một số client (như Claude Desktop cũ, Cursor, VS Code) **chỉ đọc trường text** và bỏ qua `structuredContent`.

#### Giải pháp khắc phục:
Thêm cờ `--output-mode text` vào tham số `args` của lệnh `serve`:
```json
"args": [
  "-m",
  "token_context_mcp",
  "serve",
  "--output-mode",
  "text"
]
```
*(Chế độ này sẽ serialize toàn bộ payload dữ liệu JSON vào trường text để mọi mô hình LLM đều đọc được 100%).*

---

### LỖI 3: Lỗi Schema Tool Trên Google Gemini / Antigravity

#### Dấu hiệu nhận biết:
- Khi khởi động server trong Gemini CLI hoặc Google Antigravity, log báo lỗi:
  `Invalid JSON Schema: anyOf with null is not supported` hoặc `$ref / $defs cannot be resolved`.

#### Nguyên nhân:
Mô hình Gemini yêu cầu lược đồ JSON Schema cực kỳ khắt khe: không chấp nhận nhánh `null`, cấm `$ref`/`$defs` và yêu cầu mọi mảng (array) phải khai báo rõ thuộc tính `items`.

#### Giải pháp khắc phục:
Thêm cờ `--schema-profile gemini_safe` (hoặc `--schema-profile auto`):
```json
"args": [
  "-m",
  "token_context_mcp",
  "serve",
  "--schema-profile",
  "gemini_safe",
  "--output-mode",
  "text"
]
```
*(Hệ thống sẽ tự động chuyển đổi toàn bộ 20 tool schema sang định dạng tương thích tuyệt đối với Gemini mà không làm mất tính năng).*

---

### LỖI 4: Lỗi "Repository not registered" Hoặc "Repository not found"

#### Dấu hiệu nhận biết:
LLM gọi công cụ báo lỗi:
`Repository 'my-repo' is not registered in the local config.`

#### Nguyên nhân:
Tool `token-context-mcp` áp dụng nguyên tắc **Read-Only & Hard Security**: Agent chỉ được phép truy xuất các repository đã được Admin đăng ký trước qua `repo_id`, không cho phép agent tự ý duyệt đường dẫn bất kỳ trên ổ đĩa.

#### Giải pháp khắc phục:
Mở terminal và đăng ký repo mong muốn:
```bash
# Kích hoạt venv và đăng ký:
python -m token_context_mcp register --repo-id my-repo --root "D:/path/to/my-repo"

# Sau đó chạy index:
python -m token_context_mcp index --repo-id my-repo
```

---

### LỖI 5: Cảnh Báo "index_schema_outdated_reindex_recommended"

#### Dấu hiệu nhận biết:
Kết quả từ `get_index_status` xuất hiện cảnh báo:
`"warnings": ["index_schema_outdated_reindex_recommended"]`

#### Nguyên nhân:
Cơ sở dữ liệu snapshot hiện tại được build từ phiên bản cũ (Schema 2.3 trở xuống), thiếu các bảng trường dữ liệu nâng cao của bản v0.2.0 (Schema 2.4) như `external_stubs`, `commit_sha`, phân giải overload theo arity.

#### Giải pháp khắc phục:
Chạy re-index toàn bộ:
```bash
python -m token_context_mcp index --all
```
*(Sau khi chạy xong, kiểm tra lại bằng `python -m token_context_mcp status --repo-id <ten-repo>` sẽ thấy schema hiển thị là `2.4`).*

---

### LỖI 6: SQLite Bị Khóa (`database is locked`)

#### Dấu hiệu nhận biết:
Log server hiển thị: `sqlite3.OperationalError: database is locked`.

#### Nguyên nhân:
Xảy ra khi nhiều tiến trình cùng truy cập vào `memory.sqlite` hoặc `governance.sqlite`, hoặc có tiến trình GUI/CLI bị tắt đột ngột để lại file khóa phụ `.sqlite-wal` / `.sqlite-shm`.

#### Giải pháp khắc phục:
1. Đóng các tiến trình Python hoặc MCP server đang chạy ngầm:
   - **Windows:** `Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force`
   - **Linux / macOS:** `pkill -f token_context_mcp`
2. Mở GUI Desktop Controller -> Chuyển sang tab **Cache & Storage** -> Chọn các database và nhấn **"Run VACUUM"**.
3. Nếu vẫn bị khóa, truy cập vào thư mục cấu hình (`%APPDATA%\token-context` hoặc `~/.config/token-context`) và xóa các file tạm có đuôi `-wal` hoặc `-shm`.

---

### LỖI 7: Tool `sample_summarize` Bị Treo Hoặc Quá Chậm

#### Dấu hiệu nhận biết:
Khi LLM gọi `sample_summarize`, client bị đứng từ 30s đến 60s hoặc báo lỗi Timeout.

#### Nguyên nhân:
- Mặc định router sẽ thăm dò Ollama trên cổng `11434`. Nếu máy không có card đồ họa GPU chuyên dụng (VRAM >= 6GB) nhưng Ollama lại đang nạp model 7B nặng trên CPU, tốc độ sinh token sẽ rất chậm.

#### Giải pháp khắc phục:
- **Cách 1: Ép dùng model nhẹ hơn (Khuyến nghị):**
  Đặt biến môi trường dùng model 1.5B:
  - Windows: `$env:TOKEN_CONTEXT_SAMPLING_MODEL = "qwen2.5-coder:1.5b"`
  - Linux / macOS: `export TOKEN_CONTEXT_SAMPLING_MODEL="qwen2.5-coder:1.5b"`
- **Cách 2: Tắt Ollama để dùng Fallback Heuristic siêu tốc:**
  Tắt Ollama service (`ollama stop` hoặc tắt app Ollama). `token-context-mcp` sẽ tự động chuyển sang cơ chế **Deterministic Heuristic Engine** xử lý ngay lập tức trên CPU trong < 10ms.

---

### LỖI 8: Tiến Trình Bị Treo Khi Chạy CLI / Pytest Trên Windows

#### Dấu hiệu nhận biết:
Lệnh `pytest` hoặc các lệnh CLI chạy đến đoạn git thì dừng mãi không kết thúc (treo ngầm).

#### Nguyên nhân:
Cấu hình Git toàn cục trên máy Windows đang bật `commit.gpgsign = true`, khiến Git gọi `gpg.exe` chờ nhập mật khẩu pinentry mà không hiển thị ra màn hình terminal.

#### Giải pháp khắc phục:
Bypass cờ GPG signing cho phiên làm việc hiện tại:
- **Windows PowerShell:**
  ```powershell
  $env:GIT_CONFIG_COUNT="1"; $env:GIT_CONFIG_KEY_0="commit.gpgsign"; $env:GIT_CONFIG_VALUE_0="false"
  ```
- **Linux / macOS Bash:**
  ```bash
  export GIT_CONFIG_COUNT=1; export GIT_CONFIG_KEY_0="commit.gpgsign"; export GIT_CONFIG_VALUE_0="false"
  ```
Sau đó chạy lại lệnh bình thường.

---

## 3. CHECKLIST KIỂM TRA TỔNG THỂ (VERIFICATION HEALTHCHECK)

Trước khi bắt đầu làm việc với LLM Client, hãy chạy 3 lệnh sau trong terminal để đảm bảo 100% hệ thống sẵn sàng:

```bash
# 1. Kiểm tra phiên bản (kỳ vọng: 0.2.0)
python -m token_context_mcp --version

# 2. Kiểm tra giao thức stdio (kỳ vọng: stdio_smoke ok)
python evals/stdio_smoke.py

# 3. Kiểm tra trạng thái repo (kỳ vọng: freshness = fresh, schema = 2.4)
python -m token_context_mcp status --repo-id <ten-repo>
```
Nếu cả 3 lệnh trên đều đạt kết quả mong muốn, hệ thống MCP Server của bạn đã hoàn toàn sẵn sàng và ổn định.
