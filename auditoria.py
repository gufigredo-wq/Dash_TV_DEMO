from datetime import datetime, timezone
import json
import os
import socket
from typing import Any, Mapping, Optional
import uuid

from .identidade import Usuario

REDACAO_PADRAO = [
    'senha',
    'password',
    'pass',
    'pwd',
    'senhahash',
    'senha_hash',
    'passwordhash',
    'password_hash',
    'hash',
    'token',
    'access_token',
    'refresh_token',
    'id_token',
    'accesstoken',
    'refreshtoken',
    'idtoken',
    'authorization',
    'auth',
    'cookie',
    'set-cookie',
    'secret',
    'client_secret',
    'apikey',
    'api_key',
    'x-api-key',
    'sso_jwt_secret',
    'baserow_password',
]

_REDACAO_SET = {k.lower() for k in REDACAO_PADRAO}
_RESULTADOS_VALIDOS = {'sucesso', 'falha', 'negado', 'erro'}


def _redigir(valor: Any, prof: int = 0) -> Any:
    if valor is None or prof > 8:
        return valor
    if isinstance(valor, list):
        return [_redigir(v, prof + 1) for v in valor]
    if isinstance(valor, Mapping):
        saida = {}
        for k, v in valor.items():
            k_str = str(k)
            if k_str.lower() in _REDACAO_SET:
                saida[k_str] = '[REDIGIDO]'
            else:
                saida[k_str] = _redigir(v, prof + 1)
        return saida
    return valor


def _normalizar_resultado(valor: Optional[str]) -> str:
    if not valor:
        return 'sucesso'
    v = str(valor).lower().strip()
    if v in _RESULTADOS_VALIDOS:
        return v
    if v in ('ok', 'concluido', 'solicitado', 'autorizado'):
        return 'sucesso'
    if v in ('error', 'falhou', 'rejeitado'):
        return 'falha'
    return 'sucesso'


class Auditoria:

    def __init__(self, app: str, journal_dir: str, ambiente: str):
        if not app or not app.strip():
            raise ValueError('app é obrigatório')
        if not journal_dir or not journal_dir.strip():
            raise ValueError('journal_dir é obrigatório')
        if not ambiente or not ambiente.strip():
            raise ValueError('ambiente é obrigatório')

        self.app = app.strip()
        self.journal_dir = journal_dir.strip()
        self.ambiente = ambiente.strip().lower()
        self._origem_host = socket.gethostname()

    @classmethod
    def do_ambiente(cls) -> 'Auditoria':
        """Cria o emissor a partir de AUDIT_APP, AUDIT_JOURNAL_DIR e LABS_AMBIENTE."""
        return cls(
            app=os.environ.get('AUDIT_APP', ''),
            journal_dir=os.environ.get('AUDIT_JOURNAL_DIR', '/var/audit'),
            ambiente=os.environ.get('LABS_AMBIENTE', 'labs'),
        )

    def registrar(
        self,
        acao: str,
        usuario: Optional[Usuario] = None,
        *,
        resultado: str = 'sucesso',
        nivel: str = 'critico',
        modulo: Optional[str] = None,
        recurso_tipo: Optional[str] = None,
        recurso_id: Optional[str] = None,
        recurso_rotulo: Optional[str] = None,
        dados_antes: Any = None,
        dados_depois: Any = None,
        erro_codigo: Optional[str] = None,
        ip: Optional[str] = None,
    ) -> Optional[str]:
        try:
            evento_id = str(uuid.uuid4())
            ocorrido_em = (
                datetime.now(timezone.utc)
                .isoformat()
                .replace('+00:00', 'Z')
            )

            dados_antes_redigido = (
                _redigir(dados_antes) if dados_antes is not None else None
            )
            dados_depois_redigido = (
                _redigir(dados_depois) if dados_depois is not None else None
            )

            if usuario:
                ator_tipo = 'usuario'
                ator_id = str(usuario.id) if usuario.id is not None else None
                ator_email = usuario.email
                ator_nome = usuario.nome
                ator_super_admin = '*' in usuario.modulos
            else:
                ator_tipo = 'anonimo'
                ator_id = None
                ator_email = None
                ator_nome = None
                ator_super_admin = None

            payload = {
                'evento_id': evento_id,
                'ocorrido_em': ocorrido_em,
                'ambiente': self.ambiente,
                'app': self.app,
                'modulo': modulo,
                'acao': acao,
                'resultado': _normalizar_resultado(resultado),
                'nivel': nivel,
                'http_status': None,
                'erro_codigo': (
                    str(erro_codigo)[:80] if erro_codigo else None
                ),
                'erro_detalhe': None,
                'ator_tipo': ator_tipo,
                'ator_id': ator_id,
                'ator_email': ator_email,
                'ator_nome': ator_nome,
                'ator_super_admin': ator_super_admin,
                'impersonado_por': None,
                'sessao_id': None,
                'requisicao_id': None,
                'fluxo_id': None,
                'causa_id': None,
                'recurso_tipo': (
                    str(recurso_tipo)[:60] if recurso_tipo else None
                ),
                'recurso_id': (
                    str(recurso_id)[:120] if recurso_id is not None else None
                ),
                'recurso_rotulo': (
                    str(recurso_rotulo)[:300] if recurso_rotulo else None
                ),
                'dados_antes': dados_antes_redigido,
                'dados_depois': dados_depois_redigido,
                'ip': ip,
                'user_agent': None,
                'origem_host': self._origem_host,
                'chave_idempotencia': None,
                'schema_versao': 1,
            }

            dia = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            target_dir = os.path.join(self.journal_dir, self.app)
            os.makedirs(target_dir, exist_ok=True)
            file_path = os.path.join(target_dir, f'{dia}.jsonl')

            linha = json.dumps(payload, ensure_ascii=False) + '\n'
            with open(file_path, 'a', encoding='utf-8') as f:
                f.write(linha)

            return evento_id
        except Exception:
            return None


def auditar(acao: str, usuario: Optional[Usuario] = None, **kwargs: Any) -> Optional[str]:
    """Registra um evento no journal do Labs; fora do Labs (sem AUDIT_APP) não faz nada."""
    if not os.environ.get('AUDIT_APP', '').strip():
        return None
    return Auditoria.do_ambiente().registrar(acao, usuario, **kwargs)
