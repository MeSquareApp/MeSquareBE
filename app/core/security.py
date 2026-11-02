import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.core.config import settings

bearer_scheme = HTTPBearer(auto_error=False)

class Auth0JWTValidator:
    def __init__(self):
        self.issuer = f"https://{settings.auth0_domain}/"
        self.jwks_url = f"{self.issuer}.well-known/jwks.json"
        self.jwks_client = jwt.PyJWKClient(self.jwks_url)

    def __call__(
        self,
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    ) -> dict[str, object]:
        if credentials is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = credentials.credentials
        try:
            signing_key = self.jwks_client.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=settings.auth0_algorithms,
                audience=settings.auth0_audience,
                issuer=self.issuer,
            )
            if not isinstance(payload.get("sub"), str) or not payload["sub"]:
                raise jwt.InvalidTokenError("Token subject is missing.")
            return payload
        except jwt.PyJWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials.",
                headers={"WWW-Authenticate": "Bearer"},
            )


verify_auth0_token = Auth0JWTValidator()
