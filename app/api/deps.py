"""Shared route dependencies: the service container, correlation ID, paging, rate limits."""

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.agent.conversations import ConversationService
from app.api.ratelimit import SlidingWindowLimiter
from app.auth.service import AuthService
from app.core.config import ApiConfig
from app.services.evaluation import EvaluationService
from app.services.feedback import FeedbackService
from app.services.metrics import MetricsService
from app.services.review import ReviewService
from app.services.users import UserAdminService
from app.services.verified_library import VerifiedLibraryService


@dataclass(frozen=True)
class Services:
    """Everything the routes need, built once in the app lifespan."""

    api: ApiConfig
    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]
    auth: AuthService
    conversations: ConversationService
    users: UserAdminService
    feedback: FeedbackService
    review: ReviewService
    library: VerifiedLibraryService
    metrics: MetricsService
    evaluation: EvaluationService
    question_limiter: SlidingWindowLimiter
    login_limiter: SlidingWindowLimiter


def services(request: Request) -> Services:
    container: Services = request.app.state.services
    return container


def correlation_id(request: Request) -> uuid.UUID:
    value: uuid.UUID = request.state.correlation_id
    return value


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@dataclass(frozen=True)
class Paging:
    page: int
    page_size: int

    def window[T](self, items: list[T]) -> list[T]:
        start = (self.page - 1) * self.page_size
        return items[start : start + self.page_size]


def paging(
    request: Request,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int | None, Query(ge=1)] = None,
) -> Paging:
    config = services(request).api
    size = min(page_size or config.default_page_size, config.max_page_size)
    return Paging(page=page, page_size=size)


ServicesDep = Annotated[Services, Depends(services)]
CorrelationId = Annotated[uuid.UUID, Depends(correlation_id)]
ClientIp = Annotated[str | None, Depends(client_ip)]
PagingDep = Annotated[Paging, Depends(paging)]
