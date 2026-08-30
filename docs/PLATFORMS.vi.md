# Nền tảng, truy cập từ xa, giới hạn và quyền hạn

**Bản EN:** `PLATFORMS.en.md` · **Hướng dẫn cài đặt:** `SETUP.vi.md` · **Chính sách bảo mật:** `../SECURITY.md`

Ký hiệu độ tin cậy trong tài liệu này:

- **[đã kiểm chứng]** — chạy thật trong lúc viết tài liệu này: Windows 11, Python 3.12, ngày 30/08/2026.
- **[đã kiểm chứng một phần]** — cơ chế đã chạy thật trên một máy thuộc họ đó, nhưng chưa chạy trọn bộ test.
- **[theo tài liệu]** — đúng theo hành vi nhà cung cấp công bố nhưng **chưa** chạy thử ở đây. Hãy làm bước xác minh đi kèm.

---

## 1. Hệ điều hành

| Hệ điều hành | Trạng thái | Ghi chú |
|---|---|---|
| Windows 10/11 | **[đã kiểm chứng]** — trọn bộ test, index, `harden --check` và bắt tay MCP `stdio` | Phần kiểm reparse point dùng `st_file_attributes`, chỉ tồn tại ở đây |
| Linux (x86-64) | **[đã kiểm chứng một phần]** — hành vi quyền hạn và xử lý path đã chạy trên Ubuntu 22.04 với `umask 0022`; trọn bộ test chạy trên `ubuntu-latest` trong CI | Phần kiểm reparse point lùi về `is_symlink()` |
| macOS | **[theo tài liệu]** — cùng nhánh code POSIX như Linux, chưa chạy ở đây | Registry nằm dưới `~/.config`, không phải `~/Library` |
| WSL | **[đã kiểm chứng một phần]** | Coi như Linux. Hãy index đường dẫn Linux (`/home/...`), đừng index `/mnt/c/...`: DrvFs không mang mode POSIX |

Yêu cầu giống nhau ở mọi nền tảng: **Python ≥ 3.12** (`pyproject.toml` ghi `requires-python = ">=3.12"`) và `uv`. Không cần GPU, không cần API key, không cần mạng lúc chạy.

CI chạy test nguồn và cài wheel trong môi trường sạch trên **`ubuntu-latest` và `windows-latest`** ở mỗi lần push.

### Dữ liệu nằm ở đâu

Theo từng máy **và** từng tài khoản. Đăng ký trên laptop của bạn không có tác dụng gì với server, và ngược lại.

| Hệ điều hành | Registry | Snapshot |
|---|---|---|
| Windows | `%APPDATA%\token-context-mcp\repos.toml` | `%APPDATA%\token-context-mcp\indexes\` |
| Linux | `$XDG_CONFIG_HOME/token-context-mcp/repos.toml`, nếu không có thì `~/.config/token-context-mcp/repos.toml` | `<thư mục registry>/indexes/` |
| macOS | `~/.config/token-context-mcp/repos.toml` | `<thư mục registry>/indexes/` |

`TOKEN_CONTEXT_CONFIG` ghi đè đường dẫn registry. Trên máy dùng chung, hãy đọc §4 trước khi trỏ nhiều tài khoản vào cùng một file.

---

## 2. Máy từ xa và SSH

### Quy tắc quyết định mọi thứ

Transport **chỉ có `stdio`**. Client khởi chạy server làm tiến trình con và nói JSON-RPC qua stdin/stdout; server đọc filesystem của chính máy nó được khởi chạy. Không có chặng mạng nào, nên **source và server bắt buộc nằm trên cùng một máy**. Server khởi chạy trên laptop Windows sẽ index cái laptop đó, bất kể cửa sổ editor đang kết nối tới đâu.

### VS Code Remote-SSH

VS Code quyết định MCP server chạy ở đâu dựa vào nơi đặt file cấu hình. **[theo tài liệu]**

| Nơi đặt cấu hình | Server chạy trên | Dùng được với source từ xa |
|---|---|---|
| User profile (`MCP: Open User Configuration`) | máy local | không |
| `.vscode/mcp.json` trong workspace nằm trên máy từ xa | máy từ xa | **có** |
| Remote user settings (`Remote [SSH: host]`) | máy từ xa | **có** |

Vậy: chạy `register`, `index` và `harden` từ **terminal trên server**, và đặt cấu hình vào workspace nằm trên server.

```json
{
  "servers": {
    "token-context": {
      "type": "stdio",
      "command": "/home/you/.local/bin/uv",
      "args": [
        "run", "--no-sync",
        "--directory", "/home/you/token-context-mcp",
        "token-context", "serve", "--transport", "stdio"
      ]
    }
  }
}
```

Hai chi tiết gây ra phần lớn lỗi khi chạy từ xa:

1. **Dùng `.vscode/mcp.json` với khoá `"servers"`**, không dùng `.mcp.json` ở gốc repo. VS Code trước 1.135.0 chuyển đổi đường dẫn workspace bằng `URI.fsPath`, nên `/opt/x` được gửi sang máy Linux thành `\opt\x` và spawn thất bại với `ENOENT`.
2. **Ghi `command` là đường dẫn tuyệt đối tới `uv`.** Server không được khởi chạy qua login shell, nên `~/.local/bin` thường không có trong `PATH`. Chạy `which uv` trên server rồi dán kết quả vào.

### Khởi chạy server qua SSH từ client local

`ssh` chuyển tiếp stdin và stdout nguyên vẹn, nên client local có thể khởi chạy thẳng server từ xa. **[theo tài liệu]**

```json
{
  "servers": {
    "token-context": {
      "type": "stdio",
      "command": "ssh",
      "args": ["myserver", "/home/you/.local/bin/uv run --no-sync --directory /home/you/token-context-mcp token-context serve --transport stdio"]
    }
  }
}
```

Cách này dùng được cả với **AWS SSM**, khi `~/.ssh/config` mang `ProxyCommand`; phía MCP vẫn chỉ thấy SSH thuần. Hai cái giá phải trả: mỗi lần khởi chạy server là một phiên SSH mới, và **bất kỳ banner hay MOTD nào in ra stdout đều làm hỏng luồng JSON-RPC** — kiểm tra bằng `ssh myserver true`, phải không in ra gì cả.

### Những gì không chạy được

- Agent trên cloud hoặc web không khởi chạy được server này. Chúng cần một dịch vụ MCP qua HTTP được triển khai riêng và có xác thực; dự án này cố ý chỉ ship `stdio` local.
- Đăng ký repository trên máy client không làm nó hiện ra với tiến trình server trên máy chủ.
- Index ổ Windows từ WSL (`/mnt/d/...`) thì chạy được nhưng snapshot không siết quyền được: DrvFs không mang mode POSIX.

---

## 3. Giới hạn

### Theo từng repository — đặt lúc đăng ký, sửa trong `repos.toml`

| Giới hạn | Mặc định | Điều gì xảy ra khi chạm ngưỡng |
|---|---:|---|
| `max_files` | 25.000 | `index` dừng với `repository exceeds max_files`; không ghi ra gì cả |
| `max_file_bytes` | 2.000.000 | File bị bỏ qua và được đếm vào `files_skipped` |
| `allow_symlinks` | `false` | Symlink và reparse point của Windows bị từ chối, cả khi duyệt cây lẫn khi tra cứu |

### Chính sách server — bảng `[server]`, áp dụng cho mọi request

| Khoá | Mặc định | Khoảng hợp lệ |
|---|---:|---|
| `max_request_bytes` | 1.048.576 | 1.024 – 1.048.576 |
| `max_result_tokens` | 8.192 | 32 – 8.192 |
| `max_graph_nodes` | 100 | 1 – 500 |
| `max_symbol_results` | 20 | 1 – 100 |

Giá trị nằm ngoài khoảng là lỗi cấu hình và server từ chối khởi động. 96 token của mỗi ngân sách được dành cho phần vỏ (envelope) của response, nên request 4.096 token chỉ được lấp tối đa 4.000 token nội dung.

### Phạm vi hỗ trợ

- **Ngôn ngữ được parse:** `.py`, `.pyi` (Python); `.js`, `.jsx` (JavaScript); `.ts` (TypeScript); `.tsx`.
- **Mọi đuôi file khác được ghi nhận nhưng không tìm kiếm được.** File Markdown, JSON, YAML hay TOML vẫn có một dòng trong bảng inventory với `parse_status: unsupported` — có hash và tham gia kiểm tra freshness — nhưng không sinh symbol hay edge, và **nội dung của nó không vào `search_source`**. **[đã kiểm chứng]** trên chính snapshot của repo này: ghi nhận 105 file, tìm kiếm được 48 file. Với văn bản thường, hãy dùng `rg`.
- **Định dạng `repo_id`:** `^[a-z][a-z0-9_-]{0,63}$`. Tool MCP chỉ nhận `repo_id`, không bao giờ nhận đường dẫn filesystem.
- **Không bao giờ index:** `.git`, `.hg`, `.svn`, `.ssh`, `.aws`, `.gnupg`, `__pycache__`, `.venv`, `venv`, `env`, `.env`, `node_modules`, `site-packages` và các thư mục cache thông thường; file tên `id_rsa`, `id_dsa`, `credentials`, `credentials.json`, `.npmrc`; đuôi `.pem`, `.key`, `.p12`, `.pfx`, `.kdbx`. Nội dung nhị phân được phát hiện và bỏ qua. `.gitignore` ở **gốc** repository được tôn trọng thêm bên trên đó; các file `.gitignore` lồng bên trong không được đọc.
- **Edge là kết quả từ vựng (lexical)**, không phải call graph đã phân giải. `get_impact_slice` trả về tập ứng viên kèm trạng thái `ambiguous`/`unresolved` cho từng edge, không phải một bằng chứng.

---

## 4. Quyền hạn và tính riêng tư

### Snapshot thực sự chứa gì

Snapshot lưu **nguyên văn thân hàm của source**, vì `search_source` và `get_symbol_context` phải trả về chúng. Nó là bản sao thứ hai của repository với bộ quyền riêng của nó — hãy coi nó là source, đừng coi là cache. Index không bao giờ được phép dễ đọc hơn chính repository sinh ra nó.

### POSIX (Linux, macOS)

Registry, snapshot, manifest và các file sidecar WAL của SQLite được tạo ra **chỉ chủ sở hữu đọc được**, thay vì thừa hưởng umask của tiến trình. **[đã kiểm chứng một phần]** — xác nhận trên Ubuntu 22.04 với `umask 0022`, mà nếu không có thay đổi này sẽ ra mode `0644`.

| Đường dẫn | Mode |
|---|---|
| `~/.config/token-context-mcp/` và `indexes/` | `0700` |
| `repos.toml`, `*.sqlite`, `*.sqlite-wal`, `*.sqlite-shm`, `*.manifest.json` | `0600` |

File do phiên bản cũ tạo ra vẫn giữ mode cũ. Sửa chúng bằng:

```bash
uv run token-context harden --check   # chỉ báo cáo, không sửa gì
uv run token-context harden           # áp dụng
```

Nếu `TOKEN_CONTEXT_CONFIG` trỏ tới nơi khác không phải thư mục `token-context-mcp`, `harden` chỉ siết đúng file registry và thư mục `indexes/` — nó sẽ không chmod một thư mục home hay thư mục dùng chung mà nó không sở hữu.

### Windows

Không có mode bit POSIX ở đây. `%APPDATA%` bình thường thừa hưởng một ACL chỉ cấp cho chủ sở hữu, `SYSTEM` và `Administrators` — nhưng công cụ khác có thể thêm một nhóm vào profile, và nhóm đó sau đó đọc được mọi snapshot. Cùng một lệnh sẽ kiểm tra ACL thay vì mode:

```powershell
uv run token-context harden --check
```

Nó liệt kê mọi principal ngoài chủ sở hữu, `SYSTEM` và `Administrators` trong `unexpected_principals`. Nếu bỏ `--check`, nó sẽ tắt kế thừa và cấp lại quyền cho đúng ba đối tượng đó. **Hãy tìm hiểu nhóm lạ đó dùng để làm gì trước khi gỡ** — nếu một tài khoản sandbox đang chạy MCP server, gỡ quyền của nó sẽ làm hỏng client đó.

### Máy nhiều người dùng

| Tình huống | Hệ quả | Nên làm gì |
|---|---|---|
| Mỗi người một tài khoản Linux | Registry và snapshot đã tách biệt sẵn | Chạy `harden` một lần |
| Nhiều người dùng chung một tài khoản | Chung một registry: `list_repositories` cho ai cũng thấy repo của mọi người, và các lần `index` đồng thời tranh nhau cùng một file SQLite | Cấp cho mỗi người một `TOKEN_CONTEXT_CONFIG` riêng trong cấu hình MCP của họ |
| `TOKEN_CONTEXT_CONFIG` trỏ vào đường dẫn chung | Cố ý gộp đăng ký và snapshot của nhiều người | Chỉ làm khi source đó ai cũng được phép đọc |

Trên máy Linux mặc định, người dùng khác nhìn thấy được **dòng lệnh** của tiến trình bạn qua `/proc`, nhưng không đọc được biến môi trường hay file descriptor của nó. Không bao giờ truyền secret cho MCP server bằng tham số dòng lệnh.

**Root, `SYSTEM` và local administrator đọc được các file này bất kể cấu hình thế nào.** Đó là đặc tính của hệ điều hành, không phải thứ công cụ này giữ lại được. Trên máy mà bạn không kiểm soát ở mức đó, đừng index repository không được phép lộ.

Index phải parse toàn bộ cây thư mục và ngốn nhiều CPU lẫn I/O. Trên máy dùng chung, hãy hẹn lịch chạy thay vì chạy giữa lúc người khác đang làm việc; riêng `serve` thì nhẹ.

### Những gì server không bao giờ làm

Không ghi file vào repository, không thực thi shell, không mở cổng HTTP, không gọi mạng ra ngoài, và không nhận đường dẫn filesystem tuỳ ý. `stdio` **không phải** là sandbox của hệ điều hành: nếu bạn cần một biên giới mạng được cưỡng chế, hãy áp đặt nó ở mức OS, container hoặc VM.

---

## 5. Danh sách kiểm tra

```bash
# Linux / macOS — chạy trên chính máy chứa source
uv run token-context register --repo-id myproj --root ~/code/myproj
uv run token-context index --repo-id myproj
uv run token-context status --repo-id myproj     # mong đợi "freshness": "fresh"
uv run token-context harden --check              # mong đợi "status": "compliant"
which uv                                         # dán kết quả này vào mcp.json
```

```powershell
# Windows
uv run token-context register --repo-id myproj --root D:\code\myproj
uv run token-context index --repo-id myproj
uv run token-context status --repo-id myproj
uv run token-context harden --check              # xem mục "unexpected_principals"
```

Nếu client không khởi chạy được server, trước hết hãy chạy tay đúng `command` và `args` trong cấu hình của bạn ở terminal. Việc đó tách bạch giữa một môi trường Python hỏng và một client không nạp cấu hình.
