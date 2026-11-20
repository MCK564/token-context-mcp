# Server Wire-Payload Token Benchmark (`o200k_base`)

- **Repository:** `token-context` (`C:\Users\KHA\AppData\Roaming\token-context-mcp\repos.toml`)
- **Tokenizer:** `o200k_base` on `CallToolResult.content[0].text`
- **Impact Symbol (`_lookup_prior_evidence`):** `python:src/token_context_mcp/retrieve/service.py:RetrievalService._lookup_prior_evidence:c5bc854c5b7da7cf`

## 1. Per-Tool Wire Token Counts

| Tool | Prompt | Variant | Output Mode | Wire Tokens | Wire Bytes | Truncated | Δ vs Old |
| :--- | :---: | :--- | :--- | ---: | ---: | :---: | ---: |
| `get_index_status` | P1/Pre-flight | **Old** | `text` | 457 | 1,654 | no | — |
| `get_index_status` | P1/Pre-flight | **New** | `text` | 159 | 537 | no | -65.2% |
| `get_index_status` | P1/Pre-flight | **Compact-Text** | `compact_text` | 49 | 174 | no | -89.3% |
| `get_repo_map` | P1 | **Old** | `text` | 4,821 | 15,315 | yes | — |
| `get_repo_map` | P1 | **New-Compact** | `text` | 1,062 | 3,489 | yes | -78.0% |
| `get_repo_map` | P1 | **New-Grouped** | `text` | 1,204 | 3,574 | yes | -75.0% |
| `get_repo_map` | P1 | **Compact-Text** | `compact_text` | 1,204 | 3,126 | yes | -75.0% |
| `search_source` | P2 | **Old** | `text` | 1,975 | 6,944 | yes | — |
| `search_source` | P2 | **New** | `text` | 1,155 | 4,100 | yes | -41.5% |
| `search_source` | P2 | **Compact-Text** | `compact_text` | 583 | 2,072 | yes | -70.5% |
| `get_file_skeleton` | P3 | **Old** | `text` | 1,503 | 5,142 | no | — |
| `get_file_skeleton` | P3 | **New** | `text` | 1,503 | 5,142 | no | 0.0% |
| `get_file_skeleton` | P3 | **Compact-Text** | `compact_text` | 469 | 1,546 | no | -68.8% |
| `get_impact_slice` | P4 | **Old** | `text` | 4,022 | 15,125 | yes | — |
| `get_impact_slice` | P4 | **New** | `text` | 1,458 | 5,378 | yes | -63.7% |
| `get_impact_slice` | P4 | **Compact-Text** | `compact_text` | 719 | 2,303 | yes | -82.1% |

## 2. 5-Tool Totals & Savings vs Old

| Configuration | Total Wire Tokens | Savings vs Old |
| :--- | ---: | ---: |
| **Old (`text`)** | 12,778 | — |
| **New (`text`, compact `repo_map`)** | 5,337 | -58.2% |
| **New (`text`, grouped `repo_map`)** | 5,479 | -57.1% |
| **Compact-Text (`compact_text`, grouped `repo_map`)** | 3,024 | -76.3% |
