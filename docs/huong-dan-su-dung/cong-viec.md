# Công việc của tôi

Dashboard tập trung mọi việc đang mở trên các dự án — kết hợp từ
hai nguồn: **Pulse tasks** (kanban) và **Tiến độ dự án activities**
(WBS). Đây là trang đầu tiên bạn nên mở mỗi sáng.

URL: `/my-work`

## Tổng quan trang

### 4 ô KPI ở đầu trang

- **Đang mở** — tổng việc chưa hoàn thành (toàn công ty hoặc của tôi).
- **Quá hạn** — đã vượt `due_date`. Cần xử lý gấp.
- **Hôm nay** — `due_date` đúng hôm nay.
- **Hoàn thành (7 ngày)** — tinh thần "vừa xong cái gì" cho buổi
  họp đầu tuần.

KPI tự refresh **mỗi 60 giây** để badge luôn đúng.

### 3 nhóm lọc

1. **Phạm vi**: "Toàn công ty" (mặc định) / "Của tôi" — chỉ việc
   được assign cho user hiện tại.
2. **Trạng thái**: "Đang mở" (mặc định) / "Quá hạn" / "Tất cả".
3. **Loại**: "Cả hai" (mặc định) / "Việc" (Pulse task) / "Tiến độ"
   (Schedule activity).

### Danh sách gom nhóm theo dự án

Mỗi dự án là một thẻ:
- Header: tên dự án (click để vào /pulse/{id}) + đếm số mục.
- List các việc: kind pill (Việc / Tiến độ), title, status, priority,
  due_date (highlight đỏ nếu quá hạn), assignee email.

Click một row để deep-link về Pulse tasks board hoặc Schedule
detail của dự án đó.

## Workflow khuyến nghị

### Buổi sáng (5 phút)

1. Mở `/my-work` với phạm vi **"Của tôi"**.
2. Quét ô **"Quá hạn"** — nếu > 0, xử lý trước tiên.
3. Quét ô **"Hôm nay"** — sắp xếp thứ tự thực hiện.
4. Mở từng việc, cập nhật progress hoặc reassign nếu cần.

### Buổi họp đứng (15 phút)

1. Mở `/my-work` với phạm vi **"Toàn công ty"**.
2. Cùng team review:
   - Số "Quá hạn" — ai đang bị blocker? Cần giúp gì?
   - Số "Hôm nay" — phân chia ai làm gì.
   - Số "Hoàn thành (7 ngày)" — ghi nhận thành tích tuần.

### Cuối tuần (10 phút)

1. Mở `/my-work` với trạng thái **"Quá hạn"**.
2. Lọc theo từng dự án — nhập rủi ro / lý do trễ vào panel chi
   tiết của task.
3. Nếu trễ vì dependency, vào Tiến độ dự án → re-baseline hoặc
   chạy "Phân tích rủi ro AI" để xem ảnh hưởng đường găng.

## Khác biệt giữa "Việc" và "Tiến độ"

| | Việc (Pulse task) | Tiến độ (Schedule activity) |
|---|---|---|
| Mục đích | Việc trong tuần | Cột mốc lịch dự án |
| Cấu trúc | Phẳng / kanban | WBS có cấp |
| Có baseline? | Không | Có |
| Có dependency? | Không | Có (FS/SS/FF/SF) |
| Có % hoàn thành? | Không | Có (0-100) |
| Tạo bởi | Bất kỳ team member | PM khi setup lịch |

> **Nguyên tắc**: việc gì có thể làm trong 1-3 ngày thì là Pulse
> task; cột mốc kéo dài 1-4 tuần là Schedule activity.

## Câu hỏi thường gặp

**Có thể export `/my-work` ra Excel không?**
Hiện chưa. Để xuất danh sách task, vào **Cài đặt → Xuất dữ liệu →
Tasks** (yêu cầu role admin).

**Tôi không thấy việc mà sếp vừa gán cho tôi?**
Refresh trang. Nếu vẫn không thấy, đảm bảo email user của bạn
khớp với email trong `assignee_id` của task — vào hồ sơ user để
kiểm tra.

**Có thông báo email khi việc gần đến hạn không?**
Có — gói Pro/Enterprise. Vào **Cài đặt → Thông báo** → bật "Nhắc
việc gần đến hạn".
