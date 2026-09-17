# Bilingual Parity Register & Terminology Standard

This register establishes the canonical bilingual alignment between the English and Vietnamese editions of the Multi-Agent Routing Handbook suite. It enforces consistent conceptual translations while guaranteeing that all code identifiers, JSON schema attributes, mathematical formulas, and status enums remain identical and untranslated across languages.

---

## 1. Canonical Terminology Alignment

| English Term | Vietnamese Term | Architectural Definition & Context | Untranslated Identifier / Enum |
| :--- | :--- | :--- | :--- |
| **Supervisor** | **Bộ điều phối** | The strong parent model holding primary task authority, planning, and final synthesis. | `role="supervisor"` |
| **Worker** | **Tác nhân thực thi** | A bounded subagent utilizing an economical or specialized model for narrow tasks. | `role="worker"` |
| **Task-Family Routing** | **Định tuyến nhóm tác vụ** | Classifying a subtask into functional capability categories (e.g. extraction, formatting). | `task_family` |
| **Model Selection** | **Lựa chọn mô hình** | Choosing a specific model tier based on empirical quality evidence and cost profiles. | `selected_model_alias` |
| **Conditional Branching** | **Rẽ nhánh có điều kiện** | Graph-driven control flow routing execution to tools, workers, repair, or escalation. | Conditional Edge / `branch` |
| **Abstention** | **Không quyết định / Từ chối định tuyến** | Returning `unknown` when similarity or margin falls below calibrated thresholds. | `route_decision="unknown"` |
| **Escalation** | **Nâng cấp model / Chuyển lên model mạnh** | Re-routing an unresolvable or failed subtask to the strong parent or high-tier model. | `action="escalate"` |
| **Verification** | **Kiểm chứng** | Mechanical or semantic validation of worker results against objective criteria. | `verify_worker_result` |
| **Accepted** | **Đã đạt kiểm chứng** | Terminal state where worker output passes all deterministic and semantic checks. | `status="accepted"` |
| **Completed** | **Đã hoàn tất xử lý** | Worker status indicating execution finished; does **not** imply correctness or acceptance. | `status="completed"` |
| **Bounded Repair** | **Sửa chữa có giới hạn** | An isolated, capped attempt (typically max 1) allowing the worker to remediate specific errors. | `repair_attempt` |
| **Provenance** | **Nguồn gốc bằng chứng** | Verifiable links, file paths, line spans, and commit SHAs backing all returned claims. | `evidence_refs` |
| **Budget Ledger** | **Sổ cái ngân sách** | Centralized ledger recording token counts, monetary costs, reservations, and settlements. | `BudgetLedger` |
| **Reservation** | **Tạm giữ ngân sách** | Earmarking upper-bound cost before dispatching an LLM or tool call. | `status="reserved"` |
| **Settlement** | **Quyết toán ngân sách** | Reconciling the actual recorded token usage and monetary cost upon call completion. | `status="settled"` |

---

## 2. Invariant Code, Schema & Technical Identifiers

To guarantee full runtime interoperability across language implementations, the following elements **must remain in English** in both Vietnamese and English documentation:

1. **JSON Contract Fields**:
   - `task_id`, `run_id`, `request_revision`, `objective`, `allowed_scope_files`, `dependency_task_ids`, `acceptance_criteria`, `context_evidence_refs`, `allowed_tool_families`, `mutation_rights`, `model_policy_id`, `budget_reserve`, `deadline_ms`, `escalation_conditions`.
   - `attempt_id`, `result_revision`, `status`, `bounded_answer`, `artifacts_or_changes`, `checks_actually_run`, `unknowns`, `usage_event_ref`.
   - `provider_request_id`, `requested_model`, `resolved_model`, `actual_model`, `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `monetary_cost`.
2. **State & Lifecycle Enums**:
   - Statuses: `ready`, `running`, `completed`, `accepted`, `rejected`, `partial`, `blocked`, `failed`, `cancelled`, `unresolved`.
   - Decisions: `rule_match`, `semantic_match`, `unknown`, `abstain`.
3. **Mathematical Formulas**:
   - $C_{run} = C_{parent\_plan} + C_{router} + \sum C_{worker\_attempts} + C_{tools} + C_{verify} + C_{parent\_final}$
   - Cost per accepted task formula, precision, recall, and Brier calibration scores.
4. **Mermaid Flowchart Identifiers**:
   - Graph node IDs (`A`, `B`, `Q`, `C`, `P`, `R`, `K`, `T`, `V`, `W`, `X`, `J`, `U`, `D`, `G`, `S`, `F`, `F0`).

---

## 3. Structural Parity Checklist (15 Chapters & 12 Recipes)

| ID | English Section / Recipe Name | Vietnamese Section / Recipe Name | Technical Content Alignment |
| :--- | :--- | :--- | :---: |
| **H01** | One Prompt, Multiple Calls; Roles | Một Prompt, Nhiều Lời Gọi; Các Vai Trò | Identical sequence diagram & trace |
| **H02** | Selecting Native Host, SDK, or Graph Engine | Lựa Chọn Native Host, SDK hoặc Graph Engine | Capability matrix & decision tree |
| **H03** | Manual Orchestration Within One Prompt | Điều Phối Thủ Công Trong Cùng Một Prompt | M1 blueprint, token containment rules |
| **H04** | Task Decomposition & Context Packaging | Phân Rã Tác Vụ & Đóng Gói Ngữ Cảnh | TaskSpec/WorkerResult schema contracts |
| **H05** | Rule-Based Routing Baseline | Định Tuyến Dựa Trên Luật (Baseline) | Deterministic task-to-tier decision table |
| **H06** | Semantic Embedding Task Router | Định Tuyến Tác Vụ Bằng Semantic Embedding | Aurelio router, calibration & abstention |
| **H07** | Model Selector & Cascade Strategies | Bộ Chọn Mô Hình & Chiến Lược Phân Tầng | Cost-aware selection & quality thresholds |
| **H08** | Conditional Branching in Graphs | Rẽ Nhánh Có Điều Kiện Trong Graph | LangGraph state, conditional edges, reducers |
| **H09** | Optional LLM Gateway Layer | Tầng LLM Gateway Tùy Chọn | Transport proxy vs orchestrator separation |
| **H10** | Context, Tokens, and Caching | Ngữ Cảnh, Quản Lý Token & Cơ Chế Cache | Minimal briefs, handles, supervisor overhead |
| **H11** | Verification & Deterministic Failure Handling | Kiểm Chứng & Xử Lý Lỗi Xác Định | Multi-stage validator & decision table |
| **H12** | Measuring Quality, Latency, and Cost | Đo Lường Chất Lượng, Độ Trễ & Chi Phí | All-attempt accounting, baselines, gates |
| **H13** | Operations, Security & Access Boundaries | Vận Hành, Bảo Mật & Ranh Giới Truy Cập | Data exfiltration, cancellation, audit log |
| **H14** | Production Recipes & Failure Drills | Các Recipe Vận Hành & Kịch Bản Ứng Phó | Master index for R01 through R12 |
| **H15** | Roadmap, Maturity Ladder & Terminology | Lộ Trình Phát Triển, Thang Đo & Thuật Ngữ | Maturity stages from pilot to production |
| **R01** | One-Prompt Repository Audit | Kiểm Toán Kho Mã Nguồn Trong Một Prompt | Identical M1 flow & validation trace |
| **R02** | Task Too Small / No-Delegate Branch | Tác Vụ Quá Nhỏ / Nhánh Không Phân Quyền | Direct tool or immediate parent handling |
| **R03** | Independent Batch Fan-Out | Phân Tán Song Song Cho Lô Tác Vụ Độc Lập | Bounded concurrency & safe join barrier |
| **R04** | Dependent Task DAG Execution | Thực Thi Chuỗi Tác Vụ Có Phụ Thuộc (DAG) | Sequential dependency gating & validation |
| **R05** | Ambiguous Semantic Route Abstention | Xử Lý Khi Định Tuyến Ngữ Nghĩa Mơ Hồ | Margin check & safe abstention fallback |
| **R06** | Worker Failure & Bounded Escalation | Xử Lý Khi Worker Thất Bại & Nâng Cấp Bậc | Reject, single repair, strong escalation |
| **R07** | Provider 429/Timeout Retry & Fallback | Xử Lý Lỗi 429/Timeout & Fallback Endpoint | Transport retry owner & audit records |
| **R08** | Budget Exhaustion, Cancel & Steering | Hết Ngân Sách, Hủy Bỏ & Thay Đổi Hướng | Immediate halting & partial status reporting |
| **R09** | Stale Index or Inaccessible URI Fallback | Xử Lý Khi Index Lỗi Thời Hoặc URI Bị Lỗi | Freshness check & bounded source fallback |
| **R10** | Crash Recovery & Idempotent Resume | Khôi Phục Sau Sự Cố & Tiếp Tục Idempotent | Checkpointer replay & deduplication |
| **R11** | Cross-Lingual Parity Failure Drills | Thử Nghiệm Đối Chiếu Đa Ngôn Ngữ EN/VI | Equivalent prompt routing & quality audit |
| **R12** | Multi-Worker Conflicting Edits Isolation | Cách Ly Xung Đột Khi Nhiều Worker Sửa File | Single-owner isolation & patch reconciliation |
