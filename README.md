# Smart Door · Xác thực khuôn mặt mở khóa cửa

Ứng dụng Windows nhận ảnh JPEG, dùng YuNet + SFace trên CPU, kiểm tra quyền theo thiết bị và ghi kết quả điều khiển relay. Bản demo dùng webcam laptop và relay giả lập. Thiết bị đích là **ESP32-S3 N16R8 CAM Kit của wmx88.vn, camera OV3660, relay và khóa LY-03 12 V**.

## Chạy demo trên Windows

Cần Python 3.11, webcam và Internet cho lần đầu cài thư viện, tải mô hình. **Cách nhanh** từ thư mục repo, chạy hai lệnh trong hai cửa sổ PowerShell:

    .\scripts\start_demo.ps1
    .\scripts\start_demo.ps1 -Mode Webcam

Lệnh đầu hỏi mật khẩu quản trị ở lần thiết lập đầu tiên và chạy giao diện tại http://127.0.0.1:8000. Lệnh thứ hai bật webcam giả lập thiết bị. Để kiểm tra cài đặt, dùng -Mode Check. Môi trường Python của cách này nằm trong Local AppData, ngoài thư mục OneDrive.

**Cài từng bước** nếu bạn muốn tự quản lý môi trường Python:

    py -3.11 -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -r requirements-smartdoor.txt
    .\.venv\Scripts\python.exe -m smartdoor.setup
    .\.venv\Scripts\python.exe -m smartdoor.models
    .\.venv\Scripts\python.exe scripts/run_web.py

Lệnh setup hỏi mật khẩu cho tài khoản admin. Mở [bảng điều khiển](http://127.0.0.1:8000) và đăng nhập. Trong **cửa sổ PowerShell thứ hai** tại repo:

    .\.venv\Scripts\python.exe -m smartdoor.simulator

Giữ cửa sổ này mở trong buổi demo. Để chọn webcam khác, thêm --camera 1. Ctrl+C dừng giả lập và trả camera cho ứng dụng khác. Sau khi tải mô hình, phần mềm chạy trong máy hoặc LAN.

1. Chọn **Webcam · thiết bị giả lập**. Trong **Người dùng và quyền**, tạo mã và họ tên cho người đã đồng ý, đánh dấu đồng ý và cấp quyền cho thiết bị.
2. Mở **Đăng ký khuôn mặt**, chọn người, chọn 5–10 mẫu và bắt đầu. Nhìn thẳng rồi nghiêng nhẹ trong khi tiến độ tăng. Khi đủ mẫu, rời hẳn khung khoảng 2 giây rồi quay lại. Nếu báo mặt quá nhỏ, thiếu sáng hoặc mờ, điều chỉnh theo lý do trên màn hình.
3. Xem **Lịch sử truy cập**. Người có quyền nhận lệnh mở 2 giây và xác nhận relay ngắt. Thử người chưa đăng ký. Thu hồi quyền của người đầu tiên, cho họ rời khung rồi quay lại để kiểm tra từ chối ngay lượt sau.
4. Trong **Thiết bị**, quản trị viên có thể mở thử khi thiết bị trực tuyến. Rút đồng ý ở **Sửa** sẽ xóa mẫu đã lưu, mẫu đang thu và mọi quyền của người đó. Khi đăng ký lại có gián đoạn, bộ mẫu hoàn chỉnh trước đó vẫn có hiệu lực.

### Dữ liệu cục bộ

Setup in đường dẫn riêng cho người dùng hiện tại. Trên Windows, dữ liệu nằm dưới Local AppData. Bản Python Microsoft Store có thể dùng thư mục LocalCache của gói. Muốn xem đường dẫn thực, chạy:

    .\.venv\Scripts\python.exe -c "from smartdoor.storage import data_directory; print(data_directory())"

Cùng một bản Python và giá trị SMARTDOOR_HOME phải được dùng cho setup, tải mô hình, backend và simulator. Giữ thư mục này riêng tư. SQLite chứa vector mặt, dữ liệu vận hành và khóa thiết bị. JPEG được xử lý trong bộ nhớ. Máy chủ LAN yêu cầu HTTPS. Cấu hình mẫu cho Git không chứa mật khẩu hoặc khóa thực.

### Firmware và nghiệm thu

- [Cấu hình firmware, HTTPS và thử LY-03 trên bàn](firmware/README.md)
- [Giao thức ký lệnh và quy tắc xử lý lỗi](docs/SMART_DOOR_PROTOCOL.md)
- [Hiệu chỉnh và ghi số liệu nghiệm thu](docs/SMART_DOOR_EVALUATION.md)
- [Mốc AttendAI gốc](https://github.com/ngvanhau1604/Image_Processing_FaceID/tree/e0fd6c910831c1dacd3af27aa1a3f67daf86a014). Tài liệu lớp học, seed và chuyển dữ liệu điểm danh trong lịch sử dự án áp dụng cho AttendAI.

Để tái lập buổi demo tự động qua Chromium, hai mô hình ONNX thật và relay giả lập với hình vẽ tổng hợp:

    .\.venv\Scripts\python.exe -m pip install -r requirements-browser.txt
    .\.venv\Scripts\python.exe -m playwright install chromium
    .\.venv\Scripts\python.exe -m pytest -q --run-door-browser

Mục tiêu khi có bộ phần cứng là thử tối thiểu 5 người, p95 ≤ 5 giây và 30 chu trình điều khiển. Hiện chưa có kết quả đo trên kit, khóa hoặc người tham gia. YuNet và SFace không cung cấp chức năng kiểm tra người sống.
