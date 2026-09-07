import hashlib
from functools import lru_cache
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from solution_copilot.application.access import Identity, resolve_identity
from solution_copilot.application.errors import AppError
from solution_copilot.config import get_settings
from solution_copilot.domain.models import User
from solution_copilot.infrastructure.database import get_session
from sqlalchemy import select
from sqlalchemy.orm import Session

SessionDep = Annotated[Session, Depends(get_session)]
bearer = HTTPBearer(auto_error=False)


@lru_cache
def jwks_client(url: str):
    return jwt.PyJWKClient(url, timeout=5)


def authenticate(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    if credentials is None:
        raise AppError(401, "UNAUTHORIZED", "请先登录。")
    settings = get_settings()
    token = credentials.credentials
    if settings.dev_auth_enabled:
        subject_filter = User.dev_token_hash == hashlib.sha256(token.encode()).hexdigest()
    else:
        if not all([settings.oidc_jwks_url, settings.oidc_issuer, settings.oidc_audience]):
            raise AppError(503, "AUTH_NOT_CONFIGURED", "身份服务尚未配置。")
        try:
            key = jwks_client(settings.oidc_jwks_url).get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                audience=settings.oidc_audience,
                issuer=settings.oidc_issuer,
                options={"require": ["exp", "sub", "iss", "aud"]},
            )
        except (jwt.PyJWTError, ValueError):
            raise AppError(401, "UNAUTHORIZED", "身份凭据无效或已过期。") from None
        subject_filter = User.external_subject == claims["sub"]
    user = session.scalar(select(User).where(subject_filter))
    if user is None:
        raise AppError(401, "UNAUTHORIZED", "身份凭据无效或未开户。")
    return user


UserDep = Annotated[User, Depends(authenticate)]


def current_identity(
    session: SessionDep, user: UserDep, x_organization_id: Annotated[UUID, Header()]
) -> Identity:
    return resolve_identity(session, user.id, x_organization_id)


IdentityDep = Annotated[Identity, Depends(current_identity)]
