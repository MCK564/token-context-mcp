# Corrections to evals/tasks/edge_gold_hono.json (dev set)

Checked against hono source at the pinned tag; all four were labelling errors, not tool errors.

- `benchmarks/jsx/src/react-jsx/preact.ts:4` `buildPage()`: `{'path': 'benchmarks/jsx/src/react-jsx/page-preact.ts', 'qualified_name': 'buildPage'}` -> `{'path': 'benchmarks/jsx/src/react-jsx/page-preact.tsx', 'qualified_name': 'buildPage'}`. file is page-preact.tsx, not .ts
- `src/adapter/bun/websocket.ts:70` `createWSContext`: `{'path': 'src/helper/websocket/index.ts', 'qualified_name': 'createWSContext'}` -> `{'path': 'src/adapter/bun/websocket.ts', 'qualified_name': 'createWSContext'}`. createWSContext is defined in the same file (line 33), not in helper/websocket
- `src/helper/testing/index.ts:26` `hc`: `{'path': 'src/client/index.ts', 'qualified_name': 'hc'}` -> `{'path': 'src/client/client.ts', 'qualified_name': 'hc'}`. hc is defined in client.ts; client/index.ts only re-exports it
- `src/jsx/base.ts:334` `createContext`: `{'path': 'src/jsx/base.ts', 'qualified_name': 'createContext'}` -> `{'path': 'src/jsx/context.ts', 'qualified_name': 'createContext'}`. createContext is imported from ./context (defined at context.ts:15)
