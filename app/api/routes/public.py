"""Public routes: login and health."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.deps import ClientIp, CorrelationId, ServicesDep
from app.api.errors import error_responses
from app.api.schemas import HealthResponse, LoginRequest, LoginResponse

router = APIRouter(tags=["public"])
ERRORS = error_responses(400, 401, 429, 500)


@router.post("/auth/login", response_model=LoginResponse, responses=ERRORS)
async def login(
    body: LoginRequest, services: ServicesDep, correlation_id: CorrelationId, ip: ClientIp
) -> LoginResponse:
    services.login_limiter.check(f"login:{ip or 'unknown'}")
    token = await services.auth.login(
        body.username, body.password, client_ip=ip, correlation_id=correlation_id
    )
    return LoginResponse(
        correlation_id=correlation_id,
        access_token=token.access_token,
        expires_in=token.expires_in,
        user=token.user,
    )


@router.get("/health", response_model=HealthResponse, responses={503: {"model": HealthResponse}})
async def health(services: ServicesDep, correlation_id: CorrelationId) -> JSONResponse:
    try:
        async with services.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        database_ok = True
    except Exception:  # any failure means the database is not usable
        database_ok = False
    body = HealthResponse(
        correlation_id=correlation_id,
        status="ok" if database_ok else "degraded",
        database="ok" if database_ok else "down",
        version=services.api.version,
    )
    return JSONResponse(
        status_code=200 if database_ok else 503, content=body.model_dump(mode="json")
    )
