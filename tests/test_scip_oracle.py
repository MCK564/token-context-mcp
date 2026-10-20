"""Tests for evals/scip_to_gold.py and evals/edge_oracle_eval.py."""
import gzip
import json
from pathlib import Path

from evals.scip_to_gold import extract_call_sites_from_tree, _find_identifier_node
from token_context_mcp.parse.treesitter import _load_language, _new_parser


def test_extract_call_sites_csharp():
    code = b"""
    using System;
    namespace Test {
        public class MyService {
            public void Run() {
                var helper = new Helper();
                helper.Execute();
            }
        }
    }
    """
    lang = _load_language("c_sharp")
    parser = _new_parser(lang)
    tree = parser.parse(code)
    sites = extract_call_sites_from_tree(tree.root_node, code, "c_sharp")
    assert len(sites) == 2
    types = {s["call_type"] for s in sites}
    names = {s["callee_name"] for s in sites}
    assert "object_creation_expression" in types
    assert "invocation_expression" in types
    assert "Helper" in names
    assert "Execute" in names


def test_extract_call_sites_java():
    code = b"""
    package com.example;
    public class MyService {
        public void run() {
            Helper h = new Helper();
            h.execute();
            super.toString();
        }
    }
    """
    lang = _load_language("java")
    parser = _new_parser(lang)
    tree = parser.parse(code)
    sites = extract_call_sites_from_tree(tree.root_node, code, "java")
    assert len(sites) == 3
    names = {s["callee_name"] for s in sites}
    assert "Helper" in names
    assert "execute" in names
    assert "toString" in names
