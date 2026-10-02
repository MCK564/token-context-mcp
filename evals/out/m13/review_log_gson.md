# Review log fresh_gson (2026-10-02, source reading only)
Result: 0 changed, 0 dropped. All def_lines, qualified names and paths verified against commit 854c825.
- t01 ok: GsonBuilder.setDateFormat overloads at 639/674/697; query fits.
- t02 ok: TypeToken.isAssignableFrom (Class/Type/TypeToken overloads, 186 = Type overload).
- t03 ok: JsonReader.consumeNonExecutePrefix at 1961, unique.
- t04 ok: Gson.getAdapter(TypeToken) at 340 with thread-local placeholders; Class overload delegates.
- t05 ok: JsonPrimitive.getAsBigInteger at 192 matches description; JsonArray/JsonElement variants differ.
- t06 ok: JsonArray.deepCopy at 69; "ordered list" disambiguates from JsonObject.deepCopy.
- t07 ok: RecordAdapter.createAccumulator at 643 clones constructorArgsDefaults (other accumulators create new instances).
- t08 ok: Excluder.create at 111 matches (null when not excluded, skip/null/lazy delegate).
- t09 ok: ReflectionHelper.getAccessibleObjectDescription at 89.
- t10 ok: LinkedTreeMap.rebalance at 328, only AVL code in repo ("balance" is not an identifier token of the name; left as is).
- t11 ok: JsonParser.parseReader 107, Streams.parse 43, JsonElementTypeAdapter.read 77 all verified.
- t12 ok: getFilterResult 64, ReflectiveTypeAdapterFactory.create 110 (BLOCK_ALL throws), ConstructorConstructor.get 103.
- t13 ok: MapTypeAdapterFactory.Adapter.write 217, GsonBuilder.enableComplexMapKeySerialization 360.
- t14 ok: TypeAdapters.checkValidFloatingPoint 520, JsonWriter.value(double) 598.
- t15 ok: DefaultDateTypeAdapter.deserializeToDate 165, ISO8601Utils.parse 147, PreJava9DateFormatProvider.getUsDateTimeFormat 30.
Group labels and overload/override tags consistent with the brief (a: 4 tagged, b: 3 tagged, c: all).
