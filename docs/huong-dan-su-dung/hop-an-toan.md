# Họp an toàn đầu ca (SafetyToolboxTalks)

Module ghi chép **buổi họp an toàn đầu ca** theo quy định bắt buộc của
**Nghị định 06/2021/NĐ-CP** (Quản lý chất lượng + bảo trì công trình
xây dựng) + **Thông tư 04/2017/TT-BXD**.

URL: `/safety-toolbox/{project_id}` (truy cập qua tab "Họp an toàn ↗"
trên Pulse project layout)

## Tại sao bắt buộc

- **Nghị định 06/2021 Điều 12**: Nhà thầu thi công phải tổ chức **họp
  triển khai công việc trước ca làm việc**, phổ biến biện pháp đảm
  bảo an toàn lao động.
- **Thông tư 04/2017 Điều 35**: Phải có **biên bản họp BHLĐ** ký xác
  nhận của mọi người tham gia.
- **Khi Sở Xây dựng kiểm tra** sẽ yêu cầu hồ sơ này. Thiếu hoặc gián
  đoạn → **phạt 5-15 triệu/lần vi phạm** (Nghị định 16/2022).

Module này giúp:
1. Ghi nhanh trên điện thoại — không cần giấy bút (tích hợp ảnh chữ
   ký nếu có).
2. KPI Coverage tự tính — % ngày làm việc có ghi nhận.
3. Khi inspector hỏi "show me your records" — bạn lấy ra ngay.

## Workflow hàng ngày

### Trước ca làm việc (5-10 phút)

1. Chỉ huy trưởng / HSE officer mở `/safety-toolbox/{project_id}`
   trên điện thoại.
2. Bấm **"Ghi nhận buổi họp"** → điền:
   - Ngày (mặc định hôm nay)
   - Ca (sáng/chiều/đêm)
   - **Chủ đề an toàn** — vd: "Sử dụng dây an toàn khi làm việc trên cao",
     "Phòng cháy chữa cháy mùa khô", "Chiến lược sơ tán khi mưa to",
     "Quy trình thao tác cẩu trục an toàn".
   - **Người trình bày** — họ tên + vai trò.
   - **Danh sách người tham dự** — mỗi dòng:
     `Họ tên | SĐT | Vai trò` (vd: `Nguyễn Văn A | 0987654321 | thợ hồ`).
     SĐT + vai trò có thể bỏ trống.
   - **Nội dung họp** (tuỳ chọn) — chi tiết để inspector đọc sau.

3. Bấm **"Ghi nhận"** → buổi họp xuất hiện trong "Lịch sử".

### Cuối ca / cuối ngày

Vào lại trang → coverage KPI tự cập nhật. Mục tiêu **≥ 95%** ngày
làm việc có ghi nhận (chấp nhận miss 1-2 ngày/tháng do bão / lễ
quốc gia).

## Coverage KPI

Tile ở đầu trang hiển thị:
- **Coverage 30 ngày**: % ngày làm việc có buổi họp. Xanh ≥95% / vàng
  80-94% / đỏ <80%.
- **Ngày có họp**: X / Y (Y = số ngày làm việc, đã loại trừ Chủ Nhật).
- **Ngày bỏ trống**: số ngày làm việc không có ghi nhận.
- **TB người tham dự**: trung bình head count mỗi buổi họp.

Nếu coverage < 95% và có ngày bỏ trống → **banner vàng** hiển thị
danh sách ngày trống. Bấm vào ngày để mở form ghi nhận retro
(quy định: trong vòng 7 ngày là vẫn hợp lệ).

## PPE Checks (sẽ có ở sprint sau)

Roadmap: thêm form check nhanh tình trạng PPE (mũ / áo phản quang
/ giày bảo hộ / dây an toàn) — output JSONB `{helmets: "all",
vests: "partial", ...}`. Auto-cross-reference với SiteEye detection
cùng ngày để bot phát hiện chênh lệch.

## Phân quyền

- **Member** (chỉ huy trưởng, HSE officer, kỹ sư giám sát):
  ghi nhận + thêm attendance. **Đây là role mặc định** vì người
  ghi báo cáo BHLĐ thường không phải owner platform.
- **Admin**: như Member + delete attendance individual.
- **Owner**: như Admin + delete cả buổi họp (chỉ dùng khi nhập
  trùng lặp — bình thường record là append-only).

## Tích hợp với module khác

- **SiteEye**: khi ghi buổi họp xong, chọn `siteeye_visit_id` để
  link tới lượt giám sát công trường cùng buổi. Ảnh PPE + ảnh
  ký tên đính kèm tự động qua link này.
- **Pulse**: đếm số buổi họp trong tuần tự thêm vào Báo cáo tuần.
- **Drawbridge**: chủ đề an toàn có thể click → query Drawbridge
  cho hướng dẫn QCVN chi tiết (vd: "Yêu cầu dây an toàn theo
  TCVN 5308-1991?").

## Xuất hồ sơ cho Sở Xây dựng

Hiện chưa có endpoint xuất. Roadmap Q3 2026:
- **PDF "Sổ họp BHLĐ" theo format BXD** — đóng quyển A4 in giấy.
- **Excel danh sách 30/60/90 ngày** cho inspector lọc nhanh.

Tạm thời: gọi API `GET /api/v1/safety-toolbox/projects/{id}/talks`
với `since=2026-01-01&until=2026-06-30` và export thủ công.

## Câu hỏi thường gặp

**Có cần ghi ngày Chủ Nhật không?**
Không. Tuần làm việc 6 ngày là chuẩn ngành xây dựng VN. Coverage
KPI đã exclude Sun. Nếu công trường làm 7 ngày/tuần (industrial),
contact ops để config exception.

**Ngày lễ (Tết, 30/4) thì sao?**
Tự hiểu là không phải ngày làm việc. Coverage KPI hiện chưa biết
lịch lễ VN — Sở Xây dựng inspector thường tolerant nếu thấy gap
đúng dịp Tết. Roadmap: ingest lịch lễ + auto-exclude.

**Có thể ghi retro cho ngày hôm qua không?**
Có. Hệ thống không gate timestamp; nhập `held_on` bất kỳ ngày nào.
Best practice: ghi cùng ngày để khớp ký tươi của attendees.

**Workers shared giữa nhiều dự án — có thể track họ ở đâu?**
Hiện chưa. Schema cố ý store worker_name + worker_phone dạng text
để onboarding nhanh. Module Workforce (roadmap Q4 2026) sẽ
normalise thành first-class entity với history attendance.
