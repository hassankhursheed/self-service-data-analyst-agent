"""Admin routes: review, re-run, user management, and placeholders for later steps."""

import datetime as dt
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query, status

from app.api.deps import CorrelationId, PagingDep, ServicesDep
from app.api.errors import error_responses
from app.api.schemas import (
    AlertList,
    BlockedItem,
    BlockedList,
    CreateUserRequest,
    ErrorItem,
    ErrorList,
    EvalCaseRequest,
    EvalCaseResponse,
    EvalRunDetailResponse,
    EvalRunList,
    EvalRunRequest,
    EvalRunStarted,
    MetricsResponse,
    RerunResponse,
    ResetPasswordRequest,
    ReviewList,
    UpdateUserRequest,
    UpdateVerifiedRequest,
    UserList,
    UserResponse,
    VerifiedQueryList,
    VerifiedQueryResponse,
    VerifyRequest,
)
from app.auth.dependencies import AdminUser
from app.core.enums import ErrorStatus, EvalRunStatus, RoleName
from app.eval.cases import load_cases
from app.eval.runner import EvalInputError, EvalOptions, get_eval_config
from app.services.users import UserNotFound, UserView
from app.services.verified_library import VerifyInput

router = APIRouter(prefix="/admin", tags=["admin"])
ERRORS = error_responses(400, 401, 403, 404, 409, 500)


def _user(correlation_id: uuid.UUID, view: UserView) -> UserResponse:
    return UserResponse(correlation_id=correlation_id, **view.model_dump())


# --- review ----------------------------------------------------------------------------


@router.get("/blocked", response_model=BlockedList, responses=ERRORS)
async def blocked(
    _: AdminUser,
    services: ServicesDep,
    paging: PagingDep,
    correlation_id: CorrelationId,
    reason_code: str | None = None,
    date_from: Annotated[dt.date | None, Query(alias="from")] = None,
    date_to: Annotated[dt.date | None, Query(alias="to")] = None,
) -> BlockedList:
    result = await services.review.blocked(
        page=paging.page,
        page_size=paging.page_size,
        reason_code=reason_code,
        date_from=date_from,
        date_to=date_to,
    )
    return BlockedList(
        correlation_id=correlation_id,
        items=[BlockedItem(**r) for r in result.rows],
        total=result.total,
        page=paging.page,
        page_size=paging.page_size,
    )


@router.get("/errors", response_model=ErrorList, responses=ERRORS)
async def errors(
    _: AdminUser,
    services: ServicesDep,
    paging: PagingDep,
    correlation_id: CorrelationId,
    status: ErrorStatus | None = None,
    node_name: str | None = None,
) -> ErrorList:
    result = await services.review.errors(
        page=paging.page, page_size=paging.page_size, status=status, node_name=node_name
    )
    return ErrorList(
        correlation_id=correlation_id,
        items=[ErrorItem(**r) for r in result.rows],
        total=result.total,
        page=paging.page,
        page_size=paging.page_size,
    )


@router.post(
    "/errors/{error_id}/rerun",
    response_model=RerunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses=ERRORS,
)
async def rerun(
    error_id: int, admin: AdminUser, services: ServicesDep, correlation_id: CorrelationId
) -> RerunResponse:
    result = await services.review.rerun(admin, error_id, correlation_id)
    return RerunResponse(
        correlation_id=correlation_id,
        error_id=result.error_id,
        new_question_id=result.question_id,
        conversation_id=result.conversation_id,
        status=result.state.status,
    )


# --- users -----------------------------------------------------------------------------


@router.get("/users", response_model=UserList, responses=ERRORS)
async def list_users(
    admin: AdminUser,
    services: ServicesDep,
    paging: PagingDep,
    correlation_id: CorrelationId,
    role: RoleName | None = None,
    is_active: bool | None = None,
) -> UserList:
    users = [
        u
        for u in await services.users.list_users(admin)
        if (role is None or u.role is role) and (is_active is None or u.is_active is is_active)
    ]
    return UserList(
        correlation_id=correlation_id,
        items=paging.window(users),
        total=len(users),
        page=paging.page,
        page_size=paging.page_size,
    )


@router.post(
    "/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED, responses=ERRORS
)
async def create_user(
    body: CreateUserRequest,
    admin: AdminUser,
    services: ServicesDep,
    correlation_id: CorrelationId,
) -> UserResponse:
    view = await services.users.create_user(
        admin,
        username=body.username,
        display_name=body.display_name,
        password=body.password,
        role=body.role,
        region=body.region,
        correlation_id=correlation_id,
    )
    return _user(correlation_id, view)


@router.patch("/users/{user_id}", response_model=UserResponse, responses=ERRORS)
async def update_user(
    user_id: uuid.UUID,
    body: UpdateUserRequest,
    admin: AdminUser,
    services: ServicesDep,
    correlation_id: CorrelationId,
) -> UserResponse:
    sent = body.model_fields_set
    view: UserView | None = None
    if "role" in sent or "region" in sent:
        view = await services.users.assign_role(
            admin, user_id, body.role, body.region, correlation_id=correlation_id
        )
    if body.is_active is not None:
        view = await services.users.set_active(
            admin, user_id, body.is_active, correlation_id=correlation_id
        )
    if view is None:
        view = next((u for u in await services.users.list_users(admin) if u.id == user_id), None)
        if view is None:
            raise UserNotFound(str(user_id))
    return _user(correlation_id, view)


@router.post("/users/{user_id}/reset-password", response_model=UserResponse, responses=ERRORS)
async def reset_password(
    user_id: uuid.UUID,
    body: ResetPasswordRequest,
    admin: AdminUser,
    services: ServicesDep,
    correlation_id: CorrelationId,
) -> UserResponse:
    view = await services.users.reset_password(
        admin, user_id, body.new_password, correlation_id=correlation_id
    )
    return _user(correlation_id, view)


# --- verified queries and review (Step 20) -----------------------------------------------


@router.get("/metrics", response_model=MetricsResponse, responses=ERRORS)
async def metrics(
    _: AdminUser,
    services: ServicesDep,
    correlation_id: CorrelationId,
    date_from: Annotated[dt.date | None, Query(alias="from")] = None,
    date_to: Annotated[dt.date | None, Query(alias="to")] = None,
) -> MetricsResponse:
    """Operational health for a period of days (default: today in the monitoring zone)."""
    result = await services.metrics.metrics(date_from, date_to)
    return MetricsResponse(correlation_id=correlation_id, **result.model_dump())


@router.get("/alerts", response_model=AlertList, responses=ERRORS)
async def alerts(
    _: AdminUser,
    services: ServicesDep,
    correlation_id: CorrelationId,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
) -> AlertList:
    """The most recent alerts (newest first)."""
    return AlertList(correlation_id=correlation_id, items=await services.alerts.recent(limit))


@router.get("/review", response_model=ReviewList, responses=ERRORS)
async def review_list(
    _: AdminUser,
    services: ServicesDep,
    paging: PagingDep,
    correlation_id: CorrelationId,
    kind: Literal["not_helpful", "blocked", "failure"] | None = None,
) -> ReviewList:
    items, total = await services.library.review(
        page=paging.page, page_size=paging.page_size, kind=kind
    )
    return ReviewList(
        correlation_id=correlation_id,
        items=items,
        total=total,
        page=paging.page,
        page_size=paging.page_size,
    )


@router.get("/verified-queries", response_model=VerifiedQueryList, responses=ERRORS)
async def list_verified_queries(
    _: AdminUser,
    services: ServicesDep,
    paging: PagingDep,
    correlation_id: CorrelationId,
    is_active: bool | None = None,
) -> VerifiedQueryList:
    items, total = await services.library.list_queries(
        page=paging.page, page_size=paging.page_size, is_active=is_active
    )
    return VerifiedQueryList(
        correlation_id=correlation_id,
        items=items,
        total=total,
        page=paging.page,
        page_size=paging.page_size,
    )


@router.post(
    "/verified-queries",
    response_model=VerifiedQueryResponse,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
async def create_verified_query(
    body: VerifyRequest, admin: AdminUser, services: ServicesDep, correlation_id: CorrelationId
) -> VerifiedQueryResponse:
    item = await services.library.verify(
        admin, VerifyInput(**body.model_dump()), correlation_id=correlation_id
    )
    return VerifiedQueryResponse(correlation_id=correlation_id, **item.model_dump())


@router.patch(
    "/verified-queries/{query_id}", response_model=VerifiedQueryResponse, responses=ERRORS
)
async def update_verified_query(
    query_id: uuid.UUID,
    body: UpdateVerifiedRequest,
    admin: AdminUser,
    services: ServicesDep,
    correlation_id: CorrelationId,
) -> VerifiedQueryResponse:
    item = await services.library.set_active(
        admin, query_id, body.is_active, correlation_id=correlation_id
    )
    return VerifiedQueryResponse(correlation_id=correlation_id, **item.model_dump())


@router.post(
    "/feedback/{feedback_id}/eval-case",
    response_model=EvalCaseResponse,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
async def feedback_to_eval_case(
    feedback_id: int,
    body: EvalCaseRequest,
    admin: AdminUser,
    services: ServicesDep,
    correlation_id: CorrelationId,
) -> EvalCaseResponse:
    created = await services.library.to_eval_case(
        admin,
        feedback_id,
        case_type=body.case_type,
        expected_behaviour=body.expected_behaviour,
        expected_sql=body.expected_sql,
        correlation_id=correlation_id,
    )
    return EvalCaseResponse(correlation_id=correlation_id, **created.model_dump())


# --- evaluation (Step 22) ----------------------------------------------------------------


@router.post(
    "/eval/run",
    response_model=EvalRunStarted,
    status_code=status.HTTP_202_ACCEPTED,
    responses=ERRORS,
)
async def run_eval(
    body: EvalRunRequest, admin: AdminUser, services: ServicesDep, correlation_id: CorrelationId
) -> EvalRunStarted:
    """Start an evaluation run in the background (409 while another one is running)."""
    config = get_eval_config()
    if body.dataset != config.dataset:
        raise EvalInputError(
            f"unknown dataset {body.dataset}",
            user_message=f"Unknown dataset; use {config.dataset!r}.",
        )
    cases = load_cases()
    if body.dataset_version is not None and body.dataset_version != cases.version:
        raise EvalInputError(
            "dataset version", user_message=f"Only version {cases.version} exists."
        )
    options = EvalOptions(
        experiment_name=body.experiment_name,
        verified_examples_enabled=body.verified_examples_enabled,
        semantic_mode=body.semantic_mode,
        case_ids=body.subset,
        case_types=body.case_types,
    )
    run_id = await services.evaluation.start(admin, options)
    return EvalRunStarted(
        correlation_id=correlation_id, run_id=run_id, status=EvalRunStatus.RUNNING
    )


@router.get("/eval/runs", response_model=EvalRunList, responses=ERRORS)
async def list_eval_runs(
    _: AdminUser, services: ServicesDep, paging: PagingDep, correlation_id: CorrelationId
) -> EvalRunList:
    items, total = await services.evaluation.list_runs(page=paging.page, page_size=paging.page_size)
    return EvalRunList(
        correlation_id=correlation_id,
        items=items,
        total=total,
        page=paging.page,
        page_size=paging.page_size,
        targets=get_eval_config().targets.model_dump(),
    )


@router.get("/eval/runs/{run_id}", response_model=EvalRunDetailResponse, responses=ERRORS)
async def get_eval_run(
    run_id: uuid.UUID, _: AdminUser, services: ServicesDep, correlation_id: CorrelationId
) -> EvalRunDetailResponse:
    """One run with every case result, failing cases first."""
    detail = await services.evaluation.get_run(run_id)
    return EvalRunDetailResponse(correlation_id=correlation_id, **detail.model_dump())
