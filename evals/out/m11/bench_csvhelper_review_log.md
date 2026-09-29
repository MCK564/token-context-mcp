# Independent review log (bench-csvhelper)

Reviewer read the source for every gold symbol; no retrieval tool was run and no edit was chosen from search rankings.

## Locate tasks changed
- t17: added `CsvParser.FillBufferAsync` to gold_symbols. It is a line-for-line async twin of `FillBuffer`, so it answers the query equally well. Note updated.
- t24: removed `HeaderValidationException` (symbol and file). Thin exception class, the query does not need it (the callback that builds and throws the message is `ConfigurationFunctions.HeaderValidated`). Kept `CsvReader.ValidateHeader`: all three overloads sit in one validation chain (`<T>` -> `Type` -> protected `ClassMap` collector), so each is a defensible hit; note reworded to say so.
- t26: removed `BadDataException` (symbol and file). Thin class, not needed by the query (`BadDataFound` default just throws it).

## Locate tasks checked and left unchanged
t01-t16, t18-t23, t25, t27-t30: gold body read; greps for alternatives (per-type converters, other doubling/trim/ctor-matching code, other hex/anonymous/ShouldQuote sites, `ClassMapCollection` indexer vs `GetGenericCsvClassMapType`) found no equally good competitor. t09 `WriteToBuffer` vs `FillBuffer` are distinct (string append vs stream refill). t23 both symbols required (call site and ranking logic). t12/t18 converters are unique to their types. t21/t22 keep `RecordManager` as the wiring class (thin, borderline, kept). No symbol is gold for 3+ tasks.

## Packet tasks changed
- p04: fixed `why` of `CsvReader.CanRead` (it runs after the ConvertUsing branch, not "before any expression is built"); clarified overload notes for `CreateTypeConverterExpression`, `CreateDefaultExpression`, `GetFieldIndex`; added `MemberMapData` (unambiguous class driving every branch).
- p05: `ObjectCreator.CreateInstance` why now says only the Type overload calls `GetFunc`.
- p06: replaced `TypeConverterCache.GetConverter` (3 overloads, only the Type one used) with `MemberMapData` (SetMapDefaults fills TypeConverter and Names); `RegisterClassMap` why states all three overloads reach `Maps.Add`.
- p07: `GetFieldIndex` why corrected (ReadHeader/ParseNamedIndexes clears the cache, GetFieldIndex populates it); `ValidateHeader` why lists overloads.
- p08: target `CsvWriter.CanWrite` replaced by `CollectionConverterFactory.Create` (TypeConversion coverage; old target was a 17-line method whose neighbour list was weak and the `GetTypeInfoForRecord` sibling entry was not needed to modify it). New context: `CanCreate`, `ITypeConverterFactory`, `ArrayConverter`, `CollectionGenericConverter`, `IEnumerableGenericConverter`, `TypeConverterCache.CreateDefaultConverters`, all read in source.
- p10: replaced the overloaded `ObjectResolver.Resolve` and `IObjectResolver.Resolve` with `ObjectResolver.Current` (constant embedded in the expression) and `IObjectResolver` (Resolve(Type, object[]) looked up by reflection).

## Packet tasks checked, unchanged
p01, p02, p03, p09: callees/callers/siblings verified in source; `why` texts accurate.

## Residual doubts
- Struct names with a same-named constructor (`RecordTypeInfo`, `ShouldSkipRecordArgs`, `ReadingExceptionOccurredArgs`, `ProcessedField`, `CacheKey`) resolve to two index rows; both are defensible.
- p01-p10 targets are still concentrated in CsvReader/CsvWriter/CsvParser/ExpressionManager (core pipeline), with one TypeConversion and one Configuration target.
- `CsvReader.CanRead` (p04) and `ValidateHeader` remain overloaded; documented in `why`.

Lint, packet lint and verify_bench_gold pass; all queries <= 190 chars (max 180).

VERDICT: approved
