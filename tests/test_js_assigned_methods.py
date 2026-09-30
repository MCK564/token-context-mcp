from __future__ import annotations

import pytest
from token_context_mcp.parse.treesitter import parse_source, SymbolRecord
from token_context_mcp.parse.lexical_edges import build_lexical_edges


def test_js_prototype_assigned_method_patterns() -> None:
    source = b"""
function Reply(res, context, log) {
    this.res = res;
    this.send = function (payload) { return payload; };
}

Reply.prototype.header = function (key, value) {
    return this;
};

Reply.prototype.code = (statusCode) => {
    return this;
};

Reply.prototype = {
    redirect(url) {},
    type: function (contentType) {},
    done: () => {}
};

Reply.build = function () {};
Reply.prototype.count = 0;

Object.defineProperty(Reply.prototype, 'sent', {
    get() { return true; },
    set(v) {}
});

Object.defineProperties(Reply.prototype, {
    elapsedTime: {
        get() { return 10; }
    }
});

module.exports.helper = function (x) {};
exports.util = (y) => {};
module.exports = {
    exportedFunc(z) {}
};

const res = {
    send(p) {},
    format: function (f) {}
};
res.finish = function () {};
"""
    result = parse_source("reply.js", source, "javascript")
    by_qname = {s.qualified_name: s for s in result.symbols}

    # 1. Constructor & this.m assignment
    assert "Reply" in by_qname
    assert by_qname["Reply"].kind == "function"
    assert "Reply.send" in by_qname
    assert by_qname["Reply.send"].kind == "method"
    assert by_qname["Reply.send"].name == "send"
    assert by_qname["Reply.send"].signature == "send(payload)"

    # 2. Prototype direct assignment (function and arrow)
    assert "Reply.header" in by_qname
    assert by_qname["Reply.header"].kind == "method"
    assert by_qname["Reply.header"].signature == "header(key, value)"

    assert "Reply.code" in by_qname
    assert by_qname["Reply.code"].kind == "method"
    assert by_qname["Reply.code"].signature == "code(statusCode)"

    # 3. Prototype object literal assignment
    assert "Reply.redirect" in by_qname
    assert by_qname["Reply.redirect"].kind == "method"
    assert "Reply.type" in by_qname
    assert by_qname["Reply.type"].signature == "type(contentType)"
    assert "Reply.done" in by_qname
    assert by_qname["Reply.done"].signature == "done()"

    # 4. Method on identifier
    assert "Reply.build" in by_qname
    assert by_qname["Reply.build"].kind == "method"

    # 5. Non-function data exclusion
    assert "Reply.count" not in by_qname
    assert "count" not in by_qname

    # 6. Object.defineProperty (get and set)
    sent_symbols = [s for s in result.symbols if s.qualified_name == "Reply.sent"]
    assert len(sent_symbols) == 2
    sent_sigs = {s.signature for s in sent_symbols}
    assert "get sent()" in sent_sigs
    assert "set sent(v)" in sent_sigs

    # 7. Object.defineProperties
    assert "Reply.elapsedTime" in by_qname
    assert by_qname["Reply.elapsedTime"].signature == "get elapsedTime()"

    # 8. CommonJS exports
    assert "helper" in by_qname
    assert by_qname["helper"].kind == "function"
    assert "util" in by_qname
    assert by_qname["util"].kind == "function"
    assert "exportedFunc" in by_qname
    assert by_qname["exportedFunc"].kind == "function"

    # 9. Module-level const object literal
    assert "res.send" in by_qname
    assert by_qname["res.send"].kind == "method"
    assert "res.format" in by_qname
    assert by_qname["res.format"].kind == "method"
    assert "res.finish" in by_qname
    assert by_qname["res.finish"].kind == "method"


def test_js_overload_and_reassignment_preservation() -> None:
    source = b"""
function Service() {}
Service.prototype.handle = function (req) { return 1; };
Service.prototype.handle = function (req, opt) { return 2; };
"""
    result = parse_source("service.js", source, "javascript")
    handles = [s for s in result.symbols if s.qualified_name == "Service.handle"]
    assert len(handles) == 2
    sigs = [h.signature for h in handles]
    assert "handle(req)" in sigs
    assert "handle(req, opt)" in sigs


def test_js_enclosing_symbol_and_call_resolution() -> None:
    source = b"""
function Reply() {}
Reply.prototype.send = function (data) {
    this.serialize(data);
};
Reply.prototype.serialize = function (data) {
    return JSON.stringify(data);
};
"""
    result = parse_source("reply.js", source, "javascript")
    edges = build_lexical_edges(
        result.symbols,
        calls_by_path={"reply.js": result.calls},
        source_by_path={"reply.js": source.decode("utf-8")},
    )

    call_edges = [e for e in edges if e.target_name == "serialize"]
    assert len(call_edges) == 1
    edge = call_edges[0]
    assert edge.source_symbol_id.startswith("javascript:reply.js:Reply.send")
    assert edge.target_symbol_id.startswith("javascript:reply.js:Reply.serialize")
    assert edge.status == "resolved"
    assert edge.confidence == 0.95
    assert "scope:same_class" in edge.evidence


def test_js_cross_file_split_class_resolution() -> None:
    source_reply = b"""
function Reply() {}
Reply.prototype.send = function (data) {
    this.format(data);
};
"""
    source_format = b"""
Reply.prototype.format = function (data) {
    return String(data);
};
"""
    res1 = parse_source("reply.js", source_reply, "javascript")
    res2 = parse_source("reply_format.js", source_format, "javascript")
    all_symbols = res1.symbols + res2.symbols

    edges = build_lexical_edges(
        all_symbols,
        calls_by_path={"reply.js": res1.calls, "reply_format.js": res2.calls},
        source_by_path={
            "reply.js": source_reply.decode("utf-8"),
            "reply_format.js": source_format.decode("utf-8"),
        },
    )

    format_edges = [e for e in edges if e.target_name == "format"]
    assert len(format_edges) == 1
    edge = format_edges[0]
    assert edge.source_symbol_id.startswith("javascript:reply.js:Reply.send")
    assert edge.target_symbol_id.startswith("javascript:reply_format.js:Reply.format")
    assert edge.status == "resolved"
    assert edge.confidence == 0.85
    assert "scope:same_class_split" in edge.evidence


def test_js_parse_determinism() -> None:
    source = b"""
function App() {}
App.prototype.run = function () {};
App.prototype.stop = () => {};
"""
    res1 = parse_source("app.js", source, "javascript")
    res2 = parse_source("app.js", source, "javascript")
    assert [s.symbol_id for s in res1.symbols] == [s.symbol_id for s in res2.symbols]
    assert [s.signature for s in res1.symbols] == [s.signature for s in res2.symbols]
    assert [s.start_byte for s in res1.symbols] == [s.start_byte for s in res2.symbols]
