# heldout-starlette author self-review

Author session: read all of `starlette/**` (about 7k lines) and wrote 30 localisation tasks (10 a_keyword, 10 b_hidden_dep, 10 c_multi_file) plus 10 packet tasks. No token-context tool, ranking tool or evals bench script was run. Only lint_tasks, lint_packet_tasks and verify_bench_gold were run (existence checks). The reach figures printed by verify_bench_gold were ignored and no task was chosen or changed because of them.

## Facts
* The pinned commit is `2269e9a08c1edd3dfdea865710f40f84c857b623` (git HEAD and tag 1.7.0 agree). The instruction text quoted `...a09c...`, which is a typo. The file carries the verified SHA.
* `def_line` is the line of the `def`/`class` keyword (AST `lineno`), not the decorator line. For properties (`HTTPConnection.url_for`/`base_url`/`user`) it is the `def` line below `@property`.
* `is_async_callable` is `@overload`-ed in `_utils.py` (lines 57 and 61, implementation at 64). It appears only as packet `gold_context` (p04, p09), which stores path and name only, so no def_line ambiguity is stored.
* A script (builder) computed every def_line from the AST and asserted word count (6-25), chars (<= 190), single gold for a/b, >= 2 files for c, unique queries.

## Checks run
* lint_tasks: SUCCESS (30 tasks, 6 rules). lint_packet_tasks: SUCCESS (10 tasks). verify_bench_gold: missing_gold = 0.

## Design notes
* Gold is always in `starlette/**` (no tests, docs, benchmarks). 32 distinct source modules are touched by loc gold, packet targets or packet context.
* b_hidden_dep queries were written from behaviour (verified in the code), then checked against lint rule 3. Camel-case splitting was taken into account (for example "open" is forbidden for `OpenTelemetryMiddleware`, so the query says "wraps").
* c_multi_file gold lists the symbols that actually implement the flow (2 to 4 files each). Some selection of which helpers count is subjective (see doubtful ids).
* Packet tasks: target plus 6 context symbols each, at least one other file, `need` set to body only where the body contents matter. All `why` statements were written from a read of the code.

## Doubtful / subjective (for the reviewer)
* t08: `HTTPEndpoint.dispatch` is the best answer, but `HTTPEndpoint.method_not_allowed` is part of the described behaviour ("else 405").
* t10: `FloatConvertor.to_string` is unique because of float, NaN and inf; `IntegerConvertor.to_string` only shares the negative assert.
* t13, t19: large multi-behaviour methods; the query names several behaviours of the same method, so the gold is still single.
* t22, t23, t28, t29, t30 (c tasks): the set of helper symbols counted as gold is a judgement call (for example `HTTPConnection.base_url` in t23, `TestClient.wait_shutdown` left out of t28).
* t26: `WebSocket.send` is included because of the RESPONSE state; `Response.__call__` was left out.
* p04/p09: include `is_async_callable` (overloaded symbol, path + qualified name only).
