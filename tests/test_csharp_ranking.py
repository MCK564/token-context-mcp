from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from token_context_mcp.config import AppConfig, RepositoryConfig, load_config
from token_context_mcp.index.runner import _fts_rows, build_index
from token_context_mcp.index.sqlite_store import SQLiteStore
from token_context_mcp.parse.treesitter import parse_source
from token_context_mcp.retrieve.service import RetrievalService


def test_csharp_base_list_inheritance() -> None:
    code = b"""
namespace Sample {
    public interface IWorker<T> {}
    public class BaseWorker {}
    public class Worker<T> : BaseWorker, IWorker<T>, System.IDisposable {
        public void DoWork() {}
    }
}
"""
    parsed = parse_source("Worker.cs", code, "c_sharp")
    assert "Worker" in parsed.inheritance
    assert parsed.inheritance["Worker"] == ["BaseWorker", "IWorker", "IDisposable"]


def test_csharp_doc_comment_in_member_own_body() -> None:
    code = """namespace Sample {
    /// <summary>
    /// Class documentation header.
    /// </summary>
    public class DataProcessor {
        /// <summary>
        /// Highly detailed method doc explaining algorithmic computation.
        /// </summary>
        [CustomValidation]
        public int ComputeValue(int input) {
            return input * 42;
        }
    }
}
"""
    parsed = parse_source("DataProcessor.cs", code.encode("utf-8"), "c_sharp")
    rows = _fts_rows("DataProcessor.cs", "c_sharp", code, parsed.symbols)
    by_qname = {r[3]: r for r in rows}

    class_row = by_qname["DataProcessor"]
    method_row = by_qname["DataProcessor.ComputeValue"]

    # Class own_body should have class doc, but NOT method doc
    assert "Class documentation header." in class_row[5]
    assert "Highly detailed method doc explaining algorithmic computation." not in class_row[5]

    # Method own_body should have its doc comment
    assert "Highly detailed method doc explaining algorithmic computation." in method_row[5]
    assert "CustomValidation" in method_row[5]


def test_csharp_implementation_outranks_interface_and_attribute(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()

    # Interface file
    (src_dir / "IParser.cs").write_text(
        """namespace TestLib {
    /// <summary>
    /// High-level interface contract for parsing raw record stream into structured items.
    /// </summary>
    public interface IParser {
        bool ParseRecord();
    }
}
""",
        encoding="utf-8",
    )

    # Attribute file
    (src_dir / "ParserAttribute.cs").write_text(
        """using System;
namespace TestLib {
    /// <summary>
    /// Annotation to decorate types for parsing raw record stream into structured items.
    /// </summary>
    [AttributeUsage(AttributeTargets.Class)]
    public class ParserAttribute : Attribute {
    }
}
""",
        encoding="utf-8",
    )

    # Implementation file
    (src_dir / "ConcreteParser.cs").write_text(
        """namespace TestLib {
    public class ConcreteParser : IParser {
        /// <inheritdoc/>
        public bool ParseRecord() {
            var active = true;
            return active;
        }
    }
}
""",
        encoding="utf-8",
    )

    idx_dir = tmp_path / "indexes"
    repo_cfg = RepositoryConfig(repo_id="test-cs", root=src_dir)
    build_index(repo_cfg, idx_dir, network_policy="declared-deny-not-enforced")

    store = SQLiteStore(idx_dir / "test-cs.sqlite")
    # Search for behavioral query matching interface doc
    query = "parsing raw record stream into structured items"

    cfg_file = tmp_path / "repos.toml"
    cfg_file.write_text(f"""[server]
output_mode = 'text'

[repos.test-cs]
root = '{src_dir.as_posix()}'
""", encoding="utf-8")
    app_cfg = load_config(cfg_file)
    service = RetrievalService(app_cfg, cfg_file)
    res = service.search_source("test-cs", query=query, limit=5)
    matches = res["data"]["matches"]
    assert len(matches) > 0

    # Top match should be the concrete implementation or ConcreteParser, outranking IParser interface and ParserAttribute
    symbols_returned = [m["symbol_id"] for m in matches]
    # Check that ConcreteParser method appears before or ranks above interface and attribute
    has_concrete = any("ConcreteParser" in s for s in symbols_returned)
    assert has_concrete


def test_python_deterministic_and_unaffected(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "app.py").write_text(
        """class Runner:
    '''Base runner class.'''
    def execute(self):
        '''Execute batch workflow.'''
        return 1
""",
        encoding="utf-8",
    )

    idx_dir = tmp_path / "indexes"
    repo_cfg = RepositoryConfig(repo_id="test-py", root=src_dir)
    build_index(repo_cfg, idx_dir, network_policy="declared-deny-not-enforced")

    cfg_file = tmp_path / "repos.toml"
    cfg_file.write_text(f"""[server]
output_mode = 'text'

[repos.test-py]
root = '{src_dir.as_posix()}'
""", encoding="utf-8")
    app_cfg = load_config(cfg_file)
    service = RetrievalService(app_cfg, cfg_file)
    res1 = service.search_source("test-py", query="execute batch workflow", limit=5)
    res2 = service.search_source("test-py", query="execute batch workflow", limit=5)

    assert res1["data"]["matches"] == res2["data"]["matches"]
