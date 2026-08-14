"""Project repository service with one-time keys and non-enumerating lookups."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timezone

from sqlalchemy import func, select

from ..canonical import canonical_hash
from ..errors import AgentRigError, ErrorCode
from ..identifiers import new_id
from ..infrastructure.database.orm import (
    EnvironmentORM,
    ProjectApiKeyORM,
    ProjectORM,
    utc_now,
)
from ..infrastructure.database.session import Database
from .schemas import (
    EnvironmentCreate,
    EnvironmentView,
    ProjectApiKeyCreate,
    ProjectApiKeyIssue,
    ProjectApiKeyView,
    ProjectContext,
    ProjectCreate,
    ProjectPage,
    ProjectScope,
    ProjectView,
    ReleaseRef,
)


class ProjectService:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def ensure_default(self) -> ProjectView:
        async with self._database.session() as session:
            row = await session.get(ProjectORM, "default")
            if row is None:
                row = ProjectORM(
                    id="default",
                    slug="default",
                    name="Default Project",
                    status="active",
                    default_environment="development",
                )
                session.add(row)
                # Flush the parent explicitly.  The ORM models deliberately do
                # not expose mutable Project relationships, so SQLAlchemy's
                # unit-of-work cannot infer object-level insert ordering from
                # an assigned ``project_id`` alone on every supported dialect.
                await session.flush()
                session.add(
                    EnvironmentORM(
                        id="env_default_development",
                        project_id="default",
                        name="development",
                        kind="development",
                        protected=False,
                    )
                )
                await session.commit()
            return self._project_view(row)

    async def create(self, value: ProjectCreate) -> ProjectView:
        project_id = value.id or new_id("project")
        async with self._database.session() as session:
            existing = await session.scalar(
                select(ProjectORM.id).where(
                    (ProjectORM.id == project_id) | (ProjectORM.slug == value.slug)
                )
            )
            if existing is not None:
                raise AgentRigError(ErrorCode.CONFLICT, "project id or slug already exists")
            row = ProjectORM(
                id=project_id,
                slug=value.slug,
                name=value.name,
                status="active",
                default_environment=value.default_environment,
                redaction_policy_id=value.redaction_policy_id,
                retention_policy_id=value.retention_policy_id,
            )
            session.add(row)
            await session.flush()
            session.add(
                EnvironmentORM(
                    id=new_id("env"),
                    project_id=project_id,
                    name=value.default_environment,
                    kind="development",
                    protected=False,
                )
            )
            await session.commit()
            await session.refresh(row)
            return self._project_view(row)

    async def get(self, project_id: str) -> ProjectView:
        async with self._database.session() as session:
            row = await session.get(ProjectORM, project_id)
        if row is None:
            raise AgentRigError(ErrorCode.NOT_FOUND, "project not found")
        return self._project_view(row)

    async def list_projects(self, *, limit: int = 50, offset: int = 0) -> ProjectPage:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        async with self._database.session() as session:
            total = int(await session.scalar(select(func.count(ProjectORM.id))) or 0)
            rows = list(
                await session.scalars(
                    select(ProjectORM)
                    .order_by(ProjectORM.created_at, ProjectORM.id)
                    .limit(limit)
                    .offset(offset)
                )
            )
        return ProjectPage(
            items=[self._project_view(row) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def create_environment(
        self,
        project_id: str,
        value: EnvironmentCreate,
    ) -> EnvironmentView:
        await self.get(project_id)
        if value.kind == "production" and not value.protected:
            raise AgentRigError(
                ErrorCode.VALIDATION_ERROR,
                "production environments must be protected",
            )
        row = EnvironmentORM(
            id=new_id("env"),
            project_id=project_id,
            **value.model_dump(),
        )
        async with self._database.session() as session:
            session.add(row)
            try:
                await session.commit()
            except Exception as exc:
                raise AgentRigError(
                    ErrorCode.CONFLICT,
                    "environment already exists in project",
                ) from exc
            await session.refresh(row)
        return self._environment_view(row)

    async def list_environments(self, project_id: str) -> list[EnvironmentView]:
        await self.get(project_id)
        async with self._database.session() as session:
            rows = list(
                await session.scalars(
                    select(EnvironmentORM)
                    .where(EnvironmentORM.project_id == project_id)
                    .order_by(EnvironmentORM.name)
                )
            )
        return [self._environment_view(row) for row in rows]

    async def issue_api_key(
        self,
        project_id: str,
        value: ProjectApiKeyCreate,
    ) -> ProjectApiKeyIssue:
        await self.get(project_id)
        if value.expires_at is not None and self._as_utc(
            value.expires_at
        ) <= datetime.now(timezone.utc):
            raise AgentRigError(ErrorCode.VALIDATION_ERROR, "API key expiry must be future")
        secret = secrets.token_urlsafe(32)
        prefix = secrets.token_hex(5)
        token = f"agrp_{prefix}_{secret}"
        row = ProjectApiKeyORM(
            id=new_id("pkey"),
            project_id=project_id,
            name=value.name,
            key_prefix=prefix,
            key_hash=self._token_hash(token),
            scopes=value.scopes,
            expires_at=value.expires_at,
        )
        async with self._database.session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return ProjectApiKeyIssue(api_key=self._key_view(row), token=token)

    async def list_api_keys(self, project_id: str) -> list[ProjectApiKeyView]:
        await self.get(project_id)
        async with self._database.session() as session:
            rows = list(
                await session.scalars(
                    select(ProjectApiKeyORM)
                    .where(ProjectApiKeyORM.project_id == project_id)
                    .order_by(ProjectApiKeyORM.created_at)
                )
            )
        return [self._key_view(row) for row in rows]

    async def revoke_api_key(self, project_id: str, key_id: str) -> ProjectApiKeyView:
        async with self._database.session() as session:
            row = await session.scalar(
                select(ProjectApiKeyORM).where(
                    ProjectApiKeyORM.id == key_id,
                    ProjectApiKeyORM.project_id == project_id,
                )
            )
            if row is None:
                raise AgentRigError(ErrorCode.NOT_FOUND, "project API key not found")
            if row.revoked_at is None:
                row.revoked_at = utc_now()
                await session.commit()
            return self._key_view(row)

    async def authenticate(
        self,
        project_id: str,
        token: str,
        required_scope: ProjectScope,
    ) -> ProjectContext:
        parts = token.split("_", 2)
        if len(parts) != 3 or parts[0] != "agrp":
            raise AgentRigError(ErrorCode.PERMISSION_DENIED, "invalid project API key")
        prefix = parts[1]
        async with self._database.session() as session:
            row = await session.scalar(
                select(ProjectApiKeyORM).where(
                    ProjectApiKeyORM.project_id == project_id,
                    ProjectApiKeyORM.key_prefix == prefix,
                )
            )
            now = utc_now()
            expires_at = self._as_utc(row.expires_at) if row and row.expires_at else None
            valid = (
                row is not None
                and row.revoked_at is None
                and (expires_at is None or expires_at > now)
                and hmac.compare_digest(row.key_hash, self._token_hash(token))
                and (required_scope in row.scopes or "admin" in row.scopes)
            )
            if not valid or row is None:
                raise AgentRigError(ErrorCode.PERMISSION_DENIED, "invalid project API key")
            row.last_used_at = now
            await session.commit()
            return ProjectContext.model_validate(
                {
                    "project_id": project_id,
                    "principal_id": f"api-key:{row.id}",
                    "scopes": row.scopes,
                    "api_key_id": row.id,
                }
            )

    @staticmethod
    def freeze_release(value: dict[str, object]) -> ReleaseRef:
        stable = {key: item for key, item in value.items() if key != "content_hash"}
        return ReleaseRef.model_validate({**stable, "content_hash": canonical_hash(stable)})

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _project_view(row: ProjectORM) -> ProjectView:
        return ProjectView.model_validate(row, from_attributes=True)

    @staticmethod
    def _environment_view(row: EnvironmentORM) -> EnvironmentView:
        return EnvironmentView.model_validate(row, from_attributes=True)

    @staticmethod
    def _key_view(row: ProjectApiKeyORM) -> ProjectApiKeyView:
        return ProjectApiKeyView.model_validate(row, from_attributes=True)
