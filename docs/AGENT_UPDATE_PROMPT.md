# HƯỚNG DẪN ĐỒNG BỘ, NÂNG CẤP VÀ CÀI ĐẶT AIR-GAPPED DÀNH CHO AI AGENT
# (Master Agent Update & Air-Gapped Installation Prompt for `token-context-mcp`)

> **Phiên bản kiến trúc:** 19 Tools (10 Core Retrieval + 9 Extended Agentic Infrastructure)  
> **Áp dụng cho:** Các máy nâng cấp từ commit cũ, các môi trường không có kết nối Git trực tiếp, hoặc triển khai thủ công từ gói ZIP / mạng nội bộ air-gapped.  
> **Ghi nhận học hỏi & bản quyền ý tưởng:** Tích hợp các kỹ thuật prompt envelopes, verbatim constraints, A2A tool chaining và memory consolidation từ kho mã nguồn mở `GoogleCloudPlatform/generative-ai` (Google Cloud GenAI).

---

## 1. Mục đích & Phạm vi

Tài liệu này cung cấp **toàn bộ chỉ thị kỹ thuật (System Prompt & Action Plan)** cho một AI Coding Agent (Claude Code, Codex, Antigravity, GitHub Copilot, v.v.) khi được giao nhiệm vụ:
1. Tiếp nhận và nâng cấp codebase `token-context-mcp` từ một commit/snapshot cũ hoặc từ file `.zip` tải về thủ công.
2. Thiết lập môi trường, đồng bộ thư viện và mô hình suy luận cục bộ mà **không cần truy cập trực tiếp Git repository**.
3. Bảo toàn 100% dữ liệu đã cấu hình của người dùng (danh sách repo đã index, cache AST, bộ nhớ episodic).
4. Kích hoạt toàn bộ **19 công cụ** (gồm 10 công cụ truy xuất cấu trúc lõi và 9 công cụ hạ tầng agent mở rộng).
5. Vượt qua 100% bộ kiểm thử tự động (`pytest` 94+ test cases và `evals/stdio_smoke.py`).

---

## 2. Bản đồ Tính năng & Kiến trúc 19 Tools

Codebase phân tách rành mạch thành 2 tầng công cụ:

### 2.1 Tầng 1: 10 Công cụ Lõi (Core Repository Retrieval) — Luôn kích hoạt
Không phụ thuộc bất kỳ daemon ngoại vi nào, mở SQLite snapshot ở chế độ Read-Only:
1. `list_repositories`: Liệt kê các repo đã đăng ký và hồ sơ ngân sách.
2. `get_repo_map`: Sơ đồ symbol phân cấp kèm thứ hạng PageRank/Topology.
3. `find_symbols`: Tìm kiếm symbol theo tên/đường dẫn với giới hạn ngân sách.
4. `get_module_dependents`: Phân tích quan hệ import ngược giữa các module.
5. `search_source`: Tìm kiếm toàn văn (FTS5) trong mã nguồn.
6. `get_file_skeleton`: Trích xuất khung xương, class/hàm và chữ ký mà không đọc thân hàm.
7. `get_symbol_context`: Ngữ cảnh chi tiết quanh symbol (định nghĩa, callers, callees, depth 0-3).
8. `get_impact_slice`: Phân tích lát cắt ảnh hưởng khi sửa đổi một symbol.
9. `get_index_status`: Kiểm tra độ tươi (`fresh` / `stale`) và tính toàn vẹn của chỉ mục.
10. `inspect_symbol`: Truy xuất composite một lượt tối ưu hóa token.

### 2.2 Tầng 2: 9 Công cụ Mở rộng (Extended Infrastructure) — Bật qua `enable_extensions = true`
Học hỏi trực tiếp từ kiến trúc Google Cloud GenAI (`GoogleCloudPlatform/generative-ai`):
1. **Dynamic Tool Discovery (3 tools):**
   - `list_available_tools`: Liệt kê catalog công cụ theo danh mục (retrieval, memory, discovery, sampling).
   - `search_tools`: Tìm kiếm công cụ phù hợp với mục tiêu của agent, kèm ví dụ và mẹo token.
   - `get_tool_schema`: Nạp schema chi tiết theo nhu cầu (just-in-time loading) để tiết kiệm ngữ cảnh.
2. **Episodic Cross-Session Memory & Consolidation (5 tools):**
   - `memory_put`: Lưu trữ tri thức, quyết định kiến trúc, quy ước code vào SQLite cục bộ (`memory.sqlite`).
   - `memory_get`: Truy xuất bản ghi nhớ cụ thể theo key.
   - `memory_search`: Tìm kiếm ngữ nghĩa/toàn văn trên các bài học kinh nghiệm đã tích lũy.
   - `memory_lock`: Đóng băng bản ghi nhớ bất biến (không bị ghi đè tự động).
   - `memory_consolidate`: *(Lấy cảm hứng từ Always-On Memory Agent của Google GenAI)* Hợp nhất tri thức, khử trùng lặp phân cấp, gom cụm chủ đề và tự động tổng hợp bài học sâu sắc.
3. **Structured Nested Sampling (1 tool):**
   - `sample_summarize`: Nén và trích xuất ràng buộc kỹ thuật từ mã nguồn thông qua mô hình 7B cục bộ (`qwen2.5-coder:7b-instruct-q4_K_M` qua Ollama) hoặc động cơ suy luận Heuristic tất định khi máy không có GPU/Ollama.
   - Sử dụng **Delimited Envelopes** (`<<<SOURCE_CODE_START>>>` ... `<<<SOURCE_CODE_END>>>`) chống injection.
   - Cung cấp **Quote-before-Synthesize** (`ConstraintEvidence`, trích dẫn nguyên văn mã và `line_span`).
   - Cung cấp **A2A Tool Chaining Metadata** (`recommended_followups`, `prerequisites`).

---

## 3. Nguyên tắc Vàng: Bảo toàn Dữ liệu (Zero Data Loss)

Khi cập nhật mã nguồn từ file ZIP mới:
> [!CAUTION]
> **TUYỆT ĐỐI KHÔNG GHI ĐÈ HOẶC XÓA** các thư mục và tệp tin sau:
> 1. `%APPDATA%\token-context-mcp\repos.toml` (Windows) hoặc `~/.config/token-context-mcp/repos.toml` (Linux/macOS) — *File đăng ký danh sách repo của người dùng*.
> 2. `%APPDATA%\token-context-mcp\indexes\` — *Toàn bộ cơ sở dữ liệu SQLite AST đã index*.
> 3. `%APPDATA%\token-context-mcp\memory.sqlite` — *Kho tri thức và ký ức của agent*.

---

## 4. Kịch bản Triển khai & Cập nhật cho Agent

### 4.1 Quy trình Cập nhật từ File ZIP Mới (Khi không có Git)

Khi người dùng cung cấp một file `token-context-mcp.zip` mới vào thư mục:

```powershell
# 1. Giải nén đè mã nguồn mới vào thư mục làm việc (loại trừ configs)
Expand-Archive -Path "token-context-mcp.zip" -DestinationPath "temp_update" -Force
Copy-Item -Path "temp_update\token-context-mcp\src" -Destination ".\src" -Recurse -Force
Copy-Item -Path "temp_update\token-context-mcp\tests" -Destination ".\tests" -Recurse -Force
Copy-Item -Path "temp_update\token-context-mcp\docs" -Destination ".\docs" -Recurse -Force
Copy-Item -Path "temp_update\token-context-mcp\scripts" -Destination ".\scripts" -Recurse -Force
Copy-Item -Path "temp_update\token-context-mcp\evals" -Destination ".\evals" -Recurse -Force
Copy-Item -Path "temp_update\token-context-mcp\pyproject.toml" -Destination ".\pyproject.toml" -Force
Copy-Item -Path "temp_update\token-context-mcp\uv.lock" -Destination ".\uv.lock" -Force
Remove-Item -Recurse -Force "temp_update"
```

### 4.2 Cài đặt Dependencies & Môi trường

#### Lựa chọn A: Môi trường có kết nối Internet (Sử dụng Script tự động)
- **Windows:**
  ```powershell
  .\scripts\setup_environment.ps1
  ```
- **Linux / macOS:**
  ```bash
  chmod +x scripts/setup_environment.sh scripts/download_models.sh
  ./scripts/setup_environment.sh
  ```

#### Lựa chọn B: Môi trường Air-Gapped / Hoàn toàn Offline (Sử dụng Wheels cục bộ)
Nếu gói ZIP đi kèm thư mục `wheels/`:
```powershell
# Tạo venv nếu chưa có
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Cài đặt toàn bộ dependencies offline
pip install --no-index --find-links=wheels -e .[dev]
```

### 4.3 Cấu hình `repos.toml` để kích hoạt đủ 19 Tools

Agent phải kiểm tra file `%APPDATA%\token-context-mcp\repos.toml` (Windows) hoặc `~/.config/token-context-mcp/repos.toml` (Linux/macOS).  
Đảm bảo cờ `enable_extensions = true` đã được bật trong khối `[server]`:

```toml
[server]
max_request_bytes  = 65536
max_result_tokens  = 4096
max_graph_nodes    = 200
max_symbol_results = 30
network_policy     = "declared-deny-not-enforced"
enable_extensions  = true    # BẬT ĐỦ 19 TOOLS (Discovery, Memory, Sampling)
```

### 4.4 Tải & Xác minh Local Model cho Nested Sampling (Ollama)

Để sử dụng mô hình 7B cục bộ tối ưu CPU/GPU:
- **Windows:**
  ```powershell
  .\scripts\download_models.ps1
  # Hoặc nếu máy RAM yếu (dưới 8GB RAM):
  .\scripts\download_models.ps1 -Lightweight
  ```
- **Linux / macOS:**
  ```bash
  ./scripts/download_models.sh
  # Hoặc bản nhẹ:
  ./scripts/download_models.sh --lightweight
  ```
*(Lưu ý: Nếu máy không thể cài Ollama, hệ thống tự động fallback 100% sang Deterministic Heuristic Engine, không gây lỗi).*

### 4.5 Kiểm thử Nghiệm thu Bắt buộc (Verification Checklist)

Agent phải chạy và xác nhận 100% các lệnh sau đạt kết quả xanh:

1. **Bộ Unit Test:**
   ```bash
   uv run --extra dev pytest
   ```
   *Kỳ vọng: 94 passed, 4 skipped (hoặc tương đương, 0 failure).*

2. **Kiểm thử Stdio Smoke (Chấp nhận cả 10 và 19 tools):**
   ```bash
   uv run python evals/stdio_smoke.py
   ```
   *Kỳ vọng: Thoát mã 0 (Clean exit code 0).*

3. **Kiểm tra trạng thái các Repo đã Index:**
   ```bash
   uv run python -m token_context_mcp status --repo-id <repo_id>
   ```

---

## 5. Đoạn Prompt Mẫu Cho Phép Copy-Paste Cho AI Agent

Dưới đây là đoạn văn bản đóng gói sẵn, bạn có thể copy trực tiếp và gửi cho bất kỳ AI Agent nào đang hỗ trợ bạn:

```markdown
Bạn là Kỹ sư Hệ thống Cấp cao đang phụ trách nâng cấp và cấu hình kho mã nguồn `token-context-mcp` trên máy tính này.
Môi trường hiện tại không thể dùng git clone/pull trực tiếp (môi trường mạng hạn chế hoặc sử dụng file ZIP tải thủ công).

Hãy thực hiện đầy đủ các nhiệm vụ sau theo tài liệu `docs/AGENT_UPDATE_PROMPT.md`:
1. BẢO TỒN DỮ LIỆU: Tuyệt đối không xóa hoặc ghi đè registry repo (%APPDATA%\token-context-mcp\repos.toml hoặc ~/.config/token-context-mcp/repos.toml), thư mục indexes/ và file memory.sqlite.
2. ĐỒNG BỘ MÃ NGUỒN: Cập nhật codebase lên phiên bản 19 công cụ (10 Core Retrieval + 9 Extended Infrastructure: Discovery, Episodic Memory, Nested Sampling).
3. ĐỒNG BỘ THƯ VIỆN: Chạy script `scripts/setup_environment.ps1` (trên Windows) hoặc `scripts/setup_environment.sh` (trên Linux). Nếu trong môi trường hoàn toàn offline, sử dụng các file wheel trong thư mục `wheels/` với lệnh `pip install --no-index --find-links=wheels -e .[dev]`.
4. CẤU HÌNH EXTENSIONS: Đảm bảo trong `repos.toml` mục `[server]` đã có `enable_extensions = true`.
5. MÔ HÌNH SUY LUẬN: Chạy `scripts/download_models.ps1` (hoặc `download_models.sh`) để kiểm tra hoặc tải mô hình `qwen2.5-coder:7b-instruct-q4_K_M` từ Ollama. Nếu không có Ollama, xác nhận hệ thống kích hoạt Deterministic Heuristic Engine.
6. XÁC MINH TOÀN DIỆN: Chạy `uv run --extra dev pytest` (phải đạt 94+ tests pass) và `uv run python evals/stdio_smoke.py` (phải pass với mã thoát 0).
7. HƯỚNG DẪN AGENT CLIENT: Cung cấp hướng dẫn khởi động lại MCP server trên Claude Code, VS Code Copilot hoặc Antigravity để nạp đủ 19 công cụ.
```

---

## 6. Đóng gói Bản phân phối Offline (`bundle_offline_zip.py`)

Nếu bạn cần chuẩn bị một gói ZIP chuẩn để gửi sang các máy tính khác (máy công ty, máy air-gapped không mạng):
```bash
# Đóng gói mã nguồn sạch (loại trừ .git, cache, index, config cá nhân)
python scripts/bundle_offline_zip.py -o dist/token-context-mcp-clean.zip

# Đóng gói kèm toàn bộ bánh xe (wheels) để cài đặt 100% không cần mạng
python scripts/bundle_offline_zip.py --with-wheels -o dist/token-context-mcp-offline-with-wheels.zip
```
