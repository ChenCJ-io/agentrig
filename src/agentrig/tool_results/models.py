"""工具结果领域枚举。"""

from enum import StrEnum


class SampleStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    DISABLED = "disabled"


class SampleKind(StrEnum):
    SINGLE = "single"
    SEQUENCE = "sequence"
