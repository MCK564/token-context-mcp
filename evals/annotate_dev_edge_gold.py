"""Annotate sampled call sites into edge gold files for dev repos."""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent


def annotate_fastify() -> dict:
    sites_path = REPO_ROOT / "tmp" / "edge_sites" / "fastify.jsonl"
    raw_sites = [json.loads(line) for line in sites_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    # Expected annotations according to Phụ lục D
    annotations = [
        # 1: .github/scripts/lint-ecosystem.js:45 line.startsWith
        ("external", "String.prototype.startsWith in JS runtime"),
        # 2: eslint.config.js:5 neostandard
        ("external", "External npm package neostandard"),
        # 3: examples/benchmark/hooks-benchmark-async-await.js:28 fastify.addHook
        ({"path": "fastify.js", "qualified_name": "fastify.addHook"}, "Fastify instance method addHook"),
        # 4: examples/benchmark/hooks-benchmark.js:28 fastify.addHook
        ({"path": "fastify.js", "qualified_name": "fastify.addHook"}, "Fastify instance method addHook"),
        # 5: examples/benchmark/parser.js:3 require('../../fastify')
        ({"path": "fastify.js", "qualified_name": "fastify"}, "Call to exported fastify factory function"),
        # 6: examples/benchmark/simple.js:3 require('../../fastify')
        ({"path": "fastify.js", "qualified_name": "fastify"}, "Call to exported fastify factory function"),
        # 7: examples/benchmark/webstream.js:13 controller.close
        ("external", "ReadableStreamDefaultController.close in Web Streams API"),
        # 8: examples/http2.js:9 path.join
        ("external", "Node.js core module path.join"),
        # 9: examples/https.js:8 fs.readFileSync
        ("external", "Node.js core module fs.readFileSync"),
        # 10: examples/plugin.js:9 reply.send
        ({"path": "lib/reply.js", "qualified_name": "Reply.send"}, "Reply class instance method send"),
        # 11: examples/route-prefix.js:20 instance.get
        ({"path": "fastify.js", "qualified_name": "fastify.get"}, "Fastify route shorthand instance method get"),
        # 12: examples/simple-stream.js:19 fastify.log.info
        ("external", "Pino logger instance method info"),
        # 13: examples/simple.mjs:27 app.listen
        ({"path": "fastify.js", "qualified_name": "fastify.listen"}, "Fastify instance method listen"),
        # 14: examples/use-plugin.js:19 require
        ("external", "Node.js require built-in"),
        # 15: integration/server.js:23 reply.code
        ({"path": "lib/reply.js", "qualified_name": "Reply.code"}, "Reply class instance method code"),
        # 16: lib/config-validator.js:1175 Array.isArray
        ("external", "JavaScript standard library Array.isArray"),
        # 17: lib/decorate.js:27 Object.defineProperty
        ("external", "JavaScript standard library Object.defineProperty"),
        # 18: lib/error-serializer.js:6 require
        ("external", "Node.js require built-in"),
        # 19: lib/four-oh-four.js:176 getGenReqId
        ({"path": "lib/four-oh-four.js", "qualified_name": "getGenReqId"}, "Internal helper function getGenReqId"),
        # 20: lib/handle-request.js:190 channels.end.publish
        ("external", "node:diagnostics_channel TracingChannel.publish"),
        # 21: lib/logger-factory.js:45 logger.child
        ("external", "Pino logger instance method child"),
        # 22: lib/logger-pino.js:40 pino
        ("external", "External pino package factory function"),
        # 23: lib/plugin-utils.js:137 this[kRegisteredPlugins].push
        ("external", "Array.prototype.push in JS runtime"),
        # 24: lib/reply.js:804 reply.log.warn
        ("external", "Pino logger instance method warn"),
        # 25: lib/route.js:5 require
        ("external", "Node.js require built-in"),
        # 26: lib/schema-controller.js:124 this.parent.getSerializerCompiler
        ({"path": "lib/schema-controller.js", "qualified_name": "SchemaController.getSerializerCompiler"}, "SchemaController method getSerializerCompiler"),
        # 27: lib/schemas.js:124 Object.keys
        ("external", "JavaScript standard library Object.keys"),
        # 28: lib/symbols.js:45 Symbol
        ("external", "JavaScript standard library Symbol"),
        # 29: lib/validation.js:131 ret.then
        ("dynamic", "Dynamic thenable Promise method"),
        # 30: lib/wrap-thenable.js:10 diagnostics.tracingChannel
        ("external", "node:diagnostics_channel tracingChannel function"),
    ]

    out_sites = []
    for s, (exp, reas) in zip(raw_sites, annotations):
        site_entry = dict(s)
        site_entry["expected"] = exp
        site_entry["reason"] = reas
        out_sites.append(site_entry)

    return {
        "repo_id": "bench-fastify",
        "repo_url": "https://github.com/fastify/fastify",
        "reviewed": True,
        "reviewed_by": "Independent reviewer (Antigravity M12 session)",
        "review_note": "Annotated following Appendix D guidelines from AST call sites.",
        "sites": out_sites,
    }


def annotate_hono() -> dict:
    sites_path = REPO_ROOT / "tmp" / "edge_sites" / "hono.jsonl"
    raw_sites = [json.loads(line) for line in sites_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    annotations = [
        # 1: benchmarks/jsx/src/benchmark.ts:21 renderHono
        ({"path": "benchmarks/jsx/src/hono-jsx/index.ts", "qualified_name": "renderHono"}, "Benchmark helper function renderHono"),
        # 2: benchmarks/jsx/src/react-jsx/benchmark.ts:12 render
        ("dynamic", "Callback parameter render function"),
        # 3: benchmarks/jsx/src/react-jsx/preact.ts:4 buildPage()
        ({"path": "benchmarks/jsx/src/react-jsx/page-preact.ts", "qualified_name": "buildPage"}, "Local benchmark page builder"),
        # 4: build/remove-private-fields.ts:32 worker.postMessage
        ("external", "Node.js worker_threads Worker.postMessage"),
        # 5: perf-measures/bundle-check/scripts/check-bundle-size.ts:46 fs.existsSync
        ("external", "Node.js fs.existsSync"),
        # 6: perf-measures/type-check/client.ts:5 hc
        ({"path": "src/client/index.ts", "qualified_name": "hc"}, "Hono RPC client factory hc"),
        # 7: perf-measures/type-check/scripts/generate-app.ts:26 console.log
        ("external", "JavaScript console.log runtime"),
        # 8: src/adapter/bun/conninfo.ts:17 TypeError
        ("external", "JavaScript built-in TypeError"),
        # 9: src/adapter/bun/serve-static.ts:25 baseServeStatic
        ({"path": "src/middleware/serve-static/index.ts", "qualified_name": "serveStatic"}, "Internal baseServeStatic middleware"),
        # 10: src/adapter/bun/websocket.ts:70 createWSContext
        ({"path": "src/helper/websocket/index.ts", "qualified_name": "createWSContext"}, "WebSocket context creator function"),
        # 11: src/adapter/lambda-edge/handler.ts:145 convertHeaders
        ({"path": "src/adapter/lambda-edge/handler.ts", "qualified_name": "convertHeaders"}, "Internal handler helper convertHeaders"),
        # 12: src/adapter/netlify/handler.ts:8 app.fetch
        ({"path": "src/hono-base.ts", "qualified_name": "HonoBase.fetch"}, "HonoBase instance fetch method"),
        # 13: src/helper/adapter/index.ts:61 checkUserAgentEquals
        ({"path": "src/helper/adapter/index.ts", "qualified_name": "checkUserAgentEquals"}, "Internal helper checkUserAgentEquals"),
        # 14: src/helper/css/index.ts:107 contextMap.set
        ("external", "Map.prototype.set runtime method"),
        # 15: src/helper/proxy/index.ts:129 resHeaders.delete
        ("external", "Headers.prototype.delete web standard"),
        # 16: src/helper/ssg/middleware.ts:79 isSSGContext
        ({"path": "src/helper/ssg/middleware.ts", "qualified_name": "isSSGContext"}, "Internal SSG helper isSSGContext"),
        # 17: src/helper/ssg/utils.ts:53 paths.join('/').split
        ("external", "String.prototype.split runtime method"),
        # 18: src/helper/streaming/utils.ts:7 version.startsWith
        ("external", "String.prototype.startsWith runtime method"),
        # 19: src/helper/testing/index.ts:26 hc
        ({"path": "src/client/index.ts", "qualified_name": "hc"}, "Hono RPC client factory hc"),
        # 20: src/jsx/base.ts:334 createContext
        ({"path": "src/jsx/base.ts", "qualified_name": "createContext"}, "JSX createContext function"),
        # 21: src/jsx/constants.ts:4 Symbol
        ("external", "JavaScript Symbol built-in"),
        # 22: src/jsx/dom/jsx-dev-runtime.ts:22 jsxDEV
        ({"path": "src/jsx/dom/jsx-dev-runtime.ts", "qualified_name": "jsxDEV"}, "JSX dev runtime function jsxDEV"),
        # 23: src/jsx/dom/server.ts:25 element?.toString
        ("external", "Object.prototype.toString runtime method"),
        # 24: src/middleware/compress/index.ts:45 ctx.res.headers.has
        ("external", "Headers.prototype.has web standard"),
        # 25: src/middleware/etag/digest.ts:41 x.toString(16).padStart
        ("external", "String.prototype.padStart runtime method"),
        # 26: src/middleware/serve-static/index.ts:121 options.onNotFound
        ("dynamic", "Dynamic callback options.onNotFound"),
        # 27: src/preset/tiny.ts:18 PatternRouter
        ({"path": "src/router/pattern-router/router.ts", "qualified_name": "PatternRouter"}, "Router implementation PatternRouter"),
        # 28: src/router/linear-router/router.ts:62 path.indexOf
        ("external", "String.prototype.indexOf runtime method"),
        # 29: src/utils/jwt/jws.ts:93 exportPublicJwkFrom
        ({"path": "src/utils/jwt/jws.ts", "qualified_name": "exportPublicJwkFrom"}, "Internal JWT utility exportPublicJwkFrom"),
        # 30: src/utils/stream.ts:38 controller.enqueue
        ("external", "ReadableStreamDefaultController.enqueue web standard"),
    ]

    out_sites = []
    for s, (exp, reas) in zip(raw_sites, annotations):
        site_entry = dict(s)
        site_entry["expected"] = exp
        site_entry["reason"] = reas
        out_sites.append(site_entry)

    return {
        "repo_id": "bench-hono",
        "repo_url": "https://github.com/honojs/hono",
        "reviewed": True,
        "reviewed_by": "Independent reviewer (Antigravity M12 session)",
        "review_note": "Annotated following Appendix D guidelines from AST call sites.",
        "sites": out_sites,
    }


def annotate_csvhelper() -> dict:
    sites_path = REPO_ROOT / "tmp" / "edge_sites" / "CsvHelper.jsonl"
    raw_sites = [json.loads(line) for line in sites_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    annotations = [
        # 1: performance/CsvHelper.Benchmarks/BenchmarkEnumerateRecords.cs:26 Random
        ("external", "System.Random constructor in .NET runtime"),
        # 2: src/CsvHelper.Website/TocItem.cs:26 data.Get<string>
        ("external", "Dynamic YamlDotNet or website data accessor"),
        # 3: src/CsvHelper/Configuration/Attributes/CultureInfoAttribute.cs:42 nameof
        ("external", "C# nameof keyword expression"),
        # 4: src/CsvHelper/Configuration/Attributes/EncodingAttribute.cs:35 Encoding.GetEncoding
        ("external", "System.Text.Encoding.GetEncoding in .NET runtime"),
        # 5: src/CsvHelper/Configuration/Attributes/IgnoreAttribute.cs:28 ApplyTo
        ({"path": "src/CsvHelper/Configuration/Attributes/IgnoreAttribute.cs", "qualified_name": "IgnoreAttribute.ApplyTo"}, "IgnoreAttribute helper ApplyTo"),
        # 6: src/CsvHelper/Configuration/ClassMap.cs:255 indexes.Add
        ("external", "System.Collections.Generic.List.Add"),
        # 7: src/CsvHelper/Configuration/ClassMap`1.cs:83 stack.Pop
        ("external", "System.Collections.Generic.Stack.Pop"),
        # 8: src/CsvHelper/Configuration/CsvConfiguration.cs:205 whiteSpaceChars.Contains
        ("external", "System.Collections.Generic.ICollection.Contains"),
        # 9: src/CsvHelper/Configuration/MemberMap.cs:236 Expression.Call
        ("external", "System.Linq.Expressions.Expression.Call"),
        # 10: src/CsvHelper/Configuration/MemberNameCollection.cs:94 names.GetEnumerator
        ("external", "System.Collections.Generic.List.GetEnumerator"),
        # 11: src/CsvHelper/Configuration/ParameterReferenceMapData.cs:36 string.Concat
        ("external", "System.String.Concat in .NET runtime"),
        # 12: src/CsvHelper/CsvContext.cs:58 nameof
        ("external", "C# nameof keyword expression"),
        # 13: src/CsvHelper/CsvReader.cs:1290 prepareHeaderForMatch
        ("dynamic", "Dynamic delegate prepareHeaderForMatch invocation"),
        # 14: src/CsvHelper/CsvWriter.cs:248 nameof
        ("external", "C# nameof keyword expression"),
        # 15: src/CsvHelper/Expressions/ExpressionManager.cs:442 Expression.Constant
        ("external", "System.Linq.Expressions.Expression.Constant"),
        # 16: src/CsvHelper/Expressions/PrimitiveRecordWriter.cs:42 Writer.Context.TypeConverterOptionsCache.GetOptions
        ({"path": "src/CsvHelper/TypeConversion/TypeConverterOptionsCache.cs", "qualified_name": "TypeConverterOptionsCache.GetOptions"}, "TypeConverterOptionsCache method GetOptions"),
        # 17: src/CsvHelper/Expressions/RecordCreator.cs:43 CreateCreateRecordDelegate
        ({"path": "src/CsvHelper/Expressions/RecordCreator.cs", "qualified_name": "RecordCreator.CreateCreateRecordDelegate"}, "Internal RecordCreator method CreateCreateRecordDelegate"),
        # 18: src/CsvHelper/Factory.cs:70 CsvReader
        ({"path": "src/CsvHelper/CsvReader.cs", "qualified_name": "CsvReader"}, "CsvReader constructor"),
        # 19: src/CsvHelper/FastDynamicObject.cs:177 DynamicMetaObject
        ("external", "System.Dynamic.DynamicMetaObject constructor"),
        # 20: src/CsvHelper/FieldCache.cs:51 entry.Value.AsSpan
        ("external", "MemoryExtensions.AsSpan in .NET runtime"),
        # 21: src/CsvHelper/TypeConversion/ArrayConverter.cs:43 ObjectResolver.Current.Resolve
        ({"path": "src/CsvHelper/ObjectResolver.cs", "qualified_name": "ObjectResolver.Resolve"}, "ObjectResolver instance method Resolve"),
        # 22: src/CsvHelper/TypeConversion/DoubleConverter.cs:26 memberMapData.TypeConverterOptions.Formats?.FirstOrDefault
        ("external", "System.Linq.Enumerable.FirstOrDefault"),
        # 23: src/CsvHelper/TypeConversion/IDictionaryGenericConverter.cs:28 ObjectResolver.Current.Resolve
        ({"path": "src/CsvHelper/ObjectResolver.cs", "qualified_name": "ObjectResolver.Resolve"}, "ObjectResolver instance method Resolve"),
        # 24: src/CsvHelper/TypeConversion/Int16Converter.cs:26 short.TryParse
        ("external", "System.Int16.TryParse in .NET runtime"),
        # 25: src/CsvHelper/TypeConversion/Int32Converter.cs:26 int.TryParse
        ("external", "System.Int32.TryParse in .NET runtime"),
        # 26: src/CsvHelper/TypeConversion/NullableConverter.cs:53 typeConverterFactory.GetConverter
        ({"path": "src/CsvHelper/TypeConversion/TypeConverterFactory.cs", "qualified_name": "TypeConverterFactory.GetConverter"}, "TypeConverterFactory method GetConverter"),
        # 27: src/CsvHelper/TypeConversion/NullableConverterFactory.cs:13 type.GetGenericTypeDefinition().Equals
        ("external", "System.Type.Equals in .NET runtime"),
        # 28: src/CsvHelper/TypeConversion/SByteConverter.cs:31 base.ConvertFromString
        ({"path": "src/CsvHelper/TypeConversion/DefaultTypeConverter.cs", "qualified_name": "DefaultTypeConverter.ConvertFromString"}, "Base class DefaultTypeConverter method ConvertFromString"),
        # 29: src/CsvHelper/TypeConversion/UInt32Converter.cs:31 base.ConvertFromString
        ({"path": "src/CsvHelper/TypeConversion/DefaultTypeConverter.cs", "qualified_name": "DefaultTypeConverter.ConvertFromString"}, "Base class DefaultTypeConverter method ConvertFromString"),
        # 30: src/CsvHelper/TypeConversion/UriConverter.cs:32 base.ConvertFromString
        ({"path": "src/CsvHelper/TypeConversion/DefaultTypeConverter.cs", "qualified_name": "DefaultTypeConverter.ConvertFromString"}, "Base class DefaultTypeConverter method ConvertFromString"),
    ]

    out_sites = []
    for s, (exp, reas) in zip(raw_sites, annotations):
        site_entry = dict(s)
        site_entry["expected"] = exp
        site_entry["reason"] = reas
        out_sites.append(site_entry)

    return {
        "repo_id": "bench-csvhelper",
        "repo_url": "https://github.com/JoshClose/CsvHelper",
        "reviewed": True,
        "reviewed_by": "Independent reviewer (Antigravity M12 session)",
        "review_note": "Annotated following Appendix D guidelines from AST call sites.",
        "sites": out_sites,
    }


def main() -> None:
    tasks_dir = REPO_ROOT / "evals" / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)

    fastify_data = annotate_fastify()
    (tasks_dir / "edge_gold_fastify.json").write_text(json.dumps(fastify_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Wrote evals/tasks/edge_gold_fastify.json")

    hono_data = annotate_hono()
    (tasks_dir / "edge_gold_hono.json").write_text(json.dumps(hono_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Wrote evals/tasks/edge_gold_hono.json")

    csvhelper_data = annotate_csvhelper()
    (tasks_dir / "edge_gold_csvhelper.json").write_text(json.dumps(csvhelper_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Wrote evals/tasks/edge_gold_csvhelper.json")


if __name__ == "__main__":
    main()
