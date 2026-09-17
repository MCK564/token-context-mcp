# Troubleshooting & Operational Failure Drills (R08 - R12)

This document collects essential failure drills and recovery recipes addressing runtime contingencies: budget exhaustion, stale retrieval indices, crash recovery, cross-lingual routing parity, and concurrent file write conflicts.

---

## Recipe R08: Budget Exhaustion, User Cancellation & Steering

### 1. When to Use
- The active run approaches its monetary or token budget cap, or the user issues a cancellation or steer signal while worker subagents are executing.
- **Anti-pattern**: Continuing to dispatch pending subtasks after budget exhaustion or silently dropping usage accounting.

### 2. Concrete Recovery Procedure
1. **Circuit Breaker Trip**: Ledger detects `total_committed >= max_budget_limit`.
2. **Immediate Kill Signal**: Broadcast cancellation to all running worker tasks; transition pending tasks to `status="cancelled"`.
3. **Preserve Accounting**: Authoritative ledger retains all settled events and releases unspent reservations.
4. **Graceful Degradation**: Strong supervisor produces an honest partial response explicitly enumerating uncompleted tasks, rather than inventing unverified conclusions.

---

## Recipe R09: Stale Index or Inaccessible URI Fallback

### 1. When to Use
- Token-Context MCP index returns `status="stale"` (e.g. modified source files pending re-index), or a remote hosted worker receives a local file URI it cannot access.
- **Anti-pattern**: Worker hallucinating file contents or silently trusting outdated symbol graphs.

### 2. Concrete Recovery Procedure
1. **Freshness Verification**: Worker reads file metadata; compares disk SHA-256 against index digest.
2. **Detection of Stale State**: Index reports digest mismatch or pending status for target file.
3. **Bounded Direct Fallback**: Bypass stale index; read targeted line span directly from source disk or request a freshened snippet via the host's direct filesystem tools.
4. **Provenance Disclosure**: Worker result explicitly flags `evidence_freshness="direct_disk_read_stale_index_fallback"`.

---

## Recipe R10: Crash Recovery & Idempotent Resume

### 1. When to Use
- Host process crashes, disconnects, or restarts mid-orchestration during a multi-worker workflow.
- **Anti-pattern**: Restarting the entire workflow from scratch and re-running billable model calls, or duplicating file write side-effects.

### 2. Concrete Recovery Procedure
1. **Persistent Checkpointer Ingestion**: Graph engine reloads latest verified state snapshot from SQLite/Postgres using `run_id`.
2. **Idempotent State Reducer**: Reducer deduplicates incoming events using key `(task_id, attempt_id, result_revision)`. Completed tasks are never re-dispatched.
3. **Ledger Reconciliation**: Reconcile in-flight reservations against provider logs before admitting any new calls.
4. **Seamless Resume**: Only dispatch tasks that were in `ready` or uncommitted `running` state at the moment of interruption.

---

## Recipe R11: Cross-Lingual Parity Failure Drills

### 1. When to Use
- You receive equivalent prompts in English and Vietnamese (including unaccented Vietnamese and code-mixed developer phrasing).
- You must verify that both languages yield identical task-family routing, identical model tier selection, and equivalent answer quality.

### 2. Concrete Audit Drill

```text
[TEST CASE EN]: "Inspect how pack_by_budget drops items in token_budget.py"
  -> Route: extract_evidence (sim: 0.865) -> Tier: MODEL_ECONOMY
[TEST CASE VI]: "Kiểm tra cách pack_by_budget bỏ qua các mục trong token_budget.py"
  -> Route: extract_evidence (sim: 0.852) -> Tier: MODEL_ECONOMY
[TEST CASE VI UNACCENTED]: "Kiem tra cach pack_by_budget bo qua cac muc trong token_budget.py"
  -> Route: extract_evidence (sim: 0.838) -> Tier: MODEL_ECONOMY
[TEST CASE VI CODE-MIXED]: "Check giup minh logic pack_by_budget trong token_budget.py xem co bi drop item khong"
  -> Route: extract_evidence (sim: 0.841) -> Tier: MODEL_ECONOMY
```

### 3. Verification Assertion
- Confirm all 4 variants route to `extract_evidence` and select `MODEL_ECONOMY`. If any variant triggers `unknown` or selects a different tier, expand semantic route exemplars.

---

## Recipe R12: Multi-Worker Conflicting Edits Isolation

### 1. When to Use
- Two parallel workers are assigned tasks that inadvertently touch overlapping files or shared configurations.
- **Anti-pattern**: Allowing both workers to write concurrently to the same local working directory, corrupting files with race conditions.

### 2. Concrete Isolation & Resolution Procedure
1. **Pre-dispatch Scope Validation**: Scheduler checks `allowed_scope_files` across all concurrent tasks. If overlap is detected:
   - *Option A (Serialization)*: Convert to sequential DAG (Task A completes before Task B runs).
   - *Option B (Patch Isolation)*: Workers generate unified diff patches (`.diff`) in memory; workers are strictly forbidden from writing directly to working tree files.
2. **Supervisor Conflict Reconciliation**: The strong supervisor ingests both diffs, inspects overlapping line spans, resolves conflicting hunk edits, and performs a single validated write operation.
