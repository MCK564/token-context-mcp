# Cách đặt prompt — dạng câu hỏi nào tiết kiệm token, dạng nào không

Tài liệu này trả lời đúng một câu hỏi: **hỏi thế nào để việc gọi token-context rẻ hơn
việc không gọi nó?**

Mọi con số bên dưới đều lấy từ phép đo của chính repository này. Không có số nào là suy
đoán. Xem `BENCHMARK_FINDINGS.en.md` §2.8–§2.12 và `evals/reports/` để đối chiếu bản ghi gốc.

## Câu trả lời một dòng

Tiết kiệm đến từ **định vị**, không đến từ **liệt kê**.

Một prompt có nêu tên mục tiêu — một file, một symbol, một module — có thể tiết kiệm
60–95% lượng đọc mà native tool phải trả. Một prompt bắt tool **liệt kê cả repository**
thường đắt hơn một lệnh `rg`, còn một prompt hỏi **ai gọi hàm này** đã đo được là tốn
**hơn 46%** so với không dùng tool.

## Những gì đã thực sự đo được

Pilot C3 có ghép cặp, trên `bench-invoice`, mỗi task một seed, tính theo token nội dung
đã truy xuất:

| Dạng prompt | Chỉ native | Có token-context | Kết quả |
|---|---:|---:|---|
| **T5 truy vết / dẫn chứng** | 76 293 | 12 232 native + 18 514 MCP = 30 746 | **−60%** |
| **T2 định vị theo tên** | 33 670 | 296 native + 30 491 MCP = 30 787 | **−9%** |
| **T3 tác động / ai gọi** | 39 404 | 48 735 native + 8 669 MCP = 57 404 | **+46%, tệ hơn** |

Trung vị mức giảm token tổng có ghép cặp trên ba task: **−0,3%**, CI95 trải từ **−53%
đến +33%**, n=3. Hãy đọc điều đó cho trung thực: **pilot này không đủ để tuyên bố tool
tiết kiệm token.** Ma trận đầy đủ 5 task × 3 seed vẫn chưa chạy. Cái nó đủ sức đưa ra là
một **thứ hạng theo từng dạng prompt** — và đó chính là nội dung của trang này.

Đo ở mức cơ chế trên `invoice-scanner` (124 file Python, ≈220 576 token):

| Cơ chế | Trước | Sau |
|---|---|---|
| Trả chữ ký thay vì thân hàm | cả file, 19 327 token | `get_file_skeleton` ≈985 token |
| Entry rút gọn thay vì đầy đủ | 107 token/symbol | 24 token/symbol |
| Sửa xếp hạng | recall 0,167, 3 mục nhiễu | recall 0,833, 0 nhiễu |

---

## Nhóm A — tiết kiệm chắc chắn. Hãy nêu tên mục tiêu.

### A1. "Cho tôi xem bề mặt public của *file này*"

Mức thắng lớn nhất đo được: **19 327 → ≈985 token, khoảng 95%.**

```text
Liệt kê public API của src/invoice_backend/s9_fields.py — chỉ chữ ký, không thân hàm.
Dùng get_file_skeleton; đừng đọc file.
```

Lý do nó hiệu quả: bạn hỏi **hình dạng** của một thứ có tên, mà đó đúng là việc tool sinh
ra để làm — trả hình dạng mà không trả byte.

Phiên bản **không** hiệu quả: *"cho tôi xem file đó"*. Câu đó ép đọc toàn bộ file, và bạn
trả tiền cho **cả** skeleton **lẫn** file.

### A2. "Truy vết pipeline này / đưa dẫn chứng cho X"

**76 293 → 30 746 token, −60%** trên task truy vết T5.

```text
Truy vết một hoá đơn đi từ đầu vào tới lúc được lưu trong invoice-scanner.
Nêu các stage theo đúng thứ tự trong mã nguồn, kèm path hoặc symbol làm dẫn chứng.
```

Lý do nó hiệu quả: câu trả lời là một nhúm symbol nằm rải rác trong một cây mã lớn. Native
tool phải grep nhiều lần và đọc rộng mới tìm ra; index thì đã biết sẵn chúng ở đâu.

### A3. "Xung quanh symbol này có gì"

```text
Tìm symbol extract_with_trace, rồi lấy context của nó ở depth=1.
Chỉ yêu cầu include_body=true cho đúng symbol cuối cùng mà tôi cần xem phần cài đặt.
```

Lý do nó hiệu quả: `find_symbols` → `get_symbol_context` là đường rẻ nhất đi từ một cái tên
tới vùng lân cận của nó. Thân hàm mới là phần đắt, nên hãy xin nó **sau cùng và chỉ một lần**.

---

## Nhóm B — tiết kiệm ít, hoặc hoà

### B1. Định vị theo tên

**33 670 → 30 787 token, −9%.** Có thật nhưng nhỏ. Đáng dùng vì viết nhanh hơn một lệnh
`rg` cho tử tế, chứ không phải vì nó thay đổi ngân sách.

### B2. Tìm theo nội dung thân hàm

`search_source(query="ocr", limit=100, max_tokens=4096)` trả về **41 file trong 3 900
token ước lượng**, không bị cắt, trên index `bench-invoice` đã dựng lại.

Chi phí xấp xỉ ngang `rg`. Lý do nên chọn nó nằm ở thứ trả về: **symbol ID và khoảng dòng**
đưa thẳng được vào `get_symbol_context`, thay vì các dòng thô mà bạn còn phải tự định vị.

---

## Nhóm C — thường không tiết kiệm, đôi khi còn đắt hơn

### C1. Câu hỏi về tác động và về "ai gọi" — đo được **+46% tệ hơn**

Đây là chỗ phải cẩn thận. Ở T3, agent dùng MCP **rồi vẫn đi grep**, trả tiền hai lần:
48 735 token native chồng lên 8 669 token kết quả MCP.

Nguyên nhân trực tiếp là một tín hiệu "kết quả có thể chưa đầy đủ" báo sai, và lỗi đó đã
được sửa. Nhưng căng thẳng gốc vẫn còn: cạnh đồ thị ở đây là **cạnh từ vựng, không phải đồ
thị lời gọi ngữ nghĩa**, tool nói rõ điều đó, và một agent cẩn thận sẽ phản ứng bằng cách
đi kiểm chứng bằng native.

Nếu hỏi câu này, hãy nói rõ bạn chấp nhận cái gì:

```text
Ai gọi parse_receipt_number? Dùng get_impact_slice.
Đồ thị từ vựng dạng ứng viên là chấp nhận được — cứ ghi nhãn như vậy và ĐỪNG kiểm chứng
lại bằng native search. Nếu kết quả báo node_limit_reached=false thì coi như traversal
đã đủ cho mục đích của tôi.
```

Không cấp phép đó thì hãy chuẩn bị trả tiền cho cả hai đường.

### C2. Định hướng thuần tuý và liệt kê

Một lệnh `rg --files` trả về danh sách file **đầy đủ** với 18 228 token. `get_repo_map` ở
ngân sách 4 096 trả về khoảng **6,6% số symbol** — và nhìn vào kết quả bạn **không biết được**
93% còn lại là gì.

Dùng `repo_map` để định hướng ban đầu khi bạn muốn các điểm vào **đã xếp hạng**. Đừng dùng
nó khi bạn muốn **toàn bộ** bất cứ thứ gì.

### C3. "Tìm đoạn code làm việc X" mà không có tên nào để bám

Đo trên `bench-invoice` với từ khoá `ocr`:

| | |
|---|---:|
| File có thân mã nhắc tới `ocr` | 41 |
| Symbol nằm trong các file đó | 270 |
| Symbol có `ocr` trong **tên** | 27 |
| **Vô hình với `find_symbols`** | **243 (90%)** |

`find_symbols` khớp theo tên và tên đầy đủ. `rank_symbols` chấm điểm theo path, tên, tên
đầy đủ và chữ ký. **Không cái nào đọc thân hàm.** Nên một câu hỏi theo *hành vi* đặt vào
hai tool đó sẽ trượt khoảng 90% lượng mã liên quan.

Hãy dùng `search_source` cho việc này — nó có đọc thân hàm. Và đừng kết luận "code không
tồn tại" chỉ vì `find_symbols` hay `repo_map` không thấy.

### C4. Mọi việc cần đúng từng byte

Rà soát cả file, refactor, sửa code. Kiểu gì bạn cũng cần mã nguồn, nên lấy skeleton trước
chỉ là trả thêm một lần tiền. Đọc thẳng file.

### C5. Repository và ngôn ngữ nằm ngoài index

- **Repository chưa đăng ký thì vô hình, và đó là chủ ý thiết kế.** Server chỉ nhận
  `repo_id` đã đăng ký, không bao giờ nhận đường dẫn.
- **Các tool mức symbol chỉ phủ Python, JavaScript và TypeScript/TSX.** Ngôn ngữ khác không
  có symbol, nên `find_symbols`, `repo_map`, `symbol_context` và `impact_slice` không có gì
  để trả.

### C6. Repository nhỏ

`list_repositories` → `get_index_status` → `repo_map` là một chi phí bắt tay cố định. Dưới
khoảng vài nghìn token mã nguồn, đọc thẳng file rẻ hơn là đi định hướng.

---

## Vệ sinh prompt — những lỗi làm hỏng cả một lần chạy

Đây không phải giả định. Pilot C3 đầu tiên cho ra tiêu đề "B1 tiết kiệm 8,5%" mà **toàn bộ
là ảo**: cả hai lệnh MCP đều lỗi, đóng góp đúng 178 token vỏ lỗi, và phép benchmark đã đem
**hai phiên native-only** ra so với nhau.

| Quy tắc | Không có nó thì hỏng thế nào |
|---|---|
| `repo_id` là **tên ngắn đã đăng ký**, không bao giờ là đường dẫn | `validate_repo_id` từ chối; mọi lệnh gọi lỗi rồi âm thầm rơi về native |
| Giữ `budget_tokens` / `max_tokens` trong trần của server | `budget_out_of_range`; gọi vẫn lỗi dù `repo_id` đã đúng |
| `depth` của đồ thị nằm trong 0–3 | request bị từ chối |
| Tên budget profile chỉ gồm `locate`, `orient`, `impact`, `read` | tên tự chế không phải là profile |
| Gặp vỏ lỗi thì **sửa request**, đừng âm thầm quay về native | bạn trả chi phí native cộng thêm giá trị tool bằng 0, mà lại tưởng là đã đo được tool |

Khối chỉ dẫn ở `SETUP.vi.md` §6 đã mã hoá đủ các quy tắc này. Dán nó vào system prompt của
agent; nó quan trọng ngang phần cấu hình server.

---

## Mẫu prompt dùng ngay

**Bề mặt của một file** (Nhóm A, trường hợp tốt nhất)
```text
Cho tôi các định nghĩa public của <path> — chỉ chữ ký, lược bỏ thân hàm.
Dùng get_file_skeleton với repo_id đã đăng ký. Đừng đọc file bằng native.
```

**Định vị rồi mở rộng** (Nhóm A)
```text
Tìm <symbol_name> trong <repo_id>. Dùng find_symbols, rồi get_symbol_context ở depth=1.
Chỉ xin include_body=true cho đúng một symbol tôi cần sửa.
```

**Truy vết** (Nhóm A, đo được −60%)
```text
Truy vết <đầu vào> tới <đầu ra> trong <repo_id>. Nêu các stage theo thứ tự trong mã nguồn,
kèm path làm dẫn chứng. Dùng budget profile "read".
```

**Tác động, đã khoá đường rơi về native** (Nhóm C — đọc C1 trước)
```text
Ai gọi <symbol>? Dùng get_impact_slice với profile "impact".
Đồ thị từ vựng dạng ứng viên là chấp nhận được; ghi nhãn như vậy và đừng kiểm chứng bằng
native trừ khi kết quả báo bị cắt hoặc có cảnh báo nhập nhằng.
```

**Tìm theo hành vi** (Nhóm C3)
```text
Đoạn code nào xử lý <hành vi> trong <repo_id>? Dùng search_source — nó đọc thân hàm.
Đừng kết luận code không tồn tại chỉ dựa vào find_symbols hay repo_map.
```

---

## Vì sao `total_tokens` là thước đo sai

Trong pilot đã kiểm chứng, `cached_input_tokens` chiếm **89–92% lượng input** ở mọi dòng.
Có một lần chạy, nội dung truy xuất là 2 558 token so với 120 832 token input đã cache —
phần nội dung chỉ chiếm **2%**. Chênh lệch total-token phần lớn đo **độ dài hội thoại**,
không đo lượng truy xuất.

Metric chính của benchmark là `retrieved_content_estimated_tokens`. Hãy đánh giá một dạng
prompt bằng con số đó, và bằng việc **sau đó agent có còn phải đọc lại mã nguồn bằng native
hay không**.

## Khi nào tiết kiệm thật sự xuất hiện

Nói lại `SETUP.vi.md` §8.4 trong một câu: tiết kiệm là thật đúng vào lúc MCP trả về đủ để
agent **không phải đọc lại mã nguồn bằng native** — muốn vậy cần `truncated=false`,
`omitted_count=0`, `freshness=fresh`, và không có cảnh báo nhập nhằng. Nếu bất kỳ cờ nào
bật lên, việc đi kiểm chứng bằng native là **đúng**, và tool trở thành phần cộng thêm thay
vì phần thay thế. Đó không phải lỗi của prompt; đó là tool đang nói thật về giới hạn hiểu
biết của nó.
