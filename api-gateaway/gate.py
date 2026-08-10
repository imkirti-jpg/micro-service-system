from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel, EmailStr
from pydantic_settings import BaseSettings, SettingsConfigDict
import httpx
from datetime import datetime, timedelta, timezone


class Settings(BaseSettings):
    jwt_secret: str
    user_service_url: str = "http://user-service:8001"
    jwt_algorithm: str = "HS256"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
app = FastAPI(title="API Gateway", version="1.0.0")
bearer = HTTPBearer()


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserCreate(BaseModel):
    name: str
    email: EmailStr


def require_token(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
) -> str:
    token = credentials.credentials
    try:
        jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return token


@app.get("/health")
async def health():
    return {"status": "ok", "service": "api-gateway"}


@app.post("/auth/login", response_model=TokenResponse)
async def login(payload: LoginRequest):
    # Assignment-level demo authentication.
    # Replace with a real identity provider in a production system.
    if payload.username != "admin" or payload.password != "admin":
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = jwt.encode(
        {
            "sub": payload.username,
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    return TokenResponse(access_token=token)


@app.post("/api/v1/users")
async def create_user(payload: UserCreate, token: str = Depends(require_token)):
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.post(
            f"{settings.user_service_url}/internal/v1/users",
            json=payload.model_dump(),
            headers={"Authorization": f"Bearer {token}"},
        )
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text)
    return response.json()


@app.get("/api/v1/users/{user_id}")
async def get_user(user_id: int, token: str = Depends(require_token)):
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(
            f"{settings.user_service_url}/internal/v1/users/{user_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text)
    return response.json()
