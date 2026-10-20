"""Tests for evals/scip_export.py."""
import gzip
import json
from pathlib import Path

from evals.scip_export import export_scip_json


def test_scip_export_basic(tmp_path: Path):
    dummy_scip = {
        "documents": [
            {
                "relative_path": "src/App.cs",
                "occurrences": [
                    {
                        "range": [10, 4, 12],
                        "symbol": "scip-dotnet nuget App#Run().",
                        "symbol_roles": 1,
                    },
                    {
                        "range": [20, 8, 20, 16],
                        "symbol": "scip-dotnet nuget Helper#DoWork().",
                        "symbol_roles": 0,
                    },
                ],
                "symbols": [
                    {
                        "symbol": "scip-dotnet nuget App#Run().",
                        "relationships": [
                            {
                                "symbol": "scip-dotnet nuget IApp#Run().",
                                "is_implementation": True,
                            }
                        ],
                    }
                ],
            }
        ]
    }

    out_file = tmp_path / "test.occ.jsonl.gz"
    stats = export_scip_json(dummy_scip, out_file)
    assert stats["files"] == 1
    assert stats["occurrences"] == 2
    assert stats["symbols"] == 1

    lines = []
    with gzip.open(out_file, "rt", encoding="utf-8") as f:
        for line in f:
            lines.append(json.loads(line))

    assert len(lines) == 2
    doc_line = lines[0]
    assert doc_line["path"] == "src/App.cs"
    assert len(doc_line["occurrences"]) == 2
    assert doc_line["occurrences"][0] == {
        "line": 10,
        "start_col": 4,
        "end_col": 12,
        "symbol": "scip-dotnet nuget App#Run().",
        "roles": 1,
    }
    assert doc_line["occurrences"][1] == {
        "line": 20,
        "start_col": 8,
        "end_col": 16,
        "symbol": "scip-dotnet nuget Helper#DoWork().",
        "roles": 0,
    }

    meta_line = lines[1]
    assert meta_line["_meta"] == "symbols"
    assert "scip-dotnet nuget App#Run()." in meta_line["symbols"]
    assert meta_line["symbols"]["scip-dotnet nuget App#Run()."]["is_implementation"] == ["scip-dotnet nuget IApp#Run()."]
