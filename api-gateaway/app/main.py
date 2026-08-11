import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.auth import require_auth
from app.config import settings
from app.proxy import close_client, proxy_request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("api-gateway")

limiter = Limiter(key_func=get_remote_address, default_limits=[settings.rate_limit])


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("api-gateway startup complete")
    yield
    await close_client()
    logger.info("api-gateway shutdown complete")


app = FastAPI(title="API Gateway", version="1.0.0", lifespan=lifespan)
# The limiter must be attached to the app before any routes are registered, so that the decorator can find it.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(CORSMiddleware, allow_origins=[settings.cors_origin], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "api-gateway"}


@app.post("/api/users/register")
@limiter.limit(settings.rate_limit)
async def register(request: Request):
    return await proxy_request(request, target_base=settings.user_service_url, target_path="/users/register")


@app.post("/api/users/login")
@limiter.limit(settings.rate_limit)
async def login(request: Request):
    return await proxy_request(request, target_base=settings.user_service_url, target_path="/users/login")


# auth routes

@app.get("/api/users/me")
@limiter.limit(settings.rate_limit)
async def get_me(request: Request, claims: dict = Depends(require_auth)):
    return await proxy_request(request, target_base=settings.user_service_url, target_path="/users/me", user_id=claims["sub"])


@app.get("/api/users/{user_id}")
@limiter.limit(settings.rate_limit)
async def get_user(request: Request, user_id: str, claims: dict = Depends(require_auth)):
    return await proxy_request(request, target_base=settings.user_service_url, target_path=f"/users/{user_id}", user_id=claims["sub"])


@app.get("/api/notifications/me")
@limiter.limit(settings.rate_limit)
async def get_my_notifications(request: Request, claims: dict = Depends(require_auth)):
    # Path is built from the verified JWT subject, not any client-supplied
    # id — a caller cannot read another user's notifications by guessing one.
    return await proxy_request(
        request,
        target_base=settings.notification_service_url,
        target_path=f"/notifications/{claims['sub']}",
        user_id=claims["sub"],
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"error": "internal_error"})
