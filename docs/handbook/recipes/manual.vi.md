# Các Recipe Điều Phối Thủ Công (Đường A / M1)

Tài liệu này cung cấp các quy trình vận hành đã được kiểm chứng cho phương thức điều phối thủ công trong cùng một prompt, nơi model điều phối mạnh giao các tác vụ con có phạm vi hẹp cho các worker tiết kiệm nhưng vẫn nắm quyền kiểm chứng và tổng hợp câu trả lời cuối cùng.

---

## Recipe R01: Kiểm Toán Kho Mã Nguồn Trong Một Prompt

### 1. Khi Nào Dùng
- Bạn muốn thực hiện kiểm toán đa khía cạnh một codebase (ví dụ: đánh giá kiến trúc, bảo mật hoặc hiệu quả token) trong một phiên làm việc tương tác.
- Môi trường host hỗ trợ tính năng subagent với các alias mô hình phân theo vai trò.
- **Anti-pattern**: Khởi tạo worker không giới hạn, tự do duyệt các file tùy ý mà không có ràng buộc phạm vi hoặc hợp đồng kết quả rõ ràng.

### 2. Điều Kiện Tiên Quyết
- Môi trường host đã được xác minh hỗ trợ subagent (ví dụ: Codex CLI `0.153.4` hoặc host tương thích).
- Các alias mô hình đã được ánh xạ: `MODEL_STRONG` (ví dụ: Claude 3.7 Sonnet / GPT-4o) và `MODEL_ECONOMY` (ví dụ: Gemini 1.5 Flash / GPT-4o-mini).
- Công cụ đọc code Token-Context MCP hoặc công cụ tương đương đã được kết nối ở chế độ chỉ đọc.

### 3. Đầu Vào và Đầu Ra
- **Đầu vào**: Mục tiêu người dùng nêu rõ tiêu chí kiểm toán kho mã nguồn và các thư mục đích.
- **Đầu ra**:
  - Hai bản ghi `WorkerResult` có giới hạn, chứa đoạn mã nguồn và mã băm trích xuất được.
  - Một báo cáo tổng hợp thống nhất do bộ điều phối lập, nêu bật các phát hiện đã xác minh và các điểm chưa giải quyết.

### 4. Các Bước Thực Hiện
1. **Khởi tạo bộ điều phối**: Model cha mạnh tiếp nhận yêu cầu, lập kế hoạch kiểm toán tổng thể và kiểm tra ngân sách khả dụng.
2. **Phân rã & Đóng khung ranh giới**: Bộ điều phối tách tối đa 2 tác vụ con độc lập (ví dụ: Worker A kiểm toán cơ chế đóng gói token; Worker B kiểm toán tính tươi mới của index).
3. **Phân công với bản tóm tắt thu gọn**: Bộ điều phối gọi subagent với ngữ cảnh tối thiểu, nghiêm cấm sinh subagent đệ quy.
4. **Thực thi & Đợi kết quả**: Các worker chạy song song (hoặc tuần tự nếu host yêu cầu gọi đồng bộ).
5. **Kiểm chứng cơ học**: Bộ điều phối kiểm tra đường dẫn file, dòng bắt đầu-kết thúc và mã băm SHA-256 đối chiếu với file cục bộ.
6. **Tiếp tục & Tổng hợp**: Bộ điều phối tự xử lý các tác động liên module và tổng hợp câu trả lời cuối cùng.

### 5. Ví Dụ Prompt Cụ Thể (Gắn Nhãn Minh Họa)

```text
Giữ vai trò điều phối chính bằng MODEL_STRONG.
Mục tiêu: Kiểm toán hiệu quả token và tính tươi mới của index trong repo token-context-mcp.

Quy tắc vận hành:
1. Nếu có việc độc lập đáng giao, dùng tối đa 2 subagent chạy MODEL_ECONOMY.
2. Subagent 1 (Phạm vi: src/token_context_mcp/retrieve/token_budget.py):
   - Định vị cách pack_by_budget xử lý các mục vượt quá ngân sách.
   - Trả về: đường dẫn file chính xác, khoảng dòng, mã băm SHA-256, và việc mục đó bị bỏ qua hay cắt nhỏ.
3. Subagent 2 (Phạm vi: src/token_context_mcp/index/freshness.py):
   - Định vị cách kiểm tra mtime và kích thước file.
   - Trả về: đường dẫn file chính xác, khoảng dòng, mã băm SHA-256, và việc file mới chưa theo dõi có được phát hiện hay không.
4. Hợp đồng đầu ra cho worker: Kết quả ngắn gọn, bằng chứng xác thực, các kiểm tra đã thực hiện, và các điểm chưa chắc chắn.
5. Worker KHÔNG được tạo thêm subagent con và KHÔNG được thực hiện thao tác ghi file.
6. Đợi cả hai kết quả, tự kiểm tra đối chiếu bằng chứng với mã nguồn repo, và tự tổng hợp báo cáo cuối cùng.
```

### 6. Cách Kiểm Tra Kết Quả
- Kiểm tra kết quả worker có tuân thủ cấu trúc `WorkerResult` hay không.
- Xác nhận các trích dẫn khớp với đường dẫn thực tế trong repo:
  - `src/token_context_mcp/retrieve/token_budget.py#L18-42`
  - `src/token_context_mcp/index/freshness.py#L25-60`
- Xác nhận không có worker nào cố gắng ghi file hoặc tạo thêm agent con.

### 7. Lỗi Thường Gặp & Cách Khắc Phục
- **Lỗi**: Host sao chép toàn bộ lịch sử hội thoại cho subagent, làm tăng vọt chi phí token đầu vào.
  - *Khắc phục*: Giới hạn rõ ngữ cảnh trong lời gọi; tránh fork full-history nếu host hỗ trợ tạo subagent độc lập.
- **Lỗi**: Worker trả về nhận định mơ hồ mà không có số dòng hoặc mã băm.
  - *Khắc phục*: Bộ điều phối từ chối kết quả; nếu còn ngân sách sửa chữa, yêu cầu trích xuất lại một lần có kèm số dòng.

### 8. Chi Phí và Rủi Ro
- **Ước tính token**: Tóm tắt ban đầu của supervisor (~1.200 tokens) + 2 lời gọi Worker (~1.500 tokens mỗi worker) + Tổng hợp cuối của supervisor (~2.000 tokens) = ~6.200 tokens tổng cộng.
- **So sánh chi phí**: Dùng `MODEL_ECONOMY` cho worker giúp giảm 80–90% chi phí token phần trích xuất so với việc chạy toàn bộ vòng lặp trên `MODEL_STRONG`.

### 9. Nguồn và Phiên Bản
- Căn cứ theo `DOC-CODEX-SUBAGENTS` và `LIT-ANTHROPIC-AGENTS` (Mô hình Orchestrator-Workers).

---

## Recipe R02: Tác Vụ Quá Nhỏ / Nhánh Không Phân Quyền

### 1. Khi Nào Dùng
- Tác vụ con có thể giải quyết bằng một lời gọi tool xác định đơn lẻ (ví dụ: đếm dòng, tìm symbol, lọc JSON) hoặc chỉ yêu cầu dưới 200 token đầu ra.
- **Anti-pattern**: Khởi tạo một worker LLM tiết kiệm chỉ để lọc chuỗi, so khớp regex hoặc đọc file cơ bản.

### 2. Điều Kiện Tiên Quyết
- Truy cập trực tiếp vào các tool xác định (ví dụ: `grep_search`, `find_by_name`, `view_file` hoặc chạy script).

### 3. Đầu Vào và Đầu Ra
- **Đầu vào**: Truy vấn hẹp (ví dụ: "Tìm tất cả các tham chiếu tới `ServerConfig`").
- **Đầu ra**: Danh sách cấu trúc các kết quả khớp trả trực tiếp cho bộ điều phối mà không khởi tạo subagent.

### 4. Các Bước Thực Hiện
1. **Đánh giá cổng năng lực**: Bộ điều phối kiểm tra xem tác vụ có thuật toán xác định rõ ràng hay không.
2. **Quyết định rẽ nhánh ngắn**: Nếu có, bỏ qua việc tạo subagent (`delegate=false`).
3. **Thực thi tool trực tiếp**: Chạy trực tiếp công cụ cục bộ.
4. **Tiếp nhận tức thì**: Bộ điều phối xử lý kết quả thô của tool ngay trong ngữ cảnh làm việc của mình.

### 5. Trace Thực Thi Cụ Thể (Gắn Nhãn Minh Họa)

```text
[BỘ ĐIỀU PHỐI]: Nhận tác vụ con: "Liệt kê tất cả các file Python định nghĩa MCPServer trong src/"
[QUYẾT ĐỊNH]: Tác vụ là tìm kiếm chuỗi xác định. Khởi tạo LLM worker sẽ tốn ~1.500 token overhead và mất 3 giây độ trễ. Kích hoạt nhánh không ủy quyền.
[LỜI GỌI]: grep_search(Query="class MCPServer", SearchPath="src/token_context_mcp/server.py")
[KẾT QUẢ]: Tìm thấy 1 kết quả tại src/token_context_mcp/server.py:24
[BỘ ĐIỀU PHỐI]: Kiểm chứng đạt ngay lập tức. Tiếp tục tổng hợp mà không cần điều phối worker.
```

### 6. Cách Kiểm Tra Kết Quả
- Đảm bảo số lượng subagent khởi tạo là 0 (`worker_invocations == 0`).
- Kiểm tra tool trả về dữ liệu hợp lệ, không rỗng và khớp chính xác truy vấn.

### 7. Chi Phí và Rủi Ro
- **Mức tiêu thụ token**: Không phát sinh token cho worker. Tiết kiệm từ ~1.000 đến ~3.000 token điều phối và đóng khung agent cho mỗi tác vụ đơn giản.
