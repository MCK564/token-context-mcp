# X6 — C3 matrix runbook

**Vietnamese:** `X6_RUNBOOK.vi.md` · **Frozen protocol:** `evals/c3_protocol.md` (must not be edited once the run starts)

45 sessions = 5 tasks × 3 seeds × 3 arms. Budget 2–2.5 hours of wall time.

This runbook assumes setup is complete per `SETUP.en.md` and that the Codex CLI is on PATH.

---

## 0. Three operational gaps to know first

Reading `run_c3_matrix.py` shows three points the procedure has to compensate for. None is a bug, but ignoring any of them corrupts the run:

**1. `--task-success` is a single flag for all 45 sessions.** The protocol requires grading each answer. One value cannot express 45 gradings. → Run in **two phases**: phase 1 records usage with a provisional value, phase 2 rewrites each row from the grades.

**2. There is no resume.** If session 30 fails, re-running from the top **appends duplicate records** to the same `--usage-output` file. → Run in per-task batches, each with its own usage file.

**3. The agent's answer sits inside the session log; there is no extraction step.** Grading needs the last `agent_message` from each `{arm}-{task}-seed{n}.jsonl`. → §3 provides the extraction command.

---

## 1. Pre-flight — do all of this before spending tokens

```powershell
cd D:\AI\token-context-mcp

# 1.1 Test suite must be green
uv run pytest

# 1.2 The target repo's index must be fresh
uv run python -m token_context_mcp status --repo-id invoice-scanner
```

In the `status` output, required:

- `freshness` must be `fresh`. If it is `stale`, re-run `index` — **a benchmark session against a stale index is discarded data**.
- `pending_path_count` must be `0`.

```powershell
# 1.3 Codex can see the server
codex mcp list

# 1.4 Enumerate all 45 commands without running them
uv run python evals/run_c3_matrix.py --dry-run --task-success true
```

The dry run must print exactly **45 lines**. Eyeball one B0 line and one B1 line: B0 must carry `-c mcp_servers.token-context.enabled=false`, B1 must not.

```powershell
# 1.5 One smoke batch, to catch environment failures early
uv run python evals/run_c3_matrix.py --task-success true `
  --seeds 1 --arms B1 `
  --runs-dir evals/runs/x6-smoke `
  --usage-output evals/reports/x6-smoke.jsonl
```

That is 5 tasks × 1 seed × 1 arm = 5 sessions. If it hangs past 3 minutes with no JSONL, **stop** — that is exactly the failure seen previously (Codex nested inside Codex returns no JSONL). Run this runbook from a **plain terminal**, never inside another agent session.

---

## 2. Phase 1 — run in per-task batches

One task at a time, so a mid-run failure costs 9 sessions instead of 45:

```powershell
$tasks = @("T1-orient","T2-locate","T3-impact","T4-surface","T5-trace")
foreach ($t in $tasks) {
  uv run python evals/run_c3_matrix.py `
    --task-success true `
    --seeds 1 2 3 `
    --arms B0 B1 B2 `
    --runs-dir      evals/runs/x6/$t `
    --usage-output  evals/reports/x6-$t.jsonl `
    --failure-output evals/reports/x6-$t-failures.json
}
```

`--task-success true` here is a **placeholder**. It only lets phase 1 record usage; phase 2 rewrites it from the grades. Do not feed this file to `benchmark-report` before grading.

After each batch, check immediately:

```powershell
Get-Content evals/reports/x6-T1-orient.jsonl | Measure-Object -Line   # must be 9
Get-Content evals/reports/x6-T1-orient-failures.json                  # must be []
```

If the failures file is non-empty, read `evals/runs/x6/<task>/<arm>-<task>-seed<n>.stderr.log`. A session that failed on an MCP error or a protocol violation **must not enter the results** — the runner fail-fasts correctly; do not work around it.

---

## 3. Quality grading — before looking at any token count

This is the single most important constraint in X6. Grade **first**, read cost **second**. Grading after seeing the costs is how people fool themselves.

Extract the final answer from each session:

```powershell
uv run python -c @'
import json, pathlib
for p in sorted(pathlib.Path("evals/runs/x6").rglob("*.jsonl")):
    last = None
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except Exception:
            continue
        it = ev.get("item") or {}
        if ev.get("type") == "item.completed" and (it.get("item_type") or it.get("type")) == "agent_message":
            last = it.get("text") or it.get("content")
    out = p.with_suffix(".answer.md")
    out.write_text(last or "(no agent_message found)", encoding="utf-8")
    print(f"{p.name:34s} -> {out.name}  ({len(last or '')} chars)")
'@
```

Grade each `.answer.md` against the table in `evals/c3_protocol.md` §"Predeclared quality grader". Record the results in one flat file:

```
evals/reports/x6-grades.csv
arm,task_id,seed,task_success,note
B0,T1-orient,1,true,
B1,T1-orient,1,false,"invented module invoice_frontend_ml"
...
```

T1 can be graded semi-automatically against the labelled set:

```powershell
uv run python evals/rank_eval.py --set evals/relevance/orientation_invoice_scanner.json --budget 4096
```

then check the symbols the T1 answer names against `essential_recall ≥ 0.833` and `noise = 0`.

Grade the other four by hand against the criteria already written. Do **not** add new criteria at this step.

---

## 4. Phase 2 — apply grades to the usage records

```powershell
uv run python -c @'
import csv, json, pathlib

grades = {}
with open("evals/reports/x6-grades.csv", newline="", encoding="utf-8") as fh:
    for row in csv.DictReader(fh):
        grades[(row["arm"], row["task_id"], int(row["seed"]))] = row["task_success"].strip().lower() == "true"

merged, missing = [], []
for p in sorted(pathlib.Path("evals/reports").glob("x6-T*.jsonl")):
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        key = (rec["arm"], rec["task_id"], int(rec["seed"]))
        if key not in grades:
            missing.append(key)
            continue
        rec["task_success"] = grades[key]
        merged.append(rec)

if missing:
    raise SystemExit(f"{len(missing)} sessions ungraded: {missing[:5]}")

out = pathlib.Path("evals/reports/x6-graded.jsonl")
out.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in merged), encoding="utf-8")
print(f"{len(merged)} records -> {out}")
'@
```

The script **refuses to run** while any session is ungraded. That is deliberate.

---

## 5. Phase 3 — aggregate

```powershell
uv run python -m token_context_mcp benchmark-report `
  --input  evals/reports/x6-graded.jsonl `
  --output evals/reports/x6-summary.json
```

Read the output in the priority order fixed in X4:

| Field | Role |
|---|---|
| `median_paired_retrieved_content_reduction` | **primary** |
| `paired_retrieved_content_reduction_ci95` | confidence interval on the primary |
| `median_uncached_input_tokens` | true marginal cost |
| `quality_noninferiority_delta` | quality gate — negative means the arm degraded the task |
| `median_paired_token_reduction` | **secondary**, dominated by conversation length |

---

## 6. Acceptance

An X6 run counts as valid only when **all** of the following hold:

- `paired_count` is 15 per arm (5 tasks × 3 seeds), or any shortfall is accounted for by the failure list.
- No record has a non-empty `mcp_errors` or `mcp_health: failed`.
- Every `prompt_sha256` matches across each B0/B1/B2 triple — `benchmark-report` raises if not; do not suppress that error.
- Quality was graded **before** `x6-summary.json` was opened.
- The final write-up states **explicitly** that the primary metric is `retrieved_content_estimated_tokens`, with CI95 and sample size.

---

## 7. Reading the result honestly

Three outcomes, and what each actually licenses:

**B2 reduces retrieved content with no quality loss** → the strongest claim this dataset supports: *a budget-capped MCP-first protocol retrieves less context for the same answer quality.* State the scope anyway: one repository, one model, five tasks.

**B1 shows no reduction, or an increase** → consistent with what was already measured: in a hybrid workflow MCP is **additive, not substitutive**. That is not a failure of the tool; it is a finding about **agent behaviour**. Report it as such.

**B2 quality drops** → the capped protocol is cutting off something the agent needs. Check `truncated`, `omitted_count`, and `node_limit_reached` in the session logs **before** concluding it is a ranking defect.

What must **not** be written under any outcome: a saving percentage without sample size and CI95, or a general claim generalised from one repository.

---

## 8. Stopping partway

Results are batched, so stopping is safe. Re-run **only** the missing task:

```powershell
uv run python evals/run_c3_matrix.py --task-success true `
  --seeds 1 2 3 --arms B0 B1 B2 `
  --runs-dir evals/runs/x6/T4-surface `
  --usage-output evals/reports/x6-T4-surface.jsonl
```

**Delete that task's usage file before re-running.** The runner appends rather than overwrites, so re-running without deleting creates duplicate records and `paired_count` goes wrong.

Session logs under `evals/runs/` are gitignored — they contain source bodies from the indexed repository along with local paths and the username. Do not commit them.
