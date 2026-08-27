# Benchmark protocol

The harness reads JSONL records with:

```json
{"arm":"B0","task_id":"architecture-01","seed":1,"input_tokens":1000,"output_tokens":200,"total_tokens":1200,"latency_seconds":2.1,"task_success":true}
```

Run:

```powershell
uv run token-context benchmark-report --input evals/sample-runs.jsonl --output evals/reports/sample-summary.json
```

The report calculates paired median total-token reduction and a deterministic bootstrap interval. It does not contact a provider and cannot turn local byte estimates into a billing claim.

For a publishable result, run paired B0–B6 tasks with the same model, prompt, tool permissions and seed, collect provider `input_tokens`, `output_tokens`, cache and cost fields, then apply the quality gate in `D:\AI\save_token_research_plan\03_TOKEN_BENCHMARK_PLAN.md`.

