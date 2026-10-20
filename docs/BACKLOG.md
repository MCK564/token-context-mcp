# Backlog

## Resolved Items

- **[RESOLVED] E14 (`inspect_symbol` relationship contract compliance)**:
  - View `minimal`: Retains quality-filtered relationships when budget permits (`_edge_compact_tuple` wire format); only genuine budget shortfalls drop rows.
  - View `normal`: Filters out ambiguous edges (`confidence < 0.5`) and external stubs (`append`), verified by `test_inspect_symbol_minimal_relationships_filtered` and `test_inspect_symbol_normal_relationships_exclude_ambiguous_and_stub` in `tests/test_inspect_symbol_budget.py`.

