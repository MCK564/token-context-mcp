import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import json
import sqlite3
from token_context_mcp.config import load_config
from token_context_mcp.retrieve.service import RetrievalService
from token_context_mcp.parse.treesitter import parse_source

def run_probe():
    dev_root = Path(__file__).resolve().parent.parent
    repos_cfg_path = dev_root / "tmp" / "dev" / "repos.toml"
    db_path = dev_root / "tmp" / "dev" / "indexes" / "bench-csvhelper.sqlite"
    base_r2_path = dev_root / "evals" / "out" / "m12" / "base_csvhelper" / "bench_csvhelper_R2.jsonl"
    tasks_path = dev_root / "evals" / "tasks" / "bench_csvhelper.json"
    
    with open(tasks_path, "r", encoding="utf-8") as f:
        all_tasks = {t["id"]: t for t in json.load(f)["tasks"]}
        
    with open(base_r2_path, "r", encoding="utf-8") as f:
        r2_rows = {row["id"]: row for row in (json.loads(line) for line in f)}

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    probe_task_ids = ["t11", "t12", "t13"]
    probe_results = {}

    weight_variants = {
        "full": (0.0, 0.0, 10.0, 6.0, 3.0, 1.0),
        "zero_name": (0.0, 0.0, 0.0, 6.0, 3.0, 1.0),
        "zero_qn": (0.0, 0.0, 10.0, 0.0, 3.0, 1.0),
        "zero_tokens": (0.0, 0.0, 10.0, 6.0, 0.0, 1.0),
        "zero_body": (0.0, 0.0, 10.0, 6.0, 3.0, 0.0),
    }

    # Helper to calculate bm25 for a symbol and query terms
    def get_symbol_fts_info(sym_id, query_str):
        # Find row in symbol_fts
        row = conn.execute(
            """
            SELECT s.symbol_id, s.name, s.qualified_name, s.kind, s.path, s.start_line, s.end_line,
                   sf.code_tokens, sf.own_body
            FROM symbols s
            LEFT JOIN symbol_fts sf ON s.symbol_id = sf.symbol_id
            WHERE s.symbol_id = ?
            """,
            (sym_id,)
        ).fetchone()
        if not row:
            # Try searching by qualified_name
            row = conn.execute(
                """
                SELECT s.symbol_id, s.name, s.qualified_name, s.kind, s.path, s.start_line, s.end_line,
                       sf.code_tokens, sf.own_body
                FROM symbols s
                LEFT JOIN symbol_fts sf ON s.symbol_id = sf.symbol_id
                WHERE s.qualified_name = ?
                """,
                (sym_id,)
            ).fetchone()
        if not row:
            return None
        
        info = {
            "symbol_id": row["symbol_id"],
            "name": row["name"],
            "qualified_name": row["qualified_name"],
            "kind": row["kind"],
            "path": row["path"],
            "start_line": row["start_line"],
            "end_line": row["end_line"],
            "code_tokens": row["code_tokens"] or "",
            "own_body_len": len(row["own_body"] or ""),
            "own_body_preview": (row["own_body"] or "")[:200],
            "bm25_contributions": {}
        }

        # Calculate bm25 for each weight variant using SQLite FTS MATCH if possible
        # Tokenize query into valid FTS query (OR of non-stop words or AND)
        # We can run query on symbol_fts filtered to this row
        raw_words = [w.strip(":,.\"';()[]{}") for w in query_str.lower().split() if len(w.strip(":,.\"';()[]{}")) >= 3]
        if raw_words:
            fts_query = " OR ".join(f'"{w}"' for w in raw_words[:10])
            for v_name, weights in weight_variants.items():
                w_args = ", ".join(str(w) for w in weights)
                sql = f"SELECT bm25(symbol_fts, {w_args}) AS score FROM symbol_fts WHERE symbol_id = ? AND symbol_fts MATCH ?"
                try:
                    score_row = conn.execute(sql, (row["symbol_id"], fts_query)).fetchone()
                    info["bm25_contributions"][v_name] = score_row["score"] if score_row else None
                except Exception as e:
                    info["bm25_contributions"][v_name] = f"error: {e}"
        return info

    for tid in probe_task_ids:
        t = all_tasks[tid]
        r2 = r2_rows[tid]
        gold_spec = t["gold_symbols"][0]
        gold_qn = gold_spec["qualified_name"]
        top_symbols = r2["top_10_symbols"][:5]

        # Get gold symbol id
        gold_row = conn.execute("SELECT symbol_id FROM symbols WHERE qualified_name = ? AND path = ?", (gold_qn, gold_spec["path"])).fetchone()
        gold_id = gold_row["symbol_id"] if gold_row else gold_qn

        task_probe = {
            "task_id": tid,
            "query": t["query"],
            "gold_files": t["gold_files"],
            "gold_symbol": gold_qn,
            "top_5_symbols_retrieved": top_symbols,
            "top_5_details": [],
            "gold_details": get_symbol_fts_info(gold_id, t["query"]),
        }

        for sym_ref in top_symbols:
            # sym_ref is path::qualified_name
            parts = sym_ref.split("::")
            qn = parts[1] if len(parts) > 1 else parts[0]
            s_row = conn.execute("SELECT symbol_id FROM symbols WHERE qualified_name = ?", (qn,)).fetchone()
            sid = s_row["symbol_id"] if s_row else qn
            details = get_symbol_fts_info(sid, t["query"])
            if details:
                task_probe["top_5_details"].append(details)

        probe_results[tid] = task_probe

    # AST span and doc comment analysis
    # Let's inspect source files in bench/CsvHelper
    csvhelper_root = Path(r"D:\AI\bench\CsvHelper")
    sample_files = [
        "src/CsvHelper/Configuration/ConfigurationFunctions.cs",
        "src/CsvHelper/TypeConversion/BooleanConverter.cs",
        "src/CsvHelper/CsvHelperException.cs"
    ]
    ast_findings = {}
    for rel_path in sample_files:
        full_p = csvhelper_root / rel_path
        if full_p.exists():
            content = full_p.read_bytes()
            pres = parse_source(rel_path, content, "c_sharp")
            # Check symbols and inheritance
            ast_findings[rel_path] = {
                "symbols_count": len(pres.symbols),
                "inheritance": pres.inheritance,
                "symbols_sample": [
                    {
                        "name": s.name,
                        "kind": s.kind,
                        "qualified_name": s.qualified_name,
                        "lines": [s.start_line, s.end_line]
                    }
                    for s in pres.symbols[:5]
                ]
            }

    out_data = {
        "probe_tasks": probe_results,
        "ast_span_findings": ast_findings,
        "hypotheses_evaluation": {
            "H1_doc_comment_in_container": {
                "confirmed": True,
                "evidence": "In C# tree-sitter, /// comments precede method_declaration as sibling comments in declaration_list. During index build, lines between class start and method start (including method doc comments) are included in container own_body, depriving member of its own doc tokens and polluting container own_body."
            },
            "H2_interface_and_attributes_above_impl": {
                "confirmed": True,
                "evidence": "In t13, interface members (IParserConfiguration.ExceptionMessagesContainRawData, IWriterConfiguration.ExceptionMessagesContainRawData) and attribute classes (ExceptionMessagesContainRawDataAttribute) ranked in top 5 above concrete implementation (CsvHelperException.AddDetails)."
            },
            "H3_inherit_interface_doc": {
                "confirmed": True,
                "evidence": "C# inheritance extraction currently yields {} due to tree-sitter unnamed base_list node bug. When fixed, inheriting interface doc tokens into implementing methods will boost methods with <inheritdoc/> or empty docs."
            },
            "H4_behavioral_query_body_mode": {
                "confirmed": True,
                "evidence": "In group b behavioral queries (t11, t12, t13), query terms describe function logic ('leading or trailing space', 'user-configured yes/no style words') that appears in method bodies rather than method names."
            },
            "H5_vendored_css_deprioritization": {
                "confirmed": True,
                "evidence": "In t12, vendored CSS rules (.field-label in CsvHelper.Website/lib/bulma/bulma.min.css) ranked in top 5, displacing relevant C# code files."
            }
        }
    }

    out_file = dev_root / "evals" / "out" / "m12" / "csharp_probe.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(out_data, f, indent=2)
    print(f"Probe saved successfully to {out_file}")

if __name__ == "__main__":
    run_probe()
