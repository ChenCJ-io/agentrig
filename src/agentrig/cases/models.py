"""测试用例的稳定状态枚举。"""

from enum import StrEnum


class ReviewStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"
