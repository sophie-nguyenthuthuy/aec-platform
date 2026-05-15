# SiteEye — Giám sát công trường AI

Chụp ảnh công trường từ điện thoại → AI phân tích **bảo hộ lao động
(PPE)**, **đếm người**, **phát hiện điều kiện không an toàn**, sinh
**báo cáo tiến độ + an toàn** tự động.

URL: `/siteeye`

## Quy trình giám sát hàng ngày

### Bước 1 — Cài app PWA lên điện thoại (1 phút)

Trên Android Chrome: vào `app.aec-platform.vn` → đợi banner **"Cài
AEC Platform về máy"** xuất hiện ở dưới → bấm **"Cài đặt"** → app
xuất hiện trên màn hình chính.

Trên iOS Safari: bấm nút **Share → Add to Home Screen**.

### Bước 2 — Tạo lượt giám sát (Visit)

1. Mở app từ màn hình chính.
2. Sidebar → **SiteEye → "Tạo lượt giám sát"**.
3. Chọn dự án + ngày + thợ giám sát.
4. App tự GPS-tag location.

### Bước 3 — Chụp / upload ảnh

Mở visit vừa tạo → **"Chụp ảnh"** → mở camera điện thoại → chụp.
Hoặc **"Upload từ máy ảnh"** nếu bạn dùng máy ảnh chuyên dụng.

Mỗi ảnh tự tag:
- Visit ID
- GPS toạ độ
- Timestamp
- Thợ giám sát

Tốt nhất chụp 10-30 ảnh cho mỗi lượt: tổng quan + góc khuất +
hạng mục đang thi công + thiết bị an toàn.

### Bước 4 — Worker phân tích AI (~30s/ảnh)

Worker chạy nền (`photo_analysis_job`) sẽ:
1. Tải ảnh từ MinIO storage.
2. Gọi YOLOv8 detection model (Ray Serve).
3. Phát hiện:
   - **Mũ bảo hộ** (helmet) — đếm số người có/không có
   - **Áo phản quang** (high-vis vest)
   - **Giày bảo hộ** (safety boots)
   - **Dây an toàn cao** (harness — khi làm việc trên cao)
   - **Điều kiện không an toàn** (giàn giáo lỗi, cản trở thoát hiểm)
4. Ghi vào DB → trạng thái ảnh chuyển từ **"Đang phân tích"** sang
   **"Đã phân tích"**.

### Bước 5 — Xem báo cáo

Vào `/siteeye/visits/{visit_id}`:
- **KPI**: số ảnh, số người phát hiện, tỷ lệ PPE đúng quy định,
  số incident phát hiện.
- **Grid ảnh** với overlay bounding box từ YOLO — click ảnh để
  zoom.
- **Danh sách incident** — mỗi cái có severity (high/medium/low),
  loại (no_helmet, no_vest, …), ảnh nguồn, timestamp.

## Báo cáo tuần khách hàng tự động

Sau khi có vài lượt visit trong tuần, worker `weekly_report_job`
(chạy mỗi thứ Hai 06:00 UTC) tổng hợp:
- Số ngày làm việc trong tuần
- Tỷ lệ PPE trung bình
- Top 3 incident
- Ảnh đặc trưng (1-3 ảnh)

Báo cáo render PDF + lưu vào MinIO → email gửi đến danh sách
distribution của dự án (Cài đặt → Báo cáo tuần → Danh sách email).

## Thiết lập

### Ngưỡng cảnh báo

Vào `/siteeye/settings` để chỉnh:
- **Min PPE rate** — dưới mức này → cảnh báo "an toàn yếu" trên
  báo cáo tuần (mặc định 80%).
- **Max incident per visit** — vượt mức → flag visit là "cần
  xem lại" (mặc định 3).

### YOLO model

Mặc định dùng `yolov8m-safety-vi.pt` — fine-tuned cho cảnh
công trường Việt Nam (BHLĐ mũ vàng, áo xanh phản quang, ô khoa
trắng …).

Gói Doanh nghiệp có thể train model riêng nếu công ty có đồng
phục/PPE đặc thù — liên hệ ops.

## Quyền riêng tư

- Ảnh **không bao giờ** được dùng để training AI mặc định —
  YOLO chạy local, không gửi đi.
- Ảnh chỉ lưu ở **MinIO của tổ chức bạn** (cloud hoặc on-prem
  cho Enterprise).
- Khuôn mặt không được nhận diện danh tính — chỉ box "person"
  cho mục đích đếm + check PPE.

## Best practices

1. **Chụp đủ ánh sáng** — góc ngược nắng làm YOLO bỏ sót.
2. **Khoảng cách 3-10m** — quá gần (< 1m) box bị clip; quá xa
   (> 15m) box nhỏ không detect được.
3. **2-3 lượt/ngày** lúc đầu ca + giữa ca + cuối ca cho coverage tốt.
4. **Đối chiếu báo cáo tuần với supervisor** — AI không thay được
   judgment con người, chỉ scale.
