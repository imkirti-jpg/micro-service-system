from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    port: int = 4000
    environment: str = "development"

    user_service_url: str = "http://localhost:4001"
    notification_service_url: str = "http://localhost:4002"

    jwt_secret: str
    jwt_algorithm: str = "HS256"

    internal_service_token: str

    rate_limit: str = "100/minute"
    cors_origin: str = "*"


settings = Settings()
