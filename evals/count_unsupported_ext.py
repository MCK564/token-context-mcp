"""Count files with parse_status='unsupported' per extension across index snapshots (M10.2 data).

Read-only: every snapshot is copied to a scratch dir first and queried there, so real
index/WAL files are never opened by SQLite.
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import shutil
import sqlite3
import tempfile

CANDIDATES = {
    "go": [".go"],
    "rust": [".rs"],
    "c/cpp": [".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh"],
    "kotlin": [".kt", ".kts"],
    "php": [".php"],
    "ruby": [".rb"],
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--indexes-dir", required=True, action="append")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    per: dict[str, dict] = {}
    total: collections.Counter[str] = collections.Counter()
    with tempfile.TemporaryDirectory() as scratch:
        for idx_dir in args.indexes_dir:
            for cur in sorted(glob.glob(os.path.join(idx_dir, "*.current.json"))):
                repo = os.path.basename(cur)[: -len(".current.json")]
                ptr = json.load(open(cur, encoding="utf-8"))
                src = os.path.join(idx_dir, os.path.basename(ptr["db"]))
                if not os.path.exists(src):
                    per[repo] = {"error": "snapshot_missing"}
                    continue
                dst = os.path.join(scratch, os.path.basename(src))
                shutil.copyfile(src, dst)
                con = sqlite3.connect(f"file:{dst}?mode=ro", uri=True)
                try:
                    rows = con.execute("select path, parse_status from files").fetchall()
                finally:
                    con.close()
                counter: collections.Counter[str] = collections.Counter()
                for path, status in rows:
                    if status == "unsupported":
                        counter[os.path.splitext(path)[1].lower() or "(none)"] += 1
                per[repo] = {
                    "files": len(rows),
                    "unsupported": sum(counter.values()),
                    "by_extension": dict(sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))),
                }
                total.update(counter)
    candidates = {
        lang: sum(total.get(ext, 0) for ext in exts) for lang, exts in CANDIDATES.items()
    }
    out = {
        "indexes_dirs": args.indexes_dir,
        "repos": per,
        "total_by_extension": dict(sorted(total.items(), key=lambda kv: (-kv[1], kv[0]))),
        "candidate_language_files": candidates,
    }
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    print(json.dumps(candidates))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
