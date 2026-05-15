# Video #21 — Dòng tiền dự án (CashFlow)

**⭐ NEW MODULE** — CFO/project-controller focused demo.

* **Mục tiêu**: Người xem hiểu CashFlow giúp dự báo gap vốn lưu
  động + theo dõi actual vs planned.
* **Đối tượng**: CFO, project controller, GĐ tài chính
* **Thời lượng**: 150 giây
* **Setup**:
  * Project "Trung tâm thương mại Đại Việt" với:
    - 6 entries inflow (payment terms từ chủ đầu tư: 30/30/30/10%)
    - 12 entries outflow (NCC thép, NCC bê tông, NCC MEP, …)
    - 2 trong outflow đã có actual records partial
    - 1 inflow đã có actual full
  * Forecast 12 tháng cho thấy tháng 8 cumulative âm -2 tỷ

## Shot list

### Shot 1 (0-15s) — Pain point hook

**Visual**: Slide đen:
> "Payment terms từ chủ đầu tư: 30 ngày sau nghiệm thu. NCC + công
> nhân: 7 ngày. Chênh lệch 3 tuần = working capital crunch. PM
> không biết tháng nào âm tiền cho đến khi nó âm."

Cut to laptop: `/cashflow/{project_id}`.

### Shot 2 (15-30s) — Dashboard overview

**Visual**: 4 KPI tiles ở đầu:
* Tổng thu: 28.5 tỷ
* Tổng chi: 23.7 tỷ
* Net dự kiến: +4.8 tỷ ✓ (xanh)
* **Tháng âm dòng tiền: 1** (đỏ)

**Narration**:
> "Tổng inflow 12 tháng tới là 28.5 tỷ, outflow 23.7 tỷ, net dương
> 4.8 tỷ — nhưng có 1 THÁNG âm dòng tiền. Đây là điểm cần action
> sớm."

### Shot 3 (30-55s) — Bar chart 12 tháng

**Visual**: Bar chart hiển thị:
* T01-T07: thanh xanh inflow cao, thanh đỏ outflow vừa, luỹ kế dương
* **T08**: outflow đỏ to (3.5 tỷ trả NCC), inflow chỉ 800M, luỹ kế
  hiển thị **-2.1 tỷ** màu đỏ
* T09-T12: phục hồi dương

Cursor hover T08 → tooltip:
* "08/2026"
* "Thu: 800.000.000 ₫"
* "Chi: 3.500.000.000 ₫"
* "Net: -2.700.000.000 ₫"
* "Luỹ kế: -2.100.000.000 ₫"

**Narration**:
> "Tháng 8/2026 — thu chỉ 800 triệu nhưng chi 3.5 tỷ. Cumulative
> âm 2.1 tỷ. Bây giờ là tháng 5 — anh còn 3 tháng chuẩn bị: vay
> ngân hàng, đẩy tiến độ nghiệm thu sớm tháng 7, hoặc renegotiate
> payment terms với NCC."

### Shot 4 (55-85s) — Thêm entry mới

**Visual**: Click "Thêm dòng tiền". Form mở ra:
* Toggle: "Thu (Bên A trả)" đang chọn
* Ngày dự kiến: 15/07/2026
* Mô tả: "Thanh toán 30% sau khi nghiệm thu kết cấu"
* Số tiền: 4.500.000.000 ₫
* Notes: "Sau khi đẩy nhanh nghiệm thu kết cấu lên 1 tháng"

Save → entry mới xuất hiện trong list + bar chart cập nhật:
T07 inflow tăng lên 5.3 tỷ → luỹ kế T08 giờ chỉ -700 triệu thay
vì -2.1 tỷ.

**Narration**:
> "Mô phỏng action: đẩy 4.5 tỷ thanh toán inflow lên T07 thay vì
> T08. Chart cập nhật ngay — luỹ kế T08 giảm âm xuống còn -700
> triệu. Anh thấy ngay impact mô phỏng trước khi commit."

### Shot 5 (85-115s) — Ghi actual

**Visual**: Scroll xuống danh sách entry. Click vào entry "Thanh
toán 50% NCC thép Hòa Phát đợt 1 (4 tỷ)". Form ghi actual mở:

* Số tiền: 1.500.000.000 ₫
* Ngày trả: 01/05/2026 (hôm nay)
* Reference: "HD-2026-0512-VCB"

Save. Entry hiển thị pill vàng "Đã thu/trả 1.5B / 4B" — partial payment.

**Narration**:
> "Khi thực tế chuyển khoản — bấm vào entry, nhập số tiền + ngày +
> số sao kê. Hệ thống ghi nhận partial payment. Entry tự flip
> status='paid' khi tổng actuals đạt amount entry."

### Shot 6 (115-140s) — KTNN audit

**Visual**: Click action "Xuất Excel 12 tháng". File `cashflow-
TTM-Dai-Viet-2026-05.xlsx` download. Mở Excel hiển thị:
* Sheet 1: All entries with planned + actual columns
* Sheet 2: Monthly summary
* Sheet 3: Provenance (org name, generation timestamp, count, SHA-256)

**Narration**:
> "KTNN kiểm toán hỏi 'cho tôi xem dòng tiền dự án X cuối 2025'?
> Một click — Excel có audit trail SHA-256 cho admissibility pháp
> lý. Không phải build Excel tay."

### Shot 7 (140-150s) — CTA outro

**Visual**: Outro slide:
* "CashFlow — module mới #15"
* "Dự báo gap vốn lưu động trước khi gặp gap"
* URL `app.aec-platform.vn/cashflow`
* CTA "Tất cả 17 module miễn phí 30 ngày"

**Narration**:
> "CashFlow là 1 trong 17 module của AEC Platform. Đăng ký dùng
> thử tại app.aec-platform.vn."

## Captions tiếng Việt

* "dòng tiền" / "cashflow" — dùng cả hai, viewer hiểu hơn
* "vốn lưu động" — đây là financial term cụ thể, đừng giản hoá
* "luỹ kế" — không "cumulative" English

## Mistakes to avoid

❌ **Đừng show số tiền siêu thực tế** — 28.5 tỷ là plausible cho
mall medium-size. Đừng show 500 tỷ (looks fake) hoặc 50 triệu
(looks too small).

❌ **Đừng show bank account real** — reference "HD-2026-0512-VCB"
là format mẫu (HD = hợp đồng, VCB = Vietcombank). Đừng dùng số
TK thật.

✅ **Bar chart impact moment** — viewer bị "wow" ở shot 4 khi thêm
entry → chart update. Pause 2s sau khi save để absorb.
