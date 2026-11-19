# Smart Door · Xác thực mở khóa bằng khuôn mặt

Máy tính Windows xử lý ảnh từ thiết bị trong LAN. Mỗi người tham gia đăng ký và được quản trị viên cấp quyền riêng theo thiết bị. Dữ liệu cục bộ nằm trong %LOCALAPPDATA%\FaceID-SmartDoor.

### Cài đặt trên Windows

Tại thư mục repo, mở PowerShell:

    py -3.11 -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -r requirements-smartdoor.txt
    .\.venv\Scripts\python.exe -m smartdoor.setup
    .\.venv\Scripts\python.exe scripts/run_web.py

Mở http://127.0.0.1:8000 và đăng nhập bằng tài khoản admin cùng mật khẩu vừa đặt. Chạy lại setup giữ mật khẩu đã thiết lập. Không sao chép thư mục dữ liệu sang OneDrive hoặc Git.

Bản điểm danh AttendAI được lưu ở [commit e0fd6c9](https://github.com/ngvanhau1604/Image_Processing_FaceID/tree/e0fd6c910831c1dacd3af27aa1a3f67daf86a014). Các script seed/transfer và tài liệu AttendAI cũ chỉ dùng với bản điểm danh.
