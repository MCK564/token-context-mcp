"""M10.4: the benchmark harness is tested on fake data before it is frozen (nothing here touches a real repository)."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "evals"))

import bench_retrieval as br  # noqa: E402
from make_synthetic_repo import create_temp_config  # noqa: E402

FILES = {
    "shop/__init__.py": "",
    "shop/cart.py": (
        "class Cart:\n    def add_item(self, sku, qty):\n        self.items.append((sku, qty))\n\n"
        "    def total_price(self):\n        return compute_total(self.items)\n"
    ),
    "shop/pricing.py": (
        "def compute_total(items):\n    return sum(price_of(sku) * qty for sku, qty in items)\n\n\n"
        "def price_of(sku):\n    return 10\n"
    ),
    "shop/tax.py": "def apply_tax(amount):\n    return amount * 1.2\n",
    "shop/mailer.py": "def send_receipt(order):\n    return f'receipt {order}'\n",
    "docs/notes.txt": "cart cart cart pricing\n",
}


def test_query_terms_split_identifiers_and_drop_short_words():
    assert br.query_terms("computeTotal of the cart in it") == ["compute", "total", "computetotal", "the", "cart"]
    assert br.query_terms("") == []


def test_term_regex_respects_identifier_boundaries():
    pattern = br.term_regex("wrap")
    assert pattern.search("x = wrap(text)")
    assert pattern.search("Text.WRAP")
    assert not pattern.search("wrap_lines")
    assert not pattern.search("rewrap")


def make_corpus() -> br.Corpus:
    files = {p: t for p, t in FILES.items() if p.endswith(".py")}
    symbols = [
        ("shop/cart.py", "Cart", 1, 6),
        ("shop/cart.py", "Cart.add_item", 2, 3),
        ("shop/cart.py", "Cart.total_price", 5, 6),
        ("shop/pricing.py", "compute_total", 1, 2),
        ("shop/pricing.py", "price_of", 5, 6),
    ]
    return br.Corpus(files, symbols)


def test_grep_rank_orders_by_idf_and_picks_the_innermost_symbol():
    corpus = make_corpus()
    ranking = br.grep_rank(corpus, "compute_total total_price")
    top = ranking["ranked"][0]
    assert top["path"] in {"shop/pricing.py", "shop/cart.py"}
    assert top["score"] >= ranking["ranked"][-1]["score"]
    by_path = {r["path"]: r for r in ranking["ranked"]}
    assert by_path["shop/pricing.py"]["symbol"] == "compute_total"
    assert by_path["shop/cart.py"]["symbol"] == "Cart.total_price"  # innermost, not the class
    assert "shop/tax.py" not in by_path  # no term matches
    assert br.term_regex("total").search("Cart.total_price") is None  # "total" is not a whole word there
    # deterministic
    assert br.grep_rank(corpus, "compute_total total_price") == ranking


def test_grep_output_is_rg_like_with_context_and_line_cap():
    corpus = make_corpus()
    r0 = br.run_r0(corpus, "price_of")
    lines = r0["text"].split("\n")
    assert lines[0].startswith("shop/")
    assert any(line.startswith("shop/pricing.py:5:def price_of") for line in lines)
    assert r0["tokens"] == br.tokens_of(r0["text"])
    big = br.Corpus({"big.py": "\n".join("token here" for _ in range(1000))}, [])
    assert len(br.run_r0(big, "token")["lines"]) == br.MAX_LINES_PER_FILE


def test_cut_to_tokens_is_a_prefix_within_the_budget():
    corpus = make_corpus()
    r0 = br.run_r0(corpus, "compute total price cart")
    full = r0["tokens"]
    assert full > 10
    for budget in (5, 20, full, full + 100):
        cut = br.cut_to_tokens(corpus, r0, budget)
        assert cut["tokens"] <= budget
    everything = br.cut_to_tokens(corpus, r0, full + 100)
    assert everything["lines"] == len(r0["lines"])
    tiny = br.cut_to_tokens(corpus, r0, 12)
    assert tiny["lines"] < everything["lines"]
    # files that vanish from the cut are the lowest ranked ones
    kept_paths = [i["path"] for i in tiny["items"]]
    ranked = [i["path"] for i in r0["ranking"]["ranked"]]
    assert kept_paths == ranked[: len(kept_paths)]


def test_read_top_counts_whole_files():
    corpus = make_corpus()
    r0 = br.run_r0(corpus, "compute total price cart")
    read = br.read_top(corpus, r0)
    assert read["tokens"] == sum(br.tokens_of(corpus.files[i["path"]]) for i in read["items"])
    assert len(read["items"]) <= br.READ_FILES


def test_bootstrap_is_deterministic_and_bounded():
    values = [0.0, 1.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0]
    first = br.bootstrap_ci(values)
    assert first == br.bootstrap_ci(values)
    assert 0.0 <= first[0] <= 0.625 <= first[1] <= 1.0
    assert br.bootstrap_ci([]) is None
    same = br.bootstrap_ci([0.5] * 6)
    assert same == [0.5, 0.5]


def test_paired_diff_matches_by_task_id():
    a = [{"id": "1", "m": 1.0}, {"id": "2", "m": 1.0}]
    b = [{"id": "2", "m": 0.0}, {"id": "1", "m": 1.0}]
    result = br.paired_diff(a, b, "m")
    assert result["mean"] == 0.5 and result["pairs"] == 2


@pytest.fixture
def bench_env(tmp_path):
    repo = tmp_path / "shop-repo"
    for rel, text in FILES.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    config = create_temp_config(repo, tmp_path / "cfg" / "repos.toml", repo_id="shop")
    done = subprocess.run(
        [sys.executable, "-m", "token_context_mcp", "index", "--repo-id", "shop", "--config", str(config)],
        capture_output=True, text=True, timeout=120,
    )
    assert done.returncode == 0, done.stderr
    spec = {
        "repo_id": "shop", "repo_url": "https://example.invalid/shop", "tag": "v0", "commit_sha": "0" * 40, "license": "MIT",
        "reviewed": True, "review_note": "fake data for the harness test",
        "tasks": [
            {"id": "t1", "group": "a_keyword", "split": "test", "query": "compute total of items",
             "gold_files": ["shop/pricing.py"], "gold_symbols": [{"path": "shop/pricing.py", "qualified_name": "compute_total"}]},
            {"id": "t2", "group": "b_hidden_dep", "split": "test", "query": "multiply the amount by a rate",
             "gold_files": ["shop/tax.py"], "gold_symbols": [{"path": "shop/tax.py", "qualified_name": "apply_tax"}]},
            {"id": "t3", "group": "c_multi_file", "split": "test", "query": "cart total price",
             "gold_files": ["shop/cart.py", "shop/pricing.py"],
             "gold_symbols": [{"path": "shop/cart.py", "qualified_name": "Cart.total_price"}]},
        ],
        "packet_tasks": [
            {"id": "p1", "split": "test", "target": {"path": "shop/cart.py", "qualified_name": "Cart.total_price"},
             "gold_context": [{"path": "shop/pricing.py", "qualified_name": "compute_total", "need": "signature", "why": "callee"}]},
        ],
    }
    tasks_file = tmp_path / "bench_shop.json"
    tasks_file.write_text(json.dumps(spec), encoding="utf-8")
    return config, tasks_file, tmp_path / "out"


def test_refuses_an_unreviewed_task_set(bench_env, capsys):
    config, tasks_file, out = bench_env
    spec = json.loads(tasks_file.read_text())
    spec["reviewed"] = False
    tasks_file.write_text(json.dumps(spec))
    code = br.run(argparse.Namespace(tasks=tasks_file, config=config, repo_id=None, name="shop", out_dir=out))
    assert code == 3
    assert not out.exists() or not list(out.glob("bench_shop_*"))


def test_end_to_end_on_a_fake_repository(bench_env):
    config, tasks_file, out = bench_env
    code = br.run(argparse.Namespace(tasks=tasks_file, config=config, repo_id=None, name="shop", out_dir=out))
    assert code == 0
    summary = json.loads((out / "bench_shop_summary.json").read_text())
    assert set(summary["arms"]) == set(br.ARMS)
    assert summary["reviewed"] is True and summary["token_context_version"] == __import__("token_context_mcp").__version__
    assert summary["corpus_files"] == 5  # the .txt is unsupported and stays out of the corpus
    for arm in br.ARMS:
        rows = [json.loads(line) for line in (out / f"bench_shop_{arm}.jsonl").read_text().splitlines()]
        assert [r["id"] for r in rows] == ["t1", "t2", "t3"]
        assert all(len(r["latencies_ms"]) == br.LATENCY_REPS - 1 for r in rows)
    # same-cost baseline never spends more than R2
    r2 = {json.loads(l)["id"]: json.loads(l) for l in (out / "bench_shop_R2.jsonl").read_text().splitlines()}
    cut = {json.loads(l)["id"]: json.loads(l) for l in (out / "bench_shop_R0-grep@R2.jsonl").read_text().splitlines()}
    assert all(cut[i]["wire_tokens"] <= r2[i]["wire_tokens"] for i in r2)
    # t1 is a keyword task: grep must find the file
    r0 = {json.loads(l)["id"]: json.loads(l) for l in (out / "bench_shop_R0-grep.jsonl").read_text().splitlines()}
    assert r0["t1"]["file_acc_at_5"] == 1.0
    assert (out / "bench_shop_R3.jsonl").exists()
    assert summary["r3"]["tasks"] == 1
    assert set(summary["kpis"]) >= {"same_cost_file_acc_at_5_R2_minus_R0grepR2", "file_acc_at_5_R2_minus_R0grep", "token_ratio_R2_over_R0grep", "R2_vs_R1", "R3"}
    assert summary["by_group"]["a_keyword"]["R2"]["tasks"] == 1


def test_results_are_reproducible(bench_env):
    config, tasks_file, out = bench_env
    ns = lambda name: argparse.Namespace(tasks=tasks_file, config=config, repo_id=None, name=name, out_dir=out)  # noqa: E731
    assert br.run(ns("one")) == 0 and br.run(ns("two")) == 0
    a = json.loads((out / "bench_one_summary.json").read_text())
    b = json.loads((out / "bench_two_summary.json").read_text())
    def strip_latency(node):
        if isinstance(node, dict):
            return {k: strip_latency(v) for k, v in node.items() if not k.startswith("latency")}
        return node

    a, b = strip_latency(a), strip_latency(b)
    a["benchmark"] = b["benchmark"] = ""
    assert a == b


def test_heldout_role_triggers_rule17_guard(bench_env, tmp_path, monkeypatch):
    import guard

    monkeypatch.setattr(guard, "REPO_ROOT", tmp_path)  # a directory with no git repo: no freeze tag, whatever the real repo holds
    config, tasks_file, out = bench_env
    ns = argparse.Namespace(
        tasks=tasks_file,
        config=config,
        repo_id=None,
        name="shop",
        out_dir=out,
        role="heldout",
        allow_baseline_code=None,
    )
    with pytest.raises(RuntimeError, match="Rule 17 violation"):
        br.run(ns)
