"""Taxonomy quan hệ pháp lý Việt Nam.

Dựa trên Luật Ban hành VBQPPL 2015, sửa đổi 2020.
"""
from __future__ import annotations

from enum import Enum


class LegalRelationType(str, Enum):
    # === QUAN HỆ HIỆU LỰC ===
    REPLACES    = "THAY_THE"        # A thay thế B hoàn toàn
    AMENDS      = "SUA_DOI"         # A sửa đổi một số điều của B
    SUPPLEMENTS = "BO_SUNG"         # A bổ sung thêm vào B
    SUSPENDS    = "DINH_CHI"        # A đình chỉ thi hành B
    ANNULS      = "BAI_BO"          # A bãi bỏ B (toàn bộ/một phần)
    EXTENDS     = "GIA_HAN"         # A gia hạn hiệu lực của B

    # === QUAN HỆ HƯỚNG DẪN ===
    GUIDES      = "HUONG_DAN"       # A hướng dẫn thi hành B
    DETAILS     = "QUY_DINH_CHI_TIET"  # A quy định chi tiết B
    IMPLEMENTS  = "THI_HANH"        # A để thi hành B

    # === QUAN HỆ THAM CHIẾU ===
    REFERENCES  = "THAM_CHIEU"      # A viện dẫn B
    BASED_ON    = "CAN_CU"          # A căn cứ vào B
    CONSISTENT_WITH = "PHU_HOP"     # A phải phù hợp với B

    # === QUAN HỆ PHẠM VI ===
    APPLIES_TO  = "AP_DUNG_CHO"     # A áp dụng cho lĩnh vực/đối tượng X
    GOVERNS     = "DIEU_CHINH"      # A điều chỉnh lĩnh vực X
    EXCEPTION_OF = "NGOAI_LE"       # A là ngoại lệ của B

    # === QUAN HỆ THỜI GIAN ===
    PRECEDED_BY  = "TIEN_THAN"      # A kế thừa từ B (B là văn bản cũ hơn)
    SUPERSEDED_BY = "BI_THAY_THE"   # A bị thay thế bởi B
    TRANSITIONAL = "CHUYEN_TIEP"    # A là quy định chuyển tiếp


# Mapping keyword → RelationType (để regex extract)
RELATION_KEYWORDS: dict[LegalRelationType, list[str]] = {
    LegalRelationType.REPLACES: [
        "thay thế", "thay cho", "thay thế toàn bộ",
        "hết hiệu lực", "không còn hiệu lực", "bãi bỏ và thay thế",
    ],
    LegalRelationType.AMENDS: [
        "sửa đổi", "sửa đổi, bổ sung",
        "điều chỉnh", "thay đổi nội dung điều",
    ],
    LegalRelationType.SUPPLEMENTS: [
        "bổ sung", "thêm vào",
        "bổ sung thêm điều", "bổ sung khoản",
        "được bổ sung", "bổ sung như sau",
    ],
    LegalRelationType.GUIDES: [
        "hướng dẫn thi hành", "hướng dẫn thực hiện",
        "hướng dẫn chi tiết", "hướng dẫn một số điều",
        "hướng dẫn thực hiện một số điều",
    ],
    LegalRelationType.DETAILS: [
        "quy định chi tiết", "quy định cụ thể",
        "hướng dẫn chi tiết thi hành",
        "quy định chi tiết thi hành",
    ],
    LegalRelationType.ANNULS: [
        "bãi bỏ", "hủy bỏ", "xóa bỏ",
        "không áp dụng", "chấm dứt hiệu lực",
    ],
    LegalRelationType.SUSPENDS: [
        "đình chỉ", "tạm đình chỉ", "đình chỉ thi hành",
    ],
    LegalRelationType.BASED_ON: [
        "căn cứ", "trên cơ sở", "dựa trên",
        "theo quy định tại", "thi hành",
        "căn cứ vào", "căn cứ theo",
    ],
    LegalRelationType.REFERENCES: [
        "viện dẫn", "theo quy định", "quy định tại",
        "theo điều", "theo khoản", "áp dụng điều",
    ],
    LegalRelationType.APPLIES_TO: [
        "áp dụng đối với", "áp dụng cho",
        "điều chỉnh quan hệ", "đối tượng áp dụng",
    ],
    LegalRelationType.IMPLEMENTS: [
        "để thi hành", "thi hành nghị quyết",
        "thực hiện nghị quyết", "thi hành luật",
    ],
}
