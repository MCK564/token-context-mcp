# Backlog

## M6 Backlog

- **E14 (`inspect_symbol` relationship contract compliance)**:
  - View `minimal`: Currently drops/omits all relationships (`relationships: []`, `relationships_omitted: > 0`) even when sufficient token budget remains, which diverges from the M1.1 specification requiring signature, `path:line`, and relation IDs.
  - View `normal`: Currently includes ambiguous edges (such as generic `get` with confidence 0.10) and external stub calls (such as `append`), which diverges from the M1.1 specification requiring `confidence >= 0.5` and excluding ambiguous edges.
