# HƯỚNG DẪN SỬ DỤNG GIAO DIỆN DESKTOP GUI (`token-context-gui`)

Giao diện Desktop Controller của **Token Context MCP** được xây dựng trên nền tảng **PySide6 (Qt6)** với kiến trúc bất đồng bộ (Multi-threading + Subprocess), đảm bảo **100% không làm treo giao diện (Zero UI-thread blocking)** ngay cả khi đang đánh chỉ mục các codebase lớn.

---

## 1. Cách Khởi Chạy GUI

Tùy vào môi trường cài đặt, bạn có thể khởi chạy bằng một trong các cách sau:

### Cách 1: Qua lệnh CLI
```bash
# Khi dùng uv:
uv run token-context-gui

# Hoặc kích hoạt môi trường ảo .venv:
# Windows:
.\.venv\Scripts\python.exe -m token_context_mcp.gui.main
# Linux / macOS:
./.venv/bin/python -m token_context_mcp.gui.main
```

### Cách 2: Qua Script Launcher (Windows tiện lợi)
Nhấp đúp chuột hoặc chạy file script trong thư mục `scripts/`:
- `scripts\launch_desktop_gui.bat`
- `scripts\launch_desktop_gui.ps1`

*(Lưu ý: Nếu chạy trên Linux/macOS qua SSH không có màn hình, bạn có thể chạy chế độ offscreen để kiểm thử: `QT_QPA_PLATFORM=offscreen uv run token-context-gui`).*

---

## 2. Chi Tiết Các Tab Chức Năng

Giao diện được phân bổ thành 6 Tab điều khiển chuyên biệt trên thanh điều hướng bên trái:

```
┌────────────────────────────────────────────────────────────────────────┐
│  TOKEN CONTEXT MCP - DESKTOP CONTROLLER                                │
├──────────────┬─────────────────────────────────────────────────────────┤
│ 📊 Dashboard │  System Telemetry, Hardware Probe, Active MCP Servers   │
│ 📁 Repos     │  Danh sách Repo, Trạng thái Freshness, Re-index, Cancel │
│ ⚡ Tasks     │  Hàng đợi tiến trình, Đồ thị trực quan, Nhật ký log     │
│ 🧹 Cache     │  Dung lượng Snapshot, Dọn dẹp VACUUM, GC phiên bản cũ   │
│ 🛡️ Agents    │  Quản trị Agent, Phân quyền, Nhật ký Audit, Dừng khẩn   │
│ ⚙️ Settings  │  Cấu hình server, Mẫu config MCP Client, Copy Json      │
└──────────────┴─────────────────────────────────────────────────────────┘
```

---

### 2.1 Tab 1: 📊 Dashboard (Tổng Quan Hệ Thống)
- **Telemetry Phần Cứng:**
  - Hiển thị tài nguyên CPU, RAM, GPU VRAM (NVIDIA CUDA hoặc Apple Silicon Unified Memory).
  - Tự động nhận diện trạng thái **Ollama** và các mô hình LLM Coder sẵn có trên máy.
- **Active Servers Panel:**
  - Liệt kê thời gian thực các phiên MCP Server đang chạy ngầm (`stdio`), kèm PID, thời gian heartbeat gần nhất, `output_mode` và `schema_profile` đang hoạt động.
- **Nút "Copy Client Config":**
  - Cho phép chọn nhanh client (Claude Desktop, Claude Code, VS Code Copilot, Antigravity, Cursor) để copy khối JSON cấu hình chuẩn.

---

### 2.2 Tab 2: 📁 Repositories (Quản Lý & Đánh Chỉ Mục)
Bảng điều khiển trung tâm để quản lý mọi kho mã nguồn đã đăng ký:
- **Hệ Thống Huy Hiệu Trạng Thái (Status Badges):**
  - 🟢 `FRESH`: Chỉ mục hoàn toàn khớp với mã nguồn hiện tại, sẵn sàng cho LLM truy xuất.
  - 🟡 `STALE`: Có file mã nguồn bị thay đổi sau lần index cuối.
  - 🟠 `DOCS_CHANGED`: Chỉ có file tài liệu/markdown thay đổi (không ảnh hưởng tới mã code).
  - 🔴 `SCHEMA_OUTDATED`: Chỉ mục thuộc phiên bản cũ (schema < 2.4), cần re-index lại.
  - ⚪ `NOT_INDEXED`: Chưa từng được index.
- **Tác Vụ Đánh Chỉ Mục:**
  - **Index / Re-index (Đơn lẻ):** Chọn 1 repo và nhấn **"Re-index Selected"**.
  - **Re-index All:** Tự động chạy tuần tự toàn bộ các repo trong registry.
  - **Tiến trình chạy độc lập (`IndexProcess`):** Chạy trên tiến trình con riêng biệt với định dạng NDJSON, cập nhật thanh tiến trình mượt mà (10 fps).
  - **Nút Cancel an toàn:** Khi bấm **Cancel**, GUI sẽ đệ quy tiêu diệt sạch toàn bộ cây tiến trình con (`psutil.kill_tree`), không để lại tiến trình rác hay file khóa SQLite.

---

### 2.3 Tab 3: ⚡ Tasks (Tiến Trình & Đồ Thị AST)
- **Theo dõi tiến trình:** Giám sát chi tiết các giai đoạn phân tích AST: `scan` -> `roles` -> `edges` -> `ranks` -> `write`.
- **Khung xem Log thời gian thực:** Giới hạn tối đa 5.000 dòng, đệm mượt mà mỗi 100ms, không làm đơ giật UI.
- **Trực quan hóa cấu trúc:** Xem cấu trúc phân cấp symbol và mật độ liên kết trong repo.

---

### 2.4 Tab 4: 🧹 Cache & Storage (Bộ Nhớ & Tối Ưu Hóa)
- **Thống kê dung lượng:** Thống kê chi tiết kích thước file snapshot của từng repo, kích thước `memory.sqlite`, `governance.sqlite` và `audit.sqlite`.
- **Bảo trì an toàn (VACUUM):**
  - Cho phép người dùng tick chọn các database cần nén (`memory`, `governance`, `audit`).
  - **Nguyên tắc an toàn:** Tuyệt đối không can thiệp làm thay đổi hash của các file snapshot index bất biến.
  - Tự động thử lại 3 lần nếu gặp trạng thái SQLite `database is locked`.
- **Dọn dẹp phiên bản cũ (Clean Old Snapshots):** Tự động thu gom rác (GC) các bản snapshot lịch sử không còn sử dụng để giải phóng dung lượng ổ cứng.

---

### 2.5 Tab 5: 🛡️ Agents & Security (Kiểm Soát Agent & Bảo Mật)
- **Danh sách Agent đã kết nối:** Nhận diện Agent thông qua `TOKEN_CONTEXT_AGENT_ID` hoặc định danh ẩn danh.
- **Chính sách cấp quyền (Policy Enforcement):**
  - Cho phép cấu hình phân quyền truy cập: `allow_all`, `read_only`, `restricted_tools`.
  - Phân tách quyền đối với các công cụ nhạy cảm (`admin_tools`, `memory_lock`, `agent_control`).
- **Nút Emergency Halt (Dừng Khẩn Cấp):** Ngắt kết nối và đóng băng ngay lập tức các hoạt động truy xuất của Agent trong trường hợp phát hiện hành vi bất thường.
- **Audit Logs:** Xem nhật ký kiểm toán bảo mật theo thời gian thực (được ghi bằng SQLite WAL với độ trễ < 0.05ms).

---

### 2.6 Tab 6: ⚙️ Settings (Cấu Hình)
- **Trình chỉnh sửa `repos.toml`:** Xem và chỉnh sửa trực tiếp các tham số server:
  - `max_request_bytes`: Giới hạn payload truyền nhận (mặc định: 64 KB).
  - `max_result_tokens`: Giới hạn token trả về tối đa (mặc định: 8192).
  - `enable_extensions`: Bật/tắt 9 công cụ mở rộng (Memory, Tool Discovery, Sampling).
  - `output_mode`: Chế độ xuất dữ liệu (`auto`, `structured`, `text`).
- Lưu và tải lại cấu hình mà không cần khởi động lại toàn bộ ứng dụng.

---

## 3. Mẹo Sử Dụng Nhanh

1. **Sau khi cập nhật phiên bản mới (v0.2.0):**
   - Vào tab **Repositories** -> Nhấn nút **"Re-index all"** một lần để nâng cấp toàn bộ snapshot lên Schema 2.4.
2. **Khi thêm thư mục code mới:**
   - Có thể thêm trực tiếp qua tab **Repositories** (nút *Add Repository*) hoặc gõ lệnh `token-context register`.
3. **Debug khi có hiện tượng lag/chậm:**
   - Đặt biến môi trường `TOKEN_CONTEXT_GUI_DEBUG=1` trước khi mở GUI để kích hoạt `EventLoopWatchdog` (tự động ghi log chi tiết nếu có thao tác UI bị đứng quá 100ms).
