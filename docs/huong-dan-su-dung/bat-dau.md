# Bắt đầu — Đăng ký + Khởi tạo tổ chức

Mục tiêu của trang này: trong **5 phút**, bạn có một tổ chức (org)
hoạt động + ít nhất 1 dự án mẫu để click thử.

---

## 1. Tạo tài khoản

Vào **`https://app.aec-platform.vn/login`** và làm theo một trong
hai cách:

### A. Đăng ký bằng email + mật khẩu

- Click **"Đăng ký"** (cuối form đăng nhập)
- Nhập email công ty + mật khẩu mạnh (≥ 12 ký tự, có chữ + số)
- Kiểm tra email và xác thực — link kích hoạt có hiệu lực 24h.

### B. Đăng nhập SSO (Google Workspace hoặc Microsoft)

- Click **"Đăng nhập với Google Workspace"** hoặc **"Đăng nhập với
  Microsoft"** trên form đăng nhập.
- Hệ thống chuyển đến Google/Microsoft → bạn đăng nhập tài khoản
  công ty bình thường.
- Sau khi cấp phép, trở về AEC Platform tự động.

> **Lưu ý cho IT admin**: SSO cần được kích hoạt phía nhà cung cấp
> (xem `deploy/SSO-SETUP.md`). Liên hệ ops nếu nút SSO báo lỗi
> "provider not enabled".

---

## 2. Khởi tạo tổ chức (Onboarding wizard)

Sau khi đăng nhập lần đầu, hệ thống tự đưa bạn vào **wizard 4 bước**:

### Bước 1 — Tạo tổ chức

- **Tên công ty**: hiển thị trên báo cáo, biên bản bàn giao,
  email RFQ gửi nhà cung cấp. Ví dụ: "Công ty Cổ phần Xây dựng ABC".
- **Quốc gia**: mặc định Việt Nam. Đổi nếu công ty bạn có chi nhánh
  ngoài VN.
- **Slug** (URL ngắn): tự động sinh từ tên. Không thể đổi sau khi
  tạo — dùng làm key trong audit log và URL chia sẻ.

### Bước 2 — Chọn module quan tâm

Hệ thống có 14 module. Tất cả luôn được kích hoạt — lựa chọn ở
bước này chỉ giúp ưu tiên hiển thị trên dashboard. Ví dụ:

- **Tổng thầu nhà nước**: chọn BidRadar, WinWork, CostPulse,
  Pulse, SchedulePilot, CodeGuard.
- **Nhà thầu thi công thuần**: chọn Pulse, SiteEye, SchedulePilot,
  Nhật ký, Lệnh thay đổi.
- **Nhà thầu thiết kế**: chọn Drawbridge, CodeGuard, WinWork.

Có thể đổi sau ở **Cài đặt → Module quan tâm**.

### Bước 3 — Mời thành viên (có thể bỏ qua)

Dán email các thành viên cần truy cập (cách nhau bằng dấu phẩy
hoặc xuống dòng). Họ sẽ nhận **lời mời qua email** với link đăng
ký tự động vào tổ chức bạn vừa tạo.

> Role mặc định cho người được mời là **member** — đủ để xem mọi
> dự án + thêm tasks. Để gán **admin** hoặc **owner**, vào
> Cài đặt → Thành viên sau khi tạo xong tổ chức.

### Bước 4 — Tạo dữ liệu mẫu (khuyên dùng)

- **Khuyên: bấm "Tạo dữ liệu mẫu + xong"** trong lần đầu — hệ
  thống sinh 1 dự án mẫu kèm đề xuất, dự toán, RFI, ảnh công
  trường, báo cáo tiến độ để bạn click thử trước khi nhập dự
  án thật.
- Có thể xoá dữ liệu mẫu sau ở **Dự án → bấm dự án mẫu → ⋯ →
  Xoá dự án**.

---

## 3. Sau onboarding — Bạn đang ở đâu

Bạn được đưa thẳng đến **dashboard "Hôm nay"** với:

- Inbox cá nhân (task được gán, RFI cần trả lời, mention)
- Hoạt động gần đây của team
- KPI tổng quan (số dự án đang chạy, công việc mở/quá hạn)

Sidebar bên trái có **7 nhóm** theo vòng đời dự án (Tổng quan →
Pháp lý → Thiết kế → Đấu thầu → Thi công → Bàn giao → Cài đặt).

## 4. Bước tiếp theo khuyên làm

1. **[Tạo dự án thật đầu tiên](./pulse.md#tao-du-an)** — vào Dự án →
   "Tạo dự án mới".
2. **[Upload bản vẽ + thuyết minh](./drawbridge.md#upload)** — kéo-thả
   PDF vào Drawbridge để Q&A sau này.
3. **[Mời đội ngũ](./thanh-vien.md)** — nếu bạn chưa làm ở bước 3
   của wizard.
4. **[Chọn gói cước](./goi-cuoc.md)** — gói Khởi đầu (miễn phí) phù
   hợp đánh giá 1-2 tuần; lên Chuyên nghiệp khi cần thêm dự án + AI quota.

---

## Câu hỏi thường gặp

**Tôi có thể tham gia nhiều tổ chức không?**
Có. Mỗi email có thể là thành viên của nhiều tổ chức (ví dụ: bạn
làm consultant cho 3 nhà thầu). Chuyển tổ chức qua dropdown ở
chân sidebar.

**Quên mật khẩu?**
Click **"Quên mật khẩu?"** trên form đăng nhập → email reset
được gửi trong 1-2 phút.

**Tổ chức tạo xong có xoá được không?**
Owner có thể xoá ở **Cài đặt → Tổ chức → Xoá tổ chức** — yêu cầu
nhập lại tên tổ chức để xác nhận. Mọi dữ liệu xoá vĩnh viễn sau 30
ngày retention.
