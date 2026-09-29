# Client matrix

What each MCP client does with the server's output, and the flags that suit it. Filled in from real checks only: a
row stays `not checked` until someone ran the check below in that client.

**The check (about 5 minutes per client).** Point the client at a `token-context serve` entry started with
`--output-mode structured`. Ask the model to call `get_index_status(repo_id="token-context")`.

- The model quotes the full JSON (`data.files_indexed`, `warnings`, …) → the client forwards `structuredContent` to the
  model → *Model sees payload = yes*, recommended flag `--output-mode structured` (or `auto` once its `clientInfo.name`
  is in `STRUCTURED_OK_CLIENTS` in `src/token_context_mcp/client_profile.py`).
- The model only sees a line like `repo_id=token-context freshness=fresh files_indexed=…` → *no*, recommended flag
  `--output-mode text`.

After the check, read the client name the server saw: `sqlite3 <config dir>/governance.sqlite "select client_name,
client_version, output_mode, schema_profile from server_heartbeats"`. Add that exact (lower-case) name to
`STRUCTURED_OK_CLIENTS` only for a *yes*.

Configuration commands: see `docs/SETUP.en.md` §5. The flags are added to the same `serve` args.

| Client | Model sees payload (structured)? | Recommended flags | Configuration | Checked on | Checked by |
|---|---|---|---|---|---|
| Claude (Cowork session, `remote-devices` bridge to this server) | **yes** — the model quotes the full JSON of `get_index_status(repo_id="token-context")` | `--output-mode structured` (default) | `docs/SETUP.en.md` §5.1-style `stdio` entry | 2026-09-29 (also 2026-09-27/28) | the Claude agent that ran M9 (D4). Note: that server ran pre-M9 code, so the `clientInfo.name` was not recorded |
| Claude desktop bridge (earlier check) | **no** — only the summary line reached the model | `--output-mode text` | as above | 2026-09-26 | M5 report |
| Claude Code (CLI / IDE) | not checked | start with `--output-mode structured`, then confirm | `docs/SETUP.en.md` §5.1 | — | owner, at the checkpoint |
| Antigravity | not checked | `--schema-profile gemini_safe` (also chosen by `auto`); `--output-mode text` until checked | `docs/SETUP.en.md` §5.5 | — | owner, at the checkpoint |
| VS Code Copilot Chat | not checked | `--output-mode text` until checked | `docs/SETUP.en.md` §5.3 | — | owner, at the checkpoint |
| Codex CLI | not checked | `--output-mode text` until checked | `docs/SETUP.en.md` §5.2 | — | owner, at the checkpoint |

`STRUCTURED_OK_CLIENTS` currently holds `claude-code`, the name that client is documented to send. The first row
above shows that *a* Claude client forwards `structuredContent`, but no heartbeat has yet recorded which name it
sent: confirm with the query above and correct the constant if the name differs. Until then `auto` picks `text`
for any other name, which is the safe direction.
