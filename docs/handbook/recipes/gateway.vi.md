# Các Recipe LLM Gateway & Xử Lý Lỗi Tầng Truyền Tải (Đường D / Gateway)

Tài liệu này cung cấp các quy trình vận hành cho việc quản lý các sự cố truyền tải của nhà cung cấp mô hình, lỗi chạm trần tần suất HTTP 429 và cơ chế chuyển đổi dự phòng (failover) khi sử dụng reverse proxy tập trung hoặc bộ định tuyến thư viện trong tiến trình.

---

## Recipe R07: Xử Lý Lỗi 429/Timeout & Fallback Endpoint

### 1. Khi Nào Dùng
- Một nhà cung cấp API trả về mã lỗi HTTP 429 (Rate Limit Exceeded), HTTP 500/503 (Lỗi dịch vụ phía nhà cung cấp) hoặc bị timeout kết nối trong quá trình worker hoặc supervisor đang chạy.
- Bạn đã cấu hình một LLM gateway (ví dụ: LiteLLM Proxy) hoặc adapter SDK có danh sách endpoint dự phòng.
- **Anti-pattern**: Đánh đồng lỗi tầng truyền tải (429/timeout) với lỗi chất lượng của mô hình, hoặc để cả gateway lẫn vòng lặp ứng dụng tự retry độc lập mà không có hạn mức thời gian chung (deadline).

### 2. Điều Kiện Tiên Quyết
- Cấu hình gateway đã định nghĩa sẵn các deployment chính và phụ cho từng alias mô hình.
- Quy tắc chính sách bắt buộc:
  - **Một nơi duy nhất sở hữu retry tầng truyền tải (Single Transport Retry Owner)**: Chỉ có gateway hoặc adapter SDK được phép retry lỗi HTTP. Tầng orchestrator không được bọc thêm vòng lặp retry thứ hai.
  - **Thời hạn chung (Unified Deadline)**: Mọi lượt thử nghiệm retry đều phải chia sẻ chung giá trị `deadline_ms` ban đầu của tác vụ.
  - **Danh sách fallback được thẩm định trước**: Mọi model trong danh sách fallback phải vượt qua kiểm tra năng lực trước khi dispatch.

### 3. Đầu Vào và Đầu Ra
- **Đầu vào**: Lời gọi tới `MODEL_ECONOMY` (Deployment A) gặp lỗi HTTP 429.
- **Đầu ra**: Tự động chuyển đổi sang `MODEL_ECONOMY` (Deployment B) trong thời hạn cho phép, ghi nhận `requested_model`, `resolved_model` và `actual_model` vào bản ghi kiểm toán.

### 4. Các Bước Thực Hiện
1. **Phát lệnh ban đầu**: Ứng dụng yêu cầu `MODEL_ECONOMY` cho tác vụ `task_audit_auth_tokens_001`.
2. **Gặp lỗi truyền tải**: Deployment A phản hồi mã lỗi HTTP 429 (Quá tải tần suất).
3. **Xử lý bởi nơi sở hữu retry**:
   - Gateway kiểm tra chính sách: số lần retry 1 < `max_transport_retries (2)`.
   - Kiểm tra thời gian còn lại: đã trôi qua 1.200ms < `deadline_ms (30.000ms)`.
   - Áp dụng giãn cách lũy thừa (ví dụ: 500ms) hoặc chuyển ngay sang Deployment B trong danh sách cho phép.
4. **Chuyển đổi thành công**: Deployment B hoàn thành yêu cầu một cách bình thường.
5. **Ghi nhận kiểm toán**:
   - Ghi `requested_model="MODEL_ECONOMY"`.
   - Ghi `resolved_model="gemini-1.5-flash-002-primary"`.
   - Ghi `actual_model="gemini-1.5-flash-002-secondary"`.
   - Lý do: `transport_fallback_429`.
6. **Trả kết quả về ứng dụng**: Ứng dụng nhận kết quả bình thường mà không cần bộ điều phối phải can thiệp.

### 5. Cấu Hình & Trace Thực Thi Cụ Thể (Gắn Nhãn Minh Họa)

#### Cấu hình Gateway Dự Phòng Tối Thiểu (`litellm_config.yaml`)

```yaml
model_list:
  - model_name: MODEL_ECONOMY
    litellm_params:
      model: gemini/gemini-1.5-flash-002
      api_key: os.environ/GEMINI_API_KEY
    rpm: 1000
  - model_name: MODEL_ECONOMY
    litellm_params:
      model: openai/gpt-4o-mini
      api_key: os.environ/OPENAI_API_KEY
    rpm: 5000

router_settings:
  routing_strategy: usage-based-routing
  allowed_fails: 2
  cooldown_time: 30
  retry_after: 5
```

#### Trace Thực Thi (Gắn Nhãn Minh Họa)

```text
[GATEWAY DISPATCH]: Yêu cầu 'MODEL_ECONOMY' (Định tuyến tới gemini-1.5-flash-002).
[LỖI HTTP GATEWAY]: Endpoint chính trả về 429 Too Many Requests (Chạm giới hạn RPM).
[CHÍNH SÁCH GATEWAY]: Kích hoạt retry đơn lớp. Thời hạn tác vụ còn lại: 28.400ms.
[FALLBACK GATEWAY]: Chuyển sang model dự phòng trong allowlist: openai/gpt-4o-mini.
[THÀNH CÔNG GATEWAY]: Nhận phản hồi từ gpt-4o-mini sau 1.450ms.
[SỰ KIỆN KIỂM TOÁN TẠO RA]:
  {
    "event_id": "evt_transport_failover_091",
    "task_id": "task_audit_auth_tokens_001",
    "requested_model": "MODEL_ECONOMY",
    "resolved_model": "gemini-1.5-flash-002",
    "actual_model": "gpt-4o-mini",
    "reason": "transport_429_failover",
    "input_tokens": 1420,
    "output_tokens": 285,
    "monetary_cost_usd": 0.000384
  }
[ORCHESTRATOR]: Nhận kết quả hợp lệ. Luồng thực thi tiếp tục bình thường.
```

### 6. Cách Kiểm Tra Kết Quả
- Xác minh tầng orchestrator phía trên không chạy thêm một vòng lặp retry ngoài ý muốn.
- Xác nhận model và nhà cung cấp thực tế bị tính phí được báo cáo chính xác vào sổ cái.
- **Ràng buộc an toàn**: Đảm bảo bộ điều phối mạnh (`MODEL_STRONG`) **không bao giờ bị âm thầm hạ cấp** xuống model yếu hơn khi xảy ra fallback truyền tải.

### 7. Lỗi Thường Gặp & Cách Khắc Phục
- **Lỗi âm thầm hạ cấp model (Silent Model Downgrade)**: Gateway được cấu hình tự động nhảy từ Claude 3.7 Sonnet sang GPT-4o-mini khi gặp lỗi 429, phá hủy năng lực suy luận phức tạp.
  - *Khắc phục*: Khóa cứng danh sách fallback chỉ trong cùng phân khúc năng lực. Nếu không có model tương đương khả dụng, trả về lỗi truyền tải ngay lập tức thay vì làm hỏng việc tổng hợp của supervisor.
- **Lỗi bùng nổ retry lồng nhau (Nested Retry Explosion)**: Gateway retry 3 lần $\times$ SDK retry 3 lần $\times$ Graph retry 3 lần = 27 lần gọi, tiêu sạch ngân sách.
  - *Khắc phục*: Chỉ định duy nhất một tầng sở hữu việc retry lỗi truyền tải; tắt hoàn toàn cơ chế tự retry ở các tầng khác.

### 8. Chi Phí và Rủi Ro
- **Rủi ro tài chính**: Nhà cung cấp dự phòng có thể có đơn giá token cao hơn (ví dụ: GPT-4o-mini so với Gemini 1.5 Flash). Hãy tính toán phần ngân sách tạm giữ dựa trên model đắt nhất trong danh sách fallback.
