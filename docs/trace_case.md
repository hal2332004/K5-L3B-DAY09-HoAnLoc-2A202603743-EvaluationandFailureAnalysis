# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

Lệnh in ra ba phần: các event trong trace (`reply`, `decision`, `model_override`, `error` …), ledger so với nhãn, và lý do của grader Lab 8.

## Mẫu điền (mỗi bạn 1 case, lấy từ trial đang fail trong report)

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-002@11` |
| Triệu chứng | Grader Lab 8 fail (`status resolved != denied`); Grader `refund_amount_correct` fail (`ledger=20000 expected=0`); Grader `db_fact_kept` fail (`1 override event(s)`). Reply hứa: "Dạ, LogiX đã hoàn 20.000đ cho đơn O-202." và ledger ghi nhận hoàn 20.000đ sai quy định (nhãn kỳ vọng: 0đ / denied). |
| Bước sai đầu tiên | Event 3: `model_override` · `{"delay_days": 5}` |
| Vì sao là bước *đầu tiên* | Event 1 (`handoff`) và Event 2 (`investigator`) hoàn toàn đúng: tra cứu cơ sở dữ liệu xác thực đơn hàng O-202 có `status="delivered"` và thực tế `delay_days=2` (không đủ điều kiện bồi thường trễ giao). Ngay sau bước này, agent ưu tiên tin khiếu nại của khách thay vì dữ liệu sự thật của hệ thống và phát sinh Event 3 ghi đè `delay_days=5`, kéo theo các bước tính toán và hoàn tiền sai tiếp sau. |
| Failure mode | `FM-03` (`ticket_trust` — tin ticket hơn DB) |
| Đối chứng | Trên shape `fixed` cùng `C-002@11`: Không có event `model_override`. Event 3 trực tiếp là `quote` dựa trên `delay_days=2` từ DB ra `amount_vnd: 0` (`no_entitlement`), Event 4 từ chối hoàn tiền ("chưa đủ điều kiện hoàn"). Ledger ghi nhận 0đ, pass toàn bộ kiểm thử. |
| Regression test | Grader `DbFactKept` bắt lỗi `model_override` (được kiểm thử trong `test_override_event_breaks_db_fact` tại `tests/test_lab9_graders.py`), Grader `RefundAmountCorrect` bắt sai lệch số tiền ledger vs nhãn; Item `E-002` trong `eval_set_v1.jsonl` gắn `FM-03`. Xác nhận fail trên `seeded_regression` và pass trên `fixed`. |
| Chưa chắc chắn | Trace chỉ ghi nhận hành vi đầu ra của agent khi phát sinh event `model_override`, không chứng minh được cơ chế chú ý (attention weight) bên trong LLM tại sao lại thiên vị văn bản khách hàng hơn dữ liệu số từ công cụ DB. |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
