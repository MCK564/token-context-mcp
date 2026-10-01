# Review log: edge_gold_heldout_zod.json (zod v4.6.5)

Reviewer procedure: all 30 sites were labelled independently from source only (scratch file
`scratch_review_edge_zod.json`) before the author's file was opened, then compared.

Result of comparison: 28 of 30 sites agreed exactly (same label kind and same path/qualified_name). 2 disagreed and were changed.

## Changes (0-based site index; line is the call-site line in the file)

| site | file:line | old | new | why |
|---|---|---|---|---|
| 12 | packages/bench/union.ts:5 | `dynamic` | `external` | The receiver `z` is a callback parameter typed `typeof zod4`, but the only caller (`makeSchema` in benchUtil.ts) passes exactly `zod3` (`npm:zod@~3.24.0`) and `zod4` (`npm:zod@4.0.8`) from bench/package.json. Both are registry packages, not workspace code, so the set of possible targets is fully known and entirely third-party; no repo function can be the callee. (Judgement call: the callback-parameter rule would also allow `dynamic`; flagged as the one uncertain site.) |
| 14 | packages/docs/components/gold.tsx:11 | `unknown` | `{path: packages/docs/components/gold.tsx, qualified_name: Gold}` | The node is not a call; it is the arrow function that is the body of `export const Gold = () => {...}` (file has no IIFE or trailing call). Per the non-call rule, `unknown` is only for when nothing better exists; the best label is the function the node is, `Gold` in the file that defines it. |

Also edited: `review_note` (to reflect the two changes above) and the `reason` strings of sites 12 and 14. `reviewed` left `false` (orchestrator sets it).

## Other doubtful site checked

* Site 23 (packages/zod/src/v4/locales/cs.ts:89, `getSizing`): confirmed. `getSizing` is a nested function declared at cs.ts:14 inside the `error` arrow function; per the nested-function naming rule the label is plain name `getSizing` in `packages/zod/src/v4/locales/cs.ts`. Author agreed.

## Spot confirmations of agreed sites

* Sites 16/17 (`z.number`, `z.object` in integration fixture and treeshake): `zod` is `workspace:*` in both package.json files with the `@zod/source` condition, index.ts re-exports `classic/external.ts` which `export *` from `schemas.ts` where `number` / `object` are defined.
* Site 6: `.add` is `Metabench.add` (abstract base in packages/bench/metabench.ts); no subclass overrides it.
* Site 29: `schemas` in mini/in-out.ts is `./schemas.js` (mini/schemas.ts) which defines `optional`.
* Sites 24-27: `issue.maximum` / `issue.minimum` are `number | bigint` (core/errors.ts), so `.toString()` is built-in.

VERDICT: approved
