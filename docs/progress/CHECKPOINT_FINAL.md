# CHECKPOINT_FINAL — việc của chủ repo (bản nháp, hoàn thiện ở cuối lần chạy)

## Duyệt tập tác vụ M10 (làm song song bất cứ lúc nào)

- File cần duyệt (bản sao, **sửa trực tiếp file này**, không sửa file trong repo):
  `D:\AI\token-context-mcp\tmp\run\tmp\review\bench_rich.json`
- Nội dung: 30 tác vụ định vị + 10 tác vụ packet trên `Textualize/rich` tag `v15.0.0` (commit
  `6ac483cbea39cab124dfd3483bba70ffafb71050`, MIT). Toàn bộ là tập test, không chia dev/held-out.
- Cách duyệt: kiểm từng `gold_files` / `gold_symbols` / `gold_context` có đúng không; nhóm `b_hidden_dep` không lộ tên đích.
  Xong thì đặt `"reviewed": true` và ghi `review_note`. Người duyệt: chủ repo, hoặc một phiên Claude **khác** phiên đã soạn (D3).
- Bằng chứng agent đã kiểm: `evals/out/m10/bench_rich_gold_verification.json` (mọi gold có mặt trong index và trả về thân hàm).
- Lệnh chạy benchmark sau khi duyệt sẽ được điền ở cuối lần chạy.
