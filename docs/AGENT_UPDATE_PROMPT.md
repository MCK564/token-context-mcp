# HƯỚNG DẪN CẬP NHẬT VÀ SỬA LỖI CI CHO REPO `token-context-mcp`
*(Dành cho AI Coding Agent làm việc từ bản snapshot/zip cũ)*

---

## 1. Bối cảnh & Mục tiêu

Tài liệu này đóng gói toàn bộ hướng dẫn chỉ thị (prompt & plan) cho một agent tiếp nhận codebase `token-context-mcp` từ một bản snapshot hoặc file zip cũ (từ 2 commit trước: `86cea21` hoặc `a88a693`).

Nhiệm vụ của agent là đồng bộ hóa toàn diện codebase lên phiên bản mới nhất và xử lý dứt điểm lỗi GitHub Actions CI:
1. **Bổ sung Composite Retrieval (`inspect_symbol`) & Token Efficiency** (commit `a88a693`).
2. **Bộ Cẩm nang Multi-Agent Routing Song ngữ** trong `docs/handbook/` (commit `8ac6938`).
3. **Sửa dứt điểm lỗi Clean-room Wheel Smoke Test** trong CI (`evals/stdio_smoke.py` và tài liệu setup - commit `aa70e6e`).

---

## 2. Chi tiết lỗi GitHub Actions CI cần khắc phục

### Nhật ký lỗi CI thực tế:
```text
2026-09-17T04:15:33.3340729Z subprocess.run([str(artifact_python), "evals/stdio_smoke.py"], check=True)
...
AssertionError: expected 9 tools, got 10: ['find_symbols', 'get_file_skeleton', 'get_impact_slice', 'get_index_status', 'get_module_dependents', 'get_repo_map', 'get_symbol_context', 'inspect_symbol', 'list_repositories', 'search_source']
subprocess.CalledProcessError: Command '['artifact-venv/bin/python', 'evals/stdio_smoke.py']' returned non-zero exit status 1.
##[error]Process completed with exit code 1.
```

### Nguyên nhân:
- Khi commit `a88a693` bổ sung công cụ thứ 10 (`inspect_symbol`), file kiểm thử `tests/test_server.py` đã cập nhật danh sách 10 công cụ.
- Tuy nhiên, kịch bản smoke test độc lập `evals/stdio_smoke.py` (dùng để kiểm tra file `.whl` sau khi đóng gói) vẫn giữ assertion `len(names) != 9`.
- Đồng thời các file `docs/SETUP.en.md` và `docs/SETUP.vi.md` vẫn còn ghi nhận 9 công cụ ở các hướng dẫn kiểm tra kết nối với Claude Code, VS Code Copilot và Antigravity.

---

## 3. Danh sách các thay đổi cần áp dụng

### PHẦN 1: Sửa mã nguồn Smoke Test (`evals/stdio_smoke.py`) [BẮT BUỘC ĐỂ PASS CI]
Thay thế assertion kiểm tra độ dài bằng việc đối chiếu chính xác bộ 10 công cụ đã đăng ký:

```python
EXPECTED_TOOLS = {
    "list_repositories",
    "get_repo_map",
    "find_symbols",
    "get_module_dependents",
    "search_source",
    "get_file_skeleton",
    "get_symbol_context",
    "get_impact_slice",
    "get_index_status",
    "inspect_symbol",
}


async def _run() -> None:
    command = _console_script()
    with tempfile.TemporaryDirectory(prefix="token-context-smoke-") as directory:
        config = Path(directory) / "repos.toml"
        parameters = StdioServerParameters(
            command=command,
            args=["serve", "--transport", "stdio", "--config", str(config)],
        )
        async with Client(stdio_client(parameters)) as client:
            tools = await client.list_tools()
            names = {tool.name for tool in tools.tools}
            if names != EXPECTED_TOOLS:
                raise AssertionError(
                    f"expected {len(EXPECTED_TOOLS)} tools ({sorted(EXPECTED_TOOLS)}), got {len(names)}: {sorted(names)}"
                )
```

---

### PHẦN 2: Cập nhật tài liệu Setup (`docs/SETUP.en.md` & `docs/SETUP.vi.md`)
Đồng bộ các vị trí nhắc đến số lượng công cụ từ 9 lên 10:
- `docs/SETUP.en.md`:
  - Dòng 153: `The token-context server must appear with 10 tools.`
  - Dòng 203: `tools/list returned all 10 tools.`
  - Dòng 247: `token-context must appear with 10 tools.`
- `docs/SETUP.vi.md`:
  - Dòng 149: `Server token-context phải hiện với 10 tool.`
  - Dòng 199: `tools/list trả về đủ 10 tool.`
  - Dòng 243: `token-context phải xuất hiện kèm 10 tool.`

---

### PHẦN 3: Mã nguồn Composite Retrieval & Token Efficiency (nếu snapshot thiếu)
Đảm bảo các file sau đã hiện diện và đầy đủ:
1. `src/token_context_mcp/server.py`:
   - Khai báo tool thứ 10: `@server.tool(title="Inspect symbol (composite)")` gọi `workflow_engine.inspect_symbol(...)`.
2. `src/token_context_mcp/retrieve/workflows.py`:
   - Class `WorkflowEngine` thực hiện composite single-turn retrieval.
3. `src/token_context_mcp/retrieve/projection.py`:
   - Bộ lọc thuộc tính và thu gọn payload theo preset (`minimal`, `normal`, `full`).
4. `src/token_context_mcp/retrieve/serialization.py`:
   - Compact serializer tối ưu hóa token.
5. `src/token_context_mcp/retrieve/context.py`:
   - Dataclass quản lý ngữ cảnh và xuất xứ bằng chứng (`EvidenceRef`).
6. Các file test: `tests/test_server.py` và `tests/test_token_efficiency.py`.

---

### PHẦN 4: Bộ Cẩm Nang Multi-Agent Routing (`docs/handbook/`)
Cấu trúc 21 file tài liệu và contract templates:
```text
docs/handbook/
├── CAPABILITY_MATRIX.md                  # So sánh Host, SDK, LangGraph, Gateway
├── SOURCE_REGISTER.md                    # Danh mục nguồn tài liệu và căn cứ lý thuyết
├── BILINGUAL_PARITY.md                   # Bảng đối chiếu thuật ngữ EN/VI & tính bất biến của schema
├── templates/
│   ├── task-spec.example.json            # TaskSpec schema mẫu
│   ├── worker-result.example.json        # WorkerResult schema mẫu
│   ├── route-policy.example.json         # RouteDecision & Routing policy mẫu
│   └── budget-ledger.example.json        # Sổ cái ngân sách & UsageEvent mẫu
├── recipes/
│   ├── manual.{en,vi}.md                 # R01 (Audit repo), R02 (Bỏ qua LLM, dùng tool)
│   ├── hybrid.{en,vi}.md                 # R03 (Chạy song song theo lô), R04 (Chuỗi DAG phụ thuộc)
│   ├── automatic.{en,vi}.md              # R05 (Từ chối định tuyến mơ hồ), R06 (Worker hỏng & Escalation)
│   ├── gateway.{en,vi}.md                # R07 (Chuyển đổi dự phòng lỗi 429/timeout)
│   └── troubleshooting.{en,vi}.md        # R08-R12 (Hết ngân sách, stale index, crash resume, v.v.)
├── evaluation/
│   ├── PROTOCOL.{en,vi}.md               # Giao thức đánh giá & công thức hạch toán all-attempt
├── MULTI_AGENT_ROUTING.en.md             # Master Handbook tiếng Anh (15 chương H01-H15)
└── MULTI_AGENT_ROUTING.vi.md             # Master Handbook tiếng Việt (15 chương H01-H15)
```

---

## 4. Các bước nghiệm thu bắt buộc (Verification Commands)

Agent sau khi áp dụng các thay đổi trên **phải chạy và vượt qua 100%** các bước kiểm tra sau:

### 1. Chạy bộ unit tests:
```bash
uv run pytest
```
*Kết quả yêu cầu: `66 passed, 4 skipped` (hoặc 100% pass, không có lỗi).*

### 2. Chạy smoke test trực tiếp:
```bash
uv run python evals/stdio_smoke.py
```
*Kết quả yêu cầu: Thoát với exit code 0 mà không văng `AssertionError`.*

### 3. Mô phỏng đúng quy trình Clean-room Wheel của GitHub Actions CI:
```bash
uv build
python -c "
import pathlib, subprocess, sys, shutil

root = pathlib.Path('artifact-venv')
if root.exists():
    shutil.rmtree(root)

subprocess.run([sys.executable, '-m', 'venv', str(root)], check=True)
artifact_python = root / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
artifact_command = root / ('Scripts/token-context.exe' if sys.platform == 'win32' else 'bin/token-context')
wheel = next(pathlib.Path('dist').glob('*.whl'))
subprocess.run([str(artifact_python), '-m', 'pip', 'install', str(wheel)], check=True)
subprocess.run([str(artifact_python), '-c', 'import token_context_mcp, token_context_mcp.security'], check=True)
subprocess.run([str(artifact_command), '--version'], check=True)
subprocess.run([str(artifact_python), 'evals/stdio_smoke.py'], check=True)
print('>>> CLEAN-ROOM WHEEL CI SIMULATION: SUCCESS! <<<')
"
```
*Kết quả yêu cầu: In ra dòng `>>> CLEAN-ROOM WHEEL CI SIMULATION: SUCCESS! <<<` và exit code 0.*
