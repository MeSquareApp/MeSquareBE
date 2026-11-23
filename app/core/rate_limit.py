"""In-memory rate limiting for the chat endpoints.

NOTE: in-memory storage means limits are per-process only. If the API is ever
run with multiple uvicorn workers or replicas, swap the storage for a shared
store (e.g. Redis); the slowapi Limiter API supports that without changing the
routes.
"""

import hashlib

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def _bearer_token_key(request: Request) -> str:
    """Key rate limits on the bearer token (effectively the Auth0 subject).

    The default get_remote_address key would be wrong for this API: behind
    the Supabase/Docker reverse proxies every user would share a single IP
    bucket. Hashing the Authorization header gives each user their own bucket
    without keeping raw tokens in memory.
    """
    authorization = request.headers.get("Authorization")
    if authorization:
        return hashlib.sha256(authorization.encode("utf-8")).hexdigest()
    return get_remote_address(request)


limiter = Limiter(key_func=_bearer_token_key)