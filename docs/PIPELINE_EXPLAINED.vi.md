# token-context-mcp — Mã nguồn, Config, Pipeline, Kinh tế token, SWOT

**Viết:** 27/08/2026 · **Đối chiếu:** phiên bản 0.1.0, 2083 dòng trên 27 module trong `src/token_context_mcp/`
**Phương pháp:** kiến trúc đọc từ mã nguồn; **mọi con số ở §4 đều do tôi chạy thật** service trên máy này với hai repository đã đăng ký.

---

## 1. Gói này là gì

Một **MCP server `stdio` cục bộ, chỉ đọc**, index các repository được đăng ký tường minh vào một snapshot SQLite và trả lời sáu công cụ truy xuất bằng những gói ngữ cảnh nhỏ, có băm nguồn kèm theo.

Tiền đề thiết kế mang tính phủ định và được nói thẳng trong README: *giảm việc bò quét toàn repository mà không giả vờ rằng phân tích cú pháp là một mô hình ngữ nghĩa đầy đủ.* Gần như mọi quyết định thiết kế đều bắt nguồn từ việc coi giới hạn đó là nghiêm túc.

Các mục tiêu bị loại trừ, cưỡng chế ngay trong code: không sửa file, không chạy lệnh shell, không lắng nghe HTTP, không gọi API mạng, không nhận đường dẫn tùy ý.

---

## 2. Các module

### 2.1 Nền tảng

| Module | Dòng | Vai trò |
|---|---|---|
| `constants.py` | 24 | Giới hạn và danh sách chặn. `SUPPORTED_EXTENSIONS` ánh xạ 6 đuôi file sang 4 grammar; `HARD_DENY_DIRECTORIES` chặn `.git`, `.ssh`, `.aws`, `.gnupg`, `node_modules`, `.venv`, `site-packages`, các cache; `HARD_DENY_FILE_NAMES` và `HARD_DENY_SUFFIXES` chặn `id_rsa`, `credentials.json`, `.pem`, `.key`, `.p12`, `.kdbx` |
| `models.py` | 94 | Sáu dataclass đóng băng — `RepositoryConfig`, `ServerConfig`, `AppConfig`, `FileRecord`, `SymbolRecord`, `EdgeRecord`, cộng `Evidence`. Đóng băng toàn bộ: một bản ghi snapshot không thể bị sửa sau khi đọc ra |
| `config.py` | 139 | Nạp/ghi registry TOML, kiểm `repo_id` theo `^[a-z][a-z0-9_-]{0,63}$`, và **kiểm biên mọi giới hạn server** ngay lúc nạp |

`default_config_path()` đáng nhắc riêng. Nó phân giải theo thứ tự `TOKEN_CONTEXT_CONFIG` → `%APPDATA%` (Windows) → `$XDG_CONFIG_HOME` → `~/.config`, và docstring nói rõ lý do: *"mặc định không được phụ thuộc thư mục làm việc của tiến trình vì Codex khởi động một tiến trình MCP từ rất nhiều repository khác nhau."* Một registry toàn cục cho mỗi người dùng, một cách có chủ ý.

### 2.2 Bảo mật

| Module | Dòng | Vai trò |
|---|---|---|
| `security/path_policy.py` | 67 | Giam giữ đường dẫn. `canonical_repository_root` phân giải nghiêm ngặt và từ chối symlink/reparse point. `safe_relative_path` loại bỏ byte NUL, đường dẫn tuyệt đối, ký tự ổ đĩa, tiền tố UNC và mọi đoạn `.`/`..`, rồi phân giải và kiểm lại `relative_to(root)`, sau đó duyệt **từng thành phần đường dẫn** để tìm reparse point |
| `security/content_policy.py` | 39 | `is_hard_denied` trên đường dẫn tương đối; `redact_text` thay cả dòng khớp regex gán bí mật hoặc header PEM bằng `[REDACTED: potential secret]` và trả về số lượng; `is_probably_binary` tìm NUL trong 8 KB đầu |

Phép kiểm reparse point là đặc thù Windows và **đúng**: `os.lstat(path).st_file_attributes & 0x400` bắt được junction mà `is_symlink()` bỏ sót.

### 2.3 Index

| Module | Dòng | Vai trò |
|---|---|---|
| `index/hashing.py` | 17 | SHA-256 trên bytes và trên file theo khối 1 MB |
| `index/freshness.py` | 22 | `pending_paths` băm lại các file đã index so với đĩa. Docstring nêu rõ đánh đổi: *"phát hiện thay đổi nguồn mà không cần watcher thường trú hay ghi xuống hệ thống file"* |
| `index/sqlite_store.py` | 291 | Schema và truy cập. Năm bảng — `metadata`, `files`, `symbols`, `edges`, `imports` — với index trên `symbols(path)`, `symbols(name)`, `edges(source_symbol_id)`, `edges(target_symbol_id)`. Kết nối đọc dùng `file:…?mode=ro` |
| `index/runner.py` | 215 | Pipeline index (§3) |

### 2.4 Phân tích cú pháp

| Module | Dòng | Vai trò |
|---|---|---|
| `parse/treesitter.py` | 200 | Duyệt Tree-sitter. `_NODE_KINDS` ánh xạ loại node của grammar sang loại symbol theo từng ngôn ngữ. Trích chữ ký (byte bắt đầu → byte bắt đầu thân), khoảng dòng và byte, `is_private` từ dấu gạch dưới đầu tên. `symbol_id` = `{language}:{path}:{qualified_name}:{sha256[:16]}` |
| `parse/lexical_edges.py` | 65 | Cạnh theo khớp định danh. Với mỗi thân symbol, mọi định danh được tra trong chỉ mục tên; **đúng một** kết quả → `resolved` ở confidence 0.55; nhiều kết quả → `ambiguous` ở 0.2; `edge_kind` là `call` nếu ngay sau đó là `(`, ngược lại là `reference`. Giới hạn 100 cạnh mỗi symbol, rồi khử trùng lặp |
| `parse/lsp.py`, `parse/scip.py` | 28 + 27 | **Stub có chủ ý.** Cả hai trả về `enabled: False` kèm lý do. Không cái nào sinh tiến trình con |

Các stub này là một **tuyên bố thiết kế**, không phải một khoảng trống: language server là một phụ thuộc thực thi được, phải được ghim phiên bản, đưa vào sandbox và kiểm định trước khi được phép thêm cạnh ngữ nghĩa. Gói này khai báo ranh giới thay vì lặng lẽ bước qua nó.

### 2.5 Truy xuất

| Module | Dòng | Vai trò |
|---|---|---|
| `retrieve/token_budget.py` | 33 | `estimate_tokens` = `ceil(utf8_bytes / 4)`, có version `utf8-bytes-div-4-v1`. `pack_by_budget` lấp tham lam tới hạn mức và trả về `(chosen, omitted, used)` |
| `retrieve/ranking.py` | 25 | Điểm = `1.0 + 2.0·bậc_vào + 0.5·bậc_ra + 8.0·(mỗi từ khóa truy vấn khớp) + 0.25·(class hoặc interface)` |
| `retrieve/service.py` | 416 | Sáu công cụ, phép duyệt đồ thị, và phong bì phản hồi |
| `server.py` | 135 | Đăng ký công cụ MCP. `_invoke` bắt mọi thứ và trả về lỗi chung chung — không stack trace, không lộ đường dẫn |

---

## 3. Pipeline, từng phase một

```
  register ──> [P1 kiểm kê] ──> [P2 parse] ──> [P3 cạnh] ──> [P4 snapshot]
                                                                   │
   gọi công cụ MCP <── [P7 phong bì] <── [P6 ngân sách] <── [P5 truy xuất]┘
```

### P0 — Đăng ký (`config.register_repository`)

Một quyết định allowlist cục bộ, tường minh. `repo_id` được kiểm theo regex; `root` được chuẩn hóa và bị từ chối nếu không tồn tại, không phải thư mục, hoặc là reparse point. **Đăng ký lại một `repo_id` đã có sẽ ném lỗi** thay vì lặng lẽ trỏ tên cũ sang root mới — một lựa chọn khác thường và đúng đắn, vì một lần trỏ lại âm thầm sẽ chuyển hướng mọi lời gọi công cụ về sau.

Ghi nguyên tử: dựng toàn bộ TOML trong bộ nhớ → ghi `repos.toml.tmp` → `replace()`.

### P1 — Kiểm kê (`runner._inventory`)

`os.walk(topdown=True, followlinks=False)`, cắt tỉa `directories[:]` tại chỗ để các cây con bị chặn không bao giờ được đi vào. Ba bộ lọc, áp dụng cho cả thư mục lẫn file: reparse point, danh sách chặn cứng, và chính `.gitignore` của repository (qua `pathspec.GitIgnoreSpec`). Vượt `max_files` thì **ném lỗi** chứ không cắt bớt trong im lặng.

Kết quả được sắp xếp, khiến snapshot mang tính tất định với một cây file cố định.

### P2 — Parse (`runner.build_index` + `treesitter.parse_source`)

Với mỗi file: đọc bytes → bỏ qua nếu vượt `max_file_bytes` hoặc là nhị phân → ghi `FileRecord` kèm SHA-256 → parse nếu đuôi file được hỗ trợ.

**Nhánh tăng dần mới là phần quan trọng.** Trước khi parse, runner mở snapshot *trước đó* ở chế độ chỉ đọc và tái sử dụng kết quả parse khi `previous.sha256 == current.sha256` và trạng thái cũ bắt đầu bằng `parsed` — chép symbol và import thẳng từ database cũ. Manifest sau đó báo `files_reused` và `files_reparsed` **tách bạch**, nên việc tái sử dụng có thể kiểm toán được chứ không phải chỉ được giả định.

Lỗi parse được khoanh vùng: file vẫn được giữ với `parse_status: "parse_error"` kèm cảnh báo, không bao giờ bị bỏ đi lặng lẽ. Một cây có node lỗi vẫn cho ra symbol, gắn cờ `parsed_with_warnings`.

### P3 — Dựng cạnh (`build_lexical_edges`)

Chạy một lần trên toàn bộ symbol **sau khi** mọi file đã parse xong, vì việc phân giải cần chỉ mục tên toàn cục.

Đây là phase mà gói này thành thật nhất về điểm yếu của chính nó. Một cạnh chỉ là `resolved` khi một cái tên có **đúng một** định nghĩa trên toàn repository. Hai hàm cùng tên `run` ở bất kỳ đâu trong cây sẽ khiến mọi tham chiếu tới `run` trở thành `ambiguous`. Confidence là số cứng — 0.55 cho resolved, 0.2 cho ambiguous — và đó là **hằng số khai báo**, không phải xác suất đã hiệu chuẩn.

### P4 — Snapshot (`sqlite_store.write_snapshot` + thay thế nguyên tử)

Ghi ra `{repo_id}.tmp-{uuid}.sqlite`, rồi `shutil.move` đè lên đích sau khi xóa các file `-wal`/`-shm` cũ. Một bên đọc hoặc thấy trọn snapshot cũ, hoặc thấy trọn snapshot mới.

Manifest được ghi **hai lần** có chủ ý: một lần để tính SHA-256 của database, rồi ghi lại với `artifact_sha256` đã nhúng vào.

### P5 — Truy xuất (`RetrievalService`)

Sáu công cụ, mỗi công cụ mở snapshot SQLite ở chế độ **chỉ đọc**:

| Công cụ | Trả lời câu hỏi | Bị chặn bởi |
|---|---|---|
| `get_repo_map` | "Trong repository này có gì?" | `budget_tokens` |
| `find_symbols` | "X được định nghĩa ở đâu?" | `limit`, bị chặn trần bởi `max_symbol_results` |
| `get_file_skeleton` | "File này có gì?" | `max_tokens` |
| `get_symbol_context` | "Symbol này trông ra sao và chạm tới đâu?" | `max_tokens`, `depth` ≤ 3 |
| `get_impact_slice` | "Sửa cái này thì có thể hỏng cái gì?" | `max_nodes`, bị chặn trần bởi `max_graph_nodes` |
| `get_index_status` | "Index còn hợp lệ không?" | — |

`get_file_skeleton` minh họa rõ nhất ý tưởng cốt lõi: nó trả về **các dòng import cộng phần đầu của từng symbol với thân đã lược bỏ**, dành sẵn một phần tư ngân sách cho import trước khi nhồi phần đầu symbol vào chỗ còn lại.

Phép duyệt (`_traverse`) là BFS với tập `visited` và trần `max_nodes` được kiểm ở **cả** điều kiện vòng lặp lẫn nhánh nạp hàng đợi.

### P6 — Nhồi theo ngân sách

`pack_by_budget` duyệt các mục đã xếp hạng và nhận từng mục khi `used + estimated ≤ budget`, với một ngoại lệ: mục đầu tiên vẫn được nhận kể cả khi riêng nó đã vượt ngân sách, để một yêu cầu không bao giờ trả về rỗng. Các mục bị bỏ được **trả lại**, không bị vứt đi — bên gọi biết mình đã không nhận được gì.

### P7 — Phong bì

Mọi phản hồi mang cùng một hình dạng, và đây là phần trưởng thành nhất của thiết kế:

```json
{ "schema_version", "repo_id", "index_run_id",
  "freshness": "fresh|stale",
  "budget": {"requested_tokens", "estimated_tokens"},
  "truncated": bool,
  "completeness": {"value", "basis"},
  "warnings": [...],
  "evidence": [{"path","start_line","end_line","sha256"}],
  "data": {...} }
```

`completeness` mang theo chuỗi `basis` của chính nó (`resolved_edges / observed_edges`, hoặc `no_edges_observed`) nên một con số **không bao giờ bị tách rời khỏi thứ đã sinh ra nó**. Các cảnh báo nói rõ về nhận thức luận: `lexical_edges_are_not_complete_semantic_analysis`, `ambiguous_lexical_edges_present`, `indexed_hash_differs_from_current_file`, `potential_secrets_redacted`, `network_policy_not_enforced_by_process`.

Độ tươi được tính bằng cách băm lại **mọi** file đã index ở **mọi** lời gọi.

---

## 4. Kinh tế token — cơ chế, và thứ nó thực sự đo

### 4.1 Bốn cơ chế

1. **Chữ ký thay vì thân hàm.** Một symbol tốn phần đầu của nó, không tốn phần cài đặt. `get_file_skeleton` trên một file nguồn 2.396 token trả về ~1.008 token.
2. **Xếp hạng thay vì liệt kê.** Bậc vào, bậc ra và số từ khóa khớp quyết định ngân sách cố định được tiêu vào đâu, nên N mục đầu tiên là những mục có kết nối và liên quan tới truy vấn.
3. **Ngân sách cứng thay vì hy vọng.** Bên gọi nêu `budget_tokens`; bộ nhồi dừng lại. Thứ bị bỏ quay về dưới dạng `omitted_count` và `omitted_symbol_ids`.
4. **Snapshot thay vì đọc lại.** Việc parse diễn ra một lần cho mỗi băm nội dung. File không đổi được tái sử dụng từ database trước.

### 4.2 Đo được trên máy này

Đường cơ sở = đọc mọi file `.py` dưới `src/` với công thức `bytes/4`.

| Repository | Đường cơ sở | Payload `repo_map` @1024 | **Tỷ lệ thật** |
|---|---|---|---|
| Repository A (38 file, 273 KB) | 68.259 tok | 8.849 tok | **7,7x** |
| Repository B — chính repo này (27 file, 81 KB) | 20.370 tok | 7.803 tok | **2,6x** |

Một khoản tiết kiệm thật, và đáng có. Nhưng **ngân sách khai báo không phải thứ thực sự tới nơi**.

### 4.3 Ngân sách đếm thiếu so với payload

`pack_by_budget` đo chuỗi *đã render* mà nó được đưa. `get_repo_map` render `f"{path}:{line} {signature}"` để nhồi — rồi phát ra trọn `symbol_as_dict()` **cộng thêm** một khối `evidence` cho mỗi symbol.

Một mục, đo thật:

```
pack_by_budget đo được  : 20 token   'src/.../error_codes.py:25 class PipelineException(Exception)'
thực tế phát ra         : 158 token  (symbol_id, qualified_name, 4 byte offset, is_private, evidence+sha256)
```

Trên toàn bộ phản hồi `repo_map` ở `budget_tokens=1024`:

| Công cụ | `estimated_tokens` | Payload thật | Chênh |
|---|---|---|---|
| `repo_map` @1024 | 1.020 | 8.849 | **8,7x** |
| `file_skeleton` @1024 | 192 | 1.008 | 5,2x |
| `symbol_context` @1024 | 395 | 7.253 | **18,4x** |
| `symbol_context` @2048 | 395 | 7.253 | 18,4x — *giống hệt; `max_tokens` không hề ràng buộc* |
| `find_symbols` limit=5 | 575 | 895 | 1,6x |
| `impact_slice` d=2 n=50 | 25.141 | 28.618 | 1,1x |

8.849 token đó đi đâu:

```
symbol dicts        4.411
omitted_symbol_ids  2.321   <- gấp 2,3 lần toàn bộ ngân sách khai báo, chỉ để liệt kê những gì đã bị bỏ
evidence            1.633   <- một SHA-256 dài 64 ký tự cho mỗi symbol
overhead phong bì      39
```

Riêng `omitted_symbol_ids` tốn **hơn gấp đôi** ngân sách mà bên gọi yêu cầu. Mỗi id là một chuỗi đầy đủ `python:path/to/file.py:Qualified.Name:hexdigest`, và trả về tối đa 100 cái.

### 4.4 `impact_slice` hoàn toàn không có ràng buộc token

Đo trên một server cấu hình `max_result_tokens = 2048`:

```
impact_slice(depth=2, max_nodes=50) -> 28.618 token, truncated: False
```

Gấp **mười bốn lần** trần cấu hình, và được gắn cờ là *không* bị cắt. Ba đường code kết hợp lại:

- `impact_slice` không bao giờ gọi `_validate_budget` — phép kiểm đó chỉ chạy ở nơi có tham số ngân sách.
- Nó truyền `requested_tokens=0`, và `_envelope` tính `truncated` theo `(estimated > requested if requested else False)`. Số 0 là falsy, nên `truncated` **luôn** là `False` theo cấu tạo.
- Ràng buộc duy nhất của nó là `max_nodes`, thứ giới hạn *node đồ thị*, không giới hạn token. Năm mươi symbol và 182 cạnh tuần tự hóa thành 28 KB JSON.

Mẫu `requested_tokens=0` tương tự cũng áp dụng cho `find_symbols` và `status`, nơi payload tình cờ nhỏ.

**Không điều nào ở đây làm công cụ trở nên vô dụng** — 7,7x cho việc định hướng là thật. Nó có nghĩa là những con số mà bên gọi thấy trong `budget` **không phải** những con số mà mô hình phải trả, và một công cụ có thể vượt trần cấu hình mà không nói gì.

### 4.5 Chưa có bằng chứng đầu-cuối nào

`evals/sample-runs.jsonl` chứa **hai bản ghi** — một `B0`, một `B1`. Kết quả `median_paired_token_reduction: 0.254` có `paired_count: 1` và CI95 là `[0.254, 0.254]`: một khoảng tin cậy suy biến từ đúng một cặp tổng hợp.

Repository **không giấu điều này**. `BENCHMARK.md` nói rằng một kết quả công bố được đòi hỏi các tác vụ B0–B6 ghép cặp với cùng mô hình, prompt, quyền và seed, dùng số token do nhà cung cấp báo. Bản thân bộ harness thì tốt — giảm theo cặp, bootstrap tất định, cùng một delta không-thua-kém về chất lượng để một khoản thắng token mà làm hỏng tác vụ vẫn nhìn thấy được. Nó chỉ đơn giản là chưa bao giờ được cho ăn một lượt chạy thật.

---

## 5. Các file config

| File | Mục đích |
|---|---|
| `%APPDATA%\token-context-mcp\repos.toml` | Registry sống theo từng người dùng: khối `[server]` chứa giới hạn và mỗi repository một khối `[repos.<id>]`. Ghi đè được bằng `TOKEN_CONTEXT_CONFIG` |
| `%APPDATA%\token-context-mcp\indexes\<repo_id>.sqlite` | Snapshot. Đường dẫn suy ra bằng `config_path.parent / "indexes"` |
| `%APPDATA%\token-context-mcp\indexes\<repo_id>.manifest.json` | Metadata lượt chạy cộng `artifact_sha256` của database |
| `config/repos.example.toml` | Mẫu |
| `.mcp.json` | Cấu hình khởi động `stdio` cho Claude Code / Codex |
| `schemas/index-manifest.schema.json`, `schemas/mcp-result.schema.json` | JSON Schema cho manifest và phong bì phản hồi |

Các khóa `[server]`, kèm dải giá trị được cưỡng chế lúc nạp:

| Khóa | Dải | Tác dụng |
|---|---|---|
| `max_request_bytes` | 1.024 – 1.048.576 | Từ chối tham số công cụ quá lớn |
| `max_result_tokens` | 32 – 8.192 | Trần cho mọi `budget_tokens` / `max_tokens` — **không áp dụng cho `impact_slice`** |
| `max_graph_nodes` | 1 – 500 | Chặn bề rộng phép duyệt |
| `max_symbol_results` | 1 – 100 | Chặn `find_symbols` |
| `network_policy` | chuỗi | Chỉ mang tính khai báo. Manifest ghi rõ `declared_only; enforce at OS/container boundary` |

Theo từng repository: `root`, `allow_symlinks` (mặc định `false`), `max_file_bytes` (2 MB), `max_files` (25.000).

---

## 6. SWOT

### Điểm mạnh (Strengths)

- **Sự trung thực về nhận thức được hiện thực hóa, không chỉ viết trong tài liệu.** `completeness.basis`, `lexical_edges_are_not_complete_semantic_analysis`, các stub `enabled: False` kèm lý do, `evidence` có SHA-256 cho mọi khẳng định. Rất ít công cụ truy xuất nói cho bên gọi biết nên tin kết quả tới mức nào.
- **Bảo mật nhiều tầng và cưỡng chế ngay tại ranh giới.** Allowlist đăng ký → danh sách chặn → gitignore → kiểm reparse point theo từng thành phần đường dẫn → kiểm lại việc giam giữ sau khi phân giải → che bí mật → SQLite chỉ đọc → lỗi chung chung. Path traversal và thoát bằng junction được xử lý đúng trên Windows.
- **Tính nguyên tử và tái sử dụng của snapshot.** Ghi file tạm rồi thay thế nghĩa là bên đọc không bao giờ thấy một index viết dở; tái sử dụng theo băm khiến việc index lại rẻ đi và báo `files_reused` một cách trung thực.
- **Nhỏ và dễ đọc.** 2083 dòng, dataclass đóng băng, không có cây kế thừa. Toàn bộ có thể đọc trong một buổi chiều và kiểm toán trong một ngày.
- **Tất định.** Kiểm kê được sắp xếp, import được sắp xếp, bootstrap có seed, chuỗi version cho bộ ước lượng.

### Điểm yếu (Weaknesses)

- **Ngân sách không đo payload** (§4.3). Đếm thiếu 8,7x ở `repo_map`, 18,4x ở `symbol_context`. Riêng `omitted_symbol_ids` vượt ngân sách yêu cầu 2,3 lần.
- **`impact_slice` không bị ràng buộc token** (§4.4). 28.618 token từ một server 2.048 token, gắn cờ `truncated: false`.
- **`max_tokens` của `symbol_context` không ràng buộc.** Payload giống hệt nhau ở 1024 và 2048 — mảng `edges` được phát ra ngoài bộ nhồi.
- **Cạnh từ vựng chỉ phân giải được những cái tên duy nhất toàn cục.** Bất kỳ repository nào có hai định nghĩa `run`, `main` hay `handle` đều thoái hóa dần về ambiguous. Giá trị confidence là hằng số, chưa bao giờ được hiệu chuẩn.
- **Độ tươi tốn một lần băm lại toàn bộ ở mỗi lời gọi.** `_freshness` băm lại mọi file đã index ở mọi lần gọi công cụ; với `video-lecturer` đó là 4.559 file.
- **Chỉ bốn ngôn ngữ.** Không có Go, Rust, Java, C#, Ruby, PHP. Markdown, JSON, YAML và TOML được index như file nhưng không cho ra symbol nào.
- **Chưa có khoản tiết kiệm đầu-cuối nào được đo** (§4.5). Hai dòng mẫu.
- **CLI hỏng trong im lặng.** `python -m token_context_mcp.cli register …` thoát mã 0 và không làm gì — `cli.py` thiếu `__main__` guard. Riêng biệt, `uv run token-context …` thất bại khi MCP server đang giữ console script trên Windows.
- **`repo_id` không trỏ lại được.** Đúng đắn xét như một thuộc tính an toàn, nhưng không có lệnh `unregister` hay `update`, nên cách duy nhất là sửa tay file TOML.

### Cơ hội (Opportunities)

- **Sửa phần kế toán thì tỷ lệ thật sẽ tăng.** Hạ `omitted_symbol_ids` xuống chỉ còn một con số đếm, cắt các byte offset khỏi symbol phát ra, và rút gọn băm evidence còn 12 ký tự sẽ giảm payload `repo_map` từ 8.849 xuống khoảng ~4.000 mà không mất nội dung dùng được — tức gần **gấp đôi** con số 7,7x đã đo.
- **Nhồi theo phong bì, không theo bản render.** Nhồi dựa trên `estimate_tokens(json.dumps(entry))` sẽ khiến `estimated_tokens` mang đúng nghĩa mà bên gọi vẫn giả định.
- **Chạy benchmark cho thật.** Bộ harness đã hoàn thiện; nó chỉ cần các tác vụ B0–B6 ghép cặp chạy với một nhà cung cấp thật. Việc đó biến khẳng định trung tâm từ *có lý* thành *đã chứng minh*.
- **Kiểm độ tươi rẻ hơn.** Kiểm `mtime_ns` và `size` trước, chỉ băm khi chúng khác nhau. `FileRecord` vốn đã lưu cả hai.
- **Các stub đã sẵn sàng để kích hoạt.** `SemanticBackendStatus` đã được thiết kế; một `pyright`/`tsserver` đã ghim phiên bản và đưa vào sandbox sẽ nâng `confidence` từ một hằng số lên thành một phép đo.
- **Thêm ngôn ngữ rất rẻ.** Thêm một grammar chỉ là một mục trong `SUPPORTED_EXTENSIONS` cộng một khối `_NODE_KINDS`.

### Nguy cơ (Threats)

- **Cảm giác sai về độ phủ.** `repo_map` với `truncated: true` và 133 symbol bị bỏ có thể đọc ra như một bản đồ đầy đủ. Phong bì nói ngược lại, nhưng phong bì thì hay bị đọc lướt.
- **Vượt ngân sách trong im lặng.** Một agent tin vào `budget.estimated_tokens` để hoạch định ngữ cảnh sẽ sai 8–18 lần, và `impact_slice` có thể tiêm vào 28 KB mà không báo trước. Đây là nguy cơ dễ cắn nhất trong vận hành thật.
- **Độ mơ hồ tăng theo kích thước repository.** Phân giải từ vựng thoái hóa khi va chạm tên tăng lên — đúng ngay chỗ mà công cụ này cần thiết nhất.
- **Trôi lệch do index cũ.** `freshness` có báo, nhưng không gì ngăn việc phục vụ một snapshot cũ; một bên gọi bỏ qua trường đó sẽ nhận được số dòng sai một cách đầy tự tin.
- **`network_policy` đọc như một cơ chế cưỡng chế.** Nó chỉ mang tính khai báo. Manifest và cảnh báo có nói vậy, nhưng chính cái tên khóa mời gọi một giả định sai.
- **Việc che bí mật dựa trên regex.** Một bí mật không khớp các dạng gán `key|secret|token|password|private_key|authorization` sẽ lọt qua. Nó **giảm** phơi nhiễm; nó không **ngăn** phơi nhiễm.

---

## 7. Thứ tự nên đọc

1. `constants.py` và `models.py` — bộ từ vựng
2. `index/runner.py:build_index` — P1 tới P4 gói trong một hàm
3. `retrieve/service.py:_envelope` — bản hợp đồng mà mọi câu trả lời phải tuân theo
4. `parse/lexical_edges.py` — nơi độ chính xác bị mất, và nơi điều đó được khai báo
5. `retrieve/token_budget.py` — 33 dòng, và là nguồn gốc của §4.3
