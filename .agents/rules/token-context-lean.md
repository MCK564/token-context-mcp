# Token-Context MCP: Lean Selective
Call `token-context` MCP directly (skip `.json` schema reads unless a call errors):
- `search_source(repo_id, query, profile="locate", max_tokens=1280, limit=15)`
- `get_file_skeleton(repo_id, path, include_private=false, max_tokens=1536)`
- `inspect_symbol(repo_id, query, view="full", budget_tokens=1536)`
- `get_impact_slice(repo_id, symbol_id, direction="both", depth=2, max_tokens=1536)`
- `get_repo_map(repo_id, query=None, budget_tokens=1024, format="grouped")`

1. Known path -> `get_file_skeleton` (signatures) or direct `read_file` (<300 lines); skip `list_repositories`/`get_repo_map`/`search_source`. Unknown path or impact -> 1 call (`search_source`/`inspect_symbol`/`get_impact_slice`).
2. Anti-Double-Read: when `get_file_skeleton`/`inspect_symbol` returns `freshness=fresh` & `truncated=false` with needed info, stop — never `read_file` the whole file (only 20-60 line windows if needed).
3. Skip repeat `get_index_status` (`freshness` is in every reply); keep `trajectory_record`/`memory_put` opt-in.
