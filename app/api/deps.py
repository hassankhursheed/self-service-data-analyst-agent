"""Shared route dependencies: the service container, correlation ID, paging, rate limits."""

import ipaddress
import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.agent.conversations import ConversationService
from app.api.ratelimit import SlidingWindowLimiter
from app.auth.service import AuthService
from app.core.config import ApiConfig
from app.services.cost_cap import DailyCostCap
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
    cost_cap: DailyCostCap
    question_limiter: SlidingWindowLimiter
    login_limiter: SlidingWindowLimiter


def services(request: Request) -> Services:
    container: Services = request.app.state.services
    return container


def correlation_id(request: Request) -> uuid.UUID:
    value: uuid.UUID = request.state.correlation_id
    return value


def forwarded_client_ip(header: str | None) -> str | None:
    """The address the nearest proxy (our UI server) put last in ``X-Forwarded-For``."""
    if not header:
        return None
    candidate = header.split(",")[-1].strip()
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def client_ip(request: Request) -> str | None:
    """The caller's address for login limits and the audit log.

    Behind the UI server every request comes from the UI's address, so with
    ``api.trust_forwarded_for`` (only where the API is not reachable from the internet)
    the address the UI forwards is used instead.
    """
    direct = request.client.host if request.client else None
    container: Services | None = getattr(request.app.state, "services", None)
    if container is not None and container.api.trust_forwarded_for:
        return forwarded_client_ip(request.headers.get("x-forwarded-for")) or direct
    return direct


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
