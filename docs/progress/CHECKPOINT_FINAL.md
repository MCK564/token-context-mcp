# CHECKPOINT_FINAL — việc của chủ repo (M6 phiên 2 → M10 đã xong ở local)

Trạng thái: `main` = `822e3d6` trong worktree `D:\AI\token-context-mcp\tmp\run` (58 commit sau `bb60f6e`). Chưa push, chưa tag phát hành (D7).
Tag local `m10-freeze` = `70aef25`. Checkout chính vẫn ở `feat/m6-hcp-packet` @ `ee5881e`, chưa bị đụng.
Báo cáo: `docs/reports/M6_M10_REPORT.vi.md`. Ledger: `docs/progress/RUN_LEDGER_M6_M10.md`.

Lệnh dưới đây chạy trong PowerShell, từ `D:\AI\token-context-mcp`.

## CP.1 Đóng mọi client MCP
Claude desktop, VS Code, Antigravity, Claude Code, Codex.

## CP.2 Chuyển checkout chính sang code mới
Worktree tạo **không** có `--relative-paths` (git trong VM 2.34), nên sửa đường dẫn trước:
```
git worktree repair tmp/run
git checkout main
uv sync --extra dev --extra gui
```
Worktree đã `git switch --detach` nên `main` không còn bị giữ. `tmp/dev` trong worktree là symlink tới đĩa VM (`$HOME/dev-vm`) và sẽ hỏng trên Windows: đó là dữ liệu nháp, không cần.
Giữ `tmp/run` tới hết CP.8, sau đó `git worktree remove tmp/run --force` nếu muốn.

## CP.3 Re-index 18 repo thật lên schema 2.4
```
uv run python -m token_context_mcp index --all > tmp\index_all.json
```
Dán bảng tóm tắt (`repositories`, `indexed`, `failed`). Cả 18 repo phải lên schema 2.4; repo lỗi thì báo đúng lỗi.

## CP.4 Mở lại client, kiểm ma trận client
Theo `docs/CLIENT_MATRIX.md` (khoảng 5 phút/client): chạy `serve --output-mode structured`, bảo model gọi `get_index_status(repo_id="token-context")`; thấy JSON đầy đủ = `structured` dùng được. Sau đó đọc tên client server thấy:
```
sqlite3 %APPDATA%\token-context-mcp\governance.sqlite "select client_name,client_version,output_mode,schema_profile from server_heartbeats"
```
Điền bảng; thêm tên đúng vào `STRUCTURED_OK_CLIENTS` (`src/token_context_mcp/client_profile.py`) chỉ với client trả lời "yes". Hiện `claude-code` nằm trong đó nhưng **chưa xác nhận tên**. Antigravity: thêm `--schema-profile gemini_safe`.

## CP.5 GUI (6 mục)
`uv run token-context-gui`
- (a) mở app dưới 2 s, không đơ;
- (b) chuyển qua 6 tab mượt (Dashboard và Repositories mất ~100-130 ms mới hiện dữ liệu trên VM, nhưng giao diện không đứng);
- (c) re-index 1 repo: thấy tiến độ, bấm Huỷ được (không còn process `python` mồ côi trong Task Manager);
- (d) badge đúng (không còn `SCHEMA_OUTDATED` sau CP.3);
- (e) bảng "Running MCP Servers" thấy client vừa mở (cần server chạy bản mới);
- (f) VACUUM `memory.sqlite`: báo kết quả riêng từng DB.
Để đo treo giao diện: đặt `TOKEN_CONTEXT_GUI_DEBUG=1`, log ở `%TEMP%\token-context-gui-stalls.log`.

## CP.6 Duyệt tập tác vụ benchmark M10 (chưa duyệt → chưa có số benchmark)
- File cần duyệt (bản sao; sửa trực tiếp file này): `D:\AI\token-context-mcp\tmp\run\tmp\review\bench_rich.json`
- 30 tác vụ định vị + 10 tác vụ packet trên `Textualize/rich` v15.0.0 (commit `6ac483cbea39cab124dfd3483bba70ffafb71050`, MIT). Toàn bộ là tập test.
- Kiểm từng `gold_files` / `gold_symbols` / `gold_context`; nhóm `b_hidden_dep` không được lộ tên đích. Xong: đặt `"reviewed": true`, ghi `review_note`. Người duyệt: chủ repo, hoặc một phiên Claude **khác** phiên đã soạn (D3).
- Bằng chứng agent đã kiểm: `evals/out/m10/bench_rich_gold_verification.json`.

Chạy benchmark sau khi duyệt (tất định, vài phút; harness và `src/` đã đóng băng ở `m10-freeze`, không sửa):
```
git clone --branch v15.0.0 https://github.com/Textualize/rich tmp\bench\rich
git -C tmp\bench\rich rev-parse HEAD        # phải là 6ac483cbea39cab124dfd3483bba70ffafb71050
uv run python -m token_context_mcp register --config tmp\bench\repos.toml --repo-id bench-rich --root D:\AI\token-context-mcp\tmp\bench\rich
uv run python -m token_context_mcp index --config tmp\bench\repos.toml --repo-id bench-rich
uv run python evals\bench_retrieval.py --tasks tmp\run\tmp\review\bench_rich.json --config tmp\bench\repos.toml --name rich
git diff m10-freeze -- src evals/bench_retrieval.py    # phải rỗng
```
Kết quả: `evals/out/m10/bench_rich_<arm>.jsonl` và `bench_rich_summary.json`. Nếu tập tác vụ được sửa khi duyệt, chép bản đã duyệt vào `evals/tasks/bench_rich.json` và ghi diff vào ledger. Sau đó cập nhật mục "Status" của `docs/BENCHMARK.md`.

## CP.7 Báo "checkpoint xong"

## CP.8 Probe qua server thật (agent làm sau khi chủ repo báo xong CP.7)
- `get_index_status("token-context")`: schema 2.4, `fresh`, `commit_sha` có giá trị, `head_changed_since_index = false`.
- `get_index_status` của 3 repo khác (`invoice-recognition`, `logad-bench`, `task6-fusion`): schema 2.4, hết cảnh báo schema.
- `inspect_symbol("rank_symbols", view="full", budget_tokens=4096)`: packet đủ mục, response ≤ budget.
- `inspect_symbol("rank_symbols", view="minimal", budget_tokens=1024)`: `relationships` không rỗng, không có `get`/`append`, mọi cạnh qua bộ lọc E14.
- `get_tool_schema("search_source")`: schema không rỗng.
- `search_source(query="memory_get đọc dữ liệu ở đâu", profile="locate")`: ≥ 5 match, hoặc nêu lý do.
- Nếu tập tác vụ vừa được duyệt: chạy benchmark ở CP.6 trên nhánh mới, cập nhật `docs/BENCHMARK.md`, commit vào `main` (chỉ đổi `docs/` và `evals/out/`).
- Chốt `docs/reports/M6_M10_REPORT.vi.md` với số chính thức và số probe.

## CP.9 Quyết định của chủ repo sau khi đọc báo cáo
- D6: có chạy C3 thật trên `bench-rich` không (45 lần chạy, tốn tiền provider; `--dry-run` đã pass). Lệnh: `uv run python evals/run_c3_matrix.py --manifest evals/c3_prompts_rich.json --root tmp\bench\rich --task-success <true|false> ...` theo `evals/c3_protocol_rich.md`.
- D7: push và tag phát hành (chỉ tag khi báo cáo đã có số benchmark chính thức):
```
git push origin main
git tag -a v0.2.0 -m "token-context-mcp 0.2.0"
git push origin v0.2.0
```
Sau khi push: xem CI GitHub (Linux + Windows). CI chưa chạy lần nào cho M6–M10; test GUI và test spawn-pool cần thấy xanh trên Windows.
