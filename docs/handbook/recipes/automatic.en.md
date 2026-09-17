# Automatic & Semantic Routing Recipes (Path C / M3)

This guide provides operational recipes for automatic semantic task-family routing, threshold calibration, route abstention, and deterministic failure escalation when coordinating economical workers under strict quality and budget constraints.

---

## Recipe R05: Ambiguous Semantic Route & Abstention

### 1. When to Use
- You deploy a dense embedding router (e.g. Aurelio Semantic Router) to classify subtasks dynamically into task families.
- A subtask yields a cosine similarity below the route's calibrated threshold, or the margin between the top-1 and top-2 candidate routes is too narrow (e.g. margin $< 0.08$).
- **Anti-pattern**: Forcing an unconfident classification into an economical worker tier simply to minimize nominal token price, risking incorrect execution or costly downstream hallucination.

### 2. Prerequisites
- Configured semantic router with dual-language positive and negative exemplars.
- Pre-computed, empirically calibrated cosine thresholds and margin requirements per route.
- A defined fallback policy for `RouteDecision.selected_route_family == "unknown"`.

### 3. Inputs & Outputs
- **Input**: A borderline subtask query (e.g. *"Review this authentication module and suggest security improvements or re-architect the token format"*).
- **Output**: A `RouteDecision` with `selected_route_family="unknown"`, triggering safe abstention and routing the task to the strong supervisor.

### 4. Step-by-Step Procedure
1. **Embedding Extraction**: Generate embedding vector for the subtask objective.
2. **Similarity & Margin Computation**:
   - Top-1 route: `extract_evidence` (similarity: 0.76; threshold: 0.82) -> Below threshold.
   - Top-2 route: `cross_file_design` (similarity: 0.74; threshold: 0.85) -> Below threshold.
   - Top-1 vs Top-2 Margin: $0.76 - 0.74 = 0.02$ (margin $< 0.08$).
3. **Abstention Gate Trigger**: Because neither similarity threshold nor top-1/top-2 margin is satisfied, the router enters **Abstention**.
4. **Fallback Action**: Mark route as `unknown`. Escalate the subtask to the strong supervisor (`MODEL_STRONG`) rather than guessing an economical tier.
5. **Telemetry Logging**: Record similarity score, margin, and abstention event for future threshold calibration.

### 5. Concrete Execution Trace (Labeled Illustrative)

```text
[SEMANTIC ROUTER]: Evaluating subtask: "Audit security boundaries and propose redesign of token exchange"
[EMBEDDING INFERENCE]: Generated 1536-dim vector via text-embedding-3-small.
[COSINE SCORES]:
  - candidate_1: 'extract_evidence' -> similarity = 0.762 (required >= 0.820) [FAIL]
  - candidate_2: 'cross_file_design' -> similarity = 0.741 (required >= 0.850) [FAIL]
  - calculated_margin: 0.021 (required >= 0.080) [FAIL]
[ROUTER DECISION]: Ambiguous classification. Triggering ABSTENTION.
[ROUTE DECISION RECORD]:
  {
    "selected_route_family": "unknown",
    "rule_match_reason": "ambiguous_semantic_boundary_margin_too_low",
    "selected_model_alias": "MODEL_STRONG",
    "action": "retain_in_supervisor"
  }
[SUPERVISOR]: Acknowledged abstention event. Handling subtask directly without economy delegation.
```

### 6. Result Verification
- Verify that `selected_route_family` is explicitly set to `"unknown"`.
- Ensure no subagent call was dispatched to `MODEL_ECONOMY`.
- Confirm that the router did not treat cosine similarity as an uncalibrated probability of correctness.

### 7. Cost & Risk Profile
- **Trade-off**: Incurs the higher per-token cost of `MODEL_STRONG` on the ambiguous task.
- **Benefit**: Prevents catastrophic errors where an economical model is given an ambiguous, multi-module architectural refactoring task it cannot solve.

---

## Recipe R06: Worker Failure & Bounded Escalation

### 1. When to Use
- An economical worker executes a delegated subtask but returns an invalid schema, fabricated line numbers, mismatched SHA-256 hashes, or fails mechanical validation.
- **Anti-pattern**: Entering an unbounded repair loop (retry loop) between worker and supervisor that multiplies token consumption beyond the cost of simply calling the strong model.

### 2. Prerequisites
- Mechanical validator evaluating worker outputs against verifiable disk files or test outputs.
- Policy rule enforcing `max_repair_attempts=1` and `max_escalation_depth=1`.
- Authoritative budget ledger tracking failed attempts.

### 3. Inputs & Outputs
- **Input**: A `WorkerResult` where line spans do not match actual repository content.
- **Output**: One bounded repair attempt; if still failing, escalation to `MODEL_STRONG` with full audit trace.

### 4. Step-by-Step Procedure
1. **Worker Submission**: Worker completes subtask and submits `WorkerResult(attempt_id=1)`.
2. **Mechanical Verification**: Validator tests content hash against disk.
   - *Result*: Line span `50-80` in `server.py` does not contain the cited function. Validation **REJECTED**.
3. **Bounded Repair Evaluation**:
   - Check `attempts`: attempt count is 1 $\le$ `max_repair_attempts (1)`.
   - Check budget: ledger has sufficient reserve for one repair.
   - Dispatch repair prompt to worker highlighting the exact mismatch.
4. **Second Failure / Escalation Trigger**:
   - Worker submits `WorkerResult(attempt_id=2)` but still reports inaccurate line numbers.
   - Validator marks result **REJECTED (repair exhausted)**.
5. **Quality Escalation**:
   - Transition task to **Escalated to Strong**.
   - Dispatch subtask to `MODEL_STRONG` with prior failed context.
   - Record both failed worker attempts and the successful strong attempt in the budget ledger.

### 5. Concrete Execution Trace (Labeled Illustrative)

```text
[WORKER]: Submitted attempt 1 for task 'verify_sqlite_schema'.
[VALIDATOR]: Checking sha256 of src/token_context_mcp/index/sqlite_store.py:30-45.
[VALIDATOR ERROR]: Cited content does not match disk hash. Difference detected at line 34.
[STATE]: REJECTED. Repair count: 0/1. Triggering bounded repair.
[DISPATCH REPAIR]: "Your cited span 30-45 does not match the file on disk. Please re-read the exact lines."
[WORKER]: Submitted attempt 2. Cited span: 40-55.
[VALIDATOR ERROR]: Cited span 40-55 still missing target schema definition.
[STATE]: REJECTED. Repair attempts exhausted (2/2). Triggering QUALITY ESCALATION.
[BUDGET LEDGER]: Worker attempt 1 ($0.0002) + attempt 2 ($0.0002) recorded as failed attempt costs.
[ESCALATION DISPATCH]: Handing task 'verify_sqlite_schema' to MODEL_STRONG.
[SUPERVISOR]: MODEL_STRONG locates exact definition at sqlite_store.py:98-142 with verified hash.
[VALIDATOR]: Hash verified -> State: ACCEPTED.
```

### 6. Result Verification
- Confirm total repair attempts for this task strictly equaled 1.
- Confirm both worker attempts (1 & 2) and the strong model attempt are individually accounted for in the budget ledger.
- Verify that the final cost of the task reflects: $C_{task} = C_{worker\_att1} + C_{worker\_att2} + C_{strong}$.

### 7. Cost & Risk Profile
- **Break-even Rule**: If an economical worker fails frequently ($p > 0.3$), cascading through repair and escalation costs more than dispatching directly to the strong model. Use this recipe's audit logs to adjust model routing rules.
