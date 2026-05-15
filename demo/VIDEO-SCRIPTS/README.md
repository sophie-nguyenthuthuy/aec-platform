# Demo + training video scripts

Shot-by-shot scripts cho 17 module + 4 cross-cutting flow video.
Mỗi script viết theo format:

  * **Mục tiêu** — sau khi xem video, người xem làm được gì
  * **Đối tượng** — ai sẽ xem (PM / engineer / sub / IT admin)
  * **Thời lượng** — 60-180 giây cho training, 90-300 giây cho demo
  * **Setup** — dữ liệu cần seed trước khi quay
  * **Shot list** — mỗi shot có `(seconds, action, narration)`
  * **CTA** — slide kết video

Standard hoá:
  * Voice-over Vietnamese, formal voice (anh/chị xem).
  * Cursor highlight (Loom hoặc Cleanshot) + zoom in vào click target.
  * Captions tiếng Việt cứng (không phụ thuộc auto-translate YouTube).
  * Outro 3 giây: logo AEC + URL `app.aec-platform.vn`.

## Catalogue

### Onboarding flow (cross-cutting)
- [01-onboarding.md](./01-onboarding.md) — Đăng ký + Onboarding wizard (180s)
- [02-invite-team.md](./02-invite-team.md) — Mời thành viên + phân quyền (90s)

### Lifecycle: Pháp lý
- [03-permitflow.md](./03-permitflow.md) — Theo dõi giấy phép xây dựng (120s)
- [04-pccc.md](./04-pccc.md) — Thẩm duyệt PCCC (120s)

### Lifecycle: Thiết kế
- [05-codeguard-scan.md](./05-codeguard-scan.md) — Quét tuân thủ QCVN tự động (180s) ⭐ TOP DEMO
- [06-codeguard-checklist.md](./06-codeguard-checklist.md) — Sinh checklist hồ sơ cấp phép (90s)
- [07-drawbridge-upload.md](./07-drawbridge-upload.md) — Upload + ingest bản vẽ (120s)
- [08-drawbridge-qa.md](./08-drawbridge-qa.md) — Hỏi-đáp AI cho bản vẽ (180s) ⭐ TOP DEMO

### Lifecycle: Đấu thầu
- [09-bidradar.md](./09-bidradar.md) — Săn gói thầu nhà nước (150s)
- [10-winwork.md](./10-winwork.md) — Soạn đề xuất với AI (180s)
- [11-costpulse-boq.md](./11-costpulse-boq.md) — BoQ + RFQ vật tư (180s)

### Lifecycle: Thi công
- [12-pulse-dashboard.md](./12-pulse-dashboard.md) — Dashboard điều phối dự án (120s)
- [13-schedule-gantt.md](./13-schedule-gantt.md) — Gantt + AI rủi ro tiến độ (180s) ⭐ TOP DEMO
- [14-siteeye-mobile.md](./14-siteeye-mobile.md) — Giám sát công trường bằng điện thoại (180s)
- [15-safety-toolbox.md](./15-safety-toolbox.md) — Họp BHLĐ đầu ca (120s)
- [16-dailylog.md](./16-dailylog.md) — Nhật ký công trình (90s)
- [17-changeorder.md](./17-changeorder.md) — Quản lý lệnh thay đổi (120s)
- [18-subcontractor-portal.md](./18-subcontractor-portal.md) — Cổng nhà thầu phụ (150s) ⭐ NEW

### Lifecycle: Bàn giao
- [19-handover.md](./19-handover.md) — Bàn giao + biên bản PDF (120s)
- [20-punchlist.md](./20-punchlist.md) — Danh mục tồn đọng (90s)

### Cross-cutting
- [21-cashflow.md](./21-cashflow.md) — Dòng tiền dự án (150s) ⭐ NEW
- [22-my-work.md](./22-my-work.md) — "Công việc của tôi" — flow buổi sáng (90s)
- [23-billing.md](./23-billing.md) — Chọn gói + thanh toán VietQR (150s)
- [24-llm-spend.md](./24-llm-spend.md) — Chi phí AI dashboard (60s)

## Recording stack

* **Loom Pro** — voice + cam picture-in-picture, auto-transcript.
  Plan ~$15/mo. Public link sharing.
* **OBS Studio** (backup) — local recording nếu cần edit nặng.
* **Adobe Premiere** hoặc **CapCut** — edit captions + outro slide.
* **Cleanshot X** (macOS) — cursor highlight zoom for clean tutorial frames.

## Production pipeline

1. **Tuần 1**: quay 4 top demos (#05, #08, #13, #18 + #21). 1.5 ngày
   filming + 1 ngày edit.
2. **Tuần 2**: 8 module training video kế. 2 ngày filming + 1 ngày edit.
3. **Tuần 3**: còn lại (11 video) batch quay 1 mạch.
4. **Tuần 4**: subtitle dịch + publish lên YouTube unlisted +
   embed vào docs/huong-dan-su-dung/ markdown.

## Distribution

* **YouTube channel** "AEC Platform VN" — unlisted ban đầu, public
  sau khi review.
* **Vimeo Pro** — backup, private password protect cho sales demo.
* **Loom workspace** — version đầy đủ cho team nội bộ + sales đem
  đi demo offline.
* **Embed vào docs** — mỗi user-guide markdown có 1 video embed
  ở đầu trang.

## Editorial guidelines

❌ **Không show**: production data thật của khách hàng, secrets, IP
addresses, email cá nhân.
❌ **Không hứa**: tính năng chưa ship, roadmap dates cứng nhắc.
✅ **Luôn show**: trạng thái loading rõ ràng (Loom auto-record click
+ network latency).
✅ **Luôn nói**: "Đây là dữ liệu mẫu — dữ liệu của các anh chị sẽ
khác."
✅ **Luôn link**: docs/huong-dan-su-dung/{module}.md ở description.
