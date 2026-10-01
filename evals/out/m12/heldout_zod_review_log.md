# heldout-zod review log (reviewer session, independent of the author)

Repo zod, tag v4.6.5, commit 59bbc03e10c636b9eb3c393dfeb552819774ec21. File reviewed and edited in place: `out/heldout_zod.json`.
Only zod source code was read (grep / sed / read). No token-context tool, no ranking script. Allowed helper checks only: lint_tasks, lint_packet_tasks, verify_bench_gold.
Backup of the author's version (outside the repo output dir): scratchpad `heldout_zod.orig.json`.

## What was checked, for every task
* Opened the source of every gold symbol and of every packet target; confirmed `def_line` points at the declaration of that name (scripted check: the symbol name occurs on that line for all 49 localisation gold entries and all 10 packet targets).
* grep'ed the tree for equally good alternative answers (same name in v3 / v4 / classic / mini / other locales).
* b_hidden_dep: lint rule 3 passes, and read each query for semantic leaks (name tokens, file stem, near-synonym giveaways). None found.
* c_multi_file: each has >= 2 gold files and the described behaviour really spans them.
* Packets: read each `why` against the code. All are true; all have 4-5 gold items, need values valid, each has a gold item in a file other than the target.
* gold_files == set of gold_symbols files for all tasks; all `split: "test"`; queries unique, 21-25 words, <= 184 chars; groups are 10/10/10; no gold in test files.

## Verdict per doubtful task (the author's list)
* t02 kept. be.ts has a body-identical Belarusian helper, but the query names Russian, so only ru.ts fits. Residual risk: low.
* t14 kept. v3/types.ts floatSafeRemainder uses decimal-count scaling; the query's "four machine epsilons scaled by the quotient" is only true of core/util.ts.
* t20 kept. v3/errors.ts setErrorMap just assigns a module variable and is not "deprecated" nor "passes into the configuration function"; only the classic shim fits.
* t25 kept. Both gold functions are real and the second one hoists the first and calls it only under the inDoubt guard.
* t26 kept. Link between the two gold symbols is thematic (same feature in the runtime and compiled parsers), not a call edge; acceptable for a c task.
* t28 kept. getTupleOptStart exists in core/schemas.ts and core/compile.ts, both are gold, the query spans both parsers.
* p05 kept. Index resolves target `input` to the function (span 28-36), not the same-named type alias.
* t29, t30 rewritten (see below).

## Changes
### t29 (c_multi_file) rewritten
* Old: generated fast path hoists the checksum validators (compile.ts generateStringFormatCheck + isValidCreditCard + isValidIBAN). Correct as written, but the gold was a thematic mix and it was the 5th of 10 c tasks centred on compile.ts.
* New: refinement context with `addIssue` accepting a string or legacy issue object (core/api.ts `_superRefine`, classic/schemas.ts `superRefine`, mini/schemas.ts `superRefine`). Gold def_lines 1708 / 2825 / 1909, all confirmed in the source and found by verify_bench_gold.
* Why: spread (api.ts, classic and mini were nearly unrepresented) and a cleaner, smaller gold set.

### t30 (c_multi_file) rewritten
* Old: template literal parts folded into one regex (schemas.ts partPattern/leafPattern + processor + compile check). Correct, but the processor and the compile check only read the finished `_zod.pattern`, so the gold mixed producer and passive readers; 6th compile-centred c task.
* New: pointer-segment escaping on export (core/to-json-schema.ts `encodeJSONPointerSegment`, line 297) paired with the inverse on import (classic/from-json-schema.ts `decodeJSONPointerSegment`, line 128). Query words the order issue (importer undoes slash before tilde). `resolveRef` is deliberately not in gold because it is t06's gold.
* Why: same as t29; exporter/importer pair is a different shape from the other c tasks.

No other task text, gold or id was changed. `reviewed` left `false`; `review_note` untouched (orchestrator sets those).

## Spread (after the edits)
* Primary gold area of the 30 localisation tasks: v4/core 17, v3 4, v4/locales 3, v4/classic 3, scripts/packages 3 (some tasks touch two areas; mini appears in 3 c tasks). v3 is 4/30 localisation and 2/10 packets, so the set is not dominated by v3; the heavy side is v4/core (about half the repo source).
* compile.ts is in gold of 4 c tasks (t23 t25 t26 t28) after the rewrite (was 6), plus packet p09.
* Locales: t02 t12 t13 plus packet p08 (three similar number/word helpers; accepted, each helper is unique to its language).
* Known gaps, accepted: core/checks.ts, core/regexes.ts, core/parse.ts and the classic schema class tables are not targets (members of `$constructor` tables and arrow consts are not expressible as indexed symbols, as the author noted).

## Remaining minor points (not blockers)
* t27: mini `stringbool` is a two-line `export const ... =\n (...args) =>` so `def_line` is 1948 (the declaration) while the index span starts at 1949. Nothing reads def_line.
* Packet reach per verify_bench_gold is 17/47 (informational, not tuned).
* The author notes file still describes the old t29/t30; this log supersedes it.

## Final checks (run after the last edit)
* lint_tasks: SUCCESS, all 30 tasks pass all 6 rules.
* lint_packet_tasks: SUCCESS, all 10 pass.
* verify_bench_gold: loc_tasks 30, packet_tasks 10, missing_gold 0 (output refreshed in `out/verify_zod.json`).

VERDICT: approved
