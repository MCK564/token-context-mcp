# Các Recipe Điều Phối Bán Tự Động & Theo Lô (Đường B / M2)

Tài liệu này hướng dẫn các luồng làm việc bán tự động và lai ghép (hybrid), nơi bảng luật xác định dẫn đường cho việc phân bổ tác vụ, điều phối chạy song song theo lô (fan-out) và chuỗi phụ thuộc nhiều giai đoạn (DAG) với rào cản đồng bộ nghiêm ngặt và kiểm soát ngân sách chặt chẽ.

---

## Recipe R03: Phân Tán Song Song Cho Lô Tác Vụ Độc Lập

### 1. Khi Nào Dùng
- Bạn có nhiều file hoặc thành phần không chồng chéo cần phân tích, viết tài liệu hoặc tạo test cùng lúc.
- Các tác vụ con không chia sẻ trạng thái và có thể chạy song song mà không gây xung đột (race condition).
- **Anti-pattern**: Khởi tạo worker song song không giới hạn (ví dụ: hơn 10 agent đồng thời), dẫn đến chạm trần rate limit, vượt ngân sách hoặc làm tràn ngập ngữ cảnh tổng hợp của bộ điều phối.

### 2. Điều Kiện Tiên Quyết
- Host hoặc orchestrator hỗ trợ subagent bất đồng bộ hoặc chạy nền (khuyến nghị `max_parallel_workers=2` cho giai đoạn thử nghiệm).
- Đã tạm giữ trước ngân sách trong sổ cái tập trung cho từng lượt thực thi của worker.
- Có bản `TaskSpec` rõ ràng cho từng mục trong lô với phạm vi file tách biệt.

### 3. Đầu Vào và Đầu Ra
- **Đầu vào**: Danh sách các file mục tiêu độc lập (ví dụ: `[src/.../sqlite_store.py, src/.../runner.py]`).
- **Đầu ra**: Tập hợp các bản ghi `WorkerResult` được sắp xếp chính xác theo `task_id` sau khi hoàn tất.

### 4. Các Bước Thực Hiện
1. **Đánh giá luật**: Kiểm tra bảng quy tắc; xác nhận tất cả tác vụ thuộc nhóm `extract_evidence` hoặc `summarize_source` với quyền sở hữu file rõ ràng.
2. **Tạm giữ ngân sách**: Tạm giữ `estimated_cost * 1.2` cho mỗi worker trong sổ cái.
3. **Phân tán có giới hạn**: Điều phối tối đa `max_parallel_workers` cùng lúc, sử dụng các gói ngữ cảnh cách ly.
4. **Rào cản đồng bộ (Join Barrier)**: Chờ tất cả tác vụ đã phân công hoàn tất. Nếu một worker thất bại hoặc timeout, ghi nhận `status="failed"` hoặc `status="partial"` mà không làm mất kết quả của các worker khác.
5. **Khử trùng lặp & Lắp ráp**: Sắp xếp kết quả xác định theo `task_id` và gửi bản tóm tắt thu gọn cho bộ điều phối.

### 5. Trace Thực Thi Cụ Thể (Gắn Nhãn Minh Họa)

```text
[ORCHESTRATOR]: Bắt đầu phân tích lô cho 2 file: sqlite_store.py, runner.py.
[SỔ CÁI NGÂN SÁCH]: Tạm giữ $0.0050 mỗi worker. Tổng tạm giữ: $0.0100. Trạng thái: OK.
[ĐIỀU PHỐI]:
  - Worker 1 -> TaskSpec(task_id="batch_01", file="sqlite_store.py", model="MODEL_ECONOMY")
  - Worker 2 -> TaskSpec(task_id="batch_02", file="runner.py", model="MODEL_ECONOMY")
[SỰ KIỆN]: Worker 1 hoàn thành sau 2.1s (Trạng thái: completed, Tokens: 1.120)
[SỰ KIỆN]: Worker 2 hoàn thành sau 2.8s (Trạng thái: completed, Tokens: 1.340)
[RÀO CẢN JOIN]: Đã nhận đủ cả 2 task_id: ["batch_01", "batch_02"].
[KIỂM CHỨNG]: Kiểm tra schema cơ học và mã băm đều đạt cho cả hai kết quả.
[QUYẾT TOÁN]: Chi phí thực tế quyết toán trong sổ cái: $0.00038. Phần dư tạm giữ được giải phóng.
[BỘ ĐIỀU PHỐI]: Nhận kết quả đã ghép nối; tổng hợp phân tích liên file.
```

### 6. Cách Kiểm Tra Kết Quả
- Xác nhận rào cản join nhận được kết quả khớp chính xác với tập hợp các `task_id` đã giao.
- Xác minh số lượng worker chạy đồng thời không bao giờ vượt quá `max_parallel_workers=2`.
- Kiểm tra đối soát sổ cái: số dư tạm giữ đang hoạt động trở về 0 sau khi quyết toán.

### 7. Chi Phí và Rủi Ro
- **Lợi thế độ trễ**: Giảm ~40% thời gian thực tế so với thực thi tuần tự.
- **Overhead token**: Việc theo dõi điều phối song song tốn một lượng nhỏ chi phí sổ cái, nhưng việc cách ly ngữ cảnh ngăn chặn việc phình to lịch sử bậc hai.

---

## Recipe R04: Thực Thi Chuỗi Tác Vụ Có Phụ Thuộc (DAG)

### 1. Khi Nào Dùng
- Tác vụ con B phụ thuộc chặt chẽ vào đầu ra hoặc artifact đã được chấp nhận từ Tác vụ con A (ví dụ: tạo hợp đồng giao diện trước, sau đó mới viết unit test).
- **Anti-pattern**: Bỏ qua các ràng buộc phụ thuộc và chạy tác vụ con phụ thuộc sớm trên dữ liệu chưa kiểm chứng hoặc đã lỗi thời.

### 2. Điều Kiện Tiên Quyết
- Bộ điều khiển đồ thị (Graph controller) hoặc orchestrator có khả năng theo dõi các trạng thái chuyển tiếp (`pending`, `ready`, `running`, `accepted`, `failed`, `blocked`).
- Kiểm tra đồ thị không có chu trình (Acyclic) trước khi lập lịch.

### 3. Đầu Vào và Đầu Ra
- **Đầu vào**: Đặc tả phụ thuộc: `Tác vụ A (gốc)` -> `Tác vụ B (phụ thuộc vào A)`.
- **Đầu ra**: Kết quả ở trạng thái kết thúc (terminal) được chấp nhận cho cả hai tác vụ, hoặc dừng sớm với lý do bị chặn rõ ràng nếu Tác vụ A thất bại.

### 4. Các Bước Thực Hiện
1. **Kiểm tra DAG trước**: Xác minh đồ thị phụ thuộc không có vòng lặp (cycle), không trùng ID và không thiếu ID phụ thuộc.
2. **Thực thi điều kiện tiên quyết (Tác vụ A)**: Đánh dấu Tác vụ A là `ready` và giao cho worker/tool. Tác vụ B giữ ở trạng thái `pending`.
3. **Kiểm chứng Tác vụ A**: Tác vụ A hoàn thành. Bộ kiểm chứng đánh giá các tiêu chí nghiệm thu:
   - *Nếu Bị từ chối / Thất bại*: Đánh dấu Tác vụ A là `failed`. Chuyển ngay Tác vụ B sang trạng thái `blocked` (kết thúc). Hủy các lời gọi tiếp theo để bảo toàn ngân sách.
   - *Nếu Đạt kiểm chứng*: Đánh dấu Tác vụ A là `accepted`. Cấp handle của artifact từ Tác vụ A làm ngữ cảnh cho Tác vụ B.
4. **Chuyển tiếp & Điều phối Tác vụ B**: Đánh dấu Tác vụ B là `ready` và điều phối kèm tham chiếu bằng chứng đã xác minh của Tác vụ A.
5. **Join kết thúc**: Khi tất cả tác vụ đạt trạng thái kết thúc, thông báo cho bộ điều phối tổng hợp câu trả lời cuối cùng.

### 5. Trace Thực Thi Cụ Thể (Gắn Nhãn Minh Họa)

```text
[BỘ LẬP LỊCH DAG]: Đã đăng ký DAG:
  - Tác vụ A: "Trích xuất chữ ký API công khai từ server.py" (phụ thuộc: [])
  - Tác vụ B: "Soạn test case khớp với chữ ký API" (phụ thuộc: ["Tác vụ A"])
[KIỂM TRA CHU TRÌNH]: Đồ thị không có chu trình. Không phát hiện vòng lặp nào.
[BƯỚC 1]: Giao Tác vụ A cho MODEL_ECONOMY. Tác vụ B ở trạng thái PENDING.
[BƯỚC 2]: Tác vụ A trả về WorkerResult với 9 chữ ký và mã băm dòng đã xác thực.
[BƯỚC 3]: Bộ kiểm chứng chấp nhận Tác vụ A -> Trạng thái: ACCEPTED.
[BƯỚC 4]: Thỏa mãn phụ thuộc cho Tác vụ B. Chuyển Tác vụ B sang READY.
[BƯỚC 5]: Giao Tác vụ B với ngữ cảnh: ArtifactRef(Tác vụ A, revision=1).
[BƯỚC 6]: Tác vụ B trả về bộ test case -> Trạng thái: ACCEPTED.
[TỔNG HỢP]: Bộ điều phối xem xét bộ test đã chấp nhận và đưa ra câu trả lời cuối cùng.
```

### 6. Cách Kiểm Tra Kết Quả
- Kiểm tra lịch sử trạng thái: Tác vụ B không bao giờ được phân công trước khi Tác vụ A đạt trạng thái `accepted`.
- Thử nghiệm kiểm tra âm tính: Nếu cố ý làm Tác vụ A thất bại, Tác vụ B phải chuyển sang `blocked` mà không tiêu tốn token gọi LLM.

### 7. Chi Phí và Rủi Ro
- **Bảo vệ ngân sách**: Ngăn chặn lãng phí token cho các tác vụ con phía sau khi các bước tiên quyết bị hỏng.
- **Chi phí phát sinh**: Chi phí theo dõi trạng thái đồ thị là tối thiểu (~0.01 giây độ trễ scheduler).
