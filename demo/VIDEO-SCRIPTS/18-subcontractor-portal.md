# Video #18 — Cổng nhà thầu phụ (SubcontractorPortal)

**⭐ NEW MODULE** — feature spotlight cho launch tuần này.

* **Mục tiêu**: Người xem hiểu module mới: tổng thầu mint token,
  sub xem assignments + báo tiến độ qua public portal, không cần
  Supabase login.
* **Đối tượng**: PM tổng thầu + GĐ nhà thầu phụ (B2B2C value)
* **Thời lượng**: 150 giây (2.5 phút)
* **Setup**:
  * Dự án "Tòa nhà văn phòng Đông Nam" đã có 3 sub grants tồn tại
    (active)
  * 1 sub "Cty TNHH Cơ Điện Phú Mỹ" có 4 assignment ở các status
    khác nhau
  * 2 màn hình cùng quay: admin browser + sub browser (mở incognito)

## Shot list

### Shot 1 (0-15s) — Pain point hook

**Visual**: Slide đen, text trắng:
> "Tổng thầu thuê 5-20 nhà thầu phụ. Liên lạc qua Zalo / email / điện
> thoại. Tổng thầu KHÔNG biết sub đang ở đâu trong nhiệm vụ —
> sub KHÔNG có 1 chỗ tập trung xem việc của mình."

Cut to admin browser (PM logged in).

### Shot 2 (15-30s) — Tạo grant mới

**Visual**: Navigate đến `/pulse/{project_id}` → tab "Subcontractors"
(hoặc dropdown). Click "Mời nhà thầu phụ".

Form mở ra:
* Tên: "Cty TNHH Cơ Điện Phú Mỹ"
* Email: "phumy@example.vn"
* SĐT: "0987-654-321"
* TTL: 365 ngày

Submit → modal hiện ra:
```
Cổng truy cập đã tạo ✓

URL: https://app.aec-platform.vn/subcontractor?t=eyJh...
[Copy URL]

⚠ Đây là lần duy nhất bạn xem được token này.
   Sao chép URL ngay và gửi cho nhà thầu phụ qua Zalo/SMS.
```

**Narration**:
> "Tổng thầu mint 1 cổng truy cập cho mỗi nhà thầu phụ — chỉ cần
> tên + email + số điện thoại. URL portal được tạo ngay. Bấm
> Copy, dán vào Zalo gửi cho sub."

### Shot 3 (30-50s) — Gán nhiệm vụ

**Visual**: Modal đóng. Quay lại danh sách grants — row mới
"Cty TNHH Cơ Điện Phú Mỹ" có "0 nhiệm vụ".

Click row → vào trang gán nhiệm vụ. Bấm "+ Thêm nhiệm vụ":
* Title: "Lắp đặt hệ thống điện tầng 5-8"
* Description: "Bao gồm chiếu sáng, ổ cắm, hệ thống thông tin"
* Contract value: 1.250.000.000 ₫
* Planned start: 01/06/2026
* Planned finish: 15/08/2026

Save. Lặp lại nhanh thêm 3 nhiệm vụ nữa (cuts).

**Narration**:
> "Gán scope of work cụ thể: title, mô tả, giá trị hợp đồng, ngày
> dự kiến. Mỗi sub có thể có 1-20 nhiệm vụ trên dự án."

### Shot 4 (50-80s) — Sub mở portal

**Visual**: Cut to incognito browser. Paste URL có token vào address
bar. Trang portal load.

Header:
* "CTY XÂY DỰNG ABC" (tổng thầu) - in nhỏ
* "Tòa nhà văn phòng Đông Nam" - in to
* "phumy@example.vn" badge xanh

Danh sách 4 nhiệm vụ với title + giá trị + ngày + status pill +
slider progress.

**Narration**:
> "Sub mở URL trên điện thoại — không cần đăng ký, không cần
> Supabase login. Token IS the auth. Họ thấy tên dự án, tên tổng
> thầu, và 4 nhiệm vụ của mình."

### Shot 5 (80-110s) — Sub báo tiến độ

**Visual**: Sub click vào nhiệm vụ thứ nhất "Lắp đặt hệ thống điện
tầng 5-8". Progress form expand:
* Slider drag từ 0 → 45%
* Dropdown status: "in_progress" → "Đang thi công"
* Note: "Đã hoàn thành tầng 5, đang lắp tầng 6. Tuần sau bắt đầu
  tầng 7."
* Save button.

Click save. "✓ Đã lưu" green badge xuất hiện.

**Narration**:
> "Sub kéo slider phần trăm, chọn trạng thái, nhập ghi chú. Save.
> Cập nhật tức thì — tổng thầu thấy ngay."

### Shot 6 (110-130s) — Admin thấy update

**Visual**: Cut back to admin browser. Refresh trang gán nhiệm vụ.
Row "Lắp đặt hệ thống điện tầng 5-8" giờ hiển thị:
* 45% (was 0%)
* status "Đang thi công" (was "Chưa bắt đầu")
* "Cập nhật cuối: 13:42 hôm nay"
* Sub note hiển thị inline

**Narration**:
> "Tổng thầu refresh — thấy update từ sub trong vài giây. Tên
> nhiệm vụ, % hoàn thành, ghi chú của sub. Không cần Zalo, không
> cần follow-up phone call."

### Shot 7 (130-150s) — CTA outro

**Visual**: Outro slide:
* "SubcontractorPortal — module mới #17"
* "Tổng thầu mint token. Sub truy cập qua URL. Cập nhật tức thì."
* URL `app.aec-platform.vn/subcontractors`
* CTA "Tất cả 17 module trên gói Khởi đầu miễn phí"

**Narration**:
> "SubcontractorPortal — module #17 của AEC Platform, đặc biệt
> giải quyết pain point tổng thầu VN. Đăng ký miễn phí tại
> app.aec-platform.vn. Hẹn gặp các anh chị video tiếp theo."

## Captions tiếng Việt

Đặc biệt:
* "nhà thầu phụ" (NCP) — viết tắt phổ biến nhưng không dùng trong
  narration, giữ "nhà thầu phụ" trọn chữ
* "tổng thầu" — không "tổng thầu chính" (redundant)
* "token" — giữ nguyên tiếng Anh, là technical term

## Mistakes to avoid

❌ **Đừng show full token in URL bar** — pixelate / blur the JWT
phần `eyJ...` sau dấu `=`. Token leak từ video YouTube = real
security incident.

❌ **Đừng chạy 2 sessions cùng IP** — sub side phải là incognito
hoặc khác browser hoàn toàn, để chứng minh "không cần login".

✅ **Cuts nhanh giữa admin/sub view** — viewer cần thấy "real-time"
feel, không phải đợi 5s mỗi cut.

✅ **Highlight pixel ngay khi admin refresh** — flash màu để xác
nhận "đã update". Đây là magic moment của module này.
