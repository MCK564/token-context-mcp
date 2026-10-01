# MASTER PROMPT: CÀI ĐẶT `token-context-mcp` (v0.2.0) TỪ FILE ZIP & THIẾT LẬP OLLAMA LLM

> **Mục đích:** Chỉ thị toàn diện cho AI Coding Assistant (hoặc kỹ sư) tiếp nhận mã nguồn `token-context-mcp` từ file `.zip` (hoàn toàn không dùng Git), thiết lập môi trường Python >= 3.12, nạp/sử dụng model LLM cục bộ (Ollama) cho tính năng `sample_summarize`, Re-index toàn bộ dự án và cấu hình MCP Server.

---

```markdown
# TASK: Cài đặt `token-context-mcp` từ ZIP, Tích hợp Ollama LLM và Re-index Toàn bộ Codebase

Bạn là một AI Senior Systems & Tools Engineer. Nhiệm vụ của bạn là thiết lập hoàn chỉnh hệ thống `token-context-mcp` (v0.2.0) trên máy đích từ gói mã nguồn `.zip` (môi trường không kết nối trực tiếp với Git), cấu hình mô hình LLM cục bộ (Ollama) cho công cụ nén ngữ cảnh `sample_summarize`, đăng ký và re-index toàn bộ repository, sau đó kiểm tra và kết nối vào MCP Client.

Hãy thực hiện tuần tự và cẩn trọng theo các chỉ dẫn kỹ thuật sau:

---

## BƯỚC 1: GIẢI NÉN MÃ NGUỒN (KHÔNG DÙNG GIT)

Giả sử file mã nguồn đã được tải về dưới dạng `.zip`. Giải nén vào thư mục làm việc:

- **Windows (PowerShell):**
  ```powershell
  Expand-Archive -Path "token-context-mcp.zip" -DestinationPath "." -Force
  cd token-context-mcp*
  ```

- **Linux / macOS / WSL (Bash):**
  ```bash
  unzip -o token-context-mcp.zip
  cd token-context-mcp*
  ```

---

## BƯỚC 2: CÀI ĐẶT MÔI TRƯỜNG ẢO VÀ DEPENDENCIES

Chọn phương án phù hợp với trạng thái mạng của máy đích:

### Phương án A: Máy có Internet (vẫn tải được gói qua `uv` / `pip`)
Khuyến nghị dùng `uv` để cài đặt nhanh và đúng định dạng `uv.lock`:
```bash
# Dùng uv:
uv sync --all-extras
```
*Hoặc nếu dùng `pip` tiêu chuẩn:*
- **Windows:**
  ```powershell
  python -m venv .venv
  .\.venv\Scripts\Activate.ps1
  pip install --upgrade pip
  pip install -e ".[dev,gui,watch]"
  ```
- **Linux / macOS:**
  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  pip install --upgrade pip
  pip install -e ".[dev,gui,watch]"
  ```

### Phương án B: Máy hoàn toàn Air-Gapped / Offline (Không có Internet)
*(Dành cho gói ZIP đã được đóng gói sẵn kèm thư mục `wheels/` từ máy chuẩn bị trước qua lệnh `python scripts/bundle_offline_zip.py --with-wheels`):*
- **Windows:**
  ```powershell
  python -m venv .venv
  .\.venv\Scripts\Activate.ps1
  pip install --no-index --find-links=wheels -e ".[dev,gui]"
  ```
- **Linux / macOS:**
  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  pip install --no-index --find-links=wheels -e ".[dev,gui]"
  ```

---

## BƯỚC 3: THIẾT LẬP OLLAMA VÀ MÔ HÌNH LLM (CHO `sample_summarize`)

Hệ sinh thái `token-context-mcp` tích hợp tính năng **Hardware-Aware Nested Sampling** (`sample_summarize`). Hệ thống sẽ tự động quét phần cứng (VRAM/RAM), phát hiện Ollama và tự động định tuyến.

### 3.1. Kiểm tra Ollama và Model sẵn có
Chạy lệnh kiểm tra xem Ollama đã chạy và đã có model nào chưa:
```bash
ollama list
```

### 3.2. Lựa chọn Model LLM (3 kịch bản):

#### Kịch bản 1: Đã có sẵn model trên máy
Nếu lệnh `ollama list` hiển thị bạn đã tải sẵn các model như:
- `qwen2.5-coder:7b` / `qwen2.5-coder:7b-instruct-q4_K_M` (Khuyến nghị chuẩn)
- `qwen2.5-coder:1.5b` / `qwen2.5-coder:3b`
- `deepseek-coder:6.7b` / `codellama` / `llama3.1`

👉 **Hệ thống sẽ TỰ ĐỘNG nhận diện và sử dụng model coder có sẵn này!**
- Nếu muốn **chỉ định đích danh** model mà bạn muốn dùng, hãy đặt biến môi trường:
  - Windows: `$env:TOKEN_CONTEXT_SAMPLING_MODEL = "tên-model-của-bạn"`
  - Linux/macOS: `export TOKEN_CONTEXT_SAMPLING_MODEL="tên-model-của-bạn"`

#### Kịch bản 2: Máy có Internet và muốn tải model mới
Chạy script tự động tải model chuẩn tối ưu:
- **Windows (PowerShell):**
  ```powershell
  # Tải model chuẩn 7B (cần >=6GB VRAM/RAM):
  .\scripts\download_models.ps1
  
  # Hoặc tải bản siêu nhẹ 1.5B (cho máy RAM ít hoặc chạy CPU):
  .\scripts\download_models.ps1 -Lightweight
  ```
- **Linux / macOS (Bash):**
  ```bash
  chmod +x scripts/download_models.sh
  ./scripts/download_models.sh              # Tải 7B
  ./scripts/download_models.sh --lightweight # Tải 1.5B
  ```
- *Hoặc tải thủ công bằng CLI của Ollama:*
  ```bash
  ollama pull qwen2.5-coder:7b-instruct-q4_K_M
  # hoặc bản nhẹ:
  ollama pull qwen2.5-coder:1.5b
  ```

#### Kịch bản 3: Không có Ollama hoặc không tải model
👉 **Hoàn toàn không ảnh hưởng!** `token-context-mcp` đã tích hợp sẵn cơ chế **Deterministic Heuristic Fallback** trên CPU. Khi không thấy Ollama hoặc thiếu RAM/VRAM, hệ thống tự động fallback về engine regex/AST tất định với độ chính xác tuyệt đối mà không gây crash server.

---

## BƯỚC 4: CẤU HÌNH `repos.toml` VÀ ĐĂNG KÝ REPOSITORY

File cấu hình trung tâm lưu tại:
- Windows: `%APPDATA%\token-context\repos.toml` (`C:\Users\<User>\AppData\Roaming\token-context\repos.toml`)
- Linux / macOS: `~/.config/token-context/repos.toml`

1. **Khởi tạo nội dung file cấu hình:**
   Đảm bảo bật `enable_extensions = true` để kích hoạt toàn bộ 20 tools (Memory, Tool Discovery, Sampling):
   ```toml
   [server]
   max_request_bytes = 65536
   max_result_tokens = 8192
   max_graph_nodes = 200
   max_symbol_results = 30
   network_policy = "declared-deny-not-enforced"
   output_mode = "auto"
   default_view = "normal"
   enable_extensions = true
   ```

2. **Đăng ký các repository cần đánh chỉ mục (dùng module python):**
   ```bash
   # Cú pháp: python -m token_context_mcp register --repo-id <ID> --root <DUONG_DAN_TUYET_DOI>
   python -m token_context_mcp register --repo-id my-project --root "D:/path/to/my-project"
   
   # Tự đăng ký chính repo token-context:
   python -m token_context_mcp register --repo-id token-context --root .
   ```

---

## BƯỚC 5: RE-INDEX TOÀN BỘ MÃ NGUỒN (AST SCHEMA 2.4)

Ở phiên bản v0.2.0, hệ thống sử dụng định dạng snapshot SQLite v2.4 (hỗ trợ incremental, parallel parsing và hash verification). Bắt buộc phải chạy re-index:

1. **Chạy Re-index tất cả repository đã đăng ký:**
   ```bash
   python -m token_context_mcp index --all
   ```
   *(Hoặc chạy script: `python scripts/reindex_all.py`)*

2. **Kiểm tra trạng thái chỉ mục:**
   ```bash
   python -m token_context_mcp status --repo-id token-context
   ```
   *Yêu cầu:* Kết quả JSON trả về phải đạt:
   - `"freshness": "fresh"`
   - `"index_schema_version": "2.4"`
   - Số lượng `files_indexed` và `symbols_indexed` > 0.

---

## BƯỚC 6: XÁC THỰC TOÀN DIỆN (VALIDATION & SMOKE TESTS)

Chạy các kiểm thử để xác nhận môi trường và engine hoạt động trơn tru:

1. **Kiểm tra phiên bản:**
   ```bash
   python -m token_context_mcp --version
   ```
   *(Phải in ra đúng `0.2.0`).*

2. **Test khói giao thức MCP stdio:**
   ```bash
   python evals/stdio_smoke.py
   ```
   *(Kỳ vọng: Cả 2 mode `structured` và `text` đều in ra `stdio_smoke ok`).*

3. **Kiểm tra Engine Sampling (nếu có Ollama):**
   ```bash
   python -c "from token_context_mcp.sampling.hardware_probe import probe_hardware; p = probe_hardware(); print(f'Backend: {p.backend_mode}, Model: {p.recommended_model}')"
   ```

---

## BƯỚC 7: CẤU HÌNH VÀO CÁC MCP CLIENT

Trỏ trực tiếp đường dẫn file thực thi Python trong môi trường ảo `.venv`:

### A. Claude Desktop / Claude Code (`claude_desktop_config.json`)
```json
{
  "mcpServers": {
    "token-context": {
      "command": "<DUONG_DAN_TUYET_DOI_DEN_VENV>/python",
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
*(Trên Windows: thay `/python` bằng `\\Scripts\\python.exe`)*

### B. Google Antigravity / Gemini CLI (`mcp_config.json`)
```json
{
  "mcpServers": {
    "token-context": {
      "command": "<DUONG_DAN_TUYET_DOI_DEN_VENV>/python",
      "args": [
        "-m",
        "token_context_mcp",
        "serve",
        "--schema-profile",
        "gemini_safe",
        "--output-mode",
        "text"
      ]
    }
  }
}
```

---
**Báo cáo tóm tắt:**
Sau khi hoàn tất, hãy báo cáo lại:
1. Phiên bản `token_context_mcp` đã cài.
2. Trạng thái hardware probe và model Ollama đang kích hoạt.
3. Kết quả `status` các repo đã index.
4. Kết quả test `stdio_smoke.py`.
```
