"""Admin side of the feedback loop (brief §16): the review list, the verified query
library (create, correct as a new version, disable) and turning feedback into eval cases.

Rules enforced here, whatever calls the service:
- SQL is saved only if it passes the SQL validator for every role it is allowed for.
- Allowed roles are never wider than the roles of the metrics the SQL uses.
- A correction is a new version in the same lineage; only one version per lineage is
  enabled. Disabled examples are never offered to the agent.
- Every change is written to the audit log.
"""

import datetime as dt
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import AuthenticatedUser
from app.core.enums import (
    CaseType,
    ErrorStatus,
    ExpectedBehaviour,
    Rating,
    ReviewStatus,
    RoleName,
)
from app.core.errors import AppError
from app.db.models import (
    AgentError,
    AgentRun,
    AuditLog,
    BlockedQuery,
    EvalCase,
    EvalDataset,
    Feedback,
    GeneratedQuery,
    Question,
    User,
    VerifiedQuery,
)
from app.safety.sql_validator import validate
from app.semantic.models import SemanticLayer

REVIEW_DATASET = "review-cases"
ReviewKind = Literal["not_helpful", "blocked", "failure"]
BUSINESS_ROLES = (RoleName.SALES_MANAGER, RoleName.FINANCE_ANALYST, RoleName.OPERATIONS_MANAGER)


class SqlInvalid(AppError):
    code = "SQL_INVALID"
    user_message = "The SQL did not pass validation."


class LibraryInputError(AppError):
    code = "VALIDATION_ERROR"
    user_message = "The verified query is not valid."


class NotFoundInLibrary(AppError):
    code = "NOT_FOUND"
    user_message = "Not found."


class AlreadyConverted(AppError):
    code = "CONFLICT"
    user_message = "This feedback has already been turned into an evaluation case."


class ReviewItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: ReviewKind
    id: str  # feedback id, blocked query id or error id (as text)
    question_id: uuid.UUID | None
    correlation_id: uuid.UUID | None
    question: str | None
    username: str | None
    role: str | None
    sql_text: str | None
    detail: str  # comment, block reason or error message
    status: str
    created_at: dt.datetime


class LibraryItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    lineage_id: uuid.UUID
    version: int
    question_text: str
    sql_text: str
    description: str
    tables_used: list[str]
    metrics_used: list[str]
    allowed_roles: list[str]
    is_active: bool
    verified_by: str | None
    verified_at: dt.datetime | None
    source_question_id: uuid.UUID | None


class EvalCaseCreated(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: int
    case_key: str
    dataset: str


class VerifyInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    question_text: str
    sql_text: str
    description: str
    allowed_roles: list[RoleName]
    metrics_used: list[str] = []
    source_question_id: uuid.UUID | None = None
    lineage_id: uuid.UUID | None = None


SemanticLoader = Callable[[], Awaitable[SemanticLayer]]


def check_sql_for_roles(
    sql: str, roles: list[RoleName], metrics: list[str], layer: SemanticLayer
) -> list[str]:
    """Validate ``sql`` for every role; return the tables it uses. Raises SqlInvalid."""
    if not roles or any(r not in BUSINESS_ROLES for r in roles):
        raise LibraryInputError(
            "bad roles", user_message="Choose at least one business role (not admin)."
        )
    for name in metrics:
        metric = layer.metrics.get(name)
        if metric is None:
            raise LibraryInputError(
                f"unknown metric {name}", user_message=f"Unknown metric: {name}."
            )
        wider = [r.value for r in roles if r not in metric.allowed_roles]
        if wider:
            raise LibraryInputError(
                f"metric {name} not allowed for {wider}",
                user_message=f"The metric {name} is not available to: {', '.join(wider)}.",
            )
    tables: set[str] = set()
    for role in roles:
        result = validate(sql, role, layer)
        if not result.allowed:
            raise SqlInvalid(
                f"{role.value}: {result.reason_code} {result.detail}",
                user_message=f"Not valid for {role.value.replace('_', ' ')}: "
                f"{result.user_message or result.reason_code}",
            )
        tables.update(result.tables)
    return sorted(tables)


class VerifiedLibraryService:
    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], load_semantic: SemanticLoader
    ) -> None:
        self.sessions = sessions
        self.load_semantic = load_semantic

    @staticmethod
    def _audit(
        session: AsyncSession, actor: AuthenticatedUser, event: str, target_type: str,
        target_id: str, details: dict[str, Any], correlation_id: uuid.UUID | None,
    ) -> None:  # fmt: skip
        session.add(AuditLog(
            correlation_id=correlation_id, actor_user_id=actor.user_id, event_type=event,
            target_type=target_type, target_id=target_id, details=details,
        ))  # fmt: skip

    # --- review list ---------------------------------------------------------------------

    @staticmethod
    async def _latest_sql(session: AsyncSession, question_id: uuid.UUID | None) -> str | None:
        if question_id is None:
            return None
        sql: str | None = await session.scalar(
            select(GeneratedQuery.sql_text)
            .join(AgentRun, AgentRun.id == GeneratedQuery.run_id)
            .where(AgentRun.question_id == question_id)
            .order_by(AgentRun.started_at.desc(), GeneratedQuery.attempt.desc())
            .limit(1)
        )
        return sql

    async def _not_helpful(self, session: AsyncSession, limit: int) -> tuple[list[ReviewItem], int]:
        where = (
            Feedback.rating == Rating.NOT_HELPFUL.value,
            Feedback.review_status == ReviewStatus.OPEN.value,
        )
        total = await session.scalar(select(func.count(Feedback.id)).where(*where)) or 0
        result = await session.execute(
            select(Feedback, Question, User.username)
            .join(Question, Question.id == Feedback.question_id)
            .join(User, User.id == Question.user_id)
            .where(*where)
            .order_by(Feedback.updated_at.desc())
            .limit(limit)
        )
        items = [
            ReviewItem(
                kind="not_helpful",
                id=str(fb.id),
                question_id=q.id,
                correlation_id=q.correlation_id,
                question=q.question_text,
                username=username,
                role=q.role_name,
                sql_text=await self._latest_sql(session, q.id),
                detail=fb.comment or "Rated not helpful (no comment).",
                status=fb.review_status,
                created_at=fb.updated_at,
            )
            for fb, q, username in result.all()
        ]
        return items, total

    async def _blocked(self, session: AsyncSession, limit: int) -> tuple[list[ReviewItem], int]:
        total = await session.scalar(select(func.count(BlockedQuery.id))) or 0
        result = await session.execute(
            select(
                BlockedQuery,
                AgentRun.correlation_id,
                Question,
                User.username,
                GeneratedQuery.sql_text,
            )
            .join(AgentRun, AgentRun.id == BlockedQuery.run_id)
            .join(Question, Question.id == AgentRun.question_id)
            .outerjoin(User, User.id == Question.user_id)
            .outerjoin(GeneratedQuery, GeneratedQuery.id == BlockedQuery.generated_query_id)
            .order_by(BlockedQuery.created_at.desc())
            .limit(limit)
        )
        items = [
            ReviewItem(
                kind="blocked",
                id=str(bq.id),
                question_id=q.id,
                correlation_id=correlation_id,
                question=q.question_text,
                username=username,
                role=q.role_name,
                sql_text=sql,
                detail=f"{bq.reason_code}: {bq.reason_text}",
                status=bq.stage,
                created_at=bq.created_at,
            )
            for bq, correlation_id, q, username, sql in result.all()
        ]
        return items, total

    async def _failures(self, session: AsyncSession, limit: int) -> tuple[list[ReviewItem], int]:
        is_open = AgentError.status == ErrorStatus.OPEN.value
        total = await session.scalar(select(func.count(AgentError.id)).where(is_open)) or 0
        result = await session.execute(
            select(AgentError, Question, User.username)
            .outerjoin(Question, Question.id == AgentError.question_id)
            .outerjoin(User, User.id == Question.user_id)
            .where(is_open)
            .order_by(AgentError.created_at.desc())
            .limit(limit)
        )
        items = []
        for err, q, username in result.all():
            items.append(
                ReviewItem(
                    kind="failure",
                    id=str(err.id),
                    question_id=q.id if q else None,
                    correlation_id=err.correlation_id,
                    question=q.question_text if q else None,
                    username=username,
                    role=q.role_name if q else None,
                    sql_text=await self._latest_sql(session, q.id if q else None),
                    detail=f"{err.error_type}: {err.error_message}",
                    status=err.status,
                    created_at=err.created_at,
                )
            )
        return items, total

    async def review(
        self, *, page: int, page_size: int, kind: ReviewKind | None = None
    ) -> tuple[list[ReviewItem], int]:
        """Not-helpful answers, blocked queries and open failures in one list, newest first.

        Each source is read newest first up to the end of the requested page, then merged."""
        need = page * page_size
        items: list[ReviewItem] = []
        total = 0
        async with self.sessions() as session:
            sources = {
                "not_helpful": self._not_helpful,
                "blocked": self._blocked,
                "failure": self._failures,
            }
            for name, load in sources.items():
                if kind in (None, name):
                    part, count = await load(session, need)
                    items.extend(part)
                    total += count
        items.sort(key=lambda item: item.created_at, reverse=True)
        start = (page - 1) * page_size
        return items[start : start + page_size], total

    # --- library -------------------------------------------------------------------------

    async def list_queries(
        self, *, page: int, page_size: int, is_active: bool | None = None
    ) -> tuple[list[LibraryItem], int]:
        query = (
            select(VerifiedQuery, User.username)
            .outerjoin(User, User.id == VerifiedQuery.verified_by)
            .order_by(
                VerifiedQuery.is_active.desc(),
                VerifiedQuery.question_text,
                VerifiedQuery.version.desc(),
            )
        )
        count = select(func.count(VerifiedQuery.id))
        if is_active is not None:
            query = query.where(VerifiedQuery.is_active.is_(is_active))
            count = count.where(VerifiedQuery.is_active.is_(is_active))
        async with self.sessions() as session:
            total = await session.scalar(count) or 0
            rows = await session.execute(query.limit(page_size).offset((page - 1) * page_size))
            return [self._item(vq, username) for vq, username in rows.all()], total

    @staticmethod
    def _item(vq: VerifiedQuery, username: str | None) -> LibraryItem:
        return LibraryItem(
            id=vq.id, lineage_id=vq.lineage_id, version=vq.version,
            question_text=vq.question_text, sql_text=vq.sql_text, description=vq.description,
            tables_used=list(vq.tables_used), metrics_used=list(vq.metrics_used),
            allowed_roles=list(vq.allowed_roles), is_active=vq.is_active,
            verified_by=username or ("seed" if vq.verified_by is None else None),
            verified_at=vq.verified_at, source_question_id=vq.source_question_id,
        )  # fmt: skip

    async def verify(
        self, actor: AuthenticatedUser, data: VerifyInput, correlation_id: uuid.UUID | None = None
    ) -> LibraryItem:
        """Save a verified query, or a corrected new version when ``lineage_id`` is given."""
        layer = await self.load_semantic()
        tables = check_sql_for_roles(data.sql_text, data.allowed_roles, data.metrics_used, layer)
        async with self.sessions() as session, session.begin():
            source = data.source_question_id
            if source is not None and await session.get(Question, source) is None:
                raise NotFoundInLibrary(f"question {source}")
            version = 1
            lineage = data.lineage_id or uuid.uuid4()
            if data.lineage_id is not None:
                latest = await session.scalar(
                    select(func.max(VerifiedQuery.version)).where(
                        VerifiedQuery.lineage_id == data.lineage_id
                    )
                )
                if latest is None:
                    raise NotFoundInLibrary(f"lineage {data.lineage_id}")
                version = latest + 1
                await session.execute(
                    update(VerifiedQuery)
                    .where(VerifiedQuery.lineage_id == data.lineage_id)
                    .values(is_active=False)
                )
            vq = VerifiedQuery(
                lineage_id=lineage, version=version, question_text=data.question_text.strip(),
                sql_text=data.sql_text.strip(), description=data.description.strip(),
                tables_used=tables, metrics_used=list(data.metrics_used),
                allowed_roles=[r.value for r in data.allowed_roles], is_active=True,
                source_question_id=data.source_question_id, verified_by=actor.user_id,
                verified_at=dt.datetime.now(dt.UTC),
            )  # fmt: skip
            session.add(vq)
            if data.source_question_id is not None:
                await session.execute(
                    update(Feedback)
                    .where(
                        Feedback.question_id == data.source_question_id,
                        Feedback.review_status == ReviewStatus.OPEN.value,
                    )
                    .values(review_status=ReviewStatus.VERIFIED.value)
                )
            await session.flush()
            self._audit(session, actor, "verified_query_corrected" if version > 1
                        else "verified_query_created", "verified_query", str(vq.id),
                        {"lineage_id": str(lineage), "version": version,
                         "allowed_roles": vq.allowed_roles}, correlation_id)  # fmt: skip
            return self._item(vq, actor.username)

    async def set_active(
        self, actor: AuthenticatedUser, query_id: uuid.UUID, active: bool,
        correlation_id: uuid.UUID | None = None,
    ) -> LibraryItem:  # fmt: skip
        async with self.sessions() as session, session.begin():
            vq = await session.get(VerifiedQuery, query_id)
            if vq is None:
                raise NotFoundInLibrary(f"verified query {query_id}")
            if active:
                # Re-check against today's semantic layer before offering it again.
                layer = await self.load_semantic()
                roles = [RoleName(r) for r in vq.allowed_roles]
                vq.tables_used = check_sql_for_roles(vq.sql_text, roles, list(vq.metrics_used),
                                                     layer)  # fmt: skip
                await session.execute(
                    update(VerifiedQuery)
                    .where(VerifiedQuery.lineage_id == vq.lineage_id, VerifiedQuery.id != vq.id)
                    .values(is_active=False)
                )
                await session.flush()
            vq.is_active = active
            self._audit(session, actor, "verified_query_enabled" if active
                        else "verified_query_disabled", "verified_query", str(vq.id),
                        {"lineage_id": str(vq.lineage_id), "version": vq.version},
                        correlation_id)  # fmt: skip
            await session.flush()
            username = await session.scalar(select(User.username).where(User.id == vq.verified_by))
            return self._item(vq, username)

    # --- feedback -> evaluation case ----------------------------------------------------

    async def to_eval_case(
        self, actor: AuthenticatedUser, feedback_id: int, *, case_type: CaseType,
        expected_behaviour: ExpectedBehaviour, expected_sql: str | None,
        correlation_id: uuid.UUID | None = None,
    ) -> EvalCaseCreated:  # fmt: skip
        async with self.sessions() as session, session.begin():
            row = (await session.execute(
                select(Feedback, Question, User)
                .join(Question, Question.id == Feedback.question_id)
                .join(User, User.id == Question.user_id)
                .where(Feedback.id == feedback_id)
            )).first()  # fmt: skip
            if row is None:
                raise NotFoundInLibrary(f"feedback {feedback_id}")
            feedback, question, owner = row
            if feedback.review_status == ReviewStatus.CONVERTED.value:
                raise AlreadyConverted(f"feedback {feedback_id}")
            if expected_sql and expected_sql.strip():
                if not question.role_name:
                    raise LibraryInputError("no role", user_message="The question had no role.")
                layer = await self.load_semantic()
                check_sql_for_roles(expected_sql, [RoleName(question.role_name)], [], layer)
            dataset = await session.scalar(
                select(EvalDataset).where(EvalDataset.name == REVIEW_DATASET)
                .order_by(EvalDataset.version.desc()).limit(1)
            )  # fmt: skip
            if dataset is None:
                dataset = EvalDataset(name=REVIEW_DATASET, version=1,
                                      file_path="database (from admin review)")  # fmt: skip
                session.add(dataset)
                await session.flush()
            case = EvalCase(
                dataset_id=dataset.id, case_key=f"FB-{feedback_id}", case_type=case_type.value,
                test_username=owner.username, question=question.question_text,
                expected_behaviour=expected_behaviour.value,
                expected_sql=(expected_sql or "").strip() or None,
                source_feedback_id=feedback.id,
            )  # fmt: skip
            session.add(case)
            feedback.review_status = ReviewStatus.CONVERTED.value
            await session.flush()
            self._audit(session, actor, "eval_case_created", "eval_case", str(case.id),
                        {"feedback_id": feedback_id, "case_key": case.case_key},
                        correlation_id)  # fmt: skip
            return EvalCaseCreated(case_id=case.id, case_key=case.case_key, dataset=dataset.name)
