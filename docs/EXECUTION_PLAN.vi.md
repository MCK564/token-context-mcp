# Kế hoạch thực thi — các hạng mục còn mở

**Ngày:** 28/08/2026 · **Bản EN:** `EXECUTION_PLAN.en.md`
**Phân tích và cơ sở đo đạc:** `REMEDIATION_AND_BENCHMARK_PLAN.vi.md` §2.7–2.16. Tài liệu này **chỉ có việc cần làm**, không lặp lại lập luận.

## Trạng thái thực hiện (28/08/2026)

| Hạng mục | Trạng thái | Bằng chứng |
|---|---|---|
| X1 trừ envelope | **xong** | Báo cáo C1 trên wire: cả hai repository có 0 lời gọi vượt trần 4.096 token |
| X8 tách tài liệu | **xong** | `BENCHMARK_FINDINGS.{en,vi}.md` chứa các mục 2.7–2.16 |
| X2 tập nhãn có query | **xong** | `evals/relevance/query_invoice_scanner.json` và báo cáo baseline |
| X4 giao thức C3 | **xong** | `evals/c3_protocol.md`, đã chốt ba nhánh và chỉ số nội dung chính |
| X3 seed-biased ranking | **xong** | Năm query cho danh sách khác nhau; recall thiết yếu trung bình 0,667; orientation 0,833 và 0 nhiễu |
| X5 hồ sơ ngân sách | **xong** | Bốn profile có thể khám phá; đã có test tương đương với tham số truyền tay |
| X7 mặc định theo quy mô | **xong** | status thật: invoice-scanner 667 symbol, token-context 273 symbol, giá trị suy dẫn khác nhau |
| X6 ma trận C3 đầy đủ | **chưa xong** | Protocol và runner fail-fast đã sẵn sàng; chưa chạy đủ 45 session provider |

Dòng X6 cố ý không ghi là hoàn tất: các dòng pilot cũ không thể thay cho ma trận
5 task × 3 seed đã chốt trước.

## Trạng thái đã xác minh (28/08/2026)

| Chuỗi | Trạng thái |
|---|---|
| W1–W3 hợp đồng ngân sách | xong |
| R-P0 trung thực về cắt cụt | **xong** — `node_limit_reached` tính từ traversal, `nodes_visited` phơi ra |
| R-P1 phục vụ imports | xong — `get_module_dependents` |
| R-P2 tìm toàn văn | xong — `search_source` + FTS5 |
| R-P3 phân giải theo phạm vi | **có tác dụng** — mơ hồ 22,0% → 15,0% (`invoice-scanner`) |
| E-P0 entry rẻ | xong — 107 → 24 token/entry, 42 symbol @1024 |
| E-P1 diệt N+1 | xong — 1.077 → 3 truy vấn, 13,87s → 0,164s |
| E-P5 giữ ranking cố định | xong (quyết định), nay **được thay thế** bởi RK |
| RK-P0…P3, P5 | xong — recall 0,167 → 0,833; nhiễu 3 → 0; nDCG 0,4235 → 0,7742 |

Danh sách còn mở lịch sử bên dưới được viết trước khi triển khai chuỗi X;
bảng trạng thái thực hiện ở trên là nguồn chuẩn cho plan này.

---

## X1 — Trừ sẵn envelope *(~30 phút)*

Đóng E-P2. Overshoot là **hằng số 56–75 token** (dòng summary `content` + khung `CallToolResult`), không co giãn theo payload.

- `service.py`: thêm hằng số `ENVELOPE_RESERVE_TOKENS = 96`; trừ khỏi ngân sách hiệu dụng **trước** khi nhồi, ở mọi tool có budget.
- Ghi `envelope_reserve` vào `budget` của phản hồi để bên gọi thấy được phần đã trừ.

**Nghiệm thu:** `measure_context_cost.py` báo `calls_over_server_cap: 0` trên cả hai repository, bao gồm `search_source(ocr)@4096`.

**Lưu ý:** ở ngân sách 512 overshoot chiếm 15,2%, nên bước này là **điều kiện tiên quyết** của X5 (profile `locate` ở 512), không phải tùy chọn.

---

## X2 — Tập nhãn có query *(~0,5 ngày)*

Mở khóa X3. Ground truth lấy từ **20 file test đặt tên theo chủ đề** — độc lập với mọi agent và mọi ranking.

Tạo `evals/relevance/query_invoice_scanner.json`, 5–6 chủ đề:

| Chủ đề | Query | Nguồn grade-3 |
|---|---|---|
| OCR | `"ocr text recognition"` | import của `tests/unit/test_s8_ocr.py` |
| Trích xuất trường | `"field extraction amount date"` | `test_fields.py` |
| Registry | `"frontend registry selection"` | `test_registry.py` |
| Render | `"render display ocr input"` | `test_s7_render.py` |
| Hình học | `"page detection corners geometry"` | `test_frontend_geom.py` |

Quy tắc chấm:

- **grade 3** — symbol file test **import trực tiếp**. Đội ngũ đã tuyên bố chúng trung tâm bằng cách import để kiểm thử.
- **grade 2** — symbol định nghĩa trong các module đó nhưng test không gọi trực tiếp.
- **grade 0** — nhiễu lấy từ **chủ đề khác**, cộng `rgb` và `merge`. **Đây là nửa quyết định**: ranking theo bậc toàn cục trả về cùng một top-10 cho mọi query, và nhiễu chéo chủ đề chính là thứ phơi ra điều đó.

Ghi thẳng vào file: import báo *cái gì được test*, không phải *cái gì liên quan tới câu hỏi*; symbol quan trọng không có test sẽ bị chấm thấp oan. Tập này so **ranking A với B trên cùng query**, không tuyên bố độ phủ tuyệt đối.

**Nghiệm thu:** `rank_eval.py` chạy được trên tập mới; ghi baseline ra `evals/reports/rank-query-before.json`.

---

## X3 — RK-P4 seed-biased ranking *(~1 ngày, cần X2)*

- Khi lời gọi có `query` hoặc `symbol_id`, chấm bằng random walk thiên vị seed thay vì bậc toàn cục.
- Giữ nguyên đường bậc toàn cục cho lời gọi không query.
- Ghi `rank_mode: "global" | "seed_biased"` vào phản hồi.

**Nghiệm thu:** trên `query_invoice_scanner.json`, so với `rank-query-before.json`:
- top-10 **phải khác nhau giữa các query** (đường cơ sở toàn cục cho kết quả giống hệt — đó là phép thử chính);
- `essential_recall` tăng ở ≥4 trên 5 chủ đề;
- không hồi quy trên `orientation_invoice_scanner.json` (recall ≥0,833, nhiễu 0).

---

## X4 — Chốt ba quyết định trước C3 *(~0,5 ngày, không phải code)*

Ba việc này phải chốt **trước** khi chạy, vì đổi sau sẽ vỡ tính ghép cặp.

**1. Số nhánh.** RK-P5 thêm mcp-first có giới hạn → hiện có ba ứng viên:

```
B0 native-only  |  B1 hybrid  |  B2 mcp-first (bounded)
```

`5 task × 3 seed × 3 arm = 45 lượt` ≈ 2–2,5 giờ. Chọn 2 hay 3 và ghi lại lựa chọn.

**2. Chỉ số chính.** `total_tokens` **không** được làm chỉ số chính — pilot cho thấy 2.558 token nội dung trên 120.832 cached input, tức nội dung chiếm 2% và `total_tokens` đang đo độ dài hội thoại.

| Chỉ số | Vai trò |
|---|---|
| `retrieved_content_estimated_tokens` | **chính** |
| `uncached_input_tokens` | chi phí cận biên thật |
| `total_tokens` | phụ, chi phối bởi số lượt |

**3. Bộ chấm.** Chốt cách chấm T1–T5 **trước khi nhìn số token**. T1 nay tự chấm được: dùng `orientation_invoice_scanner.json` chấm các symbol mà báo cáo nêu ra, bằng `essential_recall` và `noise_in_top_k`. Bốn task còn lại cần tiêu chí đạt/không đạt viết ra thành văn bản, chốt trước.

**Nghiệm thu:** một file `evals/c3_protocol.md` ghi ba quyết định trên, commit **trước** lượt chạy đầu tiên.

---

## X5 — E-P3 hồ sơ ngân sách theo tác vụ *(~1 ngày, cần X1)*

Khối `[budget_profiles]` trong config; tham số tường minh luôn thắng hồ sơ.

```toml
[budget_profiles.locate]   # "X ở đâu"
tools = ["find_symbols", "search_source"]
budget_tokens = 1024
limit = 30

[budget_profiles.orient]   # "repo có gì"
tools = ["repo_map"]
budget_tokens = 4096
format = "compact"

[budget_profiles.impact]   # "sửa X hỏng gì"
tools = ["impact_slice", "get_module_dependents"]
budget_tokens = 4096
max_nodes = 200
depth = 2

[budget_profiles.read]     # "cho xem file/symbol"
tools = ["file_skeleton", "symbol_context"]
budget_tokens = 2048
include_body = true
```

- Thêm tham số `profile` tùy chọn cho mỗi tool.
- `list_repositories` trả về tên hồ sơ và ngân sách, để agent **chọn** thay vì **bịa** — cùng một lỗi khám phá như W13, áp vào ngân sách.
- **Không** cho hồ sơ tự điều chỉnh theo kích thước index ở bước này. Phát hành hồ sơ cố định trước, đo xem mỗi loại tác vụ chọn cái nào, rồi mới cân nhắc suy dẫn.

**Nghiệm thu:** gọi kèm `profile="locate"` cho kết quả giống hệt việc truyền tay đúng bộ tham số đó; `list_repositories` liệt kê hồ sơ.

---

## X6 — Ma trận C3 đầy đủ *(2–3 giờ chạy, cần X4)*

Chạy theo giao thức đã chốt ở X4. Runner, `--max-mcp-calls` và fail-fast đều đã sẵn sàng — **không có chặn kỹ thuật nào**.

**Nghiệm thu:** `benchmark-report` sinh summary với `paired_count` đầy đủ; báo cáo nêu rõ chỉ số chính; mọi khẳng định về tiết kiệm đều kèm khoảng tin cậy và số lượng mẫu.

---

## X7 — E-P4 mặc định theo quy mô *(~0,5 ngày, tùy chọn)*

- `max_edges_per_symbol`: suy từ độ dài thân symbol trung vị thay vì cố định 100.
- Trần `limit`: co giãn theo số symbol đã index, sàn 30, trần 100.
- Mặc định `max_nodes` của `impact_slice`: đo lúc index, lưu vào manifest.
- Ghi mọi giá trị suy dẫn vào manifest và phơi qua `get_index_status`.

**Nghiệm thu:** hai repository chênh lệch quy mô nhận mặc định khác nhau, cả hai nhìn thấy được.

---

## X8 — Tách tài liệu *(~30 phút)*

`REMEDIATION_AND_BENCHMARK_PLAN.{vi,en}.md` đã 1.149 dòng, 16 mục con, 4 chuỗi công việc.

- Chuyển `§2.7–2.16` sang `BENCHMARK_FINDINGS.{vi,en}.md`.
- Để lại con trỏ ở file gốc.
- Giữ `§0–2.6` (khắc phục gốc) và `§3–5` (lộ trình, thứ tự, test hồi quy) tại chỗ.

---

## Thứ tự

```
X1  trừ sẵn envelope       30 phút   ← độc lập, làm ngay
X8  tách tài liệu          30 phút   ← độc lập, làm ngay
 |
X2  tập nhãn có query      0,5 ngày
X4  chốt giao thức C3      0,5 ngày  ← song song được với X2
 |
X3  seed-biased ranking      1 ngày  (cần X2)
X5  hồ sơ ngân sách          1 ngày  (cần X1, song song được với X3)
 |
X6  ma trận C3             2–3 giờ   (cần X4)
 |
X7  mặc định theo quy mô   0,5 ngày  (tùy chọn)
```

Tổng nhánh chính: **~3,5 ngày** cộng 2–3 giờ chạy.

**Hai quy tắc dừng:**

- **Đừng chạy X6 trước khi X4 chốt xong chỉ số chính.** Giữ `total_tokens` làm chính thì 45 lượt sẽ cho kết quả bị chi phối bởi số lượt hội thoại — đúng thứ ba pilot trước đã tạo ra, chỉ nhiều gấp mười lăm lần.
- **Đừng triển khai X3 trước khi X2 xong.** Triển khai seed-biased ranking mà không đo được chính là sai lầm đã tạo ra trọng số `8.0`/`12.0` ban đầu.
