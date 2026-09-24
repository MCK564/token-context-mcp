# BÁO CÁO ĐƯỜNG CƠ SỞ (BASELINE 2026-09) — TOKEN-CONTEXT-MCP (M0)

> **Nhánh thực hiện:** `feat/m0-baseline`  
> **Thời điểm đo:** 2026-09-24  
> **Môi trường:** Windows, Python 3.12, `uv`  
> **Cam kết M0:** Tuyệt đối không sửa đổi `src/` (`git diff --stat src/` rỗng). Toàn bộ script đo lường chạy được trên cả repository thực tế `token-context` và repository giả lập quy mô lớn `synthetic-5k`.

---

## 1. Kết quả kiểm tra đầu vào Phần A (A1 – A6) kèm bằng chứng thực nghiệm

| Mục | Lệnh / Lời gọi | Kết quả thực tế quan sát được | Kết luận & Đối chiếu Plan |
|---|---|---|---|
| **A1** | `srv.status("token-context")` | `index_run_id`: `"run_20260924T054243Z_62259952"`<br>`files_indexed`: 191<br>`symbols_indexed`: 662<br>`edges_indexed`: 1418<br>`freshness`: `"stale"`<br>`pending_paths`: `["README.md"]` | Khớp 100% mô tả đầu vào. Index đang ở trạng thái stale do có 1 pending path (`README.md`). |
| **A2 (E1)** | `wf.inspect_symbol("token-context", query="rank_symbols", view="full")` | `data.target_symbol_id`: `python:src/token_context_mcp/retrieve/ranking.py:rank_symbols:beef3dae7cd47590`<br>`data.symbol`: `{}` (rỗng) | **Khớp lỗi E1:** trường `data.symbol` hoàn toàn rỗng, bên gọi không nhận được nội dung/chữ ký của symbol đích. Cần sửa trong M1.1. |
| **A3 (E2)** | `srv.find_symbols("token-context", pattern="*Service*")`<br>`srv.find_symbols("token-context", pattern="*", kind="class")` | `pattern="*Service*"` trả về **0** kết quả.<br>`pattern="*"` (kind=class) trả về **0** kết quả. | **Khớp lỗi E2:** `SQLiteStore.find_symbols` chưa hỗ trợ ký tự đại diện wildcard `*` và `?`. Cần sửa trong M1.3. |
| **A4 (E3)** | `srv.search_source("token-context", query="def _invoke")` | `matches`: 1<br>`symbol_id`: `python:src/token_context_mcp/server.py:build_server:d881992658b933b7`<br>`snippet`: `def build_server(config_path: Path, enable_extensions: bool | None = None) -> MCPServer:`<br>`line_evidence`: `None` | **Khớp lỗi E3:** `def _invoke` nằm ở L52 của `server.py` bên trong `build_server`, nhưng `search_source` trả về symbol bao ngoài cùng (`build_server`) và dòng snippet đầu tiên thay vì dòng khớp chính xác `def _invoke`. Cần sửa trong M1.4. |
| **A5 (E6)** | `find_symbols("MemoryStore.get")` → `impact_slice(callers, depth=1, min_conf=0, filter_ambiguous=false)` | Symbol ID: `python:src/token_context_mcp/memory/store.py:MemoryStore.get:8f58ed0bc164eac5`<br>Tổng số callers: **14** cạnh.<br>Số caller thực sự gọi `MemoryStore.get`: **0 / 14 (0%)** | **Khớp lỗi E6:** 100% callers là dương tính giả (false positive) do `dict.get(...)` (e.g. `response.get`, `agent.get`) và `os.environ.get(...)` rơi vào fallback toàn cục `scope:global` khi chỉ có 1 symbol tên `get`. |
| **A6** | `git ls-files "evals/*.json" "evals/**/*.json"` | Liệt kê các relevance sets:<br>1. `evals/relevance/orientation_invoice_scanner.json`<br>2. `evals/relevance/query_invoice_scanner.json` | Xác định đủ 2 tập nhãn relevance cho `rank_eval.py`. |

---

## 2. Đo lường chi phí ngữ cảnh (Context Cost - C1 & C2)

Lưu tại: `evals/out/m0/context_cost_token_context.json` và `evals/out/m0/context_cost_synthetic_5k.json`.

### 2.1 Repository thực tế: `token-context`
- **Mã nguồn cơ sở:** 98 files, 615,279 bytes ~ 153,820 tokens.
- **Quy mô đồ thị chỉ mục:** 662 symbols, 1,418 edges, tỷ lệ ambiguous 7.1%.

| Tool Call | Declared Tokens | Service Tokens | Wire Tokens | Wire Accounting Gap | Mức tiết kiệm vs đọc thô |
|---|---:|---:|---:|:---:|:---:|
| `repo_map@512` | 397 | 397 | 475 | 1.20x | **323.8x** |
| `repo_map@1024` | 919 | 919 | 997 | 1.08x | **154.3x** |
| `repo_map@2048` | 1,941 | 1,941 | 2,019 | 1.04x | **76.2x** |
| `search_source(ocr)@4096` | 408 | 408 | 473 | 1.16x | **325.2x** |
| `find_symbols(limit=5)` | 731 | 731 | 787 | 1.08x | **195.5x** |
| `file_skeleton@1024` | 738 | 738 | 822 | 1.11x | **187.1x** |
| `symbol_context@1024` | 607 | 607 | 702 | 1.16x | **219.1x** |
| `symbol_context@2048` | 607 | 607 | 702 | 1.16x | **219.1x** |
| `impact_slice(depth=2, max_nodes=75)` | 522 | 522 | 643 | 1.23x | **239.2x** |

- **Khoảng chênh lệch lớn nhất (Worst accounting gap):** 1.23x (PASS giới hạn an toàn wire).
- **Số lượt vượt trần server (`calls_over_server_cap`):** 0.

### 2.2 Repository giả lập quy mô lớn: `synthetic-5k`
- **Mã nguồn cơ sở:** 5,050 files, 5,096,050 bytes ~ 1,274,013 tokens.
- **Quy mô đồ thị chỉ mục:** 40,000 symbols, 25,216 edges, tỷ lệ ambiguous 33.0%.

| Tool Call | Declared Tokens | Wire Tokens | Gap | Mức tiết kiệm |
|---|---:|---:|:---:|:---:|
| `repo_map@512` | 412 | 491 | 1.19x | **2,594.7x** |
| `repo_map@1024` | 915 | 993 | 1.09x | **1,283.0x** |
| `repo_map@2048` | 1,938 | 2,016 | 1.04x | **632.0x** |
| `search_source(ocr)@4096` | 107 | 172 | 1.61x | **7,407.1x** |
| `find_symbols(limit=5)` | 573 | 629 | 1.10x | **2,025.5x** |
| `file_skeleton@1024` | 535 | 619 | 1.16x | **2,058.2x** |
| `symbol_context@1024` | 587 | 680 | 1.16x | **1,873.5x** |
| `impact_slice(depth=2, max_nodes=75)` | 514 | 633 | 1.23x | **2,012.7x** |

---

## 3. Đánh giá chất lượng xếp hạng (Rank Evaluation)

Lưu tại: `evals/out/m0/rank_orientation_*.json` và `evals/out/m0/rank_query_*.json`.

### 3.1 Orientation Task (`orientation_invoice_scanner.json`)
- **Ngân sách:** `budget_tokens = 4096`, `k = 10`.
- **Số symbols trả về:** 186 symbols.

| Tiêu chí | Chế độ Local (Query-free) | Chế độ `--global-rank` |
|---|:---:|:---:|
| **Essential Recall @10** | **0.50** (3/6) | **0.50** (3/6) |
| **Các symbol cốt lõi bị bỏ sót** | `FrontendPipeline`, `InvoiceProcessor`, `ScanResult` | `FrontendPipeline`, `InvoiceProcessor`, `ScanResult` |
| **Nhiễu trong Top-10 (Grade 0)** | 0 | 0 |
| **nDCG@10** | **0.5248** | **0.5248** |

### 3.2 Query-specific Task (`query_invoice_scanner.json`)

| Topic / Query | Local Recall | Local nDCG@10 | Global Recall | Global Noise in Top-10 | Global nDCG@10 |
|---|:---:|:---:|:---:|:---:|:---:|
| `[ocr]` *ocr text recognition* | 3/3 (1.000) | 0.5273 | 0/3 (0.000) | 2 (`get_frontend`, `extract_with_trace`) | 0.0000 |
| `[field-extraction]` *field extraction amount date* | 2/4 (0.500) | 0.5205 | 1/4 (0.250) | 1 (`get_frontend`) | 0.1510 |
| `[registry]` *frontend registry selection* | 2/2 (1.000) | 0.8829 | 1/2 (0.500) | 0 | 0.4169 |
| `[render]` *render display ocr input* | 1/2 (0.500) | 0.3666 | 1/2 (0.500) | 1 (`get_frontend`) | 0.1642 |
| `[geometry]` *page detection corners geometry* | 2/3 (0.667) | 0.5521 | 1/3 (0.333) | 1 (`extract_with_trace`) | 0.3406 |
| **Trung bình toàn bộ (Mean)** | **0.733** | **0.5699** | **0.317** | **Tổng 5 nhiễu** | **0.2145** |
| **Số danh sách Top-10 phân biệt** | **5 / 5** | — | **1 / 5 (bị sụp về 1)** | — | — |

---

## 4. Benchmark độ trễ & chi phí Hashing (`evals/bench_latency.py`)

Lưu tại: `evals/out/m0/bench_latency_token_context.json` và `evals/out/m0/bench_latency_synthetic_5k.json`.

### 4.1 Trên `token-context` (n = 20 lượt lặp)
| Công cụ | p50 (ms) | p95 (ms) | Max (ms) | `sha256_file` / call | `sha256_bytes` / call |
|---|---:|---:|---:|---:|---:|
| `list_repositories` | 0.46 | 0.54 | 0.79 | 0.0 | 0.0 |
| `get_index_status` | 161.48 | 172.97 | 177.54 | 1.0 | 0.0 |
| `get_repo_map@1024` | 97.07 | 139.53 | 159.34 | 1.0 | 0.0 |
| `find_symbols` | 58.71 | 68.77 | 77.74 | 1.0 | 0.0 |
| `search_source` | 147.64 | 163.30 | 164.84 | 1.0 | 0.0 |
| `get_file_skeleton` | 77.86 | 135.47 | 135.89 | 1.0 | 0.0 |
| `get_symbol_context` | 210.66 | 221.61 | 244.33 | 1.0 | 0.0 |
| `get_impact_slice` | 267.37 | 277.51 | 281.97 | 1.0 | 0.0 |
| `get_module_dependents` | 0.00 | 0.00 | 0.00 | 0.0 | 0.0 |
| `inspect_symbol` | 460.91 | 526.31 | 526.33 | 3.0 | 0.0 |

### 4.2 Trên `synthetic-5k` (n = 5 lượt lặp, 5,051 files)
| Công cụ | p50 (ms) | p95 (ms) | Max (ms) | Nhận xét điểm nghẽn |
|---|---:|---:|---:|---|
| `list_repositories` | 0.14 | 0.17 | 0.17 | Không phụ thuộc kích thước repo. |
| `get_index_status` | 2,866.53 | 3,015.29 | 3,043.69 | Chi phí quét freshness toàn bộ 5,051 file. |
| `get_repo_map@1024` | 3,985.26 | 4,083.65 | 4,086.32 | Freshness check + PageRank trên 40,000 nodes. |
| `find_symbols` | 2,072.28 | 2,101.54 | 2,108.37 | Chi phí freshness check chiếm đa số. |
| `search_source` | 1,958.85 | 2,033.72 | 2,050.34 | FTS5 query nhanh (~20ms), freshness chiếm ~1.9s. |
| `get_file_skeleton` | 1,880.37 | 1,951.88 | 1,954.25 | Parse Tree-sitter 1 file ~15ms, còn lại là freshness. |
| `get_symbol_context` | 1,973.73 | 2,146.21 | 2,166.97 | Đồ thị ngữ cảnh trên SQLite. |
| `get_impact_slice` | 2,006.87 | 2,177.87 | 2,211.60 | DFS traversal trên SQLite. |
| `inspect_symbol` | 6,038.45 | 6,096.41 | 6,099.07 | Ghép composite 3 tool calls liên tiếp. |

---

## 5. Kiểm toán cạnh đồ thị (Edge Audit - `evals/edge_audit.py`)

Lưu tại: `evals/out/m0/edge_audit_token_context.json` và `evals/out/m0/edge_audit_synthetic_5k.json`.

### 5.1 Hiện tượng "Bẫy In-Degree & Fallback Toàn Cục" trên `token-context`
- **Tổng số symbols:** 662.
- **Tổng số cạnh:** 1,418.
- **Số cạnh đáng ngờ phát hiện được:** **90 cạnh**.
- **Top 1 điểm đến có In-Degree cao nhất:**
  - Symbol: `MemoryStore.get` (`src/token_context_mcp/memory/store.py`)
  - **In-degree:** 53 cạnh.
  - **Số cạnh đáng ngờ (Suspicious):** **53 / 53 (100.0%)**!
  - **Nguyên nhân cốt lõi:** Các lệnh gọi `.get(...)` trên kiểu dữ liệu từ điển (`dict.get`), môi trường (`os.environ.get`), từ các file đánh giá và công cụ khác bị phân giải sai vào `MemoryStore.get` do cơ chế fallback `scope:global` khi chỉ có 1 symbol tên `get` trong repo.

### 5.2 Top 10 đích đến theo In-Degree trên `token-context`
| # | Target Symbol | Đường dẫn | In-Degree | Nghi ngờ | Ambiguous | Tỷ lệ nghi ngờ |
|---|---|---|---:|---:|---:|---:|
| 1 | `MemoryStore.get` | `src/token_context_mcp/memory/store.py` | 53 | 53 | 0 | **100.0%** |
| 2 | `load_config` | `src/token_context_mcp/config.py` | 29 | 0 | 0 | 0.0% |
| 3 | `parse_source` | `src/token_context_mcp/parse/treesitter.py` | 26 | 0 | 0 | 0.0% |
| 4 | `SQLiteStore.connection` | `src/token_context_mcp/index/sqlite_store.py` | 23 | 0 | 0 | 0.0% |
| 5 | `_service` | `tests/test_index_retrieval.py` | 22 | 0 | 0 | 0.0% |
| 6 | `_wrap` | `src/token_context_mcp/server.py` | 21 | 0 | 0 | 0.0% |
| 7 | `AppConfig` | `src/token_context_mcp/models.py` | 17 | 3 | 0 | 17.6% |
| 8 | `RetrievalService.find_symbols` | `src/token_context_mcp/retrieve/service.py` | 17 | 0 | 0 | 0.0% |
| 9 | `save_config` | `src/token_context_mcp/config.py` | 16 | 0 | 0 | 0.0% |
| 10 | `RetrievalError` | `src/token_context_mcp/retrieve/service.py` | 16 | 0 | 0 | 0.0% |

### 5.3 Trên repository giả lập `synthetic-5k`
- **Tổng số cạnh đáng ngờ:** **12,565 / 25,216 cạnh (49.8%)** — toàn bộ bắt nguồn từ các lời gọi `dict.get` và `os.environ.get` bị disambiguation sai vào các class service.

---

## 6. Kiểm toán tương thích Schema LLM (`evals/schema_compat.py`)

Lưu tại: `evals/out/m0/schema_compat.json`.

- **Số công cụ MCP quét:** 21 tools (10 core retrieval + 9 extended + 2 admin).
- **Số file schema tĩnh:** 2 files (`index-manifest.schema.json`, `mcp-result.schema.json`).
- **Tổng số cờ không tương thích phát hiện:** **45 flags**.

### Phân loại cờ tương thích:
1. `anyof_null` (**34 cờ**): Các tham số kiểu `Optional[T]` hoặc `T | None` sinh ra cấu trúc `anyOf: [..., {"type": "null"}]`, dễ gây lỗi với một số LLM API (OpenAI/Anthropic tool calling) yêu cầu `nullable: true`.
2. `array_type` (**5 cờ**): Khai báo `type: ["string", "null"]` thay vì chuỗi đơn.
3. `property_missing_type` (**4 cờ**): Thuộc tính không có trường `type` hoặc `$ref` tường minh.
4. `defs_declared` (**1 cờ**) & `ref_used` (**1 cờ**): Dùng `$defs` và `$ref` trong schema kết quả (OpenAI Function Calling từ chối `$defs`).

---

## 7. Nghiệm thu M0

- [x] `git diff --stat src/` hoàn toàn rỗng.
- [x] Toàn bộ test suite chạy đạt 100%: `pytest -q` (95 passed, 4 skipped).
- [x] `stdio_smoke.py` chạy thành công (exit code 0).
- [x] `measure_context_cost.py` chạy thành công trên `token-context` và `synthetic-5k`.
- [x] `rank_eval.py` chạy thành công trên cả 2 bộ nhãn relevance.
- [x] `evals/bench_latency.py` chạy thành công trên cả 2 repo.
- [x] `evals/make_synthetic_repo.py` tạo và index thành công 5,051 file / 40,000 symbol.
- [x] `evals/edge_audit.py` chạy thành công trên cả 2 repo.
- [x] `evals/schema_compat.py` chạy thành công.
- [x] Toàn bộ dữ liệu baseline lưu đầy đủ trong `evals/out/m0/`.
