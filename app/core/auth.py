from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, Header, HTTPException, status

from app.core.config import Settings, get_settings
from app.core.dependencies import get_postgres
from app.db.storage import PostgresRepository


@dataclass(frozen=True)
class RequestIdentity:
    tenant_id: str
    user_id: str


def get_current_identity(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    settings: Settings = Depends(get_settings),
    repository: PostgresRepository = Depends(get_postgres),
) -> RequestIdentity:
    if settings.jwt_key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Autenticação do chatbot não configurada.",
        )

    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de acesso obrigatório.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        claims = jwt.decode(
            token.strip(),
            settings.jwt_key.get_secret_value(),
            algorithms=["HS256", "HS384", "HS512"],
            options={"require": ["exp", "sub"]},
        )
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de acesso inválido ou expirado.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    email = claims.get("sub")
    if not isinstance(email, str) or not email.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token sem usuário válido.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    identity = repository.get_user_identity_by_email(email)
    if not identity:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário do token não encontrado.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = str(UUID(str(identity["user_id"])))
        tenant_id = str(UUID(str(identity["tenant_id"])))
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário sem empresa válida.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    return RequestIdentity(tenant_id=tenant_id, user_id=user_id)
