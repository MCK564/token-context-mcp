# heldout-express author self-review

File: out/heldout_express.json (30 loc tasks t01..t30, 10 packet tasks p01..p10). Repo v5.2.1, commit dbac741a, MIT.

## Structural constraint that shaped the set
The OLD index of lib/ holds only 18 symbols: plain function declarations acceptParams, createETagGenerator,
parseExtendedQueryString, createApplication, logerror, tryRender, View, tryStat, defineGetter, sendfile, stringify and the
seven handlers nested in sendfile (onaborted, ondirectory, onerror, onend, onfile, onfinish, onstream). Every other
behaviour lives in `x.y = function` assignments (app.*, res.*, req.*, View.prototype.*, exports.*), and request getters
are declared through defineGetter(req, 'name', fn) calls, which are not symbols at all.
Consequence: t01..t25 use only indexed symbols (so some symbols are reused with different behaviours), t26..t30 are the
5 allowed `js_assigned_method` tasks (gold_pending_indexer on the assigned methods). Packet targets p08..p10 are assigned
methods too; most packet gold_context entries are assigned methods (pending).

## Symbols reused across tasks (different behaviour each time)
defineGetter t08/t22/t25; createApplication t04/t25/t30; sendfile t10/t18/t24; View t19/t20/t21; tryRender t06/t21;
stringify t09/t23; createETagGenerator t02/t23; parseExtendedQueryString t03/t22; logerror t05/t24; onerror t14 only.

## Doubtful / weaker tasks (reviewer please look first)
* t16, t17: one-statement nested handlers (`streaming = false` / `= true`), mirror images; distinguished only by the value.
* t14, t15: onerror vs onend are near twins (argument forwarded vs none); onfinish also ends in callback().
* t18: behaviour is a function expression INSIDE sendfile (`headers` listener); gold = sendfile, res.download is a weaker alternative.
* t19, t20: same gold (View constructor), two different code regions.
* t22, t24, t25: c_multi_file built from two indexed symbols whose relationship is a runtime flow, not a direct call
  (query accessor helper + parser; stream failure + default error hook; app back-reference + accessor helper).
* t21: app.render / View.render (assigned, not in gold) are also valid parts of the flow.
* p04, p05, p07: indexed target, all gold_context entries assigned methods (pending). p08..p10: pending target.

## Checks
* def_line of every indexed symbol equals the index span start (verify_bench_gold output), pending def_lines were checked by
  opening the file (assignment statement start line).
* The lint scripts in evals/ do NOT skip `gold_pending_indexer` entries. So: (a) real lint_tasks/verify_bench_gold were run on
  a scratch copy with pending gold removed (scratchpad/stripped.json); (b) the full file was linted through a thin wrapper
  that only adds the pending entries as existing symbols (existence check skipped, all other rules applied).
  Real lint_packet_tasks on the stripped copy fails only because <3 indexed context entries / no indexed cross-file entry remain
  after removing pending ones (p01..p07); with pending entries counted it is clean.
* Packet reach ceiling on the old index: 0/4 indexed context items (indexed symbols of this repo have no edges between them).
