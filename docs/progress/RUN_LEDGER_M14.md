# Run ledger — M14 (Trọng tài SCIP → Kiểu tĩnh → Override/Interface → Dispatch → MCP surface → Fresh 0.4.0)

Ngày bắt đầu: 2026-10-02.
Trọng tâm: Đồ thị cuộc gọi, quan hệ kế thừa/override/interface, dispatch qua mediator/broker cho C# và Java; sử dụng SCIP làm trọng tài khách quan và đo lường fresh nghiêm ngặt.

## Mốc git

| Tag (local, không push) | Commit | Ý nghĩa |
|---|---|---|
| `m14-base` | `45309db` (= `origin/main` @ v0.3.2) | Mã baseline trích xuất ra thư mục riêng biệt |
| `m14-freeze` | (chưa gán) | Mã đóng băng trước khi đo fresh một lần ở M14.7 |

## Nhật ký từng bước (Run Ledger)

| Thời gian (UTC) | Bước | Trạng thái | Commit | Bằng chứng | Ghi chú |
|---|---|---|---|---|---|
| 2026-10-02 04:52 | M14.0.1 | done | `45309db` | Môi trường venv `D:\AI\m14_venv`, Python 3.12.5, uv 0.11.26 | 579 passed, 9 skipped |
| 2026-10-02 05:27 | M14.0.2 | done | `45309db` | `evals/out/m14/dev_base/` | Khớp 100% từng tác vụ với M13: tc-pinned (loc A1, A2, edge_eval), rich, hono, fastify, csvhelper, jsoup, serilog, gson, newtonsoft |
| 2026-10-02 05:37 | M14.0.3 | done | `d2e5015` | `evals/bench_retrieval.py`, `evals/guard.py` | Sửa freeze_tag theo `guard.FREEZE_TAG`, thêm edge_oracle_eval & dispatch_eval vào PROTECTED_PATHS |
| 2026-10-02 05:40 | M14.0.4 | done | `ba5e1bb` | 4 repo dev dispatch đã clone và xác minh | CleanArchitecture (C# MediatR, MIT, 110 files), Sample-Outbox (C# MassTransit, MIT, 26 files), spring-amqp-samples (Java RabbitMQ, Apache-2.0, 45 files), spring-kafka (Java Kafka, Apache-2.0, 630 files) |
| 2026-10-02 05:42 | M14.0.6 | done | `804f453` | `.github/workflows/scip-oracle.yml`, `evals/oracle/targets.json`, `evals/scip_export.py` | Workflow push lên origin/m14 để chạy SCIP indexing |
| 2026-10-02 05:43 | M14.0.5 | waiting-review | – | Phụ lục C & D | Chờ 2 phiên độc lập (soạn và duyệt) tạo bộ fresh & nhãn dispatch cho eShop và eventmesh |

## Bảng thông tin Repo Dev Dispatch (M14.0.4)

| Repo | Vai trò | Framework | URL | Commit | License | Số file mã nguồn |
|---|---|---|---|---|---|---|
| `CleanArchitecture` | C# Dev Dispatch | MediatR | `https://github.com/jasontaylordev/CleanArchitecture.git` | `5353a9edae000d576eade1a4f2c0d72d3b1c1785` | MIT | 110 (.cs) |
| `Sample-Outbox` | C# Dev Dispatch | MassTransit | `https://github.com/MassTransit/Sample-Outbox.git` | `1ab8e66ebf96e5733e68c2f4d2201276f38ed9c5` | MIT | 26 (.cs) |
| `spring-amqp-samples` | Java Dev Dispatch | RabbitMQ / Spring AMQP | `https://github.com/spring-projects/spring-amqp-samples.git` | `eee2e80577d2e22415ace5ad6a69dfd0ec2e6789` | Apache-2.0 | 45 (.java) |
| `spring-kafka` | Java Dev Dispatch | Kafka / Spring Kafka | `https://github.com/spring-projects/spring-kafka.git` | `bc143ec84943c0acdcdbd67d4ecddf7431b4d7bc` | Apache-2.0 | 630 (.java) |

## SHA-256 các tệp kiểm tra fresh (Luật 11)
(Sẽ ghi nhận ngay khi phiên soạn & duyệt độc lập hoàn tất trước m14-freeze)
