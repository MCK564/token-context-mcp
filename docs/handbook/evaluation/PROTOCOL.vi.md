# Giao Thức Đánh Giá Định Tuyến Multi-Agent & Các Cổng Chất Lượng

Tài liệu này xác lập phương pháp đánh giá khoa học, công thức hạch toán chi phí toàn diện, các cấu hình đối chuẩn (baseline) bắt buộc và các cổng chất lượng triển khai đã thỏa thuận trước cho kiến trúc điều phối mô hình mạnh và mô hình tiết kiệm.

---

## 1. Công Thức Hạch Toán Chi Phí Toàn Diện Bắt Buộc

Để ngăn chặn các tuyên bố sai lệch về việc tiết kiệm token, mọi lượt chạy đánh giá đều phải tính toán tất cả các lời gọi suy luận tính phí, embedding, bộ kiểm chứng và các lần thử lại trên toàn bộ các attempt:

$$C_{run} = C_{parent\_plan} + C_{router} + \sum C_{all\_worker\_attempts} + C_{tools} + C_{verify} + C_{parent\_synthesis}$$

### Quy Tắc Hạch Toán
1. **Các Nhóm Chi Phí Loại Trừ Nhau**:
   - $\sum C_{all\_worker\_attempts}$ bao gồm tất cả các lượt phân công ban đầu cho worker, các lượt sửa chữa có giới hạn và các lần nâng cấp lên worker mạnh.
   - Bất kỳ phần việc nâng cấp nào do chính bộ điều phối trực tiếp xử lý đều được tính trong $C_{parent\_synthesis}$ và **tuyệt đối không** được cộng hai lần.
2. **Căn Cứ Theo Request ID Của Nhà Cung Cấp**:
   - Sổ cái chính thức ghi nhận mỗi mã `provider_request_id` duy nhất đúng một lần.
   - Các khoản tạm giữ đang hoạt động chỉ là lệnh giữ chỗ tạm thời; chỉ các số liệu đã quyết toán mới đại diện cho chi phí thực tế.
3. **Phải Tính Cả Các Lần Thử Nghiệm Thất Bại**:
   - Token tiêu tốn bởi các worker bị timeout, bị từ chối kết quả hoặc bị crash vẫn nằm vĩnh viễn trong mẫu số tổng chi phí.

---

## 2. Phân Tích Điểm Hòa Vốn Minh Họa

Kiến trúc phân quyền worker chỉ mang lại hiệu quả kinh tế thực sự khi tỷ lệ thành công của worker ở mức cao và chi phí kiểm chứng ở mức thấp.

```text
[VÍ DỤ MINH HỌA (KHÔNG PHẢI SỐ LIỆU ĐO LƯỜNG THỰC TẾ)]:
  - Baseline (Chỉ dùng một Agent mạnh): 100 đơn vị chi phí
  - Điều Phối Multi-Agent (Kế hoạch cha + Router + Worker tiết kiệm + Kiểm chứng + Tổng hợp): 70 đơn vị chi phí
  - Chi Phí Phạt Do Nâng Cấp (Khi worker thất bại và phải chạy lại trên model mạnh): 60 đơn vị chi phí
  - Xác Suất Worker Thất Bại: p

Chi Phí Kỳ Vọng Của Multi-Agent = 70 + 60 * p

Điều Kiện Hòa Vốn:
  70 + 60 * p < 100
  60 * p < 30
  p < 0.50
```

> [!IMPORTANT]
> Nếu một mô hình tiết kiệm thất bại hơn 50% số lần trên một nhóm tác vụ cụ thể ($p \ge 0.50$), việc giao việc cho nó sẽ làm tăng tổng chi phí và độ trễ so với việc chạy trực tiếp trên mô hình mạnh ngay từ đầu.

---

## 3. Các Cấu Hình Đối Chuẩn Bắt Buộc

Mọi đợt đánh giá đều phải so sánh đối chuẩn với 8 cấu hình tiêu chuẩn dưới đây trên cùng một snapshot repo và cùng một bộ prompt thử nghiệm:

| Mã Baseline | Tên Baseline | Kiến Trúc | Mục Đích Đối Chuẩn |
| :--- | :--- | :--- | :--- |
| **B01** | **Chỉ Dùng Model Mạnh** | Một agent duy nhất dùng `MODEL_STRONG` | Đối chuẩn chính: chất lượng cao nhất, chi phí gốc. |
| **B02** | **Chỉ Dùng Model Tiết Kiệm** | Một agent duy nhất dùng `MODEL_ECONOMY` | Đo trần năng lực: chi phí token thấp nhất, giới hạn chất lượng. |
| **B03** | **Phân Quyền Thủ Công Cố Định** | Cha giao việc cố định không qua router | Đo chi phí điều phối mà không có logic routing. |
| **B04** | **Định Tuyến Dựa Trên Luật** | Bảng quyết định if-else xác định | Xác lập baseline định tuyến không tốn phí tính toán. |
| **B05** | **Định Tuyến Bằng Embedding** | So khớp tương đồng cosine với mẫu chuẩn | Đánh giá độ chính xác phân loại vector và độ trễ. |
| **B06** | **Router Học Máy (RouteLLM)** | Bộ phân loại huấn luyện theo preference | Đánh giá mô hình dự đoán tier so với bảng luật. |
| **B07** | **Thử Tiết Kiệm Trước (Cascade)** | Luôn thử economy trước, hỏng thì nâng cấp | Đánh giá hiệu quả của chiến lược thực thi đầu cơ. |
| **B08** | **Kiến Trúc Lai Ghép Đề Xuất** | Luật $\rightarrow$ Semantic $\rightarrow$ Cổng Năng Lực $\rightarrow$ Nâng Cấp | Đánh giá thiết kế hoàn chỉnh của cẩm nang. |

---

## 4. Các Chỉ Số Hiệu Năng Cốt Lõi

### Chỉ Số Chính
1. **Tỷ Lệ Hoàn Thành ($R_{comp}$)**:
   $$R_{comp} = \frac{N_{accepted\_tasks}}{N_{total\_assigned\_tasks}}$$
2. **Chi Phí Phân Bổ Cho Mỗi Tác Vụ Đạt Kiểm Chứng ($C_{accepted}$)**:
   $$C_{accepted} = \frac{\sum C_{all\_attempts}}{N_{accepted\_tasks}}$$
   *(Nếu $N_{accepted\_tasks} = 0$, $C_{accepted}$ là không xác định).*
3. **Biểu Đồ Độ Trễ**: Độ trễ thực tế ở phân vị $p50$ và $p95$ tính từ lúc người dùng gửi yêu cầu đến khi có câu trả lời tổng hợp cuối cùng.

### Chỉ Số Chẩn Đoán Định Tuyến & Kiểm Chứng
- **Tỷ Lệ Từ Chối Định Tuyến (Abstention Rate)**: Tỷ lệ tác vụ con mà bộ định tuyến ngữ nghĩa trả về `unknown`.
- **Giao Nhầm Cho Worker Tiết Kiệm (Wrong-Economy Assignment)**: Tỷ lệ tác vụ con giao cho `MODEL_ECONOMY` nhưng sau đó buộc phải nâng cấp lên model mạnh.
- **Chấp Nhận Sai Của Bộ Kiểm Chứng ($FAR$)**: Tỷ lệ tác vụ con mà bộ kiểm chứng cơ học hoặc LLM chấp nhận một kết quả sai lệch khách quan.

---

## 5. Các Cổng Chất Lượng Triển Khai Xác Lập Trước

Trước khi bất kỳ cấu hình định tuyến multi-agent nào được phê duyệt cho môi trường production, nó phải thỏa mãn cả 5 cổng chất lượng đã cam kết trước:

| Mã Cổng | Chỉ Số Đánh Giá | Ngưỡng Yêu Cầu | Hậu Quả Khi Không Đạt |
| :--- | :--- | :--- | :--- |
| **GATE-01** | Tuân Thủ Hợp Đồng Dữ Liệu | **100%** schema hợp lệ | Chặn rollout; sửa bộ tuần tự hóa JSON schema. |
| **GATE-02** | Hồi Quy Trên Golden Pilot | **0 hồi quy mới** so với B01 | Chặn rollout; phục hồi cách phân rã tác vụ cũ. |
| **GATE-03** | Không Suy Giảm Chất Lượng | Trong phạm vi **2 điểm %** của B01 | Từ chối việc giao quyền cho tier mô hình đó. |
| **GATE-04** | Hiệu Quả Kinh Tế Thực Tế | Giảm ít nhất **15%** $C_{accepted}$ | Chuyển các tác vụ mơ hồ về model cha. |
| **GATE-05** | Giới Hạn Tăng Độ Trễ | Độ trễ $p95$ tăng không quá **10%** | Giới hạn `max_parallel_workers` hoặc tối ưu prompt. |

> [!CAUTION]
> Cả hai bộ dữ liệu kiểm thử tiếng Anh và tiếng Việt phải vượt qua các cổng này một cách **độc lập**. Thành công trên các bài kiểm thử tiếng Anh không được dùng để che lấp sự suy giảm chất lượng trên tiếng Việt.
