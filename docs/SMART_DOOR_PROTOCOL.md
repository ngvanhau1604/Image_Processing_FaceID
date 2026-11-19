# Giao thức Smart Door v1

ESP32 chủ động gửi một JPEG tại một thời điểm. Simulator dùng cùng giao thức. Giới hạn mỗi ảnh 1 MB, tối đa 2048 pixel mỗi chiều. Kiểm tra quyền dựa trên người được nhận diện trong toàn bộ tập người đồng ý. Thiết bị thực chỉ được mở tự động sau khi hiệu chỉnh đúng thiết bị và phiên bản mô hình.

    ESP32 / Webcam → JPEG + HMAC → FastAPI → YuNet → chất lượng → căn chỉnh SFace
                                        ↓
                         so cosine → kiểm tra quyền SQLite
                                        ↓
    Relay ← kiểm chữ ký, thời hạn ← quyết định đã ghi sự kiện
      └── ACK đã kích / đã ngắt ──────────→ lịch sử trên giao diện

## Yêu cầu và phản hồi

POST /api/v1/access/verify nhận JPEG nhị phân. POST /api/v1/access/ack nhận ba dòng ASCII gồm request_id của lệnh mở, started hoặc stopped và số mili giây. started gửi 0. stopped gửi độ dài xung do thiết bị đo. Cả hai dùng X-Device, X-Boot, X-Request, X-Nonce, X-Sent (Unix ms) và X-Signature. Mỗi boot/request/nonce là 32 ký tự hex thường. Mỗi lần gửi ACK lại phải tạo request/nonce mới và giữ nguyên mã lệnh gốc.

HMAC-SHA256 dùng khóa 32 byte giải mã từ hex. Chuỗi ký nối từng trường bằng LF, không có LF cuối. Chữ ký hex thường. Yêu cầu ký theo thứ tự:

    v1 | đường dẫn API | device | boot | request | nonce | sent | sha256(body)

Phản hồi verify dạng text/plain 5 dòng: quyết định, lý do, thời điểm hết hạn (Unix ms), độ dài xung (0 hoặc 2000) và chữ ký. Chuỗi ký phản hồi:

    reply | device | boot | request | nonce | sent | quyết định | lý do | hết hạn | độ dài xung

Dấu | trong tài liệu biểu thị ranh giới trường. Kiểm tra thời gian UTC và thời gian chờ bằng đồng hồ đơn điệu tại thiết bị. Backend từ chối yêu cầu quá 6500 ms hoặc đi trước hơn 1000 ms. Lệnh có hiệu lực tối đa 2500 ms kể từ lúc xử lý xong, đồng thời chịu giới hạn 6500 ms từ lúc gửi. Thiết bị thật yêu cầu TLS xác minh máy chủ. Khi DB không thể ghi và commit sự kiện, backend không trả lệnh cấp quyền.

## Trạng thái điều khiển

- Quyết định GRANTED được ghi trước khi gửi. Khi mất ACK, lịch sử hiển thị chưa có xác nhận. ACK stopped có thể cập nhật trực tiếp nếu mất started. ACK đến muộn không làm trạng thái lùi. Chưa có cảm biến xác nhận cửa.
- Mỗi phản hồi gắn với đúng lượt chờ. Thiết bị phát tối đa một xung rồi hủy lượt đó. Backend khóa lượt tự động tiếp theo cho đến khi nhận nhiều khung không mặt liên tiếp trong ít nhất một giây. Bản ghi này nằm trong SQLite qua các lần khởi động.
- Đăng ký là một phiên riêng theo người và thiết bị, hạn 3 phút. Người đăng ký lại dùng bộ mẫu cũ cho đến khi đủ bộ mới. Hủy phiên hoặc rút đồng ý xóa mẫu tạm. Trong lúc thu, cả thao tác mở thử cũng bị chặn.
- Đăng nhập quản trị dùng cookie HttpOnly, SameSite Strict, Secure khi chạy HTTPS. Danh sách người, cấp quyền, lịch sử, trạng thái máy, mở phiên thu và mở thử đều yêu cầu đăng nhập. Mở thử có thời hạn 5 giây và ghi tài khoản thao tác.
