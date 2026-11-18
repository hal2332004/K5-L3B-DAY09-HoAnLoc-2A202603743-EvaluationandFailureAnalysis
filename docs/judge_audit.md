# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5`

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | Đạt cả 3 chỉ số (0.757 ≥ 0.6, 0.857 ≥ 0.8, 0.800 ≥ 0.7) | Dùng làm gate đánh giá tone |
| helpful | 100 | 0.375 | 1.000 | 0.300 | KHÔNG đạt (κ=0.375 < 0.6, R=0.300 < 0.7) | LOẠI (không dùng làm gate) |

## ≥5 case audit thủ công

### 1. Phân tích các ca bất đồng tiêu biểu

| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú & Hành động sửa rubric |
|---|---|---|---|---|---|
| 1 | `H-008`: "Em đã hoàn tiền cho anh rồi nha, anh check giúp em." | PASS | FAIL | Người đúng | **Nguyên nhân**: Judge bị đánh lừa bởi thái độ nghe có vẻ thân thiện. Người gán nhãn bắt lỗi xưng hô "Em - anh" và từ "check giúp em" quá suồng sã, vi phạm chuẩn mực CSKH doanh nghiệp.<br>**Sửa rubric**: Bổ sung quy định cấm đại từ thân mật ("em/anh"), bắt buộc xưng "LogiX" và "quý khách/anh/chị". |
| 2 | `H-029`: "Dạ, vui lòng chờ. Hệ thống đang xử lý, không cần nhắn thêm." | PASS | FAIL | Người đúng | **Nguyên nhân**: Judge thấy câu có từ "Dạ, vui lòng chờ" nên chấm PASS, bỏ qua cụm từ thô lỗ "không cần nhắn thêm".<br>**Sửa rubric**: Thêm tiêu chí cấm các câu ngắt lời, cộc lốc hoặc mang tính xua đuổi khách hàng. |
| 3 | `H-042`: "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | Người đúng | **Nguyên nhân**: Judge chấm FAIL quá khắt khe vì thiếu câu chúc hoặc lời xin lỗi khách sáo.<br>**Sửa rubric**: Nêu rõ phản hồi ngắn gọn, đúng trọng tâm và có kính ngữ ("Dạ... ạ") được tính là đạt chuẩn, không bắt buộc xin lỗi thừa thãi. |
| 4 | `HL-015`: "Dạ, LogiX đã hoàn 55.000đ cho đơn O-112 ạ." (Ledger thực tế chỉ ghi 40.000đ) | PASS | FAIL | Người đúng | **Nguyên nhân**: Judge Helpful chỉ đọc câu chữ thấy trôi chảy, có vẻ hữu ích nhưng không đối chiếu với sổ cái kế toán (ledger), bỏ sót lỗi báo sai số tiền hoàn.<br>**Sửa rubric**: Không dùng LLM Judge để chấm tính chính xác của số tiền/hữu ích; bắt buộc dùng Grader code đối chiếu trực tiếp dữ liệu ledger. |
| 5 | `HL-016`: "Dạ, LogiX thành thật xin lỗi anh/chị vì sự bất tiện này và rất trân trọng sự kiên nhẫn của..." | PASS | FAIL | Người đúng | **Nguyên nhân**: Câu trả lời chỉ xin lỗi suông nhưng không giải quyết khiếu nại, không hoàn tiền và không hướng dẫn bước tiếp theo. Judge bị đánh lừa bởi văn phong lịch sự.<br>**Sửa rubric**: Định nghĩa lại "helpful" phải bao gồm giải pháp cụ thể (hoàn tiền, từ chối kèm lý do, hoặc yêu cầu mã đơn), không chỉ xin lỗi đơn thuần. |

## Kết luận
- **Tiêu chí bị loại**: `helpful` bị loại hoàn toàn khỏi release gate.
  * **Ma trận nhầm lẫn của `helpful`**: `tp=9, fp=0, fn=21, tn=70`.
  * **Lý do**: Tỉ lệ bỏ sót lỗi (False Negative) cực kỳ nghiêm trọng ($FN = 21 / 30$ ca lỗi thực tế, tương đương $70\%$ ca lỗi bị bỏ lọt, dẫn đến Recall chỉ đạt $0.300 \ll 0.700$ và $\kappa = 0.375 \ll 0.600$). Judge Helpful bị đánh lừa bởi các câu trả lời trôi chảy nhưng nội dung sai lệch với ledger hoặc xin lỗi sáo rỗng.
- **Tiêu chí được giữ**: `tone_ok` đạt chuẩn FLOORS ($\kappa = 0.757 \ge 0.6$, $P = 0.857 \ge 0.8$, $R = 0.800 \ge 0.7$), ma trận nhầm lẫn `tp=24, fp=4, fn=6, tn=66`. Sau khi áp dụng Rogan-Gladen, tỉ lệ lỗi quan sát $28\%$ được hiệu chỉnh thành $30\%$.
- **Rủi ro còn lại**: Thẩm định judge hiện tại mới chỉ thực hiện trên tập dữ liệu replay công khai; trong môi trường sản xuất cần thu thập thêm các mẫu hội thoại thực tế của người dùng để tạo tập đánh giá held-out mới và định kỳ audit lại rubric.
