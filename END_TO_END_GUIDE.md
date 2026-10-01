# END-TO-END GUIDE / HƯỚNG DẪN TOÀN DIỆN TỪ ĐẦU ĐẾN CUỐI

> **Token Context MCP (v0.2.0)** Master End-to-End Guide covering installation, Ollama Qwen setup, `.vscode/mcp.json` configuration, AST indexing, PySide6 Desktop GUI, and AI Assistant test prompts.

Vui lòng chọn ngôn ngữ bạn muốn xem / Please select your preferred language:

- 🇻🇳 **Tiếng Việt**: [`docs/end_to_end_guide/END_TO_END_GUIDE.vn.md`](docs/end_to_end_guide/END_TO_END_GUIDE.vn.md)
- 🇬🇧 **English**: [`docs/end_to_end_guide/END_TO_END_GUIDE.eng.md`](docs/end_to_end_guide/END_TO_END_GUIDE.eng.md)

---

### Quick Checklist:
1. **Install Package**: `pip install "token_context_mcp-0.2.0-py3-none-any.whl[gui]"`
2. **Setup Ollama & Qwen**: `ollama pull qwen2.5-coder:7b-instruct-q4_K_M` (hoặc `1.5b`)
3. **Register Codebase**: `token-context register --repo-id <id> --root <path>`
4. **Build AST Index**: `token-context index --all`
5. **Config VS Code**: Add `token-context` with `type: "stdio"`, `command: "token-context"`, `args: ["serve", "--output-mode", "text"]` to `.vscode/mcp.json`
6. **Launch GUI**: `token-context-gui`
7. **Verify Qwen**: `python -c "from token_context_mcp.sampling.hardware_probe import probe_hardware; print(probe_hardware().recommended_model)"`
