# Chain Evaluation Protocol (L0–L3)

Pre-registered benchmark protocol for multi-turn retrieval chains on `bench-rich` and `bench-fastify`.

## 1. Task Structure

Each chain file (`evals/tasks/chain_rich.json`, `evals/tasks/chain_fastify.json`) contains:
- **Main chains** (15 per repo, 30 total): each chain has `q1` (initial query), `q2` (follow-up in the same module/subsystem), and `q3` (same topic, different intent such as testing, error handling, or refactoring).
- **Topic collisions** (>= 8 per repo, >= 16 total): `q1` and `q2_prime` share vocabulary, where `q1`'s `decoy_symbol` is `q2_prime`'s gold answer.
- **Code mutations** (>= 8 per repo, >= 16 total): `edit_body`, `insert_lines_above`, `rename_symbol`, `edit_sibling_in_file`.
- **Poisoning cases** (>= 10 per repo, >= 20 total): fabricated symbol IDs, out-of-range lines, injection-like strings.

## 2. Fixed-Policy Replay Arms

1. `no_ledger`:
   - Step 1: `search_source(repo_id, query=Q, profile="locate")`.
   - Step 2+: inspect top ranked candidates (`get_symbol_context(repo_id, symbol_id=..., include_body=True)`) until a gold symbol is retrieved (up to 3 candidates).
   - Fallback (if gold symbol was not in top-3 search results): `get_repo_map(repo_id, query=Q, format="compact")` followed by `find_symbols` on the top keyword.
2. `oracle_ledger` (L0 ceiling):
   - On `q1`: identical to `no_ledger` (cold start).
   - On `q2` and `q3`: `search_source` includes a 1-card `prior_evidence` hint pointing directly to the verified gold symbol (`symbol_id`, `path`, `line`). The driver skips candidate probing and fallback calls, calling `get_symbol_context` directly on the hinted symbol.

## 3. Metrics & Go/No-Go (L-0)

- Primary metric: **wire tokens to first gold evidence** on `q2` and `q3` (measured with `o200k_base` when `tiktoken` is installed, else `utf8-bytes-div-4-v1` and labeled as such).
- Paired comparison per `(chain_id, turn)` with 2,000-sample paired bootstrap CI95.
- **L-0 Go/No-Go gate**: `oracle_ledger` median token reduction on `q2`/`q3` >= 15% and CI95 lower bound > 0.
