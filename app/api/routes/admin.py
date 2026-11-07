"""Admin routes: review, re-run, user management, and placeholders for later steps."""

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import CorrelationId, PagingDep, ServicesDep
from app.api.errors import NotImplementedYet, error_responses
from app.api.schemas import (
    BlockedItem,
    BlockedList,
    CreateUserRequest,
    ErrorItem,
    ErrorList,
    EvalRunList,
    EvalRunRequest,
    EvalRunStarted,
    MetricsResponse,
    RerunResponse,
    ResetPasswordRequest,
    UpdateUserRequest,
    UserList,
    UserResponse,
    VerifiedQueryList,
    VerifiedQueryResponse,
    VerifyRequest,
)
from app.auth.dependencies import AdminUser
from app.core.enums import ErrorStatus, RoleName
from app.services.users import UserNotFound, UserView

router = APIRouter(prefix="/admin", tags=["admin"])
ERRORS = error_responses(400, 401, 403, 404, 409, 500)
LATER = {**ERRORS, **error_responses(501)}


def _user(correlation_id: uuid.UUID, view: UserView) -> UserResponse:
    return UserResponse(correlation_id=correlation_id, **view.model_dump())


# --- review ----------------------------------------------------------------------------


@router.get("/blocked", response_model=BlockedList, responses=ERRORS)
async def blocked(
    _: AdminUser, services: ServicesDep, paging: PagingDep, correlation_id: CorrelationId,
    reason_code: str | None = None,
    date_from: Annotated[dt.date | None, Query(alias="from")] = None,
    date_to: Annotated[dt.date | None, Query(alias="to")] = None,
) -> BlockedList:  # fmt: skip
    result = await services.review.blocked(
        page=paging.page, page_size=paging.page_size, reason_code=reason_code,
        date_from=date_from, date_to=date_to,
    )  # fmt: skip
    return BlockedList(
        correlation_id=correlation_id, items=[BlockedItem(**r) for r in result.rows],
        total=result.total, page=paging.page, page_size=paging.page_size,
    )  # fmt: skip


@router.get("/errors", response_model=ErrorList, responses=ERRORS)
async def errors(
    _: AdminUser, services: ServicesDep, paging: PagingDep, correlation_id: CorrelationId,
    status: ErrorStatus | None = None, node_name: str | None = None,
) -> ErrorList:  # fmt: skip
    result = await services.review.errors(
        page=paging.page, page_size=paging.page_size, status=status, node_name=node_name
    )
    return ErrorList(
        correlation_id=correlation_id, items=[ErrorItem(**r) for r in result.rows],
        total=result.total, page=paging.page, page_size=paging.page_size,
    )  # fmt: skip


@router.post("/errors/{error_id}/rerun", response_model=RerunResponse,
             status_code=status.HTTP_202_ACCEPTED, responses=ERRORS)  # fmt: skip
async def rerun(
    error_id: int, admin: AdminUser, services: ServicesDep, correlation_id: CorrelationId
) -> RerunResponse:
    result = await services.review.rerun(admin, error_id, correlation_id)
    return RerunResponse(
        correlation_id=correlation_id, error_id=result.error_id,
        new_question_id=result.question_id, conversation_id=result.conversation_id,
        status=result.state.status,
    )  # fmt: skip


# --- users -----------------------------------------------------------------------------


@router.get("/users", response_model=UserList, responses=ERRORS)
async def list_users(
    admin: AdminUser, services: ServicesDep, paging: PagingDep, correlation_id: CorrelationId,
    role: RoleName | None = None, is_active: bool | None = None,
) -> UserList:  # fmt: skip
    users = [
        u for u in await services.users.list_users(admin)
        if (role is None or u.role is role) and (is_active is None or u.is_active is is_active)
    ]  # fmt: skip
    return UserList(
        correlation_id=correlation_id, items=paging.window(users), total=len(users),
        page=paging.page, page_size=paging.page_size,
    )  # fmt: skip


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED,
             responses=ERRORS)  # fmt: skip
async def create_user(
    body: CreateUserRequest, admin: AdminUser, services: ServicesDep,
    correlation_id: CorrelationId,
) -> UserResponse:  # fmt: skip
    view = await services.users.create_user(
        admin, username=body.username, display_name=body.display_name, password=body.password,
        role=body.role, region=body.region, correlation_id=correlation_id,
    )  # fmt: skip
    return _user(correlation_id, view)


@router.patch("/users/{user_id}", response_model=UserResponse, responses=ERRORS)
async def update_user(
    user_id: uuid.UUID, body: UpdateUserRequest, admin: AdminUser, services: ServicesDep,
    correlation_id: CorrelationId,
) -> UserResponse:  # fmt: skip
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
    user_id: uuid.UUID, body: ResetPasswordRequest, admin: AdminUser, services: ServicesDep,
    correlation_id: CorrelationId,
) -> UserResponse:  # fmt: skip
    view = await services.users.reset_password(
        admin, user_id, body.new_password, correlation_id=correlation_id
    )
    return _user(correlation_id, view)


# --- built in later steps (Steps 20-23): final models, 501 for now ---------------------


@router.get("/metrics", response_model=MetricsResponse, responses=LATER)
async def metrics(_: AdminUser) -> MetricsResponse:
    raise NotImplementedYet("metrics dashboard")


@router.get("/verified-queries", response_model=VerifiedQueryList, responses=LATER)
async def list_verified_queries(_: AdminUser) -> VerifiedQueryList:
    raise NotImplementedYet("verified queries")


@router.post("/verified-queries", response_model=VerifiedQueryResponse,
             status_code=status.HTTP_201_CREATED, responses=LATER)  # fmt: skip
async def create_verified_query(_body: VerifyRequest, _: AdminUser) -> VerifiedQueryResponse:
    raise NotImplementedYet("verified queries")


@router.post("/eval/run", response_model=EvalRunStarted, status_code=status.HTTP_202_ACCEPTED,
             responses=LATER)  # fmt: skip
async def run_eval(_body: EvalRunRequest, _: AdminUser) -> EvalRunStarted:
    raise NotImplementedYet("evaluation runs")


@router.get("/eval/runs", response_model=EvalRunList, responses=LATER)
async def list_eval_runs(_: AdminUser) -> EvalRunList:
    raise NotImplementedYet("evaluation runs")
