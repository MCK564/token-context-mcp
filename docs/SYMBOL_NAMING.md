# Quy ước đặt tên Symbol JavaScript / TypeScript (M12)

Tài liệu này chuẩn hóa quy ước tạo và đặt tên symbol cho các hàm, method gán qua prototype và object trong JavaScript/TypeScript.

## 1. Các mẫu gán method qua `prototype`

1. **Gán trực tiếp vào prototype:**
   ```javascript
   X.prototype.m = function (...) { ... }
   X.prototype.m = (...) => { ... }
   ```
   - **Tên qualified:** `X.m`
   - **Kind:** `method`
   - **Span:** Bao phủ toàn bộ câu lệnh gán (`expression_statement`).
   - **Signature:** Trích xuất từ tham số của hàm được gán.

2. **Gán object literal vào prototype:**
   ```javascript
   X.prototype = {
     m() {},
     n: function () {},
     k: () => {}
   }
   ```
   - **Tên qualified:** `X.m`, `X.n`, `X.k`
   - **Kind:** `method`
   - **Span:** Cặp `pair` hoặc `method_definition` tương ứng trong object.

3. **Định nghĩa qua `Object.defineProperty` / `Object.defineProperties`:**
   ```javascript
   Object.defineProperty(X.prototype, 'p', { get() { ... } })
   Object.defineProperties(X.prototype, { p: { get() { ... } } })
   ```
   - **Tên qualified:** `X.p`
   - **Kind:** `method`
   - **Signature:** Ghi nhận getter/setter.

## 2. Các mẫu gán method vào Object & Constructor

4. **Gán method vào object cấp module:**
   ```javascript
   X.m = function (...) { ... }
   ```
   (với `X` là identifier được khai báo ở cấp module)
   - **Tên qualified:** `X.m`
   - **Kind:** `method`

5. **Gán vào `this` trong hàm khởi tạo (Constructor function):**
   ```javascript
   function X() {
     this.m = function (...) { ... }
   }
   ```
   - **Tên qualified:** `X.m`
   - **Kind:** `method`

6. **Object literal cấp module:**
   ```javascript
   const res = {
     send() { ... }
   }
   res.send = function (...) { ... }
   ```
   - **Tên qualified:** `res.send`
   - **Kind:** `method`

## 3. Module Exports (CommonJS)

7. **Gán vào `module.exports` hoặc `exports`:**
   ```javascript
   module.exports.m = function (...) { ... }
   exports.m = function (...) { ... }
   module.exports = { m() {} }
   ```
   - **Tên qualified:** `m` (hàm cấp module)
   - **Kind:** `function`

## 4. Quy tắc loại trừ

- **Không tạo symbol cho thuộc tính dữ liệu (non-function values):**
  Ví dụ: `X.prototype.count = 0` không tạo symbol.
- **Trùng tên (Overload/Re-assignment):**
  Nếu có nhiều phép gán cho cùng `X.m`, giữ cả hai bản ghi như overload để bảo toàn ngữ cảnh tra cứu.
