# heldout-starlette review log

Reviewer: independent Claude session (not the author). Repo `starlette` at tag 1.7.0, commit 2269e9a08c1edd3dfdea865710f40f84c857b623 (git HEAD of `/home/claude/work/heldout/starlette` matches the file).
No token-context tool, ranking tool or bench script was used. Only source under `starlette/**` was read. Allowed checks run: lint_tasks, lint_packet_tasks, verify_bench_gold (existence only; the reach figures it prints were ignored and no decision depends on them).

## What was checked
* Read all of `starlette/**` (about 7k lines) and re-opened every gold symbol.
* Every `def_line` (30 loc tasks, all gold symbols, 10 packet targets) re-computed with the Python AST: 0 mismatches. All packet `gold_context` names resolve to a unique symbol except `is_async_callable` (three `@overload`/implementation entries at 57, 61, 64; stored with path + qualified name only, so no ambiguity).
* a_keyword and b_hidden_dep: grepped the tree for equally good alternatives for each answer (set_cookie/delete_cookie, MultiDict vs MutableHeaders `__setitem__`, Integer vs Float `to_string`, Host/Route/Mount `matches`, Config.get vs `_perform_cast`, HTTPEndpoint `dispatch` vs `method_not_allowed`, `Jinja2Templates._setup_env_defaults` vs the nested `url_for`, etc.). Each query has one clearly best symbol; no task needed rewriting.
* b_hidden_dep leakage: beyond the lint rule, checked by hand that no query contains the target name, any qualified-name part of 4+ characters (including camel and snake splits), the file stem, or an obvious inflection of them. Clean for t11 to t20.
* Packet tasks p01 to p10: each `why` re-read against the code. All statements are true. Targets and context count (6 each), at least one context entry in another file, `need` values reasonable.
* Spread: loc gold touches 25+ distinct modules (routing, requests, responses, datastructures, formparsers, staticfiles, testclient, websockets, endpoints, config, schemas, convertors, _utils, _exception_handler, concurrency, templating, applications, authentication, middleware cors/sessions/gzip/base/body_limit/opentelemetry/wsgi/errors/exceptions/authentication). Packet targets sit in 9 different modules. Reasonable for a 33-file repo.

## Author's doubtful ids, verdicts
* t08: keep. `HTTPEndpoint.dispatch` is the only symbol that does method lookup, HEAD fallback and the threadpool call. `method_not_allowed` only builds the 405.
* t10: keep. Float/NaN/inf asserts and the `%0.20f` formatting are unique to `FloatConvertor.to_string`.
* t13, t19: keep. Single method each, the query names behaviours of that one method; nothing else in the tree does them.
* t22: keep unchanged. Gold covers the 304 decision (`file_response`, `is_not_modified`), stat headers and the Range handling in `FileResponse.__call__`.
* t23: changed (see below).
* t26: keep unchanged. `WebSocket.send` (RESPONSE state) is a correct member; leaving out `Response.__call__` is fine because the wrapper `_wrap_websocket_denial_send` is the piece that renames the messages.
* t28, t29, t30: t28 changed (see below); t29 and t30 kept. In t30, `Request.stream` is a legitimate member because it is what replays `_body` for the cached request.
* p04/p09: keep. `is_async_callable` is overloaded but only path + qualified name is stored, and the `why` text is true.

## Changes (5 tasks, gold sets only; ids, groups, queries unchanged)
All additions keep the task in its group, keep `gold_files` equal to the set of files of `gold_symbols` (sorted), and keep c tasks at 2+ files. `def_line` taken from the AST.

| id | change | reason |
|----|--------|--------|
| t21 | added `Request.form` (requests.py:313) | public entry point of the described flow; thin wrapper over `_get_form`, an answer built on it is equally valid. Note updated. |
| t23 | added `Router.url_path_for` (routing.py:637) | `HTTPConnection.url_for` prefers `scope["router"]`, so `Router.url_path_for` is the reverse lookup actually reached before `Route.url_path_for`. Note updated. |
| t25 | added `HTTPConnection.auth` (requests.py:179) | query covers credentials and user; gold had only the `user` reader, so the credentials reader was missing. Note updated. |
| t27 | added `StreamingResponse.stream_response` (responses.py:250) | it is the loop that sends the start message, each chunk and the closing body; query starts with sending a streamed body. Note updated. |
| t28 | added `TestClient.wait_shutdown` (testclient.py:554) and `TestClient.__exit__` (testclient.py:527) | query names shutdown and leaving the context, gold had only the startup half. Note updated. |

Also: `review_note` in the JSON extended with one sentence about this review; `reviewed` left `false`.

## Post-edit checks
* lint_tasks: SUCCESS (30 tasks, 6 rules)
* lint_packet_tasks: SUCCESS (10 tasks)
* verify_bench_gold: missing_gold = 0 (loc_tasks 30, packet_tasks 10)
* AST re-check of all def_lines: 0 mismatches
* Counts: a_keyword 10, b_hidden_dep 10, c_multi_file 10, packet 10

## Remaining soft spots (not blocking)
* c tasks t22, t23, t24, t26, t30 are judgement-call gold sets (which helpers count). The central files and symbols are right; extra helper symbols could be argued either way.
* t17 has a nested `url_for` inside `_setup_env_defaults`; the query ("adds ... unless the user already defined one") points at the outer method, which is the stored gold.

VERDICT: approved
