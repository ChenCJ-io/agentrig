"""按 ExecutionProfile 顺序解析工具结果。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..errors import AgentRigError, ErrorCode
from ..profiles.models import ProviderName
from ..profiles.schemas import ProviderSpec
from ..targets.drivers import ToolResult
from .providers import (
    FixtureProvider,
    ProviderAttempt,
    ProviderContext,
    ProviderResponse,
    ProviderStatus,
    SampleProvider,
    ToolResultProvider,
)
from .repository import SampleRepository
from .validator import ToolResultValidator


class ToolResolution(BaseModel):
    result: ToolResult
    attempts: list[ProviderAttempt] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)


class ProviderChain:
    def __init__(
        self,
        providers: list[ToolResultProvider],
        validator: ToolResultValidator,
    ) -> None:
        self._providers = providers
        self._validator = validator

    async def resolve(self, context: ProviderContext) -> ToolResolution:
        attempts: list[ProviderAttempt] = []
        validation_errors: list[str] = []
        for provider in self._providers:
            try:
                response = await provider.resolve(context)
            except Exception as exc:
                attempts.append(
                    ProviderAttempt(
                        provider=provider.name,
                        status=ProviderStatus.ERROR,
                        message=str(exc),
                    )
                )
                continue
            attempt = ProviderAttempt(
                provider=provider.name,
                status=response.status,
                message=response.message,
                metadata=response.metadata,
            )
            if response.status is not ProviderStatus.HIT:
                attempts.append(attempt)
                continue
            validation = self._validator.validate(
                response.result,
                result_schema=context.tool_call.result_schema,
            )
            if not validation.valid:
                attempt.status = ProviderStatus.ERROR
                attempt.message = "; ".join(validation.errors)
                attempts.append(attempt)
                validation_errors.extend(validation.errors)
                continue
            attempts.append(attempt)
            return ToolResolution(
                result=ToolResult(
                    tool_call_id=context.tool_call.id,
                    tool_name=context.tool_call.name,
                    result=response.result,
                    source=provider.name,
                    metadata=response.metadata,
                ),
                attempts=attempts,
                validation_errors=validation_errors,
            )
        raise ProviderExhausted(attempts, validation_errors)


class ProviderExhausted(AgentRigError):
    def __init__(
        self,
        attempts: list[ProviderAttempt],
        validation_errors: list[str],
    ) -> None:
        self.attempts = attempts
        self.validation_errors = validation_errors
        super().__init__(
            ErrorCode.PROVIDER_EXHAUSTED,
            "no configured provider produced a valid tool result",
            details={
                "attempts": [item.model_dump(mode="json") for item in attempts],
                "validation_errors": validation_errors,
            },
        )


class UnavailableProvider:
    def __init__(self, name: str) -> None:
        self.name = name

    async def resolve(self, context: ProviderContext) -> ProviderResponse:
        del context
        return ProviderResponse(
            status=ProviderStatus.UNAVAILABLE,
            message=f"{self.name} provider is not configured",
        )


def build_provider_chain(
    specs: list[ProviderSpec],
    *,
    samples: SampleRepository,
    validator: ToolResultValidator,
    custom_providers: dict[ProviderName, ToolResultProvider] | None = None,
) -> ProviderChain:
    custom = custom_providers or {}
    providers: list[ToolResultProvider] = []
    for spec in specs:
        if spec.name is ProviderName.FIXTURE:
            providers.append(FixtureProvider())
        elif spec.name is ProviderName.SAMPLE:
            providers.append(SampleProvider(samples))
        elif spec.name in custom:
            providers.append(custom[spec.name])
        else:
            providers.append(UnavailableProvider(spec.name.value))
    return ProviderChain(providers, validator)
