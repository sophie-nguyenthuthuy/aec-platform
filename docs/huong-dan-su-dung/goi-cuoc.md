# Gói cước & Thanh toán

3 gói: **Khởi đầu** (miễn phí), **Chuyên nghiệp** (4,9 triệu VNĐ/tháng),
**Doanh nghiệp** (liên hệ báo giá).

URL: `/settings/billing`

> Tất cả 14 module luôn được kích hoạt trên mọi gói. Gói chỉ ảnh
> hưởng giới hạn dự án, lưu trữ, quota AI, và một số tính năng cao
> cấp (PDF báo cáo, xuất audit, SSO).

## Bảng so sánh nhanh

| | Khởi đầu | Chuyên nghiệp | Doanh nghiệp |
|---|---|---|---|
| Giá | Miễn phí | 4,9M VNĐ / tháng | Liên hệ |
| Dự án tối đa | 1 | 10 | Không giới hạn |
| Thành viên | 3 | 25 | Không giới hạn |
| Lưu trữ bản vẽ | 2 GB | 50 GB | Tuỳ chỉnh |
| Quota CodeGuard | 200 / tháng | 1.000 / tháng | 5.000+ / tháng |
| PDF báo cáo dự án + biên bản bàn giao | ✗ | ✓ | ✓ |
| Xuất KTNN audit log (CSV + XLSX có SHA-256) | ✗ | ✓ | ✓ |
| SSO Microsoft Entra + Google Workspace | ✗ | ✗ | ✓ |
| Deploy on-prem (MinIO local) | ✗ | ✗ | ✓ |
| SLA 99.9% có cam kết hợp đồng | ✗ | ✗ | ✓ |
| Custom QCVN ingest | ✗ | ✗ | ✓ |
| Hỗ trợ | Email cộng đồng | Email trong ngày | Hotline + Slack |

## Nâng gói lên Chuyên nghiệp

Vào **Cài đặt → Gói cước & Thanh toán** → bấm card **"Chuyên
nghiệp"** → có 2 phương thức:

### A. Chuyển khoản VietQR (khuyến nghị cho khách VN)

1. Bấm **"Chuyển khoản VietQR"** → modal hiện ra với:
   - Tên ngân hàng (vd: Vietcombank — CN Hà Nội)
   - Số tài khoản
   - Tên chủ tài khoản
   - Số tiền: **4.900.000 ₫**
   - **Nội dung chuyển khoản** (bắt buộc đúng chính xác từng ký
     tự, vd: `AEC platform - AEC-PRO-202605-A1B2C3D4`)

2. Mở app ngân hàng → chuyển khoản đúng các trường trên. Có thể
   quét VietQR thẳng nếu ngân hàng hỗ trợ.

3. Quay lại modal → bấm **"Tôi đã chuyển khoản"** → gói kích hoạt
   ngay (ops sẽ đối chiếu sao kê trong 1 ngày làm việc; sai sót
   sẽ liên hệ qua email).

### B. Thẻ tín dụng quốc tế (Stripe)

1. Bấm **"Thanh toán bằng thẻ (USD)"** → redirect đến Stripe Checkout.
2. Điền thông tin thẻ Visa/Master quốc tế.
3. Sau thanh toán thành công, Stripe tự gọi webhook → gói kích hoạt
   tự động trong ~30s.

> Thẻ nội địa Việt Nam (Napas) hiện chưa hỗ trợ qua Stripe. Vui
> lòng dùng VietQR.

## Doanh nghiệp — Yêu cầu báo giá

Gói Doanh nghiệp không có giá tự phục vụ. Email:
**sales@aec-platform.vn** với:
- Tên công ty
- Quy mô (số dự án/năm, số nhân viên)
- Nhu cầu đặc biệt: deploy on-prem? SSO? QCVN nội bộ? SLA cam kết?

Sales sẽ phản hồi trong 1 ngày làm việc với báo giá MSA + SOW.

## Theo dõi chi tiêu

- **Trạng thái gói + ngày hết hạn**: hiển thị ở card "Gói hiện
  tại" trên trang Billing.
- **Lịch sử hoá đơn**: bấm "Xem hoá đơn" trên cùng trang — danh
  sách 24 hoá đơn gần nhất (≈ 2 năm).
- **Chi phí AI**: dashboard riêng ở **Cài đặt → Chi phí AI** —
  theo dõi Gemini/Claude/OpenAI từng module mỗi tháng (xem
  [chi-phi-ai.md](./chi-phi-ai.md)).

## Hạ gói / Huỷ

### Tự động không gia hạn (Stripe)

Vào Stripe customer portal qua link "Quản lý subscription" trên
trang Billing → bấm "Cancel". Gói vẫn dùng đến hết kỳ hiện tại,
sau đó tự về **Khởi đầu**.

### Không thanh toán tháng tiếp theo (VietQR)

Không chuyển khoản tháng kế tiếp → gói tự hạ về **Khởi đầu** sau
ngày hết hạn 7 ngày (grace period). Trong 7 ngày này hệ thống
gửi email nhắc.

> **Hậu quả khi hạ gói**: nếu vượt giới hạn gói mới (vd: đang có
> 5 dự án mà hạ về Khởi đầu — giới hạn 1), các dự án vẫn truy
> cập được nhưng không thể tạo dự án mới hoặc upload bản vẽ mới
> cho đến khi xoá xuống đúng giới hạn hoặc nâng lại gói.

## Câu hỏi thường gặp

**Có thể trả tiền theo năm (12 tháng) để được chiết khấu?**
Liên hệ sales@ — gói Chuyên nghiệp có discount 15% khi prepay 1
năm; gói Doanh nghiệp thương lượng theo hợp đồng.

**Tôi chuyển khoản nhầm số tiền — xử lý sao?**
Liên hệ ops qua **Cài đặt → Hỗ trợ** kèm screenshot bill ngân
hàng. Ops sẽ refund chênh lệch hoặc kích hoạt gói nếu số tiền đủ.

**Tổ chức tôi là cty con — có VAT hoá đơn?**
Có. Hoá đơn điện tử (e-invoice) phát hành tự động sau mỗi thanh
toán thành công; tải về ở mục "Lịch sử hoá đơn" trên trang Billing.
