from __future__ import annotations
from typing import Any

PROMPTS: dict[str, Any] = {}

# All delimiters must be formatted as "<|UPPER_CASE_STRING|>"
PROMPTS["DEFAULT_TUPLE_DELIMITER"] = "<|#|>"
PROMPTS["DEFAULT_COMPLETION_DELIMITER"] = "<|COMPLETE|>"

# ============================================================
# ENTITY TYPES — Loại thực thể pháp lý Việt Nam
# ============================================================
# Dùng danh sách này làm giá trị mặc định khi gọi extraction
PROMPTS["DEFAULT_ENTITY_TYPES"] = [
    "VanBanPhapLuat",  # Luật, Nghị định, Thông tư, Quyết định, Chỉ thị, Nghị quyết, Pháp lệnh
    "DieuKhoan",  # Điều, Khoản, Điểm, Chương, Mục cụ thể trong văn bản
    "CoQuan",  # Cơ quan ban hành hoặc thực thi (Chính phủ, Bộ, UBND...)
    "ChuThe",  # Tổ chức / cá nhân chịu sự điều chỉnh (doanh nghiệp, công dân...)
    "KhaiNiem",  # Khái niệm / định nghĩa pháp lý được quy định trong văn bản
    "LinhVuc",  # Lĩnh vực / ngành áp dụng (đất đai, thuế, lao động, BHXH...)
    "LuatDomain",  # Nhóm pháp lý chuyên ngành — phân loại theo lĩnh vực: "Luật AI", "Luật CNTT & Viễn thông", "Luật Lao động & BHXH", "Luật Tài chính - Ngân hàng", "Luật Đất đai - Bất động sản", "Luật Doanh nghiệp - Thương mại", "Luật Hình sự - Tố tụng", "Luật Hành chính", "Luật Dân sự", "Luật Môi trường", "Luật Y tế", "Luật Giáo dục"
    "ThoiHan",  # Thời hạn, ngày hiệu lực, thời điểm áp dụng của văn bản pháp luật
    "DiaDiem",  # Địa phương, vùng lãnh thổ áp dụng
    "ThuTuc",  # Quy trình, thủ tục hành chính được quy định
    "MucPhat",  # Mức phạt, chế tài, hình thức xử lý vi phạm
]

PROMPTS["entity_extraction_system_prompt"] = """---Vai trò---
Bạn là Chuyên gia Đồ thị Tri thức Pháp luật, chuyên trích xuất thực thể và quan hệ từ các văn bản quy phạm pháp luật Việt Nam.

---Mục tiêu cốt lõi---
Nhiệm vụ QUAN TRỌNG NHẤT là nhận diện chính xác **quan hệ pháp lý giữa các văn bản** — đặc biệt là quan hệ sửa đổi, bãi bỏ, bổ sung, thay thế và hướng dẫn thi hành. Đây là nền tảng để hệ thống hiểu được hiệu lực thực tế của từng quy định.

---Tiêu chí thành công bắt buộc---
- Nếu văn bản có tín hiệu như: `sửa đổi`, `bổ sung`, `thay thế`, `bãi bỏ`, `hết hiệu lực`, `đính chính`, `được sửa đổi bởi`, `được bổ sung bởi`, `quy định chi tiết thi hành`, thì **bắt buộc** phải trích xuất ít nhất 1 quan hệ pháp lý tương ứng.
- Ưu tiên quan hệ giữa `VanBanPhapLuat` ↔ `VanBanPhapLuat`, sau đó đến quan hệ `VanBanPhapLuat` ↔ `DieuKhoan`.
- Không dùng từ khóa mơ hồ kiểu `liên quan`, `kết nối`, `tham chiếu chung` khi có thể gán vào nhóm quan hệ pháp lý cụ thể.
- **Bắt buộc** trích xuất thực thể `LuatDomain` cho mỗi văn bản, phân vào đúng nhóm chuyên ngành (ví dụ: "Luật CNTT & Viễn thông", "Luật Lao động", "Luật AI"...).
- **Bắt buộc** trích xuất thực thể `ThoiHan` ghi rõ ngày hiệu lực của văn bản nếu có ("có hiệu lực từ ngày...").
- Khi có ngày hiệu lực, thêm quan hệ `hiệu lực` từ `VanBanPhapLuat` đến thực thể `ThoiHan` tương ứng để hệ thống biết phiên bản nào đang có hiệu lực.

---Hướng dẫn trích xuất---

### 1. Trích xuất Thực thể (Entity)

**Nhận diện** các thực thể rõ ràng, có ý nghĩa trong văn bản.

Với mỗi thực thể, trích xuất:
- `entity_name`: Tên thực thể. Viết **đúng ký hiệu gốc** của văn bản (vd: "Nghị định 15/2022/NĐ-CP"). Đảm bảo **nhất quán** tên xuyên suốt toàn bộ quá trình trích xuất.
- `entity_type`: Phân loại theo một trong các loại: `{entity_types}`. Nếu không phù hợp loại nào, dùng `KhaiNiem`.
  - Lưu ý đặc biệt với `LuatDomain`: Mỗi văn bản pháp luật phải được gắn vào **đúng một** nhóm chuyên ngành (ví dụ: "Luật CNTT & Viễn thông" cho Luật An toàn thông tin mạng, "Luật Lao động & BHXH" cho các nghị định về lao động nước ngoài...). Tạo quan hệ `thuộc lĩnh vực` từ `VanBanPhapLuat` → `LuatDomain`.
- `entity_description`: Mô tả súc tích nhưng đầy đủ về thực thể, **chỉ dựa vào thông tin có trong văn bản**.

**Định dạng đầu ra — Thực thể** (4 trường, phân tách bởi `{tuple_delimiter}`, trên một dòng):
```
entity{tuple_delimiter}entity_name{tuple_delimiter}entity_type{tuple_delimiter}entity_description
```

---

### 2. Trích xuất Quan hệ (Relationship) — ƯU TIÊN CAO NHẤT

**Nhận diện và phân loại chính xác** các quan hệ pháp lý giữa các thực thể đã trích xuất.

#### 2.1 Bảng quan hệ pháp lý ưu tiên

| Quan hệ (`relationship_keywords`) | Dấu hiệu nhận diện trong văn bản |
|---|---|
| `sửa đổi, bổ sung` | "sửa đổi, bổ sung ... Nghị định/Thông tư số..." |
| `bãi bỏ` | "bãi bỏ", "không còn hiệu lực", "hết hiệu lực" |
| `thay thế` | "thay thế", "thay thế cho", "thay bằng" |
| `thay thế toàn bộ` | "thay thế Nghị định/Thông tư ... trước đây" |
| `đính chính` | "đính chính", "điều chỉnh lại lỗi kỹ thuật" |
| `được sửa đổi bởi` | "được sửa đổi bởi", "đã được sửa đổi bởi" |
| `được bổ sung bởi` | "được bổ sung bởi", "đã được bổ sung bởi" |
| `hướng dẫn thi hành` | "hướng dẫn thi hành", "quy định chi tiết thi hành" |
| `căn cứ pháp lý` | "Căn cứ Luật...", "Căn cứ Nghị định...", phần "Căn cứ" đầu văn bản |
| `quy định chi tiết` | "quy định chi tiết Điều ... của Luật..." |
| `áp dụng cho` | đối tượng điều chỉnh, phạm vi áp dụng |
| `giao nhiệm vụ` | "giao Bộ ... chủ trì", "UBND ... có trách nhiệm" |
| `chế tài, xử phạt` | mức phạt áp dụng với hành vi vi phạm cụ thể |
| `định nghĩa, giải thích` | điều khoản giải thích thuật ngữ |
| `điều kiện, tiêu chuẩn` | điều kiện để được cấp phép, công nhận |
| `chuyển tiếp, gia hạn` | điều khoản chuyển tiếp, thời gian gia hạn áp dụng |
| `thuộc lĩnh vực` | văn bản thuộc nhóm pháp lý chuyên ngành (`LuatDomain`) |
| `hiệu lực` | ngày văn bản có hiệu lực thi hành (liên kết đến `ThoiHan`) |

#### 2.2 Quy tắc phân rã quan hệ N-ngôi

Nếu một câu mô tả quan hệ giữa nhiều hơn 2 thực thể, **phân rã thành các cặp nhị phân**:
- "Nghị định X sửa đổi Điều 5 và Điều 7 của Nghị định Y" → hai quan hệ riêng biệt.
- "Bộ A và Bộ B phối hợp hướng dẫn thi hành Nghị định Z" → hai quan hệ riêng biệt.

#### 2.3 Trường thông tin Quan hệ

- `source_entity`: Tên thực thể nguồn (nhất quán với tên đã trích xuất).
- `target_entity`: Tên thực thể đích (nhất quán với tên đã trích xuất).
- `relationship_keywords`: Một hoặc nhiều từ khóa tóm tắt bản chất quan hệ, **phân tách bằng dấu phẩy `,`** (KHÔNG dùng `{tuple_delimiter}`).
- `relationship_description`: Giải thích ngắn gọn bản chất quan hệ, nêu rõ cơ sở pháp lý (số điều, khoản nếu có).

#### 2.4 Chuẩn hóa từ khóa quan hệ (khuyến nghị mạnh)

- Chỉ dùng các từ khóa trong bảng ưu tiên ở mục 2.1 khi có đủ căn cứ.
- Nếu một quan hệ có nhiều bản chất, sắp xếp từ khóa theo độ pháp lý quan trọng: `thay thế toàn bộ` > `thay thế` > `bãi bỏ` > `sửa đổi, bổ sung` > `hướng dẫn thi hành` > `quy định chi tiết` > `căn cứ pháp lý` > `áp dụng cho` > `giao nhiệm vụ`.
- Khi văn bản nêu rõ điều/khoản bị tác động, phải phản ánh trong `relationship_description` (ví dụ: "sửa đổi khoản 1 Điều 3...").

#### 2.5 Danh sách kiểm tra trước khi kết thúc

Trước khi xuất `{completion_delimiter}`, tự kiểm tra:
1. Có ít nhất một quan hệ pháp lý trực tiếp giữa các văn bản nếu văn bản có tín hiệu sửa đổi/thay thế/bãi bỏ.
2. Nếu có cụm "Điều..., Khoản..., Điểm... của [Văn bản]", đã tạo quan hệ với `DieuKhoan` tương ứng.
3. Không có quan hệ trùng nghĩa chỉ khác thứ tự từ hoặc đổi vị trí source/target.
4. Mỗi quan hệ đều có `relationship_keywords` cụ thể, không dùng nhãn chung chung.

**Định dạng đầu ra — Quan hệ** (5 trường, phân tách bởi `{tuple_delimiter}`, trên một dòng):
```
relation{tuple_delimiter}source_entity{tuple_delimiter}target_entity{tuple_delimiter}relationship_keywords{tuple_delimiter}relationship_description
```

---

### 3. Quy tắc sử dụng `{tuple_delimiter}`

`{tuple_delimiter}` là ký hiệu phân tách trường, **tuyệt đối không** chèn nội dung vào bên trong ký hiệu này.
- ❌ Sai: `entity{tuple_delimiter}Nghị định 15<|VanBanPhapLuat|>Nghị định về thuế GTGT`
- ✅ Đúng: `entity{tuple_delimiter}Nghị định 15/2022/NĐ-CP{tuple_delimiter}VanBanPhapLuat{tuple_delimiter}Nghị định về miễn, giảm thuế GTGT`

---

### 4. Thứ tự đầu ra & Ưu tiên

- Xuất toàn bộ **thực thể trước**, sau đó mới xuất **quan hệ**.
- Trong danh sách quan hệ, ưu tiên xuất **quan hệ pháp lý trực tiếp giữa văn bản** (sửa đổi, bãi bỏ, hướng dẫn thi hành) trước.

---

### 5. Tính khách quan & Ngôn ngữ

- Toàn bộ đầu ra viết bằng **tiếng Việt**, ngôi thứ ba.
- Giữ nguyên tên văn bản, ký hiệu số, tên cơ quan theo nguyên gốc.
- Tránh dùng đại từ "bài này", "văn bản này", "theo đó".

---

### 6. Kết thúc

Sau khi đã xuất đầy đủ tất cả thực thể và quan hệ, xuất ký hiệu `{completion_delimiter}` trên một dòng riêng.

---Ví dụ---
{examples}
"""

PROMPTS["entity_extraction_user_prompt"] = """---Nhiệm vụ---
Trích xuất thực thể và quan hệ từ văn bản pháp luật trong phần Dữ liệu cần xử lý dưới đây.

---Hướng dẫn---
1. **Tuân thủ nghiêm ngặt định dạng**: Tuân thủ toàn bộ yêu cầu định dạng cho danh sách thực thể và quan hệ (thứ tự xuất, ký hiệu phân tách, xử lý danh từ riêng) như quy định trong system prompt.
2. **Chỉ xuất kết quả**: Chỉ xuất danh sách thực thể và quan hệ. Không thêm lời mở đầu, giải thích hay bình luận.
3. **Ký hiệu kết thúc**: Xuất `{completion_delimiter}` trên dòng cuối cùng sau khi đã trích xuất xong.
4. **Ngôn ngữ đầu ra**: Đảm bảo toàn bộ đầu ra bằng {language}. Giữ nguyên danh từ riêng (tên văn bản, tên cơ quan, ký hiệu số) theo nguyên gốc, không dịch.
5. **Ưu tiên quan hệ pháp lý**: Nếu có dấu hiệu sửa đổi/bổ sung/thay thế/bãi bỏ/hết hiệu lực, bắt buộc trích xuất quan hệ pháp lý tương ứng trước các quan hệ phụ trợ.

---Dữ liệu cần xử lý---
<Entity_types>
[{entity_types}]

<Văn bản đầu vào>
```
{input_text}
```

<Đầu ra>
"""

PROMPTS["entity_continue_extraction_user_prompt"] = """---Nhiệm vụ---
Dựa trên lần trích xuất trước, xác định và trích xuất các thực thể và quan hệ còn **bị bỏ sót hoặc định dạng sai**.

---Hướng dẫn---
1. **Tuân thủ định dạng system**: Tuân thủ toàn bộ yêu cầu định dạng như quy định trong system instructions.
2. **Tập trung vào bổ sung / sửa lỗi**:
   - **KHÔNG** xuất lại các thực thể và quan hệ đã được trích xuất **đúng và đầy đủ**.
   - Nếu thực thể/quan hệ **bị bỏ sót**, trích xuất và xuất ngay bây giờ theo đúng định dạng.
   - Nếu thực thể/quan hệ bị **cắt ngắn, thiếu trường hoặc định dạng sai**, xuất lại **phiên bản đầy đủ và đúng**.
3. **Định dạng — Thực thể**: 4 trường, phân tách bởi `{tuple_delimiter}`, trên một dòng, trường đầu là `entity`.
4. **Định dạng — Quan hệ**: 5 trường, phân tách bởi `{tuple_delimiter}`, trên một dòng, trường đầu là `relation`.
5. **Chỉ xuất kết quả**: Không thêm giải thích hay bình luận.
6. **Ký hiệu kết thúc**: Xuất `{completion_delimiter}` trên dòng cuối.
7. **Ngôn ngữ**: Toàn bộ đầu ra bằng {language}. Giữ nguyên danh từ riêng.
8. **Bổ sung bắt buộc**: Nếu lần trước thiếu quan hệ sửa đổi/thay thế/bãi bỏ/hết hiệu lực dù văn bản có nêu, phải bổ sung đầy đủ ở lần này.

<Đầu ra>
"""

PROMPTS["entity_extraction_examples"] = [
    # ---- VÍ DỤ 1: Quan hệ sửa đổi, bổ sung ----
    """<Entity_types>
["VanBanPhapLuat","DieuKhoan","CoQuan","ChuThe","KhaiNiem","LinhVuc","ThoiHan","DiaDiem","ThuTuc","MucPhat"]

<Văn bản đầu vào>
```
NGHỊ ĐỊNH 70/2023/NĐ-CP

Sửa đổi, bổ sung một số điều của Nghị định 152/2020/NĐ-CP quy định về người lao động nước ngoài làm việc tại Việt Nam và tuyển dụng, quản lý người lao động Việt Nam làm việc cho tổ chức, cá nhân nước ngoài tại Việt Nam.

Điều 1. Sửa đổi, bổ sung một số điều của Nghị định số 152/2020/NĐ-CP ngày 30 tháng 12 năm 2020 của Chính phủ quy định về người lao động nước ngoài làm việc tại Việt Nam:

1. Sửa đổi, bổ sung khoản 1 Điều 3 như sau:
"1. Người lao động nước ngoài làm việc tại Việt Nam là người mang quốc tịch nước ngoài, đủ 18 tuổi trở lên, có năng lực hành vi dân sự đầy đủ..."

Điều 2. Bộ Lao động - Thương binh và Xã hội có trách nhiệm hướng dẫn thi hành Nghị định này.

Điều 3. Nghị định này có hiệu lực thi hành từ ngày 18 tháng 9 năm 2023.
```

<Đầu ra>
entity{tuple_delimiter}Nghị định 70/2023/NĐ-CP{tuple_delimiter}VanBanPhapLuat{tuple_delimiter}Nghị định do Chính phủ ban hành, sửa đổi bổ sung Nghị định 152/2020/NĐ-CP về người lao động nước ngoài làm việc tại Việt Nam. Có hiệu lực từ ngày 18/9/2023.
entity{tuple_delimiter}Nghị định 152/2020/NĐ-CP{tuple_delimiter}VanBanPhapLuat{tuple_delimiter}Nghị định ngày 30/12/2020 của Chính phủ quy định về người lao động nước ngoài làm việc tại Việt Nam và tuyển dụng, quản lý người lao động Việt Nam làm việc cho tổ chức, cá nhân nước ngoài tại Việt Nam. Bị sửa đổi một số điều bởi Nghị định 70/2023/NĐ-CP.
entity{tuple_delimiter}Khoản 1 Điều 3 Nghị định 152/2020/NĐ-CP{tuple_delimiter}DieuKhoan{tuple_delimiter}Khoản quy định khái niệm "người lao động nước ngoài làm việc tại Việt Nam", được sửa đổi bổ sung bởi Điều 1 Nghị định 70/2023/NĐ-CP.
entity{tuple_delimiter}Bộ Lao động - Thương binh và Xã hội{tuple_delimiter}CoQuan{tuple_delimiter}Bộ được giao trách nhiệm hướng dẫn thi hành Nghị định 70/2023/NĐ-CP.
entity{tuple_delimiter}Người lao động nước ngoài{tuple_delimiter}ChuThe{tuple_delimiter}Đối tượng điều chỉnh của Nghị định, là người mang quốc tịch nước ngoài, đủ 18 tuổi, có năng lực hành vi dân sự đầy đủ, làm việc tại Việt Nam.
entity{tuple_delimiter}Lao động nước ngoài{tuple_delimiter}LinhVuc{tuple_delimiter}Lĩnh vực điều chỉnh của các nghị định liên quan, bao gồm tuyển dụng, cấp phép và quản lý người lao động nước ngoài tại Việt Nam.
entity{tuple_delimiter}18/9/2023{tuple_delimiter}ThoiHan{tuple_delimiter}Ngày Nghị định 70/2023/NĐ-CP có hiệu lực thi hành.
relation{tuple_delimiter}Nghị định 70/2023/NĐ-CP{tuple_delimiter}Nghị định 152/2020/NĐ-CP{tuple_delimiter}sửa đổi, bổ sung{tuple_delimiter}Nghị định 70/2023/NĐ-CP sửa đổi, bổ sung một số điều của Nghị định 152/2020/NĐ-CP về người lao động nước ngoài làm việc tại Việt Nam.
relation{tuple_delimiter}Nghị định 70/2023/NĐ-CP{tuple_delimiter}Khoản 1 Điều 3 Nghị định 152/2020/NĐ-CP{tuple_delimiter}sửa đổi, bổ sung{tuple_delimiter}Điều 1 Nghị định 70/2023/NĐ-CP sửa đổi bổ sung nội dung khoản 1 Điều 3 Nghị định 152/2020/NĐ-CP về định nghĩa người lao động nước ngoài.
relation{tuple_delimiter}Bộ Lao động - Thương binh và Xã hội{tuple_delimiter}Nghị định 70/2023/NĐ-CP{tuple_delimiter}hướng dẫn thi hành, giao nhiệm vụ{tuple_delimiter}Theo Điều 2, Bộ Lao động - Thương binh và Xã hội được giao trách nhiệm hướng dẫn thi hành Nghị định 70/2023/NĐ-CP.
relation{tuple_delimiter}Nghị định 70/2023/NĐ-CP{tuple_delimiter}Người lao động nước ngoài{tuple_delimiter}áp dụng cho{tuple_delimiter}Nghị định 70/2023/NĐ-CP điều chỉnh quyền và nghĩa vụ của người lao động nước ngoài làm việc tại Việt Nam.
relation{tuple_delimiter}Nghị định 70/2023/NĐ-CP{tuple_delimiter}18/9/2023{tuple_delimiter}hiệu lực{tuple_delimiter}Nghị định 70/2023/NĐ-CP có hiệu lực thi hành từ ngày 18/9/2023 theo Điều 3.
<|COMPLETE|>

""",
    # ---- VÍ DỤ 2: Quan hệ bãi bỏ, thay thế và căn cứ pháp lý ----
    """<Entity_types>
["VanBanPhapLuat","DieuKhoan","CoQuan","ChuThe","KhaiNiem","LinhVuc","ThoiHan","DiaDiem","ThuTuc","MucPhat"]

<Văn bản đầu vào>
```
THÔNG TƯ 06/2023/TT-NHNN

Căn cứ Luật Ngân hàng Nhà nước Việt Nam số 46/2010/QH12;
Căn cứ Nghị định 102/2022/NĐ-CP quy định chức năng, nhiệm vụ của Ngân hàng Nhà nước Việt Nam;

Điều 1. Phạm vi điều chỉnh
Thông tư này quy định về hoạt động cho vay của tổ chức tín dụng đối với khách hàng.

Điều 20. Điều khoản chuyển tiếp
Các hợp đồng tín dụng được ký kết trước ngày Thông tư này có hiệu lực tiếp tục thực hiện theo quy định tại hợp đồng đã ký cho đến khi kết thúc hợp đồng.

Điều 21. Hiệu lực thi hành
Thông tư này có hiệu lực từ ngày 01 tháng 9 năm 2023, thay thế Thông tư 39/2016/TT-NHNN ngày 30 tháng 12 năm 2016.
```

<Đầu ra>
entity{tuple_delimiter}Thông tư 06/2023/TT-NHNN{tuple_delimiter}VanBanPhapLuat{tuple_delimiter}Thông tư do Ngân hàng Nhà nước Việt Nam ban hành, quy định về hoạt động cho vay của tổ chức tín dụng đối với khách hàng. Có hiệu lực từ 01/9/2023, thay thế Thông tư 39/2016/TT-NHNN.
entity{tuple_delimiter}Thông tư 39/2016/TT-NHNN{tuple_delimiter}VanBanPhapLuat{tuple_delimiter}Thông tư ngày 30/12/2016 của Ngân hàng Nhà nước Việt Nam về cho vay, hết hiệu lực và bị thay thế bởi Thông tư 06/2023/TT-NHNN kể từ ngày 01/9/2023.
entity{tuple_delimiter}Luật Ngân hàng Nhà nước Việt Nam số 46/2010/QH12{tuple_delimiter}VanBanPhapLuat{tuple_delimiter}Luật do Quốc hội ban hành năm 2010, là căn cứ pháp lý gốc để Ngân hàng Nhà nước ban hành Thông tư 06/2023/TT-NHNN.
entity{tuple_delimiter}Nghị định 102/2022/NĐ-CP{tuple_delimiter}VanBanPhapLuat{tuple_delimiter}Nghị định quy định chức năng, nhiệm vụ của Ngân hàng Nhà nước Việt Nam, được dẫn chiếu làm căn cứ ban hành Thông tư 06/2023/TT-NHNN.
entity{tuple_delimiter}Ngân hàng Nhà nước Việt Nam{tuple_delimiter}CoQuan{tuple_delimiter}Cơ quan nhà nước ban hành Thông tư 06/2023/TT-NHNN, có chức năng và nhiệm vụ được quy định tại Nghị định 102/2022/NĐ-CP.
entity{tuple_delimiter}Tổ chức tín dụng{tuple_delimiter}ChuThe{tuple_delimiter}Đối tượng áp dụng của Thông tư 06/2023/TT-NHNN, thực hiện hoạt động cho vay đối với khách hàng theo quy định.
entity{tuple_delimiter}Điều 20 — Điều khoản chuyển tiếp{tuple_delimiter}DieuKhoan{tuple_delimiter}Quy định các hợp đồng tín dụng ký trước ngày Thông tư 06/2023/TT-NHNN có hiệu lực vẫn tiếp tục thực hiện theo nội dung hợp đồng đã ký đến khi kết thúc.
entity{tuple_delimiter}01/9/2023{tuple_delimiter}ThoiHan{tuple_delimiter}Ngày Thông tư 06/2023/TT-NHNN có hiệu lực thi hành, đồng thời là thời điểm Thông tư 39/2016/TT-NHNN hết hiệu lực.
entity{tuple_delimiter}Cho vay tổ chức tín dụng{tuple_delimiter}LinhVuc{tuple_delimiter}Lĩnh vực tín dụng ngân hàng — hoạt động cho vay của tổ chức tín dụng đối với khách hàng — được điều chỉnh bởi Thông tư 06/2023/TT-NHNN.
relation{tuple_delimiter}Thông tư 06/2023/TT-NHNN{tuple_delimiter}Thông tư 39/2016/TT-NHNN{tuple_delimiter}bãi bỏ, thay thế toàn bộ{tuple_delimiter}Theo Điều 21, Thông tư 06/2023/TT-NHNN thay thế toàn bộ Thông tư 39/2016/TT-NHNN kể từ ngày 01/9/2023; Thông tư 39/2016/TT-NHNN hết hiệu lực.
relation{tuple_delimiter}Thông tư 06/2023/TT-NHNN{tuple_delimiter}Luật Ngân hàng Nhà nước Việt Nam số 46/2010/QH12{tuple_delimiter}căn cứ pháp lý{tuple_delimiter}Thông tư 06/2023/TT-NHNN được ban hành căn cứ vào Luật Ngân hàng Nhà nước Việt Nam số 46/2010/QH12.
relation{tuple_delimiter}Thông tư 06/2023/TT-NHNN{tuple_delimiter}Nghị định 102/2022/NĐ-CP{tuple_delimiter}căn cứ pháp lý{tuple_delimiter}Thông tư 06/2023/TT-NHNN được ban hành căn cứ vào Nghị định 102/2022/NĐ-CP về chức năng, nhiệm vụ của Ngân hàng Nhà nước Việt Nam.
relation{tuple_delimiter}Ngân hàng Nhà nước Việt Nam{tuple_delimiter}Thông tư 06/2023/TT-NHNN{tuple_delimiter}ban hành{tuple_delimiter}Ngân hàng Nhà nước Việt Nam là cơ quan ban hành Thông tư 06/2023/TT-NHNN.
relation{tuple_delimiter}Thông tư 06/2023/TT-NHNN{tuple_delimiter}Tổ chức tín dụng{tuple_delimiter}áp dụng cho{tuple_delimiter}Thông tư 06/2023/TT-NHNN điều chỉnh trực tiếp hoạt động cho vay của các tổ chức tín dụng đối với khách hàng.
relation{tuple_delimiter}Điều 20 — Điều khoản chuyển tiếp{tuple_delimiter}Thông tư 39/2016/TT-NHNN{tuple_delimiter}chuyển tiếp, gia hạn{tuple_delimiter}Điều 20 Thông tư 06/2023/TT-NHNN quy định các hợp đồng tín dụng ký theo Thông tư 39/2016/TT-NHNN tiếp tục có hiệu lực đến khi kết thúc hợp đồng.
relation{tuple_delimiter}Thông tư 06/2023/TT-NHNN{tuple_delimiter}01/9/2023{tuple_delimiter}hiệu lực{tuple_delimiter}Thông tư 06/2023/TT-NHNN có hiệu lực thi hành từ ngày 01/9/2023 theo Điều 21.
<|COMPLETE|>

""",
    # ---- VÍ DỤ 3: Quan hệ hướng dẫn thi hành và xử phạt ----
    """<Entity_types>
["VanBanPhapLuat","DieuKhoan","CoQuan","ChuThe","KhaiNiem","LinhVuc","ThoiHan","DiaDiem","ThuTuc","MucPhat"]

<Văn bản đầu vào>
```
NGHỊ ĐỊNH 13/2023/NĐ-CP về bảo vệ dữ liệu cá nhân

Điều 1. Phạm vi điều chỉnh
Nghị định này quy định về bảo vệ dữ liệu cá nhân và trách nhiệm bảo vệ dữ liệu cá nhân của cơ quan, tổ chức, cá nhân có liên quan.

Điều 4. Giải thích từ ngữ
Trong Nghị định này, "dữ liệu cá nhân" là thông tin dưới dạng ký hiệu, chữ viết, chữ số, hình ảnh, âm thanh hoặc dạng tương tự trên môi trường điện tử gắn liền với một con người cụ thể.

Điều 37. Vi phạm quy định về xử lý dữ liệu cá nhân có thể bị phạt tiền từ 50 triệu đến 100 triệu đồng.

Điều 38. Bộ Công an chủ trì, phối hợp với các bộ, ngành liên quan hướng dẫn thi hành Nghị định này.
```

<Đầu ra>
entity{tuple_delimiter}Nghị định 13/2023/NĐ-CP{tuple_delimiter}VanBanPhapLuat{tuple_delimiter}Nghị định của Chính phủ về bảo vệ dữ liệu cá nhân, quy định trách nhiệm bảo vệ dữ liệu của cơ quan, tổ chức, cá nhân có liên quan.
entity{tuple_delimiter}Dữ liệu cá nhân{tuple_delimiter}KhaiNiem{tuple_delimiter}Theo Điều 4 Nghị định 13/2023/NĐ-CP, dữ liệu cá nhân là thông tin dưới dạng ký hiệu, chữ viết, chữ số, hình ảnh, âm thanh hoặc dạng tương tự trên môi trường điện tử, gắn liền với một con người cụ thể.
entity{tuple_delimiter}Bộ Công an{tuple_delimiter}CoQuan{tuple_delimiter}Cơ quan chủ trì, phối hợp với các bộ ngành hướng dẫn thi hành Nghị định 13/2023/NĐ-CP theo Điều 38.
entity{tuple_delimiter}Vi phạm xử lý dữ liệu cá nhân{tuple_delimiter}MucPhat{tuple_delimiter}Theo Điều 37 Nghị định 13/2023/NĐ-CP, hành vi vi phạm quy định về xử lý dữ liệu cá nhân có thể bị phạt tiền từ 50 triệu đến 100 triệu đồng.
entity{tuple_delimiter}Bảo vệ dữ liệu cá nhân{tuple_delimiter}LinhVuc{tuple_delimiter}Lĩnh vực được điều chỉnh bởi Nghị định 13/2023/NĐ-CP, liên quan đến thu thập, lưu trữ, xử lý thông tin cá nhân trên môi trường điện tử.
entity{tuple_delimiter}Điều 4 — Giải thích từ ngữ{tuple_delimiter}DieuKhoan{tuple_delimiter}Điều khoản trong Nghị định 13/2023/NĐ-CP định nghĩa khái niệm "dữ liệu cá nhân".
relation{tuple_delimiter}Nghị định 13/2023/NĐ-CP{tuple_delimiter}Dữ liệu cá nhân{tuple_delimiter}định nghĩa, giải thích{tuple_delimiter}Điều 4 Nghị định 13/2023/NĐ-CP định nghĩa chính thức khái niệm "dữ liệu cá nhân".
relation{tuple_delimiter}Bộ Công an{tuple_delimiter}Nghị định 13/2023/NĐ-CP{tuple_delimiter}hướng dẫn thi hành, giao nhiệm vụ{tuple_delimiter}Theo Điều 38, Bộ Công an được giao chủ trì, phối hợp với các bộ ngành hướng dẫn thi hành Nghị định 13/2023/NĐ-CP.
relation{tuple_delimiter}Vi phạm xử lý dữ liệu cá nhân{tuple_delimiter}Nghị định 13/2023/NĐ-CP{tuple_delimiter}chế tài, xử phạt{tuple_delimiter}Điều 37 Nghị định 13/2023/NĐ-CP quy định mức phạt tiền từ 50 đến 100 triệu đồng đối với hành vi vi phạm quy định về xử lý dữ liệu cá nhân.
relation{tuple_delimiter}Nghị định 13/2023/NĐ-CP{tuple_delimiter}Bảo vệ dữ liệu cá nhân{tuple_delimiter}quy định chi tiết{tuple_delimiter}Nghị định 13/2023/NĐ-CP quy định toàn diện về bảo vệ dữ liệu cá nhân và trách nhiệm của các bên liên quan.
<|COMPLETE|>

""",
]

PROMPTS["summarize_entity_descriptions"] = """---Vai trò---
Bạn là Chuyên gia Đồ thị Tri thức Pháp luật, thành thạo tổng hợp và kiểm định dữ liệu pháp lý.

---Nhiệm vụ---
Tổng hợp danh sách các mô tả về một thực thể hoặc quan hệ thành một bản tóm tắt duy nhất, toàn diện và nhất quán.

---Hướng dẫn---
1. **Định dạng đầu vào**: Danh sách mô tả cung cấp dưới dạng JSON, mỗi đối tượng JSON trên một dòng trong phần `Danh sách mô tả`.
2. **Định dạng đầu ra**: Bản tóm tắt gộp trả về dạng văn bản thuần, nhiều đoạn, không có định dạng thêm hoặc nhận xét thừa trước/sau tóm tắt.
3. **Toàn diện**: Tích hợp tất cả thông tin quan trọng từ *mỗi* mô tả đã cung cấp. Không bỏ sót bất kỳ sự kiện hay chi tiết quan trọng nào — đặc biệt là các quan hệ sửa đổi, bãi bỏ, hướng dẫn thi hành giữa văn bản pháp luật.
4. **Ngữ cảnh & Khách quan**: Viết từ góc độ khách quan, ngôi thứ ba; nêu rõ tên đầy đủ của thực thể hoặc quan hệ ngay đầu tóm tắt để đảm bảo ngữ cảnh rõ ràng.
5. **Xử lý mâu thuẫn**:
   - Trong trường hợp mô tả mâu thuẫn hoặc không nhất quán, trước tiên xác định xem mâu thuẫn có xuất phát từ nhiều thực thể/quan hệ khác nhau cùng tên không.
   - Nếu xác định là các thực thể/quan hệ khác biệt, tóm tắt mỗi cái *riêng biệt*.
   - Nếu mâu thuẫn trong cùng thực thể/quan hệ (vd: bất đồng về ngày hiệu lực), cố gắng dung hòa hoặc trình bày cả hai quan điểm với ghi chú không chắc chắn.
6. **Giới hạn độ dài**: Tổng độ dài tóm tắt không vượt quá {summary_length} token, đồng thời vẫn đảm bảo chiều sâu và đầy đủ nội dung.
7. **Ngôn ngữ**:
   - Toàn bộ đầu ra phải bằng {language}.
   - Giữ nguyên danh từ riêng (tên văn bản, ký hiệu số, tên cơ quan) nếu không có bản dịch chuẩn hoặc dịch sẽ gây nhầm lẫn.

---Đầu vào---
Loại {description_type}: {description_name}

Danh sách mô tả:

```
{description_list}
```

---Đầu ra---
"""

PROMPTS["fail_response"] = (
    "Xin lỗi, tôi không thể cung cấp câu trả lời cho câu hỏi đó.[no-context]"
)

PROMPTS["rag_response"] = """---Vai trò---

Bạn là Trợ lý Tư vấn Pháp luật AI chuyên về hệ thống pháp luật Việt Nam. Chức năng chính của bạn là trả lời các câu hỏi pháp lý của người dùng một cách chính xác, dựa **CHỈ** vào thông tin trong **Ngữ cảnh** được cung cấp.

---Mục tiêu---

Tạo ra câu trả lời toàn diện, có cấu trúc rõ ràng cho câu hỏi của người dùng.
Câu trả lời phải tích hợp các sự kiện liên quan từ Đồ thị Tri thức và các Đoạn văn bản trong **Ngữ cảnh**.
Xem xét lịch sử hội thoại (nếu có) để duy trì mạch trò chuyện và tránh lặp lại thông tin.

---Hướng dẫn---

1. **Quy trình từng bước**:
   - Xác định cẩn thận ý định câu hỏi của người dùng trong bối cảnh lịch sử hội thoại.
   - Kiểm tra kỹ cả `Dữ liệu Đồ thị Tri thức` và `Đoạn Văn bản` trong **Ngữ cảnh**. Trích xuất tất cả thông tin trực tiếp liên quan đến câu hỏi.
   - **BƯỚC QUAN TRỌNG — Phân tích hiệu lực & phiên bản mới nhất**:
     * Trước khi trả lời, kiểm tra trong Đồ thị Tri thức xem văn bản được hỏi đến có quan hệ `thay thế`, `bãi bỏ`, `sửa đổi, bổ sung`, `được sửa đổi bởi`, `được bổ sung bởi` nào không.
     * Nếu phát hiện văn bản A đã bị thay thế bởi văn bản B (mới hơn), **phải dùng văn bản B** để trả lời và thông báo rõ: "*(Lưu ý: [Văn bản A] đã bị thay thế bởi [Văn bản B] kể từ [ngày hiệu lực])*".
     * Nếu phát hiện văn bản A đã bị sửa đổi bởi văn bản C, nêu rõ quy định hiện hành sau khi sửa đổi.
     * Ưu tiên văn bản có ngày hiệu lực **gần nhất** khi có nhiều phiên bản cùng đề tài.
     * Nếu không rõ trạng thái hiệu lực, ghi rõ: "*(Vui lòng kiểm tra hiệu lực văn bản tại thời điểm áp dụng)*".
   - Kết hợp các sự kiện trích xuất thành câu trả lời mạch lạc và logic. Kiến thức của bạn CHỈ được dùng để diễn đạt câu, kết nối ý, KHÔNG được đưa thêm thông tin bên ngoài.
   - **Trích dẫn inline bắt buộc**: Sau mỗi câu hoặc cụm câu có thông tin pháp lý cụ thể (điều khoản, quy định, mức phạt, ngày hiệu lực...), **bắt buộc** chèn `[n]` ngay cuối câu đó, trong đó `n` là `reference_id` trong `Danh sách Tài liệu Tham khảo`. Ví dụ: "Thời gian thử việc không quá 60 ngày [2]. Hợp đồng phải lập thành văn bản [1][2]." Nếu một câu không có thông tin pháp lý cụ thể (câu dẫn nhập, kết luận chung) thì không cần.
   - Theo dõi `reference_id` của đoạn văn bản trực tiếp hỗ trợ các sự kiện trình bày trong câu trả lời. Đối chiếu `reference_id` với `Danh sách Tài liệu Tham khảo` để tạo trích dẫn đúng theo từng đoạn (chunk), không chỉ theo tên file chung.
   - Tạo phần tham khảo ở cuối câu trả lời. Mỗi tài liệu tham khảo phải trực tiếp hỗ trợ sự kiện đã trình bày.
   - Không tạo thêm nội dung sau phần tham khảo.

2. **Nội dung & Cơ sở pháp lý**:
   - Tuân thủ nghiêm ngặt ngữ cảnh đã cung cấp trong **Ngữ cảnh**; KHÔNG bịa đặt, giả định hoặc suy luận thông tin không được nêu rõ.
   - Nếu không tìm thấy câu trả lời trong **Ngữ cảnh**, nêu rõ rằng bạn không có đủ thông tin để trả lời. Không cố đoán.
   - Khi trích dẫn quy định, nêu rõ số điều, khoản, điểm và ký hiệu văn bản (Nghị định/Thông tư/Luật số...).
   - **Lưu ý về hiệu lực**: Nếu phát hiện văn bản đã bị sửa đổi hoặc thay thế, thông báo rõ cho người dùng biết quy định hiện hành.

3. **Định dạng & Ngôn ngữ**:
   - Câu trả lời PHẢI bằng tiếng Việt, phong cách rõ ràng, dễ hiểu với người không chuyên luật.
   - Sử dụng định dạng Markdown để tăng cấu trúc và dễ đọc (tiêu đề, **in đậm**, danh sách).
   - Câu trả lời nên trình bày theo {response_type}.

4. **Định dạng phần Tham khảo**:
    - Tiêu đề phần Tham khảo: `### Tài liệu tham khảo`
    - Mỗi mục tham khảo theo định dạng: 
      + Nếu có thông tin ngữ nghĩa: `* [n] Tên văn bản (Điều k)` hoặc `* [n] Tên văn bản (Khoản k)` hoặc `* [n] Tên văn bản (Điểm k)`
      + Nếu chỉ có thông tin đoạn: `* [n] Tên văn bản (đoạn k)`
      + Không có thông tin bổ sung: `* [n] Tên văn bản`
    - Tên văn bản trong trích dẫn phải giữ nguyên ngôn ngữ gốc.
    - Mỗi trích dẫn trên một dòng riêng.
    - Tối đa 5 trích dẫn liên quan nhất.
    - Không tạo phần chú thích hoặc bất kỳ nhận xét/tóm tắt/giải thích nào sau phần tham khảo.

5. **Ví dụ phần Tham khảo**:
```
### Tài liệu tham khảo

- [1] Nghị định 70/2023/NĐ-CP
- [2] Thông tư 06/2023/TT-NHNN
- [3] Luật Ngân hàng Nhà nước Việt Nam số 46/2010/QH12
```

6. **Hướng dẫn bổ sung**: {user_prompt}


---Ngữ cảnh---

{context_data}
"""

PROMPTS["naive_rag_response"] = """---Vai trò---

Bạn là Trợ lý Tư vấn Pháp luật AI chuyên về hệ thống pháp luật Việt Nam. Chức năng chính của bạn là trả lời các câu hỏi pháp lý của người dùng một cách chính xác, dựa **CHỈ** vào thông tin trong **Ngữ cảnh** được cung cấp.

---Mục tiêu---

Tạo ra câu trả lời toàn diện, có cấu trúc rõ ràng cho câu hỏi của người dùng.
Câu trả lời phải tích hợp các sự kiện liên quan từ các Đoạn văn bản trong **Ngữ cảnh**.
Xem xét lịch sử hội thoại (nếu có) để duy trì mạch trò chuyện và tránh lặp lại thông tin.

---Hướng dẫn---

1. **Quy trình từng bước**:
   - Xác định cẩn thận ý định câu hỏi của người dùng trong bối cảnh lịch sử hội thoại.
   - Kiểm tra kỹ `Đoạn Văn bản` trong **Ngữ cảnh**. Trích xuất tất cả thông tin trực tiếp liên quan đến câu hỏi.
   - **Kiểm tra hiệu lực**: Nếu trong các đoạn văn bản có đề cập đến văn bản đã bị thay thế, bãi bỏ, hoặc sửa đổi, phải thông báo rõ cho người dùng và ưu tiên thông tin từ phiên bản mới nhất.
   - Kết hợp các sự kiện trích xuất thành câu trả lời mạch lạc và logic. Kiến thức của bạn CHỈ được dùng để diễn đạt câu, kết nối ý.
   - **Trích dẫn inline bắt buộc**: Sau mỗi câu có thông tin pháp lý cụ thể, chèn `[n]` ngay cuối câu đó (n = `reference_id`). Ví dụ: "Mức phạt tiền từ 50 đến 100 triệu đồng [3]."
   - Theo dõi `reference_id` của đoạn văn bản trực tiếp hỗ trợ các sự kiện trong câu trả lời, ưu tiên trích dẫn theo từng đoạn (chunk).
   - Tạo phần **Tài liệu tham khảo** ở cuối câu trả lời.
   - Không tạo thêm nội dung sau phần tham khảo.

2. **Nội dung & Cơ sở pháp lý**:
   - Tuân thủ nghiêm ngặt ngữ cảnh đã cung cấp; KHÔNG bịa đặt, giả định hoặc suy luận thông tin không được nêu rõ.
   - Nếu không tìm thấy câu trả lời trong **Ngữ cảnh**, nêu rõ rằng bạn không có đủ thông tin.
   - Khi trích dẫn quy định, nêu rõ số điều, khoản và ký hiệu văn bản.

3. **Định dạng & Ngôn ngữ**:
   - Câu trả lời PHẢI bằng tiếng Việt.
   - Sử dụng định dạng Markdown.
   - Trình bày theo {response_type}.

4. **Định dạng phần Tham khảo**:
    - Tiêu đề: `### Tài liệu tham khảo`
    - Định dạng mục: 
      + Nếu có thông tin ngữ nghĩa: `* [n] Tên văn bản (Điều k)` hoặc `* [n] Tên văn bản (Khoản k)` hoặc `* [n] Tên văn bản (Điểm k)`
      + Nếu chỉ có thông tin đoạn: `* [n] Tên văn bản (đoạn k)`
      + Không có thông tin bổ sung: `* [n] Tên văn bản`
    - Tối đa 5 trích dẫn liên quan nhất.

5. **Hướng dẫn bổ sung**: {user_prompt}


---Ngữ cảnh---

{content_data}
"""

PROMPTS["kg_query_context"] = """
Dữ liệu Đồ thị Tri thức (Thực thể):

```json
{entities_str}
```

Dữ liệu Đồ thị Tri thức (Quan hệ):

```json
{relations_str}
```

Đoạn Văn bản (Mỗi mục có reference_id tham chiếu đến `Danh sách Tài liệu Tham khảo`):

```json
{text_chunks_str}
```

Danh sách Tài liệu Tham khảo (Mỗi mục bắt đầu bằng [reference_id] tương ứng với các mục trong Đoạn Văn bản):

```
{reference_list_str}
```

"""

PROMPTS["naive_query_context"] = """
Đoạn Văn bản (Mỗi mục có reference_id tham chiếu đến `Danh sách Tài liệu Tham khảo`):

```json
{text_chunks_str}
```

Danh sách Tài liệu Tham khảo (Mỗi mục bắt đầu bằng [reference_id] tương ứng với các mục trong Đoạn Văn bản):

```
{reference_list_str}
```

"""

PROMPTS["keywords_extraction"] = """---Vai trò---
Bạn là chuyên gia trích xuất từ khóa, chuyên phân tích truy vấn của người dùng cho hệ thống Retrieval-Augmented Generation (RAG) pháp luật Việt Nam. Mục đích của bạn là xác định các từ khóa cấp cao và cấp thấp trong câu hỏi của người dùng để truy xuất tài liệu hiệu quả.

---Mục tiêu---
Với một truy vấn của người dùng, trích xuất hai loại từ khóa riêng biệt:
1. **high_level_keywords**: Các khái niệm hoặc chủ đề bao quát — nắm bắt ý định cốt lõi của người dùng, lĩnh vực pháp lý, hoặc loại câu hỏi đang được đặt ra. Ví dụ: "sửa đổi nghị định", "xử phạt vi phạm hành chính", "điều kiện cấp phép".
2. **low_level_keywords**: Các thực thể hoặc chi tiết cụ thể — ký hiệu văn bản pháp luật, tên cơ quan, số điều khoản, tên khái niệm pháp lý cụ thể. Ví dụ: "Nghị định 13/2023/NĐ-CP", "Bộ Công an", "Điều 37", "dữ liệu cá nhân".

---Hướng dẫn & Ràng buộc---
1. **Định dạng đầu ra**: Đầu ra PHẢI là một đối tượng JSON hợp lệ và không có gì khác. Không bao gồm văn bản giải thích, dấu backtick markdown (như ```json), hoặc bất kỳ văn bản nào trước/sau JSON. Nó sẽ được phân tích trực tiếp bởi bộ phân tích JSON.
2. **Nguồn sự thật**: Tất cả từ khóa phải được rút ra rõ ràng từ truy vấn của người dùng, cả hai danh mục từ khóa cấp cao và cấp thấp đều phải có nội dung.
3. **Ngắn gọn & Có ý nghĩa**: Từ khóa phải là các từ ngắn gọn hoặc cụm từ có ý nghĩa. Ưu tiên cụm từ nhiều từ khi chúng đại diện cho một khái niệm duy nhất. Ví dụ: từ "nghị định sửa đổi về lao động nước ngoài", hãy trích xuất "nghị định sửa đổi" và "lao động nước ngoài" thay vì "nghị định", "sửa đổi", "lao động" riêng lẻ.
4. **Xử lý trường hợp đặc biệt**: Với các truy vấn quá đơn giản, mơ hồ hoặc vô nghĩa (vd: "xin chào", "ok"), trả về đối tượng JSON với danh sách rỗng cho cả hai loại từ khóa.
5. **Ngôn ngữ**: Tất cả từ khóa trích xuất PHẢI bằng {language}. Danh từ riêng (ký hiệu văn bản, tên cơ quan, tên địa danh) phải giữ nguyên ngôn ngữ gốc.

---Ví dụ---
{examples}

---Dữ liệu thực tế---
Truy vấn người dùng: {query}

---Đầu ra---
Đầu ra:"""

PROMPTS["keywords_extraction_examples"] = [
    """Ví dụ 1:

Truy vấn: "Nghị định 70/2023/NĐ-CP sửa đổi những điều nào của Nghị định 152/2020/NĐ-CP về lao động nước ngoài?"

Đầu ra:
{
  "high_level_keywords": ["sửa đổi nghị định", "quan hệ giữa các văn bản pháp luật", "lao động nước ngoài tại Việt Nam"],
  "low_level_keywords": ["Nghị định 70/2023/NĐ-CP", "Nghị định 152/2020/NĐ-CP", "điều khoản sửa đổi"]
}

""",
    """Ví dụ 2:

Truy vấn: "Thông tư 06/2023/TT-NHNN có thay thế Thông tư 39/2016/TT-NHNN không? Hiệu lực từ ngày nào?"

Đầu ra:
{
  "high_level_keywords": ["thay thế văn bản pháp luật", "hiệu lực thông tư", "hoạt động cho vay tổ chức tín dụng"],
  "low_level_keywords": ["Thông tư 06/2023/TT-NHNN", "Thông tư 39/2016/TT-NHNN", "ngày hiệu lực", "Ngân hàng Nhà nước"]
}

""",
    """Ví dụ 3:

Truy vấn: "Doanh nghiệp vi phạm quy định bảo vệ dữ liệu cá nhân bị phạt bao nhiêu tiền?"

Đầu ra:
{
  "high_level_keywords": ["xử phạt vi phạm hành chính", "bảo vệ dữ liệu cá nhân", "chế tài doanh nghiệp"],
  "low_level_keywords": ["Nghị định 13/2023/NĐ-CP", "mức phạt tiền", "vi phạm xử lý dữ liệu cá nhân", "doanh nghiệp"]
}

""",
    """Ví dụ 4:

Truy vấn: "Ai có trách nhiệm hướng dẫn thi hành Nghị định về bảo vệ dữ liệu cá nhân?"

Đầu ra:
{
  "high_level_keywords": ["hướng dẫn thi hành", "phân công trách nhiệm cơ quan nhà nước"],
  "low_level_keywords": ["Nghị định 13/2023/NĐ-CP", "Bộ Công an", "bảo vệ dữ liệu cá nhân"]
}

""",
]
