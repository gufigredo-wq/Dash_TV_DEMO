from dataclasses import dataclass
import os
from typing import Mapping, Optional


@dataclass(frozen=True)
class Usuario:
    email: str
    nome: str
    id: str
    modulos: frozenset[str]


def obter_usuario(headers: Mapping[str, str]) -> Optional[Usuario]:
    """Obtém o usuário autenticado a partir dos cabeçalhos injetados pelo gateway seguro.

    Retorna None se o cabeçalho de e-mail estiver ausente ou vazio.
    Fora do Labs (sem AUDIT_APP), LABS_DEV_USER_EMAIL define um usuário de
    desenvolvimento usado só quando o gateway não enviou o e-mail.
    """
    if not headers or not any(
        str(k).lower() == "x-forwarded-email" for k in headers
    ):
        return _usuario_desenvolvimento()

    # Normalizar cabeçalhos para minúsculo
    h_lower = {str(k).lower(): str(v) for k, v in headers.items()}

    email = h_lower.get("x-forwarded-email")
    if not email or not email.strip():
        return None

    email = email.strip()
    nome = h_lower.get("x-forwarded-name", "").strip() or email
    user_id = (
        h_lower.get("x-forwarded-user-id", "").strip()
        or h_lower.get("x-forwarded-sub", "").strip()
        or email
    )

    raw_modulos = h_lower.get("x-forwarded-modulos", "").strip()
    if raw_modulos:
        modulos = frozenset(
            m.strip() for m in raw_modulos.split(",") if m.strip()
        )
    else:
        modulos = frozenset()

    return Usuario(email=email, nome=nome, id=user_id, modulos=modulos)


def pode_fazer(usuario: Optional[Usuario], modulo: str) -> bool:
    """Verifica se o usuário possui permissão para executar a ação no módulo.

    '*' em modulos concede acesso total; usuário None nega qualquer ação.
    """
    if usuario is None:
        return False
    if "*" in usuario.modulos:
        return True
    return modulo in usuario.modulos


def _usuario_desenvolvimento() -> Optional[Usuario]:
    if os.environ.get("AUDIT_APP", "").strip():
        return None
    email = os.environ.get("LABS_DEV_USER_EMAIL", "").strip()
    if not email:
        return None
    raw = os.environ.get("LABS_DEV_MODULOS", "*")
    modulos = frozenset(m.strip() for m in raw.split(",") if m.strip())
    return Usuario(email=email, nome=email, id=email, modulos=modulos)
