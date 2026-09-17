# Các Recipe Định Tuyến Tự Động & Ngữ Nghĩa (Đường C / M3)

Tài liệu này cung cấp các quy trình vận hành cho việc định tuyến tác vụ tự động bằng embedding ngữ nghĩa, hiệu chuẩn ngưỡng, cơ chế từ chối định tuyến (abstention) và nâng cấp bậc mô hình xác định khi worker thất bại, dưới sự kiểm soát chặt chẽ về chất lượng và ngân sách.

---

## Recipe R05: Xử Lý Khi Định Tuyến Ngữ Nghĩa Mơ Hồ (Abstention)

### 1. Khi Nào Dùng
- Bạn triển khai một bộ định tuyến embedding dense (ví dụ: Aurelio Semantic Router) để phân loại động các tác vụ con vào các nhóm tác vụ.
- Tác vụ con cho độ tương đồng cosine thấp hơn ngưỡng đã hiệu chuẩn, hoặc khoảng cách (margin) giữa 2 route ứng viên hàng đầu quá hẹp (ví dụ: margin $< 0.08$).
- **Anti-pattern**: Ép buộc một phân loại thiếu tự tin vào nhóm worker tiết kiệm chỉ để giảm giá token trên danh nghĩa, gây nguy cơ sai sót thực thi hoặc phát sinh ảo giác tốn kém ở các bước sau.

### 2. Điều Kiện Tiên Quyết
- Bộ định tuyến ngữ nghĩa đã được cấu hình các ví dụ mẫu (exemplars) chuẩn bằng cả tiếng Anh và tiếng Việt.
- Đã tính toán và hiệu chuẩn thực nghiệm ngưỡng cosine và yêu cầu margin cho từng route.
- Đã định nghĩa chính sách dự phòng khi `RouteDecision.selected_route_family == "unknown"`.

### 3. Đầu Vào và Đầu Ra
- **Đầu vào**: Một truy vấn tác vụ con ở ranh giới mơ hồ (ví dụ: *"Đánh giá module xác thực này và gợi ý cải tiến bảo mật hoặc tái thiết kế cấu trúc token"*).
- **Đầu ra**: Bản ghi `RouteDecision` với `selected_route_family="unknown"`, kích hoạt cơ chế từ chối định tuyến an toàn và chuyển tác vụ về cho model mạnh xử lý.

### 4. Các Bước Thực Hiện
1. **Trích xuất embedding**: Tạo vector nhúng cho mục tiêu của tác vụ con.
2. **Tính toán độ tương đồng và Margin**:
   - Route top-1: `extract_evidence` (similarity: 0.76; ngưỡng yêu cầu: 0.82) -> Dưới ngưỡng.
   - Route top-2: `cross_file_design` (similarity: 0.74; ngưỡng yêu cầu: 0.85) -> Dưới ngưỡng.
   - Khoảng cách Top-1 và Top-2: $0.76 - 0.74 = 0.02$ (margin $< 0.08$).
3. **Kích hoạt cổng từ chối (Abstention Gate)**: Vì cả ngưỡng tương đồng lẫn biên độ phân tách đều không thỏa mãn, bộ định tuyến chuyển sang trạng thái **Abstention**.
4. **Hành động dự phòng**: Đánh dấu route là `unknown`. Nâng cấp tác vụ con lên bộ điều phối mạnh (`MODEL_STRONG`) thay vì đoán mò một tier tiết kiệm.
5. **Ghi nhật ký đo lường**: Ghi lại điểm similarity, margin và sự kiện từ chối để phục vụ việc tái hiệu chuẩn ngưỡng sau này.

### 5. Trace Thực Thi Cụ Thể (Gắn Nhãn Minh Họa)

```text
[BỘ ĐỊNH TUYẾN NGỮ NGHĨA]: Đánh giá tác vụ con: "Audit ranh giới bảo mật và đề xuất thiết kế lại token"
[TRÍCH XUẤT EMBEDDING]: Đã tạo vector 1536 chiều qua text-embedding-3-small.
[ĐIỂM COSINE]:
  - candidate_1: 'extract_evidence' -> similarity = 0.762 (yêu cầu >= 0.820) [KHÔNG ĐẠT]
  - candidate_2: 'cross_file_design' -> similarity = 0.741 (yêu cầu >= 0.850) [KHÔNG ĐẠT]
  - margin_tính_toán: 0.021 (yêu cầu >= 0.080) [KHÔNG ĐẠT]
[QUYẾT ĐỊNH ĐỊNH TUYẾN]: Phân loại mơ hồ. Kích hoạt TỪ CHỐI ĐỊNH TUYẾN (ABSTENTION).
[BẢN GHI QUYẾT ĐỊNH]:
  {
    "selected_route_family": "unknown",
    "rule_match_reason": "ambiguous_semantic_boundary_margin_too_low",
    "selected_model_alias": "MODEL_STRONG",
    "action": "retain_in_supervisor"
  }
[BỘ ĐIỀU PHỐI]: Xác nhận sự kiện từ chối. Xử lý tác vụ trực tiếp mà không phân bổ cho worker tiết kiệm.
```

### 6. Cách Kiểm Tra Kết Quả
- Xác minh `selected_route_family` được gán chính xác là `"unknown"`.
- Đảm bảo không có lời gọi subagent nào được phát tới `MODEL_ECONOMY`.
- Xác nhận bộ định tuyến không coi điểm tương đồng cosine là xác suất thành công chưa được hiệu chuẩn.

### 7. Chi Phí và Rủi Ro
- **Đánh đổi**: Chấp nhận chi phí token cao hơn của `MODEL_STRONG` cho tác vụ chưa rõ ràng.
- **Lợi ích**: Tránh lỗi nghiêm trọng khi giao tác vụ tái cấu trúc đa module phức tạp cho worker giá rẻ không đủ năng lực giải quyết.

---

## Recipe R06: Xử Lý Khi Worker Thất Bại & Nâng Cấp Bậc Mô Hình (Escalation)

### 1. Khi Nào Dùng
- Một worker tiết kiệm thực thi tác vụ con nhưng trả về schema không hợp lệ, bịa đặt số dòng, sai mã băm SHA-256 hoặc không vượt qua kiểm chứng cơ học.
- **Anti-pattern**: Rơi vào vòng lặp sửa chữa (repair loop) không giới hạn giữa worker và supervisor, làm nhân bội số token vượt xa chi phí gọi thẳng model mạnh ngay từ đầu.

### 2. Điều Kiện Tiên Quyết
- Bộ kiểm chứng cơ học đánh giá đầu ra của worker đối chiếu với file thực tế trên đĩa hoặc kết quả test.
- Quy tắc chính sách áp đặt cứng: `max_repair_attempts=1` và `max_escalation_depth=1`.
- Sổ cái ngân sách ghi nhận đầy đủ chi phí của các lượt thử nghiệm thất bại.

### 3. Đầu Vào và Đầu Ra
- **Đầu vào**: Bản ghi `WorkerResult` có đoạn mã trích dẫn không khớp với nội dung repo thực tế.
- **Đầu ra**: Tối đa một lượt sửa chữa có giới hạn; nếu vẫn thất bại, nâng cấp lên `MODEL_STRONG` kèm đầy đủ nhật ký kiểm toán.

### 4. Các Bước Thực Hiện
1. **Worker nộp kết quả**: Worker hoàn thành tác vụ con và gửi `WorkerResult(attempt_id=1)`.
2. **Kiểm chứng cơ học**: Bộ kiểm chứng so khớp mã băm nội dung với đĩa.
   - *Kết quả*: Đoạn dòng `50-80` trong `server.py` không chứa hàm được trích dẫn. Kết quả kiểm chứng **BỊ TỪ CHỐI (REJECTED)**.
3. **Đánh giá lượt sửa chữa**:
   - Kiểm tra số lượt: `attempts = 1` $\le$ `max_repair_attempts (1)`.
   - Kiểm tra ngân sách: sổ cái còn đủ hạn mức tạm giữ cho một lần sửa.
   - Gửi prompt yêu cầu sửa chữa cho worker, chỉ rõ điểm sai lệch.
4. **Thất bại lần hai / Kích hoạt Escalation**:
   - Worker gửi `WorkerResult(attempt_id=2)` nhưng vẫn báo sai số dòng.
   - Bộ kiểm chứng đánh dấu **REJECTED (hết lượt sửa)**.
5. **Nâng cấp bậc mô hình (Quality Escalation)**:
   - Chuyển trạng thái tác vụ sang **Đã nâng cấp lên Model Mạnh (Escalated to Strong)**.
   - Điều phối tác vụ cho `MODEL_STRONG` kèm ngữ cảnh đã thất bại trước đó.
   - Ghi nhận cả 2 lượt worker thất bại và lượt gọi model mạnh thành công vào sổ cái ngân sách.

### 5. Trace Thực Thi Cụ Thể (Gắn Nhãn Minh Họa)

```text
[WORKER]: Đã nộp attempt 1 cho tác vụ 'verify_sqlite_schema'.
[BỘ KIỂM CHỨNG]: Kiểm tra sha256 của src/token_context_mcp/index/sqlite_store.py:30-45.
[LỖI KIỂM CHỨNG]: Nội dung trích dẫn không khớp mã băm trên đĩa. Sai lệch tại dòng 34.
[TRẠNG THÁI]: REJECTED. Số lần sửa: 0/1. Kích hoạt sửa chữa có giới hạn.
[GỬI SỬA CHỮA]: "Đoạn trích 30-45 của bạn không khớp với file trên đĩa. Vui lòng đọc lại chính xác các dòng."
[WORKER]: Đã nộp attempt 2. Đoạn trích: 40-55.
[LỖI KIỂM CHỨNG]: Đoạn trích 40-55 vẫn thiếu định nghĩa schema mục tiêu.
[TRẠNG THÁI]: REJECTED. Đã hết lượt sửa chữa (2/2). Kích hoạt NÂNG CẤP CHẤT LƯỢNG (ESCALATION).
[SỔ CÁI NGÂN SÁCH]: Worker attempt 1 ($0.0002) + attempt 2 ($0.0002) được ghi là chi phí của attempt thất bại.
[ĐIỀU PHỐI ESCALATION]: Chuyển tác vụ 'verify_sqlite_schema' cho MODEL_STRONG.
[BỘ ĐIỀU PHỐI]: MODEL_STRONG xác định chính xác vị trí tại sqlite_store.py:98-142 với mã băm chuẩn xác.
[BỘ KIỂM CHỨNG]: Mã băm đã khớp -> Trạng thái: ACCEPTED.
```

### 6. Cách Kiểm Tra Kết Quả
- Xác nhận tổng số lượt sửa chữa cho tác vụ này chính xác là 1.
- Xác nhận cả 2 lần gọi worker (attempt 1 & 2) cùng lần gọi model mạnh đều được hạch toán riêng biệt trong sổ cái ngân sách.
- Xác minh chi phí cuối cùng của tác vụ phản ánh đúng công thức: $C_{task} = C_{worker\_att1} + C_{worker\_att2} + C_{strong}$.

### 7. Chi Phí và Rủi Ro
- **Quy tắc điểm hòa vốn**: Nếu worker tiết kiệm thất bại thường xuyên ($p > 0.3$), việc đi qua chu trình sửa chữa rồi mới nâng cấp sẽ tốn kém hơn gọi thẳng model mạnh ngay từ đầu. Hãy dựa vào nhật ký kiểm toán của recipe này để điều chỉnh lại luật định tuyến.
