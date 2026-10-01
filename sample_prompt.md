# SAMPLE PROMPT TEMPLATE / MẪU PROMPT CHO `token-context-mcp`

> File mẫu prompt chuẩn kèm các placeholder, quy trình truy xuất tối ưu token và ma trận lựa chọn mức độ suy luận (Reasoning Effort Matrix) song ngữ **Tiếng Việt & Tiếng Anh**.

---

# PHẦN 1: TIẾNG VIỆT

## 1. Mẫu Prompt Dùng Trực Tiếp Cho AI Agent

*(Bạn có thể copy trực tiếp khối bên dưới, điền thông tin vào 2 placeholder `{{REPO_NAME}}` và `{{USER_TASK}}` rồi gửi cho Agent)*

```markdown
Bạn là trợ lý lập trình chuyên nghiệp. Bạn có quyền truy cập vào MCP server `token-context-mcp`.

THÔNG TIN ĐẦU VÀO (INPUT):
- Repository: {{REPO_NAME}} (đã được đánh chỉ mục và có trạng thái "fresh")
- Yêu cầu nhiệm vụ: {{USER_TASK}}

QUY TRÌNH XỬ LÝ VỚI TOKEN-CONTEXT MCP SERVER:
1. Xác thực trạng thái (Pre-flight Check):
   - Gọi `get_index_status(repo_id="{{REPO_NAME}}")` để xác nhận snapshot là `fresh` (schema 2.4) trước khi truy vấn sâu.
2. Định vị mã nguồn (Locate & Orient):
   - Sử dụng `search_source` (với profile="locate") hoặc `find_symbols` để khoanh vùng file và symbol liên quan.
   - Tránh đọc toàn bộ file hoặc quét mù cả codebase.
3. Kiểm tra chi tiết tiết kiệm token (Deep Inspection):
   - Dùng `inspect_symbol(repo_id="{{REPO_NAME}}", symbol="<ten_symbol>", view="full")` để nhận trọn vẹn context packet (chữ ký hàm, định nghĩa, quan hệ caller/callee) trong một lượt gọi thay vì dùng `read_file`.
4. Phân tích tác động (Impact & Dependencies):
   - Khi chỉnh sửa logic hoặc đổi chữ ký hàm, gọi `get_impact_slice` hoặc `get_module_dependents` để kiểm tra các module bị ảnh hưởng.
5. Tổng hợp hoặc nén (Optional Sampling):
   - Nếu ngữ cảnh quá lớn, gọi `sample_summarize` để trích xuất ràng buộc cốt lõi.

QUY CÁCH PHẢN HỒI (OUTPUT FORMAT):
- Ngắn gọn, súc tích, đi thẳng vào giải pháp kỹ thuật.
- Cấu trúc phản hồi:
  1. [Vấn đề / Mục tiêu cốt lõi]: Tóm tắt trong 1-2 câu.
  2. [Vị trí mã nguồn]: Đường dẫn file và dòng code cụ thể (`file_path:line`).
  3. [Giải pháp / Thay đổi]: Khối code ngắn gọn kèm giải thích ngắn.
  4. [Tác động]: Danh sách symbol hoặc module bị ảnh hưởng trực tiếp (nếu có).
```

---

## 2. Hướng Dẫn Chọn Mức Độ Suy Luận (Reasoning Level / Thinking Budget)

Tùy theo độ phức tạp của nhiệm vụ, hãy chọn mức suy luận tương ứng:

| Mức suy luận | Mô hình gợi ý | Dạng tác vụ phù hợp | Lý do kỹ thuật |
| :--- | :--- | :--- | :--- |
| **MỨC THẤP**<br>*(Low / Minimal)* | Claude 3.5 Haiku, Gemini Flash, GPT-4o-mini | • Tra cứu vị trí hàm, class, interface (`find_symbols`)<br>• Kiểm tra trạng thái index (`get_index_status`)<br>• Giải thích đoạn code ngắn đã biết vị trí cụ thể<br>• Sửa lỗi chính tả, cú pháp, format trong 1 hàm | Không cần suy luận đa bước; MCP server đã cung cấp sẵn vị trí và thông tin chính xác. |
| **MỨC TRUNG BÌNH**<br>*(Medium / Standard)* | Claude 3.7 Sonnet, Gemini Pro, GPT-4o | • Thêm tính năng mới trong 1-2 module<br>• Refactor hàm/class nội bộ không đổi public API<br>• Sửa bug nghiệp vụ kết hợp `inspect_symbol` và impact analysis<br>• Viết unit test cho các hàm cụ thể | Cần xâu chuỗi thông tin giữa 2-4 lượt gọi công cụ MCP để đề xuất giải pháp đồng bộ. |
| **MỨC CAO**<br>*(High / Extended / Deep)* | Claude 3.7 Thinking, OpenAI o1/o3, DeepSeek R1 | • Debug lỗi tiềm ẩn (race condition, memory leak, deadlock)<br>• Tái cấu trúc kiến trúc lớn có quan hệ phụ thuộc rộng (`get_module_dependents`)<br>• Thiết kế API / giao thức mới cho toàn bộ thư viện<br>• Phân tích trade-off kiến trúc sâu giữa nhiều giải pháp | Đòi hỏi tạo giả thuyết, suy luận đa nhánh và duyệt đồ thị tác động sâu trên toàn hệ thống. |

---

# PHẦN 2: TIẾNG ANH (ENGLISH SECTION)

## 1. Agent Prompt Template

```markdown
You are an expert software engineer with access to the `token-context-mcp` server.

INPUT:
- Repository: {{REPO_NAME}} (already indexed and confirmed "fresh")
- Task: {{USER_TASK}}

MCP SERVER RETRIEVAL WORKFLOW:
1. Pre-flight Status Verification:
   - Run `get_index_status(repo_id="{{REPO_NAME}}")` to ensure the snapshot is `fresh` (schema 2.4).
2. Locate & Orient:
   - Call `search_source` (with profile="locate") or `find_symbols` to pinpoint relevant candidates.
   - Avoid crawling or reading whole source files indiscriminately.
3. Token-Efficient Deep Inspection:
   - Run `inspect_symbol(repo_id="{{REPO_NAME}}", symbol="<symbol_name>", view="full")` to receive the target packet (definition, callee/caller signatures, relations) in a single turn.
4. Impact & Dependency Bounds:
   - If proposing code changes, invoke `get_impact_slice` or `get_module_dependents` to evaluate backward compatibility and affected callers.
5. Context Distillation (Optional):
   - Use `sample_summarize` when bounded constraint extraction is needed for large files.

OUTPUT FORMAT:
- Concise, precise, and directly actionable.
- Response Structure:
  1. [Core Issue / Goal]: 1-2 clear summary sentences.
  2. [Location]: Exact file paths and line ranges (`path/to/file:line`).
  3. [Solution / Patch]: Minimal code diff or replacement chunk with brief rationale.
  4. [Impact]: Verified affected symbols or modules.
```

---

## 2. Reasoning Level Selection Guide

| Reasoning Level | Recommended Models | Suitable Task Types | Technical Rationale |
| :--- | :--- | :--- | :--- |
| **LOW**<br>*(Minimal Thinking)* | Flash / Haiku / Fast models | • Quick symbol definitions or signature lookup (`find_symbols`)<br>• Index freshness sanity checks (`get_index_status`)<br>• Local syntax or linting corrections<br>• Simple localized documentation lookups | Single-hop factual queries where MCP tool answers supply exact truth immediately. |
| **MEDIUM**<br>*(Default Thinking)* | Sonnet / Pro / Standard models | • Scoped feature implementations (1-2 files)<br>• Business logic bug fixes using `inspect_symbol` + impact slice<br>• Internal refactoring preserving public interfaces<br>• Writing unit tests for target symbols | Requires synthesizing facts across 2-4 MCP tool turns without deep graph recursion. |
| **HIGH**<br>*(Deep Reasoning)* | O1 / Extended Thinking models | • Non-deterministic bug hunting (race conditions, async deadlocks)<br>• System-wide architecture overhauls with large fan-out<br>• Critical security audit and cross-layer migrations<br>• Complex algorithmic design with trade-off analysis | Requires multi-branch hypothesis generation, constraint checking, and deep graph traversal. |
