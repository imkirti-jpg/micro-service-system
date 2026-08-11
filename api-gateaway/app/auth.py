from fastapi import HTTPException, Request, status
from jose import JWTError, jwt

from app.config import settings


def require_auth(request: Request) -> dict:
    """Verifies the caller's JWT at the edge, before any request reaches an internal service."""
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme != "Bearer" or not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"error": "unauthorized", "message": "Missing bearer token"})
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm], issuer="user-service")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"error": "invalid_token"})
