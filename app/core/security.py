import requests
from fastapi import HTTPException, status
from jose import JWTError, jwt

from app.core.config import settings

if getattr(settings, "COGNITO_ENDPOINT", None):
    JWKS_URL = (
        f"{settings.COGNITO_ENDPOINT}"
        f"/{settings.COGNITO_USER_POOL_ID}/.well-known/jwks.json"
    )
else:
    JWKS_URL = f"https://cognito-idp.{settings.COGNITO_REGION}.amazonaws.com/{settings.COGNITO_USER_POOL_ID}/.well-known/jwks.json"


def verify_cognito_token(token: str):
    try:
        jwks = requests.get(JWKS_URL).json()
        header = jwt.get_unverified_header(token)
        key = next((k for k in jwks["keys"] if k["kid"] == header["kid"]), None)
        if not key:
            raise HTTPException(status_code=401, detail="Invalid token header")

        payload = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=settings.COGNITO_CLIENT_ID,
        )
        return payload

    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
        )
