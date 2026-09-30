# Checkpoint M12: Phiên Làm Việc và Soạn Thảo Held-out

Cập nhật: 2026-09-30T10:52+07:00
Trạng thái tổng thể: M12.0 hoàn tất các hạng mục cơ sở, kiểm tra Rule 17 pass, baseline edge gold hoàn thành; các bộ tác vụ held-out đã lập brief và ghi nhận `waiting-review`.

## 1. Danh sách Brief Soạn Thảo Held-out (Phụ lục C & D)

Chủ repo hoặc phiên Claude độc lập có thể sử dụng các file brief sau để soạn thảo và nghiệm thu các bộ tác vụ held-out (split `test`), tuyệt đối không dùng công cụ retrieval:

| Ngôn ngữ | Repository đề xuất | File Brief tuyệt đối | Trạng thái |
|---|---|---|---|
| Python | `encode/starlette` | `D:\AI\token-context-mcp\tmp\m12\tmp\review\brief_heldout_starlette.md` | `waiting-review` |
| TypeScript | `colinhacks/zod` | `D:\AI\token-context-mcp\tmp\m12\tmp\review\brief_heldout_zod.md` | `waiting-review` |
| JavaScript | `expressjs/express` | `D:\AI\token-context-mcp\tmp\m12\tmp\review\brief_heldout_express.md` | `waiting-review` |
| C# | `serilog/serilog` | `D:\AI\token-context-mcp\tmp\m12\tmp\review\brief_heldout_serilog.md` | `waiting-review` |

## 2. Kết quả nghiệm thu M12.0 Baseline

- **Môi trường & Git:** Worktree `tmp/m12` sạch, tag `m12-base` tại `70d8e8f`.
- **Tái tạo baseline (M12.0.4):** Khớp 100% từng tác vụ trên 4 repo dev (`rich`, `hono`, `fastify`, `CsvHelper`) và `tc-pinned` (A1final, A2, R0..R3).
- **Guard held-out (Rule 17):** Hoàn thành `evals/guard.py`, tích hợp vào `bench_retrieval.py` và `edge_gold_eval.py`, kiểm thử tự động pass (`tests/test_edge_gold_eval.py`, `tests/test_bench_retrieval.py`).
- **Edge gold baseline (M12.0.9):**
  - `bench-fastify`: 30 sites (10 internal), Precision@0.6 = 0.0% (0/1), Recall = 0.0% (0/10) [Do `m12-base` chưa nhận diện prototype/assigned method].
  - `bench-hono`: 30 sites (14 internal), Precision@0.6 = 57.14% (4/7), Recall = 28.57% (4/14).
  - `bench-csvhelper`: 30 sites (10 internal), Precision@0.6 = 100.0% (1/1), Recall = 10.0% (1/10) [Do receiver resolution có 90% ambiguous].
- **Hỗ trợ `output_mode`:** Đã cập nhật GUI `settings_tab.py`, `README.md`, và `docs/CLIENT_MATRIX.md` (xác nhận thực nghiệm Antigravity dùng `--output-mode text`).
