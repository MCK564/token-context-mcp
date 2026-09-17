# LLM Gateway & Transport Failover Recipes (Path D / Gateway)

This guide provides operational recipes for managing provider transport failures, HTTP 429 rate limits, and deployment fallbacks when using a centralized reverse proxy or in-process provider router.

---

## Recipe R07: Provider 429/Timeout Retry & Fallback

### 1. When to Use
- An API provider returns HTTP 429 (Rate Limit Exceeded), HTTP 500/503 (Provider Outage), or a connection timeout during worker or supervisor execution.
- You have configured an LLM gateway (e.g. LiteLLM Proxy) or SDK-level provider adapter with fallback endpoints.
- **Anti-pattern**: Conflating transport failure (429/timeout) with model quality failure, or allowing both the gateway and the application loop to retry independently without a unified deadline.

### 2. Prerequisites
- Gateway configuration defining primary and secondary provider deployments for each model alias.
- Policy rule defining:
  - **Single Transport Retry Owner**: Only the gateway or the SDK adapter retries HTTP transport errors. The orchestrator must not wrap transport calls in a second retry loop.
  - **Unified Deadline**: All retry attempts share the task's original `deadline_ms`.
  - **Pre-validated Fallback Allowlist**: Any fallback model must pass capability validation before dispatch.

### 3. Inputs & Outputs
- **Input**: A dispatched call to `MODEL_ECONOMY` (Deployment A) encountering HTTP 429.
- **Output**: Seamless failover to `MODEL_ECONOMY` (Deployment B) within the allocated deadline, recording `requested_model`, `resolved_model`, and `actual_model` in the audit event.

### 4. Step-by-Step Procedure
1. **Initial Dispatch**: Caller requests `MODEL_ECONOMY` for task `task_audit_auth_tokens_001`.
2. **Transport Error Encountered**: Deployment A responds with HTTP 429 (Rate Limit Exceeded).
3. **Transport Retry Owner Action**:
   - Gateway inspects retry policy: attempt count 1 < `max_transport_retries (2)`.
   - Checks remaining deadline: elapsed 1,200ms < `deadline_ms (30,000ms)`.
   - Applies exponential backoff (e.g. 500ms) or switches immediately to Deployment B in the approved fallback list.
4. **Successful Failover**: Deployment B completes the request successfully.
5. **Authoritative Logging**:
   - Record `requested_model="MODEL_ECONOMY"`.
   - Record `resolved_model="gemini-1.5-flash-002-primary"`.
   - Record `actual_model="gemini-1.5-flash-002-secondary"`.
   - Reason logged: `transport_fallback_429`.
6. **Delivery to Caller**: Caller receives the response without supervisor intervention.

### 5. Concrete Gateway Configuration & Trace (Labeled Illustrative)

#### Minimal Gateway Fallback Configuration (`litellm_config.yaml`)

```yaml
model_list:
  - model_name: MODEL_ECONOMY
    litellm_params:
      model: gemini/gemini-1.5-flash-002
      api_key: os.environ/GEMINI_API_KEY
    rpm: 1000
  - model_name: MODEL_ECONOMY
    litellm_params:
      model: openai/gpt-4o-mini
      api_key: os.environ/OPENAI_API_KEY
    rpm: 5000

router_settings:
  routing_strategy: usage-based-routing
  allowed_fails: 2
  cooldown_time: 30
  retry_after: 5
```

#### Execution Trace (Labeled Illustrative)

```text
[GATEWAY DISPATCH]: Requesting 'MODEL_ECONOMY' (Routing to gemini-1.5-flash-002).
[GATEWAY HTTP ERROR]: Primary endpoint returned 429 Too Many Requests (Rate limit hit).
[GATEWAY POLICY]: Single retry owner activated. Remaining task deadline: 28,400ms.
[GATEWAY FALLBACK]: Switching to secondary fallback in allowlist: openai/gpt-4o-mini.
[GATEWAY HTTP SUCCESS]: Response received from gpt-4o-mini in 1,450ms.
[AUDIT EVENT GENERATED]:
  {
    "event_id": "evt_transport_failover_091",
    "task_id": "task_audit_auth_tokens_001",
    "requested_model": "MODEL_ECONOMY",
    "resolved_model": "gemini-1.5-flash-002",
    "actual_model": "gpt-4o-mini",
    "reason": "transport_429_failover",
    "input_tokens": 1420,
    "output_tokens": 285,
    "monetary_cost_usd": 0.000384
  }
[ORCHESTRATOR]: Received valid response. Execution continues uninterrupted.
```

### 6. Result Verification
- Check that the application orchestrator did not execute a separate outer retry loop.
- Confirm that the actual billed model and provider are correctly reported in the ledger.
- **Safety Assertion**: Confirm that a strong supervisor model (`MODEL_STRONG`) was **never silently downgraded** to a weaker model during a transport fallback.

### 7. Common Pitfalls & Recovery
- **Pitfall: Silent Model Downgrade**: Gateway configured to fall back from Claude 3.7 Sonnet to GPT-4o-mini on 429, destroying complex reasoning capacity.
  - *Recovery*: Hard-pin fallback allowlists within the same capability tier. If no equivalent model exists, fail fast with a transport error rather than corrupting supervisor synthesis.
- **Pitfall: Nested Retry Explosion**: Gateway retries 3 times $\times$ SDK retries 3 times $\times$ Graph retries 3 times = 27 attempts, consuming the entire budget.
  - *Recovery*: Designate exactly one owner for transport retries; disable retries in all other layers.

### 8. Cost & Risk Profile
- **Financial Risk**: Fallback providers may have higher token pricing (e.g. GPT-4o-mini vs Gemini 1.5 Flash). Pre-reserve budget based on the most expensive model in the fallback allowlist.
