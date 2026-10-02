# Review log fresh_newtonsoft (2026-10-02, source reading only)
Result: 0 changed, 0 dropped. All def_lines, qualified names and paths verified against commit 52fa3ae.
- t01 ok: JsonTextWriter.WriteIndent at 321 (sync, cached indent buffer in chunks); base version in JsonWriter is empty.
- t02 ok: DateTimeUtils.TryParseDateTime 344 (StringReference) and 380 (string) dispatch Microsoft/ISO/exact.
- t03 ok: XmlNodeConverter.WriteGroupedNodes 1246 (list) and 1272 (single node) overloads.
- t04 ok: JsonSerializerInternalReader.PopulateMultidimensionalArray at 1574 uses a Stack<IList> by rank.
- t05 ok: JsonSchemaBuilder.ProcessAdditionalProperties at 387, unique.
- t06 ok: CamelCasePropertyNamesContractResolver.ResolveContract at 62 (static copy-on-write cache keyed by GetType()+type).
- t07 ok: UnixDateTimeConverter.WriteJson at 76 (seconds, AllowPreEpoch).
- t08 ok: ArraySliceFilter.ExecuteFilter at 14 (start/end/step, zero step throws).
- t09 ok: CollectionUtils.ResolveEnumerableCollectionConstructor 122/133 overloads; exact IEnumerable match preferred.
- t10 ok: JToken.ReadFromAsync 103/122; "task-returning" separates it from sync ReadFrom.
- t11 ok: JContainer.MergeEnumerableContent 1212 (Concat/Union/Replace/Merge) and JObject.MergeItem 181.
- t12 ok: NamingStrategy.GetPropertyName 58, CamelCaseNamingStrategy.ResolvePropertyName 82, StringUtils.ToCamelCase 155.
- t13 ok: JObject/JProperty/JValue WriteToAsync at 48/47/51.
- t14 ok: BsonWriter.WriteEnd 97 (writes root at Top==0), BsonBinaryWriter.WriteToken 66 (CalculateSize then write).
- t15 ok: JsonConvert.SerializeObject 685, JsonSerializer.SerializeInternal 1089, JsonSerializerInternalWriter.Serialize 63.
Group labels and overload/override tags consistent with the brief (a: 3 tagged, b: 5 tagged, c: all).
Minor note: t11 gold does not include JArray.MergeItem/JConstructor.MergeItem, but the query's focus (object merge plus array handling modes) is covered by the two gold symbols.
