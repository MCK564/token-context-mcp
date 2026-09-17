# Multi-Agent Routing Evaluation Protocol & Quality Gates

This document establishes the scientific evaluation methodology, cost-accounting formulas, baseline comparisons, and pre-established rollout gates for multi-agent routing architectures coordinating strong and economical models.

---

## 1. Authoritative Cost Accounting Formula

To prevent false claims of token savings, all evaluation runs must account for every billable inference, embedding, validator, and retry call across all attempts:

$$C_{run} = C_{parent\_plan} + C_{router} + \sum C_{all\_worker\_attempts} + C_{tools} + C_{verify} + C_{parent\_synthesis}$$

### Accounting Rules
1. **Mutually Exclusive Buckets**:
   - $\sum C_{all\_worker\_attempts}$ includes all initial worker dispatches, bounded repairs, and strong-worker escalations.
   - Any escalation handled directly by the supervisor is accounted for in $C_{parent\_synthesis}$ and must **never** be counted twice.
2. **Provider Request ID Grounding**:
   - The authoritative ledger records each unique `provider_request_id` exactly once.
   - Active reservations are temporary holds; only settled amounts represent actual expenditures.
3. **Failed Attempts Are Included**:
   - Tokens consumed by timed-out, rejected, or crashed worker attempts remain permanently in the total cost denominator.

---

## 2. Illustrative Break-Even Analysis

A worker delegation architecture only produces real economic savings when worker success rates remain high and verifier costs remain low.

```text
[ILLUSTRATIVE EXAMPLE (NOT REAL BENCHMARK DATA)]:
  - Baseline (Strong-Only Single Agent): 100 cost units
  - Multi-Agent Orchestration (Parent plan + Router + Economy Worker + Verifier + Synthesis): 70 cost units
  - Escalation Penalty (When worker fails and task must be re-run on strong model): 60 cost units
  - Probability of Worker Failure: p

Expected Multi-Agent Cost = 70 + 60 * p

Break-even Condition:
  70 + 60 * p < 100
  60 * p < 30
  p < 0.50
```

> [!IMPORTANT]
> If an economical model fails more than 50% of the time on a specific task family ($p \ge 0.50$), delegating to it increases total cost and latency compared to executing directly on the strong model.

---

## 3. Mandatory Evaluation Baselines

Every evaluation must benchmark against these 8 standardized configurations under identical repository snapshots and test prompts:

| Baseline ID | Name | Architecture | Purpose |
| :--- | :--- | :--- | :--- |
| **B01** | **Strong-Only Baseline** | Single agent using `MODEL_STRONG` | Primary benchmark: highest quality, baseline cost. |
| **B02** | **Economy-Only Baseline** | Single agent using `MODEL_ECONOMY` | Floor benchmark: lowest per-token cost, quality ceiling. |
| **B03** | **Manual Static Delegation** | Parent delegates fixed subtasks without router | Measures coordination overhead without routing logic. |
| **B04** | **Rule-Based Routing** | Deterministic if-else decision table | Establishes zero-cost routing baseline. |
| **B05** | **Semantic Embedding Router** | Cosine similarity against exemplars | Evaluates vector classification accuracy and latency. |
| **B06** | **Learned Router (RouteLLM)** | Preference-trained classifier | Evaluates learned tier prediction against rules. |
| **B07** | **Cheap-First Cascade** | Always try economy first, escalate on failure | Evaluates speculative execution efficiency. |
| **B08** | **Proposed Hybrid Architecture** | Rules $\rightarrow$ Semantic $\rightarrow$ Capability $\rightarrow$ Escalation | Evaluates full handbook design. |

---

## 4. Key Performance Metrics

### Primary Metrics
1. **Completion Rate ($R_{comp}$)**:
   $$R_{comp} = \frac{N_{accepted\_tasks}}{N_{total\_assigned\_tasks}}$$
2. **Amortized Cost Per Accepted Task ($C_{accepted}$)**:
   $$C_{accepted} = \frac{\sum C_{all\_attempts}}{N_{accepted\_tasks}}$$
   *(If $N_{accepted\_tasks} = 0$, $C_{accepted}$ is undefined).*
3. **Latency Profiles**: $p50$ and $p95$ wall-clock latency from user request to final synthesized answer.

### Routing & Validation Diagnostic Metrics
- **Abstention Rate**: Fraction of subtasks where semantic router returned `unknown`.
- **Wrong-Economy Assignment**: Fraction of subtasks routed to `MODEL_ECONOMY` that required quality escalation.
- **Verifier False Acceptance ($FAR$)**: Fraction of subtasks where mechanical or LLM validator accepted an objectively incorrect result.

---

## 5. Pre-Established Rollout Quality Gates

Before any multi-agent routing configuration is certified for production deployment, it must satisfy all 5 pre-established gates:

| Gate Identifier | Metric Evaluated | Required Threshold | Consequence of Failure |
| :--- | :--- | :--- | :--- |
| **GATE-01** | Contract Compliance | **100%** schema valid | Block rollout; fix JSON schema serializer. |
| **GATE-02** | Golden Pilot Regressions | **0 new regressions** vs B01 | Block rollout; revert task decomposition. |
| **GATE-03** | Production Quality Non-Inferiority | Within **2 percentage points** of B01 | Reject model tier assignment. |
| **GATE-04** | Economic Efficiency | $\ge 15\%$ reduction in $C_{accepted}$ | Re-route ambiguous tasks to parent. |
| **GATE-05** | Latency Tolerance | $p95$ latency increase $\le 10\%$ | Cap `max_parallel_workers` or optimize prompt length. |

> [!CAUTION]
> Both English and Vietnamese test suites must pass these gates **independently**. Success on English workloads cannot compensate for a regression on Vietnamese workloads.
