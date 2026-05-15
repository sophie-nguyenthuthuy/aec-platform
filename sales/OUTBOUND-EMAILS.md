# Outbound email templates — AEC Platform

5 cold-email variants tuned by industry segment + ICP role. Each
template has subject + body + CTA, with notes on personalisation.

Rule of thumb:
* Subject < 50 chars (mobile preview cuts it)
* Body < 150 words (anything longer gets archived)
* Single CTA per email (book a 30-min demo OR reply)
* Vietnamese formal voice (anh/chị), not bro voice

---

## Template A — SOE General Director (Tổng Giám đốc DNNN)

**Target ICP**: TGD/PTGD của tổng công ty xây dựng nhà nước.
*Examples*: Vinaconex, Cienco4, CC1, Lilama, Sông Đà.

**Subject**: Quản lý 14 module dự án xây dựng bằng AI — đề xuất demo 30 phút

**Body**:

> Kính gửi anh/chị **[Tên TGD]**,
>
> Em là **[Sales]**, founder AEC Platform — nền tảng SaaS quản lý
> dự án xây dựng được xây riêng cho thị trường Việt Nam.
>
> Em viết email này vì biết **[Tên Công ty]** đang triển khai
> **[Số]** dự án trên cả nước, với pain point lớn ở:
>
> 1. **Đối chiếu QCVN/TCVN trước khi nộp hồ sơ thiết kế** — phần
>    mềm quốc tế (Procore, Autodesk) không hiểu QCVN.
> 2. **Lập hồ sơ thầu nhà nước** — yêu cầu mẫu rất cụ thể, sai 1
>    chữ thẩm tra trả về.
> 3. **Xuất audit log theo format KTNN** — kiểm toán hỏi hồ sơ
>    quản lý 5 năm trước, không có cách trích xuất chuẩn.
>
> AEC Platform có sẵn:
> - **CodeGuard** — quét tuân thủ QCVN tự động (đã ingest QCVN
>   06:2022, 10:2014, 09:2017, TCVN 5574, 2737, …).
> - **WinWork** — AI sinh đề xuất theo mẫu BXD chuẩn.
> - **Xuất KTNN audit log CSV/XLSX có SHA-256** — đúng format Sở
>   Xây dựng + KTNN yêu cầu.
>
> Em đề xuất một buổi **demo 30 phút** vào tuần tới, em sẽ show
> dữ liệu mẫu ngành xây dựng dân dụng + công nghiệp. Nếu phù hợp
> với roadmap của công ty, em có thể đề xuất pilot trên 1 dự án
> thực tế (gói Chuyên nghiệp 4.9M VNĐ/tháng) hoặc gói Doanh
> nghiệp on-prem custom.
>
> Anh/chị có 30 phút **[Thứ X tuần Y, slot 14h-15h hoặc 16h-17h]**
> không ạ?
>
> Trân trọng,
> **[Sales] — Founder & CEO**
> **[Phone]** · **[Email]** · `https://app.aec-platform.vn`

**Personalisation checklist**:
- [ ] Tên TGD chính xác — tra trên trang chủ + Sở KH&ĐT công bố
- [ ] Số dự án — Google "[Công ty] dự án" + lấy con số gần đúng
- [ ] Loại ngành — dân dụng/công nghiệp/hạ tầng → điều chỉnh keywords

---

## Template B — Director kỹ thuật (Giám đốc Kỹ thuật / Phó TGD KT)

**Target ICP**: GĐ Kỹ thuật, Phó TGD phụ trách kỹ thuật. *Pain
points*: thẩm tra trả về, RFI tồn đọng, thiết kế revision quá nhiều.

**Subject**: Drawbridge — Hỏi bản vẽ bằng AI, có trích dẫn

**Body**:

> Kính gửi anh **[Tên]**,
>
> Em là **[Sales]** từ AEC Platform. Em viết để giới thiệu một
> tính năng mà em nghĩ team thiết kế của anh sẽ dùng hàng ngày:
>
> **Drawbridge — Hỏi-đáp AI cho bản vẽ kỹ thuật**.
>
> Upload bộ bản vẽ + thuyết minh dự án → engineer trẻ trong team
> hỏi tự nhiên ("Độ dày sàn tầng 3 là bao nhiêu?" / "Có conflict
> MEP vs kết cấu trên trục E-12 không?") → AI trả lời **kèm trích
> dẫn về bản vẽ + số trang gốc**.
>
> Không phải dán PDF vào ChatGPT (mất bí mật, không có citation).
> Đây là Q&A có trích nguồn, dùng kho bản vẽ riêng của công ty
> anh.
>
> Em demo 15 phút **[Thứ X, slot Y]** được không ạ? Em sẽ chuẩn
> bị data ngành **[xây dựng dân dụng / hạ tầng / công nghiệp]**
> để anh thử trực tiếp.
>
> Trân trọng,
> **[Sales]** · `app.aec-platform.vn/pricing`

**Personalisation checklist**:
- [ ] Tên + chức danh — tra trên LinkedIn hoặc website công ty
- [ ] Ngành đặc thù để chuẩn bị data demo
- [ ] Số lượng kỹ sư team thiết kế (Google "Phòng thiết kế [Công ty]")

---

## Template C — HSE / Safety Director

**Target ICP**: Trưởng phòng An toàn lao động, HSE Manager.
*Pain points*: thiếu hồ sơ BHLĐ khi Sở Xây dựng kiểm tra, bị phạt.

**Subject**: Hồ sơ họp BHLĐ đầu ca — tự động hoá theo Nghị định 06/2021

**Body**:

> Kính gửi anh/chị **[Tên]**,
>
> Em là **[Sales]** từ AEC Platform. Em tin rằng anh/chị đã từng
> bị Sở Xây dựng yêu cầu xuất trình hồ sơ họp BHLĐ đầu ca theo
> Nghị định 06/2021 — và một trong các tình huống đau đầu là
> không nhanh xuất được lịch sử 30/60/90 ngày.
>
> AEC Platform có module **"Họp an toàn"**:
> - **5 phút trên điện thoại** — supervisor mở app, nhập chủ đề,
>   paste danh sách công nhân (tên + SĐT), ghi nhận xong.
> - **KPI Coverage tự tính** — % ngày làm việc có ghi nhận.
> - **Banner cảnh báo** ngày bỏ trống — fix retro trước khi
>   inspector đến.
> - **Xuất Excel danh sách** cho inspector lọc nhanh.
>
> Hệ thống tích hợp với SiteEye (AI giám sát PPE bằng ảnh) →
> kiểm tra chéo giữa điều bạn ghi ("100% công nhân đội mũ") với
> ảnh thực tế.
>
> 20 phút demo **[Thứ X slot Y]**? Em sẽ show coverage KPI thực
> tế từ một site demo + cách auditor xem report.
>
> Trân trọng,
> **[Sales]** · `app.aec-platform.vn`

**Personalisation checklist**:
- [ ] Quy mô công ty (số công nhân) — Google "[Công ty] tuyển dụng"
- [ ] Vụ kiện gần đây của ngành về BHLĐ — quote nếu có

---

## Template D — Director Đấu thầu / Sales

**Target ICP**: Trưởng phòng Đấu thầu, BD Director, Phó TGD Kinh
doanh. *Pain points*: sale BD đọc website đấu thầu cả ngày, bỏ lỡ
cơ hội phù hợp năng lực.

**Subject**: BidRadar — Săn gói thầu nhà nước tự động (đã match năng lực)

**Body**:

> Kính gửi anh **[Tên]**,
>
> Em là **[Sales]** từ AEC Platform. Em biết team BD của **[Công
> ty]** mỗi ngày đọc Sở KH&ĐT 64 tỉnh để tìm gói thầu phù hợp —
> tốn 4-6 giờ/ngày của 2-3 người, và vẫn miss cơ hội.
>
> **BidRadar** là bot scrape + đánh giá AI cho website đấu thầu
> nhà nước:
> - **Tự động crawl 64 sở KH&ĐT** mỗi 4 giờ.
> - **AI score 0-100** match với năng lực công ty (vùng địa lý,
>   ngành nghề, gói thầu cùng quy mô).
> - **Email digest hàng ngày** với top-5 cơ hội mới.
>
> Team BD giảm từ "đọc list 200 gói thầu" → "review 5 gói đã
> filter" → close rate gấp **3x**.
>
> Em đề xuất demo 30 phút **[Thứ X slot Y]**, em show data
> Hà Nội + TP HCM tuần này để anh thấy chất lượng filter.
>
> Trân trọng,
> **[Sales]** · `app.aec-platform.vn/pricing`

---

## Template E — IT Director / CIO

**Target ICP**: CIO, IT Director. *Pain points*: yêu cầu hợp đồng
on-prem cho dữ liệu nhạy cảm, SSO Microsoft Entra mandatory, SLA
99.9% cam kết hợp đồng.

**Subject**: AEC Platform — Triển khai on-prem + SSO Microsoft Entra

**Body**:

> Kính gửi anh **[Tên]**,
>
> Em là **[Sales]** từ AEC Platform. Em viết để discuss khả năng
> tích hợp AEC Platform với hạ tầng IT hiện có của **[Công ty]**:
>
> - **SSO Microsoft Entra ID** (gọn trong Entra app registration,
>   không cần SAML federation custom)
> - **On-prem deployment** — Database trên Supabase enterprise
>   hoặc Postgres self-managed của các anh, MinIO local cho bản
>   vẽ (data sovereignty cho dự án quân sự / bí mật quốc gia).
> - **Multi-region failover Singapore → Tokyo**, RTO 30 phút,
>   RPO 1 phút — runbook ở `app.aec-platform.vn/docs/multi-region-failover`.
> - **SLA 99.9% có cam kết hợp đồng** — gói Doanh nghiệp.
> - **Audit log append-only** + xuất KTNN format SHA-256
>   (legal-admissibility cho compliance).
>
> Em đề xuất 1 cuộc 45 phút **[Thứ X slot Y]** để discuss
> architecture + security posture với security lead của các
> anh. Em chuẩn bị:
> - Pen-test summary 2026 (under NDA).
> - SOC 2 type II roadmap (Q4 2026).
> - Tenant isolation pattern (Postgres RLS).
>
> Trân trọng,
> **[Sales]** · `app.aec-platform.vn/docs/architecture`

---

## Follow-up template — 5 ngày sau email đầu, chưa reply

**Subject**: RE: **[Subject email trước]**

**Body**:

> Kính gửi anh/chị **[Tên]**,
>
> Em hiểu anh/chị bận. Em chỉ muốn check lại — em có thể gửi
> trước:
>
> - **30s demo video** module **[X]** (link YouTube unlisted)
> - **2-page brief** comparison với Procore / phần mềm hiện tại
> - **Slide deck PDF** (10 slide)
>
> Cái nào hữu ích nhất em gửi liền. Hoặc nếu thời điểm không
> phù hợp, em không follow nữa — chỉ cần anh/chị reply "Skip" là
> em biết.
>
> Trân trọng,
> **[Sales]**

---

## Anti-patterns — tránh các email kiểu này

❌ **Subject "Hi there!"** — generic, không personalisation.
❌ **Mở email bằng "Hope this email finds you well"** — copy paste from
US sales course. Người Việt không dùng câu đó.
❌ **Body > 300 từ** — sẽ bị archive.
❌ **Liệt kê 14 module** trong email đầu — chọn 1-2 nhất có liên
quan đến ICP role.
❌ **Hứa free trial cho enterprise** — invalid; enterprise cần MSA
+ POC paid.

## Tracking

Track mọi outbound qua:
* CRM tag: `outbound_email_template_<A|B|C|D|E>`
* Open rate target: **40-60%** (with proper subject)
* Reply rate target: **8-15%** (cold to ICP)
* Demo book rate: **3-5%** (of total sent)

Nếu open rate <30% → subject yếu. Nếu reply <5% → body không
relevant đến ICP.
