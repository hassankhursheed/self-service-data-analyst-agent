"""FastAPI dependencies: validate the bearer token on every protected call.

The API (Step 18) stores an ``AuthService`` on ``app.state.auth``. The resulting
``AuthenticatedUser`` (role and region from the database) is what the agent receives.
"""

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.models import AuthenticatedUser
from app.auth.service import AuthService
from app.auth.tokens import InvalidToken
from app.core.errors import AppError

_bearer = HTTPBearer(auto_error=False)


class AdminOnly(AppError):
    code = "ADMIN_ONLY"
    user_message = "This page is only available to administrators."


def auth_service(request: Request) -> AuthService:
    service: AuthService = request.app.state.auth
    return service


async def current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    service: Annotated[AuthService, Depends(auth_service)],
) -> AuthenticatedUser:
    try:
        if (
            credentials is None
            or credentials.scheme.lower() != "bearer"
            or not credentials.credentials
        ):
            raise InvalidToken("missing bearer token")
        return await service.authenticate(credentials.credentials)
    except InvalidToken as err:
        # Every refused token is audited with its correlation ID (Step 26, scenario 26).
        from app.api.deps import client_ip

        await service.record_rejected_token(
            err.code,
            request.url.path,
            correlation_id=getattr(request.state, "correlation_id", None),
            client_ip=client_ip(request),
        )
        raise


async def admin_user(
    user: Annotated[AuthenticatedUser, Depends(current_user)],
) -> AuthenticatedUser:
    if not user.is_admin:
        raise AdminOnly(f"{user.username} is not an admin")
    return user


CurrentUser = Annotated[AuthenticatedUser, Depends(current_user)]
AdminUser = Annotated[AuthenticatedUser, Depends(admin_user)]
