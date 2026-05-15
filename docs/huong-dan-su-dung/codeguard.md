# CodeGuard — Đối chiếu QCVN/TCVN

Module **quét tuân thủ quy chuẩn Việt Nam tự động** cho thiết kế.
Hệ thống đã nạp sẵn các trích đoạn QCVN/TCVN phổ biến (PCCC, Tiếp
cận, Kết cấu, Quy hoạch, Năng lượng); bạn có thể bổ sung tài liệu
riêng cho khách hàng của bạn (Enterprise).

URL: `/codeguard`

## Use cases chính

1. **Trước khi nộp hồ sơ thiết kế** — quét thông số dự án (số tầng,
   diện tích, công năng, vật liệu) đối chiếu các quy chuẩn liên quan.
   Tránh bị thẩm tra trả về sau.
2. **Khi nhận RFI từ tư vấn** — hỏi nhanh "QCVN 06:2022 quy định
   khoảng cách thoát nạn tối đa cho nhà 12 tầng?" và nhận câu trả
   lời kèm trích dẫn nguyên văn.
3. **Sau cuộc họp với khách** — sinh checklist hồ sơ cấp phép theo
   QCVN/TCVN phù hợp loại công trình.

## Quy trình quét tuân thủ

### Bước 1 — Nhập thông số dự án

Vào sidebar → **CodeGuard → Quét tuân thủ** → trang `/codeguard/scan`.

Điền các trường:
- **Project ID** (chọn từ dropdown các dự án đã tạo)
- **Loại công trình** (residential / office / industrial / mixed)
- **Số tầng** (số tầng trên mặt đất)
- **Số tầng hầm**
- **Diện tích sàn (m²)**
- **Sức chứa người ước tính**
- **Yêu cầu PCCC nhóm phòng cháy** (PC-01 / PC-02 / … / PC-07)

### Bước 2 — Chọn nhóm quy chuẩn quét

- PCCC (QCVN 06:2022/BXD)
- Tiếp cận (QCVN 10:2014/BXD)
- Kết cấu (TCVN 5574:2018, TCVN 2737:2023)
- Quy hoạch (QCVN 01:2021/BXD)
- Năng lượng (QCVN 09:2017/BXD)

Mặc định chọn tất cả. Bỏ chọn nhóm không liên quan để tiết kiệm
quota AI.

### Bước 3 — Bấm "Bắt đầu quét"

- Hệ thống stream kết quả **theo từng nhóm**: bạn thấy ngay khi
  PCCC xong, không phải đợi tất cả.
- Mỗi finding có:
  - **Status pill**: PASS / WARN / FAIL
  - **Severity**: critical / major / minor
  - **Trích dẫn**: số `[1]` trong mô tả → click để xem nguyên văn
    điều khoản QCVN.

### Bước 4 — Xử lý finding

Với mỗi FAIL/WARN:
- Đọc trích dẫn nguyên văn để hiểu yêu cầu.
- Cập nhật bản vẽ / thuyết minh thiết kế.
- Quét lại sau khi sửa — hệ thống ghi nhật ký so sánh các lần quét
  ở trang `/codeguard/projects/{project_id}`.

## Trang dashboard dự án — Xem xu hướng

URL: `/codeguard/projects/{project_id}`

Trang này có **3 phần**:

1. **Biểu đồ xu hướng** — 10 lượt quét gần nhất, stacked bar
   (đỏ=FAIL / vàng=WARN / xanh=PASS). Click vào bar để xem chi
   tiết lượt quét đó.
2. **Chi tiết lượt quét đang chọn** — 3 ô score (Không đạt / Cảnh
   báo / Đạt) + danh sách finding.
3. **Tất cả lượt quét** — danh sách thời gian + click để swap.

Mục tiêu hiển thị: **xu hướng nên giảm FAIL theo thời gian**, không
phải zero ngay từ đầu.

## Tra cứu QCVN (Q&A có trích dẫn)

URL: `/codeguard/query`

Hỏi tự do về QCVN/TCVN; ví dụ:
- "Khoảng cách thoát nạn tối đa cho nhà ở chung cư 12 tầng?"
- "Yêu cầu chiều rộng cửa thoát hiểm cho phòng họp 80 người?"
- "Mật độ xây dựng tối đa cho lô đất quy hoạch loại nhà ở thấp tầng?"

Câu trả lời đi kèm số `[1]`, `[2]` → click để xem nguyên văn điều
khoản + section reference (vd: `QCVN 06:2022/BXD §3.2.1`).

## Sinh checklist cấp phép

URL: `/codeguard/checklist`

Chọn:
- **Jurisdiction** (Hà Nội / TPHCM / Đà Nẵng / Bình Dương / …)
- **Loại công trình**
- **Sức chứa người + diện tích** (ảnh hưởng PCCC nhóm)

Hệ thống sinh **checklist 10-30 mục hồ sơ** cần chuẩn bị, mỗi mục
có:
- Tên hạng mục (vd: "Bản vẽ thoát hiểm tỷ lệ 1:200")
- Quy định nguồn (QCVN nào, điều khoản nào)
- Status: pending / in_progress / done / not_applicable
- Đính kèm file đã sẵn sàng

Đánh dấu từng mục khi hoàn tất; xuất PDF cuối cùng để in nộp ở
trang `/codeguard/checklist/{id}/pdf`.

## Hạn mức AI

CodeGuard tiêu hao **hạn mức quota AI hàng tháng** của tổ chức bạn.
Xem `/codeguard/quota` để biết còn bao nhiêu.

- Gói Khởi đầu: 200 lượt/tháng
- Gói Chuyên nghiệp: 1.000 lượt/tháng
- Gói Doanh nghiệp: 5.000 lượt/tháng (mặc định, có thể tăng)

Khi đạt 80% sẽ có banner cảnh báo trên đầu trang; đạt 100% các
endpoint quét sẽ trả 429 cho đến đầu tháng sau hoặc khi nâng gói.

## Bổ sung QCVN riêng (Enterprise)

Nếu công ty bạn có **QCVN nội bộ** hoặc **TCCS** chưa được nạp,
liên hệ ops để ingest. Sau khi ingest, các quy định mới sẽ tự
động được dùng trong scan + Q&A.
