"""TOML 配置加载测试。"""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic_settings import SettingsConfigDict

from agentrig.config import Settings


def _settings_cls_with_toml(toml_path: str) -> type[Settings]:
    """构造一个指向指定 toml 文件的 Settings 子类（顶层字段，无 table header）。"""

    class _S(Settings):
        model_config = SettingsConfigDict(
            env_prefix="AGENTRIG_",
            env_nested_delimiter="__",
            extra="ignore",
            toml_file=toml_path,
        )

    return _S


def test_toml_provides_values(tmp_path: Path) -> None:
    toml = tmp_path / "a.toml"
    toml.write_text('environment = "prod"\n[server]\nport = 9999\n')
    s = _settings_cls_with_toml(str(toml))()
    assert s.environment == "prod"
    assert s.server.port == 9999


def test_env_overrides_toml(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """环境变量优先于 TOML。"""
    toml = tmp_path / "a.toml"
    toml.write_text('environment = "from-toml"\n')
    monkeypatch.setenv("AGENTRIG_ENVIRONMENT", "from-env")
    s = _settings_cls_with_toml(str(toml))()
    assert s.environment == "from-env"


def test_config_file_env_overrides_default_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    toml = tmp_path / "local-demo.toml"
    toml.write_text('environment = "local-demo"\n[server]\nport = 8010\n')
    monkeypatch.setenv("AGENTRIG_CONFIG_FILE", str(toml))

    settings = Settings()

    assert settings.environment == "local-demo"
    assert settings.server.port == 8010


def test_no_toml_file_falls_back_to_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """无 toml 文件 → 用默认值（不报错）。"""
    monkeypatch.delenv("AGENTRIG_ENVIRONMENT", raising=False)
    s = Settings()
    assert s.environment == "dev"
    assert s.server.port == 8000


def test_execution_limits_reject_unsafe_defaults() -> None:
    with pytest.raises(ValueError, match="default_concurrency"):
        Settings(execution={"default_concurrency": 5, "max_concurrency": 4})
    with pytest.raises(ValueError):
        Settings(execution={"max_repeat_count": 0})
    with pytest.raises(ValueError):
        Settings(assistant={"sse_poll_interval_seconds": 0})
    with pytest.raises(ValueError):
        Settings(reporting={"max_export_records": 0})
    with pytest.raises(ValueError):
        Settings(reporting={"max_report_case_runs": 100_001})


def test_trusted_principal_header_is_normalized() -> None:
    settings = Settings(server={"trusted_principal_header": "X-Verified-User"})
    assert settings.server.trusted_principal_header == "x-verified-user"

    with pytest.raises(ValueError, match="valid HTTP header"):
        Settings(server={"trusted_principal_header": "bad header"})


def test_target_network_allowlist_is_normalized_and_rejects_unsafe_patterns() -> None:
    settings = Settings(
        target_network={"allowed_hosts": ["API.EXAMPLE.COM.", "api.example.com"]}
    )
    assert settings.target_network.allowed_hosts == ["api.example.com"]

    with pytest.raises(ValueError, match="leading"):
        Settings(target_network={"allowed_hosts": ["api.*.example.com"]})
    with pytest.raises(ValueError, match="without scheme"):
        Settings(target_network={"allowed_hosts": ["https://api.example.com"]})
