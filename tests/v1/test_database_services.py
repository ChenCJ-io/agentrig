"""11 表 SQL 数据层与 Phase 1 CRUD 规则。"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from sqlalchemy import inspect

from agentrig.cases import (
    CaseSelector,
    CaseService,
    TestCaseCreate,
    TestCasePatch,
)
from agentrig.cases.models import ReviewStatus
from agentrig.errors import AgentRigError, ErrorCode
from agentrig.infrastructure.database import Database
from agentrig.infrastructure.database.repositories import (
    SqlCaseRepository,
    SqlProfileRepository,
    SqlSampleRepository,
    SqlTargetRepository,
)
from agentrig.infrastructure.secrets import SecretResolver
from agentrig.profiles import ProfileCreate, ProfilePatch, ProfileService
from agentrig.targets import TargetCreate, TargetPatch, TargetService
from agentrig.targets.drivers import DriverRegistry
from agentrig.targets.options import merge_target_options
from agentrig.tool_results import SampleCreate, SamplePatch, SampleService, SampleStatus


@pytest.fixture
async def database() -> Database:
    value = Database("sqlite+aiosqlite:///:memory:")
    await value.create_schema()
    yield value
    await value.dispose()


def case_input(
    case_id: str | None = None,
    *,
    tags: list[str] | None = None,
) -> TestCaseCreate:
    return TestCaseCreate(
        id=case_id,
        name="search case",
        tags=tags or ["cap.search", "L0"],
        supported_versions=["v1", "v2"],
        primary_evaluator="rule",
        turns=[
            {
                "position": 1,
                "user_message": "search",
                "fixtures": [
                    {
                        "tool_name": "search",
                        "result": {"items": []},
                    }
                ],
                "assertions": [{"kind": "tool_called", "tool_name": "search"}],
            }
        ],
    )


async def test_schema_contains_v1_core_and_v2_extension_tables(database: Database) -> None:
    async with database.engine.connect() as connection:
        names = set(await connection.run_sync(lambda sync: inspect(sync).get_table_names()))
    assert names == {
        "test_cases",
        "case_turns",
        "case_tags",
        "samples",
        "targets",
        "target_versions",
        "execution_profiles",
        "runs",
        "case_runs",
        "run_events",
        "evaluations",
        "assistant_sessions",
        "assistant_events",
        "assistant_turns",
        "evaluation_plans",
        "agent_invocations",
        "integration_cursors",
    }


async def test_case_crud_selector_and_approval_boundary(database: Database) -> None:
    service = CaseService(SqlCaseRepository(database))
    created = await service.create(case_input("case_search"))
    assert created.review_status is ReviewStatus.DRAFT
    assert len(created.turns) == 1

    by_capability = await service.list_cases(CaseSelector(capabilities=["search"]))
    by_tool = await service.list_cases(CaseSelector(tool_names=["search"]))
    assert [item.id for item in by_capability.items] == ["case_search"]
    assert [item.id for item in by_tool.items] == ["case_search"]
    assert (await service.list_tags())[0].count == 1

    updated = await service.update("case_search", TestCasePatch(description="updated"))
    assert updated.description == "updated"
    approved = await service.review("case_search", ReviewStatus.APPROVED)
    assert approved.review_status is ReviewStatus.APPROVED
    with pytest.raises(AgentRigError) as exc:
        await service.update("case_search", TestCasePatch(description="forbidden"))
    assert exc.value.detail.code is ErrorCode.PERMISSION_DENIED
    with pytest.raises(AgentRigError):
        await service.delete("case_search")


async def test_rejected_case_is_mutable_but_hidden_by_default(database: Database) -> None:
    service = CaseService(SqlCaseRepository(database))
    await service.create(case_input("case_rejected"))
    await service.review("case_rejected", ReviewStatus.REJECTED)
    assert (await service.list_cases()).items == []
    explicit = await service.list_cases(
        CaseSelector(review_status=[ReviewStatus.REJECTED])
    )
    assert [item.id for item in explicit.items] == ["case_rejected"]
    await service.update("case_rejected", TestCasePatch(description="fixing"))
    await service.delete("case_rejected")


async def test_target_versions_are_replaced_atomically(database: Database) -> None:
    service = TargetService(SqlTargetRepository(database))
    target = await service.create(
        TargetCreate(
            id="target_a",
            name="Agent A",
            driver_type="http_sse",
            endpoint="http://localhost:9000",
            secret_ref="env:AGENT_TOKEN",
            versions=[
                {"version": "v1", "endpoint": "http://localhost:9001"},
                {"version": "v2"},
            ],
        )
    )
    assert [item.version for item in target.versions] == ["v1", "v2"]
    target = await service.update(
        target.id,
        TargetPatch(versions=[{"version": "feature/x", "options": {"prompt": "x"}}]),
    )
    assert [item.version for item in target.versions] == ["feature/x"]


async def test_target_check_reports_driver_capabilities_and_missing_secret(
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = TargetService(
        SqlTargetRepository(database),
        drivers=DriverRegistry(),
        secrets=SecretResolver(),
    )
    await service.create(
        TargetCreate(
            id="target_check",
            name="Check",
            driver_type="http_sse",
            secret_ref="env:TARGET_CHECK_TOKEN",
        )
    )
    missing = await service.check("target_check")
    assert missing.reachable is False
    assert "not set" in missing.message

    monkeypatch.setenv("TARGET_CHECK_TOKEN", "secret")
    valid = await service.check("target_check")
    assert valid.reachable is True
    assert "tool_result_injection" in valid.capabilities
    assert "tool_proxy_injection" in valid.capabilities


async def test_target_write_rejects_unknown_driver_and_invalid_acp_options(
    database: Database,
    tmp_path: Path,
) -> None:
    registry = DriverRegistry(
        subprocess_allowlist=[str(tmp_path / "run-acp.sh")]
    )
    service = TargetService(
        SqlTargetRepository(database),
        drivers=registry,
        secrets=SecretResolver(),
    )
    with pytest.raises(AgentRigError, match="unsupported driver"):
        await service.create(
            TargetCreate(
                id="target_unknown",
                name="Unknown",
                driver_type="not_installed",
            )
        )
    with pytest.raises(AgentRigError, match="command"):
        await service.create(
            TargetCreate(
                id="target_bad_acp",
                name="Bad ACP",
                driver_type="acp",
                options={"command": "./run-acp.sh"},
            )
        )


async def test_target_check_preflights_acp_allowlist_and_secret(
    database: Database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "run-acp.sh"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o700)
    repository = SqlTargetRepository(database)

    async def probe_without_starting_process(
        _driver: object,
        context: object,
    ) -> None:
        assert context is not None

    monkeypatch.setattr(
        "agentrig.targets.drivers.acp.AcpDriver.probe",
        probe_without_starting_process,
    )
    # 模拟升级前已经保存、但当前部署不允许启动的 Target。
    await TargetService(repository).create(
        TargetCreate(
            id="target_acp_preflight",
            name="ACP preflight",
            driver_type="acp",
            secret_ref="env:ACP_TEST_KEY",
            options={
                "command": [str(executable)],
                "credential_env": "DEEPSEEK_API_KEY",
            },
        )
    )
    denied_service = TargetService(
        repository,
        drivers=DriverRegistry(subprocess_allowlist=[]),
        secrets=SecretResolver(),
    )
    denied = await denied_service.check("target_acp_preflight")
    assert denied.reachable is False
    assert "subprocess_allowlist" in denied.message

    allowed_service = TargetService(
        repository,
        drivers=DriverRegistry(subprocess_allowlist=[str(executable)]),
        secrets=SecretResolver(),
    )
    missing_secret = await allowed_service.check("target_acp_preflight")
    assert missing_secret.reachable is False
    assert "ACP_TEST_KEY" in missing_secret.message
    monkeypatch.setenv("ACP_TEST_KEY", "test-secret")
    valid = await allowed_service.check("target_acp_preflight")
    assert valid.reachable is True
    assert "tool_proxy_injection" in valid.capabilities
    assert "initialize/session probe succeeded" in valid.message


async def test_target_check_treats_http_error_status_as_unreachable(
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = TargetService(
        SqlTargetRepository(database),
        drivers=DriverRegistry(),
        secrets=SecretResolver(),
    )
    await service.create(
        TargetCreate(
            id="target_health_404",
            name="Missing health endpoint",
            driver_type="http_sse",
            endpoint="http://agent.test",
            options={"healthcheck_url": "http://agent.test/missing"},
        )
    )

    async def return_not_found(
        _client: httpx.AsyncClient,
        url: str,
    ) -> httpx.Response:
        return httpx.Response(404, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", return_not_found)
    result = await service.check("target_health_404")
    assert result.reachable is False
    assert result.message == "HTTP endpoint responded with 404"


def test_target_version_options_are_deep_merged_without_mutating_input() -> None:
    base = {
        "user_id": 10001,
        "device_info": {
            "device_id": "agentrig",
            "os": "macOS",
            "os_version": "15.7",
            "app_version": "9.1.0",
            "tool_version": 3,
        },
        "request_defaults": {"metadata": {"project_id": 8, "source": "base"}},
    }
    override = {
        "device_info": {"app_version": "9.3.0", "tool_version": 5},
        "request_defaults": {"metadata": {"source": "version"}},
    }

    merged = merge_target_options(base, override)

    assert merged["device_info"] == {
        "device_id": "agentrig",
        "os": "macOS",
        "os_version": "15.7",
        "app_version": "9.3.0",
        "tool_version": 5,
    }
    assert merged["request_defaults"]["metadata"] == {
        "project_id": 8,
        "source": "version",
    }
    assert base["device_info"]["app_version"] == "9.1.0"


async def test_profile_crud_persists_typed_config(database: Database) -> None:
    service = ProfileService(SqlProfileRepository(database))
    profile = await service.create(
        ProfileCreate(
            id="profile_core",
            name="Core",
            config={
                "tool_mode": "controlled",
                "provider_chain": [{"name": "fixture"}, {"name": "sample"}],
                "concurrency": 3,
            },
        )
    )
    assert profile.config.concurrency == 3
    updated = await service.update(profile.id, ProfilePatch(description="stable"))
    assert updated.description == "stable"
    assert (await service.list_profiles()).total == 1
    await service.delete(profile.id)


async def test_only_approved_samples_are_provider_candidates(database: Database) -> None:
    repository = SqlSampleRepository(database)
    service = SampleService(repository)
    sample = await service.create(
        SampleCreate(
            id="sample_search",
            name="search result",
            tool_name="search",
            content={"items": [{"id": 1}]},
            match_arguments={"query": "hello"},
            supported_versions=["v1"],
        )
    )
    assert await repository.approved_candidates("search", "v1") == []
    sample = await service.update(sample.id, SamplePatch(name="reviewed search"))
    assert sample.name == "reviewed search"
    approved = await service.review(sample.id, SampleStatus.APPROVED)
    assert approved.status is SampleStatus.APPROVED
    assert len(await repository.approved_candidates("search", "v1")) == 1
    assert await repository.approved_candidates("search", "v2") == []
    with pytest.raises(AgentRigError):
        await service.delete(sample.id)
