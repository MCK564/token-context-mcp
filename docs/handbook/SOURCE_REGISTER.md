# Source Register & Architectural Citations

This register establishes the authoritative documentation, academic literature, and technical benchmarks supporting the Multi-Agent Routing Handbook. All claims, thresholds, and patterns must trace back to an entry in this registry.

---

## 1. Verified Documentation Sources

| Source Identifier | Canonical Reference / URL | Research Date | Core Concept / Claim Supported | Documented Boundaries & Caveats |
| :--- | :--- | :--- | :--- | :--- |
| **DOC-CODEX-SUBAGENTS** | [Codex Subagent Configuration](https://learn.chatgpt.com/docs/agent-configuration/subagents) | 2026-09-16 | Native subagent instantiation, role mapping, model alias resolution, and effort profiles. | Model aliases are subject to host runtime policy and precedence. Subagent role naming does not guarantee cheaper inference. |
| **DOC-OAI-ORCH** | [OpenAI Agent Orchestration](https://developers.openai.com/api/docs/guides/agents/orchestration) | 2026-09-16 | Manager-worker topology ("agents as tools") vs full handoff. Supervisor retains final response authority. | Full handoff transfers dialogue ownership; "agents as tools" preserves supervisor synthesis authority. |
| **DOC-OAI-MODELS** | [OpenAI Model Configuration](https://developers.openai.com/api/docs/guides/agents/models) | 2026-09-16 | Granular model assignment per agent, structured output enforcement, tool calling specs. | Feature support (e.g. JSON schema, reasoning effort) varies by model revision; requires runtime validation. |
| **DOC-LANGGRAPH-API** | [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api) | 2026-09-16 | Conditional branching, `Command` for state update + routing, `Send` for dynamic fan-out, explicit state reducers. | State reducers must be strictly idempotent. Parallel writes to shared state require conflict resolution rules. |
| **DOC-LANGGRAPH-RESUME** | [LangGraph Checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers) | 2026-09-16 | Persistent checkpointing (SQLite/Postgres), replay, human-in-the-loop resume. | Checkpointer replays may duplicate non-idempotent tool calls (e.g. file mutations, external API calls) unless idempotency keys are used. |
| **DOC-LANGGRAPH-FAULT** | [LangGraph Fault Tolerance](https://docs.langchain.com/oss/python/langgraph/fault-tolerance) | 2026-09-16 | Node-level retry policies, async node timeouts, fallback exception handling. | Node timeouts require `langgraph>=1.2` and apply specifically to async nodes. Compatibility check required before implementation. |
| **DOC-AURELIO-ROUTER** | [Aurelio Semantic Router](https://docs.aurelio.ai/docs/semantic-router/user-guide/components/routers) | 2026-09-16 | Dense embedding similarity routing, hybrid route matching, per-route threshold definitions. | Cosine similarity measures geometric alignment with exemplars, not task difficulty or probability of model success. |
| **DOC-AURELIO-THRESH** | [Aurelio Threshold Optimization](https://docs.aurelio.ai/docs/semantic-router/user-guide/features/threshold-optimization) | 2026-09-16 | Empirical threshold tuning using calibration datasets. | Calibration data must be held out from both exemplar sets and final evaluation sets to prevent optimistic leakage. |
| **DOC-LITELLM-ROUTE** | [LiteLLM Model Routing](https://docs.litellm.ai/docs/routing) | 2026-09-16 | Reverse proxy routing, provider alias mapping, deployment failover, rate-limit backoff. | Gateway owns transport retries (429/5xx). It must not perform quality escalation or alter task definitions. |
| **DOC-LITELLM-BUDGET** | [LiteLLM Budget Reservation](https://docs.litellm.ai/docs/proxy/users#budget-reservation) | 2026-09-16 | Centralized token/monetary budget reservation and account tracking. | Reservation semantics depend on backend storage (Redis). Reservation is a temporary hold, not actual billed usage. |
| **DOC-LITELLM-MCP** | [LiteLLM MCP Bridge](https://docs.litellm.ai/docs/mcp) | 2026-09-16 | Bridging Model Context Protocol tools through gateway proxy. | Stdio MCP servers require local process access. A remote gateway cannot access local files without explicit bridge tunnels. |

---

## 2. Academic & Industry Literature

| Paper / Article Identifier | Citation / Link | Research Date | Theoretical Grounding | Key Takeaway for Architecture |
| :--- | :--- | :--- | :--- | :--- |
| **LIT-ANTHROPIC-AGENTS** | [Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents) (Anthropic Engineering) | 2026-09-16 | Workflow patterns: Prompt Chaining, Routing, Parallelization, Orchestrator-Workers, Evaluator-Optimizer. | Favor simpler workflows (single agent, router, or fixed DAG) over multi-agent meshes unless complexity is strictly justified. |
| **LIT-ANTHROPIC-MARS** | [Multi-Agent Research System](https://www.anthropic.com/engineering/multi-agent-research-system) (Anthropic Engineering) | 2026-09-16 | Empirical coordination trade-offs in multi-agent systems. | Coordination overhead and context dilution grow rapidly. Debate and majority voting incur heavy token penalties. |
| **LIT-ROUTELMM** | [RouteLLM: Learning to Route LLMs](https://arxiv.org/abs/2406.18665) (Ong et al., ICML 2024) | 2026-09-16 | Learned routing between strong (expensive) and weak (cheaper) models using preference data. | Router thresholds allow tuning the fraction of calls sent to strong models, but pre-trained pairs must be re-evaluated on custom domains. |
| **LIT-FRUGALGPT** | [FrugalGPT: How to Use Large Language Models While Reducing Cost and Improving Performance](https://arxiv.org/abs/2305.05176) (Chen et al., 2023) | 2026-09-16 | Model cascades, prompt adaptation, and cost-aware model selection. | Cascading from cheap to strong models is only cost-effective when the verifier has high precision and low marginal cost. |
| **LIT-SELF-REF** | [Self-REF: Evaluating and Improving LLM Confidence Calibration](https://proceedings.mlr.press/v267/chuang25b.html) (Chuang et al., PMLR 2025) | 2026-09-16 | LLM confidence calibration and selective prediction. | Uncalibrated verbalized confidence ("I am 90% sure") is heavily biased and must never be treated as true success probability. |

---

## 3. Strict Citations Policy

When referencing these sources in recipes and chapters:
1. **Explicit version & status**: Never present an experimental beta feature (e.g. LiteLLM auto-routing) as a stable production pattern without highlighting its beta status.
2. **No unmeasured savings claims**: Do not transfer percentage savings reported in FrugalGPT or RouteLLM directly into guarantees for custom enterprise tasks.
3. **Traceability**: Every architectural parameter (such as `max_parallel_workers=2`, `max_delegation_depth=1`, repair caps) must be explicitly identified as an illustrative design choice or calibrated metric.
