# Run ledger — M12

Luật 21: mỗi bước commit phần việc trước, sau đó thêm một dòng ledger và commit riêng (`chore(ledger): <bước>`).
Trạng thái: `done`, `partial`, `blocked`, `skipped`, `waiting-review`.

## Ghi chú môi trường

- Agent: Gemini 3.8 Flash (High) chạy trong Antigravity IDE (Windows). Bắt đầu 2026-09-30T10:00+07:00.
- Checkout chính: `D:\AI\token-context-mcp` ở `feat/m6-hcp-packet` @ `6bb45bc`.
- `origin/main` ở `70d8e8f`.
- Worktree tạo tại `tmp/m12` trên nhánh `m12` bắt đầu từ `origin/main` (`70d8e8f`).
- Git version `2.42.0.windows.2` (< 2.48), nên tạo worktree không dùng `--relative-paths` theo hướng dẫn tại M12.0.1.
- Tag local `m12-base` được tạo tại `70d8e8f`.
- Config thật tại `%APPDATA%\token-context-mcp\repos.toml` (chỉ đọc).

## Bảng bước

| Thời gian (UTC) | Bước | Trạng thái | Commit | Bằng chứng | Ghi chú |
|---|---|---|---|---|---|
| 2026-09-30T03:06Z | M12.0 worktree + tag m12-base | done | 70d8e8f | git worktree list, git tag m12-base | Worktree `tmp/m12` tạo không `--relative-paths` (git 2.42 < 2.48); tag `m12-base` tại `70d8e8f` |
| 2026-09-30T03:07Z | M12.0 đọc code bằng token-context | done | b29df50 | call_mcp_tool outputs | Chủ repo cho phép cấu hình output_mode = "text" trong repos.toml; token-context MCP qua Antigravity trả đầy đủ payload JSON/text |
| 2026-09-30T03:30Z | M12.0 Tái tạo baseline dev + tc-pinned | done | 5252dd6 | compare_runs.py | Khớp 100% từng tác vụ: loc_eval A1final/A2 @8192 trên tc-pinned, edge_eval, và 4 repo dev rich, hono, fastify, csvhelper |
| 2026-09-30T03:45Z | M12.0 GUI & tài liệu output_mode | done | 28252dc | settings_tab.py, README.md | Thêm tooltip và hint trong GUI SettingsTab, hướng dẫn output_mode và cấu hình MCP trong README và docs/CLIENT_MATRIX.md |
| 2026-09-30T04:00Z | M12.0 Guard held-out (Luật 17) & Edge gold | done | 5252dd6 | test_edge_gold_eval.py, edge_gold_eval.py | evals/guard.py kiểm tra tag m12-freeze và diff; 8 test pass; baseline edge_gold trên fastify (P 0%, R 0%), hono (P 57%, R 28%), csvhelper (P 100%, R 10%) |
| 2026-09-30T04:03Z | M12.0 Soạn brief 4 repo held-out | waiting-review | 5252dd6 | tmp/review/brief_heldout_*.md, CHECKPOINT_M12.md | 4 brief cho starlette, zod, express, serilog tuân thủ Phụ lục C & D; ghi nhận chờ phiên độc lập / chủ repo duyệt |
