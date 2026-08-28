# token-context-mcp — Các phát hiện benchmark

Tài liệu đi kèm này chứa các mục §2.7–§2.16 được tách từ plan khắc phục. Nó ghi lại phát hiện đã đo, quyết định thiết kế benchmark và các chuỗi công việc R/E/RK.

---

## 2.7 Khám nghiệm pilot C3 (27/08/2026) — pilot đã không đo được gì về công cụ

Lượt C3 đầu tiên, `T1-orientation` trên `bench-invoice`, 1 task x 1 seed:

| Nhánh | Lời gọi MCP | Tổng token | Thời gian | Thành công |
|---|---|---|---|---|
| B0 native-only | 0 | 315.262 | 90,59 s | có |
| B1 token-context | 2 | 288.545 | 117,80 s | có |

Được báo cáo là "B1 tiết kiệm 8,5%, chậm hơn 1,30x". **Cả hai kết luận đều là ảo ảnh.** Session log cho thấy vì sao.

### Phát hiện 1 — không có gì chạy hai lần

Các lệnh trông như bị lặp trong log vì Codex phát ra **cả** `item.started` **lẫn** `item.completed` cho cùng một item. Số item riêng biệt: B0 = 8 (3 `agent_message` + 5 `command_execution`); B1 = 10 (4 `agent_message` + 2 `mcp_tool_call` + 4 `command_execution`). Không lệnh nào thực thi hai lần.

### Phát hiện 2 — cả hai lời gọi MCP đều trả về lỗi

```
get_index_status  repo_id="D:\AI\bench\invoice-scanner-frozen"                      -> lỗi, 89 tok
get_repo_map      repo_id="D:\AI\bench\invoice-scanner-frozen", budget_tokens=5000  -> lỗi, 89 tok
```

Tổng đóng góp của token-context vào B1: **178 token phong bì lỗi.** Con số 8,5% là dao động giữa các lượt chạy trong cách mỗi nhánh diễn đạt ripgrep — B0 phát ra 42.265 token đầu ra shell qua 5 lệnh, B1 phát ra 29.339 qua 4 lệnh. **Pilot đã so sánh hai phiên native-only với nhau.**

Ba nguyên nhân độc lập, mỗi cái tự nó đã đủ:

- **C-a. `repo_id` là một đường dẫn hệ thống file.** Id đã đăng ký là `bench-invoice`; `validate_repo_id` từ chối mọi thứ không khớp `^[a-z][a-z0-9_-]{0,63}$`.
- **C-b. `budget_tokens: 5000` vượt `max_result_tokens: 2048`.** Lời gọi sẽ vẫn thất bại ngay cả với id đúng.
- **C-c. Agent không thể tự sửa.** `server._invoke` gộp mọi ngoại lệ thành `"request rejected by read-only repository policy"`. Agent không biết được id sai, không biết có trần ngân sách, cũng không biết một id hợp lệ trông ra sao — nên nó bỏ công cụ sau hai lần thử và quay về shell gốc.

C-c mới là khuyết tật thiết kế. **Không công cụ nào phơi ra danh sách `repo_id` đã đăng ký**, và phần hướng dẫn agent trong `INTEGRATION.md` không hề nói `repo_id` là một tên ngắn đã đăng ký chứ không phải đường dẫn. Mọi công cụ đều đòi một giá trị mà agent không có cách nào khám phá ra.

### Phát hiện 3 — đường cơ sở của C1 là một hình nộm

C1 so với "đọc mọi file `.py`" = 201.767 token cho `bench-invoice`, cho ra 25x-184x. **B0 chưa bao giờ làm vậy.** Một agent có năng lực sẽ grep: B0 hoàn thành tác vụ với 42.265 token đầu ra shell — ít hơn 4,8 lần so với đường cơ sở ngây thơ.

Đo theo thứ agent thực sự làm, phép so sánh trung thực là `repo_map` đối chiếu `rg --files`, và với tác vụ định hướng thì `rg` thắng về độ phủ trên mỗi token:

| Ngân sách `repo_map` | Payload | Số symbol hiện | Độ phủ trên 437 |
|---|---|---|---|
| 1.024 | 992 | 8 | 1,8% |
| 2.048 | 1.969 | 16 | 3,7% |
| 4.096 | 3.996 | 32 | 7,3% |
| 8.192 | 8.125 | 63 | 14,4% |

Một lệnh `rg --files` duy nhất của B0 tốn 18.228 token và trả về danh sách file **đầy đủ**. Ở trần server 2.048, công cụ cho 3,7% số symbol. **Với T1-orientation, `repo_map` không cạnh tranh nổi với ripgrep**, và không lượng sửa lỗi kế toán nào thay đổi được điều đó.

Đây là một giới hạn thật, không phải lỗi: `repo_map` trả về symbol đã xếp hạng kèm metadata — giàu hơn trên mỗi mục, nhưng phủ ít hơn nhiều trên mỗi token. Lợi thế của nó lẽ ra phải hiện ra ở các tác vụ **định vị và tác động** (T2, T3, T5), nơi `rg` phải chạy đi chạy lại và đồ thị chính là thứ được hỏi. Những tác vụ đó **chưa được chạy**.

### Đầu việc mới

- **W13 — làm `repo_id` khám phá được.** Thêm công cụ `list_repositories` chỉ trả về id (không bao giờ trả root — đó mới là nửa nhạy cảm). Thiếu nó, bề mặt công cụ không dùng được với một agent chưa được cấu hình bằng tay.
- **W14 — làm lỗi hành động được mà không lộ đường dẫn.** Phân biệt `unknown_repo_id`, `budget_out_of_range` (nêu rõ trần) và `policy_rejected`. Chính một thông điệp mờ đục duy nhất đã biến hai sai sót sửa được thành một cuộc bỏ cuộc hoàn toàn.
- **W15 — nêu hợp đồng ngay trong hướng dẫn agent.** `INTEGRATION.md` phải nói: `repo_id` là tên ngắn đã đăng ký, hãy gọi `list_repositories` trước, và `budget_tokens` không được vượt trần server.

### Sửa giao thức trước khi chạy lại C3

1. Sửa W13-W15 trước. Một pilot mà công cụ lỗi ở mọi lời gọi thì không đo được gì.
2. **Khẳng định sức khỏe công cụ ngay trong runner**: cho lượt chạy fail nếu bất kỳ `mcp_tool_call` nào trả về phong bì `error`. Pilot này lẽ ra đã dừng sau 4 giây thay vì sinh ra con số 8,5% gây hiểu nhầm.
3. **Báo cáo hai đường cơ sở**: đọc-toàn-bộ ngây thơ (C1, một cận trên) *và* native-có-năng-lực (đầu ra shell thật của B0, mẫu số trung thực). Hãy trích dẫn cái thứ hai.
4. **Chạy T2/T3/T5, không chỉ T1.** Định hướng đúng là tác vụ mà công cụ yếu nhất về mặt cấu trúc.
5. Ghi `cached_input_tokens` riêng — 83% input ở cả hai nhánh là phát lại cache, nên chênh lệch tổng token phản ánh độ dài hội thoại nhiều hơn là khối lượng truy xuất.


### Các bản sửa đã áp dụng (28/08/2026)

Ba khiếm khuyết tìm được khi truy nguyên vì sao chính con số của pilot C3 đã kiểm định trông sai:

**Sửa A — ngừng nhân đôi mọi phản hồi MCP.** Các tool trong `server.py` trả về một dict thường, và `structured_output=True` khiến MCP SDK JSON-dump đúng dict đó vào một khối text `content` **thêm vào** `structured_content` — 42% mỗi phản hồi đo được là bản sao byte-cho-byte của nửa còn lại. Giờ mỗi tool trả về trực tiếp một `CallToolResult`: `structured_content` mang trọn envelope (giữ nguyên — mọi test hiện có vốn đã khẳng định trên `structured_content`, không bao giờ trên `content`), còn `content` mang một dòng tóm tắt ngắn (`repo_id=... freshness=... symbols=16 omitted_count=421`) thay vì một bản sao. Đo trên `bench-invoice`, `repo_map`@2048: kích thước dây từ ~3.938 tok xuống 2.048 tok, giảm gần một nửa, và phản hồi giờ nằm gọn trong trần cấu hình thay vì vượt trần.

**Sửa B — đo tại tầng dây truyền, không đo giá trị trả về của service.** `evals/measure_context_cost.py` trước đây gọi thẳng `RetrievalService` và đo dict đó — đúng tầng mà Sửa A phát hiện đang bị nhân đôi. Giờ nó bọc mọi phản hồi qua `server._result()` (đúng đường mã mà một lời gọi MCP thật đi qua) trước khi đo, nên `calls_over_server_cap` và cổng chênh lệch kế toán phản ánh đúng thứ agent thực sự bị tính phí. Chạy lại sau Sửa A: chênh lệch tệ nhất từ 34,6x → 1,28x trên `bench-invoice`, từ 32,1x → 1,14x trên `token-context`; `calls_over_server_cap` từ 3 → 0 ở cả hai.

**Sửa C — tính byte kết quả MCP vào nội dung đã truy xuất.** `evals/run_c3.py` trước đây chỉ cộng dồn byte từ các item `command_execution`; kết quả `mcp_tool_call` được đếm số lượng (`mcp_completed_call_count`) nhưng chưa bao giờ được đo kích thước. Điều này tạo ra `native_command_output_estimated_tokens: 296` cho một lượt B1 mà thực tế đã kéo về 30.491 token qua 9 lời gọi MCP thành công, khiến nhánh đó trông như gần như không truy xuất gì so với 33.670 token đầu ra shell của B0. Runner giờ cũng cộng dồn `mcp_result_output_bytes` từ mỗi `mcp_tool_call.result` đã hoàn thành, và ghi `mcp_result_output_estimated_tokens` cùng `retrieved_content_estimated_tokens = native + mcp` cho mỗi lượt. `benchmark-report` giờ báo thêm `median_retrieved_content_estimated_tokens` bên cạnh trường native-only cũ. Tính lại từ chính session log của pilot đã kiểm định: nội dung thật của T2 là B0 33.670 so với B1 30.787 (gần như ngang nhau, không phải "B1 gần như không truy xuất gì"); T5 là B0 76.293 so với B1 30.746 (B1 thực sự truy xuất ít hơn).

Không điều nào ở đây thay đổi `total_tokens` (con số do nhà cung cấp tính phí, dùng để tính thống kê giảm theo cặp) cho ba dòng pilot đã ghi — các lượt đó có trước Sửa A và không thể sửa lại hồi tố. **Kết luận `-0,32%` của pilot đã kiểm định vẫn đứng nguyên như đã báo cáo và vẫn không phải bằng chứng cho một khoản tiết kiệm** (`paired_count: 3`, CI95 `[-0,53, +0,33]`); điều thay đổi là một lượt chạy lại hôm nay sẽ (a) gửi khoảng một nửa số byte dây truyền cho mỗi lời gọi MCP, và (b) ghi một con số truy xuất nội dung trung thực thay vì một con số khiến B1 trông như không dùng công cụ. Chạy lại C3 vẫn là việc còn mở.

**Kiểm chứng:** `pytest` — 32 passed, 1 skipped, không hồi quy. `evals/measure_context_cost.py --repo-id bench-invoice` và `--repo-id token-context` đã chạy lại, báo cáo đính kèm (`evals/reports/c1-bench-invoice.json`, `evals/reports/c1-token-context.json`).

---

## 2.8 Chạy lại C3 đã xác thực (27/08/2026) — đã sửa tool health; chưa có khẳng định tiết kiệm

Lượt chạy lại dùng cùng repository frozen chỉ gồm source `bench-invoice`, khớp SHA-256 của prompt trong từng cặp B0/B1 và chạy T2, T3, T5 một lần. B1 gọi `list_repositories` trước, chọn `bench-invoice`, và mọi lượt B1 đều có `mcp_health: passed`, không có phong bì lỗi MCP. `evals/run_c3.py` nay từ chối ghi usage nếu MCP trả lỗi; report cũng từ chối các error row và prompt hash không khớp.

| Tác vụ | B0 tổng / thời gian | B1 tổng / thời gian | MCP call của B1 | Giảm token ghép cặp |
|---|---:|---:|---:|---:|
| T2 định vị | 468.382 / 100,27 s | 718.246 / 138,72 s | 10 | -53,35% |
| T3 tác động | 998.548 / 207,83 s | 1.001.735 / 208,83 s | 4 | -0,32% |
| T5 bằng chứng | 879.958 / 177,62 s | 589.001 / 163,16 s | 6 | +33,06% |

Cả hai nhánh đều trả lời có bằng chứng source cho cả ba tác vụ; đây là kiểm tra thành công thủ công, chưa phải điểm quality/non-inferiority chính thức. Trung vị của ba *mức giảm theo cặp* là **-0,32%** (B1 nhỉnh hơn một chút), và các giá trị quan sát trải từ **-53,35% đến +33,06%**. Vì vậy pilot này **không** đủ để khẳng định tiết kiệm token đầu-cuối.

`cached_input_tokens` chiếm 89-92% input ở mọi dòng, nên phải báo cáo riêng và không diễn giải chênh lệch tổng token như khối lượng truy xuất. Ước lượng competent-native-output là chẩn đoán cục bộ `utf8-bytes / 4`, không phải chi phí provider; B1 thấp hơn ở T2/T5 nhưng cao hơn ở T3.

Rerun phát lộ hai vấn đề còn lại: agent vẫn đọc native sau MCP discovery, và ranking của `repo_map` bị nhiễu ở T5. Cổng C3 tiếp theo là call policy được khai báo trước (kèm call budget), các task/seed còn lại và quality gate đã định nghĩa. Không công bố con số tiết kiệm trước khi ma trận ghép cặp đủ 5 task x 3 seed vượt qua.

Projection có thêm content được tính lại trực tiếp từ raw session log nhưng giữ nguyên mọi trường token provider. Nó ghi T2 B1 là **296 native + 30.491 MCP = 30.787 token nội dung truy xuất**, T5 B1 là **12.232 native + 18.514 MCP = 30.746**. Đây là chẩn đoán nội dung truy xuất cục bộ, không phải số tính phí; T3 cũng được ghi và B1 có tổng 57.404 token nội dung truy xuất.

Artifact: `evals/reports/c3-validated-content.jsonl`, `evals/reports/c3-validated-content-summary.json` và `evals/runs/c3-rerun/`. Các artifact `c3-invoice-*`, `c3-rerun.jsonl` và report content trước C chỉ để audit, không được dùng cho khẳng định hiệu năng.

---

## 2.9 Vì sao workflow hybrid không thể cho thấy tiết kiệm — nguyên nhân gốc (28/08/2026)

Giả thuyết sau pilot đã kiểm định là "cap quá thấp, và prompt cho phép agent quay về native". Đo đạc cho thấy cap là nguyên nhân **ít quan trọng nhất** trong bốn, và một trong các thay đổi cap được đề xuất sẽ **che lấp một lỗi** thay vì sửa nó.

### R1 — Index không tìm được code theo việc nó LÀM, chỉ theo việc nó được ĐẶT TÊN

`find_symbols` khớp SQL `name LIKE ? OR qualified_name LIKE ?`. `rank_symbols` chấm điểm trên `path + name + qualified_name + signature`. **Không cái nào từng nhìn vào thân hàm.** `rg` nhìn từng byte.

Đo trên `bench-invoice`, từ khóa `ocr`:

| | |
|---|---|
| Số file có thân mã chứa `ocr` | **41** |
| Symbol nằm trong các file đó | **270** |
| Symbol có `ocr` trong tên — tìm được qua `find_symbols` | **27** |
| **Symbol vô hình với `find_symbols` dù nằm trong code OCR** | **243 (90%)** |

`repo_map(query="ocr")` cũng không khép được khoảng này, vì nó xếp hạng trên cùng một tập chỉ-có-tên:

| ngân sách | symbol trả về | trong đó ở file OCR | bị bỏ |
|---|---|---|---|
| 1.024 | 8 | 7 | 429 |
| 2.048 | 16 | 13 | 421 |
| 4.096 | 33 | 25 | 404 |
| 8.192 | 64 | 48 | 373 |

Ở **mức ngân sách tối đa cấu hình được**, công cụ trả về 64 trên 437 symbol (14,6%). Để chạm tới 270 symbol liên quan OCR sẽ tốn khoảng 35.000 token `repo_map`; `rg -n 'ocr'` định vị cả 41 file trong một lệnh. Đây là lý do T2 và T5 đẩy agent về ripgrep, và **không giá trị `max_result_tokens` nào thay đổi được điều đó**.

### R2 — `graph_node_limit_capped_by_server` bật lên khi không có gì bị cắt

`service.py:422` phát cảnh báo khi `effective_max_nodes < max_nodes` — tức là bất cứ khi nào *yêu cầu* bị kẹp, bất kể phép duyệt có bao giờ chạm tới giới hạn hay không. `symbol_limit_capped_by_server` (dòng 184) cùng dạng.

Đo trên `parse_receipt_number`, chính là chủ thể của T3:

| `max_nodes` | node trả về | cạnh | token dây | cảnh báo |
|---|---|---|---|---|
| 75 | 23 | 24 | 5.546 | không |
| 200 | 23 | 24 | 5.546 | không |
| 500 | 23 | 24 | 5.546 | không |

**Đồ thị thật chỉ có 23 node.** Giới hạn chưa bao giờ ràng buộc ở bất kỳ mức nào. Nhưng agent yêu cầu `max_nodes=100` trên server cap 75, nên `100 > 75` làm bật `graph_node_limit_capped_by_server`, agent đọc đúng thành "đồ thị này có thể chưa đầy đủ", rồi quay về ripgrep — **48.735 token đầu ra native cho T3, nhiều hơn cả 39.404 của B0**, bị kích hoạt bởi một cảnh báo về việc cắt cụt **đã không xảy ra**.

Đây cùng họ lỗi với W3 (`truncated: false` theo cấu tạo): *một trường trạng thái tính từ yêu cầu thay vì tính từ kết quả.*

Lưu ý điều này với đề xuất tăng cap. Nâng `max_graph_nodes` lên 200 làm `min(100, 200) = 100`, phép kẹp biến mất, cảnh báo im lặng — nên **triệu chứng đỡ đi trong khi lỗi vẫn sống** cho bất kỳ ai yêu cầu quá 200. **Hãy sửa cảnh báo; đừng tinh chỉnh vòng quanh nó.**

### R3 — Bảng imports được index và không bao giờ được phục vụ

`index/sqlite_store.py` duy trì bảng `imports`, ghi đầy ở mọi lượt index: **579 dòng trên 96 file** với `bench-invoice`. Không tool truy xuất nào đọc nó — `imports_for_path` chỉ được gọi bởi chính nhánh tái sử dụng của indexer.

Cạnh import là phần duy nhất của index này được *parse chứ không phải đoán*. Chúng đúng là bằng chứng mà một câu hỏi "ai phụ thuộc vào module này" (T3) cần, và không mang chút nào trong 22% mơ hồ từ vựng. Công cụ hiện đang trả lời câu hỏi phụ thuộc bằng dữ liệu kém tin cậy nhất của nó, trong khi dữ liệu đáng tin nhất nằm im không ai đọc.

### R4 — Độ mơ hồ tập trung, không rải đều

Tỷ lệ 22% cạnh mơ hồ trên `bench-invoice` không rải đều trên 601 symbol. Nó là một nhúm tên phương thức phổ biến:

```
run 127 · available 25 · _geometry 17 · main 14 · recognise 13
__init__ 13 · set_cell_margins 12 · build 11 · get_inputs 11 · draw_box 10
```

Riêng `run` là 127 trên 336 cạnh mơ hồ (38%); mười tên đầu chiếm khoảng 75%. Một backend ngữ nghĩa đầy đủ (O4, 1–2 tuần) là câu trả lời trọn vẹn, nhưng **phân giải theo phạm vi file và module** — ưu tiên định nghĩa cùng file, rồi cùng package, trước khi tuyên bố mơ hồ — sẽ giải quyết phần lớn số này với chi phí nhỏ hơn nhiều.

### Điều này có nghĩa gì với benchmark

Trong workflow hybrid, MCP mang tính **cộng thêm**, không phải **thay thế**: agent trả tiền cho công cụ *và* cho những lần đọc xác minh mà chính công cụ gợi ra. Khối lượng truy xuất tính lại cho thấy đúng điều đó:

| Task | B0 native | B1 native + MCP | B1 tổng |
|---|---|---|---|
| T2-locate | 33.670 | 296 + 30.491 | 30.787 (−9%) |
| T3-impact | 39.404 | 48.735 + 8.669 | **57.404 (+46%)** |
| T5-evidence | 76.293 | 12.232 + 18.514 | 30.746 (−60%) |

T3 không phải nhiễu — nó là R2 tạo ra một tín hiệu thiếu-đầy-đủ giả, cộng R1/R3 khiến agent không có cách đáng tin nào để liệt kê caller. **Chừng nào R1–R3 chưa sửa, một benchmark hybrid đang đo chi phí của sự mất lòng tin, không phải giá trị của truy xuất.**

---

## 2.10 Kế hoạch: chuỗi R

Nguyên tắc sắp xếp: sửa thứ khiến agent mất lòng tin vào công cụ, trước khi chi bất cứ gì cho dung lượng.

### R-P0 — Ngừng nói dối về việc cắt cụt *(~0,5 ngày)*

- Chỉ phát `graph_node_limit_capped_by_server` khi phép duyệt **thực sự dừng ở giới hạn** (`len(visited) >= effective_max_nodes`), không phải khi yêu cầu bị kẹp. Tương tự với `symbol_limit_capped_by_server`: chỉ bật khi store trả về đúng `effective_limit` dòng.
- Thêm `nodes_visited`, `node_limit_reached: bool` vào envelope của impact-slice để agent phân biệt được "23 node, đầy đủ" với "75 node, đã dừng".
- **Nghiệm thu:** `impact_slice` trên `parse_receipt_number` ở `max_nodes=100`, server cap 75, trả về 23 node và **không** cảnh báo cap. Một symbol có đồ thị thực sự vượt cap thì vẫn phải cảnh báo.
- **Hiệu quả dự kiến:** loại bỏ tác nhân đã khiến T3 tốn ~49k token đọc lại native.

### R-P1 — Phục vụ bảng imports *(~0,5 ngày)*

- Tool mới `get_module_dependents(repo_id, path | module)` trả về bên import và module được import từ bảng `imports`, kèm `basis: "parsed_import_statements"` để phân biệt với cạnh từ vựng.
- Thêm số đếm `imports` và `imported_by` vào `get_file_skeleton` và `get_index_status`.
- **Nghiệm thu:** với bất kỳ file nào trong `bench-invoice`, tool trả về đúng tập importer như `rg -n "^\s*(from|import).*<module>"`, không mục nào mơ hồ.
- **Vì sao làm trước:** đây là cách rẻ nhất để cho các câu hỏi dạng T3 một câu trả lời mà agent tin được mà không cần xác minh.

### R-P2 — Tìm kiếm toàn văn thân mã *(~2 ngày, đây mới là thứ quan trọng)*

Đây là bản sửa cho R1 và là thay đổi duy nhất chạm tới lý do agent với tay lấy `rg`.

- Thêm bảng ảo FTS5 trên thân symbol lúc index. SQLite 3.45.3 trong venv này đã biên dịch sẵn FTS5 — **đã kiểm chứng, không thêm phụ thuộc mới**.
- Tool mới `search_source(repo_id, query, limit, max_tokens)`: khớp toàn văn trên thân mã, trả về `symbol_id`, path, khoảng dòng và một đoạn trích có giới hạn — tương đương có cấu trúc của `rg -n`, kèm span và ID mà `rg` không cho được.
- Mở rộng `rank_symbols` thêm một thành phần khớp thân mã để `repo_map(query=…)` thôi xếp hạng chỉ trên tên.
- Chi phí lưu trữ: thân mã vốn đã được đọc lúc index; FTS5 thêm khoảng bằng kích thước nguồn trên đĩa (~800 KB cho `bench-invoice`). Chặn bằng `max_file_bytes` sẵn có.
- **Nghiệm thu:** `search_source(query="ocr")` trả về ≥35 trong 41 file mà `rg` tìm thấy, trong một ngân sách token đã nêu. Chạy lại C1 và ghi tỷ lệ độ-phủ-trên-token so với `rg -n`.
- **Nói thẳng:** việc này làm công cụ **cạnh tranh được** với ripgrep về định vị, chứ không hiển nhiên vượt trội. Lợi thế của nó vẫn là span có cấu trúc + symbol id + đồ thị, không phải độ thu hồi thô.

### R-P3 — Phân giải cạnh theo phạm vi *(~1 ngày)*

- Phân giải một định danh theo định nghĩa cùng file trước, rồi cùng package, trước khi rơi về chỉ mục tên toàn cục; ghi phạm vi đã dùng vào `EdgeRecord.evidence`.
- **Nghiệm thu:** tỷ lệ cạnh mơ hồ trên `bench-invoice` giảm từ 22,0%; báo cáo tỷ lệ mới và phân tách theo tên. **Không tuyên bố con số mục tiêu trước khi đo.**
- Giữ nguyên `lexical_edges_are_not_complete_semantic_analysis` — thu hẹp phạm vi làm giảm sai số, không xóa bỏ nó.

### R-P4 — Config, làm sau cùng và nhỏ nhất *(~10 phút)*

Chỉ sau R-P0. Mức `4096 / 200 / 30` đề xuất là hợp lý nhưng nên áp dụng vì lý do đúng: `max_result_tokens = 4096` thực sự tăng gấp đôi độ phủ `repo_map` (16 → 33 symbol) với chi phí gấp đôi, đó là một đánh đổi công bằng cho việc định hướng. `max_graph_nodes = 200` **không nên** được áp dụng như một cách sửa cảnh báo T3 — R-P0 mới sửa điều đó, còn tăng cap chỉ giấu nó đi.

| Khóa | Hiện tại | Đề xuất | Cơ sở đo được |
|---|---|---|---|
| `max_result_tokens` | 2.048 | 4.096 | độ phủ `repo_map` 3,7% → 7,3% trên `bench-invoice` |
| `max_graph_nodes` | 75 | 200 | không có hiệu ứng đo được với T3 (đồ thị 23 node); chỉ nhận để thôi kẹp các yêu cầu hợp lệ |
| `max_symbol_results` | 15 | 30 | `find_symbols("ocr")` hiện cắt ở 15 trên 27 kết quả khớp tên |

### R-P5 — Hai giao thức benchmark, không phải một *(~1 ngày)*

Nhánh hybrid trả lời "cái này có giúp một agent thật không?" Nhánh MCP-only trả lời "truy xuất tốt tới đâu?" Đó là hai câu hỏi khác nhau và nhánh đơn hiện tại đang gộp chúng làm một.

- **B1-hybrid** — prompt hiện tại. Báo cáo `retrieved_content_estimated_tokens` tách theo kênh; dự trù MCP còn mang tính cộng thêm cho tới khi R-P0–R-P2 vào.
- **B2-mcp-first** — shell native chỉ được phép tối đa **một lần mỗi task**, và chỉ để xác nhận một dòng cụ thể đã định vị được qua MCP. Lời gọi native thứ hai làm lượt chạy fail. Cách này đo trực tiếp độ đầy đủ của truy xuất.
- Thêm **log tác nhân xác minh**: với mỗi lệnh native trong B1, ghi lại cảnh báo MCP nào đã xuất hiện ngay trước nó. Việc đó biến "agent không tin công cụ" từ một suy luận thành một phép đo, và lẽ ra đã chỉ đích danh R2 ngay từ pilot đầu tiên.

### Thứ tự

```
R-P0  trung thực về cắt cụt    0,5 ngày  <- gỡ tín hiệu giả đã khiến T3 tốn ~49k token
R-P1  phục vụ imports          0,5 ngày  <- câu trả lời phụ thuộc đáng tin, dữ liệu đã index sẵn
R-P2  tìm toàn văn thân mã     2 ngày    <- lý do thật khiến agent dùng rg
R-P3  phân giải theo phạm vi   1 ngày    <- 22% mơ hồ là 10 cái tên, không phải 601 symbol
R-P4  nâng config             10 phút    <- chỉ sau R-P0, và chỉ vì độ phủ
R-P5  tách hai giao thức       1 ngày    <- rồi mới chạy lại 5 task x 3 seed
```

**Đừng chạy lại ma trận C3 đầy đủ trước R-P0 và R-P2.** Hành vi hiện tại của agent là phản ứng hợp lý trước một công cụ báo thiếu độ đầy đủ của chính nó và không tìm được theo thân mã; 30 lượt chạy sẽ đo đúng phản ứng đó 30 lần.

### Trạng thái hiện thực chuỗi R (28/08/2026)

R-P0 đến R-P5 đã được hiện thực:

- cảnh báo cap của impact/symbol dựa trên kết quả thực sự bị bỏ, kèm
  nodes_visited và node_limit_reached;
- get_module_dependents phục vụ quan hệ import đã parse và các bộ đếm import;
- FTS5 index thân symbol và toàn bộ source đã index; search_source trả snippet,
  span và ID có nguồn;
- phân giải lexical ưu tiên định nghĩa cùng file, rồi cùng package, trước global;
- registry đang chạy dùng max_result_tokens=4096, max_graph_nodes=200 và
  max_symbol_results=30.

Trên index bench-invoice vừa build lại, search_source(query="ocr",
limit=100, max_tokens=4096) trả 41 file trong 3.900 token ước lượng, không
truncate; 36 match gắn được symbol ID. R-P5 đã có trong runner (giao thức
hybrid, mcp-first và log verification trigger). Ma trận C3 đầy đủ
5 task × 3 seed vẫn chưa chạy.

---

## 2.11 Ngân sách thích ứng và tính co dãn — cơ sở đo được (28/08/2026)

Một lượt kiểm chứng độc lập nêu ba điểm: các con số MCP đang trộn payload service với payload trên wire, `repo_map@1024` chỉ trả 8 symbol, và `repo_map@1024` mất ~15 giây chứ không phải ~1 giây. Cả ba đều tái lập được. Nguyên nhân gốc bên dưới; hai trong ba **không phải như vẻ ngoài của nó**.

### E1 — 8 symbol là vấn đề mã hóa, không phải vấn đề dung lượng

`repo_map` lấp `budget_tokens` bằng các entry nguyên khối. Chi phí đo được của một entry trên `invoice-scanner`:

```json
{"rank": 75.75,
 "symbol": {"symbol_id": "python:src/invoice_core/contracts.py:ScanResult:b5482a5c4f4ad30c",
            "path": "src/invoice_core/contracts.py", "name": "ScanResult",
            "qualified_name": "ScanResult", "kind": "class", "signature": "class ScanResult",
            "start_line": 60, "end_line": 76, "is_private": false},
 "evidence": [{"path": "src/invoice_core/contracts.py", "start_line": 60,
               "end_line": 76, "sha256": "73ca8b5fa606"}]}
```

| | token |
|---|---|
| `symbol` | 71 |
| `evidence` | 26 |
| `rank` | 2 |
| **tổng một entry** | **107** |
| **dạng tối thiểu hữu ích** `src/invoice_core/contracts.py:60 class ScanResult` | **13** |

**8,2 lần của mỗi entry là dư thừa**, và đều mang tính cơ học:

- `evidence` lặp lại `path`, `start_line`, `end_line` vốn đã có trong `symbol`, cộng một digest **giống hệt nhau cho mọi symbol cùng file**.
- `symbol_id` đã mã hóa sẵn `path` + `qualified_name`; cả hai lại được lặp thành trường riêng.
- `qualified_name` bằng đúng `name` với mọi symbol cấp cao nhất.
- `is_private` chính là `name.startswith("_")`.

Độ phủ ở từng ngân sách, đo được (503 symbol không phải test):

| ngân sách | wire | giữ lại | bỏ | độ phủ | token/symbol |
|---|---|---|---|---|---|
| 512 | 495 | 3 | 500 | 0,6% | 165 |
| 1.024 | 1.051 | 8 | 495 | 1,6% | 131 |
| 2.048 | 2.049 | 16 | 487 | 3,2% | 128 |
| 4.096 | 4.110 | 33 | 470 | 6,6% | 125 |

Ở mức ~13 token/entry, chính ngân sách 1.024 đó sẽ chở được khoảng **70 symbol thay vì 8**. Nâng cap lên 4.096 — gấp bốn chi phí ngữ cảnh — chỉ mua được 33. **Entry rẻ hơn thắng cap lớn hơn cả một bậc độ lớn, và không tốn gì thêm mỗi lời gọi.**

### E2 — 15 giây là ba vòng lặp truy vấn N+1, không phải freshness

Profile `repo_map@1024`: **1.077 lời gọi `execute` của SQLite, 7,71 s trên tổng 9,05 s.**

| Vị trí | Số lần | Thời gian | Cách sửa |
|---|---|---|---|
| `_evidence_for_symbol` → `store.file(path)` mỗi entry đã xếp hạng | 565 | 4,31 s | Nạp bảng files một lần vào dict |
| Lambda render của `pack_by_budget` → `store.edges_from()` mỗi ứng viên | 503 | 3,77 s | `store.edges()` — một truy vấn |
| `_freshness` băm lại, gọi một lần mỗi lần thử `build_response` | 7 | 0,82 s | Tính một lần cho mỗi request |

`store.edges()` **đã tồn tại sẵn** và trả về cả 1.658 cạnh trong **0,02 s** so với 5,82 s của vòng N+1 — đo được **248 lần**. Và lưu ý bộ nhồi gọi hàm render trên cả 503 ứng viên chỉ để giữ lại 8: chi phí co giãn theo *kích thước index*, không theo ngân sách.

Freshness từng là nghi phạm ở W8/O3 và **không phải** thủ phạm ở đây — 220 file băm lại hết 0,09 s. Nó sẽ quan trọng với `video-lecturer` (4.559 file); ở quy mô này thì không.

### E3 — `search_source` vượt chính cái cap nó được cấp

Với `max_result_tokens = 4096`, `search_source(query="ocr", max_tokens=4096)` trả về payload wire **4.173 token** — vượt 77. Báo cáo độc lập nói đúng: `calls_over_server_cap` phải ghi 1 cho phép đo đó.

Nguyên nhân chính là phần W1 còn để ngỏ: `_pack_to_budget` chặn payload *service*, còn dòng summary `content` cộng khung `CallToolResult` được thêm vào **sau đó, ngoài ngân sách**. Nên mọi tool đều vượt một lượng nhỏ và biến thiên. Nó chỉ vượt qua vạch khi một lời gọi được nhồi sát trần, mà `search_source` ở 4096 thì đúng như vậy.

### E4 — Bề mặt đang bị cố định cứng

Mỗi mục dưới đây hôm nay là một hằng số biên dịch, và mỗi mục đều là một **chính sách** lẽ ra phải thay đổi theo quy mô repository hoặc hình dạng tác vụ:

| Hằng số | Giá trị | Ở đâu | Nên phụ thuộc vào |
|---|---|---|---|
| mặc định `budget_tokens` | 1024 | `server.py:55` | loại tác vụ |
| `max_tokens` (`file_skeleton`) | 1024 | `server.py:122` | kích thước file |
| `max_tokens` (`symbol_context`) | 2048 | `server.py:141` | depth, `include_body` |
| `limit` (`find_symbols`, `search_source`) | 20 | `server.py:75,103` | loại tác vụ |
| `depth` / `max_nodes` (`impact_slice`) | 2 / 100 | `server.py:165-166` | kích thước đồ thị |
| dải `depth` | 0–3 | `service.py:501,576` | cố định là hợp lý; nhưng phải ghi rõ vì sao |
| dải `limit` | 1–100 | `service.py:201,281` | kích thước index |
| trọng số xếp hạng | `2.0 / 0.5 / 8.0 / 12.0 / 0.25` | `ranking.py:24-30` | chưa bao giờ được tinh chỉnh; không có đánh giá nào |
| `max_edges_per_symbol` | 100 | `lexical_edges.py:12` | độ dài thân symbol |
| confidence của cạnh | `0.55 / 0.2` | `lexical_edges.py:42` | phải đến từ hiệu chuẩn, không phải một số viết thẳng |

Trọng số xếp hạng đáng được gắn cờ riêng: `12.0` và `8.0` đủ lớn để **át hoàn toàn** bậc đồ thị, và **chưa phép đo nào từng biện minh cho bất kỳ số nào trong năm số đó.** Biến chúng thành config mà không có đánh giá chỉ là chuyển chỗ phỏng đoán vào một file khác.

---

## 2.12 Kế hoạch: chuỗi E (ngân sách co dãn)

### E-P0 — Làm entry rẻ đi trước khi làm ngân sách lớn lên *(~1 ngày)*

Thay đổi có đòn bẩy cao nhất trong toàn bộ tài liệu này. Không mục nào khác trong chuỗi E quan trọng bằng.

- Bỏ `evidence` khỏi entry của `repo_map`; nó lặp lại các trường đã có. Giữ digest file **một lần cho mỗi phản hồi** trong một map `file_digests` khóa theo path, không phải mỗi symbol một lần.
- Bỏ `qualified_name` khi nó bằng `name`; bỏ `is_private` (suy ra được); bỏ `path` và `qualified_name` khỏi entry khi `symbol_id` đã mang chúng, hoặc rút `symbol_id` thành một khóa chỉ mục mờ và giữ lại các trường đọc được.
- Thêm `format: "compact" | "full"` cho `repo_map`, mặc định compact. Giữ `full` cho bên gọi cần provenance theo từng symbol.
- **Nghiệm thu:** chi phí entry ≤ 25 token; `repo_map@1024` trả ≥ 40 symbol trên `invoice-scanner`; `evals/measure_context_cost.py` ghi lại con số token/symbol mới. **Không tuyên bố trước một con số độ phủ cụ thể** khi chưa chạy lượt đó.

### E-P1 — Diệt ba vòng lặp N+1 *(~0,5 ngày)*

- `repo_map`: một lời gọi `store.edges()` thay cho 503 lời gọi `edges_from()`.
- `_evidence_for_symbol` / `_repo_map_entry`: nâng `store.files()` thành một `dict[path, FileRecord]` cho mỗi request.
- `_freshness`: tính một lần cho mỗi request, truyền kết quả vào `build_response`.
- Thêm kiểm tra trước `mtime_ns` + `size` rồi mới băm (chính là mục W8/O3), để việc này vẫn rẻ trên repository 4.000 file dù ở mức 220 file nó chưa phải nút thắt.
- **Nghiệm thu:** `repo_map@1024` trên `invoice-scanner` dưới 1 giây; số lời gọi `execute` của SQLite dưới 20 mỗi call. **Hãy assert số lượng truy vấn trong một test** — một con số đếm mới là thứ làm cho hồi quy N+1 hiện ra.

### E-P2 — Chặn ngân sách ở tầng wire, không ở payload service *(~0,5 ngày)*

Hoàn tất phần W1 bỏ dở và khép E3.

- Chuyển việc cưỡng chế ngân sách ra lớp ngoài cùng: nhồi dựa trên `CallToolResult` đã tuần tự hóa, hoặc dành sẵn một khoản đã đo cho phong bì và dòng summary trước khi nhồi.
- **Nghiệm thu:** với mọi tool ở mọi ngân sách trên cả hai repository, `wire_tokens ≤ max_result_tokens`; `calls_over_server_cap` bằng 0, bao gồm cả `search_source(ocr)@4096`.

### E-P3 — Hồ sơ ngân sách theo loại tác vụ *(~1 ngày)*

Chỉ làm sau E-P0, vì ngân sách đúng phụ thuộc vào chi phí một entry.

Thêm khối config `[budget_profiles]` gồm các hồ sơ có tên, để bên gọi chọn theo **ý định** thay vì đoán số token:

```toml
[budget_profiles.locate]      # "X nằm ở đâu" - ít kết quả, cần chính xác
tools = ["find_symbols", "search_source"]
budget_tokens = 1024
limit = 30

[budget_profiles.orient]      # "repo này có gì" - cần bề rộng
tools = ["repo_map"]
budget_tokens = 4096
format = "compact"

[budget_profiles.impact]      # "sửa X thì hỏng gì" - cần đồ thị
tools = ["impact_slice", "get_module_dependents"]
budget_tokens = 4096
max_nodes = 200
depth = 2

[budget_profiles.read]        # "cho tôi xem file/symbol này"
tools = ["file_skeleton", "symbol_context"]
budget_tokens = 2048
include_body = true
```

- Thêm tham số `profile` tùy chọn cho mỗi tool; tham số tường minh luôn thắng hồ sơ.
- `list_repositories` trả về tên các hồ sơ khả dụng cùng ngân sách của chúng, để agent **chọn** thay vì **bịa** một con số — đúng cùng một lỗi khám phá như W13, áp vào ngân sách.
- **Đừng** làm hồ sơ tự điều chỉnh theo kích thước index ở bước này. Hãy phát hành các hồ sơ cố định có tên trước, đo xem mỗi loại tác vụ thực sự chọn hồ sơ nào, rồi mới cân nhắc việc suy dẫn. Một ngân sách tự tinh chỉnh mà chưa ai đo là **lớp phỏng đoán thứ hai**.

### E-P4 — Mặc định nhận biết quy mô *(~0,5 ngày)*

Ở những chỗ mặc định thực sự nên bám theo kích thước repository:

- `max_edges_per_symbol`: suy từ độ dài thân symbol trung vị thay vì cố định 100.
- Trần `limit` của `find_symbols` / `search_source`: co giãn theo số symbol đã index, sàn 30, trần 100.
- Mặc định `max_nodes` của `impact_slice`: `min(trần_server, 2 x kích thước thành phần trung vị)` đo lúc index và lưu vào manifest.
- Ghi mọi giá trị suy dẫn vào index manifest để một phản hồi có thể nêu rõ chính sách nào đã sinh ra nó.
- **Nghiệm thu:** hai repository chênh lệch quy mô rõ rệt nhận được mặc định suy dẫn khác nhau, và cả hai đều nhìn thấy được qua `get_index_status`.

### E-P5 — Chưa biến trọng số xếp hạng thành config *(0 ngày — một quyết định, không phải công việc)*

`ranking.py` mang năm hằng số chưa tinh chỉnh. Phơi chúng ra thành config sẽ cho phép bên gọi tinh chỉnh một hàm chấm điểm **chưa bao giờ được đánh giá** đối chiếu với bất kỳ phán định liên quan nào. **Hãy giữ chúng cố định và thêm một comment nói rõ chúng chưa được đánh giá**, cho tới khi có một tập nhãn gồm các cặp (truy vấn, symbol liên quan) để tinh chỉnh dựa vào. Tập đó mới là điều kiện tiên quyết, không phải phần đường ống config.

Điều tương tự áp dụng cho `0.55 / 0.2` trong `lexical_edges.py`: chúng phải trở thành **phép đo** (R-P3 phân giải theo phạm vi, rồi một cuộc hiệu chuẩn), không bao giờ là núm vặn config.

### Thứ tự

```
E-P0  entry rẻ                1 ngày    <- gấp 8 lần symbol trên mỗi token, không đổi dung lượng
E-P1  diệt các vòng N+1      0,5 ngày   <- 15 s -> dưới 1 s, riêng phần cạnh đã đo được 248x
E-P2  chặn ngân sách ở wire  0,5 ngày   <- khép lỗi vượt cap của search_source
 |
E-P3  hồ sơ theo tác vụ       1 ngày    <- chỉ có nghĩa khi entry đã rẻ
E-P4  mặc định theo quy mô   0,5 ngày
E-P5  giữ nguyên ranking      0 ngày    <- quyết định: không tinh chỉnh khi chưa có tập đánh giá
```

**E-P0 trước E-P3.** Tinh chỉnh ngân sách trong khi mỗi entry lãng phí 8 lần là tối ưu sai biến số: ở mức 13 token mỗi entry, ngân sách mặc định 1.024 đã vượt trội hơn mức 4.096 của hôm nay.

### Trạng thái hiện thực chuỗi E (28/08/2026)

E-P0 và E-P1 đã được hiện thực và kiểm chứng:

- `repo_map` compact là mặc định; mỗi symbol có dạng `[short_id, path:line, kind/name, optional rank marker]`, còn digest file chỉ xuất hiện một lần trong `file_digests`;
- `format="full"` giữ lại dạng evidence theo từng symbol cho bên gọi cần provenance;
- `repo_map@1024` trên index `invoice-scanner` đang dùng trả về 40 symbol; entry lớn nhất là 24 token ước lượng và trung bình là 17,4;
- `repo_map@1024` hoàn tất trong khoảng 0,16 giây và dùng ba câu lệnh SQLite (files, symbols, edges), đạt nghiệm thu dưới một giây và dưới 20 query;
- freshness được tính một lần mỗi request, bảng file được cache theo request, và pre-check `mtime_ns`/size hiện có tránh băm lại file không đổi.
- trọng số ranking vẫn hard-code và đã có ghi chú rằng chúng chưa được đánh giá; không thêm núm tinh chỉnh khi chưa có tập relevance được gán nhãn.

Harness đo hiện ghi thêm số symbol trả về, token mỗi symbol, thống kê kích thước entry, thời gian chạy và số câu lệnh SQLite. Payload service của `repo_map@1024` là 1.015 token ước lượng, còn ước lượng trên wire MCP là 1.090 vì phong bì kết quả bên ngoài vẫn tốn token. E-P2 vẫn còn mở để budget toàn bộ wire result; `search_source(ocr)@4096` vẫn vượt wire cap hiện tại.

---

## 2.13 Đặc tả ranking — đo trên tập nhãn (28/08/2026)

Hai báo cáo định hướng về `invoice-scanner`, một dùng native thuần và một dùng token-context, bất đồng về kiến trúc. Đối chiếu cả hai với repository cho thấy báo cáo MCP sai hai điểm sự thật, và nguyên nhân là **ranking, không phải dung lượng**. Mục này đặc tả bản sửa và phép đo gác cửa nó.

### Đường cơ sở, đã đo

`evals/rank_eval.py` trên `evals/relevance/orientation_invoice_scanner.json`, `repo_map@4096`, k=10:

```
 #  grade  symbol                       path
 1      3  ScanResult                   src/invoice_core/contracts.py
 2      2  PageDetection                src/invoice_core/contracts.py
 3      2  OcrResult                    src/invoice_core/contracts.py
 4      0  rgb                          scripts/build_s0_s6_report_revised.py   <- nhiễu
 5      -  probe                        src/invoice_frontend_dl/degradation.py
 6      1  QualityReport                src/invoice_core/contracts.py
 7      1  TextBox                      src/invoice_core/contracts.py
 8      0  merge                        src/invoice_core/config.py              <- nhiễu
 9      0  audit                        scripts/prepare_datasets.py             <- nhiễu
10      1  GeometryInfo                 src/invoice_core/contracts.py

essential recall : 1/6 = 0,167
essential thiếu  : InvoiceProcessor, FrontendPipeline, GeomFrontend, DlFrontend, get_frontend
nhiễu trong top-10: 3
nDCG@10          : 0,4235
```

Năm trên sáu symbol thiết yếu không bao giờ xuất hiện, ba trên mười ô là nhiễu, và sáu trên mười đến từ **cùng một file**. Đây là phép đo mà bản sửa phải làm dịch chuyển.

### Vì sao công thức hiện tại đảo ngược tầm quan trọng kiến trúc

`ranking.py` chấm `1.0 + 2.0*in_degree + 0.5*out_degree + 8.0*mỗi từ khóa + 12.0*<khớp chính xác> + 0.25*<class>`. In-degree áp đảo, mà in-degree đo **một cái tên được tham chiếu bao nhiêu lần** — trong một codebase có kiểu, điều đó nghĩa là **kiểu dữ liệu xếp trên logic**:

| Symbol | grade | in | out | hình dạng | nhóm |
|---|---|---|---|---|---|
| `ScanResult` | 3 | 36 | 5 | connector | src |
| `InvoiceProcessor` | 3 | 5 | 18 | connector | src |
| `DlFrontend` | 3 | 6 | 10 | connector | src |
| `get_frontend` | 3 | 5 | 3 | connector | src |
| `FrontendPipeline` | 3 | 2 | 2 | connector | src |
| `GeomFrontend` | 3 | 1 | 2 | near-source | src |
| `rgb` | 0 | 24 | 0 | **pure sink** | **scripts** |
| `merge` | 0 | 16 | 0 | **pure sink** | src |
| `audit` | 0 | 14 | 1 | connector | **scripts** |
| `build_document` | 0 | 1 | 28 | **near-source** | **scripts** |

`rgb` — một hàm tạo màu trong script dựng báo cáo — xếp trên `InvoiceProcessor`, tức orchestrator và là symbol được nhắc nhiều nhất trong tài liệu thiết kế, **gấp năm lần** chỉ tính riêng in-degree.

Ba lý do cấu trúc khiến các symbol thiết yếu bị điểm thấp:

- **Orchestrator được gọi, không được tham chiếu.** `InvoiceProcessor` là entry point khai báo trong console-script; không chỗ nào bên trong gọi tên nó.
- **Protocol gần như không có tham chiếu nào.** `FrontendPipeline` (in=2) là interface mà cả hai frontend cạnh tranh đều implement.
- **Registry nối bằng chuỗi khóa.** `register("geom", GeomFrontend)` và `register("dl", DlFrontend)` khiến mỗi frontend chỉ có đúng một tham chiếu từ vựng. `GeomFrontend` với in=1 không bao giờ nổi lên — và đó **chính xác** là lý do báo cáo MCP mô tả một kiến trúc A/B **thiếu mất một trong hai nhánh**.

Chuyển sang out-degree cũng không cứu được: top bốn của nó là `build_document` (28), `EnsembleAdapter` (24), `_build_tab` (21) và một unit test (19). **Không bậc nào dùng riêng nhận diện được code trung tâm về mặt kiến trúc.**

### Đặc tả

Ba thay đổi, xếp theo độ mạnh của bằng chứng. Tín hiệu 1 và 2 là **sự kiện** đọc từ cây cú pháp và manifest dự án; tín hiệu 3 là heuristic và được gán trọng số tương ứng.

**S1 — Dấu hiệu vai trò cấu trúc (bằng chứng cứng, để nâng hạng).**
Ghi lúc index vào `SymbolRecord.roles: list[str]`, mỗi vai trò kèm bằng chứng sinh ra nó:

| Vai trò | Phát hiện từ | Áp dụng cho |
|---|---|---|
| `protocol_definition` | Tree-sitter: class có base là `Protocol` | `FrontendPipeline`, `OcrEngine` |
| `protocol_implementation` | class có tập phương thức phủ một Protocol đã biết, hoặc được đăng ký qua factory có kiểu đó | `GeomFrontend`, `DlFrontend`, `PassthroughFrontend`, ba OCR engine |
| `declared_entry_point` | `[project.scripts]` / `[project.entry-points]` trong `pyproject.toml` | `invoice_backend.processor:main` |
| `module_entry_point` | `if __name__ == "__main__"` trong module định nghĩa | `app.py` và 11 script |
| `registry_wiring` | lời gọi tới hàm có tham số kiểu Protocol | `register`, `get_frontend` |

Đây là **những tín hiệu duy nhất** có thể làm nổi `FrontendPipeline` (in=2) và `GeomFrontend` (in=1). Không cách gán trọng số nào cho bậc chạm tới được chúng.

**S2 — Hình dạng bậc, không phải độ lớn bậc (để hạ hạng).**
Thay `2.0*in + 0.5*out` bằng một thành phần tính trên **hình dạng** của cặp:

- `out == 0` → pure sink. Tiện ích lá hoặc kiểu dữ liệu; chặn trần đóng góp của nó.
- `in <= 1` → near-source. Gốc script hoặc code chết; chặn trần đóng góp.
- cả hai đều không tầm thường → connector; đây là hình dạng của **mọi** symbol grade-3 trừ `GeomFrontend`.

Riêng điều này đã hạ `rgb` (24/0), `merge` (16/0) và `build_document` (1/28) — ba trên bốn mục nhiễu đã gán nhãn — mà không đụng tới symbol thiết yếu nào.

**S3 — Nhóm đường dẫn (heuristic, trọng số nhẹ).**
`src` 209 symbol, `tests` 164, `scripts` 153, `ui` 70, `evaluation` 62. Với tác vụ định hướng thì `scripts/` và `evaluation/` là công cụ, không phải kiến trúc. Áp một mức hạ hạng vừa phải, **cấu hình được theo từng repository**, và ghi rõ nhóm nào đã tạo ra điều chỉnh đó vào phản hồi để bên gọi nhìn thấy. Đây là tín hiệu **duy nhất** ở đây mang tính phỏng đoán; nó không được phép nặng hơn S1.

**Ngoài phạm vi.** `include_tests=False` đã loại `tests/` rồi. Trọng số từ khóa (`8.0`, `12.0`) giữ nguyên: tập này có `query: null` nên **không đánh giá được chúng**, và tinh chỉnh một trọng số mà tập không đo được chính là cách các con số hiện tại ra đời.

### Tập nhãn

`evals/relevance/orientation_invoice_scanner.json` — 22 symbol gán điểm 0–3, mỗi mục mang theo bằng chứng cho điểm của nó. Nhãn đến từ **bằng chứng trong repository** (số lần được nhắc trong tài liệu thiết kế, `pyproject.toml`, định nghĩa Protocol, khóa registry), **không** đến từ đầu ra của agent nào; hai báo cáo được coi là **giả thuyết** mà tập này kiểm tra.

Các mục grade-0 là nửa mang tính phân biệt. `build_document` được đưa vào **có chủ ý** để một lần chuyển ngây thơ sang xếp hạng theo out-degree cũng trượt.

Giới hạn được ghi thẳng trong file: một repository, một tác vụ, 22 symbol, `query: null`. **Tập này phát hiện được một cuộc đảo ngược ranking thô bạo. Nó không chứng minh được ranking nào tốt hơn ranking nào một cách tổng quát.** Hãy coi điểm đạt là "khuyết tật đã biết đã biến mất", không bao giờ là "ranking đã tốt".

### Nghiệm thu

Chạy `python evals/rank_eval.py --set evals/relevance/orientation_invoice_scanner.json --budget 4096 --compare evals/reports/rank-before.json`:

| Chỉ số | Trước | Mục tiêu |
|---|---|---|
| essential recall @10 | 0,167 (1/6) | **≥ 0,67 (4/6)** |
| nhiễu trong top-10 | 3 | **0** |
| nDCG@10 | 0,4235 | **≥ 0,70** |

`GeomFrontend` (in=1, near-source) là mục khó nhất và **cố ý** không nằm trong mục tiêu 4/6: chạm tới nó đòi hỏi phần phát hiện `protocol_implementation` của S1 phải xuyên qua được lớp gián tiếp registry. Nếu nó nổi lên, phần hiện thực S1 thực sự đang hoạt động.

Cổng bổ sung: `evals/measure_context_cost.py` không được cho thấy hồi quy về token/symbol, và `repo_map@1024` vẫn phải trả ≥40 symbol trên `invoice-scanner`. **Ranking không được phép mua độ liên quan bằng kích thước payload.**

### Một năng lực mà không báo cáo nào đưa ra được

`pyproject.toml` khai báo `invoice-scan = "invoice_backend.processor:main"`, và **`processor.py` không định nghĩa `main` nào cả**. Cả hai báo cáo định hướng đều lặp lại khai báo đó như một sự thật; bản native đã **đọc chính file đó** mà vẫn bỏ sót, vì nó đọc file vì mục đích khác.

Phân giải các entry point khai báo đối chiếu với symbol đã index là **một truy vấn** trên dữ liệu vốn đã có sẵn trong index, và ripgrep không làm được nếu không được bảo phải tìm gì. Hãy thêm vào `get_index_status` dưới dạng `entry_points: [{declared, resolved: bool}]`. Đó là một câu trả lời nhỏ và cụ thể cho câu hỏi "index cho tôi thứ gì mà grep không cho" — và với lập luận đó, nó đáng giá hơn bất kỳ tỷ lệ token nào trong tài liệu này.

---

## 2.14 SWOT — đề xuất "Semantic Graph Bootstrapping" (28/08/2026)

Đề xuất: chạy **một lượt warm-up** cho LLM đọc toàn bộ codebase, gán nhãn ngữ nghĩa cho từng node (`ENTRYPOINT` / `CORE_LOGIC` / `CONTRACT` / `UTILITY`), lưu vào graph DB cục bộ; sau đó **runtime dùng thuần MCP** với truy xuất 2 tầng theo seed node và Personalized PageRank.

Đánh giá dưới đây đối chiếu từng luận điểm với repo thật và với ràng buộc kiến trúc của gói này.

### Phần đề xuất nói ĐÚNG, và đã được đo độc lập

Chẩn đoán "bẫy high in-degree" là **chính xác**, và §2.13 đã đo được nó trước khi đọc đề xuất này: `rgb` (in=24, một hàm tạo màu trong script dựng báo cáo) xếp trên `InvoiceProcessor` (in=5, orchestrator) **gấp năm lần**. `essential recall @10 = 1/6`. Đây không phải suy đoán lý thuyết — nó là khuyết tật đã đo.

Ba đề xuất kỹ thuật cũng đúng hướng:

- **Node categorization** trùng phần lớn với **S1** ở §2.13.
- **Personalized PageRank / seed-biased walk** là hướng đúng và **không cần LLM**.
- **Lazy 2-tier retrieval** khả thi ngay với các tool hiện có: `find_symbols` → `symbol_context` → `impact_slice`. Đây là thay đổi **giao thức**, không phải thay đổi code.

### Strengths — nếu áp dụng đúng phần

- **Node categorization giải đúng thứ ranking không giải được.** `FrontendPipeline` (in=2) và `GeomFrontend` (in=1) không thể nổi lên bằng bất kỳ cách gán trọng số nào cho bậc. Chỉ nhãn vai trò mới chạm tới.
- **Tách warm-up khỏi runtime là mô hình đúng.** Gói này vốn đã có đúng ranh giới đó: `index` là lệnh admin ghi snapshot, `serve` chỉ đọc. Đề xuất khớp với kiến trúc sẵn có.
- **Chi phí có thể tăng dần, không phải một lần.** Indexer đã theo dõi `files_reused` / `files_reparsed` theo sha256. Nhãn ngữ nghĩa có thể cache theo hash từng file và chỉ gán lại cho file đổi — biến "warm-up 220k token mỗi lần" thành "vài trăm token mỗi commit".
- **Seed-biased ranking né được vấn đề gốc.** PageRank toàn cục hỏi "cái gì quan trọng nhất repo" — câu hỏi mà `rgb` thắng. PPR từ seed hỏi "cái gì quan trọng **với vấn đề này**" — câu hỏi đúng, và không cần LLM.

### Weaknesses — những chỗ đề xuất sai với repo này

- **Quy tắc phạt điểm theo tên thư mục bắn trúng con số không.** Đề xuất đề nghị giảm 70% trọng số cho `utils/`, `helpers/`, `log/`, `common/`, `constants/`. Repo này **không có thư mục nào trong số đó**. Và mục nhiễu `merge` nằm ở `src/invoice_core/config.py` — một đường dẫn `src/` hoàn toàn hợp lệ. Heuristic này **bỏ sót đúng thứ nó nhắm tới**.
- **Vấn đề "hidden edges" nêu sai đối tượng.** Đề xuất lo về decorator (`@router.get`), DI (`Depends()`), event-driven (Kafka/Redis). Grep toàn bộ `src/` và `ui/`: **không có mẫu nào trong số đó**. Cạnh ẩn thật ở đây là **registry nối bằng chuỗi**: `register("geom", GeomFrontend)`. Một lượt LLM đọc code cũng chỉ **đoán** được liên kết đó, không phân giải được nó. Câu trả lời trung thực vẫn là backend ngữ nghĩa (O4), không phải nhãn LLM.
- **"Giảm 90–95% token" không có bằng chứng và mâu thuẫn với số đo.** §2.9 đo được: trong workflow hybrid MCP là **cộng thêm**, không thay thế; T3 tăng +46% khối lượng truy xuất. Ở tác vụ orientation, native vừa rẻ hơn vừa đúng hơn. Không con số nào trong dự án này chống lưng cho mức 90–95%.
- **"Context chuẩn xác 100%" không đứng vững.** Nhãn do LLM sinh ra là **suy luận**, không phải sự kiện parse. Chúng có thể sai, và sai một cách không nhìn thấy được.
- **Chi phí warm-up co giãn xấu.** `invoice-scanner` 220.576 token là khả thi. `video-lecturer` **1.841.549 token** — vượt cửa sổ ngữ cảnh của phần lớn model. Với repo lớn, "đọc toàn bộ một lần" là bất khả thi, đúng cái quy mô mà công cụ này cần thiết nhất.

### Opportunities

- **Lấy phần categorization, bỏ phần LLM.** §2.13 S1 đã đặc tả năm vai trò suy ra từ **bằng chứng parse**: `protocol_definition` (base class `Protocol` trong cây Tree-sitter), `protocol_implementation`, `declared_entry_point` (`[project.scripts]`), `module_entry_point` (`__main__`), `registry_wiring`. Rẻ hơn, **kiểm chứng được**, không cần mạng, và cho ra đúng loại nhãn mà đề xuất muốn.
- **Nếu vẫn muốn nhãn LLM, đặt nó ở tầng admin.** Một lệnh `token-context enrich --repo-id X` riêng biệt, chạy ngoài server, ghi vào một bảng **tách rời** với `basis: "llm_inferred"` và model id + prompt hash. Server tiếp tục chỉ đọc. Đây là con đường duy nhất không phá ranh giới bảo mật.
- **PPR từ seed node là hạng mục giá trị cao nhất không cần LLM.** Nó trả lời đúng câu hỏi mà tác vụ đặt ra và tránh hoàn toàn bẫy in-degree toàn cục.
- **Lazy 2-tier có thể thử ngay hôm nay.** Không cần code mới — chỉ cần một giao thức prompt: bắt đầu từ `find_symbols`, mở rộng bằng `symbol_context` depth=1, chỉ lấy body cho node đã lọc. Đo bằng chính `rank_eval.py` và `measure_context_cost.py`.

### Threats

- **Phá vỡ ranh giới chỉ-đọc.** `SECURITY.md:3` nêu rõ: gói này *"deliberately has no tools for shell execution, **writes**, reindexing, registration or arbitrary filesystem paths"*. Một vòng "LLM gán nhãn → lưu vào graph" đòi hỏi đường ghi mà dự án **cố ý** từ chối có. Nếu để agent ghi lại nhãn qua MCP, toàn bộ mô hình bảo mật sụp.
- **Không được gọi API mạng.** `README:17`: *"does not edit files, execute shell commands, listen on HTTP, **call network APIs**"*. Server không thể tự gọi LLM. D-003 cũng cấm điều này.
- **Sụp đổ provenance — đây là nguy cơ lớn nhất.** Giá trị đặc biệt của gói này là **mọi khẳng định đều có bằng chứng**: `completeness.basis`, `evidence` kèm SHA-256, cảnh báo `lexical_edges_are_not_complete_semantic_analysis`. Trộn nhãn LLM vào cùng index mà không có ranh giới provenance sẽ biến một công cụ *biết giới hạn của mình* thành một công cụ *đoán một cách tự tin*. Đó là đúng thứ mà toàn bộ tài liệu này đã dành nhiều tuần để loại bỏ khỏi Task 2.
- **Nhãn cũ trở nên nguy hiểm hơn index cũ.** Index cũ được `freshness` phát hiện qua sha256. Một nhãn ngữ nghĩa cũ — "module này là CORE_LOGIC" — vẫn *trông* đúng rất lâu sau khi code đã đổi vai trò. Cần TTL và ràng buộc theo hash, nếu không nó âm thầm sai.
- **Nhãn LLM không thể kiểm định nếu không có tập nhãn.** Đề xuất giả định LLM gán vai trò đúng. `orientation_invoice_scanner.json` tồn tại chính là để kiểm điều đó — và nó chỉ có 22 mục trên một repo. Triển khai nhãn LLM trước khi có tập đánh giá là lặp lại đúng sai lầm của trọng số ranking hiện tại: những con số chưa ai đo.

### Kết luận: khả thi tới đâu

| Thành phần đề xuất | Khả thi | Ghi chú |
|---|---|---|
| Chẩn đoán bẫy in-degree | **Đã xác nhận** | Đo độc lập ở §2.13 |
| Node categorization | **Nên làm ngay** | Nhưng suy từ parse (S1), không từ LLM |
| Seed-biased PPR | **Nên làm** | Không cần LLM, giá trị cao |
| Lazy 2-tier retrieval | **Thử được hôm nay** | Thay đổi giao thức, không cần code |
| Phạt điểm theo tên thư mục | **Bỏ** | Bắn trúng 0 symbol ở repo này |
| Cache nhãn theo sha256 | **Nên làm nếu enrich** | Biến chi phí một lần thành tăng dần |
| Warm-up LLM gán nhãn | **Chỉ ở tầng admin CLI** | Không bao giờ trong server; phải có `basis` riêng |
| "MCP thuần, giảm 90–95%" | **Chưa có bằng chứng** | Số đo hiện tại mâu thuẫn |
| "Context chuẩn xác 100%" | **Bác bỏ** | Nhãn suy luận không phải sự kiện |

**Lộ trình đề nghị:** làm S1 + S2 ở §2.13 trước (parse-derived, rẻ, kiểm chứng được, đã có cổng nghiệm thu). Đo lại bằng `rank_eval.py`. **Chỉ khi** essential recall vẫn dưới mục tiêu mới cân nhắc tầng enrich bằng LLM — và khi đó đặt nó ở lệnh admin riêng, bảng riêng, `basis` riêng, TTL theo sha256.

Lý do thứ tự này: S1 giải đúng những ca mà đề xuất viện dẫn (`FrontendPipeline`, `GeomFrontend`), tốn một phần nhỏ chi phí, và **không đánh đổi thứ tài sản duy nhất mà gói này thực sự có** — việc nó nói thật về những gì nó biết.

---

## 2.15 Kế hoạch: chuỗi RK (sửa ranking)

§2.13 là đặc tả, §2.14 là phán quyết SWOT. Mục này là **breakdown công việc có thứ tự** rút ra từ cả hai — thứ trước đó còn thiếu.

Nguyên tắc: mỗi bước phải **dịch chuyển được một con số trong `rank_eval.py`**, hoặc nó không thuộc chuỗi này.

Đường cơ sở cần đánh bại (`evals/reports/rank-before.json`):

```
essential recall @10 : 0,167 (1/6)
nhiễu trong top-10   : 3
nDCG@10              : 0,4235
```

### RK-P0 — Ghi vai trò cấu trúc lúc index *(~1,5 ngày, phần lớn nhất)*

Hiện thực **S1**. Đây là bước duy nhất chạm được `FrontendPipeline` (in=2) và `GeomFrontend` (in=1).

File thay đổi:

| File | Việc |
|---|---|
| `models.py` | Thêm `roles: list[str]` và `role_evidence: dict[str, str]` vào `SymbolRecord` |
| `parse/treesitter.py` | Phát hiện `protocol_definition` (class có base `Protocol`), `module_entry_point` (`if __name__ == "__main__"`) |
| `index/runner.py` | Đọc `[project.scripts]` / `[project.entry-points]` từ `pyproject.toml` → `declared_entry_point`; suy `protocol_implementation`; phát hiện `registry_wiring` |
| `index/sqlite_store.py` | Thêm cột `roles_json`; cập nhật `_symbol_from_row` |

**Rủi ro di trú phải xử lý:** nhánh tái sử dụng ở `runner.py:41-47` mở snapshot **cũ** để đọc lại symbol theo sha256. Một DB cũ không có cột `roles_json` sẽ làm `_symbol_from_row` ném lỗi. Hai cách, chọn một và ghi rõ:

- Bọc phần đọc `previous_store` trong `try/except` rồi rơi về parse lại toàn bộ (đơn giản, một lượt index chậm).
- Hoặc ghi `schema_version` vào bảng `metadata` và bỏ qua việc tái sử dụng khi phiên bản không khớp (sạch hơn, nên chọn cách này).

Cách thứ hai đáng làm vì nó cũng vá được lỗ hổng sẵn có: hiện `write_snapshot` chỉ `DELETE FROM` rồi chèn lại, nên **không có gì phát hiện được thay đổi schema**.

**Nghiệm thu:** `get_index_status` báo số symbol có ít nhất một vai trò; `FrontendPipeline`, `OcrEngine` mang `protocol_definition`; `GeomFrontend`, `DlFrontend` mang `protocol_implementation`. Chưa đụng tới ranking ở bước này — chỉ ghi dữ liệu.

### RK-P1 — Hình dạng bậc thay cho độ lớn bậc *(~0,5 ngày)*

Hiện thực **S2**. Chỉ sửa `ranking.py`.

Thay `2.0*in + 0.5*out` bằng thành phần tính trên hình dạng cặp: `out == 0` → pure sink, `in <= 1` → near-source, cả hai khác 0 → connector.

**Nghiệm thu:** `rgb` (24/0), `merge` (16/0), `build_document` (1/28) rời khỏi top-10. `nhiễu trong top-10` từ 3 → **≤1**. Chạy `rank_eval.py --compare rank-before.json`.

Làm được **độc lập với RK-P0** — nên có thể chạy song song, và nó là bước rẻ nhất cho một cải thiện đo được.

### RK-P2 — Dùng vai trò trong công thức xếp hạng *(~0,5 ngày, cần RK-P0)*

Cộng thành phần thưởng cho `roles`, và một mức hạ hạng nhẹ theo nhóm đường dẫn (**S3**, cấu hình được, không nặng hơn S1). Ghi `rank_basis` vào từng entry để bên gọi thấy tín hiệu nào đã nâng nó lên.

**Nghiệm thu — đây là cổng chính của cả chuỗi:**

| Chỉ số | Trước | Mục tiêu |
|---|---|---|
| essential recall @10 | 0,167 | **≥ 0,67** |
| nhiễu top-10 | 3 | **0** |
| nDCG@10 | 0,4235 | **≥ 0,70** |

Cộng thêm cổng không-hồi-quy: `repo_map@1024` vẫn ≥40 symbol, token/symbol không tăng.

### RK-P3 — Phân giải entry point khai báo *(~0,5 ngày, cần RK-P0)*

Thêm `entry_points: [{declared, resolved: bool}]` vào `get_index_status`. Dữ liệu đã có sau RK-P0.

**Nghiệm thu:** trên `invoice-scanner`, báo `invoice-scan = invoice_backend.processor:main` với `resolved: false` — lỗi thật mà **cả hai** báo cáo định hướng đều bỏ sót.

Nhỏ, nhưng đây là câu trả lời cụ thể nhất cho "index cho tôi thứ gì mà grep không cho".

### RK-P4 — Xếp hạng theo seed node *(~1 ngày, cần RK-P1)*

Từ §2.14 — hạng mục giá trị cao nhất **không cần LLM**.

Khi lời gọi có `query` hoặc `symbol_id`, chấm điểm bằng random walk thiên vị seed thay vì bậc toàn cục. PageRank toàn cục hỏi "cái gì quan trọng nhất repo" — câu hỏi mà `rgb` thắng. PPR hỏi "cái gì quan trọng **với vấn đề này**".

**Cần trước:** một tập nhãn thứ hai **có `query`**. Tập hiện tại là `query: null` nên **không đo được** thay đổi này. Không triển khai RK-P4 trước khi có tập đó — đó đúng là sai lầm đã tạo ra trọng số `8.0`/`12.0` hiện tại.

### RK-P5 — Thử giao thức truy xuất 2 tầng *(~0,5 ngày, không cần code)*

Từ §2.14. Chỉ là một giao thức prompt: bắt đầu bằng `find_symbols` / `search_source`, mở rộng `symbol_context` depth=1, chỉ lấy body cho node đã lọc. Đo bằng `measure_context_cost.py` và một lượt C3 nhánh riêng.

Làm được **ngay hôm nay**, độc lập với mọi bước trên.

### Không thuộc chuỗi này

- **Trọng số từ khóa `8.0` / `12.0`** — tập nhãn hiện tại có `query: null`, không đo được. Giữ nguyên.
- **Nhãn ngữ nghĩa do LLM sinh** — §2.14 kết luận: chỉ ở tầng admin CLI, bảng riêng, `basis` riêng, và **chỉ khi** RK-P2 không đạt cổng.
- **Phạt điểm theo tên thư mục** — bắn trúng 0 symbol trên repo này.

### Thứ tự

```
RK-P1  hình dạng bậc         0,5 ngày  ← rẻ nhất, độc lập, hạ 3 mục nhiễu
RK-P0  ghi vai trò lúc index 1,5 ngày  ← song song được với RK-P1
 |
RK-P2  vai trò vào ranking   0,5 ngày  ← CỔNG CHÍNH (recall ≥0,67, nhiễu 0)
RK-P3  entry point resolution 0,5 ngày
 |
[cần tập nhãn thứ hai có query]
RK-P4  seed-biased PPR         1 ngày
RK-P5  thử 2 tầng            0,5 ngày  ← làm được ngay, bất cứ lúc nào
```

**RK-P1 trước** vì nó rẻ, độc lập, và cho một con số dịch chuyển ngay — xác nhận harness `rank_eval.py` hoạt động trước khi đổ 1,5 ngày vào RK-P0.

**Giới hạn cần nhắc lại:** 22 symbol, một repo, một tác vụ. Đạt cổng nghĩa là "khuyết tật đã đo đã biến mất", **không phải** "ranking đã tốt". Muốn khẳng định mạnh hơn thì cần tập nhãn thứ hai trên repo khác — và đó cũng là điều kiện tiên quyết của RK-P4.

### Trạng thái thực thi chuỗi RK (28/08/2026)

RK-P0 đến RK-P3 đã được hiện thực và kiểm chứng trên index sống của
`invoice-scanner`. Index dùng schema `2.0`, lưu bằng chứng vai trò cấu trúc,
và `get_index_status` báo `symbols_with_roles`, `role_counts` cùng trạng thái
phân giải entry point. Entry point
`invoice-scan = invoice_backend.processor:main` được báo
`resolved: false`.

RK-P1 đưa tập nhãn từ recall `0,167` / nhiễu `3` / nDCG `0,4235` thành
recall `0,333` / nhiễu `0` / nDCG `0,4464`. RK-P2 thêm bonus vai trò đã đo,
hạ điểm theo nhóm đường dẫn và `rank_basis` trong entry full. Kết quả cuối là
recall `0,833` (5/6), nhiễu `0`, nDCG `0,7742`; compact map budget 1024 trả
42 symbol trên `invoice-scanner` và 42 trên `token-context`.

Bộ đóng gói compact giữ nguyên mười symbol đứng đầu theo ranking, sau đó lấp
phần ngân sách còn lại bằng symbol trong các file đã xuất hiện. Nhờ vậy digest
mỗi file không ăn hết ngân sách độ phủ, vẫn giữ provenance và qua cổng không
hồi quy mà không đổi phần đầu ranking đã đo.

RK-P5 đã được ghi trong `docs/INTEGRATION.md` thành giao thức hai tầng:
MCP-first để định vị và mở rộng symbol có giới hạn, sau đó chỉ dùng lệnh native
read-only để xác minh một vị trí mã cụ thể khi có mơ hồ hoặc truncate. Một pilot
có giới hạn đã hoàn tất với `mcp_health: passed`, sáu MCP call, không có native
command và không có MCP error; runner ghi 2.558 token nội dung ước lượng đã
truy xuất và 135.852 provider token tổng (120.832 cached input). Đây chỉ là kết
quả kiểm tra sức khỏe giao thức, không phải tuyên bố tiết kiệm hay thay thế C3
ghép cặp.

RK-P4 vẫn cố ý để mở. Repository chưa có tập nhãn thứ hai với `query` khác
`null`, nên chưa thể đo seed-biased ranking mà không lặp lại lỗi tinh chỉnh
trọng số khi chưa có dữ liệu. Lỗi wire-cap còn lại của `search_source` thuộc
E-P2, không thuộc chuỗi RK, và vẫn được theo dõi riêng.

---

## 2.16 RK-P4: tập nhãn có query, và điều kiện chạy ma trận C3 (28/08/2026)

### Đính chính: E-P2 nhỏ hơn tôi đánh giá

Overshoot ở tầng wire là **hằng số, không co giãn theo payload**:

| Lời gọi | service | wire | overshoot | % |
|---|---|---|---|---|
| `repo_map@512` | 493 | 568 | 75 | **15,2%** |
| `repo_map@1024` | 1.024 | 1.098 | 74 | 7,2% |
| `repo_map@4096` | 4.079 | 4.154 | 75 | 1,8% |
| `search_source(ocr)@4096` | 4.103 | 4.173 | 70 | **1,7%** |
| `find_symbols(Invoice,30)` | 993 | 1.049 | 56 | 5,6% |

Đó là dòng summary `content` cộng khung `CallToolResult` — một chi phí cố định chưa bao giờ được kế toán, **không phải** lỗi co giãn. Sửa bằng cách trừ sẵn `envelope_reserve_tokens = 96` trước khi nhồi: **~30 phút, không phải 0,5 ngày**.

Nhưng giữ lại một cảnh báo: ở ngân sách nhỏ tỷ lệ tương đối tệ hơn nhiều (15,2% ở 512). Nếu E-P3 tạo profile `locate` ở 512 thì phần trừ sẵn này trở nên **bắt buộc**, không còn là tùy chọn.

**E-P2 không chặn ma trận C3.**

### Tập nhãn cho RK-P4: dùng file test làm oracle chủ đề

Vấn đề của một tập có query là ground truth. Không được dùng đầu ra của agent (vòng lặp tự khẳng định), và không được dùng chính `search_source` (khiến phép đo trở thành tautology).

Repo này có sẵn một oracle **độc lập với mọi agent và mọi ranking**: **20 file test đặt tên theo chủ đề**, và import của chúng là do đội ngũ tự viết.

```
tests/unit/test_s8_ocr.py   → s8_ocr, RapidOcrEngine, TextBox
tests/unit/test_fields.py   → s9_fields, OcrResult, TextBox
tests/unit/test_registry.py → registry, FrontendPipeline
tests/unit/test_s7_render.py, test_frontend_geom.py, test_ensemble.py, ...
```

**Cách dựng, bốn bước:**

1. **Chọn chủ đề từ tên file test.** `test_s8_ocr` → query `"ocr text recognition"`. `test_fields` → `"field extraction amount date"`. `test_registry` → `"frontend registry selection"`. Lấy 5–6 chủ đề có file test rõ ràng nhất.
2. **Hạt giống grade-3 = symbol mà file test import trực tiếp.** Đội ngũ đã tự tuyên bố những symbol này là trung tâm của chủ đề bằng cách import chúng để kiểm thử.
3. **Grade-2 = symbol định nghĩa trong các module đó nhưng test không gọi trực tiếp.** Liên quan, không thiết yếu.
4. **Grade-0 = mục nhiễu, lấy từ chủ đề *khác*.** Ví dụ với query `"ocr"`, đưa `rgb`, `merge` và một symbol grade-3 của `test_frontend_geom` vào làm nhiễu. Đây là nửa phân biệt: một ranking theo bậc toàn cục sẽ trả về cùng một top-10 cho **mọi** query, nên nhiễu chéo chủ đề chính là thứ phát hiện ra điều đó.

**Điều tập này đo được:** ranking có **phản ứng với query** hay không. Một ranking theo bậc toàn cục cho ra kết quả giống hệt nhau ở mọi query — và tập này sẽ chỉ đích danh điều đó. PPR thiên vị seed thì không.

**Giới hạn phải ghi trong file:** import là tín hiệu về *mã được kiểm thử*, không phải *mã liên quan tới câu hỏi*. Một symbol quan trọng không có test sẽ bị chấm thấp một cách sai lệch. Vì vậy tập này chỉ dùng để so **ranking A với ranking B trên cùng query**, không dùng để tuyên bố độ phủ tuyệt đối.

**Chi phí:** ~0,5 ngày dựng, chủ yếu là đọc 6 file test và kiểm từng nhãn.

### Ma trận C3 đầy đủ: cái gì thực sự chặn

Không có chặn kỹ thuật nào. Runner chạy được, giao thức đã có, `--max-mcp-calls` đã có. Bốn điều kiện dưới đây là **quyết định thiết kế phải chốt trước**, không phải lỗi phải sửa.

**1. Số nhánh đã đổi từ 2 thành 3.** RK-P5 thêm giao thức mcp-first có giới hạn. Ma trận giờ là:

```
B0 native-only  |  B1 hybrid  |  B2 mcp-first (bounded)
5 task × 3 seed × 3 arm = 45 lượt chạy
```

Ở 90–210 giây mỗi lượt, đó là khoảng 2–2,5 giờ thời gian thực cộng chi phí token. Chốt 2 hay 3 nhánh **trước khi chạy**, vì chạy lại một nhánh riêng sau đó sẽ vỡ tính ghép cặp.

**2. Chỉ số chính chưa chốt — và `total_tokens` là lựa chọn sai.** Pilot vừa rồi của bạn: **2.558 token nội dung truy xuất, 120.832 token cached input**. Nội dung chiếm 2% tổng. `total_tokens` đo **độ dài hội thoại**, không đo hiệu quả truy xuất — đúng điều §2.9 đã chỉ ra và vẫn chưa được xử lý.

Nên báo cáo ba chỉ số tách bạch, và nêu rõ cái nào là chính:

| Chỉ số | Đo cái gì |
|---|---|
| `retrieved_content_estimated_tokens` | **chính** — khối lượng truy xuất thật |
| `uncached_input_tokens` | chi phí thật cận biên |
| `total_tokens` | phụ, chi phối bởi số lượt |

**3. Chưa có quy trình chấm điểm lặp lại được.** T1–T5 có tiêu chí bằng văn xuôi ở §2.2 nhưng không có bộ chấm. Với 45 lượt, phải chốt cách chấm **trước khi nhìn số token** — nếu không thì đúng vào cái bẫy "chấm sau khi đã thấy chi phí".

**4. T1 giờ đã tự chấm được — đây là cơ hội mới.** `orientation_invoice_scanner.json` chính là ground truth cho T1. Thay vì chấm tay đạt/không đạt, chấm bằng `essential_recall` và `noise_in_top_k` trên các symbol mà báo cáo nêu ra. **Đây là bằng chứng mạnh hơn token**: nó đo *độ đúng*, và độ đúng mới là thứ báo cáo MCP đã thua ở lượt orientation (sai Streamlit/Gradio, thiếu `invoice_frontend_geom`).

### Thứ tự đề nghị

```
E-P2 trừ sẵn envelope        30 phút   ← rẻ, gỡ luôn cảnh báo over-cap
tập nhãn có query            0,5 ngày  ← mở khóa RK-P4
 |
RK-P4 seed-biased PPR          1 ngày
 |
chốt nhánh + chỉ số + bộ chấm  0,5 ngày ← quyết định, không phải code
ma trận C3 đầy đủ            2–3 giờ chạy
```

**Đừng chạy C3 trước khi chốt chỉ số chính.** Nếu vẫn để `total_tokens` làm chỉ số chính thì 45 lượt chạy sẽ tạo ra một kết quả bị chi phối bởi số lượt hội thoại — chính xác là điều mà ba lượt pilot trước đã tạo ra, chỉ nhiều hơn gấp mười lăm lần.

### Ghi chú về chính tài liệu này

File này giờ khoảng 960 dòng với 16 mục con và bốn chuỗi công việc (R, E, RK, và phần khắc phục gốc). Nó đã vượt quá điểm còn tra cứu được thoải mái. Nên tách `§2.7–2.16` thành `BENCHMARK_FINDINGS.vi.md` và để lại con trỏ — trước khi thêm mục thứ mười bảy.

---
