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
| 2026-09-30T04:47Z | M12.1 JS prototype & assigned methods | done | 7872ff8 | test_js_assigned_methods.py, edge_eval_m12_1.json | Trích xuất 8 mẫu prototype/assigned method JS/TS; PARSER_ARTIFACT_VERSION=3; same_class_split (conf 0.85); regression gate tc-pinned và rich khớp 100% |
| 2026-09-30T08:50Z | M12.2 C# ranking & doc comments | done | 3bd055d | test_csharp_ranking.py, csharp_grid.json, csharp_probe.json | Probe 3 tác vụ CsvHelper; H1 doc comment shifting vào member; H2 impl ranking (method > class > interface/attr); H3 inherit interface doc; H5 demote vendored; FTS_BUILDER_VERSION=2; PARSER_ARTIFACT_VERSION=4; CsvHelper SymRecall@10 tăng từ 0.3278 lên 0.5167 (+18.9% abs); hono/fastify dev R2 không suy giảm; cổng hồi quy tc-pinned và rich khớp 100% |
| 2026-09-30T15:15Z | M12.3 Edge ambiguity reduction (E1-E10) | done | 3a0d382 | edge_gold_csvhelper_m12_3.json, edge_gold_fastify_m12_3.json, edge_gold_hono_m12_3.json, edge_eval_m12_3.json, loc_A1final_m12_3.json, loc_A2_m12_3.json | E1-E10 (implicit this, overloads by arity/group, C# namespace scoping, local var types, field without this, instantiation new/object_creation, C# generic/conditional calls, CommonJS/ES6 bindings, TS property signature types); PARSER_ARTIFACT_VERSION=6, RESOLVER_VERSION=3; CsvHelper Edge Gold Recall 10% -> 40% (P 100%, 0 FP); Fastify Recall 0% -> 10% (P 100%, 0 FP); Hono Recall 28% -> 42.9%; cổng hồi quy tc-pinned (86/150, 0 FP) và rich khớp 100% (0 diff trên A1final, A2 @8192, edge_eval); stdio_smoke ok |
| 2026-09-30T15:20Z | M12.4 Python diagnostics | done | 109cb52 | python_partB_diag.json, bench_rich_summary.json | M12.4.1 chẩn đoán edge_eval phần B: resolver giải đúng 59/60 (98.3%) call site trong file; số báo 18/60 (30.0%) là do lệch số dòng (code drift) giữa gold M4 và snapshot tc-pinned (+9 dòng trong service.py, +15 server.py); M12.4.2 R2 < R1 rich: 2 tác vụ t26 (rank 5->8) và t29 (rank 4->9) do đồ thị kéo các file hub trung tâm (console.py, __init__.py), ghi nhận chờ chủ repo; M12.4.3 không có lỗi resolver, bảo toàn 100% byte Python |
| 2026-09-30T15:32Z | M12.5 C3 v2 Multi-Agent Harness & Adapters | done | 1021278 | test_c3_v2.py, test_c3_runner.py, run_c3_matrix.py dry-run | Adapter chuẩn hóa Claude Code, Gemini CLI, Codex; locate_v2 manifest (20 task counted trên 4 repo + 1 probe); grade_answer tự động từ fenced JSON; run_c3_matrix xáo trộn arm ngẫu nhiên tất định seed 20261001; cổng chấp nhận dry-run sinh đúng 120 run cho mỗi agent; git diff m12-base -- src không đổi thêm trong M12.5; 22 unit test pass |
| 2026-09-30T15:35Z | M12.6 Freeze, Guard check & Checkpoint | done | 70ce4bb | tag m12-freeze, evals/guard.py, CHECKPOINT_M12.md | Gắn tag m12-freeze; evals/guard.py kiểm tra role heldout pass; regression_gate tc-pinned 0 diff; tổng kết toàn diện CHECKPOINT_M12.md; hoàn tất Milestone M12 |


