# Hướng dẫn sử dụng AEC Platform

Tài liệu này dành cho **người dùng cuối** — chủ đầu tư, ban quản lý dự
án, kỹ sư công trường, kế toán dự án. Đội kỹ thuật (lập trình, vận
hành hạ tầng) tham khảo `/docs/architecture.md`, `/docs/operations.md`
thay vì tài liệu này.

## Bắt đầu nhanh

1. **[Đăng ký + Khởi tạo tổ chức](./bat-dau.md)** — 5 phút để mở
   không gian làm việc cho công ty.
2. **[Tổng quan giao diện](./giao-dien-tong-quan.md)** — sơ đồ
   sidebar 7 nhóm module theo vòng đời dự án.
3. **[Công việc của tôi](./cong-viec.md)** — dashboard tập trung
   việc cần làm hôm nay.

## Theo vòng đời dự án xây dựng

### Giai đoạn pháp lý
- **[PermitFlow — Giấy phép xây dựng](./permitflow.md)** —
  theo dõi hồ sơ giấy phép qua các bước.
- **[PCCC — Phòng cháy chữa cháy](./pccc.md)** — chứng nhận thẩm
  duyệt + nghiệm thu PCCC.

### Giai đoạn thiết kế
- **[CodeGuard — Đối chiếu QCVN](./codeguard.md)** — quét tự động
  tuân thủ QCVN/TCVN cho bản vẽ.
- **[Drawbridge — Hỏi bản vẽ](./drawbridge.md)** — trợ lý AI trả
  lời câu hỏi về bản vẽ + thuyết minh kỹ thuật.

### Giai đoạn đấu thầu
- **[BidRadar — Săn gói thầu](./bidradar.md)** — bot quét + đánh giá
  cơ hội thầu nhà nước.
- **[WinWork — Đề xuất & Báo giá](./winwork.md)** — soạn đề xuất + báo
  giá có trợ giúp AI.
- **[CostPulse — Dự toán & Vật tư](./costpulse.md)** — BoQ + RFQ vật
  tư + đối chiếu bảng giá tỉnh.

### Giai đoạn thi công
- **[Tiến độ dự án (SchedulePilot)](./tien-do-du-an.md)** — Gantt +
  baseline + đường găng + AI phân tích rủi ro.
- **[Pulse — Điều phối dự án](./pulse.md)** — kanban tasks, milestone,
  meeting note, báo cáo tuần khách hàng.
- **[SiteEye — Giám sát công trường](./siteeye.md)** — chụp ảnh +
  phân tích AI PPE, BHLĐ, an toàn.
- **[Nhật ký công trình](./nhat-ky.md)** — daily log + báo cáo nhật trình.
- **[Lệnh thay đổi](./change-orders.md)** — quản lý change order.

### Giai đoạn bàn giao
- **[Handover — Bàn giao công trình](./handover.md)** — gói bàn giao,
  bản vẽ hoàn công, sổ tay vận hành, biên bản bàn giao PDF.
- **[Punch list — Danh mục tồn đọng](./punchlist.md)** — đôn đốc các
  hạng mục chưa hoàn thiện trước khi bàn giao.

## Quản trị

- **[Gói cước & Thanh toán](./goi-cuoc.md)** — chọn gói, chuyển khoản
  VietQR, thanh toán thẻ Stripe.
- **[Chi phí AI](./chi-phi-ai.md)** — dashboard theo dõi chi phí
  Gemini/Claude/OpenAI theo module.
- **[Mời thành viên + Phân quyền](./thanh-vien.md)** — owner, admin,
  member, viewer.
- **[Nhập dữ liệu từ Excel](./nhap-du-lieu.md)** — bulk import dự án
  + nhà cung cấp từ CSV/XLSX.

## Cần trợ giúp?

- Email hỗ trợ: `support@aec-platform.vn`
- Slack chung (Enterprise): qua đầu mối CSM
- Tài liệu kỹ thuật (cho dev): `docs/api/`
