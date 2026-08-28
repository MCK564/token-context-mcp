"""Measure one unchanged-index freshness scan at representative file counts."""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from pathlib import Path

from token_context_mcp.config import AppConfig
from token_context_mcp.index.hashing import sha256_bytes
from token_context_mcp.models import FileRecord
from token_context_mcp.retrieve.service import RetrievalService


def _measure(root: Path, count: int, repetitions: int) -> dict[str, float | int | str]:
    raw = b"pass\n"
    digest = sha256_bytes(raw)
    root.mkdir(parents=True, exist_ok=True)
    records: list[FileRecord] = []
    for index in range(count):
        path = root / f"file_{index:05d}.py"
        path.write_bytes(raw)
        stat = path.stat()
        records.append(
            FileRecord(
                path=path.name,
                sha256=digest,
                size=len(raw),
                mtime_ns=stat.st_mtime_ns,
                language="python",
                parse_status="parsed",
                warnings=[],
            )
        )
    service = RetrievalService(AppConfig(repositories={}), root / "repos.toml")
    service._freshness(root, records)
    elapsed_ms: list[float] = []
    for _ in range(repetitions):
        started = time.perf_counter()
        result = service._freshness(root, records)
        elapsed_ms.append((time.perf_counter() - started) * 1000)
        if result != "fresh":
            raise RuntimeError(f"expected fresh result for {count} unchanged files, got {result}")
    median_ms = statistics.median(elapsed_ms)
    return {
        "files": count,
        "median_ms": round(median_ms, 3),
        "per_file_us": round(median_ms * 1000 / count, 3),
        "scan": "unchanged files; stat/path-validation fast path",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--counts", nargs="+", type=int, default=[1000, 10000, 25000])
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()
    if args.repetitions < 1 or any(count < 1 for count in args.counts):
        raise SystemExit("counts and repetitions must be positive")
    with tempfile.TemporaryDirectory(prefix="token-context-freshness-") as directory:
        root = Path(directory)
        measurements = [_measure(root / str(count), count, args.repetitions) for count in args.counts]
    print(json.dumps(measurements, indent=2))


if __name__ == "__main__":
    main()
