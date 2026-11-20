# Đồ án IoT: Xác thực khuôn mặt mở khóa điện — 20/11/2026

**Trạng thái: bản nguyên mẫu phần mềm, chưa đo kiểm phần cứng. KHÔNG dùng bảo vệ cửa thật.**
Pipeline hiện tại chưa có liveness/PAD nên vẫn có thể bị đánh lừa bởi ảnh/video.

## Thiết kế đã chốt

- Camera / MCU: Keyestudio MB0184 ESP32-S3-CAM N16R8 (OV3660, Flash 16 MB, PSRAM 8 MB).
- Xử lý AI: laptop chạy Python, Face ID dlib/ResNet, FastAPI, SQLite; ESP32 không xử lý embedding.
- Khóa hiện có: LY-03 DC 12 V ghi 0,35 A (danh định 4,2 W); nguồn hiện có 12 V/1 A đầu tròn.
- Chưa mua/chốt và kiểm chứng: module relay hoặc MOSFET/driver, diode bảo vệ xung ngược, dây và cầu chì, chân GPIO điều khiển.
- Board cấp 5 V bằng USB-C, không cấp 12 V trực tiếp vào board/GPIO. Nguồn 12 V dùng nhánh khóa qua driver phù hợp.

Nguồn 12 V/1 A có thể đủ theo dòng danh định 0,35 A của chiếc khóa đã có, nhưng
chưa đo dòng hút ban đầu, cực tính, chế độ làm việc và không được mặc nhiên kết
luận đủ với mọi biến thể LY-03 (một số bản có dòng cao hơn).

## Kiến trúc

ESP32-S3 OV3660 -> Wi-Fi (HTTPS) -> laptop FastAPI/Face ID -> quyết định ký HMAC
-> ESP32 kiểm tra chữ ký, nonce và thời hạn -> GPIO qua relay/driver -> LY-03.

Xử lý mở khóa mặc định **OFF**. Backend không sử dụng quyền điểm danh làm quyền
mở khóa mặc định: cần danh sách Student.id được cấp quyền riêng, người tham gia
đồng ý, đủ 5 góc embedding đang hoạt động ở đúng model/profile. Camera chỉ
gửi JPEG; ảnh không được lưu bởi endpoint cửa.

## Trạng thái triển khai

| Hạng mục | Trạng thái |
| --- | --- |
| Face ID / đăng ký 5 góc / FastAPI / SQLite | IMPLEMENTED (từ AttendAI) |
| API /iot/door/capture: HMAC, thời gian, nonce, kiểm ảnh JPEG | IMPLEMENTED |
| Chỉ cho ID trong allowlist, đủ 5 góc, đồng ý và khớp model | IMPLEMENTED |
| Xác nhận ít nhất 3 khung khác nhau trong 8 giây, cooldown 5 giây | IMPLEMENTED |
| Phản hồi JSON ký HMAC; log quyết định trước lệnh mở | IMPLEMENTED |
| Unit tests logic protocol | TEST CODE ADDED, chưa có kết quả chạy |
| Firmware ESP32 / GPIO / relay / khóa / TLS | PENDING, chưa flash và test |
| Liveness/PAD, audit trong nhiều worker, vận hành production | NOT IMPLEMENTED |

Bản AttendAI cũ vẫn hiện diện và tài liệu ở docs/SYSTEM.md mô tả phân hệ kế
thừa, không thể dùng làm chứng cứ đã hoàn thành mạch IoT.

## Định dạng API thiết bị

POST /iot/door/capture, Content-Type: image/jpeg, tối đa 250.000 byte.
Các HTTP headers cần có: X-Device-ID; X-Timestamp (Unix UTC giây);
X-Nonce (16 byte random biểu diễn 32 hex thường); X-Signature (64 hex SHA256).

Chữ ký request HMAC-SHA256 với message dạng:
device_id + newline + timestamp + newline + nonce + newline + sha256_hex(jpeg).
Backend chỉ nhận timestamp lệch không quá 15 giây và nonce chưa dùng.
Response JSON gồm decision (denied/pending/cooldown/unlock), reason,
request_nonce, valid_until (Unix UTC) và unlock_ms (0 khi không cấp quyền).
HMAC response được tính trên đúng các bytes JSON gửi đi và đặt trong
X-Door-Response-Signature. Firmware phải kiểm tra cả chữ ký, nonce, hạn dùng
và giới hạn xung trước khi kích khóa. Không coi phản hồi HTTP 200 là quyền mở.

Nonce replay guard hiện chỉ lưu RAM trong một process; restart sẽ mất lịch sử.
Không chạy uvicorn nhiều worker cho demo mà không thay bằng store dùng chung.
3 ảnh khác nhau là xác nhận nhiều lần, KHÔNG phải chống giả mạo khuôn mặt.
Cần HTTPS với CA được kiểm chứng (không dùng insecure TLS) để bảo vệ dữ liệu mặt.

## Cấu hình backend

Sao chép .env.example thành .env, giữ hệ thống tắt cho đến khi kiểm tra.

- IOT_DOOR_ENABLED=false
- IOT_DOOR_DEVICE_ID=door-demo-01
- IOT_DOOR_HMAC_SECRET= (để trống: không hoạt động)
- IOT_DOOR_ALLOWED_STUDENT_IDS= (để trống: không có quyền)
- IOT_DOOR_MIN_HITS=3
- IOT_DOOR_UNLOCK_MS=2000 (xung tối đa 2 giây)

Tạo secret bằng: python -c "import secrets; print(secrets.token_hex(32))".
Chỉ khi có secret thực và người tham gia đã đồng ý thì mới cấp quyền rõ ràng
bằng các ID trong bảng Student, ví dụ IOT_DOOR_ALLOWED_STUDENT_IDS=1,4.
Không dùng mã sinh viên, tài khoản đăng nhập hay số thứ tự giao diện làm ID.

Cài engine Face ID theo README cũ; chạy python -m pytest -q
tests/test_iot_door.py để kiểm logic. Địa chỉ 127.0.0.1 là địa chỉ laptop,
không thể dùng từ ESP32; cấu hình LAN + HTTPS chứng chỉ hợp lệ.

## Điện và thử nghiệm còn thiếu

1. Chụp ảnh nhãn, xác nhận loại LY-03, đo dòng lúc hút và kiểm tra nhiệt/độ rộng xung.
2. Xác minh sơ đồ board và relay/driver thực tế, mức kích 3,3 V, mức khi boot,
   COM/NO với relay, chân GPIO ra header và diode flyback phân cực đúng.
3. Không đưa dòng khóa qua GPIO hoặc breadboard; dùng nhánh nguồn 12 V riêng
   với driver, dây và cầu chì phù hợp. ESP32 nhận 5 V qua USB-C.
4. Thử bằng LED/tải giả trước, rồi mới nối LY-03; thử rớt Wi-Fi, reset, mất AI,
   trùng nonce, sai chữ ký, người lạ, nhiều mặt, ảnh/video giả.
5. Lấy chứng cứ thực nghiệm: độ trễ, số lần nhận đúng/sai, thời gian mở, nhiệt,
   mức dòng, và ảnh wiring thực tế. Phân biệt TESTED với HARDWARE_VERIFIED.

## Tài liệu tham khảo để xác minh pinout, biến thể khóa

- Hãng Keyestudio MB0184:
  https://docs.keyestudio.com/projects/MB0184/en/latest/docs/MB0184%20ESP32-S3%20CAM%20Development%20Board.html
- LY-03 0,35 A (tham khảo đúng biến thể):
  https://nshopvn.com/product/khoa-chot-dien-tu-ly-03-12vdc-tiet-kiem-nang-luong/
- Biến thể LY-03 có thông số khác nhau:
  https://lkcg.vn/khoa-chot-dien-tu-ly-03-12vdc
