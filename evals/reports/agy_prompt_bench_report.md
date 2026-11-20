# Antigravity 5-Prompt Benchmark Report: No MCP (A0) vs Plain MCP (A1) vs `sample_prompt.md` (A3) vs Lean Selective (A4)

> Measured directly from Antigravity `transcript.jsonl` / `transcript_full.jsonl` provider token logs (`input_tokens` = uncached new input, `cache_read_tokens` = cached prefix reads, `output_tokens` = output + thinking).

## 1. Summary Table Across Model Tiers & Arms

| Model | Arm | Steps | Uncached Input | Cache Read | Eff. Input Cost | Peak Context | Output Tokens | Retrieved (MCP / Schema / Native) | MCP Adoption | Gold (0–5) | Ledger Cards | Time (s) |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | :---: | ---: | :---: | ---: | ---: |
| `flash` | **A0** (No MCP (Plain)) | 25 | 101,325 | 1,215,880 | 162,119 | 77,169 | 15,576 | 41,369 (0 / 0 / 41,369) | 0.0% | 5/5 | 0 | 138.0 |
| `flash` | **A1** (MCP Enabled (Plain Chat)) | 26 | 106,339 | 1,251,609 | 168,920 | 77,818 | 11,540 | 44,290 (0 / 0 / 44,290) | 0.0% | 5/5 | 0 | 127.0 |
| `flash` | **A3** (MCP + sample_prompt.md (3.2 + 3.3)) | 26 | 131,210 | 1,653,250 | 213,872 | 108,300 | 21,820 | 59,507 (19,394 / 4,429 / 35,684) | 45.9% | 5/5 | 0 | 187.0 |
| `pro` | **A0** (No MCP (Plain)) | 32 | 117,508 | 1,816,681 | 208,342 | 96,527 | 27,347 | 47,994 (0 / 0 / 47,994) | 0.0% | 5/5 | 0 | 230.0 |
| `pro` | **A1** (MCP Enabled (Plain Chat)) | 27 | 120,866 | 1,692,786 | 205,505 | 105,081 | 27,480 | 54,020 (0 / 0 / 54,020) | 0.0% | 5/5 | 0 | 197.0 |
| `pro` | **A3** (MCP + sample_prompt.md (3.2 + 3.3)) | 39 | 225,810 | 4,640,371 | 457,829 | 204,533 | 49,835 | 114,119 (53,915 / 5,559 / 54,645) | 62.8% | 5/5 | 5 | 375.0 |
| `flash` | **A4** (MCP + Lean Selective (3.0)) | 21 | 82,747 | 846,729 | 125,084 | 63,191 | 11,282 | 26,466 (8,338 / 0 / 18,128) | 22.2% | 5/5 | 0 | 119.0 |
| `pro` | **A4** (MCP + Lean Selective (3.0)) | 23 | 103,104 | 1,274,984 | 166,853 | 89,649 | 25,566 | 36,055 (11,170 / 0 / 24,885) | 22.9% | 5/5 | 0 | 181.0 |

## 2. Paired Comparisons (A1 vs A0, A3 vs A0, A4 vs A0, A4 vs A1, A4 vs A3)

| Model | Comparison | Δ Uncached Input | Δ Eff. Input Cost | Δ Peak Context | Δ Retrieved Content | Δ Output Tokens |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| `flash` | **A1 vs A0** | +4.9% | +4.2% | +0.8% | +7.1% | -25.9% |
| `flash` | **A3 vs A0** | +29.5% | +31.9% | +40.3% | +43.8% | +40.1% |
| `flash` | **A3 vs A1** | +23.4% | +26.6% | +39.2% | +34.4% | +89.1% |
| `flash` | **A4 vs A0** | -18.3% | -22.8% | -18.1% | -36.0% | -27.6% |
| `flash` | **A4 vs A1** | -22.2% | -26.0% | -18.8% | -40.2% | -2.2% |
| `flash` | **A4 vs A3** | -36.9% | -41.5% | -41.7% | -55.5% | -48.3% |
| `pro` | **A1 vs A0** | +2.9% | -1.4% | +8.9% | +12.6% | +0.5% |
| `pro` | **A3 vs A0** | +92.2% | +119.7% | +111.9% | +137.8% | +82.2% |
| `pro` | **A3 vs A1** | +86.8% | +122.8% | +94.6% | +111.3% | +81.4% |
| `pro` | **A4 vs A0** | -12.3% | -19.9% | -7.1% | -24.9% | -6.5% |
| `pro` | **A4 vs A1** | -14.7% | -18.8% | -14.7% | -33.3% | -7.0% |
| `pro` | **A4 vs A3** | -54.3% | -63.6% | -56.2% | -68.4% | -48.7% |

## 3. Per-Prompt Breakdown (`P1..P5`)

### Model `flash`

| Prompt | Arm | Steps | Uncached Input | Peak Ctx | Retrieved (MCP/Schema/Native) | Tools (MCP / Native) | Gold |
| :--- | :--- | ---: | ---: | ---: | :---: | :---: | :---: |
| **P1** | A0 | 6 | 35,719 | 33,674 | 18,277 (0/0/18,277) | 0 / 8 | PASS |
| **P1** | A1 | 6 | 35,006 | 32,961 | 18,278 (0/0/18,278) | 0 / 8 | PASS |
| **P1** | A3 | 8 | 63,084 | 53,284 | 29,888 (7,251/4,429/18,208) | 9 / 8 | PASS |
| **P1** | A4 | 6 | 36,850 | 34,805 | 11,950 (1,444/0/10,506) | 1 / 11 | PASS |
| **P2** | A0 | 4 | 21,538 | 53,166 | 12,097 (0/0/12,097) | 0 / 6 | PASS |
| **P2** | A1 | 6 | 28,133 | 53,700 | 13,634 (0/0/13,634) | 0 / 7 | PASS |
| **P2** | A3 | 4 | 21,172 | 73,047 | 11,338 (3,282/0/8,056) | 2 / 4 | PASS |
| **P2** | A4 | 5 | 18,344 | 47,922 | 7,657 (2,622/0/5,035) | 2 / 4 | PASS |
| **P3** | A0 | 3 | 11,304 | 62,423 | 4,967 (0/0/4,967) | 0 / 1 | PASS |
| **P3** | A1 | 3 | 12,856 | 62,459 | 4,967 (0/0/4,967) | 0 / 1 | PASS |
| **P3** | A3 | 4 | 14,458 | 85,459 | 6,687 (1,720/0/4,967) | 2 / 1 | PASS |
| **P3** | A4 | 3 | 7,581 | 51,406 | 1,587 (1,587/0/0) | 1 / 0 | PASS |
| **P4** | A0 | 9 | 25,522 | 74,565 | 5,653 (0/0/5,653) | 0 / 8 | PASS |
| **P4** | A1 | 9 | 25,422 | 76,046 | 7,411 (0/0/7,411) | 0 / 12 | PASS |
| **P4** | A3 | 6 | 19,522 | 99,422 | 7,453 (4,088/0/3,365) | 2 / 6 | PASS |
| **P4** | A4 | 5 | 15,301 | 61,100 | 5,272 (2,685/0/2,587) | 2 / 6 | PASS |
| **P5** | A0 | 3 | 7,242 | 77,169 | 375 (0/0/375) | 0 / 1 | PASS |
| **P5** | A1 | 2 | 4,922 | 77,818 | 0 (0/0/0) | 0 / 0 | PASS |
| **P5** | A3 | 4 | 12,974 | 108,300 | 4,141 (3,053/0/1,088) | 2 / 1 | PASS |
| **P5** | A4 | 2 | 4,671 | 63,191 | 0 (0/0/0) | 0 / 0 | PASS |

### Model `pro`

| Prompt | Arm | Steps | Uncached Input | Peak Ctx | Retrieved (MCP/Schema/Native) | Tools (MCP / Native) | Gold |
| :--- | :--- | ---: | ---: | ---: | :---: | :---: | :---: |
| **P1** | A0 | 7 | 38,493 | 36,449 | 16,565 (0/0/16,565) | 0 / 12 | PASS |
| **P1** | A1 | 7 | 45,152 | 43,108 | 22,100 (0/0/22,100) | 0 / 10 | PASS |
| **P1** | A3 | 12 | 85,475 | 81,386 | 45,197 (16,299/5,559/23,339) | 15 / 11 | PASS |
| **P1** | A4 | 6 | 40,590 | 40,595 | 13,347 (1,444/0/11,903) | 1 / 11 | PASS |
| **P2** | A0 | 8 | 30,401 | 61,249 | 15,087 (0/0/15,087) | 0 / 12 | PASS |
| **P2** | A1 | 5 | 26,207 | 67,270 | 14,165 (0/0/14,165) | 0 / 9 | PASS |
| **P2** | A3 | 7 | 49,613 | 128,956 | 29,682 (16,556/0/13,126) | 13 / 6 | PASS |
| **P2** | A4 | 5 | 26,595 | 65,145 | 13,145 (5,454/0/7,691) | 4 / 6 | PASS |
| **P3** | A0 | 4 | 11,418 | 70,621 | 4,026 (0/0/4,026) | 0 / 4 | PASS |
| **P3** | A1 | 3 | 12,985 | 78,208 | 4,967 (0/0/4,967) | 0 / 1 | PASS |
| **P3** | A3 | 5 | 26,656 | 153,567 | 12,967 (7,439/0/5,528) | 7 / 2 | PASS |
| **P3** | A4 | 3 | 7,089 | 70,187 | 1,587 (1,587/0/0) | 1 / 0 | PASS |
| **P4** | A0 | 10 | 30,089 | 92,951 | 11,795 (0/0/11,795) | 0 / 17 | PASS |
| **P4** | A1 | 9 | 28,803 | 100,870 | 12,413 (0/0/12,413) | 0 / 16 | PASS |
| **P4** | A3 | 10 | 48,217 | 193,547 | 22,379 (10,856/0/11,523) | 11 / 9 | PASS |
| **P4** | A4 | 6 | 20,374 | 85,290 | 7,430 (2,685/0/4,745) | 2 / 9 | PASS |
| **P5** | A0 | 3 | 7,107 | 96,527 | 521 (0/0/521) | 0 / 1 | PASS |
| **P5** | A1 | 3 | 7,719 | 105,081 | 375 (0/0/375) | 0 / 1 | PASS |
| **P5** | A3 | 5 | 15,849 | 204,533 | 3,894 (2,765/0/1,129) | 3 / 1 | PASS |
| **P5** | A4 | 3 | 8,456 | 89,649 | 546 (0/0/546) | 0 / 1 | PASS |

## 4. MCP Tool Usage Breakdown

- **`flash` / A3** (`15e9679e-8a95-43b7-bd11-3e9e6ef880f2`): schema_reads=12, mcp_calls=17 -> {'list_repositories': 1, 'get_index_status': 1, 'get_repo_map': 2, 'search_source': 5, 'memory_get': 1, 'memory_search': 1, 'get_file_skeleton': 3, 'get_impact_slice': 1, 'get_module_dependents': 1, 'inspect_symbol': 1}
- **`pro` / A3** (`fbe5e355-f6be-4afe-b03c-6bf70a4c38e2`): schema_reads=15, mcp_calls=49 -> {'list_repositories': 1, 'memory_get': 1, 'memory_search': 1, 'get_index_status': 4, 'get_repo_map': 4, 'search_source': 5, 'get_file_skeleton': 6, 'find_symbols': 5, 'inspect_symbol': 5, 'get_impact_slice': 4, 'get_symbol_context': 1, 'trajectory_record': 6, 'memory_put': 6}
- **`flash` / A4** (`d8b02c5c-37f2-40fb-a8dd-aab6d83874c0`): schema_reads=0, mcp_calls=6 -> {'get_file_skeleton': 2, 'search_source': 3, 'inspect_symbol': 1}
- **`pro` / A4** (`92ce7d18-5a67-4bc3-8447-d397a7196359`): schema_reads=0, mcp_calls=8 -> {'get_file_skeleton': 4, 'search_source': 3, 'inspect_symbol': 1}
