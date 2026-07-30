"""设计文档要求的三条 V1 纵向 Demo 必须持续可运行。"""

from examples.v1.http_sse_controlled import run as run_http_sse
from examples.v1.mcp_proxy_sample_curator import run as run_mcp_proxy
from examples.v1.openai_evidence_judge import run as run_openai_judge


async def test_http_sse_controlled_demo() -> None:
    await run_http_sse()


async def test_openai_evidence_judge_demo() -> None:
    await run_openai_judge()


async def test_mcp_proxy_sample_curator_demo() -> None:
    await run_mcp_proxy()
