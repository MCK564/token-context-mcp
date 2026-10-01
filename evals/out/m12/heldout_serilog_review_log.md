# heldout-serilog review log (reviewer session, independent of the author)

Scope: every one of the 30 localisation tasks (t01..t30) and 10 packet tasks (p01..p10) was checked against the source at tag v4.4.0 (commit 6d9fc0b84e004418f2677b5961b9c8970349d0be, `src/Serilog` only). Method: opened each gold file, confirmed `def_line` points at the member's signature line (scripted check: all 59 loc gold + 10 packet targets OK; for overloaded or attributed members the first-overload line / attribute-line span start differ, both accepted), grepped the tree for equally valid answers, re-read every `why`. No token-context tool and no ranking script were used; only lint_tasks, lint_packet_tasks and verify_bench_gold were run.

## Changes (5 loc tasks + 2 packet items edited; same ids/groups)

| id | change | reason |
|----|--------|--------|
| t19 | query reworded: "a decorator wraps them" -> "a decorator encloses them" (also "capture ... adds to" -> "configured through a callback on") | the old query contained "wraps", the inflected stem of the target name `Wrap` (token lint did not flag it, but it is a name leak for a b_hidden_dep task) |
| t20 | query reworded to say the message takes "up to three format arguments"; note extended | `SelfLog.SelfLogFailureListener.OnLoggingFailed` also bumps a counter and writes a timestamped string to the callback, so the old wording had two near-equal answers. The format-string-with-three-optional-args clause pins `SelfLog.WriteLine` |
| t23 | added gold symbol `KeyValuePairSettings.SelectConfigurationMethod` (def_line 257), note extended | query says "matching by argument name"; that is exactly what SelectConfigurationMethod does, so it is a legitimate part of the answer (same file as ApplyDirectives, so gold_files unchanged) |
| t26 | query reworded: now names the configuration option that sets the maximum plus the thread-static depth counter that yields the null scalar | old wording ("when converting nested sequence and dictionary elements") pointed at PropertyValueConverter.TryConvertEnumerable (same file family, not gold) and only weakly implied the second gold file (LoggerDestructuringConfiguration.ToMaximumDepth) |
| p02 | `why` of Padding.Apply: "every token's text" -> "every property token's text (...)" | text tokens are written by RenderTextToken, not Padding.Apply; the old sentence was slightly false |
| p07 | PropertyBinder context item: `need` body -> signature, `why` rewritten | in the index the name `PropertyBinder` resolves to the 4-line constructor (the class and its #if-split methods are not indexed), so a "body" need could not be met; the dependency itself (Process delegates to it; SelfLog instead of throwing) is real and stated in the new why |

## Per-task verdicts (no change unless listed above)

Group a_keyword
* t01 ok. GetEffectiveLevel is the only dot-boundary, case-insensitive prefix matcher over override keys; Matching.FromSource (t08) differs (predicate over events, no level/switch); Logger.ForContext only calls it.
* t02 ok. WriteQuotedJsonString is the only JSON string escaper (bulk copy of clean segments).
* t03 ok. SignalShutdown unique (Dispose/DisposeAsync merely call it).
* t04 ok. Regex split only in TryParseStaticMemberAccessor (ConvertToType just calls it).
* t05 ok. CreateSink unique; the static Wrap overloads call it but add the wrapper logic.
* t06 ok. Suspend vs Reset: only Suspend returns a bookmark.
* t07 ok. LoggerExtensions has a single ForContext; other ForContext methods are on Logger/ILogger/Log (different qualified names).
* t08 ok. Two FromSource overloads (generic type / string); the query describes both, so both are valid. def_line 27 = first overload (index span start of the last overload is 39). Accepted.
* t09 ok. DictionaryValue.Render unique (single overload).
* t10 ok. TrySplitTagContent is the unique splitter that rejects an empty alignment (ParsePropertyToken does not).

Group b_hidden_dep (no name/stem leak after the t19 fix)
* t11 ok. Parse is the only method with the 1024 / 1000 limits. (The class itself is a container; the behaviour lives in Parse.)
* t12 ok. PostLevelCheckEmit is the only method with enrich-in-try/catch followed by sink emit; SafeAggregateEnricher.Enrich lacks the sink call; ILogEventSink.Emit lacks the try/catch.
* t13 ok. Dispose(bool) is the only pooling/threshold logic.
* t14 ok. CreateStructureValue is unique; TryConvertStructure only guards and calls it.
* t15 ok. Sequence/Dictionary siblings have no type tag; "keeps the type tag" pins the structure variant. Accepted.
* t16 ok. SelectConfigurationMethod unique.
* t17 ok. Gold is the property symbol (kind property, span 47-62, equal to def_line). The enclosing class is a container, so the property is the single best answer. Accepted.
* t18 ok. RenderPropertyToken is the only one writing RawText for a missing property; MessageTemplateTextFormatter.Format skips missing values instead.
* t19 edited (see above). Sink analogue LoggerSinkConfiguration.Wrap is about sinks and has no enricher/SelfLog warning.
* t20 edited (see above).

Group c_multi_file
* t21 ok. Roles named in the query map one-to-one to the three gold symbols (FallbackChain, FailureListenerSink.Emit, DelegatingLoggingFailureListener.OnLoggingFailed).
* t22 ok. MarkFailure / NextInterval / DrainOnFailure; 2 files. (LoopAsync is the orchestrator and is covered by p03.)
* t23 edited (see above). ApplyDirectives def_line 227 vs index span start 225 (attributes), ConvertToType 40 vs 38, FindConfigurationMethods 20 vs 19: all accepted.
* t24 ok. Overloaded names inside gold (GetLevelMoniker has 3 overloads, Padding.Apply 2) are all legitimate parts of the described Level-token rendering; def_line 55 / 24 are the first overloads. Casing.Format is peripheral (used for plain u/w formats) but real. Accepted.
* t25 ok. FromLogContext (expression-bodied, 86-86), LogContextEnricher.Enrich, LogContext.Enrich.
* t26 edited (see above). CreatePropertyValue has two overloads in DepthLimiter (Destructuring / explicit-interface bool); both contain the depth check, def_line 38 = first, span start 50 = second; accepted.
* t27 ok. CreateLogger + the three Emit methods; the claims in the note are true.
* t28 ok. SecondaryLoggerSink.Emit + LogEvent.Copy.
* t29 ok. ByTransforming / ByTransformingWhere (single overload each) + ProjectedDestructuringPolicy.TryDestructure.
* t30 ok. ConvertToHexString has two overloads in ByteMemoryScalarConversionPolicy (def_line 45 first, span start 55 last); both are valid. File is under `#if FEATURE_SPAN` but is ordinary source.

## Packet tasks
* p01 ok. All six `why` statements verified (7-arg PropertyValueConverter constructor, auditing flag passed as propagateExceptions, override map created only when overrides exist, ...).
* p02 edited (one `why`). Other items verified (OutputProperties constants, ReusableStringWriter.GetOrCreate used when an alignment exists, PropertiesOutputFormat.Render takes both templates).
* p03 ok. LoopAsync def_line 107; all six items called from the loop or its helpers.
* p04 ok. Configure def_line 83. Both Override overloads are called by Configure (LogEventLevel and LoggingLevelSwitch); the listed handle covers either.
* p05 ok. TryGetDictionary, BuildArrayValue, DepthLimiter.CreatePropertyValue, DictionaryValue, SequenceValue all used in TryConvertEnumerable as described.
* p06 ok. MessageTemplate.Render handle is overloaded (string-returning overload is the one called, which calls the TextWriter overload); both relevant.
* p07 edited (PropertyBinder need). BindMessageTemplate def_line 1405 (index span start 1404 = attribute line), accepted either way.
* p08 ok. All six `why` verified against ParsePropertyToken (hint stripping, dotted identifier validation via TryContinuePropertyName, Alignment from direction + abs width).
* p09 ok. Small target (5 lines) but the four items are genuine (snapshot via ToArray in the SafeAggregateEnricher constructor, EnricherStack enumeration order, lazy GetOrCreateEnricherStack, return type). Accepted.
* p10 ok. Constructor def_line 42; array order of the scalar policies and the user-before-built-in order of destructuring policies verified.

All packet tasks have 4-6 gold_context entries and at least one in a different file than the target.

## Structure / spread checks
* 10 a_keyword, 10 b_hidden_dep, 10 c_multi_file; 30 unique queries, all 6-25 words and <= 190 chars; 10 packet tasks.
* No file is gold in more than two localisation tasks. Gold spans Capturing, Configuration, Context, Core (Logger, LevelOverrideMap, LoggingLevelSwitch, Pipeline, Sinks, Sinks/Batching, Sinks/Fallback), Data, Debugging, Events, Filters, Formatting (Display, Json), Parsing, Policies, Rendering, Settings. Packet targets: LoggerConfiguration, Display formatter, BatchingSink, KeyValuePairSettings, PropertyValueConverter (x2), JsonFormatter, Logger, MessageTemplateParser, LogContext.
* Gold is non-test source code only.
* `reviewed` left false (orchestrator sets it).

## Checks after edits
* lint_tasks: SUCCESS (30 tasks, all 6 rules).
* lint_packet_tasks: SUCCESS (10 tasks).
* verify_bench_gold: missing_gold = 0 (30 loc, 10 packet). Output rewritten to `out/verify_serilog.json`.

## Known, accepted quirks (not content problems)
* Index-quirk handles: `PropertyBinder`, `EventProperty`, `Alignment` resolve to constructor symbols (class/struct not indexed under that name); `MessageTemplateProcessor.Process` resolves to the `#else` signature. The `why` texts remain true for the real types.
* Low packet "reach ceiling" (0.30) is informational (many packet items are classes/interfaces rather than direct callees).

VERDICT: approved
