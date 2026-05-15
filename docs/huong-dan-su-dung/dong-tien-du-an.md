# Dòng tiền dự án (CashFlow)

Module quản lý **dòng tiền theo dự án** — dự báo thu/chi theo
tháng, phát hiện tháng âm dòng tiền, theo dõi sai lệch giữa kế
hoạch và thực tế.

URL: `/cashflow/{project_id}` (truy cập qua tab "Dòng tiền ↗" trên
Pulse project layout, hoặc trực tiếp bằng URL)

## Tại sao module này quan trọng

Pain point #1 của nhà thầu Việt Nam: **payment terms từ chủ đầu tư
chậm 30-60 ngày sau nghiệm thu**, trong khi phải trả NCC + công
nhân hàng tuần. Không có công cụ dự báo → vay vốn lưu động cận-hạn
hoặc trễ thanh toán → mất uy tín NCC.

CashFlow giúp bạn:
1. **Lập kế hoạch trước** — tháng nào âm dòng tiền → chuẩn bị vốn lưu
   động sớm.
2. **Theo dõi sai lệch** — thực tế vs dự báo → adjust mô hình dự báo
   cho dự án sau.
3. **Báo cáo cho CFO/CEO** — KPI tổng thu/chi/net rõ ràng.

## Khái niệm cơ bản

- **Entry (dòng tiền)** — một sự kiện thu hoặc chi dự kiến.
  - `kind=inflow` (thu) — Bên A (chủ đầu tư) trả ta.
  - `kind=outflow` (chi) — ta trả Bên B (NCC, công nhân, ngân hàng).
- **Status (trạng thái)**:
  - `planned` — kế hoạch, chưa cam kết.
  - `committed` — đã ký hợp đồng / đã chốt, sẽ xảy ra đúng ngày.
  - `invoiced` — đã xuất hoá đơn / được xuất hoá đơn, đang đợi tiền vào.
  - `paid` — tiền đã chuyển. Tự động flip khi tổng actuals đạt amount.
  - `overdue` — quá hạn (đánh dấu thủ công).
  - `cancelled` — huỷ.
- **Actual** — bản ghi tiền thật khi nó thực sự chuyển. Một entry
  có thể có nhiều actual (vd: thanh toán làm nhiều đợt).
- **Forecast (dự báo)** — tổng hợp tháng, hiển thị thu/chi/net/luỹ kế.

## Thêm dòng tiền mới

Vào `/cashflow/{project_id}` → bấm **"Thêm dòng tiền"** → form
hiển thị:

1. **Loại**: Thu (Bên A trả) / Chi (Trả NCC).
2. **Ngày dự kiến**: ngày cash thực sự move (không phải ngày ký hợp đồng).
3. **Mô tả**: VD "Thanh toán 30% sau khi nghiệm thu kết cấu",
   "Tạm ứng NCC thép Hòa Phát đợt 1".
4. **Số tiền (VNĐ)**: số nguyên đơn vị đồng (không phẩy thập phân).
5. **Ghi chú** (tuỳ chọn).

Bấm **"Thêm"** → entry xuất hiện trong danh sách + bar chart cập
nhật ngay.

## Workflow khuyến nghị

### Khi bắt đầu dự án (1 lần)

1. Chuyển bộ payment schedule từ hợp đồng với chủ đầu tư → các
   entry inflow tương ứng (vd: "30% tạm ứng" + "30% sau nghiệm thu
   kết cấu" + "30% sau bàn giao" + "10% giữ chậm 12 tháng").
2. Chuyển dự toán mua sắm + nhân công → các entry outflow theo
   tháng dự kiến.
3. Xem forecast → nếu có tháng âm dòng tiền lớn → discuss với CFO
   chuẩn bị vốn lưu động.

### Hàng tuần (5 phút)

1. Vào trang → review entry sắp đến hạn (7 ngày tới).
2. Khi nhận được tiền inflow → bấm vào entry → "Ghi nhận thanh toán
   thực tế" → nhập số tiền + reference (số sao kê hoặc số hoá đơn).
3. Khi chuyển tiền outflow → same flow.

### Cuối tháng (15 phút)

1. So sánh inflow_dự_kiến vs inflow_actual của tháng vừa rồi —
   sai lệch lớn? Tại sao? Đối tác chậm? Chứng từ kẹt?
2. Adjust entry tháng tới nếu mô hình dự báo sai.
3. Báo cáo cho CFO: KPI tổng tháng + xu hướng cumulative.

## Bar chart dòng tiền

Trang dashboard show **bar chart 12 tháng** với:
- Cột xanh: inflow tháng đó.
- Cột đỏ: outflow tháng đó.
- Số dưới cột: luỹ kế (cumulative_vnd). Số đỏ = âm dòng tiền.

Hover một cột → tooltip với:
- Tháng (mm/yyyy)
- Thu / Chi / Net / Luỹ kế

Tooltip tháng đỏ là **CẢNH BÁO** — cần action ngay để chuẩn bị vốn.

## KPI tiles

4 ô KPI ở đầu trang:
- **Tổng thu (Inflow)** — tổng inflow trong horizon 12 tháng.
- **Tổng chi (Outflow)** — tổng outflow.
- **Net dự kiến** — Inflow − Outflow.
- **Tháng âm dòng tiền** — số tháng có cumulative_vnd < 0.

## Phân quyền

- **Member**: chỉ đọc dashboard + forecast.
- **Admin**: tạo / sửa / record actual.
- **Owner**: tất cả + xoá entry (soft cancel khuyến nghị hơn).

PMs (role member) thường không quản dòng tiền — đó là project
controller / kế toán. Phân quyền này khớp với cấu trúc tổ chức
thực tế.

## Tích hợp với module khác

- **Milestone**: khi tạo entry inflow, có thể link với Pulse
  milestone — khi milestone đạt status='achieved', entry tự nhảy
  từ `planned` → `committed` (tự động trong sprint sau).
- **CostPulse**: estimate có thể auto-generate dự báo outflow theo
  category nguyên vật liệu (sprint sau).
- **ThanhToan**: payment vào Pulse milestone tự tạo actual record
  cho entry liên quan (sprint sau).

## Xuất Excel / PDF

Hiện chưa có. Sprint sau:
- Excel: xuất danh sách entry + forecast table.
- PDF: báo cáo dòng tiền tháng cho CFO (1 trang).

## Câu hỏi thường gặp

**Đơn vị tiền có phải VNĐ không? Có hỗ trợ USD/EUR không?**
Hiện chỉ VNĐ (column `amount_vnd` BIGINT). Multi-currency là roadmap
Q4 2026 cho khách hàng EPCC nước ngoài.

**Nếu thanh toán làm nhiều đợt thì sao?**
Mỗi đợt là một actual record. Entry tự flip sang `paid` khi tổng
actuals đạt amount. Trước đó hiển thị pill vàng "Đã thu/trả X/Y".

**Có nhắc nhở khi entry sắp đến hạn không?**
Roadmap. Sprint sau sẽ thêm cron đẩy notification 7 ngày trước
expected_date cho người tạo entry.

**Có thể clone forecast từ dự án cũ sang dự án mới không?**
Roadmap Q3 2026 — "template forecast" cho các dự án tương tự về
quy mô + loại công trình.
