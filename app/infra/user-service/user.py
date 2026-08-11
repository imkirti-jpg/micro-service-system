import json
import ssl
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import nats
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel, EmailStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import String, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Settings(BaseSettings):
    database_url: str
    jwt_secret: str
    nats_url: str = "tls://nats:4222"
    nats_username: str
    nats_password: str
    nats_ca_file: str
    jwt_algorithm: str = "HS256"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
engine = create_async_engine(settings.database_url)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
nc = None
js = None
bearer = HTTPBearer()


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)


class UserCreate(BaseModel):
    name: str
    email: EmailStr


def verify_token(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
):
    try:
        return jwt.decode(
            credentials.credentials,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")



async def publish_user_created(user: User):
    event = {
        "event_id": f"user-{user.id}-{int(datetime.now(timezone.utc).timestamp() * 1000)}",
        "event_type": "user.created",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "data": {
            "user_id": user.id,
            "name": user.name,
            "email": user.email,
        },
    }
    await js.publish("users.created", json.dumps(event).encode())


@asynccontextmanager
async def lifespan(app: FastAPI):
    global nc, js

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    tls = ssl.create_default_context(cafile=settings.nats_ca_file)
    nc = await nats.connect(
        servers=[settings.nats_url],
        user=settings.nats_username,
        password=settings.nats_password,
        tls=tls,
    )
    js = nc.jetstream()

    try:
        await js.add_stream(
            name="USER_EVENTS",
            subjects=["users.created"],
        )
    except Exception:
        pass

    yield

    await nc.drain()
    await engine.dispose()


app = FastAPI(title="User Service", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "user-service"}


@app.post("/internal/v1/users")
async def create_user(payload: UserCreate, _: dict = Depends(verify_token)):
    async with SessionLocal() as session:
        existing = await session.scalar(
            select(User).where(User.email == payload.email)
        )
        if existing:
            raise HTTPException(status_code=409, detail="Email already exists")

        user = User(name=payload.name, email=str(payload.email))
        session.add(user)
        await session.commit()
        await session.refresh(user)

        await publish_user_created(user)

        return {
            "id": user.id,
            "name": user.name,
            "email": user.email,
        }


@app.get("/internal/v1/users/{user_id}")
async def get_user(user_id: int, _: dict = Depends(verify_token)):
    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return {
            "id": user.id,
            "name": user.name,
            "email": user.email,
        }
