# Các Kịch Bản Khắc Phục Sự Cố & Vận Hành (R08 - R12)

Tài liệu này tổng hợp các kịch bản ứng phó sự cố thiết yếu trong quá trình vận hành thực tế: cạn kiệt ngân sách, chỉ mục truy xuất lỗi thời, khôi phục sau sự cố crash, đối chiếu định tuyến đa ngôn ngữ và cách ly xung đột ghi đè file giữa nhiều worker.

---

## Recipe R08: Hết Ngân Sách, Hủy Bỏ & Thay Đổi Hướng

### 1. Khi Nào Dùng
- Lượt chạy hiện tại chạm ngưỡng giới hạn ngân sách (tiền hoặc token), hoặc người dùng gửi tín hiệu hủy (cancel) / chuyển hướng (steer) trong khi các worker đang chạy.
- **Anti-pattern**: Tiếp tục giao các tác vụ con đang chờ xử lý sau khi đã hết ngân sách hoặc âm thầm bỏ qua việc ghi nhận token đã tiêu tốn.

### 2. Quy Trình Khắc Phục Cụ Thể
1. **Ngắt mạch tự động (Circuit Breaker)**: Sổ cái phát hiện `total_committed >= max_budget_limit`.
2. **Phát tín hiệu hủy tức thì**: Gửi lệnh hủy tới tất cả các worker đang chạy; chuyển các tác vụ đang chờ sang `status="cancelled"`.
3. **Bảo toàn dữ liệu hạch toán**: Sổ cái giữ nguyên mọi sự kiện đã quyết toán và giải phóng các khoản tạm giữ chưa chi.
4. **Phản hồi trung thực có giới hạn**: Bộ điều phối lập câu trả lời trung thực nêu rõ các tác vụ chưa hoàn tất và trạng thái hiện tại, tuyệt đối không bịa đặt kết luận cho các phần việc bị hủy.

---

## Recipe R09: Xử Lý Khi Index Lỗi Thời Hoặc URI Bị Lỗi

### 1. Khi Nào Dùng
- Index của Token-Context MCP báo `status="stale"` (ví dụ: các file mã nguồn đã sửa đổi đang chờ index lại), hoặc một hosted worker ở xa nhận được đường dẫn URI file cục bộ mà nó không thể truy cập.
- **Anti-pattern**: Worker tự tạo ra nội dung file giả định hoặc âm thầm tin tưởng vào biểu đồ symbol đã cũ.

### 2. Quy Trình Khắc Phục Cụ Thể
1. **Kiểm tra tính tươi mới**: Worker đọc metadata của file; so sánh mã băm SHA-256 trên đĩa với bản ghi trong index.
2. **Phát hiện trạng thái cũ**: Index báo mã băm không khớp hoặc file nằm trong danh sách chờ index (`pending`).
3. **Dự phòng đọc trực tiếp có giới hạn**: Bỏ qua index cũ; đọc trực tiếp đoạn dòng mục tiêu từ file trên đĩa hoặc yêu cầu đoạn trích tươi mới thông qua công cụ hệ thống file trực tiếp của host.
4. **Minh bạch xuất xứ**: Kết quả của worker phải ghi rõ `evidence_freshness="direct_disk_read_stale_index_fallback"`.

---

## Recipe R10: Khôi Phục Sau Sự Cố & Tiếp Tục Idempotent

### 1. Khi Nào Dùng
- Tiến trình của host bị sập (crash), ngắt kết nối hoặc khởi động lại giữa chừng khi đang điều phối luồng nhiều worker.
- **Anti-pattern**: Chạy lại toàn bộ quy trình từ đầu làm tốn thêm chi phí gọi model đã thanh toán, hoặc lặp lại các thao tác ghi file ngoài ý muốn.

### 2. Quy Trình Khắc Phục Cụ Thể
1. **Nạp Checkpoint bền vững**: Graph engine tải lại ảnh chụp trạng thái đã xác minh gần nhất từ SQLite/Postgres dựa vào `run_id`.
2. **Reducer trạng thái Idempotent**: Reducer khử trùng lặp các sự kiện đến bằng khóa `(task_id, attempt_id, result_revision)`. Các tác vụ đã hoàn thành tuyệt đối không được phân công lại.
3. **Đối soát sổ cái**: Đối soát các khoản tạm giữ đang treo với nhật ký nhà cung cấp trước khi cấp phát ngân sách mới.
4. **Tiếp tục liền mạch**: Chỉ phát lệnh chạy các tác vụ ở trạng thái `ready` hoặc các tác vụ đang chạy (`running`) chưa được commit tại thời điểm xảy ra sự cố.

---

## Recipe R11: Thử Nghiệm Đối Chiếu Đa Ngôn Ngữ EN/VI

### 1. Khi Nào Dùng
- Bạn nhận được các yêu cầu tương đương bằng tiếng Anh và tiếng Việt (bao gồm cả tiếng Việt không dấu và cách diễn đạt pha trộn thuật ngữ code).
- Bạn cần xác minh rằng cả hai ngôn ngữ đều cho ra cùng một nhóm tác vụ định tuyến, cùng một tier mô hình và chất lượng câu trả lời tương đương.

### 2. Thử Nghiệm Kiểm Toán Cụ Thể

```text
[TEST CASE EN]: "Inspect how pack_by_budget drops items in token_budget.py"
  -> Route: extract_evidence (sim: 0.865) -> Tier: MODEL_ECONOMY
[TEST CASE VI]: "Kiểm tra cách pack_by_budget bỏ qua các mục trong token_budget.py"
  -> Route: extract_evidence (sim: 0.852) -> Tier: MODEL_ECONOMY
[TEST CASE VI KHÔNG DẤU]: "Kiem tra cach pack_by_budget bo qua cac muc trong token_budget.py"
  -> Route: extract_evidence (sim: 0.838) -> Tier: MODEL_ECONOMY
[TEST CASE VI PHA TRỘN CODE]: "Check giup minh logic pack_by_budget trong token_budget.py xem co bi drop item khong"
  -> Route: extract_evidence (sim: 0.841) -> Tier: MODEL_ECONOMY
```

### 3. Điều Kiện Kiểm Chứng
- Xác nhận cả 4 trường hợp đều định tuyến về `extract_evidence` và chọn `MODEL_ECONOMY`. Nếu có trường hợp rơi vào `unknown` hoặc chọn nhầm tier, cần bổ sung thêm các ví dụ mẫu (exemplars) cho bộ định tuyến ngữ nghĩa.

---

## Recipe R12: Cách Ly Xung Đột Khi Nhiều Worker Sửa Cùng File

### 1. Khi Nào Dùng
- Hai worker chạy song song vô tình được giao các tác vụ đụng chạm tới cùng một file hoặc cấu hình dùng chung.
- **Anti-pattern**: Cho phép cả hai worker cùng ghi đè trực tiếp vào thư mục làm việc, gây hỏng file do xung đột ghi đồng thời (race condition).

### 2. Quy Trình Cách Ly & Xử Lý Cụ Thể
1. **Kiểm tra phạm vi trước khi giao việc**: Bộ lập lịch kiểm tra `allowed_scope_files` của tất cả các tác vụ chạy song song. Nếu phát hiện trùng lặp:
   - *Lựa chọn A (Tuần tự hóa)*: Chuyển sang chuỗi DAG tuần tự (Tác vụ A hoàn thành xong mới chạy Tác vụ B).
   - *Lựa chọn B (Cách ly bằng Patch)*: Các worker chỉ tạo ra bản vá diff (`.diff`) trong bộ nhớ; nghiêm cấm worker ghi trực tiếp vào cây mã nguồn.
2. **Bộ điều phối giải quyết xung đột**: Bộ điều phối mạnh tiếp nhận cả hai bản diff, kiểm tra các dòng bị chồng chéo, giải quyết các xung đột merge hunk, và thực hiện một thao tác ghi duy nhất đã được kiểm chứng.
