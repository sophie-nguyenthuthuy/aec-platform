# Video #05 — CodeGuard: Quét tuân thủ QCVN tự động

**⭐ TOP DEMO VIDEO** — used in sales pitches, landing page hero,
LinkedIn launch.

* **Mục tiêu**: Người xem hiểu CodeGuard quét bản thiết kế đối chiếu
  QCVN tự động, mỗi finding có trích dẫn nguyên văn.
* **Đối tượng**: Giám đốc thiết kế, kỹ sư TVTK, thẩm tra trưởng
* **Thời lượng**: 180 giây (3 phút)
* **Setup**:
  * Account `demo-tvtk@aec-platform.vn` đã tạo
  * 1 dự án mẫu "Chung cư Tân Hòa 25 tầng" với thông số:
    - residential, 25 tầng, 12.500 m², PCCC nhóm 4
  * QCVN 06:2022/BXD + QCVN 10:2014/BXD + TCVN 5574:2018 đã ingest
  * Quota AI đầy (>500 lượt)

## Shot list

### Shot 1 (0-15s) — Hook

**Visual**: Mở `/codeguard` trên trình duyệt, cursor trỏ vào tile
"Quét tuân thủ".

**Narration**:
> "Mỗi lần bộ thiết kế nộp Sở Xây dựng, thẩm tra thường trả về
> 2-3 lần với các yêu cầu vi phạm QCVN. Mỗi lần trả về là 1-2
> tuần re-design. CodeGuard giải quyết bằng cách quét tự động
> TRƯỚC khi nộp."

### Shot 2 (15-30s) — Click vào Quét

**Visual**: Click "Bắt đầu quét tuân thủ" → trang `/codeguard/scan`.
Cursor đi qua từng trường form.

**Narration**:
> "Đầu tiên, chọn dự án và nhập thông số: loại công trình, số
> tầng, diện tích, sức chứa người, nhóm PCCC."

### Shot 3 (30-50s) — Điền thông số

**Visual**:
* Dropdown "Dự án" → chọn "Chung cư Tân Hòa 25 tầng" (auto-fill
  thông số đã lưu).
* Bật/tắt 5 nhóm QCVN: PCCC ☑ Tiếp cận ☑ Kết cấu ☑ Quy hoạch ☐
  Năng lượng ☑.

**Narration**:
> "Hệ thống đã ingest QCVN 06:2022 về PCCC, QCVN 10:2014 về tiếp
> cận, TCVN 5574 + 2737 về kết cấu. Bạn chọn nhóm nào liên quan
> đến hồ sơ thiết kế của bạn — tiết kiệm quota AI."

### Shot 4 (50-75s) — Quét streaming

**Visual**: Click "Bắt đầu quét". Progress strip hiển thị từng
nhóm streaming:
* `[PCCC]` xanh ✓ — 3 finding
* `[Tiếp cận]` xanh ✓ — 2 finding
* `[Kết cấu]` đang... → xanh ✓ — 5 finding
* `[Năng lượng]` đang... → xanh ✓ — 2 finding

Tổng 12 finding xuất hiện dần dưới chart compliance donut.

**Narration**:
> "Quét stream theo từng nhóm — bạn thấy ngay kết quả PCCC, không
> phải đợi tất cả xong. Trong 30 giây hệ thống đã rà 4 nhóm quy
> chuẩn, tìm 12 vấn đề."

### Shot 5 (75-110s) — Click 1 finding FAIL

**Visual**: Scroll xuống danh sách finding. Click 1 finding **FAIL
critical**: "Khoảng cách thoát nạn vượt 25m so với QCVN".

Panel expand. Số `[1]` blue chip inside text. Cursor hover số [1] —
tooltip hiển thị trích đoạn nguyên văn QCVN 06:2022 §3.3.

**Narration**:
> "Đây là finding FAIL. Hệ thống nói chi tiết: 'Khoảng cách thoát
> nạn từ phòng cuối hành lang đến lối thoát hiểm là 28m, vượt
> giới hạn 25m theo QCVN 06:2022 mục 3.3'. Click số [1] để xem
> nguyên văn điều khoản. Không phải gõ tay tra QCVN."

### Shot 6 (110-140s) — Sửa thiết kế → Quét lại

**Visual**:
* Đóng panel finding.
* Click "Quét lại" sau khi mô phỏng có sửa bản vẽ.
* Scan stream chạy lại nhanh hơn (cached embeddings) — kết quả
  mới: 10 finding (giảm 2), 0 FAIL critical.

**Narration**:
> "Sau khi điều chỉnh thiết kế, quét lại — chỉ còn 10 finding,
> 0 FAIL critical. Bạn yên tâm nộp Sở Xây dựng lần 1, không phải
> lần 3."

### Shot 7 (140-165s) — Project history dashboard

**Visual**: Navigate đến `/codeguard/projects/{project_id}`.
Trend chart 10 scans gần nhất hiển thị: 5 cột FAIL→0 đỏ→giảm dần.

**Narration**:
> "Trang riêng cho mỗi dự án — xu hướng theo thời gian. Mục tiêu:
> tỷ lệ FAIL giảm dần qua các lần quét. Inspector / TVTK trưởng
> theo dõi tiến độ improving của team thiết kế."

### Shot 8 (165-180s) — CTA outro

**Visual**: Fade to outro slide:
* Logo AEC + tagline "Nền tảng AI quản lý dự án xây dựng VN"
* URL `app.aec-platform.vn/codeguard`
* CTA "Dùng thử miễn phí 30 ngày"

**Narration**:
> "CodeGuard là 1 trong 17 module của AEC Platform — built for VN
> construction. Đăng ký dùng thử miễn phí 30 ngày tại
> app.aec-platform.vn. Hẹn gặp các anh/chị trong video tiếp theo."

## Captions tiếng Việt

Chuẩn bị file `.srt` với timing chính xác từng câu để upload lên
YouTube. Sample SRT entry:

```
1
00:00:00,000 --> 00:00:15,000
Mỗi lần bộ thiết kế nộp Sở Xây dựng, thẩm tra thường trả về
2-3 lần với các yêu cầu vi phạm QCVN.

2
00:00:15,000 --> 00:00:25,000
Mỗi lần trả về là 1-2 tuần re-design. CodeGuard giải quyết
bằng cách quét tự động TRƯỚC khi nộp.
```

## Mistakes to avoid

❌ **Đừng quét live nhiều nhóm cùng lúc khi quay** — AI có thể
chậm + có spinner dài 30s+ làm video lê thê. Pre-record cached
scan, edit để stream effect 30s thay vì thực tế.

❌ **Đừng show quota counter** trên header — số quota là internal,
khách demo không cần biết "đã dùng 73/200 lượt".

❌ **Đừng show error path FAIL có Vietnamese diacritic mangled** —
test trước, nếu có thì fix font registration ngay.

✅ **Show số [1] trích dẫn rõ ràng** — zoom cursor vào blue chip,
giữ tooltip ít nhất 3 giây.
