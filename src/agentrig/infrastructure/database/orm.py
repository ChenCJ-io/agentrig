"""AgentRig V1 的 11 张核心表与 V2 的 6 张协作表。

领域层只处理 Pydantic 对象；这些 ORM 类型仅由 infrastructure repository 使用。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TestCaseORM(Base):
    __tablename__ = "test_cases"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    supported_versions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    primary_evaluator: Mapped[str] = mapped_column(String(32), nullable=False)
    initial_state: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    case_assertions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    case_rubric: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    turns: Mapped[list[CaseTurnORM]] = relationship(
        back_populates="case",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="CaseTurnORM.position",
    )
    tags: Mapped[list[CaseTagORM]] = relationship(
        back_populates="case",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="CaseTagORM.tag",
    )


class CaseTurnORM(Base):
    __tablename__ = "case_turns"
    __table_args__ = (UniqueConstraint("case_id", "position"),)

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("test_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    user_message: Mapped[str] = mapped_column(Text, nullable=False)
    simulation_instruction: Mapped[str | None] = mapped_column(Text)
    fixtures: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    assertions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    rubric: Mapped[str | None] = mapped_column(Text)

    case: Mapped[TestCaseORM] = relationship(back_populates="turns")


class CaseTagORM(Base):
    __tablename__ = "case_tags"

    case_id: Mapped[str] = mapped_column(
        ForeignKey("test_cases.id", ondelete="CASCADE"), primary_key=True
    )
    tag: Mapped[str] = mapped_column(String(300), primary_key=True, index=True)

    case: Mapped[TestCaseORM] = relationship(back_populates="tags")


class SampleORM(Base):
    __tablename__ = "samples"
    __table_args__ = (Index("ix_samples_match", "tool_name", "status"),)

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    tool_name: Mapped[str | None] = mapped_column(String(300), index=True)
    sample_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[Any] = mapped_column(JSON)
    match_arguments: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    ignored_argument_paths: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    supported_versions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_tool_call_id: Mapped[str | None] = mapped_column(String(96), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class TargetORM(Base):
    __tablename__ = "targets"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    driver_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    endpoint: Mapped[str | None] = mapped_column(Text)
    secret_ref: Mapped[str | None] = mapped_column(String(300))
    options: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    versions: Mapped[list[TargetVersionORM]] = relationship(
        back_populates="target",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="TargetVersionORM.created_at",
    )


class TargetVersionORM(Base):
    __tablename__ = "target_versions"
    __table_args__ = (UniqueConstraint("target_id", "version"),)

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    target_id: Mapped[str] = mapped_column(
        ForeignKey("targets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[str] = mapped_column(String(300), nullable=False)
    endpoint_override: Mapped[str | None] = mapped_column(Text)
    options_override: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    target: Mapped[TargetORM] = relationship(back_populates="versions")


class ExecutionProfileORM(Base):
    __tablename__ = "execution_profiles"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class RunORM(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    selection_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    resolved_case_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    profile_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    target_snapshots: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cancelled_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)

    case_runs: Mapped[list[CaseRunORM]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        lazy="noload",
    )


class CaseRunORM(Base):
    __tablename__ = "case_runs"
    __table_args__ = (
        Index("ix_case_runs_run_status", "run_id", "status"),
        Index("ix_case_runs_pair", "comparison_pair_id", "comparison_role"),
    )

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    case_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    case_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    target_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    profile_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    version: Mapped[str | None] = mapped_column(String(300))
    repeat_index: Mapped[int] = mapped_column(Integer, nullable=False)
    comparison_pair_id: Mapped[str | None] = mapped_column(String(96))
    comparison_role: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    primary_evaluator: Mapped[str] = mapped_column(String(32), nullable=False)
    evaluation_state: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    run: Mapped[RunORM] = relationship(back_populates="case_runs")
    events: Mapped[list[RunEventORM]] = relationship(
        back_populates="case_run",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="RunEventORM.seq",
    )
    evaluations: Mapped[list[EvaluationORM]] = relationship(
        back_populates="case_run",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="EvaluationORM.created_at",
    )


class RunEventORM(Base):
    __tablename__ = "run_events"
    __table_args__ = (UniqueConstraint("case_run_id", "seq"),)

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    case_run_id: Mapped[str] = mapped_column(
        ForeignKey("case_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    case_run: Mapped[CaseRunORM] = relationship(back_populates="events")


class EvaluationORM(Base):
    __tablename__ = "evaluations"
    __table_args__ = (UniqueConstraint("case_run_id", "evaluator_type"),)

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    case_run_id: Mapped[str] = mapped_column(
        ForeignKey("case_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    evaluator_type: Mapped[str] = mapped_column(String(32), nullable=False)
    evaluator_source: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    verdict: Mapped[str | None] = mapped_column(String(32))
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    criteria: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    evidence_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    config_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    model_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    case_run: Mapped[CaseRunORM] = relationship(back_populates="evaluations")


class AssistantSessionORM(Base):
    __tablename__ = "assistant_sessions"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String(96), nullable=False, default="default", index=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    matrix_room_id: Mapped[str | None] = mapped_column(String(300), unique=True)
    active_plan_id: Mapped[str | None] = mapped_column(String(96), index=True)
    last_event_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[str] = mapped_column(String(300), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class AssistantEventORM(Base):
    __tablename__ = "assistant_events"
    __table_args__ = (
        UniqueConstraint("session_id", "seq"),
        UniqueConstraint("session_id", "client_message_id"),
        Index("ix_assistant_events_session_created", "session_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("assistant_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(300), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    turn_id: Mapped[str | None] = mapped_column(String(96), index=True)
    plan_id: Mapped[str | None] = mapped_column(String(96), index=True)
    run_id: Mapped[str | None] = mapped_column(String(96), index=True)
    case_run_id: Mapped[str | None] = mapped_column(String(96), index=True)
    invocation_id: Mapped[str | None] = mapped_column(String(96), index=True)
    client_message_id: Mapped[str | None] = mapped_column(String(128))
    matrix_event_id: Mapped[str | None] = mapped_column(String(300), unique=True)
    delivery_status: Mapped[str] = mapped_column(String(32), nullable=False)
    delivery_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class AssistantTurnORM(Base):
    __tablename__ = "assistant_turns"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("assistant_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    trigger_event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    matrix_request_event_id: Mapped[str | None] = mapped_column(String(300), unique=True)
    matrix_response_event_id: Mapped[str | None] = mapped_column(String(300), unique=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    model_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class EvaluationPlanORM(Base):
    __tablename__ = "evaluation_plans"
    __table_args__ = (UniqueConstraint("session_id", "revision"),)

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("assistant_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_turn_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    parent_plan_id: Mapped[str | None] = mapped_column(String(96), index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    goal: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    selection: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    reasoning_summary: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    preview: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    confirmation: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    selection_hash: Mapped[str | None] = mapped_column(String(64))
    submit_idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True)
    run_id: Mapped[str | None] = mapped_column(String(96), unique=True, index=True)
    last_error: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(300), nullable=False)
    confirmed_by: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentInvocationORM(Base):
    __tablename__ = "agent_invocations"
    __table_args__ = (
        UniqueConstraint("agent_role", "idempotency_key"),
        Index("ix_agent_invocations_run_role", "run_id", "agent_role"),
    )

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    agent_role: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    session_id: Mapped[str | None] = mapped_column(String(96), index=True)
    plan_id: Mapped[str | None] = mapped_column(String(96), index=True)
    run_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    case_run_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    tool_call_event_id: Mapped[str | None] = mapped_column(String(96), index=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    result_ref: Mapped[str | None] = mapped_column(String(300))
    result_hash: Mapped[str | None] = mapped_column(String(64))
    matrix_room_id: Mapped[str | None] = mapped_column(String(300))
    request_event_id: Mapped[str | None] = mapped_column(String(300), unique=True)
    response_event_id: Mapped[str | None] = mapped_column(String(300), unique=True)
    assigned_agent: Mapped[str | None] = mapped_column(String(300))
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IntegrationCursorORM(Base):
    __tablename__ = "integration_cursors"

    integration: Mapped[str] = mapped_column(String(128), primary_key=True)
    cursor: Mapped[str] = mapped_column(Text, nullable=False)
    cursor_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class TargetChatSessionORM(Base):
    """人工探索 Target 的可恢复历史；不属于权威 Evaluation 事实。"""

    __tablename__ = "target_chat_sessions"
    __table_args__ = (Index("ix_target_chat_sessions_target_updated", "target_id", "updated_at"),)

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    target_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    profile_id: Mapped[str | None] = mapped_column(String(96), index=True)
    version: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    events: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
