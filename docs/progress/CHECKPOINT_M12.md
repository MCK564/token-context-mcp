# Checkpoint M12: Tổng Kết Toàn Diện Milestone M12

**Thời gian:** 2026-10-01 (Hoàn tất toàn bộ M12.0 – M12.6).  
**Branch:** `m12` (Khởi tạo từ `origin/main` @ `70d8e8f`).  
**Code Freeze Tag:** `m12-freeze` (Đã gắn thẻ tại HEAD).  
**Trạng thái tổng thể:** HOÀN THÀNH TOÀN BỘ CÁC MỤC TIÊU M12.

---

## 1. Tóm Tắt Thành Tựu Từng Hạng Mục (M12.0 – M12.6)

### M12.0: Cơ Sở, Tái Tạo Baseline & Held-out Guard
- **Worktree & Môi trường:** Worktree `tmp/m12` độc lập, tag `m12-base` tại `70d8e8f`.
- **Tái tạo baseline:** Khớp 100% từng tác vụ trên 4 repo dev (`rich`, `hono`, `fastify`, `CsvHelper`) và `tc-pinned` (A1final, A2, R0..R3).
- **Held-out Guard (Rule 17):** Hoàn thành `evals/guard.py`, tích hợp bảo vệ nghiêm ngặt chống rò rỉ held-out trước `m12-freeze`.
- **Brief 4 repo held-out:** Soạn thảo 4 tài liệu brief Phụ lục C & D (`starlette`, `zod`, `express`, `serilog`) tại `tmp/review/`.
- **Hỗ trợ `output_mode`:** Cập nhật GUI `settings_tab.py`, `README.md`, và `docs/CLIENT_MATRIX.md`.

### M12.1: Nhận Diện Prototype & Assigned Methods (JS/TS)
- Nhận diện 8 mẫu prototype/assigned method JavaScript/TypeScript (`PARSER_ARTIFACT_VERSION = 3`).
- Chiến lược `same_class_split` (confidence 0.85).
- Cổng hồi quy `tc-pinned` và `rich` khớp 100%.

### M12.2: C# Ranking & Doc Comments
- **Cải tiến:**
  - H1: Di chuyển doc comment từ file/class context vào member method.
  - H2: Xếp hạng triển khai ưu tiên (`method` có body > `class/struct` > `interface/attr`).
  - H3: Kế thừa doc comment từ interface sang implementation method.
  - H5: Hạ độ ưu tiên của thư viện vendored (`wwwroot/lib/`, `bulma/`).
- **Phiên bản:** `FTS_BUILDER_VERSION = 2`, `PARSER_ARTIFACT_VERSION = 4`.
- **Hiệu quả:** `CsvHelper` SymRecall@10 tăng mạnh từ **0.3278 lên 0.5167 (+18.9% tuyệt đối)**; `hono`/`fastify` dev R2 không bị suy giảm; cổng hồi quy `tc-pinned` và `rich` khớp 100%.

### M12.3: Giảm Độ Nhập Nhằng Cạnh Gọi (Edge Ambiguity Reduction E1–E10)
- **Cải tiến kỹ thuật:**
  - E1: Implicit `this` call resolution.
  - E2: Phân biệt overload theo số lượng tham số (arity).
  - E3: Nhận diện C# namespace scoping.
  - E4: Suy luận kiểu biến cục bộ (local variable type tracking).
  - E5: Truy cập trường/field không có từ khóa `this`.
  - E6: Khởi tạo đối tượng (`new` / `object_creation_expression`).
  - E7: Lệnh gọi C# generic và conditional (`?.`).
  - E8: Liên kết CommonJS (`require`) và ES6 destructuring imports.
  - E9: Chuẩn hóa đường dẫn tương đối (CommonJS/ES6 relative path resolution).
  - E10: Xử lý kiểu TypeScript property signature trong interface/type.
- **Phiên bản:** `PARSER_ARTIFACT_VERSION = 6`, `RESOLVER_VERSION = 3`.
- **Kết quả Dev Edge Gold:**
  - `CsvHelper`: Recall tăng từ **10.0% lên 40.0%** (Precision 100%, 0 False Positive).
  - `Fastify`: Recall tăng từ **0.0% lên 10.0%** (Precision 100%, 0 False Positive).
  - `Hono`: Recall tăng từ **28.6% lên 42.9%**.
- **Cổng hồi quy Rule 19:** `tc-pinned` (86/150, 0 FP) và `rich` khớp byte-for-byte 100% (0 diff trên `loc_A1final`, `loc_A2`, và `edge_eval`).

### M12.4: Chẩn Đoán Python
- **M12.4.1 (edge_eval Part B):** Chẩn đoán xác nhận resolver thực tế giải đúng **59/60 (98.3%)** call site trong mã nguồn `tc-pinned`. Tỷ lệ báo cáo trước đó 18/60 (30.0%) hoàn toàn do hiện tượng lệch số dòng (code drift +9 dòng ở `service.py`, +15 dòng ở `server.py`) giữa snapshot gold M4 và mã nguồn `tc-pinned`.
- **M12.4.2 (rich R2 < R1):** Xác định chính xác 2 tác vụ bị tụt hạng (`t26` rank 5 → 8; `t29` rank 4 → 9) do đồ thị mở rộng kéo các file hub trung tâm (`console.py`, `__init__.py`). Đã ghi nhận báo cáo kỹ thuật.
- **M12.4.3:** Không có lỗi resolver trong Python; bảo toàn 100% byte Python.

### M12.5: C3 v2 Multi-Agent Benchmark Harness & Adapters
- **Đa agent:** Bộ chuyển đổi chuẩn hóa (`evals/c3_adapters.py`) hỗ trợ Claude Code (`claude`), Gemini CLI (`gemini`), và Codex CLI (`codex`).
- **Bộ benchmark `locate_v2`:** `evals/c3/locate_v2_manifest.json` gồm 20 tác vụ counted (5 tác vụ/repo trên 4 ngôn ngữ: 1 keyword, 2 hidden dep, 2 multi-file) + 1 probe task.
- **Ma trận 120 run / agent:** 20 tác vụ × 3 arms (B0, B1, B2) × 2 seeds.
- **Xáo trộn ngẫu nhiên tất định:** Seed `20261001` xáo trộn thứ tự arm trên mỗi `(task, seed)` nhằm triệt tiêu thiên kiến warm-up/cache.
- **Chấm điểm tự động (`evals/c3_grade.py`):** Tự động bóc tách fenced JSON (`files`, `symbols`), chấm đạt theo tiêu chí chuẩn:
  - Nhóm a & b: Ít nhất 1 file gold trong top 3.
  - Nhóm c: Recall file gold trong top 5 ≥ 0.50.
- **Báo cáo & Phân tích (`evals/c3_report.py`):** Tính toán độ tiết kiệm token theo cặp (paired reductions) và khoảng tin cậy bootstrap CI95 (2,000 resamples).
- **Cổng chấp nhận:** Dry-run sinh đúng **120 run** cho cả 3 agent; `git diff m12-base -- src` không bị sửa đổi thêm trong M12.5; 22 unit test pass 100%.

### M12.6: Code Freeze & Nghiệm Thu
- **Gắn thẻ Code Freeze:** Tag `m12-freeze` đã tạo tại commit HEAD của `m12`.
- **Xác thực Guard:** `evals/guard.py` xác thực thành công:
  - Tag `m12-freeze` tồn tại.
  - `git diff m12-freeze -- src evals/bench_retrieval.py evals/edge_gold_eval.py` hoàn toàn sạch.
- **Cổng hồi quy Rule 19:** `regression_gate.py` vượt qua với 0 sai biệt.

---

## 2. Bảng Trạng Thái Của Bộ Tác Vụ Held-out (Rule 16 & 17)

Toàn bộ mã nguồn đã được đóng băng tại `m12-freeze`. Các bộ tác vụ held-out (split `test`) hiện được bảo toàn theo đúng Rule 16:
- Phiên Claude độc lập hoặc chủ repo có thể sử dụng các file brief tại `tmp/review/` để soạn thảo và nghiệm thu độc lập trên 4 repo held-out (`encode/starlette`, `colinhacks/zod`, `expressjs/express`, `serilog/serilog`).
- Mọi đánh giá held-out trong tương lai sẽ tuân thủ nghiêm ngặt bảo vệ `evals/guard.py`.

---

## 3. Kết Luận
Milestone M12 đã hoàn thành toàn diện tất cả các yêu cầu về mở rộng hỗ trợ ngôn ngữ (JS prototype, C# ranking, đa ngôn ngữ call resolution), chẩn đoán Python, hạ tầng benchmark đa agent C3 v2, và cổng kiểm soát hồi quy 100%.
