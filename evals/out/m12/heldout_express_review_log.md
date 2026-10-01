# heldout-express review log (reviewer session, independent of author)

Repo v5.2.1, commit dbac741a. Method: read all six lib/ files completely, opened every gold def_line, grepped call sites of every
indexed helper, judged for each task whether an assigned method (res.send, res.json, app.use, app.set, app.render, View.prototype.*, ...)
would be an equally good answer. No token-context tool, no ranking script, source code only. Lint scripts used as provided.

## Changes made (9 edits on 7 tasks; packet tasks untouched)

| id | change | why |
|----|--------|-----|
| t12 | query rewritten (no longer names the error-code literal) | b_hidden_dep: the literal contained the substring "aborted" = part of the target name onaborted; lint is token based so it did not catch it. New wording keeps the behaviour (fresh error, connection-level code, at most once) and still separates it from ondirectory/onerror/onfinish. |
| t16 | query rewritten | b_hidden_dep: plain word "file" is the second half of the name onfile ("located a file"). Replaced by a paraphrase of the event; value (false) still decides vs t17. |
| t17 | query rewritten | b_hidden_dep: "streaming" contains "stream" (part of onstream). Replaced by "in-flight body delivery"; value (true) and "begun piping" decide vs t16. |
| t21 | query rewritten | alternative-answer risk: app.render (assigned, application.js) both builds the View and calls tryRender, and app.engine "maps extension to engine handler" also fit the old wording. New wording pins View to "loads the engine module for an extension and resolves the file" and tryRender to the sync-exception guard. |
| t23 | query + note rewritten | alternative-answer risk: res.json (calls stringify) + res.send (Buffer conversion + etag) are a complete, equally plausible answer for the flow wording "JSON body preparation ... then derive an entity tag from the resulting buffer"; compileETag also matched "strong or weak". New wording describes only what stringify and the generator returned by createETagGenerator do (unicode escaping of < > &; buffering string bodies with an encoding). Not widened with pending gold because that would push a 6th task onto assigned methods. |
| t24 | query rewritten | alternative-answer risk: res.sendFile's callback also "receives file transfer failures". Wording now says "listeners that hand ... failures to a one-shot completion callback", which is sendfile only; logerror half unchanged. |
| t27 | gold_symbols += `lib/application.js::app.set` (def_line 351, gold_pending_indexer true); note updated | alternative-answer risk resolved by adding: "inherit the parent's value unless overridden" needs app.set too (it stores 'trust proxy fn' via compileTrust and flips the trustProxyDefaultSymbol marker to false on an explicit set, which is exactly what makes the onmount listener in app.defaultConfiguration skip the override). t27 already carries js_assigned_method, so the cap is unchanged. gold_files unchanged (same two files). |

All other fields (ids, groups, gold of the other tasks, packet tasks p01..p10) are unchanged. `reviewed` left `false`.

## Per-task check (no change = gold confirmed best, def_line confirmed by opening the file)
a_keyword t01-t10: all gold are plain indexed functions, def_lines match source. Assigned alternatives considered and rejected:
t01 normalizeType (only wraps acceptParams), t03 compileQueryParser (only selects the parser), t04 app.init, t05/t24 app.handle (only wires logerror),
t06 app.render/View.render, t09 res.json (settings lookup + send, no escaping logic), t10 res.sendFile (does not register listeners).
b_hidden_dep t11-t20: no name/part/stem leak any more (checked token AND substring, parts >= 4 chars, incl. "on"-prefix stripped).
t11 tryStat vs View.resolve (caller only); t13 ondirectory vs sendFile callback (consumes EISDIR, does not create it);
t14 onerror vs onfinish (delegates to onerror); t15 onend vs tail of onfinish (onfinish also has ECONNRESET/error/setImmediate logic, t07 owns that);
t18 sendfile vs res.set/res.download (no listener / not "just before the body goes out"); t19/t20 View ctor vs app.engine
(app.engine only stores the function, does not require() the module nor derive the extension from the default engine).
c_multi_file t21-t30: >= 2 files each, gold_files = set of gold paths (checked by script).
t22 compileQueryParser is selector only, not equal. t25 app.handle/app.defaultConfiguration set prototypes but do not create the per-app prototype with the app back-reference.
t26 compileETag + app.set confirmed (no better alternative; exports.etag/wetag are data properties). t28 res.format + normalizeType + normalizeTypes confirmed
(req.accepts is a thin wrapper over the accepts library, only the matching half; not added). t29 res.render + app.render confirmed. t30 app.use + createApplication confirmed
(app.defaultConfiguration onmount only inherits prototypes; not equal to mountpath/parent/restore in app.use).

## Cap and pending gold
* js_assigned_method tasks: t26, t27, t28, t29, t30 = 5 (cap 5, not exceeded). No other localisation task has pending gold or the tag.
* Pending def_lines opened and confirmed against the assignment statement start (script + visual): compileETag 130, app.set 351, compileTrust 194,
  app.defaultConfiguration 90, res.format 576, normalizeType 61, normalizeTypes 75, res.render 900, app.render 522, app.use 190.
  Packet: app.init 59, app.handle 152, app.use 190, app.engine 294, app.enabled 420, View.render 133, View.lookup 104, res.send 125, res.json 239, res.jsonp 267,
  res.sendFile 378, res.download 440, compileQueryParser 162 (plus the ones above). All correct. Indexed def_lines equal the old-index span starts (verify_bench_gold).

## Packet tasks p01-p10 (no change)
All `why` statements checked against the code and true (tryRender sole caller = app.render; acceptParams sole caller = normalizeType;
res.sendFile callback codes EISDIR/ECONNABORTED/write; merge order in app.render; jsonp default callback name set in defaultConfiguration; etc.).
3-5 gold_context each, always one other file, need values valid. Targets: express.js, application.js x2, view.js, utils.js x3, response.js x3.

## Lint after edits
* lint_tasks: SUCCESS, all 30 tasks pass 6 rules.
* lint_packet_tasks (expected-total 10): SUCCESS, all 10 pass.
* verify_bench_gold: missing_gold 0 (pending entries skipped); packet reach ceiling 0.0 on the old index (expected, indexed symbols have no mutual edges).
* Group counts 10/10/10, 30 unique queries, 6-25 words and <= 190 chars each.

## Remaining caveats (accepted, not blockers)
* Spread: 10 of the 20 a/b tasks sit in lib/response.js (7 nested handlers of sendfile + sendfile x2 + stringify). Forced by the old index (only 18 symbols, 7 of them nested handlers); the 5-task assigned-method cap leaves no room to move them.
* t16/t17 are one-statement handlers, separated only by value and event paraphrase; t14/t15/t12/t13 are small near-twins separated by distinct behaviour. Hard but each has one best gold.
* Symbols reused across tasks (sendfile x3, View x3, defineGetter x3, createApplication x3, ...) with different behaviours each time; acceptable for a measurable set.
* Packet reach on the old index is 0 by construction; packet tasks measure the new indexer only.

VERDICT: approved
