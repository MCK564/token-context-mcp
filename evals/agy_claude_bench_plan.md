# Kế hoạch Chạy Tiếp cho Claude Sonnet 5.5 & Arm A2 (10 Core Tools) trên Antigravity

> Tài liệu này giữ nguyên kịch bản đối chiếu chéo cho **Claude Sonnet 5.5 (Medium)**, **Orchestrator (Neon)** và **Arm A2 (`enable_extensions = false` — chỉ 10 tool lõi)** khi bạn gia hạn xong gói Claude, sử dụng **cùng bộ 5 prompt P1–P5** trong [`evals/agy_prompt_pack.json`](agy_prompt_pack.json) để so sánh công bằng trực tiếp với kết quả Gemini (`flash` & `pro`) đã chạy.

---

## 1. Bộ câu hỏi & Bảng Arm mở rộng

Giữ nguyên 100% nội dung `P1..P5` và `brevity_suffix` trong `evals/agy_prompt_pack.json` (không sửa đề bài để đảm bảo so sánh trực tiếp cùng một nhiệm vụ).

| Arm | Cấu hình MCP (`repos.toml`) | Cách gửi Prompt | Mục tiêu đo thêm |
| :--- | :--- | :--- | :--- |
| **A0** | Tắt `token-context` MCP | Nhắn thường P1 → P5 | Baseline không MCP trên Claude 5.5 |
| **A1** | Bật `token-context` (`enable_extensions = true`) | Nhắn thường P1 → P5 (không bọc `sample_prompt.md`) | Đo tỷ lệ tự gọi MCP của Claude 5.5 khi không ép prompt |
| **A2** *(mới)* | Bật `token-context` với **`enable_extensions = false`** (chỉ 10 tool lõi, `[ledger].enabled = true`) | P1 bọc mẫu 3.2; P2–P5 bọc mẫu 3.3 | Tách riêng lợi ích khi bỏ bớt schema của 11 tool mở rộng |
| **A3** | Bật `token-context` với `enable_extensions = true` (reset `ledger.sqlite` & `memory.sqlite` trước khi chạy) | P1 bọc mẫu 3.2; P2–P5 bọc mẫu 3.3 | Đo chi phí & hiệu quả đầy đủ của Lá Phổi (`trajectory_record`) + `memory_*` trên Claude 5.5 |

---

## 2. Quy trình thực hiện (Tiết kiệm Quota tối đa)

1. **Vệ sinh trạng thái trước khi chạy:**
   - Kiểm tra index `fresh`:
     ```powershell
     & "D:\AI\token-context-mcp\.venv\Scripts\python.exe" -m token_context_mcp index --repo-id token-context
     ```
   - Đảm bảo sổ `ledger.sqlite` sạch thẻ test cũ trước A3:
     ```powershell
     & "D:\AI\token-context-mcp\.venv\Scripts\python.exe" -m token_context_mcp ledger list --repo-id token-context
     # Nếu còn card test cũ, xóa bằng: ... ledger forget <card_id>
     ```
2. **Đặt model trên Antigravity:**
   - Chọn **`Claude Sonnet 5.5 (Medium)`** *(tránh `High` hoặc `Opus` nếu muốn giữ chi phí thấp — Sonnet High từng ghi nhận verbosity cao trong benchmark)*.
   - Nếu chạy thêm **`Orchestrator (Neon)`**, có thể chạy 3 Arm cốt lõi (**A0, A1, A3**) giống đợt đầu.
3. **Chạy từng Arm trong 1 New Conversation riêng:**
   - Đặt tên rõ ràng, ví dụ: `[BENCH][Claude-Sonnet-5.5-Med][A0]`, `[A1]`, `[A2]`, `[A3]`.
   - Khi chuyển sang **A2** (`enable_extensions = false`): chỉnh `enable_extensions = false` trong `%APPDATA%\token-context-mcp\repos.toml` (hoặc tắt flag `--enable-extensions` ở cấu hình MCP client), restart/reload kết nối MCP rồi mới mở New Conversation cho A2. Xong A2 thì bật lại `enable_extensions = true` trước khi chạy A3.
   - Ghi lại `conversation_id` của từng cuộc hội thoại (xem trong `C:\Users\KHA\.gemini\antigravity\brain\`) và số card ghi vào `ledger.sqlite` sau A3.

---

## 3. Cập nhật vào Manifest & Xuất Báo cáo Tổng hợp

Mở [`evals/reports/agy_bench_manifest.json`](reports/agy_bench_manifest.json) và thêm các object mới vào mảng `"runs"`:

```json
{
  "run_id": "claude_sonnet_med_a0",
  "model_tier": "claude-sonnet-5.5-medium",
  "arm": "A0",
  "arm_label": "No MCP (Plain)",
  "conversation_id": "<CONVERSATION_ID_A0>",
  "cache_discount_factor": 0.10,
  "ledger_cards_created": 0,
  "notes": "Claude Sonnet 5.5 Medium, MCP disabled"
}
```

> Lưu ý hệ số chiết khấu cache (`cache_discount_factor`):
> - **Gemini 4 (`flash` / `pro` / `Hydrogen` / `Neon`)**: `0.05` (giảm 95% input cache).
> - **Claude 5.5 (`Sonnet` / `Opus`)**: `0.10` (giảm 90% input cache).

Chạy lại script phân tích (0 tốn token LLM):

```powershell
& "D:\AI\token-context-mcp\.venv\Scripts\python.exe" D:\AI\token-context-mcp\evals\analyze_agy_transcripts.py
```

Kết quả đối chiếu đầy đủ giữa **Gemini 4** và **Claude 5.5** sẽ tự động cập nhật ra [`evals/reports/agy_prompt_bench_report.md`](reports/agy_prompt_bench_report.md) và [`evals/reports/agy_prompt_bench_report.json`](reports/agy_prompt_bench_report.json).
