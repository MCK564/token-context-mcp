# Architecture

The package is split into two planes:

```text
admin CLI (register/index) -> atomic SQLite snapshot + manifest
                                        |
                                        v
                           read-only MCP stdio server -> agent
```

The admin plane owns canonical roots and writes snapshots. The server plane opens the database read-only and never accepts an absolute path, reindex request, shell command or write operation.

## Analysis levels

1. Tree-sitter extracts definitions and source spans for Python, JavaScript, TypeScript and TSX.
2. A lexical identifier graph produces `resolved` or `ambiguous` observed edges.
3. LSP/SCIP semantic adapters are intentionally not enabled in 0.1.0. Their results must only be added after a language-specific precision/recall evaluation and an allowlisted, sandboxed backend.

The server returns hashes, `freshness`, provenance and warnings. It never treats the absence of a lexical edge as proof that no semantic edge exists.

## Token behavior

The estimator is explicitly `utf8-bytes-div-4-v1`, not provider billing. The benchmark harness consumes provider-reported usage in JSONL; see [`BENCHMARK.md`](BENCHMARK.md).

