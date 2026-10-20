"""Export SCIP JSON index to compact occ.jsonl.gz format (M14.0.6).

Only standard library dependencies (json, gzip, sys, pathlib).
Reads a SCIP index formatted as JSON (e.g. from `scip print --json index.scip`).

Output format:
Per file record:
{
  "path": "path/to/file.ext",
  "occurrences": [
    {"line": 10, "start_col": 4, "end_col": 12, "symbol": "scip-symbol", "roles": 1}
  ]
}
Symbol metadata / relationships:
{
  "_meta": "symbols",
  "symbols": {
    "scip-symbol": {
      "is_implementation": ["parent-symbol-1"],
      "is_reference": false
    }
  }
}
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path
from typing import Any


def export_scip_json(raw_json: dict[str, Any], output_path: Path) -> dict[str, int]:
    documents = raw_json.get("documents", [])
    files_count = 0
    occ_count = 0
    symbols_meta: dict[str, dict[str, Any]] = {}

    # Open gzip output
    with gzip.open(output_path, "wt", encoding="utf-8") as out:
        for doc in documents:
            rel_path = doc.get("relative_path") or doc.get("relativePath") or ""
            # Normalise path separators
            rel_path = rel_path.replace("\\", "/")
            raw_occs = doc.get("occurrences", [])
            occurrences = []

            for occ in raw_occs:
                # range: [start_line, start_col, end_col] or [start_line, start_col, end_line, end_col]
                rng = occ.get("range", [])
                symbol = occ.get("symbol", "")
                roles = occ.get("symbol_roles", occ.get("symbolRoles", 0))

                if len(rng) == 3:
                    start_line, start_col, end_col = rng[0], rng[1], rng[2]
                elif len(rng) >= 4:
                    start_line, start_col, _, end_col = rng[0], rng[1], rng[2], rng[3]
                else:
                    continue

                occurrences.append({
                    "line": int(start_line),
                    "start_col": int(start_col),
                    "end_col": int(end_col),
                    "symbol": symbol,
                    "roles": int(roles),
                })
                occ_count += 1

            for sym_info in doc.get("symbols", []):
                sym_name = sym_info.get("symbol")
                if not sym_name:
                    continue
                rels = sym_info.get("relationships", [])
                impls = []
                for r in rels:
                    if r.get("is_implementation") or r.get("isImplementation"):
                        impls.append(r.get("symbol"))
                if sym_name not in symbols_meta:
                    symbols_meta[sym_name] = {"is_implementation": impls}
                else:
                    symbols_meta[sym_name]["is_implementation"].extend(impls)

            file_record = {
                "path": rel_path,
                "occurrences": occurrences,
            }
            out.write(json.dumps(file_record, ensure_ascii=False) + "\n")
            files_count += 1

        # Also check root-level symbols if present
        for sym_info in raw_json.get("symbols", []):
            sym_name = sym_info.get("symbol")
            if not sym_name:
                continue
            rels = sym_info.get("relationships", [])
            impls = []
            for r in rels:
                if r.get("is_implementation") or r.get("isImplementation"):
                    impls.append(r.get("symbol"))
            if sym_name not in symbols_meta:
                symbols_meta[sym_name] = {"is_implementation": impls}
            else:
                symbols_meta[sym_name]["is_implementation"].extend(impls)

        # Write symbol metadata record
        meta_record = {
            "_meta": "symbols",
            "symbols": symbols_meta,
        }
        out.write(json.dumps(meta_record, ensure_ascii=False) + "\n")

    return {"files": files_count, "occurrences": occ_count, "symbols": len(symbols_meta)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Export SCIP JSON index to occ.jsonl.gz")
    parser.add_argument("--input", "-i", type=Path, required=True, help="Input scip JSON file")
    parser.add_argument("--output", "-o", type=Path, required=True, help="Output occ.jsonl.gz file")
    args = parser.parse_args()

    if not args.input.exists():
        print(f"Error: input file {args.input} does not exist", file=sys.stderr)
        return 1

    with args.input.open("r", encoding="utf-8") as f:
        data = json.load(f)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    stats = export_scip_json(data, args.output)
    print(f"Exported {stats['files']} files, {stats['occurrences']} occurrences, {stats['symbols']} symbols -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
