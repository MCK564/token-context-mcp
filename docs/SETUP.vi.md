# Cài đặt từ đầu tới khi chạy được

**Bản EN:** `SETUP.en.md` · **Số liệu đo:** `BENCHMARK_FINDINGS.vi.md` · **Runbook benchmark:** `X6_RUNBOOK.vi.md`

Ký hiệu độ tin cậy trong tài liệu này:

- **[đã kiểm chứng]** — chạy thật trên máy Windows 11 / Python 3.12.5 / uv 0.11.26 ngày 28/08/2026.
- **[đã kiểm chứng một phần]** — lệnh khởi chạy đã chạy thật, nhưng chặng cuối (client có nạp config không) phải do bạn xác nhận trong app.
- **[theo tài liệu]** — theo định dạng nhà cung cấp công bố, **chưa** chạy thử trên máy này. Hãy làm bước xác minh đi kèm.

---

## 1. Yêu cầu hệ thống

| Thành phần | Yêu cầu | Kiểm tra |
|---|---|---|
| Python | **≥ 3.12** (`pyproject.toml` ghi `requires-python = ">=3.12"`) | `python --version` |
| uv | bất kỳ bản gần đây | `uv --version` |
| Hệ điều hành | Windows / macOS / Linux. Phần kiểm reparse point là đặc thù Windows nhưng không chặn nền khác | — |
| Ổ đĩa | ~50 MB cho gói + index. Index của `invoice-scanner` (220 file) là ~1,5 MB | — |

Không cần GPU, không cần khóa API, không cần mạng lúc chạy. Server **không gọi API mạng nào**.

Nếu chưa có uv:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

---

## 2. Cài đặt gói **[đã kiểm chứng]**

```powershell
git clone https://github.com/MCK564/token-context-mcp.git
cd token-context-mcp
uv sync --extra dev
```

`uv sync` tự tạo `.venv/` và cài đúng phiên bản trong `uv.lock`. Không cần `python -m venv` thủ công.

Phụ thuộc runtime (6 gói, không có gói nặng):

```
mcp>=2.0.0                    giao thức MCP
pathspec>=0.12.1              đọc .gitignore khi kiểm kê file
tree-sitter>=0.24.0           bộ phân tích cú pháp
tree-sitter-python>=0.23.6    grammar Python
tree-sitter-javascript>=0.23.1
tree-sitter-typescript>=0.23.2
```

Nhóm `dev` thêm `pytest`, `pytest-cov`, `jsonschema`.

**Xác minh cài đặt:**

```powershell
uv run pytest
```

Kỳ vọng: **54 passed, 1 skipped** (một test bị skip có chủ ý — nó cần một môi trường không có ở CI).

Nếu `uv run` báo lỗi khóa file `token-context.exe` trên Windows: đó là do một tiến trình MCP đang giữ console script. Dùng đường module thay thế — **mọi lệnh quản trị trong tài liệu này đều có dạng module**:

```powershell
uv run python -m token_context_mcp <lệnh>
```

---

## 3. Đăng ký và index repository **[đã kiểm chứng]**

Server chỉ đọc được repository đã nằm trong danh sách cho phép. Nó **không** tự dò thư mục làm việc.

```powershell
uv run python -m token_context_mcp register --repo-id myrepo --root D:\AI\myrepo
uv run python -m token_context_mcp index    --repo-id myrepo
uv run python -m token_context_mcp status   --repo-id myrepo
```

Quy tắc quan trọng:

- `--repo-id` phải khớp `^[a-z][a-z0-9_-]{0,63}$`. **Không bao giờ truyền đường dẫn làm `repo_id`** — đây là lỗi đã làm hỏng trọn một lượt benchmark (xem `BENCHMARK_FINDINGS.vi.md` §2.7).
- `--root` là **một** thư mục repository cụ thể. Đừng đăng ký thư mục cha như `D:\AI` cho tiện.
- Đăng ký lại cùng `repo_id` sẽ **báo lỗi**, không âm thầm trỏ sang root mới. Muốn đổi thì dùng `update --force`.

```powershell
uv run python -m token_context_mcp unregister --repo-id myrepo
uv run python -m token_context_mcp update --repo-id myrepo --root D:\AI\new-path --force
```

Registry mặc định nằm ở `%APPDATA%\token-context-mcp\repos.toml` (Windows), `$XDG_CONFIG_HOME` hoặc `~/.config` trên nền khác. Đặt biến `TOKEN_CONTEXT_CONFIG` nếu muốn registry di động hoặc dùng chung.

**Chạy lại `index` sau mỗi lần code đổi đáng kể.** Server báo `freshness: "stale"` khi file trên đĩa khác với lúc index, nhưng nó **không tự index lại**.

---

## 4. Chỉnh giới hạn tài nguyên

Sửa khối `[server]` trong `%APPDATA%\token-context-mcp\repos.toml`, rồi **khởi động lại tiến trình MCP** (registry chỉ đọc lúc khởi động):

```toml
[server]
max_request_bytes  = 65536
max_result_tokens  = 4096
max_graph_nodes    = 200
max_symbol_results = 30
network_policy     = "declared-deny-not-enforced"
```

`max_result_tokens` là **núm điều khiển chính** cho chi phí token. Mỗi phản hồi được trừ sẵn 96 token cho khung MCP trước khi nhồi nội dung, nên không lời gọi nào vượt trần.

`list_repositories` công bố bốn profile ngân sách dựng sẵn là `locate`, `orient`, `impact` và `read`. Truyền `profile` cho tool phù hợp; các tham số tường minh như `budget_tokens`, `limit`, `depth` hoặc `include_body` sẽ ghi đè profile. `get_impact_slice` nhận `max_tokens`; nếu bỏ qua thì mặc định là giá trị nhỏ hơn giữa 2.048 và trần kết quả của server.

---

## 5. Cấu hình từng agent

Lệnh khởi động **giống nhau cho mọi agent**:

```
uv run --no-sync --directory <ĐƯỜNG_DẪN_TUYỆT_ĐỐI_TỚI_REPO> token-context serve --transport stdio
```

`--no-sync` là bắt buộc: không có nó, uv sẽ cố cài lại console script mỗi lần khởi động và **thất bại trên Windows** khi server đang chạy.

### 5.1 Claude Code **[đã kiểm chứng]**

Tạo `.mcp.json` ở gốc dự án (mẫu có sẵn tại `.mcp.json.example`):

```json
{
  "mcpServers": {
    "token-context": {
      "type": "stdio",
      "command": "uv",
      "args": [
        "run", "--no-sync",
        "--directory", "D:/AI/token-context-mcp",
        "token-context", "serve", "--transport", "stdio"
      ]
    }
  }
}
```

Nếu `uv` không nằm trên PATH của tiến trình Claude Code, thay `"command"` bằng đường dẫn tuyệt đối tới `uv.exe`.

**Xác minh:** mở Claude Code trong dự án, chạy `/mcp`. Server `token-context` phải hiện với 9 tool.

### 5.2 Codex CLI **[đã kiểm chứng một phần]**

```powershell
codex mcp add token-context -- uv run --no-sync --directory D:\AI\token-context-mcp token-context serve --transport stdio
codex mcp list
```

Bật/tắt cho từng lượt chạy — chính là cách bộ benchmark tạo nhánh B0:

```powershell
codex exec --json -c mcp_servers.token-context.enabled=false "..."
```

### 5.3 GitHub Copilot trong VS Code **[đã kiểm chứng một phần]**

VS Code đọc cấu hình MCP từ **`.vscode/mcp.json`** ở gốc workspace. Lưu ý khóa cấp cao nhất là **`servers`**, *không phải* `mcpServers` như Claude Code:

```json
{
  "servers": {
    "token-context": {
      "type": "stdio",
      "command": "uv",
      "args": [
        "run", "--no-sync",
        "--directory", "D:/AI/token-context-mcp",
        "token-context", "serve", "--transport", "stdio"
      ]
    }
  }
}
```

Muốn dùng cho mọi workspace thì đặt cùng nội dung vào `%APPDATA%\Code\User\mcp.json`.

Các bước bật:

1. Cài extension **GitHub Copilot** và **GitHub Copilot Chat**, đăng nhập tài khoản có quyền Copilot.
2. Trong `settings.json`, bật `"chat.mcp.enabled": true`.
3. Mở Chat, chuyển sang chế độ **Agent** (MCP chỉ hoạt động ở agent mode, không hoạt động ở chế độ hỏi đáp thường).
4. Bấm biểu tượng công cụ trong khung Chat để xem danh sách tool; `token-context` phải xuất hiện.

**Xác minh — làm bước này, đừng bỏ qua:**

- Command Palette → `MCP: List Servers` → `token-context` phải ở trạng thái running.
- Nếu không thấy: Command Palette → `MCP: Show Output` để đọc log khởi động. Lỗi hay gặp nhất là `uv` không có trên PATH của VS Code; thay bằng đường dẫn tuyệt đối tới `uv.exe`.
- Trong Chat, hỏi: *"list the repositories available from token-context"*. Nếu trả về danh sách `repo_id` thì server đã nối đúng.

> **Đã kiểm chứng đến đâu.** Trên máy này: VS Code **1.135.0** (MCP đã GA, dùng khóa `servers`), Copilot Chat đang hoạt động — nó là extension **built-in**, nên không xuất hiện trong `code --list-extensions`. File `.vscode/mcp.json` ở trên đã được tạo sẵn trong repo và parse hợp lệ. Chính **lệnh khởi chạy** bên trong đã được kiểm chứng bằng bắt tay MCP thật qua stdio: `initialize` thành công, `tools/list` trả về đủ **9 tool**.
>
> Phần **chưa** kiểm chứng là chặng cuối: Copilot Chat có nạp file này và hiện tool ra hay không. Đó là việc bạn xác nhận trong app bằng `MCP: List Servers`.

### 5.4 GitHub Copilot CLI **[theo tài liệu]**

Copilot CLI dùng file cấu hình riêng, không dùng chung với VS Code. Cách chắc chắn nhất là dùng lệnh có sẵn của chính CLI thay vì sửa file tay:

```powershell
copilot
# trong phiên tương tác:
/mcp add
```

rồi khai báo: transport `stdio`, command `uv`, args như mục 5.1.

**Xác minh:** `/mcp` trong phiên Copilot CLI phải liệt kê `token-context`.

### 5.5 Antigravity **[đã kiểm chứng một phần]**

Antigravity không dùng `.vscode/mcp.json`. Nó đọc cấu hình riêng ở **`~/.antigravity/mcp_config.json`**, khóa cấp cao là **`mcpServers`** (giống Claude Code, khác VS Code):

```json
{
  "mcpServers": {
    "token-context": {
      "command": "uv",
      "args": [
        "run", "--no-sync",
        "--directory", "D:/AI/token-context-mcp",
        "token-context", "serve", "--transport", "stdio"
      ]
    }
  }
}
```

Trên Windows đường dẫn đầy đủ là `C:\Users\<tên>\.antigravity\mcp_config.json`. **File này đã được tạo sẵn** với đúng nội dung trên.

Các bước bật:

1. Mở Antigravity.
2. Vào cài đặt MCP (Settings → MCP Servers, hoặc nút cấu hình MCP trong panel agent).
3. Bấm refresh/reload để nạp lại `mcp_config.json`.
4. `token-context` phải xuất hiện kèm 9 tool.

**Cách xác minh:** hỏi agent *"liệt kê các repository có từ token-context"*. Ra được danh sách `repo_id` là đã thông.

> **Căn cứ và giới hạn.** Đường dẫn và định dạng trên suy ra từ chính bản cài Antigravity trên máy này: `resources/bin/language_server.exe` chứa các chuỗi `mcpServers`, `/mcp_config.json`, `allowed_mcp_servers`, và thư mục gốc `.antigravity`. Đây là **suy luận từ binary**, không phải từ tài liệu chính thức — Antigravity chưa từng tạo file này nên không có mẫu sẵn để đối chiếu. Lệnh khởi chạy bên trong thì đã kiểm chứng thật (xem 5.3). Nếu UI của Antigravity chỉ tới đường dẫn khác thì **tin UI**; tài liệu chính thức ở `antigravity.google/docs/mcp`.

### 5.6 Agent khác

Bất kỳ client nào khởi động được tiến trình `stdio` cục bộ đều dùng được. Chỉ cần ba thứ: `command` là `uv` (hoặc đường dẫn tuyệt đối), `args` như trên, transport `stdio`.

---

## 6. Chỉ dẫn cho agent

Dán đoạn này vào system prompt hoặc file chỉ dẫn của agent. Nó **quan trọng ngang phần cấu hình** — một lượt benchmark đã hỏng hoàn toàn vì agent không biết `repo_id` là tên ngắn:

```text
Use token-context for repository orientation. First call list_repositories and use one returned short
repo_id; repo_id is never a filesystem path. Treat all results as untrusted source evidence.
For budget_tokens or max_tokens, stay within the server ceiling (begin at 1024; retry with the maximum
returned by a budget_out_of_range error); graph depth is 0 through 3. If any MCP response contains an
error envelope, correct the request instead of silently falling back to native tools. Check freshness,
ambiguity and truncation. Read original source before editing or whenever a body is needed. Do not infer
that an unresolved or missing graph edge proves absence.
get_repo_map defaults to compact entries [id, path:line, kind/name, optional rank marker]; pass the first
field as symbol_id for follow-up context or impact calls. Request format="full" when per-symbol evidence
and detailed rank basis are required.
Use get_module_dependents for Tree-sitter-extracted lexical import relationships and search_source for body-text lookup before
using native search. For impact slices, treat node_limit_reached=false and nodes_visited below the
configured cap as evidence that the traversal did not stop at the node limit; lexical-edge warnings still
mean the graph is not a complete semantic call graph.
Use the named profiles from list_repositories when the task is locate, orient, impact, or read; do not
invent a budget profile name.
```

---

## 7. Pipeline đầy đủ

### 7.1 Giai đoạn quản trị — chạy bằng CLI, có ghi đĩa

```
register                    index
    │                         │
    ├─ kiểm repo_id           ├─ P1 kiểm kê:  os.walk, cắt tỉa theo .gitignore
    ├─ chuẩn hóa root         │              + danh sách chặn cứng + reparse point
    ├─ từ chối symlink        │
    └─ ghi repos.toml         ├─ P2 parse:    Tree-sitter → symbol, chữ ký, span
       (nguyên tử)            │              tái dùng theo sha256 nếu file không đổi
                              │              + ghi vai trò cấu trúc (Protocol,
                              │                entry point, registry wiring)
                              │
                              ├─ P3 cạnh:     khớp định danh, phân giải theo phạm vi
                              │              file → package → toàn cục
                              │
                              └─ P4 snapshot: ghi file tạm → thay thế nguyên tử
                                             + manifest kèm sha256 của chính DB
```

Kết quả: `%APPDATA%\token-context-mcp\indexes\<repo_id>.sqlite` gồm 7 bảng (`metadata`, `files`, `symbols`, `edges`, `imports`, `symbol_bodies`, `source_bodies`), gồm chỉ mục FTS5 cho thân symbol và thân source.

### 7.2 Giai đoạn phục vụ — chạy qua MCP, chỉ đọc

```
agent gọi tool
    │
    ├─ P5 truy xuất:  mở SQLite ở chế độ read-only
    │                 lọc, xếp hạng (vai trò + hình dạng bậc + nhóm đường dẫn)
    │
    ├─ P6 ngân sách:  nhồi entry cho tới hạn mức, trừ sẵn 96 token khung MCP
    │                 phần bị bỏ trả về dưới dạng omitted_count
    │
    └─ P7 phong bì:   schema_version, freshness, budget, truncated,
                      completeness{value, basis}, warnings, evidence, data
```

### 7.3 Chín tool

| Tool | Trả lời câu hỏi | Bị chặn bởi |
|---|---|---|
| `list_repositories` | "có repo nào, profile nào" | — |
| `get_index_status` | "index còn mới không, entry point có phân giải được không" | — |
| `get_repo_map` | "repo này có gì" | `budget_tokens` |
| `find_symbols` | "X định nghĩa ở đâu" | `limit`, trần `max_symbol_results` |
| `search_source` | "chuỗi này xuất hiện ở đâu trong thân mã" | `max_tokens` |
| `get_file_skeleton` | "file này có gì" | `max_tokens` |
| `get_symbol_context` | "symbol này trông ra sao, chạm tới đâu" | `max_tokens`, `depth ≤ 3` |
| `get_impact_slice` | "sửa cái này thì có thể hỏng gì" | `max_nodes`, `max_tokens` |
| `get_module_dependents` | "ai import module này" | — |

### 7.4 Kiến trúc hiện tại và sơ đồ mã nguồn

Code có hai mặt phẳng: CLI quản trị ghi snapshot SQLite nguyên tử, còn MCP server mở snapshot ở chế độ chỉ đọc. Các lớp mã nguồn là:

| Lớp | Module chính | Trách nhiệm |
|---|---|---|
| Nền tảng | `constants.py`, `models.py`, `config.py` | giới hạn, bản ghi bất biến và registry repository |
| Bảo mật | `security/path_policy.py`, `security/content_policy.py` | containment đường dẫn, deny-list, kiểm tra binary và che secret |
| Index | `index/runner.py`, `index/sqlite_store.py`, `index/freshness.py` | inventory, parse, reuse, snapshot nguyên tử và freshness |
| Parse | `parse/treesitter.py`, `parse/lexical_edges.py` | định nghĩa/span, import lexical và cạnh identifier quan sát được |
| Truy xuất | `retrieve/service.py`, `retrieve/token_budget.py`, `retrieve/ranking.py` | lookup có giới hạn, xếp hạng, duyệt graph và envelope bằng chứng |
| Biên | `server.py`, `cli.py`, `telemetry/benchmark.py` | MCP stdio, lệnh quản trị và kế toán benchmark |

Có ba mức phân tích rõ ràng: định nghĩa và span từ Tree-sitter; graph identifier lexical với cạnh có thể `resolved` hoặc `ambiguous`; và adapter semantic LSP/SCIP tùy chọn, hiện vẫn tắt cho tới khi có đánh giá precision/recall theo ngôn ngữ và review sandbox. Server không bao giờ xem việc thiếu một cạnh lexical là bằng chứng rằng không có cạnh semantic.

Artifact bền vững gồm registry theo user tại `%APPDATA%\\token-context-mcp\\repos.toml` (hoặc đường dẫn tương đương trên nền tảng khác), snapshot tại `indexes\\<repo_id>.sqlite` và manifest chứa hash của database. Package không đọc root tùy ý ngoài allowlist đã đăng ký.

---

## 8. Chính xác thì phần nào được tiết kiệm

Đây là phần hay bị hiểu sai nhất, nên nói thẳng bằng số đo.

### 8.1 Token chia làm bốn loại

| Loại | Nội dung | MCP có tác động không |
|---|---|---|
| **input, chưa cache** | nội dung mới đưa vào lượt này | **có — đây là chỗ tiết kiệm** |
| **input, đã cache** | lịch sử hội thoại phát lại | gián tiếp, chỉ khi giảm số lượt |
| **reasoning** | suy luận nội bộ của model | không trực tiếp |
| **output** | patch, lời gọi tool, câu trả lời | **không nén được** |

### 8.2 Cơ chế tiết kiệm, kèm số đo

Đo trên `invoice-scanner` (124 file Python, 882.304 byte ≈ 220.576 token):

| Cơ chế | Trước | Sau |
|---|---|---|
| Chữ ký thay vì thân hàm | đọc cả file 19.327 token | `get_file_skeleton` ~985 token |
| Entry gọn thay vì đầy đủ | 107 token/symbol | **24 token/symbol** |
| Bỏ trùng lặp payload MCP | JSON gửi 2 lần | gửi 1 lần, còn ~48% |
| Xếp hạng đúng | recall 0,167, 3 nhiễu | **recall 0,833, 0 nhiễu** |
| Diệt N+1 | 1.077 truy vấn, 13,87 s | **3 truy vấn, 0,164 s** |

### 8.3 Điều **không** được tuyên bố

- **Output không giảm.** Patch và câu trả lời cuối vẫn tốn gần như cũ.
- **Trong workflow hybrid, MCP là cộng thêm chứ không thay thế.** Đo được: một tác vụ tăng **+46%** khối lượng truy xuất vì agent dùng MCP *rồi vẫn* grep.
- **`total_tokens` không phải thước đo đúng.** Trong một pilot, nội dung truy xuất là 2.558 token trên 120.832 token cached input — tức nội dung chiếm **2%**. Phần còn lại là độ dài hội thoại. Vì vậy chỉ số chính của benchmark là `retrieved_content_estimated_tokens`.
- **Với tác vụ định hướng thuần, `rg` có thể thắng.** Một lệnh `rg --files` cho danh sách file **đầy đủ** với 18.228 token; `repo_map` ở trần 4.096 chỉ cho ~6,6% số symbol. Lợi thế của MCP nằm ở **định vị và tác động**, nơi `rg` phải chạy lặp lại.

### 8.4 Khi nào tiết kiệm thật sự xuất hiện

Khi plan đã đủ rõ và MCP trả đủ thông tin để agent **không cần đọc lại source bằng native**:

1. Gọi `list_repositories`, rồi `get_index_status` cho `repo_id` ngắn.
2. Định vị ứng viên bằng `find_symbols` hoặc `search_source`; chỉ dùng `repo_map` khi cần định hướng rộng.
3. Mở rộng ứng viên bằng `get_symbol_context` ở `depth=1`.
4. Chỉ yêu cầu `include_body=true` cho symbol cuối cùng cần đọc implementation.
5. Chỉ dùng lệnh native read-only để kiểm chứng khi MCP báo bị cắt, mơ hồ hoặc graph lexical không đầy đủ; sau đó tạo patch và chạy test.

Lúc đó phần tiết kiệm là **toàn bộ output của `rg` và `Get-Content`** vốn sẽ trở thành input của lượt kế tiếp. Điều kiện: MCP phải báo `truncated=false`, `omitted_count=0`, `freshness=fresh` và không có cảnh báo mơ hồ. Nếu có bất kỳ cờ nào bật, agent **phải** xác minh bằng native — bỏ qua bước đó thì nhanh hơn nhưng dễ sai.

---

## 9. Sự cố thường gặp

| Triệu chứng | Nguyên nhân | Cách xử lý |
|---|---|---|
| `uv run` lỗi khóa `token-context.exe` | tiến trình MCP đang giữ console script | dùng `uv run python -m token_context_mcp ...` |
| `unknown_repo_id` | agent truyền đường dẫn làm `repo_id` | gọi `list_repositories` trước |
| `budget_out_of_range` | vượt `max_result_tokens` | dùng giá trị `maximum_tokens` mà lỗi trả về |
| `freshness: "stale"` | code đã đổi sau lần index | chạy lại `index` |
| Server không hiện trong agent | `uv` không có trên PATH của tiến trình agent | thay bằng đường dẫn tuyệt đối tới `uv.exe` |
| `python -m token_context_mcp.cli` thoát 0 không làm gì | sai đường module | dùng `python -m token_context_mcp` |
