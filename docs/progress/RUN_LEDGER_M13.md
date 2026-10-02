# Run ledger — M13 (Java / C#: overload, override, tên nhiều từ)

Ngày: 2026-10-02. Agent: Claude Sonnet 5.5 (phiên Claude Code trên cloud). Yêu cầu của chủ repo: xử lý C#/Java, chạy benchmark nhẹ trong hai ngôn ngữ, cải thiện, tự commit và push. Không chạy benchmark tốn tiền (không C3, không agent), không đụng config/index thật của chủ repo, không dùng Opus.

## Mốc git

| Tag (local, không push) | Commit | Ý nghĩa |
|---|---|---|
| `m13-base` | `e745d52` (= `origin/main`, 0.3.1) | Mã cũ; cây `src/` trùng byte với `base031` dùng làm nhánh baseline (guard đã kiểm) |
| `m13-freeze` | `4ada9ee` (0.3.2) | Mã mới đóng băng trước khi đọc/đo bộ fresh |

## Bảng bước

| Bước | Trạng thái | Bằng chứng | Ghi chú |
|---|---|---|---|
| Chẩn đoán C#/Java | done | `evals/out/m13/dev_base/` | Cạnh mơ hồ ở CsvHelper 35 %, jsoup 38 %, Serilog 40 %; nguyên nhân: không có kiểu receiver, overload chọn theo tên, Java không có `package`, `#if` làm hỏng cây cú pháp |
| Cài đặt (resolver kiểu tĩnh, overload, kế thừa, package, `#if`, token tìm kiếm) | done | `tests/test_m13_jvm.py`, toàn bộ pytest pass | `PARSER_ARTIFACT_VERSION` 8, `RESOLVER_VERSION` 4, `FTS_BUILDER_VERSION` 3, version 0.3.2 |
| Bộ dev: CsvHelper, jsoup (mới), Serilog (đã "cháy" từ M12) | done | `evals/out/m13/dev_{base,new,base_regold}/` | jsoup do chính executor soạn → không độc lập. 3 nhãn gold jsoup sai đã sửa sau khi đọc mã nguồn; phía base được chạy lại với nhãn đã sửa |
| Cổng hồi quy Python/JS/TS | done | `cmp_bench.py`, so sánh JSON bỏ latency | `tc-pinned` loc A1final/A2, `edge_eval`, `rich`, `hono`, `fastify` (6 arm), edge gold và edge audit của hono/fastify: giống hệt giữa 0.3.1 và 0.3.2 |
| Đo bộ fresh gson (Java) và Newtonsoft.Json (C#) | done (một lần) | `evals/out/m13/fresh_{base,new}/` | Mỗi bộ 15 tác vụ + 12 call site; mã đóng băng `4ada9ee`; baseline = cây byte-identical `m13-base`. Edge gold chạy một lần; retrieval chạy một lần mỗi phía (một lần chạy base-Newtonsoft bị ngắt do timeout của công cụ trước khi ghi kết quả, chạy lại cùng lệnh, cùng mã) |
| Duyệt bộ fresh | partial | `evals/out/m13/review_log_*.md` | Tác giả: một phiên Sonnet độc lập; reviewer: một phiên Sonnet khác (đọc nguồn, không có công cụ truy xuất) duyệt **sau khi** edge gold đã đo, chỉ cho phần retrieval (cổng `reviewed:true` của `bench_retrieval.py`): 0/30 tác vụ bị sửa. Nhãn call site không được duyệt. Chưa có người duyệt |
| Tài liệu, commit, push | done | `CHANGELOG.md`, `docs/BENCHMARK.md` (M13), README (VI/EN) | Không push tag |

## Băm SHA-256 của bộ fresh

Như do tác giả viết (trước khi bất kỳ ai chạy công cụ trên chúng):

- `fresh_gson.json` `38988ba2cfe27c981a1a4b3d82713b7f814607f7f60af4111388df5badee4484`
- `fresh_newtonsoft.json` `bfddca8f84389ad1d52b03aebdee5f83025ccd6ff46df8460edba00c5e5db27b`
- `edge_gold_fresh_gson.json` `b3d9a721eac2f77e30aeb4924fb820c588fc84215d803f2d710de5cbb9ca8361`
- `edge_gold_fresh_newtonsoft.json` `a3102d2318eefed7425177f73870161bf0aa322ae7661c7bf4613b5e1fee7fc3`

Sau khi reviewer đặt `reviewed: true` và kéo dài `review_note` (nội dung tác vụ không đổi), file dùng cho phép đo retrieval là:

- `fresh_gson.json` `dee91d292ee5f717aa016f84c3c9ba2eb54381839047dfb96a526a0169190dc0`
- `fresh_newtonsoft.json` `90aa4ff8420d70862d69f13e1fd9d88b810442eacb6ba91026d38a402695f1f5`

(Hai file edge gold không đổi.)

## Những điều cần nói thẳng

- Bộ fresh nhỏ (15 tác vụ, 12 call site), một tác giả, chưa có người duyệt; khoảng tin cậy rộng. Chỉ `R1` Symbol Recall@10 có khoảng loại trừ 0 ở cả hai bộ.
- `bench_retrieval.py` ghi `freeze_tag` của M12 trong `summary.json` (cứng trong file được bảo vệ); guard thực tế dùng `TC_GUARD_MILESTONE=m13` → `m13-freeze`.
- Serilog đã được dùng làm held-out ở M12, giờ chỉ là tham khảo. jsoup là dev tự soạn.
- Heuristic "suspicious edges" của `edge_audit.py` dựa trên tên/receiver (thiết kế cho ngôn ngữ động) nên phạt cả cách phân giải theo kiểu; không dùng như độ chính xác.
- Thử và bỏ (không có lợi ích trên dev): giới hạn họ overload ("family cap") và gộp overload.
- Chưa làm: ràng buộc type parameter (`T extends Node`), field chain Java, constructor chaining, kiểu phần tử generic, kiểu tham số lambda, `await`; phương thức mở rộng trùng tên BCL khai báo trong repo (`Where`, `GetFields`) được giải về bản của repo.
- Không chạy C3/agent (tốn tiền); kết luận chỉ về chất lượng truy xuất và đồ thị gọi.
