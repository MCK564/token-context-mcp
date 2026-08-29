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

For the deterministic context-only comparisons (C1/C2), run:

```powershell
uv run python evals/measure_context_cost.py `
  --repo-id token-context `
  --config $env:APPDATA\token-context-mcp\repos.toml `
  --output evals/reports/c1-token-context-x1.json
```

This records both the naive source-read baseline and the serialized payload
received from each retrieval tool, including whether any call exceeds the
configured `max_result_tokens` cap. The X1 reports cover `token-context` and
`invoice-scanner`; they are local `utf8 bytes / 4` estimates, not provider
usage. C3 requires paired agent runs with provider-reported token counts.

## C3 tool-health gate

Run every instrumented C3 arm through `evals/run_c3.py`. It streams Codex JSONL,
terminates the agent as soon as an MCP tool returns an `error` envelope, and
only then appends a provider-usage record. `benchmark-report` also rejects any
record declaring MCP errors.

```powershell
uv run --no-sync python evals/run_c3.py `
  --arm B1 --task-id T2-locate --seed 1 --task-success true --prompt-sha256 <same-hash-as-B0> `
  --raw-output evals/runs/c3/B1-T2.jsonl `
  --stderr-output evals/runs/c3/B1-T2.stderr.log `
  --usage-output evals/reports/c3-runs.jsonl `
  --require-mcp-server token-context `
  -- codex exec --ephemeral --json --color never --sandbox danger-full-access --skip-git-repo-check `
  -C D:\AI\bench\invoice-scanner-frozen "<same prompt used by B0>"
```

Record `cached_input_tokens` separately. It is cache replay, not newly supplied
repository context, and can otherwise dominate a one-turn provider comparison.
The runner also records native command output using the clearly labelled local
`utf8-bytes-div-4-v1` estimate, so a competent-native baseline can sit beside
the naive full-source C1 upper bound without being mistaken for provider usage.
For MCP arms it separately records `mcp_result_output_estimated_tokens` and
`retrieved_content_estimated_tokens` (native output plus MCP result output);
compare the latter when measuring retrieved content across arms.

For a publishable result, run the paired B0/B1/B2 matrix defined in
[`evals/c3_protocol.md`](../evals/c3_protocol.md): 5 tasks × 3 seeds × 3 arms. Use the
same model, prompt bytes, tool permissions and working tree, collect provider
`input_tokens`, `output_tokens`, cache and cost fields, and apply the declared
quality gate before aggregating savings.

## Hybrid and MCP-first protocols

The C3 runner accepts `--protocol hybrid` (the B1 behavior) or
`--protocol mcp-first` (B2). MCP-first requires a successful MCP call before
native verification and rejects a second native command in the same task.
Both protocols record `verification_triggers`, including warnings returned by
the most recent MCP call before each native command.

Use `--max-mcp-calls N` to make the retrieval budget explicit for a C3 arm. The
runner rejects the run before writing provider usage when the agent exceeds
that call budget; this prevents an ostensibly MCP-first prompt from turning
into an unbounded sequence of follow-up lookups.
