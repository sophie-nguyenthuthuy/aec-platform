# Drawbridge — Hỏi bản vẽ

Trợ lý AI trả lời câu hỏi từ kho **bản vẽ kỹ thuật + thuyết minh
+ schedule** đã upload cho mỗi dự án. Mọi câu trả lời có **trích
dẫn về tài liệu nguồn** — không phải hallucination.

URL: `/drawbridge`

## Use cases

- "Bản vẽ M2 ghi độ dày sàn tầng 3 là bao nhiêu?"
- "Liệt kê toàn bộ vật liệu thép trong schedule kết cấu."
- "Phòng kỹ thuật điện trên mặt bằng tầng hầm 1 ở đâu?"
- "Cọc bê tông ly tâm dùng cho công trình có thông số gì?"
- "Phát hiện xung đột giữa hệ thống MEP và kết cấu trên trục E-12."

## Upload tài liệu

URL: `/drawbridge/documents` → bấm **"+ Upload tài liệu"**.

Hỗ trợ:
- **PDF bản vẽ** (mọi tỷ lệ; OCR tự chạy nếu là PDF scan)
- **Thuyết minh DOCX / PDF**
- **Schedule XLSX** (bóc tách thành các dòng riêng)
- **Hình ảnh JPG/PNG** (cần OCR)

Khi upload, bạn chọn:
- **Dự án** áp dụng
- **Discipline** (kiến trúc / kết cấu / MEP / phòng cháy / cấp
  thoát nước / …)
- **Drawing number** (vd: A-101, S-201, M-301)
- **Tên + revision**

Sau khi upload, **worker xử lý nền** (~30-60 giây cho PDF 10-trang):
- Chunk text từ trang
- Embed mỗi chunk (Gemini embedding-001 768-dim)
- Index vào pgvector
- Quét title block OCR để verify drawing number

Khi xong, trạng thái tài liệu chuyển từ **"Đang xử lý"** sang
**"Sẵn sàng"** trên `/drawbridge/documents`.

## Hỏi Q&A

URL: `/drawbridge/query`

1. Chọn dự án ở thanh trên.
2. Gõ câu hỏi vào ô soạn (Enter để gửi, Shift+Enter xuống dòng).
3. Trợ lý hiển thị **"Đang đọc bản vẽ…"** rồi trả lời từng phần
   (typing animation cho cảm giác streaming).

Câu trả lời có:
- **Câu chữ chính** với số `[1]`, `[2]` xen vào.
- **Chip xanh tròn nhỏ** = trích dẫn. Hover để xem preview trích
  đoạn nguồn; click để jump đến tài liệu gốc.
- **Panel "X nguồn tham chiếu"** ở dưới — mở rộng để xem **toàn
  bộ excerpt** + discipline tag + số trang.
- **Câu hỏi liên quan** (pill xanh) — click để hỏi tiếp mà không
  cần gõ lại.

### Lọc theo discipline

Khi câu hỏi đặc thù cho một ngành (vd: chỉ MEP), thêm `disciplines`
trong API call. UI hiện tại không expose filter này — sắp tới
sẽ có dropdown bên cạnh ô search.

## Quét xung đột (Conflict scan)

URL: `/drawbridge/conflicts` → bấm **"Quét xung đột mới"**.

Hệ thống chạy AI để **so chéo các bản vẽ** tìm xung đột:
- Tường kiến trúc đi qua hệ MEP
- Cao độ trần phòng làm việc thấp hơn ống điều hoà
- Vị trí cột kết cấu trên schedule khác mặt bằng
- ...

Mỗi xung đột có **severity** (critical/major/minor) + 2 excerpt
từ 2 bản vẽ liên quan. Click vào conflict → xem panel chi tiết
+ markup vị trí nếu có toạ độ bbox.

## Khắc phục lỗi thường gặp

**"Câu trả lời không có trích dẫn"** → tài liệu chưa được ingest
xong (status "Đang xử lý") hoặc chunk hết embedding quota. Kiểm
tra trạng thái ở `/drawbridge/documents` và `/codeguard/quota`.

**"Trả lời sai số"** → kiểm tra trích dẫn nguồn (click chip [N])
— có thể OCR đọc nhầm chữ số trên bản vẽ scan kém. Reupload bản
vẽ PDF chất lượng tốt hơn.

**"Không tìm thấy schedule"** → schedule XLSX cần upload riêng,
không tự bóc từ PDF.

## Best practices

1. **Đặt drawing_number nhất quán** (A-101, S-201, M-301…) — giúp
   trích dẫn của AI dễ đọc với người dùng.
2. **Upload thuyết minh kỹ thuật** kèm bản vẽ — AI dùng cả hai
   để cross-reference.
3. **Re-upload bản revision mới** với cùng drawing_number — hệ
   thống tự đánh dấu "outdated" cho rev cũ; chỉ rev mới được dùng
   trong Q&A.
4. **Đặt câu hỏi cụ thể**: "Trên bản A-101 ghi chiều cao trần
   tầng 3 là?" tốt hơn "Trần cao bao nhiêu?".
