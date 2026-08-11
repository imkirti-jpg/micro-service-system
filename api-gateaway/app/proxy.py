import logging

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse, Response

from app.config import settings

logger = logging.getLogger("api-gateway.proxy")

# Reused across requests — a fresh AsyncClient per-request would drop
# connection pooling for no benefit.
_client = httpx.AsyncClient(timeout=10.0)

# Headers that must not be forwarded verbatim between hops.
_HOP_BY_HOP = {"connection", "keep-alive", "transfer-encoding", "upgrade", "content-length", "host"}


async def proxy_request(
    request: Request,
    *,
    target_base: str,
    target_path: str,
    user_id: str | None = None,
) -> Response:
    """Forward `request` to `{target_base}{target_path}`, attaching the
    shared internal-service token (and the verified user id, if any) so
    the upstream service can trust this call came through the gateway.
    """
    url = f"{target_base}{target_path}"

    forward_headers = {k: v for k, v in request.headers.items() if k.lower() not in _HOP_BY_HOP}
    forward_headers["x-internal-token"] = settings.internal_service_token
    if user_id:
        forward_headers["x-user-id"] = user_id

    body = await request.body()

    try:
        upstream = await _client.request(
            request.method,
            url,
            content=body,
            headers=forward_headers,
            params=request.query_params,
        )
    except httpx.RequestError as exc:
        logger.error("upstream request failed url=%s error=%s", url, exc)
        return JSONResponse(status_code=502, content={"error": "bad_gateway", "message": "Upstream service unavailable"})

    response_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in _HOP_BY_HOP}
    return Response(content=upstream.content, status_code=upstream.status_code, headers=response_headers, media_type=upstream.headers.get("content-type"))


async def close_client() -> None:
    await _client.aclose()
