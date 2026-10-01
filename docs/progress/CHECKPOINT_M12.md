# Checkpoint M12 (viết lại sau phiên rà soát 2026-10-01)

Bản checkpoint trước do agent đầu tiên viết khi mới xong phần hạ tầng và ghi "HOÀN THÀNH TOÀN BỘ", điều đó không đúng: chưa có bộ held-out nào được soạn hay đo. Bản này thay thế nó.

**Nhánh:** `m12-fix` (đã merge vào `main` cục bộ; chưa push). **Phiên bản:** 0.3.1. **Tag cục bộ:** `m12-base` (`70d8e8f`), `m12-freeze` (`7172665`, code 0.3.0 đã đo held-out). Không tag nào được publish.
**Số liệu và bảng đầy đủ:** `docs/BENCHMARK.md` mục "M12 — held-out evaluation of 0.3.0 and the 0.3.1 follow-up". **Bằng chứng thô:** `evals/out/m12/`.

## 1. Trạng thái

| Hạng mục | Trạng thái | Ghi chú |
| --- | --- | --- |
| M12.1 JS assigned methods | xong, có lỗi hồi quy đã sửa ở 0.3.1 | 0.3.0 mất method trong object literal truyền làm đối số; 0.3.1 sửa + gán chuỗi |
| M12.2 C# ranking | xong | Symbol Recall@10 serilog 0,43 → 0,64; **File Acc@5 không tăng** |
| M12.3 giảm cạnh mơ hồ | xong | JS 64 → 43 %, C# 69 → 40 %, TS 65 → 56 % cạnh mơ hồ |
| M12.4 chẩn đoán Python | xong | Python giữ nguyên từng byte |
| M12.5 C3 v2 harness | xong, đã sửa lỗi | sửa đếm token, thêm `--mcp-optional`, `--effort`; chỉ Claude Code được chạy |
| M12.6 đo held-out | xong (retrieval) | 4 repo, mỗi bộ một lần; 4/10 mục tiêu đạt |
| C3 end-to-end | **dở dang, chưa kiểm định** | chỉ seed 1 (60/120 lượt) trên held-out; seed 2, suite dev, Gemini, Codex **không chạy** (chi phí) |
| Người duyệt bộ tác vụ held-out | **chưa** | các bộ do phiên độc lập soạn và duyệt |

## 2. Kết quả chính (held-out, code 0.3.0)

- **Tốt lên:** JavaScript (File Acc@5 0,80 → 0,93; packet ref. coverage 0,00 → 0,39), C# symbol (0,43 → 0,64) và recall cạnh (5/17 → 13/17, đúng 11/11 ở ≥ 0,6).
- **Không đổi hoặc yếu:** Python giữ nguyên; TypeScript chỉ nhích (Symbol Recall@10 +0,04; đồ thị gọi vẫn mơ hồ 56 %, 0 cạnh ≥ 0,6 trong mẫu gold); C# File Acc@5 0,73 → 0,70 và câu hỏi hành vi không có tên chỉ 0,40.
- **Mục tiêu không đạt:** K1 (0,933; đã sửa ở 0.3.1, 90/90), K3, K4, K6 (zod 0,85), K7 (zod +0,08), K10 (+25 đến +27 % ở 2/12 truy vấn).
- **C3 seed 1 (Sonnet 5.5, medium):** thành công 100 % ở cả ba arm (hiệu ứng trần); B1 không gọi MCP lần nào; B2 ít hơn 20 % tổng token (chủ yếu là đọc cache) nhưng cùng chi phí tính phí. Không suy ra được gì về tác vụ khó hơn.

## 3. Việc còn lại cho chủ repo (không có việc nào chạy tự động)

1. **Cập nhật máy thật** (không động vào cấu hình/index thật cho tới khi bạn làm):
   ```powershell
   Set-Location D:\AI\token-context-mcp
   git fetch; git checkout main; git pull      # sau khi bạn nhận nhánh đã merge
   uv sync --all-extras
   uv run token-context index --all            # bắt buộc: parser 7, FTS 2, resolver 3
   ```
   Khởi động lại client MCP (Codex, Claude Code/Desktop, Antigravity); cấu hình client không đổi.
2. **Push và tag** (chưa làm, theo ràng buộc): `git push origin main`; tag `v0.3.1` chỉ khi bạn quyết định.
3. **Chạy C3 khi có ngân sách** (ước tính theo số đo seed 1: mỗi 60 lượt ≈ 4,6M token tổng, ≈ US$3 giá API tương đương, ≈ 12 phút):
   ```powershell
   # seed 2 trên held-out (cần các clone held-out, index 0.3.0 hoặc 0.3.1, và `claude` đã đăng nhập)
   uv run python evals/run_c3_matrix.py --agent claude --suite locate_v2 --manifest evals/c3/locate_v2_manifest.json `
     --run-config <run_held.json> --seeds 2 --only-repo starlette --runs-dir <dir>\runs `
     --usage-output <dir>\usage_starlette_seed2.jsonl --failure-output <dir>\fail_starlette_seed2.json
   # lặp cho zod, express, serilog; sau đó:
   uv run python evals/c3_report.py --runs-file <gộp seed 1 + seed 2> --manifest evals/c3/locate_v2_manifest.json
   ```
   Mẫu `run_held.json` / `mcp_held.json` nằm ở `evals/out/m12/c3_heldout_seed1/` (đường dẫn trong đó là của container, cần sửa). Tùy chọn: suite dev `evals/c3/locate_v2_dev_manifest.json` (≈ 4,6M token/seed), mô hình yếu hơn (Haiku 4.5), Gemini CLI, Codex.
4. **Đo lại held-out cho 0.3.1** chỉ nên làm nếu chấp nhận rằng bộ held-out đã bị "đốt" (Luật 18): kết quả sẽ là thăm dò, không phải held-out; tốt hơn là soạn bộ held-out mới.
5. **Người duyệt** bộ tác vụ held-out (`evals/tasks/heldout_*.json`, `evals/tasks/edge_gold_heldout_*.json`) và nhãn hono đã sửa.

## 4. Hướng xử lý tương lai (nhẹ)

- Tìm nguyên nhân fastify `R2` Symbol Recall@10 giảm (0,69 → 0,60): symbol mới từ method gán chen vào top 10; thử trọng số xếp hạng riêng cho symbol gán.
- Xếp hạng C# theo thân hàm cho câu hỏi hành vi (file accuracy chưa tăng); xem `b_hidden_dep` 0,40 (held-out) và 0,10 (dev).
- Suy luận kiểu receiver cho JS/TS (cạnh còn mơ hồ 43 đến 56 %); đây là giới hạn trần của packet.
- Đo lại độ trễ `search_source`/`get_symbol_context` (hai truy vấn chậm hơn 25 đến 27 %), sửa `bench_latency.py` để dùng truy vấn cố định.
- Vá kẽ hở guard (baseline qua `PYTHONPATH` không cần cờ `--allow-baseline-code`).
- C3 khó hơn (tác vụ có nhiều file, repo ít nổi tiếng hơn để tránh nhớ sẵn), nhiều seed hơn, và chế độ hybrid khiến agent thực sự dùng MCP (B1 hiện 0/20).
- Soạn bộ held-out mới cho vòng sau, có người duyệt.
