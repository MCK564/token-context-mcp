# C3 protocol — public repository (rich)

Status: drafted before any measurement, `reviewed: false` (see `evals/tasks/bench_rich.json`).
Date: 2026-09-29. Author: Claude (drafting session). Reviewer: repo owner or a different Claude session.

## Scope and pairing

Repository under test: `Textualize/rich` tag `v15.0.0`, commit `6ac483cbea39cab124dfd3483bba70ffafb71050`
(MIT). The agent works on a frozen, source-only copy of the tree (`tmp/bench/rich-frozen`), registered as
repo id `bench-rich`. Frozen prompts: `evals/c3_prompts_rich.json`.

Everything else follows `evals/c3_protocol.md` unchanged: 5 tasks × 3 seeds × 3 arms = 45 runs; arms B0 (native),
B1 (hybrid, ≤ 12 MCP calls), B2 (MCP-first, ≤ 12 MCP calls, ≤ 1 native verification command after MCP); the
`prompt_sha256` is the pairing key; primary metric `retrieved_content_estimated_tokens`; secondary metrics as in the
original protocol; paired reductions with the deterministic bootstrap CI95 from `benchmark-report`.
D6 default: **not executed** by the drafting run; `run_c3_matrix.py --manifest evals/c3_prompts_rich.json --dry-run`
must list all 45 attempts.

## Predeclared quality grader (ground truth taken from the v15.0.0 tree before freezing)

Quality is graded independently of token counts, after each answer is captured and before aggregate cost results
are inspected.

| Task | Pass condition |
|---|---|
| T1 orientation | Names at least five modules that exist in `rich/` (list below), states a responsibility for each that is consistent with its content, invents no module, and includes `rich/console.py`. |
| T2 locate | Gives `rich/_emoji_replace.py` and the symbol `_emoji_replace` with a line within ±10 of line 9. Naming `Console.render_str` (`rich/console.py`, ~1409), `markup.render` (`rich/markup.py`, ~106) or `Emoji.replace` (`rich/emoji.py`, ~62) as callers is fine, but the definition file/symbol must be named. |
| T3 impact | Names at least one true caller from this set with path: `Console.render_lines` (`rich/console.py`, call at ~1381), `Console.print` (~1751), `Console.log` (~2025), `Console.export_svg` (~2486); labels the result as a candidate lexical graph; does not claim complete semantic coverage. Tests and benchmarks may also be named. |
| T4 surface | Lists `Measurement` (fields `minimum: int`, `maximum: int`; property `span`; methods `normalize`, `with_maximum`, `with_minimum`, `clamp`; classmethod `get`) and the function `measure_renderables`, with signatures and without bodies. Private definitions are omitted (this module has none to name). Every one of the eight items must appear. |
| T5 trace | Names at least three real stages in this source order, each with path or symbol: `Console.print` (`rich/console.py` ~1652) → `Console._collect_renderables` (~1500) → `Console.render_str` (~1409) → `markup.render` (`rich/markup.py` ~106) → `Console.render` (~1294) → `Text.__rich_console__` (`rich/text.py` ~689) → `Console._check_buffer` (~2044) / `Console._write_buffer` (~2059). Stages out of order, or not in the tree, fail the criterion. |

Any failed criterion means the run does not support a saving claim even when its token count is lower.
MCP errors, stale-index use, or missing source evidence are also quality failures.

### Real modules under `rich/` for T1 (77 files)

`__init__` `__main__` `_emoji_codes` `_emoji_replace` `_export_format` `_extension` `_fileno` `_inspect` `_log_render`
`_loop` `_null_file` `_palettes` `_pick` `_ratio` `_spinners` `_stack` `_timer` `_win32_console` `_windows`
`_windows_renderer` `_wrap` `abc` `align` `ansi` `bar` `box` `cells` `color` `color_triplet` `columns` `console`
`constrain` `containers` `control` `default_styles` `diagnose` `emoji` `errors` `file_proxy` `filesize` `highlighter`
`json` `jupyter` `layout` `live` `live_render` `logging` `markdown` `markup` `measure` `padding` `pager` `palette`
`panel` `pretty` `progress` `progress_bar` `prompt` `protocol` `region` `repr` `rule` `scope` `screen` `segment`
`spinner` `status` `style` `styled` `syntax` `table` `terminal_theme` `text` `theme` `themes` `traceback` `tree`

## Execution gate

Run only after this file, `evals/c3_prompts_rich.json` and the frozen working tree are present and unchanged, and after
the task file has been reviewed. Grade the captured answers against the table above before choosing
`--task-success true|false`.
