"""Guards for audit items BUG-08 (multi-byte source), BUG-12 (overloads) and BUG-14 (CRLF).

All three were reported as defects but do not reproduce: byte offsets are sliced on the raw bytes before
decoding, overloaded and ``#if``-duplicated members get distinct symbol ids, and CRLF files give the same
spans, signatures and bodies as LF files. These tests pin that behaviour.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from token_context_mcp.config import AppConfig, RepositoryConfig, ServerConfig, load_config, save_config
from token_context_mcp.index.runner import build_index
from token_context_mcp.retrieve.service import RetrievalService

SOURCES = {
    "u.py": '# Chào thế giới 🌏 日本語\nVN = "Việt Nam 🇻🇳"\n\n\ndef xin_chao(ten):\n    """Lời chào: Tiếng Việt 😀"""\n    return "Xin chào " + ten\n\n\nclass Lớp:\n    def phương_thức(self):\n        return "ñ"\n',
    "u.js": '// Chào 🌏 日本語\nconst s = "Việt Nam 😀";\nfunction xinChao(ten) {\n  return "Xin chào " + ten;\n}\nclass Lop {\n  phuongThuc() { return "ñ😀"; }\n}\n',
    "U.java": 'package p;\n// Chào 🌏 日本語\npublic class U {\n  String s = "Việt Nam 😀";\n  void process(int x) { }\n  void process(String x) { }\n  void process(int x, int y) { }\n}\n',
    "U.cs": 'namespace P {\n// Chào 🌏 日本語\npublic class U {\n  string s = "Việt Nam 😀";\n  void Process(int x) { }\n  void Process(string x) { }\n#if DEBUG\n  void Cond() { }\n#else\n  void Cond() { }\n#endif\n}\n}\n',
    "u.go": 'package p\n\n// Chào 🌏 日本語\nfunc XinChao(ten string) string {\n\treturn "Xin chào " + ten\n}\n',
}


def _service(tmp_path: Path, name: str, newline: str) -> RetrievalService:
    root = tmp_path / name
    root.mkdir()
    for file_name, text in SOURCES.items():
        (root / file_name).write_bytes(text.replace("\n", newline).encode("utf-8"))
    config = tmp_path / f"{name}-config" / "repos.toml"
    repo = RepositoryConfig(repo_id="u", root=root.resolve())
    save_config(config, AppConfig(repositories={"u": repo}, server=ServerConfig()))
    build_index(repo, config.parent / "indexes", network_policy="declared-deny-not-enforced")
    return RetrievalService(load_config(config), config)


def _symbols(service: RetrievalService) -> list[dict[str, Any]]:
    found = service.find_symbols("u", pattern="*", limit=100)["data"]["symbols"]
    rows = []
    for symbol in sorted(found, key=lambda item: (item["path"], item["start_line"])):
        context = service.symbol_context("u", symbol_id=symbol["symbol_id"], depth=0, include_body=True, max_tokens=2048)
        rows.append({**symbol, "body": context["data"]["symbols"][0]["content"]})
    return rows


@pytest.fixture(scope="module")
def lf_symbols(tmp_path_factory: pytest.TempPathFactory) -> list[dict[str, Any]]:
    return _symbols(_service(tmp_path_factory.mktemp("lf"), "repo", "\n"))


@pytest.fixture(scope="module")
def crlf_symbols(tmp_path_factory: pytest.TempPathFactory) -> list[dict[str, Any]]:
    return _symbols(_service(tmp_path_factory.mktemp("crlf"), "repo", "\r\n"))


def test_multibyte_source_bodies_match_their_line_spans(lf_symbols: list[dict[str, Any]]) -> None:
    assert len(lf_symbols) == 16
    for symbol in lf_symbols:
        lines = SOURCES[symbol["path"]].split("\n")
        expected = "\n".join(lines[symbol["start_line"] - 1 : symbol["end_line"]]).strip()
        assert symbol["body"] == expected, (symbol["path"], symbol["qualified_name"])


def test_overloaded_and_conditional_members_keep_distinct_ids(lf_symbols: list[dict[str, Any]]) -> None:
    ids = [symbol["symbol_id"] for symbol in lf_symbols]
    assert len(set(ids)) == len(ids)
    names = [(s["path"], s["qualified_name"]) for s in lf_symbols]
    assert names.count(("U.java", "U.process")) == 3
    assert names.count(("U.cs", "U.Process")) == 2
    assert names.count(("U.cs", "U.Cond")) == 2
    bodies = {s["body"] for s in lf_symbols if s["qualified_name"] == "U.process"}
    assert bodies == {"void process(int x) { }", "void process(String x) { }", "void process(int x, int y) { }"}


def test_crlf_files_give_the_same_spans_signatures_and_bodies(
    lf_symbols: list[dict[str, Any]], crlf_symbols: list[dict[str, Any]]
) -> None:
    assert len(crlf_symbols) == len(lf_symbols)
    for lf, crlf in zip(lf_symbols, crlf_symbols):
        assert (crlf["path"], crlf["qualified_name"], crlf["start_line"], crlf["end_line"]) == (
            lf["path"], lf["qualified_name"], lf["start_line"], lf["end_line"],
        )
        assert "\r" not in crlf["signature"] and "\r" not in crlf["body"]
        assert crlf["signature"] == lf["signature"]
        assert crlf["body"] == lf["body"]
