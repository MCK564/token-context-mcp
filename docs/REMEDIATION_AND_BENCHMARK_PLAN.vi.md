# token-context-mcp — Thứ tự khắc phục, Thiết kế benchmark, Lộ trình cơ hội

**Ngày tạo:** 27/08/2026 · **Đối chiếu:** 0.1.0 @ `791ddce`
**Tài liệu đi kèm:** `PIPELINE_EXPLAINED.vi.md` (kiến trúc + SWOT)
**Mọi con số dưới đây đều đo trên máy này**, trên ba repository đã đăng ký với kích thước tăng dần.

---

## 0. Trạng thái "trước khi sửa", đã đo

Một repository thứ ba được index để kiểm tra xem các phát hiện SWOT có mở rộng theo quy mô không: `invoice-scanner` — 124 file Python, 882 KB, 667 symbol, 1.658 cạnh.

### 0.1 Khoản tiết kiệm là thật và **tăng theo kích thước repository**

| Repository | Symbol | Đường cơ sở (đọc hết `.py`) | Payload `repo_map`@1024 | **Tiết kiệm thật** |
|---|---|---|---|---|
| `token-context` | 134 | 20.370 tok | 7.803 tok | 2,6x |
| `task2-demo` | 202 | 68.259 tok | 8.849 tok | 7,7x |
| **`invoice-scanner`** | **667** | **220.576 tok** | **8.823 tok** | **25,0x** |

Đây là lập luận mạnh nhất cho công cụ và trước giờ chưa từng được đo: **payload gần như đứng yên (~8,8k) trong khi đường cơ sở tăng tuyến tính**, nên khoản tiết kiệm nhân lên theo quy mô repository. Ở mức 667 symbol, công cụ trả về đúng 1/25 so với cách đọc ngây thơ.

### 0.2 Lỗi kế toán **không** nhỏ đi theo quy mô

| Lời gọi | `estimated_tokens` khai báo | Payload thật | Chênh |
|---|---|---|---|
| `repo_map`@1024 | 1.024 | 8.823 | **8,6x** |
| `repo_map`@2048 | 2.046 | 14.349 | 7,0x |
| `symbol_context`@1024 | 47 | 1.510 | **32,1x** |
| `symbol_context`@2048 | 47 | 1.510 | **32,1x — giống hệt, `max_tokens` không ràng buộc** |
| `impact_slice`(d2,n75) | 6.149 | 7.480 | `truncated: false`, **trần server là 2.048** |

### 0.2b `max_result_tokens` không ràng buộc bất cứ thứ gì thực sự được phát ra

Chạy `evals/measure_context_cost.py` trên cả hai repository cho thấy trần bị vi phạm ở **3 trong 8 lời gọi**, và không chỉ bởi `impact_slice`:

| Lời gọi | Payload | Trần server | |
|---|---|---|---|
| `repo_map`@512 | 5.468 | 2.048 | vượt |
| `repo_map`@1024 | 8.823 | 2.048 | vượt |
| `repo_map`@2048 | 14.349 | 2.048 | vượt |

`_validate_budget` kiểm **tham số ngân sách được yêu cầu** so với `max_result_tokens`; **không có gì kiểm payload thực sự phát ra**. Nên một server cấu hình 2.048 token vẫn thường xuyên trả về 14.349, và `repo_map`@2048 qua được kiểm định đúng vì 2048 ≤ 2048. Trần này giới hạn thứ **được phép hỏi**, không bao giờ giới hạn thứ **được gửi đi** — khiến nó vô dụng như một cơ chế kiểm soát tài nguyên.

Điều này mở rộng W2: bản sửa không phải "cấp ngân sách cho `impact_slice`" mà là "buộc **mọi** phản hồi tôn trọng trần server".

### 0.3 Độ mơ hồ tăng theo quy mô — nguy cơ trong SWOT, nay đã xác nhận

| Repository | Symbol | Cạnh mơ hồ |
|---|---|---|
| `token-context` | 134 | 18 / 498 = **3,6%** |
| `task2-demo` | 202 | 56 / 690 = **8,1%** |
| `invoice-scanner` | 667 | 356 / 1.658 = **21,5%** |

Gấp năm lần số symbol, gấp sáu lần tỷ lệ mơ hồ. Phân giải từ vựng thoái hóa đúng ở nơi công cụ cần thiết nhất. Đây **không sửa được bằng tinh chỉnh** — nó là cái giá đã ghi nhận của backend từ vựng, và lộ trình xử lý nó đúng như vậy (§3, O4).

---

## 1. Thứ tự khắc phục

Nguyên tắc sắp xếp: **sửa thứ khiến bên gọi hành động dựa trên một con số sai, trước thứ chỉ tốn token.** Một ngân sách báo thiếu 32 lần là **lỗi tính đúng đắn** trong bộ hoạch định ngữ cảnh của agent, không phải một sự kém hiệu quả.

### P0 — Tính đúng đắn của hợp đồng *(~2 ngày)*

**W1. Nhồi theo mục được phát ra, không theo chuỗi render.**
`pack_by_budget` đo `f"{path}:{line} {signature}"` (20 tok) trong khi phong bì phát ra trọn `symbol_as_dict()` cộng `evidence` (158 tok). Đổi callback `render` trong `repo_map`, `file_skeleton` và `symbol_context` thành `lambda item: json.dumps(entry_as_emitted(item))`.
*Nghiệm thu:* với mọi công cụ và mọi ngân sách, `estimated_tokens ≤ payload_thật ≤ 1,15 × estimated_tokens`. Thêm test tuần tự hóa phản hồi rồi khẳng định giới hạn đó — lỗi này tồn tại vì **chưa bao giờ có ai so sánh hai con số ấy với nhau**.

**W2. Buộc mọi phản hồi tôn trọng `max_result_tokens`.**
`_validate_budget` kiểm tham số *được yêu cầu*, không bao giờ kiểm payload *được phát ra* (§0.2b), nên 3 trong 8 lời gọi đo được đã vượt trần — `repo_map` ở mọi mức ngân sách, cộng `impact_slice`, vốn còn không có tham số `max_tokens` nào và ràng buộc duy nhất (`max_nodes`) giới hạn node đồ thị chứ không giới hạn byte. Thêm `max_tokens` cho `impact_slice` (mặc định `min(2048, server.max_result_tokens)`), đưa symbol và cạnh của nó qua `pack_by_budget`, trả về `omitted_edge_count`, và thêm một assertion ở tầng phong bì rằng phản hồi đã tuần tự hóa nằm gọn trong trần.
*Nghiệm thu:* `evals/measure_context_cost.py` báo `calls_over_server_cap: 0` trên cả hai repository, bao gồm cả `impact_slice(depth=3, max_nodes=500)`.

**W3. Sửa `truncated` khi `requested_tokens == 0`.**
`_envelope` tính `(estimated > requested if requested else False)` — số 0 là falsy, nên `truncated` **luôn** là `False` theo cấu tạo với `impact_slice`, `find_symbols` và `status`. Thay bằng `truncated: bool | None` tường minh, trong đó `None` nghĩa là "không bị điều khiển bởi ngân sách" chứ không phải "không bỏ sót gì".
*Nghiệm thu:* không phản hồi nào báo `truncated: false` trong khi vẫn bỏ bớt nội dung.

W1–W3 là **một thay đổi mạch lạc**: phong bì không được nêu một con số mà nó không hề tính. Đó đúng là nguyên tắc gói này vốn đã áp dụng cho `completeness.basis`; chỉ là chưa từng áp dụng cho `budget`.

### P1 — Hiệu quả payload *(~1 ngày)*

**W4. `omitted_symbol_ids` tốn hơn cả ngân sách mà nó báo cáo.**
2.321 token ở `budget_tokens=1024` — gấp 2,3 lần toàn bộ yêu cầu — chỉ để liệt kê các chuỗi đầy đủ `python:path/to/file.py:Qualified.Name:hexdigest`. Thay bằng `omitted_count` cộng tối đa 10 id, đặt sau cờ `include_omitted_ids`.
*Dự kiến:* payload `repo_map`@1024 từ 8.823 → ~6.500.

**W5. Rút băm evidence còn 12 ký tự hex.**
1.633 token của SHA-256 dài 64 ký tự, mỗi symbol một cái. Mười hai ký tự vẫn đủ kháng va chạm cho việc phát hiện thay đổi trong phạm vi một repository. *Dự kiến:* −1.200 tok.

**W6. Bỏ byte offset khỏi symbol phát ra.**
`start_byte`, `end_byte`, `body_start_byte`, `body_end_byte` là tọa độ cắt lát nội bộ; bên gọi đã có `start_line`/`end_line`. Giữ chúng trong SQLite, bỏ khỏi đường truyền. *Dự kiến:* −800 tok.

**W7. Ràng buộc phần `edges` của `symbol_context`.**
Mảng `edges` được phát ra ngoài bộ nhồi, đó là lý do payload giống hệt nhau từng byte ở 1024 và 2048. Cho nó đi qua cùng một ngân sách.

Hiệu quả cộng gộp của P1, dự phóng: `repo_map`@1024 từ **8.823 → ~4.300 token**, đưa `invoice-scanner` từ 25,0x lên **~51x**. Khoản tiết kiệm đo được **tăng gần gấp đôi** mà không bỏ đi thứ gì bên gọi thực sự dùng.

### P2 — Các cạnh sắc trong vận hành *(~0,5 ngày)*

**W8. Kiểm độ tươi rẻ hơn.** `_freshness` băm lại **mọi** file đã index ở **mọi** lời gọi công cụ — 220 file với `invoice-scanner`, 4.559 với `video-lecturer`. Hãy so `mtime_ns` và `size` trước; chỉ băm khi lệch. `FileRecord` vốn đã lưu cả hai.

**W9. `cli.py` thiếu `__main__` guard.** `python -m token_context_mcp.cli register …` thoát mã 0 và không làm gì — không phân biệt được với thành công. Thêm guard, hoặc xóa hẳn đường module đó để chỉ còn `python -m token_context_mcp`.

**W10. `uv run token-context …` thất bại khi server đang chạy** — Windows khóa console script. Ghi `python -m token_context_mcp` làm entry point quản trị trong `INTEGRATION.md`.

**W11. Không có lệnh `unregister` / `update`.** Đăng ký lại thì ném lỗi (đúng), nên cách khôi phục duy nhất là sửa tay file TOML. Thêm cả hai, với `update` bắt buộc `--force`.

### P3 — Trung thực về độ mơ hồ *(~0,5 ngày)*

**W12. Đưa tỷ lệ mơ hồ ra đúng chỗ người ta hành động.** 21,5% trên `invoice-scanner` hiện chỉ hiện ra dưới dạng một chuỗi cảnh báo boolean. Hãy đặt `edge_precision: {ambiguous_rate, resolved_rate, basis}` vào phong bì của mọi công cụ trả về đồ thị, và báo tỷ lệ toàn repository trong `status`. Một bên gọi đang cân nhắc có tin một impact slice hay không cần **con số**, không phải tính từ.

---

## 2. Benchmark — ba phép so sánh, không phải một

Repository vốn đã có sẵn bộ harness đúng đắn (`benchmark-report`: giảm theo cặp, bootstrap tất định, delta không-thua-kém về chất lượng). Nó chưa bao giờ được cho ăn dữ liệu thật — `evals/sample-runs.jsonl` chỉ có hai dòng tổng hợp. Mục này đặc tả thứ cần đưa vào.

### 2.1 Đóng băng mục tiêu trước

`invoice-scanner` nặng 1,5 GB, trong đó **code chỉ 2,2 MB** (`weights/` 219 MB, `data/` 642 MB, `output/` 151 MB, `artifacts/` 371 MB). Chỉ copy phần code:

```powershell
robocopy D:\AI\invoice_scan\invoice-scanner D:\AI\bench\invoice-scanner-frozen /E `
  /XD .venv __pycache__ weights data output artifacts .git `
  /XF *.png *.zip *.jpg
cd D:\AI\token-context-mcp
.venv\Scripts\python.exe -m token_context_mcp register --repo-id bench-invoice --root D:/AI/bench/invoice-scanner-frozen
.venv\Scripts\python.exe -m token_context_mcp index --repo-id bench-invoice
```

**Đóng băng nó và không bao giờ sửa.** Một mục tiêu di động khiến trước/sau không so sánh được — và đó chính là nhiễu loạn làm cho phần lớn benchmark công cụ trở nên vô giá trị.

### 2.2 Năm tác vụ

Chọn sao cho mỗi tác vụ dùng một công cụ khác nhau và có đáp án kiểm tra được:

| id | Tác vụ | Công cụ chính | Tiêu chí thành công |
|---|---|---|---|
| `T1-orient` | "Liệt kê các module chính của repository này và mỗi module chịu trách nhiệm gì." | `repo_map` | Nêu đúng ≥5 module cấp cao có thật; không bịa |
| `T2-locate` | "Phần hậu xử lý OCR hóa đơn nằm ở đâu? Cho file và dòng." | `find_symbols` | Trích đúng path + dòng, sai lệch trong ±10 dòng |
| `T3-impact` | "Nếu đổi chữ ký của `<symbol>`, những chỗ gọi nào phải sửa?" | `impact_slice` | Nêu ≥1 caller thật; có nói rõ cạnh từ vựng là không đầy đủ |
| `T4-surface` | "Giao diện công khai của `<module>` là gì? Chỉ chữ ký." | `file_skeleton` | Đủ mọi def công khai, không có thân hàm, không có symbol riêng tư |
| `T5-trace` | "Truy vết một hóa đơn đi từ đầu vào tới kết quả được lưu." | `symbol_context` + `impact_slice` | Nêu ≥3 công đoạn theo đúng thứ tự |

Chấm điểm từng tác vụ **trước khi** nhìn số token. Một khoản thắng token trên câu trả lời sai không phải là thắng, và chấm sau khi đã thấy chi phí chính là cách người ta mắc lỗi đó.

### 2.3 So sánh C1 — công cụ có tiết kiệm không? *(tất định, chạy được ngay hôm nay)*

Chỉ đo chi phí ngữ cảnh, không cần nhà cung cấp, không tốn tiền, tái lập hoàn toàn:

- **Nhánh A0** — ngây thơ: số token để đọc mọi file mà tác vụ có khả năng chạm tới.
- **Nhánh A1** — token-context: tổng payload thật qua các lời gọi công cụ cần thiết.

Đã đo cho tác vụ định hướng: 220.576 so với 8.823 = **25,0x**. Mở rộng ra cả năm tác vụ. Đây là con số tiêu đề trung thực và **không cần agent nào cả**.

### 2.4 So sánh C2 — các bản sửa có giúp không? *(tất định, sau §1)*

Cùng một script, `0.1.0` đối chiếu `0.2.0`. Kỳ vọng: `repo_map`@1024 từ 8.823 → ~4.300; chênh của `symbol_context` từ 32,1x → ≤1,15x; `impact_slice` từ 7.480 → ≤2.048.

**Ghim cái này thành test hồi quy.** Lỗi kế toán tồn tại được là vì không có gì so sánh khai báo với thực tế; C2 chính là phép so sánh đó, chạy trong CI.

### 2.5 So sánh C3 — có tiết kiệm đầu-cuối không? *(cần agent; phần này bạn phải chạy)*

Không có `codex`, `antigravity`, `gemini` hay `aider` nào trên `PATH` của máy này, nên **tôi không thể thực thi hay đo nửa này**. Giao thức:

- **B0** — agent chỉ dùng công cụ file gốc của nó, tắt MCP.
- **B1** — cùng agent, cùng model, cùng prompt, bật MCP token-context, và system prompt khuyến nghị hạn chế đọc file trực tiếp.
- 5 tác vụ × 3 seed × 2 nhánh = **30 lượt chạy mỗi agent**. Giữ nguyên model và temperature xuyên suốt; biến duy nhất là sự sẵn có của công cụ.

Ghi mỗi lượt chạy một dòng JSONL, theo đúng schema mà `benchmark-report` đã kiểm:

```json
{"arm":"B1","task_id":"T2-locate","seed":1,"input_tokens":4120,"output_tokens":310,
 "total_tokens":4430,"latency_seconds":11.4,"task_success":true}
```

Rồi:

```powershell
.venv\Scripts\python.exe -m token_context_mcp benchmark-report `
  --input evals/invoice-runs.jsonl --output evals/reports/invoice-summary.json
```

**Dùng `input_tokens`/`output_tokens` do nhà cung cấp báo, tuyệt đối không dùng ước lượng cục bộ.** `estimate_tokens` là `bytes/4`; §0.2 chính là minh chứng cho điều xảy ra khi một ước lượng cục bộ bị tin như con số tính tiền.

Cách nối từng agent — tất cả đều nhận cùng một lệnh `stdio`; `.mcp.json.example` là mẫu:

| Agent | Vị trí cấu hình |
|---|---|
| Claude Code | `.mcp.json` ở gốc dự án, hoặc phạm vi người dùng |
| Codex CLI/IDE | mục MCP servers trong `config.toml` (`docs/INTEGRATION.md` §Codex) |
| Antigravity / khác | bất kỳ client nào khởi động được tiến trình `stdio` cục bộ với `uv` trên `PATH` |

Khởi động lại client sau khi đổi registry — registry chỉ được đọc lúc tiến trình khởi động.

### 2.6 C3 cho thấy được gì và không cho thấy được gì

Nó **có thể** cho thấy một agent có công cụ hoàn thành cùng những tác vụ đó với ít token hơn ở mức chất lượng không thua kém. Đó là khẳng định đáng đưa ra.

Nó **không thể** cho thấy một khoản tiết kiệm phổ quát. Năm tác vụ trên một repository với một model là **một điểm dữ liệu**, và bản viết trung thực phải nói vậy — đúng như `BENCHMARK.md` đã nói. Hãy dự trù C3 cho mức giảm **nhỏ hơn** 25x của C1: agent vẫn tốn token cho suy luận và đầu ra, còn công cụ chỉ nén được nửa phần truy xuất.

**Dự đoán, ghi lại ngay bây giờ để nó có thể sai:** C1 ≈ 25x cho tác vụ định hướng, C3 ≈ 1,5–3x trên tổng token cho cùng bộ tác vụ. Nếu C3 quay về gần 1,0x, nguyên nhân nhiều khả năng là **agent vẫn đọc file như thường** dù có công cụ — hãy kiểm log tool-call trước khi kết luận công cụ không có ích.

---

## 3. Lộ trình cơ hội — sau khi các bản sửa đã vào

Sắp theo *bằng chứng mở khóa được trên mỗi đơn vị công sức*, không theo mức hấp dẫn.

**O1 — Công bố các con số C1/C2. (1 ngày, sau §1)**
Khẳng định trung tâm của repository hiện chưa có bằng chứng. C1 và C2 tất định, không cần nhà cung cấp, và biến "được thiết kế để giảm việc bò quét" thành một tỷ lệ đã đo kèm phương pháp được nêu rõ. **Giá trị cao nhất trên mỗi giờ công trong toàn bộ lộ trình.** Đặt bảng đó vào `README.md` cùng với script đo đi kèm.

**O2 — Chạy C3 với một agent. (2–3 ngày, chủ yếu là thời gian của bạn)**
Biến khẳng định từ "gói ngữ cảnh nhỏ hơn" thành "ít token hơn cho cùng một tác vụ đã hoàn thành". Hãy làm **một** agent cho tử tế thay vì ba agent qua loa.

**O3 — Kiểm độ tươi rẻ hơn. (0,5 ngày)** = W8. Làm cho công cụ dùng được trên các repository lớn, nơi hiện tại nó băm lại hàng nghìn file mỗi lời gọi.

**O4 — Kích hoạt một backend ngữ nghĩa. (1–2 tuần)**
Đòn bẩy chất lượng lớn nhất, và là câu trả lời cho 21,5% mơ hồ ở §0.3. `SemanticBackendStatus` đã được thiết kế sẵn và cả hai stub đều nêu rõ điều kiện của mình: một language server đã ghim phiên bản, đưa vào sandbox, và kiểm định trên một kho ngữ liệu theo ngôn ngữ. Bắt đầu với Python và `pyright`, giữ `backend: "lexical"` làm dự phòng, và để `confidence` trở thành một phép đo thay vì hằng số 0,55/0,2. **Gác nó sau một cuộc đánh giá độ chính xác** — một backend ngữ nghĩa chưa kiểm định mà phân giải sai trong im lặng còn tệ hơn một backend từ vựng trung thực.

**O5 — Thêm ngôn ngữ. (0,5 ngày mỗi ngôn ngữ)**
Một mục `SUPPORTED_EXTENSIONS` cộng một khối `_NODE_KINDS`. Go và Rust trước — cả hai đều có grammar Tree-sitter sạch và loại node function/method/type rõ ràng.

**O6 — Phân phối. (1–2 ngày, chỉ sau O1)**
Gắn tag `v0.2.0`, publish lên PyPI, thêm một GitHub Actions chạy bộ test cộng phép hồi quy C2. `supply-chain/sbom.cdx.json` và `provenance.intoto.json` đã tồn tại và hiện là bản khởi tạo chưa ký — hãy ký chúng trong workflow phát hành. **Đừng phân phối trước O1:** một công cụ mà khẳng định tiêu đề là tiết kiệm token thì nên xuất xưởng kèm phép đo, không phải kèm một lời hứa.

**O7 — `unregister` / `update`. (0,5 ngày)** = W11. Nhỏ, và là thứ đầu tiên bất kỳ ai cũng vấp sau khi gõ sai một đường dẫn.

---

## 4. Thứ tự thực hiện

```
P0  W1-W3  tính đúng đắn hợp đồng    2 ngày  <- agent đang hoạch định ngữ cảnh sai tới 32 lần
 |
P1  W4-W7  hiệu quả payload          1 ngày  <- 25x -> ~51x, không mất nội dung dùng được
 |
C1 + C2    benchmark tất định        1 ngày  <- bằng chứng, và cũng là test hồi quy
 |
O1         công bố các con số        1 ngày
 |
P2  W8-W11 cạnh sắc vận hành       0,5 ngày
P3  W12    độ mơ hồ vào phong bì   0,5 ngày
 |
O2         C3 với một agent        2-3 ngày  (thời gian của bạn; máy này không có agent CLI)
 |
O6         tag, PyPI, CI            1-2 ngày
 |
O4         backend ngữ nghĩa        1-2 tuần (gác sau đánh giá độ chính xác)
O5         Go + Rust                 1 ngày
```

**Vì sao P0 đi trước tất cả.** Mục đích của công cụ là để một agent hoạch định ngữ cảnh của nó. Một agent đọc `budget.estimated_tokens = 47` rồi nhận về 1.510 token đã được đưa cho một con số sai **theo đúng chiều gây tràn**. Công bố một khoản tiết kiệm đo được khi lỗi đó còn nguyên tại chỗ đồng nghĩa với việc công bố một con số mà chính mã nguồn không thể bảo chứng.

**Vì sao C1/C2 đi trước C3.** Chúng tất định, không tốn gì, và lẽ ra đã bắt được lỗi kế toán ngay từ ngày đầu. C3 thuyết phục hơn nhưng đắt hơn nhiều và bị nhiễu bởi hành vi của agent. Hãy hạ cánh phần bằng chứng rẻ trước.

---

## 5. Các test hồi quy cần thêm cùng với bản sửa

Mỗi cái tương ứng một khuyết tật đã lọt lưới vì **không có gì so sánh hai thứ lẽ ra phải khớp nhau**:

- **`test_declared_budget_bounds_actual_payload`** — với mọi công cụ và mọi ngân sách, `estimated_tokens ≤ len(json.dumps(response))/4 ≤ 1,15 × estimated_tokens`. Bắt W1, W4–W7 và ngăn chúng quay lại.
- **`test_no_tool_exceeds_server_max_result_tokens`** — bao gồm cả `impact_slice` ở `depth=3, max_nodes=500`. Bắt W2.
- **`test_truncated_is_never_false_while_omitting`** — khẳng định trên mọi công cụ có bỏ bớt nội dung. Bắt W3.
- **`test_cli_module_entrypoint_acts_or_fails`** — `python -m token_context_mcp.cli register …` phải hoặc đăng ký được, hoặc thoát khác 0. Bắt W9.
- **`test_freshness_does_not_rehash_unchanged_files`** — đếm số lần gọi `sha256_file` qua hai lời gọi `status()` liên tiếp. Bắt W8 và ghim O3.
