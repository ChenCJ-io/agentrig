"""Target 领域枚举。"""

from enum import StrEnum


class DriverType(StrEnum):
    HTTP_SSE = "http_sse"
    PIXCAKE_HTTP_SSE = "pixcake_http_sse"
    OPENAI_COMPATIBLE = "openai_compatible"
    PYTHON = "python"
    SUBPROCESS = "subprocess"
