# Video #08 — Drawbridge: Hỏi-đáp AI cho bản vẽ

**⭐ TOP DEMO VIDEO** — second highest-traffic clip in landing page.

* **Mục tiêu**: Người xem hiểu Drawbridge cho engineer trẻ trả lời
  câu hỏi từ bản vẽ trong vài giây + có trích dẫn.
* **Đối tượng**: Engineer thiết kế, PM, BIM lead
* **Thời lượng**: 180 giây (3 phút)
* **Setup**:
  * Project mẫu đã upload 4 PDF:
    - "A-Series-Architecture.pdf" (kiến trúc, 12 trang)
    - "S-Series-Structure.pdf" (kết cấu, 8 trang)
    - "M-Series-MEP.pdf" (MEP, 18 trang)
    - "Thuyet-minh-thiet-ke.pdf" (thuyết minh, 24 trang)
  * Tất cả status="Sẵn sàng" trên `/drawbridge/documents`
  * Quota AI đầy

## Shot list

### Shot 1 (0-15s) — Hook

**Visual**: Picture-in-picture: tay engineer trẻ ngồi văn phòng,
2 màn hình mở, đang scroll PDF bản vẽ. Voice over qua slide:

> "Bộ bản vẽ + thuyết minh dự án thường 200-500 trang. Engineer
> trẻ trong team mất 30-60 phút để tìm 1 thông số đơn lẻ — độ
> dày sàn, vị trí phòng kỹ thuật, công suất HVAC."

Cut to laptop screen, mở `/drawbridge/query`.

### Shot 2 (15-30s) — Chọn dự án

**Visual**: Project picker dropdown → chọn "Chung cư Tân Hòa
25 tầng". Empty state hiển thị 4 suggested-opener pill:
* "Bản vẽ này có bao nhiêu lối thoát hiểm?"
* "Tổng chiều dài hệ thống đường ống ngầm bao nhiêu?"
* "Thông số kỹ thuật của thang máy là gì?"
* "Có mấy phòng kỹ thuật điện trên mặt bằng tầng 1?"

**Narration**:
> "Đầu tiên chọn dự án. Trợ lý sẽ trả lời từ kho bản vẽ + thuyết
> minh của dự án này — không lẫn dự án khác."

### Shot 3 (30-50s) — Câu hỏi đầu tiên

**Visual**: Click suggested-opener "Bản vẽ M2 ghi độ dày sàn
tầng 3 là bao nhiêu?". Bubble user xuất hiện bên phải.

Bubble assistant bên trái thinking dots ("Đang đọc bản vẽ..."
khoảng 4s).

Sau đó câu trả lời typing animation chữ-from-chữ:
> "Độ dày sàn tầng 3 là **180mm** theo bản vẽ kết cấu [1].
> Đây là sàn bê tông cốt thép thông thường cho công năng dân
> dụng 25 tầng, đảm bảo TCVN 5574:2018 mục 6.4."

Chip `[1]` blue circle inside the text.

**Narration**:
> "Hỏi tự nhiên bằng tiếng Việt. Trợ lý đọc bản vẽ + thuyết minh,
> trả lời trong vài giây với trích dẫn rõ ràng. Số `[1]` là chip
> click được."

### Shot 4 (50-75s) — Hover citation chip

**Visual**: Cursor hover chip `[1]`. Popover hiển thị:
* Drawing number "S-201" + page 4
* Excerpt: "Cấu tạo sàn tầng điển hình — bê tông M250, thép phi 12 a200,
  chiều dày sàn 180mm…"

**Narration**:
> "Hover số [1] để xem nguồn — trích đoạn từ bản vẽ S-201 trang 4.
> Click chip để mở thẳng tài liệu gốc. Không phải scroll PDF tay."

### Shot 5 (75-105s) — Câu hỏi follow-up

**Visual**: Sau khi câu trả lời thứ nhất xong, dưới có pills
"Câu hỏi liên quan":
* "Vật liệu sàn các tầng còn lại?"
* "Có dự phòng tải trọng cho thang máy không?"
* "Chiều dày cột tầng điển hình?"

Click pill thứ ba.

Câu trả lời mới (stream):
> "Cột tầng điển hình kích thước **600×600mm** [1], bê tông M300
> [2], cốt thép thông qua được tính toán theo tải trọng cộng dồn
> từ tầng 25 xuống tầng 1 [3]…"

3 citation chips.

**Narration**:
> "Câu trả lời thứ nhất sinh ra câu hỏi tiếp theo. Click follow-up,
> trợ lý tiếp tục trả lời — multi-turn, có trích dẫn riêng cho mỗi
> số."

### Shot 6 (105-130s) — Mở Citations Panel

**Visual**: Sau khi câu thứ hai stream xong, click "3 nguồn tham
chiếu" expandable details. Panel mở ra hiển thị:
* `[1] S-201 Page 7 — Architecture: kích thước cột tầng điển hình`
* `[2] Thuyet-minh trang 12 — Vật liệu bê tông M300...`
* `[3] S-105 Page 2 — Tải trọng cộng dồn tính toán theo TCVN 2737`

Mỗi cái có discipline tag (kiến trúc / kết cấu) + excerpt 2-3 dòng.

**Narration**:
> "Hoặc xem TẤT CẢ nguồn tham chiếu cùng một lúc. Mỗi nguồn có
> discipline tag, drawing number, page, và trích đoạn — bạn
> verify nhanh trước khi trust câu trả lời AI."

### Shot 7 (130-160s) — Câu hỏi phức tạp cross-discipline

**Visual**: Gõ vào ô compose:
> "Trên mặt bằng tầng hầm 1, có conflict nào giữa hệ MEP và kết
> cấu không?"

Submit. Thinking 6s. Câu trả lời:
> "Tôi phát hiện **1 conflict tiềm năng**: ống điều hoà trục Y-12
> đi qua dầm chính kết cấu B-8 [1, 2]. Đường ống cao 600mm + dầm
> dày 700mm = clearance còn 300mm dưới trần — dưới mức 400mm
> tiêu chuẩn cho thi công bảo dưỡng."

3 citation chips spanning MEP + kết cấu.

**Narration**:
> "Câu hỏi phức tạp xuyên discipline — trợ lý kết hợp MEP + kết
> cấu, phát hiện conflict. Đây là loại bug thường bỏ sót khi
> review thủ công."

### Shot 8 (160-180s) — CTA outro

**Visual**: Fade to outro slide:
* Logo AEC + tagline
* "Drawbridge — 1 trong 17 module"
* URL `app.aec-platform.vn/drawbridge`
* CTA "Dùng thử 30 ngày miễn phí"

**Narration**:
> "Drawbridge cho engineer trẻ năng suất bằng engineer 5 năm
> kinh nghiệm. Đăng ký dùng thử tại app.aec-platform.vn. Video
> tiếp theo: BidRadar — Săn gói thầu tự động."

## Captions tiếng Việt + tiếng Anh

Drawbridge là module dễ xuất khẩu nhất — engineer FDI thường
nói tiếng Anh. Quay cả VN narration version cho local market
+ EN dubbed version cho Samsung/LG/Foxconn pitches.

## Mistakes to avoid

❌ **Đừng hỏi câu trả lời chính xác không có trong data demo** —
AI sẽ hallucinate hoặc abstain. Quay câu hỏi đã test pre-recording.

❌ **Đừng để typing animation lê thê** — 4 chars per tick × 18ms
là mặc định, nhưng câu dài có thể edit tăng tốc x2 trong post.

✅ **Show 1 conflict thật cross-discipline** — đây là "AHA" moment
cho engineer khán giả. Đảm bảo conflict sample có bbox dữ liệu
đủ để demo tốt.
