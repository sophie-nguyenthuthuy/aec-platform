# Tiến độ dự án (SchedulePilot)

Module quản lý **lịch dự án theo CPM (Critical Path Method)** với
baseline-vs-actual + AI phân tích rủi ro trễ.

URL: `/schedule`

## Khái niệm cơ bản

- **Schedule** — một bản lịch của dự án. Một dự án có thể có nhiều
  schedule (vd: re-baselining → tạo schedule v2).
- **Activity** (hoạt động / WBS item) — đơn vị nhỏ nhất: một
  task, một milestone (cột mốc), hoặc một summary (nhóm gộp).
- **Dependency** — quan hệ trước-sau giữa các activity. Hỗ trợ FS
  (finish→start, mặc định), SS, FF, SF + lag (số ngày dịch).
- **Baseline** — bản lịch "đóng băng" tại một thời điểm để so sánh
  về sau. Sau khi chốt baseline, các cột `baseline_start` +
  `baseline_finish` không tự cập nhật nữa.
- **Đường găng (Critical path)** — chuỗi activity nếu trễ một
  ngày thì cả dự án trễ một ngày. Hệ thống tính tự động khi bạn
  chạy "Phân tích rủi ro AI".

## Tạo lịch mới

1. Vào sidebar → **"Tiến độ dự án"** → bấm **"Tạo lịch mới"**.
2. Chọn dự án + đặt tên (vd: "Lịch thi công v1").
3. Hệ thống đưa bạn vào trang chi tiết lịch trống.

## Nhập activity

Có 3 cách:

### A. Nhập tay từng dòng
- Bấm **"+ Thêm hoạt động"** → điền mã WBS (1.1, 1.2, …), tên,
  ngày bắt đầu/kết thúc dự kiến, loại (task/milestone/summary),
  người phụ trách.

### B. Import từ MS Project / Primavera P6
- Xuất file MSP `.xml` từ MS Project (`File → Save As → XML`).
- Vào trang lịch → **"⋯" → "Import từ MSP/P6"** → kéo-thả file.
- Hệ thống tự dò mã WBS, ngày, dependency.

### C. Sinh từ AI (Pro/Enterprise)
- Bấm **"Sinh lịch từ thông số dự án"** ở trang trống → AI gợi ý
  WBS dựa trên loại công trình + diện tích + số tầng đã khai báo.
- Bạn xem lại + chỉnh sửa trước khi save.

## Biểu đồ Gantt

Mặc định trang chi tiết hiển thị **biểu đồ Gantt SVG** với 3 lớp
bar mỗi hoạt động:

- **Bar xám mảnh phía trên** — baseline (chỉ hiện sau khi chốt
  baseline).
- **Bar xanh dương dày** — kế hoạch hiện tại.
- **Bar xanh đậm bên trong** — phần đã hoàn thành (theo
  `percent_complete`).

Màu bar:
- 🔵 Xanh dương = đúng kế hoạch
- 🟠 Cam = trễ baseline
- 🔴 Đỏ rose = nằm trên đường găng (critical)
- 🟢 Diamond = milestone (zero-duration)

Đường gạch dọc đỏ = **vạch "Hôm nay"** — so sánh ngay được kế hoạch
với thực tế.

Có thể đổi sang chế độ **Danh sách** ở góc trên phải khi cần xem
nhiều cột dữ liệu cùng lúc.

## Chốt baseline

1. Khi lịch đã ổn định, bấm **"Chốt baseline"** (nút màu vàng).
2. Hệ thống chép `planned_start` + `planned_finish` → `baseline_*`
   cho mọi activity.
3. Sau đó, bạn vẫn có thể cập nhật `planned_*` (vd: trễ tiến độ
   thực tế) — bar xám baseline vẫn cố định để so sánh.

> **Lưu ý**: Chỉ chốt baseline **một lần** cho mỗi schedule. Nếu
> cần re-baseline, tạo **schedule mới** (vd: "v2") thay vì sửa
> baseline cũ — audit trail sạch hơn.

## Phân tích rủi ro AI

Bấm **"Phân tích rủi ro"** (nút có biểu tượng Sparkles):

1. AI duyệt toàn bộ activity, tính lại đường găng (CPM).
2. So sánh `planned_*` với `baseline_*` + tốc độ tiến độ thực tế.
3. Trả về:
   - **Overall slip days**: tổng số ngày dự đoán trễ baseline.
   - **Top risks**: 3-5 activity có khả năng trễ cao nhất với
     reason + mitigation gợi ý.
   - **Confidence**: độ tin cậy của phân tích (0-100%).

Chạy lại bất cứ khi nào cập nhật tiến độ. Mỗi lần chạy tốn ~5,000
token AI — xem dashboard `/settings/llm-spend` để theo dõi chi phí.

## Cập nhật tiến độ thực tế

Click vào một activity → mở panel chi tiết bên phải → cập nhật:
- **Phần trăm hoàn thành** (0-100)
- **Ngày bắt đầu thực tế** (`actual_start`)
- **Ngày kết thúc thực tế** (`actual_finish`)
- **Trạng thái**: not_started / in_progress / complete / on_hold

> Workflow khuyến nghị: cập nhật cuối tuần, trước khi gửi báo cáo
> tuần khách hàng (Pulse → Báo cáo → "Tạo báo cáo tuần").

## Xuất PDF

Trang chi tiết lịch → **"⋯" → "Xuất PDF"** — sinh báo cáo Gantt
in giấy A3 (Pro/Enterprise).

## Khắc phục lỗi thường gặp

**"Đường găng có loop"** → có dependency vòng (A → B → A). Hệ
thống cảnh báo + đánh dấu cặp tạo loop; xoá một trong hai dependency.

**Bar không hiển thị** → activity thiếu `planned_start` hoặc
`planned_finish`. Mở chi tiết activity và điền.

**Phân tích rủi ro lỗi quota** → tổ chức bạn hết hạn mức CodeGuard
+ schedule risk trong tháng. Xem `/codeguard/quota` hoặc nâng gói.
