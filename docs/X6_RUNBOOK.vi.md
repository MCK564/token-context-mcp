# X6 — Runbook chạy ma trận C3

**Bản EN:** `X6_RUNBOOK.en.md` · **Giao thức đã chốt:** `evals/c3_protocol.md` (không được sửa sau khi bắt đầu chạy)

45 lượt = 5 task × 3 seed × 3 nhánh. Ước tính 2–2,5 giờ thực tế.

Runbook này giả định đã cài xong theo `SETUP.vi.md` và Codex CLI đã có trên PATH.

---

## 0. Ba khoảng trống vận hành phải biết trước

Đọc mã `run_c3_matrix.py` cho thấy ba điểm mà quy trình chạy phải bù, không phải lỗi nhưng sẽ hỏng việc nếu bỏ qua:

**1. `--task-success` là một cờ duy nhất cho cả 45 lượt.** Nhưng giao thức yêu cầu chấm từng câu trả lời. Không thể chấm 45 lượt bằng một giá trị. → Bắt buộc chạy **hai pha**: pha 1 ghi usage với giá trị tạm, pha 2 chấm rồi sửa lại từng dòng.

**2. Không có khả năng resume.** Nếu lượt thứ 30 hỏng, chạy lại từ đầu sẽ **nối thêm bản ghi trùng** vào cùng file `--usage-output`. → Chạy theo lô từng task, mỗi task một file usage riêng.

**3. Câu trả lời của agent nằm trong session log, chưa có bước trích ra.** Muốn chấm thì phải lấy `agent_message` cuối cùng từ mỗi file `{arm}-{task}-seed{n}.jsonl`. → Mục 4 có sẵn lệnh trích.

---

## 1. Tiền kiểm — làm hết trước khi tốn token

```powershell
cd D:\AI\token-context-mcp

# 1.1 Bộ test phải xanh
uv run pytest

# 1.2 Index của repo mục tiêu phải fresh
uv run python -m token_context_mcp status --repo-id invoice-scanner
```

Trong kết quả `status`, bắt buộc:

- `freshness` phải là `fresh`. Nếu `stale` thì chạy lại `index` — **một lượt benchmark trên index cũ là dữ liệu bỏ đi**.
- `pending_path_count` phải là `0`.

```powershell
# 1.3 Codex thấy được server
codex mcp list

# 1.4 Liệt kê 45 lệnh mà không chạy
uv run python evals/run_c3_matrix.py --dry-run --task-success true
```

Dry-run phải in đúng **45 dòng**. Kiểm tra bằng mắt một dòng B0 và một dòng B1: dòng B0 phải có `-c mcp_servers.token-context.enabled=false`, dòng B1 thì không.

```powershell
# 1.5 Một lượt thử duy nhất, để bắt lỗi môi trường sớm
uv run python evals/run_c3_matrix.py --task-success true `
  --seeds 1 --arms B1 `
  --runs-dir evals/runs/x6-smoke `
  --usage-output evals/reports/x6-smoke.jsonl
```

Lượt này chạy 5 task × 1 seed × 1 nhánh = 5 lượt. Nếu treo quá 3 phút không ra JSONL thì **dừng lại** — đó đúng là lỗi đã gặp ở lần thử trước (Codex lồng trong Codex không trả JSONL). Chạy runbook này từ **terminal thường**, không chạy bên trong một phiên agent khác.

---

## 2. Pha 1 — chạy theo lô, từng task một

Chạy từng task riêng để một lỗi giữa chừng chỉ mất 9 lượt thay vì 45:

```powershell
$tasks = @("T1-orient","T2-locate","T3-impact","T4-surface","T5-trace")
foreach ($t in $tasks) {
  uv run python evals/run_c3_matrix.py `
    --task-success true `
    --seeds 1 2 3 `
    --arms B0 B1 B2 `
    --runs-dir      evals/runs/x6/$t `
    --usage-output  evals/reports/x6-$t.jsonl `
    --failure-output evals/reports/x6-$t-failures.json
}
```

`--task-success true` ở đây là **giá trị tạm**. Nó chỉ để pha 1 ghi được usage; pha 3 sẽ sửa lại theo kết quả chấm. Đừng dùng file này cho `benchmark-report` trước khi chấm.

Sau mỗi lô, kiểm tra ngay:

```powershell
Get-Content evals/reports/x6-T1-orient.jsonl | Measure-Object -Line   # phải là 9
Get-Content evals/reports/x6-T1-orient-failures.json                  # phải là []
```

Nếu file failures không rỗng: đọc `evals/runs/x6/<task>/<arm>-<task>-seed<n>.stderr.log`. Lượt hỏng vì lỗi MCP hoặc vi phạm giao thức **không được ghi vào kết quả** — runner đã fail-fast đúng, đừng lách.

---

## 3. Chấm chất lượng — trước khi nhìn số token

Đây là ràng buộc quan trọng nhất của cả X6. Chấm **trước**, xem chi phí **sau**. Chấm sau khi đã thấy chi phí là cách người ta tự lừa mình.

Trích câu trả lời cuối của từng lượt:

```powershell
uv run python -c @'
import json, pathlib
for p in sorted(pathlib.Path("evals/runs/x6").rglob("*.jsonl")):
    last = None
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except Exception:
            continue
        it = ev.get("item") or {}
        if ev.get("type") == "item.completed" and (it.get("item_type") or it.get("type")) == "agent_message":
            last = it.get("text") or it.get("content")
    out = p.with_suffix(".answer.md")
    out.write_text(last or "(no agent_message found)", encoding="utf-8")
    print(f"{p.name:34s} -> {out.name}  ({len(last or '')} chars)")
'@
```

Chấm từng file `.answer.md` theo bảng trong `evals/c3_protocol.md` §"Predeclared quality grader". Ghi kết quả vào một file phẳng:

```
evals/reports/x6-grades.csv
arm,task_id,seed,task_success,note
B0,T1-orient,1,true,
B1,T1-orient,1,false,"bịa module invoice_frontend_ml"
...
```

T1 chấm bán tự động được — dùng chính tập nhãn:

```powershell
uv run python evals/rank_eval.py --set evals/relevance/orientation_invoice_scanner.json --budget 4096
```

rồi đối chiếu các symbol mà báo cáo T1 nêu ra với `essential_recall ≥ 0.833` và `noise = 0`.

Bốn task còn lại chấm tay theo tiêu chí đã viết sẵn. Không thêm tiêu chí mới ở bước này.

---

## 4. Pha 2 — áp điểm chấm vào bản ghi usage

```powershell
uv run python -c @'
import csv, json, pathlib

grades = {}
with open("evals/reports/x6-grades.csv", newline="", encoding="utf-8") as fh:
    for row in csv.DictReader(fh):
        grades[(row["arm"], row["task_id"], int(row["seed"]))] = row["task_success"].strip().lower() == "true"

merged, missing = [], []
for p in sorted(pathlib.Path("evals/reports").glob("x6-T*.jsonl")):
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        key = (rec["arm"], rec["task_id"], int(rec["seed"]))
        if key not in grades:
            missing.append(key)
            continue
        rec["task_success"] = grades[key]
        merged.append(rec)

if missing:
    raise SystemExit(f"chua cham {len(missing)} luot: {missing[:5]}")

out = pathlib.Path("evals/reports/x6-graded.jsonl")
out.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in merged), encoding="utf-8")
print(f"{len(merged)} ban ghi -> {out}")
'@
```

Script này **từ chối chạy** nếu còn lượt chưa chấm. Đó là cố ý.

---

## 5. Pha 3 — tổng hợp

```powershell
uv run python -m token_context_mcp benchmark-report `
  --input  evals/reports/x6-graded.jsonl `
  --output evals/reports/x6-summary.json
```

Đọc kết quả theo đúng thứ tự ưu tiên đã chốt ở X4:

| Trường | Vai trò |
|---|---|
| `median_paired_retrieved_content_reduction` | **chính** |
| `paired_retrieved_content_reduction_ci95` | khoảng tin cậy của chỉ số chính |
| `median_uncached_input_tokens` | chi phí cận biên thật |
| `quality_noninferiority_delta` | cổng chất lượng — âm nghĩa là nhánh đó làm hỏng tác vụ |
| `median_paired_token_reduction` | **phụ**, bị chi phối bởi số lượt hội thoại |

---

## 6. Nghiệm thu

Lượt chạy X6 chỉ được coi là hợp lệ khi **tất cả** các điều sau đúng:

- `paired_count` bằng 15 cho mỗi nhánh (5 task × 3 seed), hoặc chênh lệch được giải thích bằng danh sách failure.
- Không bản ghi nào có `mcp_errors` khác rỗng hoặc `mcp_health: failed`.
- Mọi `prompt_sha256` khớp nhau trong từng bộ ba B0/B1/B2 — `benchmark-report` sẽ ném lỗi nếu không, đừng bỏ qua lỗi đó.
- Điểm chất lượng được chấm **trước** khi mở `x6-summary.json`.
- Báo cáo cuối nêu **rõ ràng** chỉ số chính là `retrieved_content_estimated_tokens`, kèm CI95 và cỡ mẫu.

---

## 7. Diễn giải kết quả một cách trung thực

Ba tình huống, và cách đọc đúng từng cái:

**B2 giảm nội dung truy xuất, chất lượng không thua** → đây là khẳng định mạnh nhất mà bộ dữ liệu này chống đỡ được: *giao thức MCP-first có giới hạn truy xuất ít ngữ cảnh hơn cho cùng chất lượng câu trả lời.* Vẫn phải nói rõ: một repository, một model, năm task.

**B1 không giảm hoặc tăng** → khớp với những gì đã đo trước đó: trong workflow hybrid, MCP mang tính **cộng thêm** chứ không thay thế. Đây không phải thất bại của công cụ, mà là kết quả về **hành vi agent**. Báo cáo đúng như vậy.

**Chất lượng B2 tụt** → giao thức có giới hạn đang cắt mất thứ agent cần. Kiểm `truncated`, `omitted_count`, `node_limit_reached` trong session log **trước khi** kết luận là lỗi ranking.

Điều **không** được viết trong bất kỳ trường hợp nào: một con số phần trăm tiết kiệm mà không kèm cỡ mẫu và CI95, hoặc một khẳng định tổng quát rút ra từ một repository.

---

## 8. Nếu phải dừng giữa chừng

Kết quả theo lô nên việc dừng là an toàn. Chạy lại **chỉ** task còn thiếu:

```powershell
uv run python evals/run_c3_matrix.py --task-success true `
  --seeds 1 2 3 --arms B0 B1 B2 `
  --runs-dir evals/runs/x6/T4-surface `
  --usage-output evals/reports/x6-T4-surface.jsonl
```

**Xóa file usage của task đó trước khi chạy lại.** Runner nối thêm chứ không ghi đè, nên chạy lại mà không xóa sẽ tạo bản ghi trùng và `paired_count` sẽ sai.

Session log dưới `evals/runs/` đã được gitignore — chúng chứa thân mã của repository được index cùng đường dẫn cục bộ và tên người dùng. Đừng commit chúng.
