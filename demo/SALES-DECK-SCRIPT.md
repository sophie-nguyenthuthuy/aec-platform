# AEC Platform — Sales demo script (30 phút)

Kịch bản demo trực tuyến chuẩn cho prospect mới. Mục tiêu: cuối 30
phút, khách hiểu (a) AEC giải quyết vấn đề gì, (b) khác gì Procore /
phần mềm xây dựng nội địa, (c) bước tiếp theo (POC trial hoặc đặt
hợp đồng Doanh nghiệp).

**Slide structure**: 12 slide chính + 4 slide phụ tuỳ ngành khách hàng.
File PowerPoint nguồn: `demo/AEC-Platform-Demo.pptx`.

---

## Phần 1 — Mở đầu (3 phút)

### Slide 1 — Title

> "Xin chào anh/chị **[Tên khách]**. Em là **[Sales name]** từ AEC
> Platform. Hôm nay em demo 30 phút về cách nền tảng giải quyết 3 vấn
> đề lớn của nhà thầu xây dựng Việt Nam: **đối chiếu QCVN**, **giám
> sát công trường**, và **lập hồ sơ thầu**. Anh/chị có câu hỏi nào
> trước khi bắt đầu không?"

> _Mục đích slide_: warm-up + xác nhận thời gian + hỏi câu hỏi context.

### Slide 2 — "Tại sao chúng tôi tồn tại"

3 bullets, mỗi cái 1 dòng:
- Phần mềm xây dựng quốc tế (Procore, Autodesk Construction Cloud)
  không biết QCVN/TCVN, không có VietQR, không xuất KTNN audit format.
- Phần mềm nội địa (Coffee Cup, Eta Soft) thiếu AI + cấu trúc dữ liệu
  multi-tenant cho SaaS quy mô lớn.
- **AEC Platform = Procore + AI tiếng Việt + tích hợp QCVN sẵn**.

> "Đây không phải Procore dịch tiếng Việt — đây là phần mềm xây dựng
> Việt Nam built ground-up với AI."

---

## Phần 2 — Demo sản phẩm (20 phút)

### Slide 3 — Vòng đời dự án (1 phút)

Đưa khách sơ đồ 5 phase: **Pháp lý → Thiết kế → Đấu thầu → Thi công
→ Bàn giao** với module tương ứng. Hỏi:

> "Anh/chị đang gặp vấn đề lớn nhất ở giai đoạn nào? Em sẽ deep-dive
> vào đó trước."

Câu trả lời quyết định thứ tự demo các slide 4-9.

### Slide 4 — Tiến độ dự án (3 phút) — Nếu khách là nhà thầu thi công

Live demo `/schedule/{demo-schedule-id}`:
- Mở Gantt chart — chỉ 3 lớp bar (baseline / planned / actual).
- Bấm "Phân tích rủi ro AI" — đợi 10s, hiện top 3 risk với mitigation.
- "Đây là điểm khác biệt: phần mềm quốc tế cũng có Gantt, nhưng
  AI Risk Analysis hiểu QCVN — ví dụ activity 'Lắp đặt PCCC' bị
  AI đánh dấu vì nó biết PCCC thẩm duyệt thường mất 30 ngày, mà
  lịch chỉ allow 15 ngày."

### Slide 5 — CodeGuard (3 phút) — Nếu khách là nhà thầu thiết kế / TVTK

Live demo `/codeguard/scan`:
- Nhập thông số: nhà chung cư 25 tầng, 12.500 m², PCCC nhóm 4.
- Chọn 5 nhóm QCVN → bấm "Bắt đầu quét".
- Đợi 30s, kết quả streaming: 12 finding (3 FAIL / 5 WARN / 4 PASS).
- Click 1 finding FAIL → xem trích dẫn nguyên văn QCVN 06:2022 §3.2.1.

> "Bình thường thẩm tra TVQH trả về 2 lần là chậm 2 tuần. Quét trước
> với CodeGuard, sửa trước khi nộp = nộp 1 lần, qua 1 lần."

### Slide 6 — SiteEye (3 phút) — Nếu khách quan tâm an toàn

Live demo qua điện thoại (chia sẻ màn hình):
- Mở app PWA → tạo visit → chụp 2-3 ảnh công trường mẫu.
- Đợi 30s → quay lại visit → xem AI detection: 5 người, 3 đội mũ
  bảo hộ, 2 không đội. 1 ảnh flag "thiếu áo phản quang".
- Mở báo cáo tuần → ảnh + KPI tự động.

> "Một consultant an toàn 1 tháng đến công trường 1 lần. SiteEye
> coverage hàng ngày. Cost ~1/10."

### Slide 7 — Drawbridge (3 phút) — Nếu khách là PM / kỹ sư

Live demo `/drawbridge/query`:
- Mở chat → hỏi: "Bản vẽ M2 ghi độ dày sàn tầng 3 là bao nhiêu?"
- Đợi 5s → câu trả lời stream với citation [1] → click chip → xem
  trích đoạn từ bản vẽ thực tế.
- Hỏi tiếp: "Có xung đột MEP với kết cấu trục E-12 không?" → chuyển
  sang trang Conflicts để demo conflict scan.

> "Engineer trẻ không cần đọc 200 trang thuyết minh để trả lời 1
> câu hỏi đơn giản. Trả lời tức thì, có nguồn — kiểm chứng được."

### Slide 8 — BidRadar (3 phút) — Nếu khách là sales / BD

Live demo `/bidradar`:
- Mở danh sách bot scrape — 50 gói thầu từ 64 sở KH&ĐT trong 7 ngày
  qua.
- Filter "gói thầu xây lắp + Hà Nội + > 50 tỷ" → 8 cơ hội còn lại.
- Click 1 cơ hội → AI score 78/100 (matched với năng lực công ty
  + vùng địa lý + ngành nghề).

> "Sales BD bình thường mất 4-6 giờ/ngày đọc website đấu thầu. BidRadar
> filter còn 30 phút check + chốt cơ hội đáng theo đuổi."

### Slide 9 — WinWork (2 phút)

Click "Tạo đề xuất từ gói thầu này" → AI sinh proposal draft từ
template + AI fill scope of work + lịch.

> "Cắt 60% thời gian soạn hồ sơ thầu. PM giỏi vẫn cần review final
> draft, nhưng heavy-lifting là của AI."

### Slide 10 — Bàn giao + xuất PDF (2 phút)

Click `/handover/packages/{demo}/certificate.pdf` → download
**Biên bản bàn giao công trình** đúng mẫu BXD với header "CỘNG HOÀ
XÃ HỘI CHỦ NGHĨA VIỆT NAM" + chữ ký 2 bên.

> "Biên bản này có thể in nộp Sở Xây dựng ngay. Không phải copy
> sang Word rồi format lại."

---

## Phần 3 — Giá + Bước tiếp theo (7 phút)

### Slide 11 — Bảng giá (2 phút)

Show 3 gói: Khởi đầu / Chuyên nghiệp / Doanh nghiệp.

> "Khởi đầu free để các anh/chị thử với 1 dự án. Chuyên nghiệp 4.9 triệu
> VNĐ/tháng cho cty quy mô vừa. Doanh nghiệp custom price khoảng từ
> **[50-200 triệu/tháng]** tuỳ scope — nhưng đó là conversation
> riêng nếu các anh/chị quan tâm."

Tránh nói giá Doanh nghiệp cụ thể trước khi qualify nhu cầu.

### Slide 12 — Khác biệt với competitor (3 phút)

Bảng so sánh 5 dòng:

| | AEC Platform | Procore (US) | Coffee Cup (VN) | Tự build |
|---|---|---|---|---|
| QCVN/TCVN | ✅ ingest sẵn | ❌ | ❌ | 6 tháng |
| AI built-in | ✅ | ⚠️ add-on | ❌ | 12 tháng |
| Multi-tenant SaaS | ✅ | ✅ | ❌ | 12 tháng |
| VietQR + e-invoice VN | ✅ | ❌ | ✅ | 3 tháng |
| Data sovereignty (on-prem) | ✅ Enterprise | ❌ | ⚠️ tự host | tự build |

### Slide 13 — Bước tiếp theo (2 phút)

3 đường dẫn cho khách chọn:

1. **POC 30 ngày miễn phí**: tạo tài khoản Khởi đầu, seed dự án mẫu,
   thử 1 module quan tâm nhất. Sales handhold trong tuần đầu.
2. **Pilot 90 ngày trả phí gói Chuyên nghiệp**: 1 dự án thật, 5
   người dùng. ~15 triệu (3 tháng × 5 triệu). Đào tạo 1 buổi.
3. **MSA Doanh nghiệp**: liên hệ legal team. Báo giá custom dựa
   trên scope. SLA + hợp đồng có thời hạn 12 tháng+.

Đóng:

> "Em sẽ gửi email tổng kết demo + link tài liệu trong tối nay.
> Anh/chị muốn em sắp xếp cuộc follow-up nào cụ thể không?"

---

## Phụ lục — Slide backup (chỉ show nếu khách hỏi)

### A. Bảo mật + Compliance

- Tenant isolation qua Postgres RLS (mọi query có `WHERE
  organization_id = caller.org` enforced ở DB layer).
- Audit log append-only — mọi thay đổi (ai, lúc nào, từ IP nào, đổi gì).
- SOC 2 type II prep — đang triển khai (Q4 2026).
- Penetration test 2026 sẵn sàng chia sẻ NDA.

### B. Tích hợp

- REST API + Webhooks documented ở `/docs/api`.
- SDK Python + TypeScript.
- MS Project import / export.
- VnInvoice e-invoice connector.
- Custom integration trong gói Doanh nghiệp.

### C. Multi-region failover (Enterprise)

- Primary DB: Supabase Singapore.
- Read replica: AWS Tokyo (lag ~50ms typical).
- RTO 30 phút, RPO 1 phút target.
- Runbook ở `/docs/multi-region-failover.md` (gửi cho IT bên khách).

### D. Đào tạo + onboarding

- Tier 1 self-onboarding: wizard 5 phút trên app.
- Tier 2 (gói Pro): 1 buổi video onboarding 90 phút cho team.
- Tier 3 (Doanh nghiệp): on-site đào tạo 2 ngày + 30 ngày
  go-live support 1-1.

---

## Tips cho sales

1. **Đừng feature-vomit** — chỉ demo 2-3 module nhất khách quan tâm,
   để khách hỏi mới đi sâu thêm.
2. **Mở mic của khách thường xuyên** — câu hỏi sớm = engagement cao =
   close rate cao.
3. **Show data thật, không phải mock** — dùng tài khoản `demo@aec-platform.vn`
   với dữ liệu sinh ra từ `make seed-demo` (28 entity cross-module).
4. **Đừng hứa custom feature** ngoài kế hoạch — sale-engineer được
   approve cụ thể cho gói Doanh nghiệp.
5. **Câu hỏi qualifying critical**:
   - Số dự án đang chạy?
   - Pain point lớn nhất hiện tại?
   - Đang dùng phần mềm gì?
   - Budget allocation cho phần mềm/năm?
   - Ai là decision maker (IT? Director? CTO?)?
