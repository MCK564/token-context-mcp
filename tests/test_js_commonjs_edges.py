import pytest
from token_context_mcp.parse.treesitter import parse_source, SymbolRecord
from token_context_mcp.parse.lexical_edges import build_lexical_edges


def test_commonjs_require_module_match():
    helper_code = b"""
function run() { return 1; }
module.exports = { run };
"""
    app_code = b"""
const Helper = require('./helper');

function start() {
    return Helper.run();
}
"""
    res_helper = parse_source("src/helper.js", helper_code, "javascript")
    res_app = parse_source("src/app.js", app_code, "javascript")

    symbols = res_helper.symbols + res_app.symbols
    calls_by_path = {"src/app.js": res_app.calls}
    js_module_bindings = {
        "src/app.js": res_app.module_bindings,
        "src/helper.js": res_helper.module_bindings,
    }

    edges = build_lexical_edges(
        symbols=symbols,
        source_by_path={},
        calls_by_path=calls_by_path,
        js_module_bindings=js_module_bindings,
    )

    run_edges = [e for e in edges if e.target_name == "run"]
    assert len(run_edges) == 1
    assert run_edges[0].status == "resolved"
    assert "scope:import_module_match" in run_edges[0].evidence
    assert run_edges[0].confidence >= 0.75
    target = next(s for s in symbols if s.symbol_id == run_edges[0].target_symbol_id)
    assert target.path == "src/helper.js"
    assert target.name == "run"


def test_commonjs_destructuring_import_match():
    parser_code = b"""
function parse(text) { return text; }
function format(data) { return data; }
module.exports = { parse, format };
"""
    app_code = b"""
const { parse, format: myFormat } = require('./parser');

function process() {
    const p = parse("hello");
    return myFormat(p);
}
"""
    res_parser = parse_source("src/parser.js", parser_code, "javascript")
    res_app = parse_source("src/app.js", app_code, "javascript")

    symbols = res_parser.symbols + res_app.symbols
    calls_by_path = {"src/app.js": res_app.calls}
    js_module_bindings = {
        "src/app.js": res_app.module_bindings,
        "src/parser.js": res_parser.module_bindings,
    }

    edges = build_lexical_edges(
        symbols=symbols,
        source_by_path={},
        calls_by_path=calls_by_path,
        js_module_bindings=js_module_bindings,
    )

    parse_edges = [e for e in edges if e.target_name == "parse"]
    assert len(parse_edges) == 1
    assert parse_edges[0].status == "resolved"
    assert "scope:import_match" in parse_edges[0].evidence

    format_edges = [e for e in edges if e.target_name == "myFormat"]
    assert len(format_edges) == 1
    assert format_edges[0].status == "resolved"
    assert "scope:import_match" in format_edges[0].evidence


def test_commonjs_relative_path_normalization():
    utils_code = b"""
function check() { return true; }
"""
    route_code = b"""
const utils = require('../utils');

function handle() {
    return utils.check();
}
"""
    res_utils = parse_source("src/utils.js", utils_code, "javascript")
    res_route = parse_source("src/routes/users.js", route_code, "javascript")

    symbols = res_utils.symbols + res_route.symbols
    calls_by_path = {"src/routes/users.js": res_route.calls}
    js_module_bindings = {
        "src/routes/users.js": res_route.module_bindings,
        "src/utils.js": res_utils.module_bindings,
    }

    edges = build_lexical_edges(
        symbols=symbols,
        source_by_path={},
        calls_by_path=calls_by_path,
        js_module_bindings=js_module_bindings,
    )

    check_edges = [e for e in edges if e.target_name == "check"]
    assert len(check_edges) == 1
    assert check_edges[0].status == "resolved"
    assert "scope:import_module_match" in check_edges[0].evidence
    target = next(s for s in symbols if s.symbol_id == check_edges[0].target_symbol_id)
    assert target.path == "src/utils.js"


def test_commonjs_index_resolution():
    logger_code = b"""
function info(msg) { console.log(msg); }
"""
    app_code = b"""
const log = require('./logger');

function run() {
    log.info("started");
}
"""
    res_log = parse_source("src/logger/index.js", logger_code, "javascript")
    res_app = parse_source("src/app.js", app_code, "javascript")

    symbols = res_log.symbols + res_app.symbols
    calls_by_path = {"src/app.js": res_app.calls}
    js_module_bindings = {
        "src/app.js": res_app.module_bindings,
        "src/logger/index.js": res_log.module_bindings,
    }

    edges = build_lexical_edges(
        symbols=symbols,
        source_by_path={},
        calls_by_path=calls_by_path,
        js_module_bindings=js_module_bindings,
    )

    info_edges = [e for e in edges if e.target_name == "info"]
    assert len(info_edges) == 1
    assert info_edges[0].status == "resolved"
    assert "scope:import_module_match" in info_edges[0].evidence
    target = next(s for s in symbols if s.symbol_id == info_edges[0].target_symbol_id)
    assert target.path == "src/logger/index.js"


def test_ts_property_signature_field_type():
    ts_code = b"""
class Service {
    public client: HttpClient;
    run() {
        this.client.fetch();
    }
}
"""
    res = parse_source("src/service.ts", ts_code, "typescript")
    call = next(c for c in res.calls if c.name == "fetch")
    assert call.receiver == "this.client"
    assert call.receiver_type == "HttpClient"
