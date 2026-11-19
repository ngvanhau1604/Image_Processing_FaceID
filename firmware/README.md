# ESP32-S3 N16R8 CAM Kit · wmx88.vn · OV3660

Mục tiêu là bo N16R8 của wmx88.vn, camera OV3660, relay giao tiếp 3,3 V và chốt LY-01 12 V. Sơ đồ chân DVP trong mô tả bán hàng còn thiếu D0–D7 và PCLK theo từng GPIO. Mẫu JSON để trống các chân cần đối chiếu. Dùng sơ đồ của đúng phiên bản PCB hoặc đo thông mạch khi đã ngắt nguồn. Ghi nguồn đối chiếu vào pinout_source. Điền -1 cho PWDN/RESET chỉ khi xác nhận chúng không nối GPIO. Ghi cấu hình thực vào một bản sao ngoài Git. Không dùng pin map MB0184 chỉ vì cùng N16R8.

### Biên dịch

Arduino CLI, core esp32:esp32 3.3.7, FQBN esp32:esp32:esp32s3:FlashSize=16M,PSRAM=opi. Lệnh từ thư mục repo:

    arduino-cli core update-index --additional-urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
    arduino-cli core install esp32:esp32@3.3.7 --additional-urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
    arduino-cli compile --fqbn esp32:esp32:esp32s3:FlashSize=16M,PSRAM=opi firmware/smart_door

Bản này biên dịch ở chế độ chờ, chưa chọn chân, chưa có thông tin mạng. Khi có sơ đồ và bo, dùng môi trường Python của dự án:

    python -m smartdoor.hardware tls 192.168.1.20
    python -m smartdoor.hardware prepare --profile C:/private/board.json --url https://192.168.1.20:8443 --ssid LAB --ntp 192.168.1.20

Thay IP, SSID và máy NTP bằng cấu hình LAN thực. Lệnh prepare hỏi mật khẩu Wi-Fi và tạo sketch riêng ở %LOCALAPPDATA%/FaceID-SmartDoor/firmware/smart_door. Biên dịch và nạp **thư mục riêng đó**. Wi-Fi, khóa và chứng chỉ nằm ngoài Git. Chứng chỉ LAN tự cấp có hạn một năm. Khi thay chứng chỉ gốc, cấp lại cấu hình cho thiết bị. Dùng NTP trong LAN khi không có Internet.

Trên Windows PowerShell:

    $tls = Join-Path $env:LOCALAPPDATA 'FaceID-SmartDoor/tls'
    python scripts/run_web.py --host 0.0.0.0 --port 8443 --cert "$tls/server.pem" --key "$tls/server.key"

Mở cổng server cho mạng LAN thử nghiệm. ESP32 xác minh CA và hostname/IP. Thiếu đồng hồ, lỗi TLS, sai mã cảm biến, mất camera hoặc mất backend đều không tạo xung mở.

### Thử trên bàn

1. Giữ nhánh khóa 12 V ngắt nguồn. Nạp cấu hình chỉ-camera. Đọc Serial 115200 để xác nhận OV3660, thử ảnh JPEG và trạng thái thiết bị trên UI.
2. Xác nhận GPIO riêng, mức kích, khả năng nhận 3,3 V và điện trở kéo bảo đảm relay ngắt từ lúc cấp nguồn đến khi firmware chạy. Kiểm tra lúc reset, mất mạng và mất nguồn bằng tải chỉ thị. Sau khi xác nhận, thêm --enable-verified-relay khi tạo cấu hình và nạp lại.
3. Board nhận 5 V từ USB. Dùng nhánh 12 V riêng cho relay/LY-01, tiếp điểm thường hở, cầu chì và diode dập xung đúng cực trên cuộn khóa. Kiểm tra định mức DC theo đúng linh kiện nhận được. Thử xung 2 giây và đo ở tải. Bộ hẹn giờ trên ESP32 ngắt GPIO độc lập với yêu cầu mạng.
4. Hiệu chỉnh ngưỡng theo camera trước khi nghiệm thu mở tự động. Lưu log thời gian, phản hồi GPIO và quan sát chốt như các bằng chứng riêng.

[Driver camera Espressif](https://github.com/espressif/esp32-camera) · [Giới hạn GPIO ESP32-S3](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/peripherals/gpio.html)
