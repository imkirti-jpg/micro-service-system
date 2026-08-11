import asyncio
import json
import ssl

import nats
from fastapi import FastAPI
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import String, Integer, Text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Settings(BaseSettings):
    database_url: str
    nats_url: str = "tls://nats:4222"
    nats_username: str
    nats_password: str
    nats_ca_file: str
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
engine = create_async_engine(settings.database_url)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer)
    recipient: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(50), default="processed")
    message: Mapped[str] = mapped_column(Text)


app = FastAPI(title="Notification Service", version="1.0.0")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "notification-service"}


async def consume():
    tls = ssl.create_default_context(cafile=settings.nats_ca_file)
    nc = await nats.connect(
        servers=[settings.nats_url],
        user=settings.nats_username,
        password=settings.nats_password,
        tls=tls,
    )
    js = nc.jetstream()

    try:
        await js.add_stream(name="USER_EVENTS", subjects=["users.created"])
    except Exception:
        pass

    async def handler(msg):
        event = json.loads(msg.data.decode())
        event_id = event["event_id"]
        data = event["data"]

        async with SessionLocal() as session:
            from sqlalchemy import select

            existing = await session.scalar(
                select(Notification).where(Notification.event_id == event_id)
            )
            if existing:
                await msg.ack()
                return

            notification = Notification(
                event_id=event_id,
                user_id=data["user_id"],
                recipient=data["email"],
                status="processed",
                message=f"Welcome {data['name']}!",
            )
            session.add(notification)
            await session.commit()

        print(
            f"[notification-service] processed user.created "
            f"event_id={event_id} recipient={data['email']}"
        )
        await msg.ack()

    sub = await js.subscribe(
        "users.created",
        durable="notification-service",
        manual_ack=True,
    )

    while True:
        msg = await sub.next_msg(timeout=30)
        await handler(msg)


async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    while True:
        try:
            await consume()
        except Exception as exc:
            print(f"[notification-service] consumer error: {exc}")
            await asyncio.sleep(3)


if __name__ == "__main__":
    asyncio.run(main())
