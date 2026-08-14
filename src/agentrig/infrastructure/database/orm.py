"""AgentRig V1 核心表与 V2/V2.1 协作、决策表。

领域层只处理 Pydantic 对象；这些 ORM 类型仅由 infrastructure repository 使用。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
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


class ProjectORM(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    slug: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    default_environment: Mapped[str] = mapped_column(String(128), nullable=False)
    redaction_policy_id: Mapped[str | None] = mapped_column(String(96))
    retention_policy_id: Mapped[str | None] = mapped_column(String(96))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EnvironmentORM(Base):
    __tablename__ = "environments"
    __table_args__ = (UniqueConstraint("project_id", "name"),)

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    release_metadata_schema: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    protected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class ProjectApiKeyORM(Base):
    __tablename__ = "project_api_keys"
    __table_args__ = (Index("ix_project_api_keys_project_active", "project_id", "revoked_at"),)

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class TestCaseORM(Base):
    __tablename__ = "test_cases"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(96), nullable=False, default="default", index=True
    )
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
    project_id: Mapped[str] = mapped_column(
        String(96), nullable=False, default="default", index=True
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    tool_name: Mapped[str | None] = mapped_column(String(300), index=True)
    sample_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[Any | None] = mapped_column(JSON)
    match_arguments: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    ignored_argument_paths: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
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
    project_id: Mapped[str] = mapped_column(
        String(96), nullable=False, default="default", index=True
    )
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
    project_id: Mapped[str] = mapped_column(
        String(96), nullable=False, default="default", index=True
    )
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
    project_id: Mapped[str] = mapped_column(
        String(96), nullable=False, default="default", index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    selection_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    resolved_case_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    profile_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    target_snapshots: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    manifest_schema_version: Mapped[str | None] = mapped_column(String(64))
    manifest_hash: Mapped[str | None] = mapped_column(String(72), index=True)
    manifest: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    recovery_of_run_id: Mapped[str | None] = mapped_column(String(96), index=True)
    recovery_reason: Mapped[str | None] = mapped_column(Text)
    cell_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    finished_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
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
        Index("ix_case_runs_run_cell", "run_id", "cell_key"),
        UniqueConstraint("evaluation_attempt_id"),
    )

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(96), nullable=False, default="default", index=True
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    case_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    case_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    target_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    profile_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    capability_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    version: Mapped[str | None] = mapped_column(String(300))
    repeat_index: Mapped[int] = mapped_column(Integer, nullable=False)
    comparison_pair_id: Mapped[str | None] = mapped_column(String(96))
    comparison_role: Mapped[str | None] = mapped_column(String(32))
    cell_key: Mapped[str | None] = mapped_column(String(72))
    evaluation_attempt_id: Mapped[str | None] = mapped_column(String(96))
    attempt_index: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    primary_evaluator: Mapped[str] = mapped_column(String(32), nullable=False)
    evaluation_state: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    failure_class: Mapped[str | None] = mapped_column(String(64), index=True)
    recovery_of_case_run_id: Mapped[str | None] = mapped_column(String(96), index=True)
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
    attempt_id: Mapped[str | None] = mapped_column(String(96), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    case_run: Mapped[CaseRunORM] = relationship(back_populates="events")


class EvaluationORM(Base):
    __tablename__ = "evaluations"
    __table_args__ = (UniqueConstraint("case_run_id", "evaluator_type"),)

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(96), nullable=False, default="default", index=True
    )
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
    project_id: Mapped[str] = mapped_column(
        String(96), nullable=False, default="default", index=True
    )
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
    decision_id: Mapped[str | None] = mapped_column(String(96), index=True)
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
    __table_args__ = (
        UniqueConstraint("session_id", "revision"),
        UniqueConstraint("run_id"),
        Index("ix_evaluation_plans_run_id", "run_id"),
    )

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(96), nullable=False, default="default", index=True
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("assistant_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_turn_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    parent_plan_id: Mapped[str | None] = mapped_column(String(96), index=True)
    origin_decision_id: Mapped[str | None] = mapped_column(String(96), index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    goal: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    selection: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    reasoning_summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    preview: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    confirmation: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    selection_hash: Mapped[str | None] = mapped_column(String(64))
    submit_idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True)
    run_id: Mapped[str | None] = mapped_column(String(96))
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
    project_id: Mapped[str] = mapped_column(
        String(96), nullable=False, default="default", index=True
    )
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


class DecisionRecordORM(Base):
    __tablename__ = "decision_records"
    __table_args__ = (
        UniqueConstraint("session_id", "turn_id", "ordinal"),
        UniqueConstraint("action_idempotency_key"),
        Index("ix_decision_records_session_created", "session_id", "created_at"),
        Index("ix_decision_records_action_ref", "action_ref_type", "action_ref_id"),
    )

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(96), nullable=False, default="default", index=True
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("assistant_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    turn_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    parent_decision_id: Mapped[str | None] = mapped_column(String(96), index=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    observation_summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    options: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    selected_action: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    rationale_summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    evidence_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    context_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_verdict: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    confirmation_event_id: Mapped[str | None] = mapped_column(String(96), index=True)
    action_idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    action_ref_type: Mapped[str | None] = mapped_column(String(64))
    action_ref_id: Mapped[str | None] = mapped_column(String(96))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    proposed_by: Mapped[str] = mapped_column(String(300), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
    project_id: Mapped[str] = mapped_column(
        String(96), nullable=False, default="default", index=True
    )
    target_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    profile_id: Mapped[str | None] = mapped_column(String(96), index=True)
    version: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    events: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IngestSourceORM(Base):
    __tablename__ = "ingest_sources"
    __table_args__ = (UniqueConstraint("project_id", "name"),)

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    api_key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    key_prefix: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    allowed_service_names: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    redaction_policy: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, nullable=False)
    daily_span_quota: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProductionSessionORM(Base):
    __tablename__ = "production_sessions"
    __table_args__ = (UniqueConstraint("project_id", "source_id", "external_session_id_hash"),)

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("ingest_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_session_id_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    environment: Mapped[str | None] = mapped_column(String(128), index=True)
    release: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    user_identity_hash: Mapped[str | None] = mapped_column(String(64))
    trace_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class ProductionTraceORM(Base):
    __tablename__ = "production_traces"
    __table_args__ = (
        UniqueConstraint("project_id", "source_id", "external_trace_id"),
        Index("ix_production_traces_project_time", "project_id", "started_at"),
        Index("ix_production_traces_project_status", "project_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("production_sessions.id", ondelete="SET NULL"), index=True
    )
    external_trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    root_span_id: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    service_name: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    environment: Mapped[str | None] = mapped_column(String(128), index=True)
    release: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    input_preview_redacted: Mapped[str | None] = mapped_column(Text)
    output_preview_redacted: Mapped[str | None] = mapped_column(Text)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    token_usage: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    cost_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    ingest_status: Mapped[str] = mapped_column(String(32), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(72), nullable=False)
    redaction_policy_hash: Mapped[str] = mapped_column(String(72), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class ProductionSpanORM(Base):
    __tablename__ = "production_spans"
    __table_args__ = (
        UniqueConstraint("trace_id", "external_span_id"),
        Index("ix_production_spans_trace_time", "trace_id", "started_at"),
    )

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    trace_id: Mapped[str] = mapped_column(
        ForeignKey("production_traces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_span_id: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_external_span_id: Mapped[str | None] = mapped_column(String(64), index=True)
    span_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    agent_path: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    model_call: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    tool_call: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    tool_result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    permission: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    memory_operation: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    artifact_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    events: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    content_hash: Mapped[str] = mapped_column(String(72), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class TraceCaseLineageORM(Base):
    __tablename__ = "trace_case_lineages"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    source_trace_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    source_span_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    annotation_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    failure_pattern_id: Mapped[str | None] = mapped_column(String(96), index=True)
    draft_case_id: Mapped[str | None] = mapped_column(String(96), index=True)
    draft_sample_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    mapping_version: Mapped[str] = mapped_column(String(64), nullable=False)
    mapping_hash: Mapped[str] = mapped_column(String(72), nullable=False)
    created_by: Mapped[str] = mapped_column(String(300), nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class ReviewItemORM(Base):
    __tablename__ = "review_items"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    subject_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    subject_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    subject_snapshot_hash: Mapped[str] = mapped_column(String(72), nullable=False)
    queue: Mapped[str] = mapped_column(String(128), nullable=False, default="default", index=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    assignment: Mapped[str | None] = mapped_column(String(300), index=True)
    cohort: Mapped[str | None] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    required_reviews: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(String(300), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AnnotationORM(Base):
    __tablename__ = "annotations"
    __table_args__ = (UniqueConstraint("review_item_id", "revision"),)

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    review_item_id: Mapped[str] = mapped_column(
        ForeignKey("review_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(32), nullable=False)
    criteria: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    annotator_id: Mapped[str] = mapped_column(String(300), nullable=False)
    confidence: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="submitted")
    supersedes_id: Mapped[str | None] = mapped_column(String(96))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class GoldLabelORM(Base):
    __tablename__ = "gold_labels"
    __table_args__ = (UniqueConstraint("review_item_id", "revision"),)

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    review_item_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(32), nullable=False)
    annotation_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    resolution_method: Mapped[str] = mapped_column(String(64), nullable=False)
    adjudicator_id: Mapped[str] = mapped_column(String(300), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(72), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class EvaluatorVersionORM(Base):
    __tablename__ = "evaluator_versions"
    __table_args__ = (UniqueConstraint("project_id", "evaluator_id", "version"),)

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    evaluator_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluator_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    config_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(72), nullable=False)
    created_by: Mapped[str] = mapped_column(String(300), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(300))
    alignment_run_id: Mapped[str | None] = mapped_column(String(96))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AlignmentRunORM(Base):
    __tablename__ = "alignment_runs"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    evaluator_version_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    gold_label_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    predictions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    cohort_metrics: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    disagreements: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    source_snapshot_hash: Mapped[str] = mapped_column(String(72), nullable=False)
    limitations: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FailureSignalORM(Base):
    __tablename__ = "failure_signals"
    __table_args__ = (
        UniqueConstraint("project_id", "source_type", "source_id", "detector_version"),
    )

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[str] = mapped_column(String(96), nullable=False)
    source_snapshot_hash: Mapped[str] = mapped_column(String(72), nullable=False)
    detector_version: Mapped[str] = mapped_column(String(64), nullable=False)
    signature: Mapped[str] = mapped_column(String(72), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    environment: Mapped[str | None] = mapped_column(String(128), index=True)
    release: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    target_runtime: Mapped[str | None] = mapped_column(String(300), index=True)
    evidence_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class FailurePatternORM(Base):
    __tablename__ = "failure_patterns"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    signature: Mapped[str] = mapped_column(String(72), nullable=False, index=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    definition_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    matcher: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    owner: Mapped[str | None] = mapped_column(String(300))
    confirmed_by: Mapped[str | None] = mapped_column(String(300))
    resolved_by_run_id: Mapped[str | None] = mapped_column(String(96))
    ignored_reason: Mapped[str | None] = mapped_column(Text)
    ignored_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    representative_signal_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    linked_case_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    linked_suite_versions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    linked_release_gate_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    release: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class FailurePatternMembershipORM(Base):
    __tablename__ = "failure_pattern_memberships"

    pattern_id: Mapped[str] = mapped_column(
        ForeignKey("failure_patterns.id", ondelete="CASCADE"), primary_key=True
    )
    signal_id: Mapped[str] = mapped_column(
        ForeignKey("failure_signals.id", ondelete="CASCADE"), primary_key=True
    )
    definition_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    membership_source: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    explanation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="candidate")
    accepted_by: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class FailureMonitorORM(Base):
    __tablename__ = "failure_monitors"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    pattern_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    environment: Mapped[str | None] = mapped_column(String(128))
    definition_version: Mapped[int] = mapped_column(Integer, nullable=False)
    cursor: Mapped[str | None] = mapped_column(String(300))
    shadow_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    recurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notification_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class FailurePatternEventORM(Base):
    __tablename__ = "failure_pattern_events"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    pattern_id: Mapped[str] = mapped_column(
        ForeignKey("failure_patterns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String(300), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class FailureNotificationORM(Base):
    __tablename__ = "failure_notifications"
    __table_args__ = (UniqueConstraint("monitor_id", "idempotency_key"),)

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    monitor_id: Mapped[str] = mapped_column(
        ForeignKey("failure_monitors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pattern_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(72), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    last_error: Mapped[str | None] = mapped_column(Text)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class GovernanceAuditEventORM(Base):
    __tablename__ = "governance_audit_events"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    aggregate_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String(300), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class ExecutionJobORM(Base):
    __tablename__ = "execution_jobs"
    __table_args__ = (
        UniqueConstraint("project_id", "idempotency_key"),
        UniqueConstraint("project_id", "case_run_id"),
        Index("ix_execution_jobs_claim", "status", "available_at", "priority"),
    )

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    case_run_id: Mapped[str] = mapped_column(
        ForeignKey("case_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(300), index=True)
    lease_token_hash: Mapped[str | None] = mapped_column(String(64))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    external_side_effect: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class ExecutionAttemptORM(Base):
    __tablename__ = "execution_attempts"
    __table_args__ = (UniqueConstraint("job_id", "attempt"),)

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("execution_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    lease_owner: Mapped[str] = mapped_column(String(300), nullable=False)
    lease_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    external_side_effect: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class WorkerRegistrationORM(Base):
    __tablename__ = "worker_registrations"

    id: Mapped[str] = mapped_column(String(300), primary_key=True)
    backend: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
