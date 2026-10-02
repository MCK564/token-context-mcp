"""Guards PARSER_ARTIFACT_VERSION (M7): snapshots cache what ``parse_source`` returns per file, so any change of
that output for the same bytes must come with a version bump (otherwise old artifacts would be trusted).

If this test fails: you changed the parser output.  Bump ``PARSER_ARTIFACT_VERSION`` in
``src/token_context_mcp/parse/treesitter.py``, then update GOLDEN below (run this file to see the new digest) and
mention the bump in CHANGELOG.md ("first index after upgrading re-parses every file").
"""
from __future__ import annotations

import dataclasses
import hashlib
import json

from token_context_mcp.parse.treesitter import PARSER_ARTIFACT_VERSION, CallRecord, parse_source

# (PARSER_ARTIFACT_VERSION, digest of the parse of SAMPLES).  Update both together.
GOLDEN = (9, "4515da0c86240aa7f8271f2557c27bb612c93ab2652314be08c17a048385998f")

SAMPLES = {
    "python": (
        "s.py",
        "import os\nfrom pkg.mod import helper as h\n\n\nclass Base:\n    def run(self) -> int:\n        return self.step()\n\n"
        "    def step(self) -> int:\n        return h(1)\n\n\nclass Child(Base):\n    def __init__(self, svc: Base) -> None:\n"
        "        self.svc = svc\n\n    def go(self):\n        x = Base()\n        x.run()\n        return self.svc.step()\n\n\n"
        "def main():\n    return Child(Base()).go()\n\n\nif __name__ == '__main__':\n    main()\n",
    ),
    "typescript": (
        "s.ts",
        "import { a } from './a';\nexport class Box<T> extends Base {\n  get(): T { return a(this.value); }\n}\n"
        "export function make(): Box<number> { return new Box<number>(); }\n",
    ),
    "java": (
        "S.java",
        "package p;\nimport java.util.List;\npublic class S extends B implements I {\n  public int f(List<String> xs) { return g(xs.size()); }\n"
        "  private int g(int n) { return n + 1; }\n}\n",
    ),
    "c_sharp": (
        "S.cs",
        "using System;\nnamespace N { public class S : B { public int F(int n) { return G(n); } private int G(int n) => n + 1; } }\n",
    ),
    "javascript": (
        "s.js",
        "const x = require('x');\nfunction a(n) { return b(n) + 1; }\nfunction b(n) { return x.c(n); }\nclass K extends J { m() { return a(1); } }\n",
    ),
    "go": (
        "s.go",
        "package p\n\nimport \"fmt\"\n\ntype S struct{}\n\nfunc (s *S) F(n int) int { return s.g(n) }\n\nfunc (s S) g(n int) int { fmt.Println(n); return n + 1 }\n\nfunc Main() int { return (&S{}).F(1) }\n",
    ),
}


def _digest() -> str:
    payload = {}
    for language, (path, source) in SAMPLES.items():
        parsed = parse_source(path, source.encode("utf-8"), language)
        payload[language] = {
            "language": parsed.language,
            "symbols": [dataclasses.astuple(symbol) for symbol in parsed.symbols],
            "imports": parsed.imports,
            "calls": [dataclasses.astuple(call) for call in parsed.calls],
            "inheritance": parsed.inheritance,
            "warnings": parsed.warnings,
        }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def test_parser_output_is_pinned_to_the_artifact_version() -> None:
    assert (PARSER_ARTIFACT_VERSION, _digest()) == GOLDEN, (
        "parse_source output changed: bump PARSER_ARTIFACT_VERSION and update GOLDEN "
        f"(new value: {(PARSER_ARTIFACT_VERSION, _digest())!r})"
    )


def test_call_record_layout_is_serialised_positionally() -> None:
    # runner._calls_to_json stores dataclasses.astuple(call); a new field means a new artifact format.
    assert [f.name for f in dataclasses.fields(CallRecord)] == [
        "name", "receiver", "line", "start_byte", "end_byte", "receiver_type", "is_tainted",
        "assigned_from_fn", "receiver_type_source", "arg_count", "arg_types", "chain", "call_kind",
    ]
