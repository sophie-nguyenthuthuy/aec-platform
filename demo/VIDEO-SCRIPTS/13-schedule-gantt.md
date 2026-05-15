# Video #13 — Tiến độ dự án: Gantt + AI rủi ro

**⭐ TOP DEMO VIDEO** — flagship "tiến độ" hero for PM-focused
sales pitches.

* **Mục tiêu**: Người xem hiểu SchedulePilot = Gantt thật + baseline
  tracking + AI dự đoán rủi ro trễ.
* **Đối tượng**: PM, chỉ huy trưởng, GĐ kỹ thuật
* **Thời lượng**: 180 giây (3 phút)
* **Setup**:
  * Schedule mẫu "Thi công khu chung cư Tân Hòa — v1" với:
    - 30 activities trải qua 18 tháng
    - 6 dependencies FS giữa các phase
    - 3 milestone (móng xong, kết cấu xong, hoàn thiện xong)
    - 5 activities trên đường găng
    - 4 activities slipped vs baseline
    - Latest risk assessment đã chạy → critical_path_codes có
  * Status: baselined + 30% progress

## Shot list

### Shot 1 (0-15s) — Hook

**Visual**: Slide đen, text trắng:
> "70% dự án xây dựng VN trễ tiến độ. Chủ yếu vì PM không
> biết activity nào nằm trên đường găng cho đến khi nó trễ."

Cut to laptop: mở `/schedule/{id}` với Gantt loading.

### Shot 2 (15-30s) — Gantt overview

**Visual**: Full Gantt chart loaded:
* 30 rows, 18 cột tháng
* Bars 3-track: baseline xám / planned xanh / actual overlay đậm
* 5 đỏ rose bars (critical path)
* 4 cam bars (slipped vs baseline)
* Today line vertical đỏ dashed ~tháng 9
* Milestone diamonds bên cạnh activity name

**Narration**:
> "Đây là Gantt thật — 30 hoạt động xuyên 18 tháng. Mỗi row có
> 3 lớp bar: xám là baseline đã chốt, xanh là kế hoạch hiện tại,
> xanh đậm bên trong là phần đã hoàn thành."

### Shot 3 (30-50s) — Color coding

**Visual**: Cursor zoom vào 1 row đỏ rose. Hover → tooltip:
> "1.3.2 — Đổ bê tông cột tầng 5-10 · 01/03/2026 → 28/03/2026 ·
> 65% hoàn thành · trên đường găng"

Sau đó cursor đi qua 1 row cam:
> "2.1 — Lắp đặt hệ MEP tầng kỹ thuật · trễ 14 ngày so với
> baseline"

**Narration**:
> "Màu rose là đường găng — trễ 1 ngày là cả dự án trễ 1 ngày.
> Màu cam là trễ baseline, không trên critical nhưng vẫn cần
> theo dõi. Xanh là on plan."

### Shot 4 (50-75s) — Today line + drift visualization

**Visual**: Zoom vào today line vertical. Hiển thị 3 activities
đáng lẽ phải xong tuần trước (planned_finish < today nhưng
percent_complete < 100). Cursor highlight từng cái.

**Narration**:
> "Đường đỏ dashed là 'hôm nay'. 3 activities ở bên trái đáng lẽ
> phải xong tuần trước — vẫn còn 80%, 92%, 76%. Đây là warning
> sớm 1 tuần trước khi PM bị TGD hỏi 'tại sao trễ'."

### Shot 5 (75-110s) — AI risk analysis

**Visual**: Cursor click button "Phân tích rủi ro" (Sparkles icon).
Spinner 5s. Modal hiện ra:

```
PHÂN TÍCH RỦI RO AI
Overall slip prediction: +18 ngày so với baseline

TOP 3 RISKS:
1. Activity 1.3.2 — Đổ bê tông cột tầng 5-10
   Expected slip: 12 ngày
   Reason: Tốc độ thi công thực tế chậm hơn baseline 15%;
           dự báo theo trend hiện tại sẽ trễ 12 ngày.
   Mitigation: Tăng ca thợ hồ ngày T7, đặt thêm cốp pha.

2. Activity 2.1 — Hệ MEP tầng kỹ thuật
   Expected slip: 8 ngày
   ...

3. ...

Confidence: 73%
Critical path: [1.1.1, 1.2.3, 1.3.2, 1.4.1, 2.3.5]
```

**Narration**:
> "Bấm 'Phân tích rủi ro AI' — trong 5 giây hệ thống tính lại
> đường găng + dự đoán slip cuối dự án. Top 3 risks có lý do + đề
> xuất mitigation. AI biết QCVN, biết tốc độ thi công thực tế,
> biết dependencies."

### Shot 6 (110-140s) — Switch sang Danh sách

**Visual**: Toggle "Biểu đồ Gantt / Danh sách" → switch to list
view. Table hiển thị columns: mã, tên, status, % hoàn thành,
ngày bắt đầu, ngày kết thúc. Search filter "1.3" highlight 3 row.

**Narration**:
> "Đối với data entry hoặc review hàng loạt, bấm 'Danh sách' để
> xem table dense. Lọc, sort, edit nhanh. Khi cần present cho
> sếp, switch lại Gantt."

### Shot 7 (140-165s) — Mobile view

**Visual**: Resize browser xuống mobile width hoặc cut to phone
screenshot. Gantt scrolls horizontal trên phone. Activities tappable.

**Narration**:
> "Trên điện thoại — Gantt scroll ngang, tap vào activity để xem
> chi tiết + update progress. Chỉ huy trưởng cập nhật tiến độ
> ngoài công trường, không phải về văn phòng."

### Shot 8 (165-180s) — CTA outro

**Visual**: Outro slide với:
* "SchedulePilot — Tiến độ dự án + AI rủi ro"
* URL `app.aec-platform.vn/schedule`
* CTA "Dùng thử 30 ngày"

**Narration**:
> "SchedulePilot là 1 trong 17 module của AEC Platform. Đăng ký
> dùng thử tại app.aec-platform.vn. Video tiếp theo: SiteEye giám
> sát công trường bằng điện thoại."

## Captions tiếng Việt

Đặc biệt chú ý transcribe đúng:
* "đường găng" (critical path — không phải "critical pass")
* "baseline đã chốt"
* "thi công" (không phải "xây dựng")

## Mistakes to avoid

❌ **Đừng quay AI risk analysis live** — nó tốn ~$0.05 LLM + 5-15s
latency. Pre-record output mỗi lần, replay từ cache trong demo
mode (set `AEC_DEMO_MODE=1`).

❌ **Đừng zoom quá sâu vào 1 activity ở overview** — viewers cần
context của toàn schedule trước. Zoom dần dần, không jump cut.

✅ **Show today line rõ ràng** — đây là feature explainable nhất.
Pause 2-3s ở shot 4 cho viewer absorb.
