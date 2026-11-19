# Nghiệm thu Smart Door

## Đã kiểm tra bằng phần mềm

Bài kiểm tra Chromium dùng hai khuôn mặt vẽ bằng OpenCV, đăng ký 5 JPEG khác nhau, phát hiện bằng YuNet, căn chỉnh/trích vector bằng SFace thật trên CPU, mở relay giả lập, nhận ACK rồi thử người lạ và người bị thu hồi quyền. Bài kiểm thử giao thức dùng dữ liệu tổng hợp để tạo các lỗi một cách lặp lại. CI biên dịch firmware ở cả cấu hình khóa đầu ra và cấu hình tích hợp với thông số giả. Các con số từ những phép thử này chỉ mô tả phần mềm.

## Hiệu chỉnh bằng bộ kit

1. Lắp camera đã đối chiếu đúng chân. Chưa nối tải khóa. Đăng ký tối thiểu 5 người tự nguyện, mỗi người 5–10 mẫu. Ghi riêng mã phiên đăng ký. Cho người vừa đăng ký rời khung trước lượt mới.
2. Trong một phiên khác, dùng chính OV3660 chụp từng người đã đăng ký và người chưa đăng ký đồng ý thử. Trước hiệu chỉnh, sự kiện có lý do calibration_required và điểm so khớp, relay giữ tắt. Dùng mã request in qua Serial hoặc trả về từ API lịch sử (quyền admin).
3. Lập CSV riêng với dòng đầu **request,expected_code,session**. Mỗi dòng ghi mã lượt, mã người thật hoặc UNKNOWN và mã phiên hiệu chỉnh. Mỗi lượt dùng một lần. Không lưu file cá nhân lên Git.
4. Chạy thử rồi áp dụng bộ ngưỡng sau khi xem số mẫu và số nhận đúng:

       python -m smartdoor.evaluate calibrate labels.csv --device door-kit
       python -m smartdoor.evaluate calibrate labels.csv --device door-kit --apply

   Công cụ thử các cặp ngưỡng cosine và chênh lệch hai người đứng đầu, ưu tiên 0 nhận nhầm trên tập hiệu chỉnh rồi tối đa số lượt đúng. Nếu hòa, chọn ngưỡng chặt hơn. Dữ liệu thiếu người lạ hoặc không tìm được ngưỡng đều giữ nguyên cấu hình. Ghi lại phiên bản mẫu, vị trí camera và ánh sáng. Hiệu chỉnh lại sau khi thay camera hoặc mô hình.

## Đo độc lập trên bàn

Dùng phiên mới với nhiều lượt cho từng điều kiện và cùng tiêu chí trước khi xem kết quả. Đo từ đầu thu ảnh tới khi thiết bị xác minh quyết định. Đọc latency_ms theo request qua Serial. Timeout ghi riêng. Đo độ dài xung ở nhánh tải và quan sát chốt trực tiếp. ACK chỉ mô tả điều khiển GPIO.

| Thử nghiệm | Mục tiêu | Bằng chứng phần cứng |
| --- | --- | --- |
| Tối thiểu 5 người, sáng tốt/yếu, thay đổi góc | Ít nhất 90% lượt hợp lệ cấp đúng người | Chờ đo |
| Người lạ, đã thu hồi, nhiều mặt | 0 lần kích mở trong các lượt không hợp lệ | Chờ đo |
| Độ trễ LAN, CPU Windows | p95 ≤ 5000 ms | Chờ đo |
| Khóa LY-03 | Xung khoảng 2 s, từng lần dưới 5 s theo mô tả nhà bán | Chờ đo |
| Mất mạng, tắt backend, reset bo, mất ACK | Không phát sinh xung ngoài ý muốn | Chờ đo |
| Tối thiểu 30 chu trình mở/ngắt | Ghi số xung, thời gian, số lỗi và quan sát chốt | Chờ đo |
| Ảnh in và video phát lại | Báo cáo số lần nhận/từ chối riêng theo từng loại | Chờ đo |

Dòng đầu CSV nghiệm thu:

    request,scenario,session,condition,expected_code,recognized_code,result,pulse,pulse_ms,latency_ms

scenario dùng authorized, unknown, revoked, multiple, empty, print, video, fault hoặc cycle. result dùng GRANTED, DENIED, ERROR hoặc TIMEOUT. pulse dùng yes, no hoặc unobserved. Ghi riêng mã lượt kể cả khi timeout. Ghi actual recognized_code khi có kết quả danh tính. Chỉ nhập pulse_ms khi có quan sát xung, và ghi rõ nguồn đo trong condition. Chạy báo cáo:

    python -m smartdoor.evaluate report trials.csv --camera OV3660 --device door-kit --evidence bench

Báo cáo gồm commit Git, model, tập hiệu chỉnh, số lượt/điều kiện, số kết quả từng loại và p50/p95 kiểu nearest-rank của các lượt đo thành công. Ghi kèm số TIMEOUT khi trích kết quả. Với dữ liệu mô phỏng dùng --device webcam-demo --evidence simulator. Xem riêng trường ly03_pulse_limit_exceeded. Chưa có đánh giá độ chính xác người thật, khả năng chống giả hoặc độ bền vật lý.
