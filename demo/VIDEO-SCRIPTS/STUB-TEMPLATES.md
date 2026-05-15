# Stub scripts — remaining 20 video scripts

For modules where the recording session can use a simpler 60-90s
"feature spotlight" format vs the 150-180s flagship demos. Each
stub here gives the shot list + narration outline; flesh into
full markdown when scheduling that recording.

---

## Video #01 — Onboarding wizard (180s)

* **Hook (0-15s)**: "Tân user 90s từ signup → có dự án mẫu để click."
* **Shot 1**: SSO Google → land /onboarding (15s)
* **Shot 2**: Step 1 — tên công ty, country VN (15s)
* **Shot 3**: Step 2 — 14 module checkboxes, select 4 hot (20s)
* **Shot 4**: Step 3 — paste 3 emails team (20s)
* **Shot 5**: Step 4 — bấm "Tạo dữ liệu mẫu" (10s wait)
* **Shot 6**: Land /inbox với dashboard đầy data (30s)
* **Shot 7**: Sidebar showcase 7 nhóm module VN (30s)
* **CTA outro**: signup link (20s)

## Video #02 — Mời thành viên + phân quyền (90s)

* Settings → Thành viên → Mời 2 email
* Show 4 roles: owner / admin / member / viewer + matrix
* Sub-flow: revoke + change role
* CTA: tài liệu phân quyền

## Video #03 — PermitFlow (120s)

* Tạo permit application từ project
* Upload bộ hồ sơ thiết kế
* Submit → trackable status (submitted → inspection_scheduled →
  rfi loop → approved)
* AI generate cover letter
* CTA

## Video #04 — PCCC certification (120s)

* PCCC checklist sinh tự động theo nhóm phòng cháy
* Upload thẩm duyệt → AI parse number + ngày hết hạn
* Reminder 6 tháng trước expiry

## Video #06 — CodeGuard checklist sinh tự động (90s)

* Chọn jurisdiction Hà Nội + loại công trình
* AI generate 22 mục checklist
* Click 1 mục → trích dẫn nguồn QCVN
* Export PDF mang Sở nộp

## Video #07 — Drawbridge upload + ingest (120s)

* Upload 4 PDF kéo-thả
* Status: Đang xử lý → Sẵn sàng
* Show backend timing 30-60s per drawing
* Conflict scan auto-trigger
* CTA

## Video #09 — BidRadar săn gói thầu (150s)

* Dashboard 50+ gói thầu mới 7 ngày
* Filter Hà Nội + xây lắp + >50 tỷ → 8 results
* AI score 78/100 + reason
* Bấm "Create proposal from this opportunity" → handoff to WinWork
* CTA

## Video #10 — WinWork (180s)

* Tạo proposal từ template
* AI fill scope of work từ thông số khách hàng
* Cost estimate tự liên kết CostPulse
* Export PDF mẫu BXD
* Track status (draft → sent → won/lost)
* CTA

## Video #11 — CostPulse BoQ + RFQ (180s)

* Tạo BoQ + import từ Excel
* RFQ dispatch email đến 5 supplier
* Supplier reply via public portal
* Compare quotes side-by-side
* Pick winner → contract draft
* CTA

## Video #12 — Pulse project dashboard (120s)

* Click vào project → /pulse/{id}/dashboard
* 11-module rollup: tasks count, milestones, change orders, RFI...
* Schedule mini-Gantt embedded
* Project header + presence badge
* CTA

## Video #14 — SiteEye mobile (180s)

* Mở app PWA trên phone (cài vào màn hình chính)
* Tạo visit → chụp 10 ảnh
* Background AI processing 30s
* Refresh → see YOLO bounding boxes on PPE
* Incident list (no helmet, no vest)
* Weekly report email arrives
* CTA

## Video #15 — Safety Toolbox (120s)

* Mở `/safety-toolbox/{id}` trên phone
* Coverage KPI 87% with banner "8 ngày bỏ trống"
* Bấm "Ghi nhận buổi họp" form
* Paste danh sách 12 công nhân
* Submit → coverage cập nhật → 95%
* CTA: Nghị định 06/2021 compliance

## Video #16 — Daily log (90s)

* Tạo daily log entry
* AI suggest từ SiteEye observations
* Photo attachment + voice note
* PM review + sign-off
* Export weekly CSV

## Video #17 — Change order (120s)

* New change order với template
* Cost impact calculation (auto from CostPulse)
* Schedule impact (auto from SchedulePilot)
* Approval workflow: draft → submitted → approved/rejected
* Final value rollup vào project P&L

## Video #19 — Handover certificate PDF (120s)

* Setup handover package
* Closeout checklist 30 items
* As-built drawings upload
* Bấm "Tạo biên bản bàn giao PDF"
* Show PDF với CỘNG HOÀ XÃ HỘI CHỦ NGHĨA VIỆT NAM header + parties +
  scope table + signatures
* Download + email gửi Chủ đầu tư

## Video #20 — Punch list (90s)

* Setup punch list trên dự án near-handover
* Add 15 items với severity
* Assign cho từng nhà thầu phụ
* Track status until "verified by chủ đầu tư"
* Sign-off flow

## Video #22 — Công việc của tôi (90s)

* Mở /my-work buổi sáng
* 4 KPI tiles
* Filter "Của tôi" → 7 tasks open
* Group by project
* Click task → cập nhật progress
* Cuối ngày: KPI "Hoàn thành 7 ngày" tăng

## Video #23 — Billing + VietQR (150s)

* /settings/billing
* Click "Chuyên nghiệp" → modal VietQR
* Show bank info + reference code "AEC-PRO-202605-..."
* Mô phỏng chuyển khoản trên app ngân hàng (mock screen)
* Bấm "Tôi đã chuyển khoản"
* Status flip thành "Active"
* Subscription card hiển thị "Hiệu lực đến 14/06/2026"

## Video #24 — Chi phí AI (60s)

* /settings/llm-spend
* 4 KPI tiles: cost, calls, input tokens, output tokens
* Bar chart daily 30 ngày
* Module breakdown: Drawbridge 45%, CodeGuard 28%, WinWork 18%, ...
* "Tháng này: 850K đ"
* CTA: nâng gói nếu cần thêm quota

---

## Common shot conventions

* **Outro slide** (3-5s): Logo AEC + URL + CTA "Dùng thử miễn phí 30 ngày"
* **Loom highlights**: cursor zoom on click, 500ms post-click hold
* **Captions tiếng Việt**: cứng burn-in từ Premiere, không phụ thuộc
  YouTube auto-translate
* **Music**: instrumental, không lời, EDM mid-tempo (royalty-free từ
  Pixabay Music)
* **Voice-over**: Vietnamese, formal voice "anh/chị", articulate
  vừa phải (60-80% talking speed)
* **Color grade**: slight saturation boost on platform UI (looks
  vibrant); leave PDFs/screenshots untouched
