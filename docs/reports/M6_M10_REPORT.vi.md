# Báo cáo M6 phiên 2 → M10 (2026-09-29)

Agent: Claude (Sonnet 5.5) trong Cowork VM (2 core, 3,9 GB RAM, lệnh tối đa 180 s). Mọi con số trỏ tới file trong `evals/out/m<N>/` (luật 7). Bản này **chưa chốt**: thiếu số benchmark M10 (chờ duyệt tập tác vụ) và probe server thật (CP.8). Việc chủ repo cần làm: `docs/progress/CHECKPOINT_FINAL.md`.

## Tóm tắt
- Cả 5 phần (M6 phiên 2, M7, M9, M8, M10) đã merge `--no-ff` vào `main` trong worktree `tmp/run` (`822e3d6`); 58 commit sau `bb60f6e`. Mọi cổng cứng đạt. Không có nhánh nào bị revert hay `blocked`.
- **Chưa làm được, có lý do:** (1) benchmark công khai M10.5: tập tác vụ `bench_rich` chưa được duyệt nên harness từ chối chạy, chưa có con số nào; (2) probe server thật, ma trận client (chỉ 1 client), 6 kiểm tra tay GUI, CI Linux + Windows: đều thuộc checkpoint.
- **KPI mềm không đạt** (liệt kê đủ ở mục cuối): M7 hiệu năng trên VM 2 core, M8 thời gian render tab với 50 repo, M9 ma trận client (chỉ 1/≥3 client), M10 (chưa có số).

## Ledger
`docs/progress/RUN_LEDGER_M6_M10.md`: 22 dòng `done`, 2 `waiting-review` (P0.7 soạn tác vụ M10, M10.5 chạy benchmark). Không có `partial`, `blocked`, `skipped`.

## Nhánh / commit
`git log --oneline bb60f6e..main` (58 commit; danh sách trong `tmp/gitlog_m6_m10.txt` của worktree). Nhánh: `feat/m6s2-packet`, `feat/m7-incremental-index`, `feat/m9-client-compat`, `feat/m8-gui-offload`, `feat/m10-public-benchmark`, tất cả đã merge. Tag local: `m10-freeze` (`70aef25`). Không push, không tag phát hành (D7).

## Pha 0
- Baseline test (P0.2): 287 passed, 1 skipped (`test_hardware_probe.py:104`, ctypes Windows). Cuối lần chạy: 492 test thu thập, xanh, vẫn 1 skip (`tmp/pytest_*`; số skip không tăng).
- Baseline `tc-pinned` (git archive `ee5881e`, 319 file, 1.021 symbol, schema 2.3): `evals/out/m6/pinned_base_*.json`. @8192 (cổng hồi quy): A1final Acc@5 1,00; A2 Acc@5 0,90. @2048 khớp M6 phiên 1 (`edge_eval` 86/150, 0 FP); khác biệt: wire token TB −1 (1.874,8 vs 1.875,8), xếp hạng khác ở t18 (A1final) và t17, t18 (A2) vì index live của M6 phiên 1 có thêm file (`evals/out/m6/pinned_vs_m6s1_2048_diff.json`).
- Config thật (đọc được qua thư mục đã xin quyền, chỉ đọc): `output_mode = "structured"`, `default_view = "normal"`, `enable_extensions = true`, `enable_admin_tools` không có trong file; 18 repo đăng ký.
- Tập packet duyệt (D10) theo Phụ lục C: lint pass 20/20. Tập M10: repo `Textualize/rich` v15.0.0 (`6ac483c…`, MIT); `httpx` bị loại vì chỉ 60 file `.py` (<80). **Chưa duyệt** (`reviewed: false`).

## M6 phiên 2 — packet trong `inspect_symbol(view="full")`
Held-out (12 tác vụ), một lần chạy sau khi đóng băng hằng số (`29b99e6`: shares .30/.25/.25/.08/.12, K=15). `evals/out/m6/packet_{P0,P1,READ,CMP}_heldout_{2048,4096}.json`:

| Budget | Arm | sig_cov | ref_cov | body_cov | reach_ceiling | wire token TB | savings vs READ |
|---|---|---|---|---|---|---|---|
| 2048 | P0 (pre-M6) | 0 | 0,435 | 0 | 1,0 | 1.602 | 0,953 |
| 2048 | P1 | 0,725 | 0,824 | 0 | 1,0 | 1.740 | 0,951 |
| 4096 | P0 | 0 | 0,435 | 0 | 1,0 | 2.622 | 0,927 |
| 4096 | P1 | 0,958 | 1,000 | 0 | 1,0 | 2.932 | 0,923 |

READ = 37.194 token TB. Không tác vụ held-out nào P1 kém P0 về `ref_coverage`. `sig_cov` của P0 bằng 0 theo thiết kế (không có chữ ký neighbor), nên không dùng để so. `body_coverage` = 0 ở cả hai: theo thiết kế (Phụ lục C.2) packet chỉ mang thân của đích và chỉ số này chỉ báo cáo, nhưng cần biết là 0 chứ không phải "thấp". Không chạy lại held-out. Latency `inspect_symbol(full, 4096)` trên 20 đích: 9,84 ms/lần p50, 10,5 ms p95 (P0: 5,33 ms) — `latency_m6s2.json` (`inspect_symbol[full@4096]x20`, chia 20), sau khi memo hoá (22 → 9,8 ms, output giống từng byte).
KPI mềm: P1 ≥ P0 đạt; sig ≥ 0,60 đạt (0,958); ref ≥ 0,80 đạt (1,000); savings ≥ 0,70 đạt (0,923); latency p50 < 40 ms, p95 < 150 ms đạt. Cổng hồi quy identical @8192 và @2048 (`regression_gate_m6s2.json`).

## M7 — index incremental (schema 2.4)
`evals/out/m7/baseline_*.json` vs `after_*.json` (median 3 lần, VM 2 core):

| Repo | Trường hợp | Trước | Sau | Số lần `parse_source` |
|---|---|---|---|---|
| tc-pinned (137 file mã) | full | 1,988 s | 2,086 s | 137 → 137 |
| tc-pinned | no-op | 2,257 s | 0,418 s | 137 → **0** |
| tc-pinned | đổi 1 file | 2,219 s | 0,452 s | 137 → **1** |
| synthetic-1k | full | 8,284 s | 5,233 s | 1.050 → 1.050 |
| synthetic-1k | no-op | 9,639 s | 0,771 s | 1.050 → **0** |
| synthetic-1k | đổi 1 file | 9,522 s | 0,809 s | 1.050 → **1** |

RSS đỉnh cây tiến trình (full): tc-pinned 56,4 → 58,1 MB; syn1k 62,4 → 69,6 MB. `get_index_status` syn1k p50 97 ms → 3,6 ms (ledger M7.6). I1 (chuỗi 5 kịch bản + racy mtime) pass trên tc-pinned và syn1k (`equivalence_*.json`). Pool spawn chỉ khi ≥32 file và ≥1 MB (spawn ~0,8 s trên VM); M7.5 (edge theo phạm vi) **đã làm**, nhưng điều kiện của prompt (giai đoạn `edges` >30% lần đổi 1 file sau M7.1–M7.4) không được đo trước khi làm: ledger không ghi lý do, và ở baseline `edges` chỉ ~19% lần đổi 1 file trên syn1k (1,8 s/9,5 s) và ~3% trên tc-pinned (59 ms/2,2 s). Mức nhanh nhờ M7.5 (edges no-op 1.911 → 39 ms trên syn1k) là có thật, nhưng việc làm bước có điều kiện này là quyết định chưa được biện minh theo đúng luật của prompt. Cổng hồi quy identical.
KPI mềm: no-op ≤ 15% index full: tc-pinned **20%** (không đạt), syn1k 14,7% (đạt); đổi 1 file ≤ 25%: đạt cả hai (21,6% và 15,5%); index full nhanh hơn ≥ 40%: tc-pinned **−5% (không đạt, parse-bound trên 2 core)**, syn1k −37% (**không đạt**, <40%); RSS cây giảm ≥ 30%: **không đạt**; synthetic-5k ≥150 file/s: **không đo** (VM 2 core, 5k không index nổi trong một lệnh; đã ghi 1k); `get_index_status` p50 < 100 ms: đạt.

## M9 — tương thích client
`evals/out/m9/`: `schema_compat_default.json` 43 vấn đề (32 `anyOf` null, 5 `type` mảng, 4 property thiếu `type`, 1 `$defs`, 1 `$ref`) → `schema_compat_gemini_safe.json` **0**. Profile `default` giống hệt trước M9 (test snapshot `tests/fixtures/tool_schemas_default.json`). `get_tool_schema("search_source")` có `expand`, `expand_k`, `expand_hops`, `min_confidence`. `auto` không có client info → `text`. Cảnh báo injection nằm trong budget: `search_source@2048` số match TB 13,2 → 13,2 (`inj_budget_pre/post.json`); quét toàn repo: 11 dòng khớp, tất cả trong `tests/test_m9_client_compat.py` (câu mẫu của chính tính năng). `locate`: 1.024 token → 3,6 match TB (min 3); chọn nâng lên 2.048 → 9,4 match, File Acc@5 dev 0,90 giữ nguyên (`locate_probe.json`).
Ma trận client (`docs/CLIENT_MATRIX.md`): **1 client có dữ liệu** (Claude qua cầu `remote-devices`: thấy đủ JSON ở mode `structured`; server đó chạy code trước M9 nên chưa ghi `clientInfo.name`). Cầu Claude desktop lần kiểm 26/09: chỉ thấy dòng tóm tắt. `STRUCTURED_OK_CLIENTS = {claude-code}` là tên theo tài liệu, **chưa xác nhận**. KPI mềm "≥3 client": chưa đạt, chờ CP.4.

## M8 — GUI
`tests/test_gui_m8.py` (27 test) cộng test GUI cũ đã chỉnh: xanh. Có test monkeypatch xác nhận `list_repositories`, `get_storage_stats`, `collect_snapshot`, `get_server_config`, `detect_ai_hardware`, mọi `sqlite3.connect` và `Path.read_text` không chạy trên UI thread khi chuyển 6 tab và refresh tay; Huỷ giết cả cây (test tạo cháu); VACUUM không đổi sha256 của snapshot. `evals/out/m8/gui_perf.json` (offscreen, VM): first paint **399 ms** (<1,5 s đạt); **0** lần treo >100 ms khi chuyển tab và khi index synthetic-1k (7,0 s) qua tiến trình con (đạt); click → render xong với 50 repo: tasks 27 ms, cache 38, settings 30, agents 25, **dashboard 90 (tối đa 118)**, **repositories 126 (tối đa 127)** — KPI "<100 ms" **không đạt** với 2 tab đó (UI không đứng; thời gian là đọc status ở worker). 6 kiểm tra tay: chờ CP.5. Watchdog debug bằng `TOKEN_CONTEXT_GUI_DEBUG=1`. Cổng hồi quy identical (`regression_gate_m8.json`).

## M10
- Grammar mới: **Go** (D8: 0 file `unsupported` thuộc 6 ứng viên trong 18 snapshot thật, `real_unsupported_extensions.json`). tree-sitter-go 0.25.0, `PARSER_ARTIFACT_VERSION` 1 → 2. gorilla/mux @`db9d1d0` (BSD-3): 17 file `.go`, parse_error **0%** (<5%: đạt), 261 symbol; cạnh theo tên nên 253 resolved / 395 ambiguous (`go_grammar_gomux.json`) — đồ thị Go kém chính xác hơn Python.
- Version 0.2.0 từ một nguồn; wheel 0.2.0 clean-room pass (chạy `stdio_smoke` 2 mode, index file Go).
- C3 `--dry-run` liệt kê đủ 45 lần chạy (`c3_dry_run_rich.json`); không chạy thật (D6).
- Benchmark: harness `evals/bench_retrieval.py` (R0-grep, R0-grep@R2, R0-read, R1, R2, R3) có 11 test dữ liệu giả, đóng băng ở `m10-freeze` (`git diff m10-freeze -- src evals/bench_retrieval.py` rỗng). **Không có số**: tập `bench_rich` (30 định vị + 10 packet, đã kiểm gold trong index) chưa `reviewed: true`. Bảng R0-grep / R0-grep@R2 / R0-read / R1 / R2 / R3 kèm CI: **chờ duyệt**. `docs/BENCHMARK.md` mô tả protocol và KPI chốt trước; `docs/benchmark_sources.json` rỗng (không trích số đối thủ).
- Cổng hồi quy identical (`regression_gate_m10.json`).

## Cổng hồi quy, pytest, smoke, clean-room từng milestone
Cổng chung (`tc-pinned`, loc A1final/A2 held-out @8192 + `edge_eval`, so từng tác vụ với baseline P0.5): **identical ở M6, M7, M9, M8, M10** (`regression_gate_m6s2/m7/m9/m8/m10.json`). `pytest` (lõi + gui) xanh, `stdio_smoke` (structured và text từ M9) pass, wheel clean-room pass ở cả 5 milestone. Sửa giữa chừng: breaker của I1 không còn đặt ở lúc import (làm hỏng test khác khi chạy chung); NDJSON không phát `done` trung gian. CI GitHub chưa chạy (chưa push).

## Checkpoint
Việc của chủ repo: `docs/progress/CHECKPOINT_FINAL.md` (CP.1–CP.9). CP.8 (probe server thật) làm sau khi chủ repo báo xong.

## KPI mềm không đạt và lý do
1. M7 tc-pinned index full không nhanh hơn (−5%) và syn1k −37% (<40%): VM 2 core, parse chiếm >60% và pool spawn tốn ~0,8 s; đề xuất đo lại trên máy 8 core của chủ repo.
2. M7 RSS cây tiến trình không giảm 30% (tăng nhẹ ở full vì pool); no-op tc-pinned 20% (>15%); synthetic-5k chưa đo.
3. M8 render tab <100 ms không đạt cho Dashboard (~90–118 ms) và Repositories (~126 ms) với 50 repo.
4. M9 ma trận client: 1 client có dữ liệu (<3); tên client `claude-code` chưa xác nhận.
5. M10 KPI benchmark: chưa có số.

## Rủi ro còn lại
- Chưa có lần chạy CI Linux + Windows nào cho code mới; test GUI và spawn-pool cần xanh trên Windows.
- `index --all` trên 18 repo thật chưa chạy; lần index đầu sau nâng cấp parse lại mọi file (schema 2.4, parser artifact 2).
- Đồ thị Go theo tên, nhiều cạnh ambiguous; `body_coverage` của packet = 0 theo thiết kế; tập benchmark do một phiên soạn nên cần người duyệt độc lập.
- `tmp/dev` trong worktree là symlink tới đĩa VM (hỏng trên Windows; chỉ là dữ liệu nháp).

## Câu hỏi cho chủ repo
1. Ai duyệt `tmp/review/bench_rich.json` (chính bạn hay một phiên Claude khác)?
2. Có chạy C3 thật trên `bench-rich` (D6) không?
3. Sau CP.8, push `main` và tag `v0.2.0` (D7)?
