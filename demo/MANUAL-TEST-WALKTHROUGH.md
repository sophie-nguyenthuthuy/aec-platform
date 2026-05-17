# AEC Platform — Manual Test Walkthrough

Hands-on script for taking a non-technical viewer through every module of the live deployment. Each step lists what to click, what to expect, and the data already seeded so the page renders with real Vietnamese construction content (not empty states).

---

## 0 · Setup

| | |
|---|---|
| **URL** | `https://aec-platform-web-git-main-sophie-nguyenthuthuys-projects.vercel.app/login` |
| **Email** | `sophie.nguyenthuthuy@gmail.com` |
| **Password** | `AECDemo2026!` |
| **Active org** | Demo Construction Co. |
| **Browser** | Chrome or Safari (latest); hard-refresh before the demo to clear stale cache |

> **Note on URL:** the `web-five.vercel.app` alias is *not* in the API's CORS allow-list right now, so it will look empty on every data page. Use the `web-git-main-…` URL above and everything populates.

---

## 1 · Login (Slide 3)

1. Open the URL above
2. Type email + password → click **`Đăng nhập`**
3. **Expected:** instant redirect to `/winwork` (the Đề xuất page)
4. **Look at:** sidebar footer — shows `Demo Construction Co.` + `sophie.nguyenthuthuy@gmail.com` confirming the session is live

If signup is interesting to the demo viewer, click `Đăng ký` at the bottom of the login page — they'll see the same form layout with a confirm-email step.

---

## 2 · Hôm nay (Inbox) — Slide 4

Click **`Hôm nay`** in the sidebar (under TỔNG QUAN).

**You should see 14 inbox items across 6 tabs:**

| Tab | Count | Items |
|---|---|---|
| Tất cả | 14 | All sources merged |
| RFI | 5 | Drawing conflicts on Lotus Center (cột-dầm trục C5, cao độ sàn, lỗ chờ MEP, mẫu đá tự nhiên, xung đột HVAC) |
| Punch list | 8 | Items from VCB Q.1 walkthrough (silicone seal, paint mismatch, exit light, leaky tap, fire door, granite scratch, smoke detector, HVAC) |
| Khiếm khuyết | 0 | No defects yet |
| Đệ trình | 1 | Submittals due for review |
| CO | 0 | No pending change orders today |
| CO (AI) | 0 | No AI-flagged COs |

**Click any RFI** → opens the project's drawbridge view with the RFI thread.

---

## 3 · Dự án (Projects) — Slide 5

Click **`Dự án`** in the sidebar.

**You should see 6 project cards** rendered in a grid:

| Project | Type | Budget | Area | Open tasks · COs · docs |
|---|---|---|---|---|
| **Lotus Center Hà Nội** | commercial | ₫250B | 18,000 m² | 7 · 3 · 10 |
| Sky Garden Residences Saigon | residential | ₫180B | 12,500 m² | 0 · 0 · 0 |
| Samsung Yên Phong II-C — Nhà máy SDIV | industrial | ₫410B | 35,000 m² | 0 · 0 · 0 |
| FPT Đà Nẵng Campus — Tower B | commercial | ₫95B | 8,200 m² | 0 · 0 · 0 |
| Vinmec Hạ Long — Bệnh viện đa khoa | healthcare | ₫320B | 22,000 m² | 0 · 0 · 0 |
| Vietcombank Tower Q.1 | commercial | ₫540B | 38,000 m² | 0 · 0 · 0 |

Filter bar: `Tất cả`, `Lập kế hoạch`, `Thiết kế`, `Đấu thầu`, `Thi công`, `Bàn giao`, `Hoàn thành`. All 6 projects are currently `active` (status), so they appear under `Tất cả`.

**Click Lotus Center** → drills into a 14-module roll-up for that project.

---

## 4 · WinWork — Đề xuất (Slide 6)

Click **`WinWork`** in the sidebar.

**You should see 6 proposals**:

| Title | Status | Client | Fee | AI confidence |
|---|---|---|---|---|
| Lotus Center — Engineering services | **Thắng** | Lotus Group JSC | ₫1.8B | 92% |
| Sky Garden Residences — MEP design | Đã gửi | Cityland Investment | ₫850M | — |
| Samsung Yên Phong II-C — Shell-and-core | **Thắng** | Samsung Display VN | ₫2.4B | 88% |
| FPT Đà Nẵng Tower B — Structural | Bản nháp | FPT Corp | ₫720M | — |
| Vinmec Hạ Long — Full A&E | **Thua** | Vingroup Healthcare | ₫1.6B | — |
| Khu phức hợp Vincom Quy Nhơn — RFP | Đã gửi | Vingroup | ₫2.9B | — |

Click **`Tất cả`** filter buttons to flip between status. Click any won proposal to see the AI confidence indicator + fee breakdown.

---

## 5 · BidRadar — Hồ sơ đấu thầu phù hợp (Slide 7)

Click **`BidRadar`** in the sidebar.

**You should see 10 tenders ranked by AI fit score** (slider defaults to min 50):

- Xây dựng trụ sở UBND huyện Đông Anh — ₫45B
- Dự án trường tiểu học liên cấp Vạn Phúc — ₫28B
- Cầu vượt sông Tô Lịch — ₫12B
- Trạm biến áp 110kV Thái Hà — EVN — ₫88B
- Bệnh viện Đa khoa Tỉnh Bình Định — ₫156B
- Cải tạo trụ sở Bộ Tài chính — ₫8.5B
- Khu tái định cư Nhơn Trạch giai đoạn 2 — ₫220B
- Kho LNG Thị Vải — Petrovietnam — ₫380B
- Bangkok BTS Brown Line — cross-border PH/TH
- DPWH Mindanao Road Network Phase II

Top right: **`Chấm điểm lại`** button — recomputes fit scores against the firm profile.

---

## 6 · CodeGuard (Slide 8)

Click **`CodeGuard`** in the sidebar.

You land on the **4-surface module landing**:

1. **Hỏi quy chuẩn** — natural-language Q&A
2. **Quét tuân thủ** — AI compliance scan
3. **Checklist cấp phép** — permit checklist generator
4. **Thư viện quy chuẩn** — regulation library

**Click `Lịch sử kiểm tra` at the top** → shows the 4 hand-seeded compliance checks:

- Rà soát tầng hầm Lotus Center theo QCVN 06:2022/BXD (3 findings)
- Kiểm tra tiếp cận cho người khuyết tật — Vinmec Hạ Long (0 findings)
- Tải trọng động đất Skygarden — TCVN 9386:2012 (1 finding)
- Đánh giá năng lượng theo QCVN 09:2017/BXD — Lotus Center (2 findings)

**Click `Checklist cấp phép`** → shows 2 generated checklists (Lotus Hà Nội + FPT Đà Nẵng) with the VN permit chain.

---

## 7 · Drawbridge (Slide 9)

Click **`Drawbridge`** in the sidebar.

Top nav: **`Tài liệu | Hỏi bản vẽ | Xung đột | RFI | Trích xuất`**

### Tài liệu (default)
- 10 documents indexed for Lotus Center
- Discipline filter: Kiến trúc / MEP / Kết cấu / PCCC / Cấp thoát / Cảnh quan
- Drag-drop upload zone for PDF / DOCX / DWG (up to 100MB)

**Click `RFI` in the top nav** → shows 5 RFIs:
- Chi tiết giao cột-dầm tại trục C5 tầng 5 (open, high)
- Cao độ sàn hoàn thiện tầng 1 — A vs S khác nhau 35mm (answered, medium)
- Vị trí lỗ chờ MEP tại dầm trục B-D2 (open, high)
- Yêu cầu mẫu vật liệu lát đá tự nhiên (open, low)
- Xung đột giữa ống HVAC và trần kỹ thuật tầng 18 (in-progress, medium)

---

## 8 · CostPulse (Slide 10)

Click **`CostPulse`** in the sidebar.

5 surfaces visible:

1. **Dự toán** — 4 estimates seeded
2. **Dự toán mới** — AI from brief or drawing
3. **Cơ sở dữ liệu giá** — 20 material prices live (steel Hoà Phát ₫16,800/kg, xi măng Vicem ₫1.58M/tấn, etc.)
4. **Nhà cung cấp** — 8 verified suppliers
5. **Quản lý RFQ** — 2 RFQs, one with 4-supplier quote responses

**Click `Cơ sở dữ liệu giá`** → table of 20 materials with VND prices, effective dates, supplier links.

**Click `Quản lý RFQ` → open the Lotus Center RFQ** → see the supplier comparison table with Hòa Phát (₫12.5B), Vicem (₫13.2B), Hà Tiên (₫11.8B) quotes side-by-side.

---

## 9 · PermitFlow (Slide 11)

Click **`PermitFlow`** in the sidebar (under PHÁP LÝ).

Empty list by default (no hồ sơ created yet), but the page shows the **5-stage permit chain** at the top: `chủ trương đầu tư → quy hoạch 1/500 → thẩm định TKCS → giấy phép xây dựng → nghiệm thu PCCC`.

Click **`Tạo hồ sơ mới`** top right to walk through the wizard (5 steps mirroring the chain).

---

## 10 · Pulse (Slide 12)

Click **`Pulse`** in the sidebar (under GIAI ĐOẠN THI CÔNG). You'll be prompted to pick a project — click **Lotus Center Hà Nội**.

You'll see the Pulse dashboard for that project:

- **9 active tasks** mix of `todo`, `in_progress`, `blocked`, `done`
  - Hoàn thiện shop drawing tầng kỹ thuật M&E
  - Lập kế hoạch lao động tuần 24
  - Rà soát BOQ phần móng cọc
  - Cập nhật tiến độ S-curve hôm nay
  - Đặt vật tư thép D14 — đợt 3
  - Họp khởi công gói hoàn thiện tầng 1-5
  - Kiểm tra điện trở tiếp địa khu tủ chính
  - Phối hợp khoan đất nền
  - Phê duyệt mẫu vật liệu hoàn thiện sảnh

---

## 11 · SiteEye (Slide 13)

Click **`SiteEye`** in the sidebar → pick **Lotus Center**.

**Top nav tabs:** Dashboard / Visits / Safety / Progress / Reports

### Visits tab
5 site visits over the last week:
- B2 cốt thép cột (5 days ago, 142 workers, sunny 32°C)
- Tầng 6 sàn bê tông (4 days ago, mưa rào nhẹ, 98 workers)
- Hầm chống thấm (3 days ago, 165 workers, 35°C)
- Mặt ngoài giàn giáo tầng 18-22 (2 days ago, 78 workers)
- Sảnh granite (1 day ago, 54 workers)

### Safety tab
3 incidents:
- Missing helmet (open, high) — tầng 12 cốt pha
- Exposed rebar (acknowledged, medium) — tầng 5
- Missing harness (resolved, high) — tầng 18

---

## 12 · Change orders (Slide 14)

Click **`Change orders`** in the sidebar.

**6 COs in the pipeline:**

| # | Title | Status | Cost impact | Days |
|---|---|---|---|---|
| CO-001 | Tăng quy mô tầng hầm 2 lên 4500m² | **Đã duyệt** | +₫8.5B | +14 |
| CO-002 | Đổi vật liệu mặt ngoài sang kính Low-E | Đã gửi | +₫2.1B | 0 |
| CO-003 | Bổ sung hệ thống ống khói thoát khí | Đã gửi | +₫850M | +7 |
| CO-004 | Thay đổi thông gió hầm theo QCVN 06:2022 | **Đã duyệt** | +₫1.4B | +5 |
| CO-005 | Hủy hạng mục sảnh VIP tầng 2 | Bị từ chối | −₫1.2B | −3 |
| CO-006 | Bổ sung kho lưu trữ chứng từ | Bản nháp | +₫380M | +4 |

Net cost impact: **+₫12.13B**

---

## 13 · Submittals (Slide 15)

Click **`Submittals`** in the sidebar.

**6 packages** with CSI division metadata:

- LOT-SUB-001 · Mẫu đá granite ốp sảnh (09 30 00) — **Đã duyệt**
- LOT-SUB-002 · Bản vẽ shop ván khuôn cột (03 11 00) — Đang duyệt
- LOT-SUB-003 · Mẫu cửa kính Low-E (08 41 00) — Yêu cầu sửa/gửi lại
- LOT-SUB-004 · Catalog HVAC tầng kỹ thuật (23 60 00) — Đã nộp
- LOT-SUB-005 · Phương pháp móng cọc khoan nhồi (31 60 00) — **Đã duyệt**
- LOT-SUB-006 · Mẫu kính ốp tường WC (09 60 00) — Bị từ chối

Status badge colours match the ball-in-court (Owner / Designer / Contractor).

---

## 14 · Nhật ký — Daily logs (Slide 16)

Click **`Nhật ký`** in the sidebar.

**7 daily logs** for Lotus Center (one per day for the last week). Each log shows:
- Date + weather (temperature, humidity, conditions)
- Supervisor (sophie)
- Narrative paragraph
- Work completed sections
- Issues observed (some days have safety notes — "1 công nhân quên đeo dây an toàn")
- Status: submitted (recent) → approved (older)

---

## 15 · Punch list (Slide 17)

Click **`Punch list`** in the sidebar.

**2 walkthroughs** seeded:

### Walkthrough tầng 1-5 — VCB Q.1 (4 days ago)
Owner attendees: CDT ô. Nam · TVGS ô. Hùng · NT bà Linh

8 items tracked:
1. Khe co giãn sàn tầng 2 chưa trám silicone (medium, open)
2. Sơn tường sảnh thang máy tầng 4 lệch màu (low, in_progress)
3. Đèn exit khu thoát hiểm tầng 3 không hoạt động (**high**, open)
4. Vòi nước WC nam tầng 1 rò rỉ (medium, **fixed**)
5. Cửa thoát hiểm tầng 5 không tự đóng (**high**, in_progress)
6. Sàn granite tầng sảnh có vết xước dài 30cm (low, open)
7. Đầu báo khói tầng 4 chưa lập trình (**high**, open)
8. Hệ thống thông gió WC nam tầng 5 yếu (medium, open)

### Pre-handover lot 5 — Lotus Center (10 days ago)
2 items: tường sảnh nứt cọng tóc + quạt thông gió WC nữ.

---

## 16 · Handover (Slide 18)

Click **`Handover`** in the sidebar.

**2 packages:**

### Vietcombank Tower Q.1 — bàn giao tầng 6-22 (in-review)
Scope JSON shows: floors 6-22, areas (văn phòng + sảnh thang máy + WC chung), required docs (as-built A&E + MEP + biên bản PCCC + sổ tay vận hành), warranty 24 months.

### Lotus Center — bàn giao tầng hầm + 1-5 (**delivered** 12 days ago)
Warranty period: 24 months.

Top nav also shows: Bảo hành (Warranty) and Lỗi tồn đọng (Punch defects).

---

## 17 · Hoạt động — Activity feed (Slide 19)

Click **`Hoạt động`** in the sidebar (under TỔNG QUAN).

Cross-module activity stream — every RFI, CO, submittal, daily log, punch update lands here with module icon + project context + timestamp. Filter by module or project.

This is the canonical place to leave open on a second monitor during construction phase — it doubles as the "what's happening today" view.

---

## 18 · Wrap-up

After ~10 minutes you've walked through 14 modules, ~260 routes, 124 data rows.

### Recap

- **Six real Vietnamese construction projects**, ₫1.795 trillion VND total budget under management
- **6 modules with active data:** Projects, WinWork, BidRadar, CostPulse, CodeGuard, Pulse, SiteEye, Drawbridge, Nhật ký, Submittals, Change orders, Punch list, Handover
- **2 modules ready for data** but not seeded: PermitFlow + PCCC (intentionally empty so demo viewers can walk through the wizard themselves)
- **All Vietnamese** — module names, statuses, regulations (QCVN/TCVN), project names, supplier names

### What the AI does (when not blocked by a corp gateway)

- **WinWork** — drafts proposals from brief
- **CodeGuard** — Q&A over QCVN/TCVN with citations
- **CostPulse** — estimates from drawing or brief
- **Drawbridge** — semantic search over drawings + RFI answering
- **Pulse** — weekly client report from raw site data
- **BidRadar** — fit-scores tenders against firm profile
- **Daily log** — extract narrative from photos
- **SiteEye** — PPE detection on photos (when wired to GPU)

---

## Companion deck

`/tmp/aec-platform-demo.pptx` — 21 slides, 16:9 widescreen, mirrors this walkthrough with full-screen screenshots for projection.
