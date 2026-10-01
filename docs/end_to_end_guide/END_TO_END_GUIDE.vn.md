# HƯỚNG DẪN TOÀN DIỆN TỪ ĐẦU ĐẾN CUỐI (END-TO-END GUIDE)
# Thiết Lập, Cấu Hình `mcp.json`, Tích Hợp Ollama Qwen, Đánh Chỉ Mục, Desktop GUI & Test Prompt

Tài liệu này hướng dẫn chi tiết quy trình triển khai hoàn chỉnh **Token Context MCP (v0.2.0)** từ A đến Z, bao gồm: cài đặt package, thiết lập mô hình LLM cục bộ (Ollama Qwen), đăng ký kho mã nguồn, cấu hình client MCP, kiểm tra tích hợp và sử dụng Desktop GUI.

---

## MỤC LỤC
1. [Cài Đặt Môi Trường & Thư Viện (Wheel / Source)](#1-cài-đặt-môi-trường--thư-viện)
2. [Tải & Cấu Hình Ollama LLM (Qwen2.5-Coder)](#2-tải--cấu-hình-ollama-llm-qwen25-coder)
3. [Đăng Ký Kho Mã Nguồn (Repository Registration)](#3-đăng-ký-kho-mã-nguồn)
4. [Đánh Chỉ Mục (Index AST Snapshot Schema 2.4)](#4-đánh-chỉ-mục-index)
5. [Cấu Hình MCP Client Trong `.vscode/mcp.json`](#5-cấu-hình-mcp-client-trong-vscodemcpjson)
6. [Khởi Chạy & Sử Dụng Desktop GUI](#6-khởi-chạy--sử-dụng-desktop-gui)
7. [Kiểm Tra Tích Hợp Qwen LLM (`sample_summarize`)](#7-kiểm-tra-tích-hợp-qwen-llm)
8. [Mẫu Test Prompt Chuẩn Cho AI Coding Assistant](#8-mẫu-test-prompt-chuẩn)

---

## 1. CÀI ĐẶT MÔI TRƯỜNG & THƯ VIỆN

Yêu cầu hệ điều hành: Windows 10/11, macOS hoặc Linux. **Python >= 3.12**.

### Cách A: Cài đặt từ file `.whl` (Khuyến nghị cho người dùng)
Tải file `token_context_mcp-0.2.0-py3-none-any.whl` từ GitHub Release và cài đặt:
```bash
# Tạo môi trường ảo (khuyến nghị):
python -m venv .venv

# Kích hoạt môi trường ảo:
# Windows:
.\.venv\Scripts\Activate.ps1
# Linux / macOS:
source .venv/bin/activate

# Cài đặt file wheel kèm tính năng GUI:
pip install "token_context_mcp-0.2.0-py3-none-any.whl[gui]"
```

### Cách B: Cài đặt từ mã nguồn (Source Code / Git / ZIP)
```bash
# Dùng uv:
uv sync --all-extras

# Hoặc dùng pip:
pip install -e ".[gui,dev,watch]"
```

*Kiểm tra cài đặt:*
```bash
token-context --version
# Kết quả kỳ vọng: 0.2.0
```

---

## 2. TẢI & CẤU HÌNH OLLAMA LLM (QWEN2.5-CODER)

`token-context-mcp` sử dụng mô hình LLM cục bộ cho công cụ **`sample_summarize`** (trích xuất ràng buộc code và tóm tắt có bảo toàn cấu trúc).

### 2.1. Cài đặt Ollama
- **Windows / macOS:** Tải bộ cài chính thức tại [ollama.com/download](https://ollama.com/download) và cài đặt.
- **Linux:**
  ```bash
  curl -fsSL https://ollama.com/install.sh | sh
  ```

### 2.2. Khởi động Ollama Service
Sau khi cài đặt, đảm bảo dịch vụ Ollama đang chạy:
- Trên Windows/macOS: Ứng dụng Ollama tự chạy ngầm ở khay hệ thống (System Tray).
- Hoặc mở terminal gõ: `ollama serve`.
- Kiểm tra cổng kết nối: mở trình duyệt truy cập `http://localhost:11434` (thấy dòng *"Ollama is running"* là thành công).

### 2.3. Tải Mô Hình Qwen2.5-Coder (Chọn 1 trong 2 bản)

#### Lựa chọn 1: Bản chuẩn 7B (Khuyến nghị cho máy có GPU VRAM >= 6GB hoặc RAM >= 16GB)
```bash
ollama pull qwen2.5-coder:7b-instruct-q4_K_M
```
*(Hoặc dùng script có sẵn: `powershell .\scripts\download_models.ps1` trên Windows / `./scripts/download_models.sh` trên Linux).*

#### Lựa chọn 2: Bản nhẹ 1.5B (Cho máy yếu, không có GPU rời, chạy thuần CPU)
```bash
ollama pull qwen2.5-coder:1.5b
```

### 2.4. Kiểm tra danh sách model
```bash
ollama list
```
*Kết quả hiển thị `qwen2.5-coder:...` là bạn đã sẵn sàng.*

> **Lưu ý:** Nếu không có GPU hoặc không cài Ollama, hệ thống vẫn hoạt động bình thường nhờ cơ chế **Deterministic Heuristic Fallback** tự động trên CPU.

---

## 3. ĐĂNG KÝ KHO MÃ NGUỒN

Trước khi LLM có thể đọc hiểu code, bạn cần đăng ký đường dẫn thư mục dự án với server:

```bash
# Cú pháp: token-context register --repo-id <TEN_REPO> --root <DUONG_DAN_TUYET_DOI>

# Ví dụ trên Windows:
token-context register --repo-id my-project --root "D:\Projects\my-project"

# Ví dụ trên Linux/macOS:
token-context register --repo-id my-project --root "/Users/name/projects/my-project"
```

*Kiểm tra danh sách đã đăng ký:* Mở file `%APPDATA%\token-context\repos.toml` (Windows) hoặc `~/.config/token-context/repos.toml` (Linux/macOS) để xem danh sách `[repos.<id>]`.

---

## 4. ĐÁNH CHỈ MỤC (INDEX)

Xây dựng đồ thị phụ thuộc (call graph) và snapshot SQLite AST (Schema 2.4):

```bash
# Index một repository cụ thể:
token-context index --repo-id my-project

# Hoặc Index TẤT CẢ các repo đã đăng ký:
token-context index --all
```

*Kiểm tra tính sẵn sàng (Healthcheck):*
```bash
token-context status --repo-id my-project
```
**Yêu cầu:** Trường `"freshness"` hiển thị `"fresh"`, `"index_schema_version"` là `"2.4"`.

---

## 5. CẤU HÌNH MCP CLIENT TRONG `.vscode/mcp.json`

Mở file `.vscode/mcp.json` trong dự án VS Code của bạn và cấu hình như sau:

```json
{
  "mcpServers": {
    "token-context": {
      "type": "stdio",
      "command": "token-context",
      "args": [
        "serve",
        "--output-mode",
        "text"
      ]
    }
  }
}
```

### Giải thích các tham số quan trọng:
- `"type": "stdio"`: **Bắt buộc giữ nguyên** để VS Code nhận diện kết nối qua Standard Input/Output.
- `"command"`: Lệnh khởi chạy. Nếu môi trường Python chưa nằm trong biến môi trường PATH, bạn hãy điền đường dẫn tuyệt đối đến file thực thi:
  - Windows: `"D:\\AI\\token-context-mcp\\.venv\\Scripts\\token-context.exe"`
  - Linux/Mac: `"/path/to/.venv/bin/token-context"`
- `"--output-mode", "text"`: **Rất quan trọng**, đảm bảo mọi mô hình LLM (kể cả client chưa hỗ trợ `structuredContent`) đều đọc được đầy đủ dữ liệu code trả về.
- *(Tùy chọn)* Nếu bạn dùng client là **Google Antigravity / Gemini CLI**, thêm cờ:
  `"args": ["serve", "--schema-profile", "gemini_safe", "--output-mode", "text"]`.

---

## 6. KHỞI CHẠY & SỬ DỤNG DESKTOP GUI

Sau khi đã cài đặt dependencies cho GUI (`[gui]` extra bao gồm `PySide6`):

### 6.1. Khởi chạy GUI
```bash
token-context-gui
```
*(Hoặc nhấp đúp file: `scripts\launch_desktop_gui.bat` trên Windows).*

### 6.2. Các thao tác chính trên GUI:
1. **Tab Dashboard:** Xem mức tiêu thụ CPU, RAM, VRAM và trạng thái phát hiện mô hình Ollama.
2. **Tab Repositories:**
   - Kiểm tra huy hiệu màu xanh 🟢 `FRESH` bên cạnh tên repo.
   - Nhấn nút **"Re-index all"** nếu thấy huy hiệu màu đỏ 🔴 `SCHEMA_OUTDATED`.
   - Có thể bấm **"Cancel"** bất kỳ lúc nào để dừng an toàn mà không làm lỗi database.
3. **Tab Settings:** Cho phép sao chép nhanh khối cấu hình JSON cho từng loại client.

---

## 7. KIỂM TRA TÍCH HỢP QWEN LLM

Để xác nhận `token-context-mcp` đã nhận diện thành công Ollama và model Qwen trên máy bạn, hãy chạy lệnh kiểm tra sau trong terminal:

```bash
python -c "from token_context_mcp.sampling.hardware_probe import probe_hardware; p = probe_hardware(force_refresh=True); print(f'Ollama Connected: {p.has_ollama}\nBackend Mode: {p.backend_mode}\nDetected Model: {p.recommended_model}\nAvailable Models: {p.available_models}')"
```

### Kết quả kỳ vọng:
```text
Ollama Connected: True
Backend Mode: ollama_gpu (hoặc ollama_cpu)
Detected Model: qwen2.5-coder:7b-instruct-q4_K_M (hoặc qwen2.5-coder:1.5b)
Available Models: ['qwen2.5-coder:...']
```

#### Test nén mã nguồn thử nghiệm:
```bash
python -c "from token_context_mcp.sampling.router import SamplingRouter; r = SamplingRouter(); res = r.summarize('def add(a, b):\n    return a + b', intent='test'); print('Output:', res.get('summary'))"
```
Nếu màn hình in ra kết quả phân tích tóm tắt hàm, tính năng LLM Sampling đã hoạt động hoàn hảo 100%!

---

## 8. MẪU TEST PROMPT CHUẨN

Khi trò chuyện với AI Coding Assistant trong VS Code / Claude / Cursor, hãy gửi prompt mẫu sau để kiểm tra khả năng truy xuất của MCP:

```markdown
Bạn là trợ lý lập trình chuyên nghiệp. Bạn có quyền truy cập vào MCP server `token-context-mcp`.

THÔNG TIN ĐẦU VÀO:
- Repository: my-project (đã được đánh chỉ mục và có trạng thái "fresh")
- Yêu cầu: "Tìm hiểu kiến trúc hàm khởi tạo và luồng xử lý chính của dự án."

QUY TRÌNH TRUY XUẤT YÊU CẦU:
1. Gọi `get_index_status(repo_id="my-project")` để kiểm tra độ tươi của chỉ mục.
2. Dùng `search_source` hoặc `find_symbols` để xác định các file và class cốt lõi.
3. Gọi `inspect_symbol(repo_id="my-project", symbol="<ten_symbol>", view="full")` để đọc trọn vẹn context packet tiết kiệm token.
4. Trả lời ngắn gọn, nêu rõ đường dẫn file và dòng code cụ thể (`file:line`).
```

Khi AI phản hồi kèm các dẫn chiếu chính xác từ công cụ `inspect_symbol` và `get_index_status`, toàn bộ quy trình End-to-End của bạn đã hoàn tất xuất sắc!
