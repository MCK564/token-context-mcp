# Run ledger — M6 phiên 2 → M10

Luật 16: mỗi bước commit phần việc trước, rồi thêm một dòng ledger và commit riêng (`chore(ledger): <bước>`).
Trạng thái: `done`, `partial`, `blocked`, `skipped`, `waiting-review`.

## Ghi chú môi trường (P0.1–P0.3)

- Agent: Claude (Sonnet 5.5) chạy trong Cowork VM (Phụ lục B). Bắt đầu 2026-09-29 11:5x giờ VN.
- Checkout chính `D:\AI\token-context-mcp` ở `feat/m6-hcp-packet` @ `ee5881e`; worktree `tmp/run` trên nhánh `feat/m6s2-packet`.
- **Worktree tạo KHÔNG có `--relative-paths`** (git trong VM là 2.34.1, cờ cần ≥ 2.48). Đường dẫn trong `.git/worktrees/run/gitdir` và `tmp/run/.git` là đường dẫn Linux tuyệt đối. **CP.2 phải chạy `git worktree repair tmp/run` trước khi dùng worktree trên Windows.**
- Mount trong VM đổi tên sau khi thêm thư mục thứ hai: repo nằm ở `$HOME/mnt/AI--token-context-mcp`; đã tạo symlink `$HOME/mnt/token-context-mcp -> AI--token-context-mcp` để đường dẫn đã ghi trong gitdir vẫn đúng. Config thật ở `$HOME/mnt/Roaming--token-context-mcp` (đã xin quyền thư mục `%APPDATA%\token-context-mcp`, chỉ đọc).
- Quyền xoá file trong thư mục repo: đã được cấp một lần.
- `.git/index.lock.stale-by-claude-20260928`: đã xoá.
- venv: `UV_PROJECT_ENVIRONMENT=$HOME/venv-run` (Python 3.12 do uv tải), `uv sync --extra dev --extra gui`. Script môi trường: `tmp/env.sh` (không commit).
- Thiếu `libEGL.so.1` trong VM (không có root): tải `libegl1` + `libglvnd0` bằng `apt-get download`, giải nén bằng `dpkg -x` vào `$HOME/extra-libs`, thêm vào `LD_LIBRARY_PATH` trong `tmp/env.sh`. Test GUI offscreen chạy được.
- VM: 2 core, ~3,9 GB RAM, lệnh tối đa 180 s. synthetic-5k sẽ không lập được trong một lệnh (P0.4 dùng 1k).
- Config thật, mục `[server]` (P0.3): `output_mode = "structured"`, `default_view = "normal"`, `enable_extensions = true`, `enable_admin_tools`: không có trong file (mặc định). 18 repo đăng ký.
- M10.2 (D8), dữ liệu từ 18 snapshot thật (đọc bản chép, không mở DB thật): **0 file** `unsupported` thuộc {go, rust, c/cpp, kotlin, php, ruby}. Đuôi `unsupported` nhiều nhất: `.json` 592, `.md` 372, `.jsonl` 202, `.yaml` 122, `.txt` 74. Không có dữ liệu → **chọn Go** theo D8. Bằng chứng: `evals/out/m10/real_unsupported_extensions.json`.

## Bảng bước

| Thời gian (UTC) | Bước | Trạng thái | Commit | Bằng chứng | Ghi chú |
|---|---|---|---|---|---|
| 2026-09-29T05:00Z | P0.1 worktree + ledger | done | ee5881e (base; không có commit việc) | — | worktree không dùng --relative-paths → CP.2 cần `git worktree repair tmp/run` |
| 2026-09-29T05:00Z | P0.2 môi trường | done | ee5881e | tmp/pytest_all.txt (không commit) | baseline VM: 287 passed, 1 skipped (test_hardware_probe.py:104 Windows ctypes); stdio_smoke exit 0; default_config_path = tmp/dev/repos.toml |
| 2026-09-29T05:00Z | P0.3 config thật (chỉ đọc) | done | 5a2f002 | evals/out/m10/real_unsupported_extensions.json | output_mode=structured, default_view=normal, enable_extensions=true; M10.2 → Go (0 file ứng viên) |
| 2026-09-29T05:10Z | P0.4 config dev + corpus ghim | done | 70e8de8 | tmp/dev (symlink → $HOME/dev-vm trên đĩa local VM) | tc-pinned=git archive ee5881e (319 file, 1021 symbol, schema 2.3); token-context (worktree); synthetic-1k (1051 file, 8000 symbol). Chuyển tmp/dev sang đĩa local vì index trên mount FUSE chậm ~10× (synthetic-1k 95 s vs 10 s). synthetic-5k: sinh được (5051 file) + đã đăng ký nhưng index >150 s nên chưa index; làm lại ở M7 |
| 2026-09-29T05:10Z | P0.5 baseline tc-pinned | done | 94e88c2 | evals/out/m6/pinned_base_*.json; pinned_vs_m6s1_2048_diff.json | @2048 khớp M6s1: A1final Acc@5 1.00, MRR 0.8892, SymRec@10 0.725; A2 Acc@5 0.90, MRR 0.8729; edge_eval 86/150, 0 FP; khác biệt: wire token TB -1 (1874.8 vs 1875.8), xếp hạng khác ở t18 (A1final) và t17,t18 (A2) vì index live có thêm file. Baseline gate @8192: A1final Acc@5 1.00 / A2 0.90 |
| 2026-09-29T05:10Z | P0.6 duyệt tập packet (D10) | done | 7558d7d | evals/tasks/packet_token_context.json | reviewed=true, review_note theo Phụ lục C.3; lint pass 20/20 trên tc-pinned |
| 2026-09-29T05:19Z | P0.7 soạn tác vụ M10 (rich v15.0.0) | waiting-review | d7ebf28 | evals/tasks/bench_rich.json, evals/c3_prompts_rich.json, evals/c3_protocol_rich.md, evals/out/m10/bench_rich_gold_verification.json | Chọn rich thay httpx (httpx chỉ 60 file .py < ngưỡng 80). Chỉ repo Python (JS tuỳ chọn: bỏ). 30 định vị + 10 packet (53 mục gold, trần 1-hop 1.00), reviewed=false. Bản duyệt: D:\AI\token-context-mcp\tmp\run\tmp\review\bench_rich.json (sha256 trùng bản trong repo lúc soạn). Từ đây không đọc rich cho tới m10-freeze (luật 20) |
| 2026-09-29T05:20Z | P0.8 đối chiếu hiện trạng | done | ee5881e | token-context find_symbols (index run_20260928T132135Z_303b15ba, fresh) | Đủ 7 symbol khớp bảng: _inspect_symbol_scoped workflows.py:80-312, _pack_to_budget service.py:1669-1688, _effective_budget 1550-1556, _symbol_packet 1724-1760, _compact_symbol_ref 1908-1911, _source_import_lines 1941-1947, symbol_relationships 1333-1399. Không có đổi tên/dời chỗ |
| 2026-09-29T05:58Z | M6.1-M6.3 packet + test | done | 370d174 | tests/test_context_packet.py (31), tests/fixtures/inspect_symbol_snapshots (40) | D9: full = data.packet, bỏ data.content/relationships; snapshot minimal/normal không đổi; full pytest 359 collected, pass, 1 skip |
| 2026-09-29T05:58Z | M6.4 tune dev + freeze + held-out | done | b92c2d7 | evals/out/m6/packet_tuning_dev_grid.json; packet_{P0,P1,READ,CMP}_heldout_{2048,4096}.json | freeze 29b99e6 (shares C: .30/.25/.25/.08/.12, K=15) trước held-out; held-out chạy 1 lần: ref P1 1.000 vs P0 0.435 @4096, 0.824 vs 0.435 @2048; sig 0.958/0.725; KPI mềm P1>=P0 đạt |
| 2026-09-29T05:58Z | M6 gate: hồi quy + smoke + clean-room + latency | done | c7b9168 | evals/out/m6/regression_gate_m6s2.json; latency_m6s2.json | Cổng hồi quy identical @8192 và @2048; stdio_smoke 0; wheel 0.1.0 clean-room pass; latency full@4096 9.8ms/lần vs P0 5.3ms (sau memo hoá 22ms->9.8ms, output byte-identical) |
| 2026-09-29T06:07Z | M7.0 đo baseline | done | 04f6da8 | evals/out/m7/baseline_{tc_pinned,synthetic_1k}.json | tc-pinned full 1.99s (parse 1252ms 63%, write 406ms), noop 2.26s, one 2.22s, parse_source_calls 137 mọi trường hợp; RSS cây 56 MB, tracemalloc 28 MB. syn1k full 8.28s (roles 2646ms, parse 2259ms, edges 1811ms, write 737ms), noop 9.64s, one 9.52s, 1050 parse_source/lần; RSS 62 MB, tracemalloc 44.9 MB. Ưu tiên: roles O(n²) (syn1k), parse, edges, write |
