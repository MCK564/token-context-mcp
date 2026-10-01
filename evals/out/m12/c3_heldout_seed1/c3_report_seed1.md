# C3 Benchmark Report

- **Total Runs:** 60
- **Completed:** 60
- **Protocol Violations:** 0 (0.00%)
- **Infra Failures:** 0 (0.00%)

## Arm Summary

| Arm | Runs | Success Rate (CI95) | Retrieved Tokens (CI95) | Total Tokens (CI95) | MCP Calls | Native Calls | Latency (s) |
|---|---:|---:|---:|---:|---:|---:|---:|
| B0 | 20 | 100.0% (100.0%..100.0%) | 752.8 (504..1031) | 82210.6 (74350..90607) | 0.0 | 2.1 | 12.22 |
| B1 | 20 | 100.0% (100.0%..100.0%) | 468.1 (285..669) | 84506.9 (71449..98866) | 0.0 | 2.0 | 12.53 |
| B2 | 20 | 100.0% (100.0%..100.0%) | 1387.0 (1049..1780) | 65463.6 (59205..72782) | 1.1 | 0.1 | 10.63 |

## Paired Reductions

| Comparison | Metric | Pairs | Mean Diff | CI95 | % Reduction |
|---|---|---:|---:|---:|---:|
| b1_vs_b0 | retrieved_tokens | 20 | -284.7 | -560.55..-52.0 | 37.82% |
| b1_vs_b0 | total_tokens | 20 | 2296.2 | -9019.0..14201.85 | -2.79% |
| b1_vs_b0 | task_success | 20 | 0.0 | 0.0..0.0 | -0.0% |
| b2_vs_b0 | retrieved_tokens | 20 | 634.25 | 294.1..975.3 | -84.26% |
| b2_vs_b0 | total_tokens | 20 | -16747.05 | -25065.45..-8586.1 | 20.37% |
| b2_vs_b0 | task_success | 20 | 0.0 | 0.0..0.0 | -0.0% |
| b2_vs_b1 | retrieved_tokens | 20 | 918.95 | 587.15..1295.0 | -196.34% |
| b2_vs_b1 | total_tokens | 20 | -19043.25 | -31374.7..-7443.1 | 22.53% |
| b2_vs_b1 | task_success | 20 | 0.0 | 0.0..0.0 | -0.0% |

## Group Performance

| Group | B0 Success | B1 Success | B2 Success | B0 Retrieved | B1 Retrieved | B2 Retrieved |
|---|---:|---:|---:|---:|---:|---:|
| a_keyword | 100.0% | 100.0% | 100.0% | 498.0 | 306.5 | 1462.0 |
| b_hidden_dep | 100.0% | 100.0% | 100.0% | 663.0 | 532.1 | 1045.9 |
| c_multi_file | 100.0% | 100.0% | 100.0% | 969.9 | 484.8 | 1690.6 |
| probe | - | - | - | - | - | - |
