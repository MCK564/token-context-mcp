# Review log (independent reviewer)

All 30 locate and 10 packet tasks were checked against the source; queries are all <= 190 chars, gold paths are non-test lib/ or fastify.js.

## Changes
- t15 (b_hidden_dep): query was loose (any timeout hook runner could match). Reworded to describe the listener reading the context/request/reply stored on the socket and running hooks with an empty callback; still avoids the name parts and file stem.
- t24 (c_multi_file): added lib/route.js + symbol addNewRoute. The startup compilation (normalizeSchema, setupValidator, compileSchemasForValidation) is wired in the preReady hook inside addNewRoute; without it the "at startup" half of the query has no answer file.
- t25 (c_multi_file): dropped lib/validation.js / compileSchemasForSerialization (compile phase is not asked by the query; the symbol was also gold in t06 and p08, so reuse is reduced). Reworded to "custom reply serializer, else per-status response definition, else JSON stringify"; gold is now preSerializationHookEnd + serialize (reply.js) and getSchemaSerializer (schemas.js), which is exactly that decision chain.
- t29 (c_multi_file): added decorateRequest and decorateReply as gold symbols (the public entry points that call decorateConstructor); files unchanged.
- p03: fixed the `why` of onSendHook (it calls onSendEnd directly when there are no onSend hooks, otherwise through wrapOnSendEnd).
- p08: removed preSerializationHookEnd from gold_context (it calls serialize, not getSchemaSerializer, so it is not a direct neighbour; leaves 3 entries, still >=1 in another file).

## Checked, no change
t01-t14, t16-t23, t26-t28, t30 and p01, p02, p04-p07, p09, p10 read against source and judged correct.
Residual doubts: t23 uses rawBody as stand-in for ContentTypeParser.prototype.run (not indexed) - acceptable, both in the same file. t02/t21 share headRouteOnSendHandler and t01/t23 share rawBody (2 uses each, below the 3-use limit). t22 has two symbols named setNotFoundHandler in different files; gold entries carry the path so they are unambiguous. t30 gold covers both bad-URL handlers and the query names both. p07 has only 3 context entries (few real neighbours).

VERDICT: approved
