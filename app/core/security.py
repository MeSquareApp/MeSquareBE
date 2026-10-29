import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.core.config import settings

reusable_oauth2 = HTTPBearer()

class Auth0JWTValidator:
    def __init__(self):
        self.issuer = f"https://{settings.AUTH0_DOMAIN}/"
        self.jwks_url = f"{self.issuer}.well-known/jwks.json"
        self.jwks_client = jwt.PyJWKClient(self.jwks_url)

    def __call__(self, credentials: HTTPAuthorizationCredentials = Depends(reusable_oauth2)) -> dict:
        token = credentials.credentials
        try:
            signing_key = self.jwks_client.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=settings.AUTH0_ALGORITHMS,
                audience=settings.AUTH0_AUDIENCE,
                issuer=self.issuer,
            )
            return payload  # Contains 'sub' (Auth0 User ID), permissions, etc.
        except jwt.PyJWTError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid authentication credentials: {str(e)}",
                headers={"Authorization": "Bearer"},
            )

verify_auth0_token = Auth0JWTValidator()
