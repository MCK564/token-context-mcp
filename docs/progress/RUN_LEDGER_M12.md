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
