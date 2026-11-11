import glob
import json
import os
import shutil
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# tema fixo mesmo sem o .streamlit/config.toml (a pasta oculta às vezes não sobe pelo site do GitHub)
for _k, _v in {"theme.base": "light", "theme.primaryColor": "#2a78d6", "theme.backgroundColor": "#f2f4f9",
               "theme.secondaryBackgroundColor": "#ffffff", "theme.textColor": "#1f1f1e", "client.toolbarMode": "minimal"}.items():
    try:
        if st.get_option(_k) != _v:
            st._config.set_option(_k, _v)
    except Exception:
        pass

os.chdir(os.path.dirname(os.path.abspath(__file__)))
import tv  # noqa: E402
import diario  # noqa: E402
import chat  # noqa: E402  (assistente do painel: fase 1, respostas prontas)
import banco  # noqa: E402  (banco de dados da empresa, opcional: sem conexão configurada, lê os arquivos de dados/)


# ============================================================ modo de demonstração
def _modo_demo():
    """Demonstração com dados fictícios quando: Secrets tem modo = "demo", a variável PAINEL_MODO=demo está definida,
    ou existe o arquivo MODO_DEMO na pasta do app. O mesmo código serve ao painel real e à demonstração."""
    try:
        if str(st.secrets.get("modo", "")).lower() == "demo":
            return True
    except Exception:
        pass
    return os.environ.get("PAINEL_MODO", "").lower() == "demo" or os.path.exists("MODO_DEMO")


MODO_DEMO = _modo_demo()
if MODO_DEMO:
    # os dados fictícios são gerados na hora numa pasta própria (fora do Git) e o painel passa a trabalhar nela:
    # nada de dado real é lido, nada é gravado no banco nem no GitHub
    _pasta_demo = os.path.join(os.getcwd(), "demo_runtime")
    if not os.path.exists(os.path.join(_pasta_demo, "dados", "rodadas_diarias")):
        import demo_dados
        demo_dados.gera(_pasta_demo)
    os.chdir(_pasta_demo)


def _banco_ativo():
    """Banco de dados em uso: conexão configurada e fora do modo demonstração."""
    return banco.ativo() and not MODO_DEMO


# ============================================================ login corporativo, permissão e auditoria (biblioteca labs_streamlit da TI)
from labs_streamlit import Usuario, auditar, obter_usuario, pode_fazer  # noqa: E402

# permissão que libera as gravações, como vem no cabeçalho X-Forwarded-Modulos do gateway (padrão do Labs: "atualizar");
# quem não a tem só consulta
MODULO_PERMISSAO = "atualizar"


# só na demonstração: perfis simulados para testar o login e as permissões sem o gateway do Labs
PERFIS_DEMO = {
    "Pode atualizar": Usuario(email="ana.pesquisa@redebahia.com.br", nome="Ana Pesquisa (simulação)", id="demo-1",
                              modulos=frozenset({"acesso", "atualizar"})),
    "Só consulta": Usuario(email="joao.jornalismo@redebahia.com.br", nome="João Jornalismo (simulação)", id="demo-2",
                           modulos=frozenset({"acesso"})),
    "Sem login": None,
}


def usuario_atual():
    if MODO_DEMO:
        return PERFIS_DEMO.get(st.session_state.get("perfil_demo") or "Pode atualizar")
    """Usuário autenticado pelo gateway corporativo (cabeçalhos X-Forwarded-*). Fora do Labs, LABS_DEV_USER_EMAIL."""
    try:
        cab = dict(st.context.headers)
    except Exception:
        cab = {}
    u = obter_usuario(cab)
    if u is not None:          # cabeçalhos HTTP chegam como Latin-1: "JoÃ£o" (UTF-8 lido errado) volta a ser "João"
        import dataclasses
        u = dataclasses.replace(u, nome=_texto_utf8(u.nome), email=_texto_utf8(u.email))
    return u


def _texto_utf8(t):
    try:
        return t.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError, AttributeError):
        return t


def pode_gravar():
    """Só grava quem tem a permissão "atualizar" (ou '*'). Na demonstração, vale o perfil simulado escolhido na tela."""
    return pode_fazer(usuario_atual(), MODULO_PERMISSAO)


def registra(acao, resultado="sucesso", **kw):
    """Registra a gravação no journal de auditoria do Labs (fora do Labs, sem AUDIT_APP, não faz nada)."""
    if MODO_DEMO:
        return None
    try:
        return auditar(acao, usuario_atual(), resultado=resultado, modulo=MODULO_PERMISSAO, **kw)
    except Exception:
        return None


def _sem_permissao(acao):
    registra(acao, resultado="negado", recurso_tipo="painel", erro_codigo="sem_permissao_atualizar")
    st.session_state["msg_erro"] = "Seu perfil permite apenas consulta."

_PROFUNDIDADE = {"n": 0}


def protegido(acao, recurso_tipo, detalhe=None):
    """Envolve uma função que grava: confere a permissão antes e registra a gravação na auditoria depois
    (uma vez só, mesmo quando uma gravação chama outra). `detalhe(*a, **k)` pode devolver outra ação/recurso
    conforme o que está sendo gravado (ex.: rodada.upload com o nome do arquivo)."""
    def deco(func):
        def envolta(*a, **k):
            info = dict(acao=acao, recurso_tipo=recurso_tipo, recurso_id=None, recurso_rotulo=None)
            if detalhe:
                try:
                    info.update(detalhe(*a, **k) or {})
                except Exception:
                    pass
            if _PROFUNDIDADE["n"] == 0 and not pode_gravar():
                _sem_permissao(info["acao"])
                return None
            _PROFUNDIDADE["n"] += 1
            try:
                saida = func(*a, **k)
            except Exception as ex:
                if _PROFUNDIDADE["n"] == 1:
                    registra(info["acao"], resultado="erro", recurso_tipo=info["recurso_tipo"], recurso_id=info["recurso_id"],
                             erro_codigo=ex.__class__.__name__)
                raise
            finally:
                _PROFUNDIDADE["n"] -= 1
            if _PROFUNDIDADE["n"] == 0:
                rot = info["recurso_rotulo"] or next((str(x) for x in list(a) + list(k.values()) if isinstance(x, str)), None)
                registra(info["acao"], recurso_tipo=info["recurso_tipo"], recurso_id=info["recurso_id"], recurso_rotulo=rot)
            return saida
        envolta.__name__ = func.__name__
        envolta.__doc__ = func.__doc__
        return envolta
    return deco

st.set_page_config(page_title="Painel de Audiência · TV", page_icon="📺", layout="wide", initial_sidebar_state="collapsed")

# ============================================================ identidade visual (a mesma do painel de rádio)
# modo claro / escuro: botão do cabeçalho (o link guarda ?tema=escuro e o navegador lembra a escolha)
if "tema_escuro" not in st.session_state:
    st.session_state["tema_escuro"] = st.query_params.get("tema") == "escuro"
ESCURO = bool(st.session_state["tema_escuro"])


def _troca_tema():
    novo = not st.session_state.get("tema_escuro", False)
    st.session_state["tema_escuro"] = novo
    st.query_params["tema"] = "escuro" if novo else "claro"


AZUL, LARANJA = "#2a78d6", "#eb6834"
if ESCURO:
    FUNDO, CARTAO, BORDA, BORDA_IN, CAMPO, LINHA, REALCE = "#0b1120", "#131c31", "#22304d", "#2b3a5c", "#18223a", "#1c2740", "#1a2a4a"
    TOPO, AVISO_BG, AVISO_BD = "#001564", "#2e2610", "#5c4a1a"
    SOBE, DESCE = "#4cd08a", "#ff7a6b"
    TINTA, TINTA2, CINZA, CINZA_CLARO, GRADE, EIXO = "#e8edf7", "#aab6cf", "#7f8aa3", "#3a4664", "#1f2a42", "#2e3b58"
    SEQ = [[0, "#142038"], [.15, "#1b3563"], [.35, "#23508f"], [.55, "#2f6fc0"], [.75, "#5a98e6"], [1, "#a9cdf7"]]
else:
    FUNDO, CARTAO, BORDA, BORDA_IN, CAMPO, LINHA, REALCE = "#f2f4f9", "#ffffff", "#e3e7f0", "#d6d4d1", "#fafaf9", "#f0efec", "#f7f9fd"
    TOPO, AVISO_BG, AVISO_BD = "#001564", "#fff8e6", "#f3dca0"
    SOBE, DESCE = "#0a7a0a", "#b42318"
    TINTA, TINTA2, CINZA, CINZA_CLARO, GRADE, EIXO = "#1f1f1e", "#52514e", "#8a8984", "#c9c8c3", "#ecebe8", "#d6d4d1"
    SEQ = [[0, "#eef5fd"], [.15, "#cde2fb"], [.35, "#86b6ef"], [.55, "#3987e5"], [.75, "#1c5cab"], [1, "#0d366b"]]
SOMBRA, SOMBRA2 = (".35", ".5") if ESCURO else (".06", ".10")
FONTE_TXT = "Inter, Segoe UI, Helvetica Neue, Arial, sans-serif"
# semáforo da meta 100% (mesmas cores da apresentação)
COR_SEM = {"Provável": "#2e7d32", "Indefinido": "#f5a623", "Improvável": "#c62828", "–": CINZA}
COR_SEM_CLARO = ({"Provável": "#173a2a", "Indefinido": "#3d3214", "Improvável": "#45201f", "–": "#1c2740"} if ESCURO else
                 {"Provável": "#d9f2e6", "Indefinido": "#fdf0cc", "Improvável": "#fbdcdc", "–": "#f0efec"})
COR_MET = {"Audiência": AZUL, "Share": LARANJA}
COR_PROG = {"6h às 24h": "#1f3a68", "7h às 24h": "#5b7fc4", "Jornal da Manhã": "#2a78d6", "Bahia Meio Dia": "#eb6834", "Globo Esporte": "#1baf7a",
            "BATV": "#7030a0", "Bom Dia Sábado": "#eda100", "Conexão Bahia": "#e87ba4", "Panela de Bairro": "#c0504d",
            "Mosaico Baiano": "#008080", "Bahia Rural": "#7b4a12"}
if ESCURO:      # tons escuros demais para o fundo escuro: mesma família, mais claros
    COR_PROG.update({"6h às 24h": "#7b9ad8", "7h às 24h": "#9fb7e6", "BATV": "#9b5fd0", "Bahia Rural": "#c48a4a",
                     "Mosaico Baiano": "#2bb3b3"})
def _vivo(hexcor):
    """Versão mais viva da cor para o fundo escuro: mais clara (luminosidade ≥ 58%) e mais saturada, sem virar neon."""
    import colorsys
    r, g, b = [int(hexcor[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    l = min(max(l, .58), .72) if not (.42 <= h <= .53) else min(max(l, .46), .6)   # verde-água/ciano: menos claro
    s = max(s, min(.88, s * 1.2 + .05)) if s > .08 else s
    return "#%02x%02x%02x" % tuple(round(x * 255) for x in colorsys.hls_to_rgb(h, l, s))


if ESCURO:      # no fundo escuro, todas as séries ficam mais vivas
    COR_PROG = {p_: _vivo(c) for p_, c in COR_PROG.items()}
    AZUL, LARANJA = _vivo(AZUL), _vivo(LARANJA)
    COR_MET = {"Audiência": AZUL, "Share": LARANJA}
MESES = tv.MESES

st.markdown(f"""<style>
html, body, [class*="css"], .stApp {{font-family:{FONTE_TXT};}}
.stApp {{background:{FUNDO};}}
header[data-testid="stHeader"] {{background:transparent; height:0;}}
.block-container {{padding:0 1.6rem 2rem; max-width:1500px;}}
[data-testid="stSidebar"], [data-testid="collapsedControl"] {{display:none;}}
.bi-top {{background:{TOPO}; color:#fff; margin:0 -1.6rem 0; padding:14px 1.6rem 12px; display:flex;
          align-items:center; justify-content:space-between; border-bottom:3px solid {AZUL};}}
.bi-top h1 {{font-size:1.15rem; font-weight:600; margin:0; padding:0; color:#fff; letter-spacing:.2px;}}
.bi-top .sub {{font-size:.78rem; color:#c9d3e6; margin-top:2px;}}
[data-testid="stElementContainer"]:has(style), [data-testid="stElementContainer"]:has(iframe[height="1"]),
[data-testid="stElementContainer"]:has(iframe[data-testid="stIFrame"]) {{display:none;}}
.bi-top .meta {{font-size:.74rem; color:#c9d3e6; text-align:right; line-height:1.5;}}
.bi-top .meta b {{color:#fff; font-weight:600;}}
.stTabs [data-baseweb="tab-list"] {{gap:0; background:{CARTAO}; margin:0 -1.6rem 14px; padding:0 1.6rem; border-bottom:1px solid {BORDA};}}
.stTabs [data-baseweb="tab"] {{height:42px; padding:0 18px; font-size:.86rem; color:{TINTA2}; border-radius:0;}}
.stTabs [aria-selected="true"] {{color:{TINTA}; font-weight:600;}}
.stTabs [data-baseweb="tab-highlight"] {{background:{AZUL}; height:3px;}}
.stTabs [data-baseweb="tab-border"] {{display:none;}}
[class*="st-key-card"] {{background:{CARTAO}; border:1px solid {BORDA} !important; border-radius:4px !important;
    box-shadow:0 1px 2px rgba(0,0,0,.06); transition:box-shadow .15s; padding:12px 14px 6px !important;}}
[class*="st-key-card"]:hover {{box-shadow:0 4px 12px rgba(0,0,0,.10);}}
[data-testid="stToolbar"], [data-testid="stDecoration"] {{display:none !important;}}
.vt {{font-size:.88rem; font-weight:600; color:{TINTA}; margin:0 0 1px;}}
.vs {{font-size:.74rem; color:{CINZA}; margin:0 0 4px;}}
[data-testid="stWidgetLabel"] p {{font-size:.74rem !important; font-weight:600; color:{TINTA2}; text-transform:uppercase; letter-spacing:.5px;}}
.kpis {{display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:10px; margin:2px 0 12px;}}
.kpi {{background:{CARTAO}; border:1px solid {BORDA}; border-radius:4px; padding:10px 14px 9px; border-top:3px solid var(--c);
       box-shadow:0 1px 2px rgba(0,0,0,.06);}}
.kpi .t {{font-size:.7rem; text-transform:uppercase; letter-spacing:.5px; color:{TINTA2}; font-weight:600; line-height:1.35;}}
.kpi .v {{font-size:1.65rem; font-weight:600; color:{TINTA}; line-height:1.25; margin-top:2px; font-variant-numeric:tabular-nums;}}
.kpi .d {{font-size:.74rem; color:{CINZA}; line-height:1.4;}}
.kpi .up {{color:{SOBE}; font-weight:600;}} .kpi .down {{color:{DESCE}; font-weight:600;}}
.painel {{display:grid; grid-template-columns:repeat(auto-fill, minmax(250px, 1fr)); gap:10px;}}
.pg {{background:#f4f6fa; border-radius:6px; padding:9px 10px 10px;}}
.pg .n {{font-size:.82rem; font-weight:600; color:{TINTA}; margin:0 0 6px;}}
.pg .n span {{font-weight:400; color:{CINZA}; font-size:.72rem;}}
.pg .par {{display:grid; grid-template-columns:1fr 1fr; gap:6px;}}
.pg .c {{border-radius:5px; color:#fff; text-align:center; padding:6px 4px 6px;}}
.pg .c .m {{font-size:.7rem; opacity:.9;}} .pg .c .p {{font-size:1.25rem; font-weight:600; line-height:1.2;}}
.pg .c .x {{font-size:.68rem; opacity:.92;}}
.rk {{width:100%; border-collapse:collapse; font-size:.8rem; font-variant-numeric:tabular-nums;}}
.rk th {{text-align:left; font-size:.68rem; text-transform:uppercase; letter-spacing:.5px; color:{TINTA2};
         font-weight:600; padding:4px 6px; border-bottom:1px solid {BORDA}; vertical-align:bottom;}}
.rk td {{padding:6px 6px; border-bottom:1px solid {LINHA}; color:{TINTA}; white-space:nowrap;}}
.rk td.n, .rk th.n {{text-align:right;}} .rk tr:hover td {{background:{REALCE};}}
.rk td.s {{font-weight:600; text-align:right;}}
.xf {{font-size:.78rem; color:{TINTA2}; background:{CARTAO}; border:1px dashed {AZUL}; border-radius:4px; padding:6px 10px; margin-bottom:10px;}}
.xf b {{color:{AZUL};}}
.aviso {{font-size:.8rem; color:{TINTA2}; background:{AVISO_BG}; border:1px solid {AVISO_BD}; border-radius:4px; padding:7px 11px; margin-bottom:10px;}}
.leitura {{font-size:.8rem; color:{TINTA2}; background:#f4f6fa; border-left:3px solid {TOPO}; border-radius:4px; padding:8px 12px; margin:4px 0 10px;}}
.leitura b {{color:{TINTA};}}
.rodape {{font-size:.72rem; color:{CINZA}; margin-top:6px; line-height:1.5;}}
[data-testid="stMarkdownContainer"] {{margin-bottom:0 !important;}}
[data-testid="stMarkdownContainer"] > p:last-child {{margin-bottom:0 !important;}}
.vs {{line-height:1.45;}}
.st-key-notas [data-testid="stExpander"] details {{border:0; background:transparent;}}
.st-key-notas [data-testid="stExpander"] summary {{padding:4px 0; font-size:.74rem; color:{CINZA};}}
.st-key-notas [data-testid="stExpander"] summary p {{font-size:.74rem; color:{CINZA};}}
.st-key-notas [data-testid="stExpanderDetails"] {{font-size:.82rem; color:{TINTA2};}}
/* ---------- aba de projeções ---------- */
@property --pv {{ syntax:'<number>'; inherits:false; initial-value:0; }}
@keyframes enche {{ from {{ --pv:0; }} }}
@keyframes barra {{ from {{ width:0; }} }}
.secao {{display:flex; align-items:center; gap:12px; margin:18px 0 10px; animation:subir .5s cubic-bezier(.2,.7,.2,1) backwards;}}
.secao .num {{width:30px; height:30px; border-radius:9px; display:grid; place-items:center; font-weight:700; font-size:.9rem;
    color:#fff; background:linear-gradient(135deg,#2a78d6,#7b5cff); box-shadow:0 6px 16px rgba(42,120,214,.30); flex:none;}}
.secao .st {{font-size:1.02rem; font-weight:700; color:{TINTA}; letter-spacing:.1px;}}
.secao .ss {{font-size:.76rem; color:{CINZA};}}
.secao .linha {{flex:1; height:1px; background:linear-gradient(90deg, rgba(42,120,214,.45), transparent); margin-left:6px;}}
.hero {{display:grid; grid-template-columns:repeat(auto-fit, minmax(330px, 1fr)); gap:12px; margin:2px 0 14px;}}
.gcard {{display:flex; gap:18px; align-items:center; background:{CARTAO}; border:1px solid {BORDA}; border-radius:16px; padding:16px 18px;
    box-shadow:0 1px 2px rgba(16,24,64,.05), 0 10px 26px rgba(16,24,64,.07); position:relative; overflow:hidden;
    animation:subir .55s cubic-bezier(.2,.7,.2,1) backwards; transition:transform .25s, box-shadow .25s;}}
.gcard:hover {{transform:translateY(-3px); box-shadow:0 4px 10px rgba(16,24,64,.08), 0 18px 36px rgba(16,24,64,.12);}}
.gcard::before {{content:""; position:absolute; inset:0 auto 0 0; width:4px; background:var(--c);}}
.anel {{position:relative; --pv:var(--p); width:118px; height:118px; border-radius:50%; flex:none; display:grid; place-items:center;
    background:conic-gradient(var(--c) calc(var(--pv) * 1%), {LINHA} 0); animation:enche 1.4s cubic-bezier(.2,.8,.2,1) backwards;
    box-shadow:0 0 0 6px color-mix(in srgb, var(--c) 10%, transparent);}}
[class*="st-key-ficha_"], [class*="st-key-diario_"] {{animation:subir .5s cubic-bezier(.2,.7,.2,1) backwards;}}
.anel {{transition:box-shadow .4s;}}
.anel::after {{content:""; position:absolute; inset:-6px; border-radius:50%; pointer-events:none;
    background:conic-gradient(from 0deg, transparent 0 82%, color-mix(in srgb, var(--c) 55%, transparent) 92%, transparent 100%);
    animation:gira 1.4s cubic-bezier(.2,.8,.2,1) both; opacity:0;}}
@keyframes gira {{ 0% {{transform:rotate(-90deg); opacity:.9;}} 85% {{opacity:.6;}} 100% {{transform:rotate(270deg); opacity:0;}} }}
.anel .meio {{width:90px; height:90px; border-radius:50%; background:{CARTAO}; display:grid; place-items:center; text-align:center;}}
.anel .gv {{font-size:1.35rem; font-weight:800; color:{TINTA}; line-height:1; font-variant-numeric:tabular-nums;}}
.anel .gl {{font-size:.6rem; color:{CINZA}; margin-top:3px; line-height:1.2; text-transform:uppercase; letter-spacing:.4px;}}
.gtxt {{font-size:.78rem; color:{TINTA2}; line-height:1.55; min-width:0;}}
.gtxt .gk {{font-size:.72rem; font-weight:700; text-transform:uppercase; letter-spacing:.5px; color:{TINTA2};}}
.gtxt .gf {{font-size:1.05rem; color:{TINTA}; margin:2px 0;}}
.gtxt .gf b {{font-size:1.35rem;}}
.chip {{display:inline-block; padding:2px 10px; border-radius:999px; font-size:.7rem; font-weight:700; color:#fff; background:var(--c);
    margin-right:6px;}}
.resumo .seg {{display:flex; height:14px; border-radius:999px; overflow:hidden; margin:10px 0 12px; background:{LINHA};}}
.resumo .seg i {{display:block; height:100%; animation:barra 1.1s cubic-bezier(.2,.8,.2,1) backwards;}}
.resumo .gnum {{display:flex; gap:16px; align-items:baseline; flex-wrap:wrap;}}
.resumo .gnum div {{font-size:.74rem; color:{TINTA2};}}
.resumo .gnum b {{font-size:1.6rem; font-weight:800; margin-right:4px; font-variant-numeric:tabular-nums;}}
.resumo .lst {{font-size:.74rem; color:{TINTA2}; line-height:1.55; margin-top:4px;}}
.resumo .lst span {{font-weight:700;}}
.pg .c .bar {{height:5px; border-radius:999px; background:rgba(255,255,255,.28); margin:5px 8px 3px; overflow:hidden; position:relative;}}
.pg .c .bar::after {{content:""; position:absolute; top:-1px; bottom:-1px; left:86.96%; width:2px; background:rgba(0,0,0,.35);}}
.pg .c .bar i {{display:block; height:100%; background:#fff; border-radius:999px; animation:barra 1s cubic-bezier(.2,.8,.2,1) backwards;}}
.st-key-p2_prog [data-testid="stButtonGroup"] button {{border-radius:999px;}}
.stTabs .stTabs [role="tablist"] {{margin:0 0 12px !important; padding:0 !important; background:transparent !important;
    backdrop-filter:none; border-bottom:1px solid {BORDA} !important;}}
.stTabs .stTabs [role="tab"] {{height:38px; font-size:.82rem;}}
.st-key-p2_ordem_txt, .st-key-p1_ordem_txt {{position:absolute !important; left:-9999px; height:0; overflow:hidden;}}
@media (max-width:700px) {{ .bi-top {{flex-direction:column; align-items:flex-start; gap:6px;}} .bi-top .meta {{text-align:left;}} }}
</style>""", unsafe_allow_html=True)


LOGO_B64 = "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"

st.markdown(f"""<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
[data-testid="stElementContainer"]:has(style), [data-testid="stElementContainer"]:has(iframe[height="1"]),
[data-testid="stElementContainer"]:has(iframe[data-testid="stIFrame"]) {{display:none;}}
@keyframes subir {{ from {{opacity:0; transform:translateY(10px);}} to {{opacity:1; transform:none;}} }}
@keyframes brilho {{ 0% {{background-position:-200% 0;}} 100% {{background-position:200% 0;}} }}
@keyframes pulso {{ 0%,100% {{opacity:.55;}} 50% {{opacity:1;}} }}
.stApp {{background:
    radial-gradient(1200px 500px at 85% -10%, rgba(42,120,214,.10), transparent 60%),
    radial-gradient(900px 400px at -10% 10%, rgba(0,21,100,.07), transparent 60%), {FUNDO};}}
/* cabeçalho Rede Bahia */
.bi-top {{position:relative; overflow:hidden; border-bottom:0; padding:14px 1.6rem 14px;
    background:linear-gradient(110deg, #001564 0%, #062a8c 55%, #0b3fae 100%);
    box-shadow:0 8px 24px rgba(0,21,100,.18);}}
.bi-top::before {{content:""; position:absolute; inset:0; pointer-events:none;
    background:linear-gradient(105deg, transparent 35%, rgba(255,255,255,.10) 50%, transparent 65%);
    background-size:200% 100%; animation:brilho 7s ease-in-out infinite;}}
.bi-top::after {{content:""; position:absolute; left:0; right:0; bottom:0; height:3px;
    background:linear-gradient(90deg, #00c2ff, #2a78d6, #7b5cff, #00c2ff); background-size:200% 100%;
    animation:brilho 6s linear infinite;}}
.bi-top .marca {{display:flex; align-items:center; gap:14px; position:relative; z-index:1;}}
.bi-top .logo {{height:44px; width:auto; display:block; filter:drop-shadow(0 2px 6px rgba(0,0,0,.25));}}
.bi-top .sep {{width:1px; height:36px; background:rgba(255,255,255,.25);}}
.bi-top h1 {{font-weight:700; letter-spacing:.1px;}}
.bi-top .sub, .bi-top .meta {{color:#b9c6ea; position:relative; z-index:1;}}
/* abas com efeito vidro */
.stTabs [role="tablist"], .stTabs [data-baseweb="tab-list"] {{background:rgba(255,255,255,.72) !important;
    backdrop-filter:blur(10px); -webkit-backdrop-filter:blur(10px); border-bottom:1px solid {BORDA} !important;}}
.stTabs [role="tab"] {{border-radius:8px 8px 0 0;}}
.stTabs [role="tab"]:hover {{background:rgba(42,120,214,.06);}}
.stTabs [role="tab"][aria-selected="true"] {{box-shadow:inset 0 -3px 0 #2a78d6;}}
/* cartões */
[class*="st-key-card"] {{border-radius:14px !important; border:1px solid rgba(16,24,64,.07) !important; position:relative;
    box-shadow:0 1px 2px rgba(16,24,64,.04), 0 8px 24px rgba(16,24,64,.05);
    transition:box-shadow .25s ease, transform .25s ease, border-color .25s ease;
    animation:subir .55s cubic-bezier(.2,.7,.2,1) both;}}
[class*="st-key-card"]:hover {{transform:translateY(-2px); border-color:rgba(42,120,214,.25) !important;
    box-shadow:0 2px 4px rgba(16,24,64,.05), 0 14px 32px rgba(16,24,64,.09);}}
.vt {{font-size:.9rem; font-weight:600; letter-spacing:.1px;}}
/* KPIs */
.kpi {{border-radius:12px; border:1px solid rgba(16,24,64,.07); border-top:0; position:relative; overflow:hidden;
    box-shadow:0 1px 2px rgba(16,24,64,.04), 0 6px 18px rgba(16,24,64,.05);
    transition:transform .25s ease, box-shadow .25s ease; animation:subir .5s cubic-bezier(.2,.7,.2,1) both;}}
.kpi::before {{content:""; position:absolute; left:0; right:0; top:0; height:3px;
    background:linear-gradient(90deg, var(--c), color-mix(in srgb, var(--c) 35%, #ffffff));}}
.kpi:hover {{transform:translateY(-3px); box-shadow:0 4px 10px rgba(16,24,64,.06), 0 16px 32px rgba(16,24,64,.10);}}
.kpi .v {{font-weight:700; letter-spacing:-.4px;}}
.kpis .kpi:nth-child(1) {{animation-delay:.02s;}} .kpis .kpi:nth-child(2) {{animation-delay:.06s;}}
.kpis .kpi:nth-child(3) {{animation-delay:.10s;}} .kpis .kpi:nth-child(4) {{animation-delay:.14s;}}
.kpis .kpi:nth-child(5) {{animation-delay:.18s;}} .kpis .kpi:nth-child(6) {{animation-delay:.22s;}}
.kpis .kpi:nth-child(7) {{animation-delay:.26s;}} .kpis .kpi:nth-child(8) {{animation-delay:.30s;}}
/* campos e botões */
[data-baseweb="select"] > div, [data-testid="stMultiSelect"] [data-baseweb="select"] > div {{border-radius:10px !important;
    transition:box-shadow .2s, border-color .2s;}}
[data-baseweb="select"] > div:hover {{box-shadow:0 0 0 3px rgba(42,120,214,.10);}}
.stButton button, .stDownloadButton button {{border-radius:10px; transition:transform .15s, box-shadow .2s, background .2s;}}
.stButton button:hover, .stDownloadButton button:hover {{transform:translateY(-1px); box-shadow:0 6px 14px rgba(42,120,214,.18);}}
[data-testid="stSegmentedControl"] button {{transition:all .2s;}}
/* botão de expandir no canto dos cartões */
.st-key-exp_calor, .st-key-exp_curva {{position:absolute !important; top:8px; right:10px; width:auto !important; z-index:3;}}
.st-key-exp_calor button, .st-key-exp_curva button {{min-height:0; height:30px; width:30px; padding:0; border-radius:9px;
    border:1px solid rgba(16,24,64,.10); background:rgba(255,255,255,.9); color:#2a78d6;}}
.st-key-exp_calor button:hover, .st-key-exp_curva button:hover {{background:#2a78d6; color:#fff; transform:scale(1.06);}}
/* janela expandida */
[data-testid="stDialog"] [role="dialog"] {{border-radius:18px; box-shadow:0 30px 80px rgba(0,21,100,.25);}}
.mini {{display:grid; grid-template-columns:repeat(auto-fit, minmax(150px,1fr)); gap:8px; margin:4px 0 10px;}}
.mini div {{background:linear-gradient(180deg,#f7f9ff,#eef3fd); border:1px solid rgba(42,120,214,.12); border-radius:10px;
    padding:8px 11px; font-size:.72rem; color:{TINTA2}; animation:subir .45s both;}}
.mini b {{display:block; font-size:1.05rem; color:{TINTA}; margin-top:2px; font-variant-numeric:tabular-nums;}}
.vivo {{display:inline-block; width:7px; height:7px; border-radius:50%; background:#00c2ff; margin-right:6px;
    box-shadow:0 0 0 0 rgba(0,194,255,.6); animation:pulso 4s ease-in-out infinite; vertical-align:middle;}}
/* ---------- animações dos gráficos ---------- */
@keyframes barY {{ from {{transform:scaleY(0);}} to {{transform:scaleY(1);}} }}
@keyframes barX {{ from {{transform:scaleX(0);}} to {{transform:scaleX(1);}} }}
@keyframes desenha {{ from {{stroke-dashoffset:4000;}} to {{stroke-dashoffset:0;}} }}
@keyframes surge {{ from {{opacity:0;}} to {{opacity:1;}} }}
@keyframes surgeZoom {{ from {{opacity:0; transform:scale(.97);}} to {{opacity:1; transform:none;}} }}
@keyframes larg {{ from {{width:0;}} }}
.js-plotly-plot .barlayer .point path {{transform-box:fill-box; transform-origin:50% 100%;
    animation:barY .75s cubic-bezier(.2,.85,.25,1) backwards; animation-delay:var(--d, 0ms);}}
.st-key-v_pct_meta .js-plotly-plot .barlayer .point path {{
    transform-origin:0% 50%; animation-name:barX;}}
.js-plotly-plot .barlayer .point text, .js-plotly-plot .barlayer .bartext {{animation:surge .45s ease backwards;
    animation-delay:calc(var(--d, 0ms) + 420ms);}}
.js-plotly-plot .scatterlayer .js-line {{stroke-dasharray:4000; animation:desenha 1.4s cubic-bezier(.45,.05,.25,1) backwards;}}
.js-plotly-plot .scatterlayer .js-fill {{animation:surge .9s ease backwards;}}
.js-plotly-plot .scatterlayer .points path, .js-plotly-plot .scatterlayer .textpoint {{animation:surge .5s ease backwards; animation-delay:.75s;}}
.js-plotly-plot .heatmaplayer image {{animation:surgeZoom .8s cubic-bezier(.2,.8,.2,1) backwards; transform-box:fill-box; transform-origin:center;}}
.js-plotly-plot .heatmaplayer text {{animation:surge .5s ease backwards; animation-delay:.5s;}}
/* o gráfico cresce suavemente quando muda de altura (ex.: mais bancos no período) */
.js-plotly-plot .svg-container {{transition:height .6s cubic-bezier(.2,.8,.2,1); overflow:hidden;}}
/* tabelas: linhas entram em sequência e as barrinhas crescem */
.rk tr {{animation:subir .45s cubic-bezier(.2,.8,.2,1) backwards;}}
.rk tr:nth-child(2) {{animation-delay:.03s;}} .rk tr:nth-child(3) {{animation-delay:.06s;}} .rk tr:nth-child(4) {{animation-delay:.09s;}}
.rk tr:nth-child(5) {{animation-delay:.12s;}} .rk tr:nth-child(6) {{animation-delay:.15s;}} .rk tr:nth-child(7) {{animation-delay:.18s;}}
.rk tr:nth-child(8) {{animation-delay:.21s;}} .rk tr:nth-child(9) {{animation-delay:.24s;}} .rk tr:nth-child(10) {{animation-delay:.27s;}}
.rk tr:nth-child(n+11) {{animation-delay:.3s;}}
.rk .bar {{animation:larg .9s cubic-bezier(.2,.8,.2,1) backwards; animation-delay:.25s;}}
.kpi .v {{transition:color .3s;}}
.kpi .v.contando {{color:#2a78d6;}}
@media (prefers-reduced-motion: reduce) {{ *, *::before, *::after {{animation:none !important; transition:none !important;}} }}
/* painel da meta: quadros entram em sequência */
@keyframes pop {{ from {{opacity:0; transform:scale(.92);}} to {{opacity:1; transform:none;}} }}
.pg {{border-radius:12px; background:linear-gradient(180deg,#f7f9ff,#eef3fd); border:1px solid rgba(42,120,214,.10);
    animation:subir .5s cubic-bezier(.2,.7,.2,1) backwards; transition:transform .25s, box-shadow .25s;}}
.pg:hover {{transform:translateY(-2px); box-shadow:0 10px 24px rgba(16,24,64,.10);}}
.pg .c {{border-radius:9px; animation:pop .5s cubic-bezier(.2,.8,.2,1) backwards; box-shadow:inset 0 -2px 0 rgba(0,0,0,.08);}}
.painel .pg:nth-child(1) {{animation-delay:.02s;}} .painel .pg:nth-child(2) {{animation-delay:.07s;}} .painel .pg:nth-child(3) {{animation-delay:.12s;}}
.painel .pg:nth-child(4) {{animation-delay:.17s;}} .painel .pg:nth-child(5) {{animation-delay:.22s;}} .painel .pg:nth-child(6) {{animation-delay:.27s;}}
.painel .pg:nth-child(7) {{animation-delay:.32s;}} .painel .pg:nth-child(8) {{animation-delay:.37s;}} .painel .pg:nth-child(9) {{animation-delay:.42s;}}
.painel .pg:nth-child(10) {{animation-delay:.47s;}}
.painel .pg .c:nth-child(2) {{animation-delay:.12s;}}
.leitura {{border-radius:10px; border-left:3px solid #2a78d6; background:linear-gradient(90deg,#f1f5ff,#f7f9ff);
    animation:subir .5s cubic-bezier(.2,.7,.2,1) backwards;}}
/* abas fixas com sublinhado azul ([role=tab] = versões novas do Streamlit) */
.stTabs [role="tablist"] {{gap:0 !important; margin:0 -1.6rem 14px; padding:0 1.6rem;}}
.stTabs [role="tab"] {{padding:0 16px !important; white-space:nowrap; height:42px;}}
.stTabs .react-aria-SelectionIndicator {{display:none;}}
/* o cabeçalho do próprio Streamlit (invisível, mas no Streamlit Cloud fica por cima do canto superior direito)
   não pode capturar os cliques: o nosso cabeçalho fica acima dele */
header[data-testid="stHeader"] {{pointer-events:none !important; height:0 !important; min-height:0 !important; background:transparent !important;}}
header[data-testid="stHeader"] * {{pointer-events:none !important;}}
[data-testid="stMain"], [data-testid="stAppViewContainer"] {{overflow-x:hidden;}}
/* cabeçalho (faixa azul com logo, datas e botão do modo escuro) */
.st-key-topo {{z-index:1000100 !important; position:relative; overflow:hidden; width:100vw !important; max-width:none !important;
    margin:0 0 0 calc(50% - 50vw) !important; box-sizing:border-box; gap:0;
    padding:12px max(1.6rem, calc(50vw - 750px + 1.6rem)) 13px !important;
    background:linear-gradient(110deg, #001564 0%, #062a8c 55%, #0b3fae 100%); box-shadow:0 8px 24px rgba(0,21,100,.18);}}
.st-key-topo::before {{content:""; position:absolute; inset:0; pointer-events:none;
    background:linear-gradient(105deg, transparent 35%, rgba(255,255,255,.10) 50%, transparent 65%);
    background-size:200% 100%; animation:brilho 32s ease-in-out infinite;}}
.st-key-topo::after {{content:""; position:absolute; left:0; right:0; bottom:0; height:3px;
    background:linear-gradient(90deg, #00c2ff, #2a78d6, #7b5cff, #00c2ff); background-size:200% 100%; animation:brilho 36s linear infinite;}}
.st-key-topo [data-testid="stHorizontalBlock"] {{position:relative; z-index:1;}}
.st-key-topo .marca {{display:flex; align-items:center; gap:14px;}}
.st-key-topo .logo {{height:44px; width:auto; display:block; filter:drop-shadow(0 2px 6px rgba(0,0,0,.25));}}
.st-key-topo .sep {{width:1px; height:36px; background:rgba(255,255,255,.25);}}
.st-key-topo h1 .tela {{display:inline-flex; position:relative; width:30px; height:19px; margin-left:8px; vertical-align:-3px;
    border:2px solid rgba(255,255,255,.75); border-radius:4px; overflow:hidden; background:#0b1430;
    box-shadow:0 0 10px rgba(0,194,255,.35), inset 0 0 6px rgba(0,0,0,.6);}}
.st-key-topo h1 .tela::after {{content:""; position:absolute; left:50%; bottom:-6px; width:12px; height:3px; transform:translateX(-50%);
    background:rgba(255,255,255,.6); border-radius:2px;}}
.st-key-topo h1 .tela i {{flex:1; height:100%; animation:cor 9s ease-in-out infinite;}}
.st-key-topo h1 .tela i:nth-child(1) {{background:#e8e8e8;}}
.st-key-topo h1 .tela i:nth-child(2) {{background:#f2d43a; animation-delay:-1.3s;}}
.st-key-topo h1 .tela i:nth-child(3) {{background:#35c9d8; animation-delay:-2.6s;}}
.st-key-topo h1 .tela i:nth-child(4) {{background:#3fbf4f; animation-delay:-3.9s;}}
.st-key-topo h1 .tela i:nth-child(5) {{background:#c44bc0; animation-delay:-5.2s;}}
.st-key-topo h1 .tela i:nth-child(6) {{background:#d9433b; animation-delay:-6.5s;}}
.st-key-topo h1 .tela i:nth-child(7) {{background:#2a4fd6; animation-delay:-7.8s;}}
.st-key-topo h1 .tela b {{position:absolute; left:0; right:0; top:-30%; height:30%; pointer-events:none;
    background:linear-gradient(180deg, transparent, rgba(255,255,255,.55), transparent); animation:varredura 5.5s linear infinite;}}
@keyframes cor {{ 0%,100% {{filter:brightness(.75) saturate(.8);}} 50% {{filter:brightness(1.12) saturate(1.1);}} }}
@keyframes varredura {{ from {{top:-30%;}} to {{top:110%;}} }}
.st-key-topo canvas.sinal {{position:absolute; inset:0; width:100%; height:100%; pointer-events:none; z-index:0;}}
.st-key-topo h1 {{font-size:1.15rem; font-weight:700; margin:0; padding:0; color:#fff !important; letter-spacing:.1px;}}
.st-key-topo .sub {{font-size:.78rem; color:#b9c6ea !important; margin-top:2px;}}
.st-key-topo .meta {{font-size:.74rem; color:#b9c6ea !important; text-align:right; line-height:1.5;}}
.st-key-topo .meta b {{color:#fff !important; font-weight:600;}}
.st-key-topo [data-testid="stMarkdownContainer"] p {{margin:0;}}
.demo {{margin:10px 0 2px; padding:8px 14px; border-radius:10px; font-size:.8rem; color:#6b4e00; border:1px solid #f0c24b;
    background:repeating-linear-gradient(135deg, #fff6d6 0 14px, #fff0bf 14px 28px);}}
.demo b {{color:#4a3600;}}
.st-key-tema_btn, .st-key-pdf_btn {{display:flex; justify-content:flex-end;}}
.st-key-pdf_btn button {{background:rgba(255,255,255,.08) !important; color:#dbe4ff !important; border:1px solid rgba(255,255,255,.3) !important;
    border-radius:999px !important; padding:5px 15px !important; min-height:0 !important; white-space:nowrap; box-shadow:none !important;}}
.st-key-pdf_btn button:hover {{background:rgba(255,255,255,.18) !important; border-color:rgba(255,255,255,.55) !important;}}
.st-key-pdf_btn button p {{color:#dbe4ff !important; font-size:.78rem;}}
.st-key-tema_btn button {{background:rgba(255,255,255,.08) !important; color:#dbe4ff !important; border:1px solid rgba(255,255,255,.3) !important;
    border-radius:999px !important; padding:5px 15px !important; min-height:0 !important; font-size:.78rem; white-space:nowrap;
    box-shadow:none !important;}}
.st-key-tema_btn button:hover {{background:rgba(255,255,255,.18) !important; border-color:rgba(255,255,255,.55) !important;}}
.st-key-tema_btn button p {{color:#dbe4ff !important; font-size:.78rem;}}
@media (max-width:700px) {{ .st-key-topo .meta {{text-align:left;}} }}
""" + (f"""
/* ---------- modo escuro ---------- */
.stApp {{background:radial-gradient(1200px 520px at 85% -10%, rgba(42,120,214,.16), transparent 60%),
    radial-gradient(900px 420px at -10% 10%, rgba(0,60,200,.12), transparent 60%), {FUNDO} !important;}}
.stTabs [role="tablist"], .stTabs [data-baseweb="tab-list"] {{background:rgba(19,28,49,.78) !important;}}
.stTabs [role="tab"]:hover {{background:rgba(90,152,230,.10);}}
.stTabs [role="tab"][aria-selected="true"] {{box-shadow:inset 0 -3px 0 #5a98e6 !important;}}
[class*="st-key-card"] {{border-color:rgba(255,255,255,.06) !important; box-shadow:0 1px 2px rgba(0,0,0,.4), 0 10px 28px rgba(0,0,0,.28);}}
[class*="st-key-card"]:hover {{border-color:rgba(90,152,230,.35) !important; box-shadow:0 2px 6px rgba(0,0,0,.45), 0 16px 36px rgba(0,0,0,.4);}}
.kpi {{border-color:rgba(255,255,255,.06); box-shadow:0 1px 2px rgba(0,0,0,.4), 0 8px 22px rgba(0,0,0,.3);}}
.kpi::before {{background:linear-gradient(90deg, var(--c), color-mix(in srgb, var(--c) 30%, {CARTAO}));}}
.kpi .v.contando {{color:#6aa6f0;}}
.mini div {{background:linear-gradient(180deg,#17223b,#131c31); border-color:rgba(90,152,230,.18);}}
.st-key-exp_calor button, .st-key-exp_curva button {{background:rgba(19,28,49,.9); border-color:rgba(255,255,255,.14); color:#8fb8f0;}}
.st-key-exp_calor button:hover, .st-key-exp_curva button:hover {{background:#2a78d6; color:#fff;}}
[data-testid="stDialog"] [role="dialog"] {{box-shadow:0 30px 80px rgba(0,0,0,.6);}}
.stButton button:hover, .stDownloadButton button:hover {{box-shadow:0 6px 16px rgba(42,120,214,.30);}}
.xf {{border-color:#3d6fb8;}}
/* gráficos mais vivos no fundo escuro: leve brilho nas linhas e cores um pouco mais saturadas */
.js-plotly-plot .scatterlayer .js-line {{filter:drop-shadow(0 0 3px rgba(255,255,255,.22));}}
.js-plotly-plot .barlayer .point path {{filter:saturate(1.1) brightness(1.06);}}
.js-plotly-plot .scatterlayer .points path {{filter:drop-shadow(0 0 2px rgba(255,255,255,.3));}}
/* componentes do próprio Streamlit (o tema dele fica claro; aqui eles ganham as cores escuras) */
.stApp, .stApp p, .stApp li, .stApp label, .stMarkdown, [data-testid="stMarkdownContainer"],
[data-testid="stCaptionContainer"], [data-testid="stExpander"] summary, .stApp h1, .stApp h2, .stApp h3, .stApp h4 {{color:{TINTA};}}
[data-testid="stWidgetLabel"] p {{color:{TINTA2} !important;}}
[data-baseweb="select"] > div, [data-baseweb="input"], [data-baseweb="input"] > div, [data-baseweb="base-input"],
.stTextInput input, .stNumberInput input, [data-baseweb="textarea"] textarea {{background:{CAMPO} !important; color:{TINTA} !important;
    border-color:{BORDA_IN} !important;}}
[data-baseweb="select"] input, [data-baseweb="select"] span, [data-baseweb="select"] div {{color:{TINTA};}}
[data-baseweb="select"] svg, [data-testid="stNumberInput"] svg {{fill:{TINTA2}; color:{TINTA2};}}
[data-baseweb="popover"] > div, [data-baseweb="popover"] ul, [data-baseweb="menu"], [role="listbox"] {{background:{CARTAO} !important; color:{TINTA} !important;}}
[data-baseweb="popover"] li, [role="option"] {{color:{TINTA} !important; background:transparent;}}
[data-baseweb="popover"] li:hover, [role="option"]:hover, [role="option"][aria-selected="true"], [role="option"][data-focused] {{background:{REALCE} !important;}}
[data-testid="stSelectbox"] [role="group"], [data-testid="stMultiSelect"] [role="group"],
[data-testid="stNumberInputContainer"], [data-testid="stTextInputRootElement"] {{background:{CAMPO} !important;
    border-color:{BORDA_IN} !important; color:{TINTA};}}
[data-testid="stSelectbox"] input, [data-testid="stMultiSelect"] input, [data-testid="stNumberInput"] input,
[data-testid="stTextInput"] input {{background:transparent !important; color:{TINTA} !important;}}
[data-testid="stSelectbox"] [role="group"] *, [data-testid="stNumberInputContainer"] * {{color:{TINTA};}}
[data-testid="stSelectbox"] svg, [data-testid="stMultiSelect"] svg {{color:{TINTA2}; fill:{TINTA2};}}
[data-testid="stSelectboxVirtualDropdown"], [data-testid="stMultiSelectDropdown"] {{background:{CARTAO} !important;
    color:{TINTA} !important; border:1px solid {BORDA}; box-shadow:0 12px 32px rgba(0,0,0,.45);}}
[data-testid="stSelectboxVirtualDropdown"] *, [data-testid="stMultiSelectDropdown"] * {{color:{TINTA};}}
[data-testid="stNumberInput"] button {{background:{CAMPO}; color:{TINTA2}; border-color:{BORDA_IN};}}
.stButton button[kind="secondary"], .stDownloadButton button, [data-testid="stBaseButton-secondary"] {{background:{CAMPO}; color:{TINTA};
    border-color:{BORDA_IN};}}
[data-testid="stButtonGroup"] button {{background:{CAMPO}; color:{TINTA2}; border-color:{BORDA_IN};}}
[data-testid="stButtonGroup"] button[aria-checked="true"], [data-testid="stButtonGroup"] button[kind*="Active"] {{background:rgba(42,120,214,.22); color:#cfe2ff; border-color:#3d6fb8;}}
[data-testid="stExpander"] details {{background:transparent; border-color:{BORDA};}}
[data-testid="stDialog"] [role="dialog"] {{background:{CARTAO} !important; color:{TINTA};}}
[data-testid="stDialog"] [role="dialog"] button[aria-label="Close"] svg {{fill:{TINTA2};}}
[data-testid="stFileUploaderDropzone"] {{background:{CAMPO}; border-color:{BORDA_IN}; color:{TINTA2};}}
[data-testid="stFileUploaderDropzone"] span, [data-testid="stFileUploaderDropzone"] small {{color:{TINTA2};}}
[data-testid="stAlert"] {{color:{TINTA};}}
[data-testid="stAlert"] p {{color:{TINTA} !important;}}
[data-testid="stTooltipIcon"] svg, [data-testid="stTooltipHoverTarget"] svg {{color:{CINZA}; stroke:{CINZA};}}
[data-testid="stSliderTickBar"], [data-testid="stSliderTickBarMin"], [data-testid="stSliderTickBarMax"] {{color:{CINZA};}}
/* tabelas do Streamlit (desenhadas em canvas): inversão de cores para combinar com o fundo escuro */
[data-testid="stDataFrame"] canvas, [data-testid="stDataFrameResizable"] canvas {{filter:invert(.9) hue-rotate(180deg) brightness(1.05);}}
[data-testid="stDataFrame"], [data-testid="stDataFrameResizable"] {{border-radius:10px; overflow:hidden;}}
.pg {{background:linear-gradient(180deg,#17223b,#131c31) !important; border-color:rgba(90,152,230,.16) !important;}}
.leitura {{background:linear-gradient(90deg,#16213a,#131c31) !important; color:{TINTA2};}}
.leitura b {{color:{TINTA};}}
""" if ESCURO else "") + """</style>""", unsafe_allow_html=True)

# ============================================================ dados
ARQ_BASE = os.path.join("dados", "tv_mensal.csv")
ARQ_PAR = "parametros_tv.json"
PASTA_RODADAS = os.path.join("dados", "rodadas")
PASTA_RODADAS_BANCO = "cache_rodadas"          # cópia local das rodadas guardadas no banco (o leitor trabalha com arquivos)


def rodadas_disponiveis():
    """Planilhas de resultado em dados/rodadas/ e também soltas em dados/ (rodada_*.xlsx ou resultado_*.xlsx)."""
    if _banco_ativo():
        arqs = banco.rodadas_para_pasta(PASTA_RODADAS_BANCO)
    else:
        arqs = glob.glob(os.path.join(PASTA_RODADAS, "*.xlsx"))
        arqs += [a for a in glob.glob(os.path.join("dados", "*.xlsx"))
                 if os.path.basename(a).lower().startswith(("rodada", "resultado"))]
    return sorted({a for a in arqs if not os.path.basename(a).startswith("~$") and "diario" not in os.path.basename(a).lower()},
                  reverse=True)


def caminho_rodada(nome):
    return next((a for a in rodadas_disponiveis() if os.path.basename(a) == nome), os.path.join(PASTA_RODADAS, nome))


def _assinatura():
    if _banco_ativo():
        return ("banco",) + banco.assinatura(["tv_audiencia_mensal", "tv_rodadas", "painel_parametros"])
    arqs = [ARQ_BASE, ARQ_PAR, "tv.py"] + rodadas_disponiveis()
    return tuple(sorted((a, os.path.getmtime(a), os.path.getsize(a)) for a in arqs if os.path.exists(a)))


@st.cache_data
def carregar(assinatura=None):
    if _banco_ativo():
        par = banco.parametros("tv", estrito=True)
        # banco de dados da empresa: a aplicação de carga da TI grava a audiência; rodadas e parâmetros podem vir do painel
        base = banco.ler("tv_audiencia_mensal").reindex(columns=tv.COLUNAS)
        base["mes"] = pd.to_datetime(base["mes"])
        base["valor"] = pd.to_numeric(base["valor"], errors="coerce")
    else:                                   # só na demonstração: arquivos fictícios gerados em demo_runtime/
        par = json.load(open(ARQ_PAR, encoding="utf-8")) if os.path.exists(ARQ_PAR) else {}
        base = tv.ler_base(ARQ_BASE) if os.path.exists(ARQ_BASE) else pd.DataFrame(columns=tv.COLUNAS)
    rods = {}
    for a in rodadas_disponiveis():
        try:
            rods[os.path.basename(a)] = _so_programas(tv.ler_resultado(a))
        except Exception as ex:          # uma rodada com problema não derruba o painel
            rods[os.path.basename(a)] = {"erro": str(ex)}
    return base, par, rods


def _so_programas(rod):
    """Tira da rodada do modelo mensal as linhas das faixas (6h e 7h às 24h): elas vêm do modelo diário."""
    faixas = {"6h às 24h", "7h às 24h"}
    out = {}
    for k, v in rod.items():
        if isinstance(v, pd.DataFrame) and len(v):
            if isinstance(v.index, pd.MultiIndex):
                v = v[~v.index.get_level_values(0).isin(faixas)]
            elif v.index.isin(faixas).any():
                v = v[~v.index.isin(faixas)]
            if "programa" in v.columns:
                v = v[~v["programa"].isin(faixas)]
        out[k] = v
    return out


def _nao_disponivel(motivo):
    """Sem banco de dados: o painel avisa e para. Nunca volta para arquivos locais (a pasta dados/ não vai ao repositório)."""
    st.error("**Não disponível.** Os dados do painel não puderam ser carregados do banco de dados. "
             "Tente novamente em alguns minutos; se continuar, avise a TI.")
    st.caption(f"Detalhe técnico: {motivo}")
    st.stop()


if not MODO_DEMO and not banco.ativo():
    _nao_disponivel("conexão com o banco não configurada (variável PAINEL_DB_URL)")
try:
    BASE, PAR, RODADAS = carregar(_assinatura())
except Exception as _ex:
    if MODO_DEMO:
        raise
    _nao_disponivel(f"falha ao ler o banco ({_ex.__class__.__name__})")
_mes_max = pd.to_datetime(BASE["mes"]).max() if len(BASE) else None
_validas = {k: v for k, v in RODADAS.items() if "erro" not in v}
_ord = sorted(_validas, key=lambda k: _validas[k]["meta"]["corte"] or pd.Timestamp(0), reverse=True)
ATIVA = PAR.get("rodada_ativa") if PAR.get("rodada_ativa") in _validas else (_ord[0] if _ord else None)
R = _validas.get(ATIVA)                       # rodada do modelo mensal: só programas (as faixas vêm do modelo diário)
META = R["meta"] if R else {}
ANO = META.get("ano") or (int(_mes_max.year) if _mes_max is not None and pd.notna(_mes_max) else pd.Timestamp.today().year)
CORTE = META.get("corte")
REST = META.get("meses_rest", "")
ANT = META.get("anterior", "rodada anterior")


# =================================================================================== MODELO DIÁRIO (por faixa)
PASTA_DIARIAS = os.path.join("dados", "rodadas_diarias")


def arquivos_rodadas_diarias():
    if _banco_ativo():
        return [a for a in banco.rodadas_para_pasta(PASTA_RODADAS_BANCO) if "diario" in os.path.basename(a).lower()]
    return diario.arquivos_diarios([PASTA_DIARIAS, "dados"])


@st.cache_data(show_spinner=False)
def carregar_diarias(assinatura=None):
    return diario.carregar_rodadas(arquivos_rodadas_diarias())


def _assinatura_diarias():
    if _banco_ativo():
        return ("banco",) + banco.assinatura(["tv_rodadas"])
    return tuple(sorted((a, os.path.getmtime(a), os.path.getsize(a)) for a in arquivos_rodadas_diarias()))


def _corte_diario(faixa):
    """Data de corte da rodada mais recente do modelo diário da faixa (None se não houver)."""
    try:
        lista = carregar_diarias(_assinatura_diarias())[0].get(faixa, [])
    except Exception:
        return None
    return lista[0]["corte"] if lista else None


# ============================================================ formatação e componentes
def br(v, casas=2):
    if v is None or pd.isna(v):
        return "–"
    s = f"{v:,.{casas}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def sinal(v, casas=2):
    return ("+" if v is not None and pd.notna(v) and v > 0 else "") + br(v, casas)


def rot_mes(d, ano=True):
    d = pd.Timestamp(d)
    return f"{MESES[d.month - 1]}/{str(d.year)[2:]}" if ano else MESES[d.month - 1]


def dpp(v):
    """Variação de probabilidade em pontos percentuais."""
    if v is None or pd.isna(v):
        return ""
    if abs(v) < 0.5:
        return "estável"
    return f"{'+' if v > 0 else '−'}{br(abs(v), 1)} p.p."


def layout(fig, h=290, legenda=False):
    fig.update_layout(template="none", height=h, margin=dict(l=6, r=10, t=6 if not legenda else 30, b=6),
                      paper_bgcolor=CARTAO, plot_bgcolor=CARTAO, separators=",.",
                      font=dict(family=FONTE_TXT, size=12, color=TINTA2), showlegend=legenda,
                      legend=dict(orientation="h", x=0, y=1.02, yanchor="bottom", font=dict(size=11), title_text=""),
                      hoverlabel=dict(bgcolor=CARTAO, bordercolor=BORDA, font=dict(family=FONTE_TXT, size=12, color=TINTA)),
                      bargap=0.28, barcornerradius=4, dragmode=False,
                      transition=dict(duration=450, easing="cubic-in-out"))
    fig.update_xaxes(showgrid=False, linecolor=EIXO, ticks="", tickfont=dict(size=11), automargin=True, title_text="")
    fig.update_yaxes(gridcolor=GRADE, zeroline=False, linecolor="rgba(0,0,0,0)", tickfont=dict(size=11), automargin=True,
                     title_text="", tickformat=",.1f")
    return fig


CFG = {"displayModeBar": False}
_n_card = [0]


def cartao(titulo, sub=""):
    _n_card[0] += 1
    st.session_state["_card_titulo"], st.session_state["_card_sub"] = _sem_tags(titulo), _sem_tags(sub)
    c = st.container(border=True, key=f"card{_n_card[0]}")
    c.markdown(f'<div class="vt">{titulo}</div>' + (f'<div class="vs">{sub}</div>' if sub else ""), unsafe_allow_html=True)
    return c


def _sem_tags(t):
    import re
    return re.sub(r"<[^>]+>", "", str(t)).replace('"', "")


def kpis(lista):
    if isinstance(st.session_state.get("_kpis_run"), list):
        st.session_state["_kpis_run"].append({"aba": st.session_state.get("_aba_atual", ""),
                                              "cartoes": [(_sem_tags(t), _sem_tags(v), _sem_tags(d), c) for t, v, d, c in lista]})
    st.markdown('<div class="kpis">' + "".join(
        f'<div class="kpi" style="--c:{c}"><div class="t">{t}</div><div class="v">{v}</div>'
        f'<div class="d" title="{_sem_tags(d)}">{d}</div></div>' for t, v, d, c in lista) + "</div>", unsafe_allow_html=True)


def sem_html(s):
    return f'<span style="color:{COR_SEM.get(s, CINZA)}; font-weight:600">{s}</span>'


def _rodar_js(html):
    if hasattr(st, "iframe"):
        st.iframe(html, height=1)
    else:
        import streamlit.components.v1 as components
        components.html(html, height=0)

_EFEITOS_JS = r"""
(function () {
  const P = window, D = document;
  if (P.__efeitosPainel) return;
  P.__efeitosPainel = true;
  // 0) modo claro/escuro: o botão é do próprio Streamlit; aqui o navegador só lembra a última escolha
  D.addEventListener("click", ev => {
    const b = ev.target.closest(".st-key-tema_btn button");
    if (b) { try { P.localStorage.setItem("painelTema", b.textContent.includes("escuro") ? "escuro" : "claro"); } catch (e) {} }
  }, true);
  (function lembra(n) {
    const b = D.querySelector(".st-key-tema_btn button");
    if (!b) { if (n < 60) setTimeout(() => lembra(n + 1), 200); return; }
    let salvo = null;
    try { salvo = P.localStorage.getItem("painelTema"); } catch (e) { return; }
    const atual = b.textContent.includes("escuro") ? "claro" : "escuro";
    if (salvo && salvo !== atual && !/[?&]tema=/.test(P.location.search)) b.click();
  })(0);
  // 1) barras novas entram em sequência: atraso por série e por posição
  function escalona(raiz) {
    raiz.querySelectorAll(".js-plotly-plot .barlayer .trace").forEach((tr, k) => {
      tr.querySelectorAll(".point").forEach((g, i) => {
        if (!g.dataset.anim) { g.dataset.anim = 1; g.style.setProperty("--d", Math.min(k * 110 + i * 22, 900) + "ms"); }
      });
    });
  }
  // 2) números dos cartões contam até o valor (e de um valor ao outro quando o filtro muda)
  const ultimo = {};
  function parse(t) {
    const m = t.trim().match(/^([+\-−]?)([\d.]+)(?:,(\d+))?(.*)$/);
    if (!m || /\d/.test(m[4])) return null;       // datas e textos como 30/09/2026 não contam
    const casas = m[3] ? m[3].length : 0;
    const v = parseFloat(m[2].replace(/\./g, "") + (m[3] ? "." + m[3] : ""));
    return {sinal: m[1], v: (m[1] === "-" || m[1] === "−") ? -v : v, casas, suf: m[4], mil: m[2].includes(".") || v >= 1000};
  }
  function fmt(x, n) {
    const neg = x < 0, a = Math.abs(x);
    let [i, d] = a.toFixed(n.casas).split(".");
    if (n.mil || a >= 1000) i = i.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    const s = neg ? (n.sinal === "−" ? "−" : "-") : (n.sinal === "+" ? "+" : "");
    return s + i + (d ? "," + d : "") + n.suf;
  }
  function conta(el) {
    if (el.dataset.contado === el.textContent) return;
    const alvo = el.textContent, n = parse(alvo);
    const chave = (el.closest(".kpi")?.querySelector(".t")?.textContent || el.closest("[data-m]")?.dataset.m || "") + "|" + n?.suf
                  + "|" + (el.classList.contains("gv") ? "anel" : el.closest(".gf") ? "fecha" : "kpi");
    if (!n) { el.dataset.contado = alvo; return; }
    const de = ultimo[chave] !== undefined ? ultimo[chave] : 0;
    ultimo[chave] = n.v;
    if (de === n.v) { el.dataset.contado = alvo; return; }
    const t0 = performance.now(), dur = 900;
    el.classList.add("contando");
    function passo(t) {
      const f = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - f, 3);
      el.textContent = f < 1 ? fmt(de + (n.v - de) * e, n) : alvo;
      el.dataset.contado = el.textContent;
      if (f < 1) requestAnimationFrame(passo); else el.classList.remove("contando");
    }
    requestAnimationFrame(passo);
  }
  function varre(raiz) {
    escalona(raiz);
    raiz.querySelectorAll(".kpi .v, .anel .gv, .gtxt .gf > b").forEach(conta);
  }
  new MutationObserver(ms => {
    for (const m of ms) for (const n of m.addedNodes) if (n.nodeType === 1) varre(n.closest ? (n.closest(".js-plotly-plot") || n) : n);
    ms.forEach(m => { if (m.type === "characterData" && m.target.parentElement?.matches(".kpi .v, .anel .gv, .gtxt .gf > b")) conta(m.target.parentElement); });
  }).observe(D.body, {childList: true, subtree: true, characterData: true});
  varre(D);

  // ---- cabeçalho: sinal de transmissão (arcos saindo de uma antena) e varredura de tela, bem lentos
  const calmo = P.matchMedia && P.matchMedia("(prefers-reduced-motion: reduce)").matches;
  function sinal() {
    const topo = D.querySelector(".st-key-topo");
    if (!topo) { setTimeout(sinal, 400); return; }
    if (topo.querySelector("canvas.sinal")) return;
    const c = D.createElement("canvas");
    c.className = "sinal";
    topo.prepend(c);
    const ctx = c.getContext("2d");
    let t = 0;
    function desenha() {
      if (!c.isConnected) { setTimeout(sinal, 400); return; }
      const w = c.clientWidth, h = c.clientHeight, dpr = P.devicePixelRatio || 1;
      if (c.width !== w * dpr || c.height !== h * dpr) { c.width = w * dpr; c.height = h * dpr; }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      const ax = w * .55, ay = h * .5;                      // a antena fica no meio, entre o título e os botões
      for (let k = 0; k < 5; k++) {                          // arcos que nascem na antena e se afastam devagar
        const fase = ((t * .045) + k / 5) % 1, r = 14 + fase * w * .5, alfa = .16 * (1 - fase);
        ctx.beginPath();
        ctx.arc(ax, ay, r, -Math.PI * .22, Math.PI * .22);
        ctx.strokeStyle = `rgba(120,200,255,${alfa})`; ctx.lineWidth = 1.4; ctx.stroke();
        ctx.beginPath();
        ctx.arc(ax, ay, r, Math.PI * .78, Math.PI * 1.22);
        ctx.strokeStyle = `rgba(160,140,255,${alfa})`; ctx.stroke();
      }
      ctx.fillStyle = "rgba(120,200,255,.35)";               // a antena: um ponto que pulsa
      ctx.beginPath(); ctx.arc(ax, ay, 2.2 + Math.sin(t * .8) * .6, 0, Math.PI * 2); ctx.fill();
      const yv = ((t * 7) % (h + 40)) - 20;                  // varredura horizontal de tela
      const g = ctx.createLinearGradient(0, yv - 14, 0, yv + 14);
      g.addColorStop(0, "rgba(255,255,255,0)"); g.addColorStop(.5, "rgba(255,255,255,.05)"); g.addColorStop(1, "rgba(255,255,255,0)");
      ctx.fillStyle = g; ctx.fillRect(0, yv - 14, w, 28);
      ctx.fillStyle = "rgba(255,255,255,.018)";              // linhas de tela, bem leves
      for (let y = 0; y < h; y += 3) ctx.fillRect(0, y, w, 1);
      if (!D.hidden) t += .012;
      if (!calmo) requestAnimationFrame(desenha);
    }
    desenha();
  }
  sinal();
})();
"""
_rodar_js("<script>const D = window.parent.document; if (!window.parent.__efeitosPainel) { const s = D.createElement('script'); "
          "s.textContent = " + json.dumps(_EFEITOS_JS) + "; D.head.appendChild(s); }</script>")


NOME_P = {tv.FAIXA: "TV Bahia (6h às 24h)", tv.FAIXA_7: "TV Bahia (7h às 24h)"}


def nome_p(p):
    return NOME_P.get(p, p)


def serie(prog, met):
    return tv.serie(BASE, prog, met)


def linha(prog, met):
    """Linha da rodada ativa para a série (programa, métrica)."""
    try:
        return R["fech"].loc[(prog, met)]
    except (KeyError, TypeError):
        return None


def mensal_proj(prog, met):
    if not R:
        return pd.DataFrame()
    m = R["mensal"]
    return m[(m["programa"] == prog) & (m["metrica"] == met)].set_index("mes").sort_index()


def metas_bi(prog, met):
    d = PAR.get("metas_mensais_bi", {}).get(f"{prog}|{met}", {})
    return pd.Series({pd.Timestamp(k + "-01"): v for k, v in d.items()}, dtype=float).sort_index()


# ============================================================ cabeçalho
_ult_mes = BASE["mes"].max() if len(BASE) else None
with st.container(key="topo"):
    _fx_cab = st.session_state.get("faixa_ref") or tv.FAIXA
    _corte_cab = _corte_diario(_fx_cab)
    _c = st.columns([5.6, 2.5, 1.15, 1.15], vertical_alignment="center", gap="small")
    _c[0].markdown(f"""<div class="marca"><img class="logo" alt="Rede Bahia" src="data:image/png;base64,{LOGO_B64}">
<div class="sep"></div><div><h1>Painel de Audiência · TV <span class="tela" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><b></b></span></h1>
<div class="sub">Globo · TV Bahia · Faixa 6h às 24h e programas locais · TT Domicílios · Grande Salvador · Kantar IBOPE (Instar)</div></div></div>""",
                   unsafe_allow_html=True)
    _c[1].markdown(f"""<div class="meta"><span class="vivo"></span>Dados mensais até <b>{rot_mes(_ult_mes) if _ult_mes is not None else '–'}</b><br>
Projeção · faixa {_fx_cab[:2]}: <b>{f"{_corte_cab:%d/%m}" if _corte_cab is not None else "–"}</b> · programas: <b>{f"{CORTE:%d/%m}" if CORTE is not None else "–"}</b></div>""",
                   unsafe_allow_html=True)
    _c[2].button("📄 Exportar PDF", key="pdf_btn", on_click=lambda: st.session_state.update(_abrir_pdf=True))
    _c[3].button("☀️ Modo claro" if ESCURO else "🌙 Modo escuro", key="tema_btn", on_click=_troca_tema)
if PAR.get("demo"):
    st.markdown('<div class="demo">🧪 <b>Ambiente de demonstração.</b> Todos os números deste painel são <b>fictícios</b>, gerados '
                'só para testar e apresentar as funcionalidades. Eles não representam a audiência real e as concorrentes têm nomes '
                'inventados.</div>', unsafe_allow_html=True)
if getattr(st, "_plotly_versao", 0) < 2:
    # (1) no modo escuro, os gráficos usam só as cores do painel; (2) cada gráfico desenhado fica registrado na sessão,
    # com o título do cartão, para o relatório em PDF. Tudo é lido da sessão de cada pessoa.
    st._plotly_original = getattr(st, "_plotly_original", st.plotly_chart)

    def _plotly_tema(fig, *a, **k):
        ss_ = st.session_state
        if ss_.get("tema_escuro"):
            k.setdefault("theme", None)
        chave = str(k.get("key", ""))
        if chave and not chave.startswith("dlg_") and isinstance(ss_.get("_graf_run"), list):
            ss_["_graf_run"].append({"chave": chave, "titulo": ss_.get("_card_titulo", ""), "sub": ss_.get("_card_sub", ""),
                                     "aba": ss_.get("_aba_atual", ""), "fig": fig})
        return st._plotly_original(fig, *a, **k)
    st.plotly_chart = _plotly_tema
    st._plotly_versao = 2
st.session_state["_graf_run"] = []
st.session_state["_kpis_run"] = []

# ---- visualizações da tela inicial: as padrão já vêm marcadas; as extras entram pelo rodapé (🧩 Visualizações)
VIS_PADRAO = {"evolucao": "Evolução (barras)", "desempenho": "Desempenho do último mês (tabela)", "anual": "Média anual",
              "curva": "Curva do ano", "calor": "Mapa de calor", "comparativo": "Comparativo em linhas"}
VIS_EXTRA = {"outra": "A outra métrica (audiência ↔ share)", "yoy": "Variação vs mesmo mês do ano anterior",
             "mm": "Variação vs mês anterior", "tendencia": "Tendência: média móvel de 12 meses",
             "indice": "Índice vs TV Bahia (6h às 24h)", "ranking": "Ranking dos programas no último mês",
             "sazonal": "Sazonalidade por mês (caixas)"}
VIS_TODAS = {**VIS_PADRAO, **VIS_EXTRA}
if "vis_sel" not in st.session_state:
    _q = st.query_params.get("vis")
    st.session_state["vis_sel"] = [v for v in _q.split(",") if v in VIS_TODAS] if _q else list(VIS_PADRAO)


def mostra(codigo):
    return codigo in st.session_state.get("vis_sel", list(VIS_PADRAO))


def _guarda_vis():
    sel_ = st.session_state.get("vis_w") or []
    st.session_state["vis_sel"] = list(sel_)
    if sorted(sel_) == sorted(VIS_PADRAO):
        st.query_params.pop("vis", None)
    else:
        st.query_params["vis"] = ",".join(sel_)


def faixa_atual():
    return st.session_state.get("faixa_ref") or tv.FAIXA


_fx = st.columns([1.6, 5])
_fx[0].segmented_control("Faixa horária de referência", diario.FAIXAS, default=tv.FAIXA, key="faixa_ref",
                         help="O único lugar onde se escolhe a faixa: a Visão geral mostra a faixa escolhida junto com os "
                              "programas, e as Projeções mostram o modelo diário dessa faixa.")
_fx[1].markdown(f'<div class="vs" style="margin-top:30px">Faixa em uso: <b>{st.session_state.get("faixa_ref") or tv.FAIXA}</b> · '
                f'TV Bahia (Globo) · Grande Salvador</div>', unsafe_allow_html=True)
paginas = st.tabs(["Visão geral", "Projeções e metas"])


# =================================================================================== PÁGINA 1 · VISÃO GERAL
def _nome_curto(prog, met):
    return f"{prog} ({'aud.' if met == 'Audiência' else 'share'})"


def _agrupa(series):
    """Junta as duas métricas de um programa quando as duas estão no mesmo grupo: 'BATV' em vez de 'BATV (aud.), BATV (share)'."""
    por_prog = {}
    for p, m in series:
        por_prog.setdefault(p, []).append(m)
    return [p if len(ms) == 2 else _nome_curto(p, ms[0]) for p, ms in por_prog.items()]


def _lista(nomes):
    return ", ".join(nomes[:-1]) + " e " + nomes[-1] if len(nomes) > 1 else (nomes[0] if nomes else "nenhuma")


def secao(num, titulo, sub=""):
    st.markdown(f'<div class="secao"><div class="num">{num}</div><div><div class="st">{titulo}</div>'
                f'{f"<div class=ss>{sub}</div>" if sub else ""}</div><div class="linha"></div></div>', unsafe_allow_html=True)


def _registra_kpis(lista):
    """Guarda cartões para o relatório em PDF sem desenhá-los (quando a tela mostra outra forma visual)."""
    if isinstance(st.session_state.get("_kpis_run"), list):
        st.session_state["_kpis_run"].append({"aba": st.session_state.get("_aba_atual", ""),
                                              "cartoes": [(_sem_tags(t), _sem_tags(v), _sem_tags(d), c) for t, v, d, c in lista]})


# =================================================================================== PÁGINA 2 · PROGRAMAS
_ARRASTE_JS = r"""
(function () {
  const P = window, D = document, SEL = ".st-key-__CHAVE__", TXT = ".st-key-__TXT__ input";
  if (P["__arraste___CHAVE__"]) return;
  P["__arraste___CHAVE__"] = true;
  const css = D.createElement("style");
  css.textContent = `
    ${SEL} [data-tag], ${SEL} [data-baseweb="tag"] {cursor:grab; touch-action:none; user-select:none;}
    .arraste-fantasma {position:fixed; z-index:99999; pointer-events:none; opacity:.9; transform:rotate(-2deg);
                       box-shadow:0 6px 16px rgba(0,0,0,.25); cursor:grabbing;}
    .arraste-marca {position:fixed; z-index:99998; width:3px; border-radius:2px; background:#1c5cab; pointer-events:none;}`;
  D.head.appendChild(css);
  const Q = `${SEL} [data-tag], ${SEL} [data-baseweb='tag']`;
  const tags = () => [...D.querySelectorAll(Q)];
  const rotulo = t => (t.getAttribute("aria-label") || t.textContent || "").trim();
  let ini = null, arr = null, fant = null, marca = null, destino = null;
  function onde(x, y) {
    const ts = tags(); let pos = ts.length;
    for (let i = 0; i < ts.length; i++) {
      const r = ts[i].getBoundingClientRect();
      if (y < r.top - 4) { pos = i; break; }
      if (y <= r.bottom + 4 && x < r.left + r.width / 2) { pos = i; break; }
    }
    return pos;
  }
  function mostraMarca(pos) {
    const ts = tags(); if (!ts.length) return;
    const ref = pos < ts.length ? ts[pos].getBoundingClientRect() : ts[ts.length - 1].getBoundingClientRect();
    const x = pos < ts.length ? ref.left - 4 : ref.right + 2;
    Object.assign(marca.style, {left: x + "px", top: ref.top + "px", height: ref.height + "px"});
  }
  function enviar(ordem) {
    const inp = D.querySelector(TXT); if (!inp) return;
    const set = Object.getOwnPropertyDescriptor(P.HTMLInputElement.prototype, "value").set;
    inp.focus();
    set.call(inp, JSON.stringify({o: ordem, t: Date.now()}));
    inp.dispatchEvent(new P.Event("input", {bubbles: true}));
    inp.dispatchEvent(new P.KeyboardEvent("keydown", {key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true}));
    inp.blur();
  }
  const ehTag = ev => ev.target.closest(Q) && !ev.target.closest("button, [role='presentation']");
  D.addEventListener("pointerdown", ev => {
    if (!ehTag(ev) || ev.button !== 0) return;
    ev.preventDefault(); ev.stopPropagation();
    const t = ev.target.closest(Q);
    ini = {x: ev.clientX, y: ev.clientY, tag: t, i: tags().indexOf(t)};
  }, true);
  D.addEventListener("mousedown", ev => { if (ehTag(ev)) { ev.preventDefault(); ev.stopPropagation(); } }, true);
  D.addEventListener("pointermove", ev => {
    if (!ini) return;
    if (!arr) {
      if (Math.hypot(ev.clientX - ini.x, ev.clientY - ini.y) < 5) return;
      arr = ini; const r = arr.tag.getBoundingClientRect();
      fant = arr.tag.cloneNode(true); fant.classList.add("arraste-fantasma");
      Object.assign(fant.style, {width: r.width + "px", height: r.height + "px", left: r.left + "px", top: r.top + "px"});
      arr.dx = ev.clientX - r.left; arr.dy = ev.clientY - r.top;
      marca = D.createElement("div"); marca.className = "arraste-marca";
      D.body.append(fant, marca); arr.tag.style.opacity = ".35";
    }
    fant.style.left = (ev.clientX - arr.dx) + "px"; fant.style.top = (ev.clientY - arr.dy) + "px";
    destino = onde(ev.clientX, ev.clientY); mostraMarca(destino);
  }, true);
  function fim() {
    if (arr) {
      const nomes = tags().map(rotulo), de = arr.i;
      let para = destino == null ? de : destino;
      arr.tag.style.opacity = ""; fant.remove(); marca.remove();
      if (para > de) para -= 1;
      if (para !== de && de >= 0) { const [m] = nomes.splice(de, 1); nomes.splice(para, 0, m); enviar(nomes); }
    }
    ini = arr = fant = marca = destino = null;
  }
  D.addEventListener("pointerup", fim, true);
  D.addEventListener("pointercancel", fim, true);
})();
"""


def ordem_do_arraste(chave, txt, opcoes, rotulo=lambda x: x):
    v = st.session_state.get(txt, "")
    if v and v != st.session_state.get(f"_{txt}_lida"):
        st.session_state[f"_{txt}_lida"] = v
        try:
            por_rot = {rotulo(o): o for o in opcoes}
            nova = [por_rot[n] for n in json.loads(v)["o"] if n in por_rot]
            if sorted(nova) == sorted(st.session_state.get(chave, [])):
                st.session_state[chave] = nova
        except (ValueError, KeyError, TypeError):
            pass


def arrastar_selecionados(chave, txt):
    """Os quadros azuis do campo de seleção podem ser arrastados para mudar a ordem (a ordem nova volta por um campo escondido)."""
    st.text_input("ordem", key=txt, label_visibility="collapsed")
    js = _ARRASTE_JS.replace("__CHAVE__", chave).replace("__TXT__", txt)
    _rodar_js(f"""<script>
    const D = window.parent.document;
    if (!window.parent["__arraste_{chave}"]) {{
      const s = D.createElement("script"); s.textContent = {json.dumps(js)}; D.head.appendChild(s);
    }}
    </script>""")


# =================================================================================== VISÃO GERAL · DESEMPENHO
PADRAO_P1 = ["BATV", "Globo Esporte", "Bahia Meio Dia"]          # programas; a faixa vem do seletor acima das abas


def _peso(prog, mes):
    return tv.n_exib(prog, mes, mes + pd.offsets.MonthEnd(0))


def _periodos(sel, met, serie_):
    meses = sorted(set(BASE.loc[BASE["programa"].isin(sel) & (BASE["metrica"] == met), "mes"]))
    meses = [pd.Timestamp(m) for m in meses]
    if serie_ == "Mês":
        return meses
    if serie_ == "Trimestre":
        q = pd.Series(1, index=pd.DatetimeIndex(meses)).groupby(pd.PeriodIndex(meses, freq="Q")).size()
        return [p.end_time.normalize().replace(day=1) for p, n in q.items() if n == 3]
    return sorted({m.year for m in meses})


def _rot_per(x, serie_):
    if serie_ == "Mês":
        return rot_mes(x)
    if serie_ == "Trimestre":
        return f"{tv.MESES[x.month - 3]}–{tv.MESES[x.month - 1]}/{str(x.year)[2:]}"
    return str(x)


def _valor_per(prog, met, x, serie_):
    """Valor do período: o mês; ou a média do trimestre/ano ponderada pelas exibições. Devolve (valor, nº de meses)."""
    s = serie(prog, met).dropna()
    if serie_ == "Mês":
        v = s.get(x, np.nan)
        return v, int(pd.notna(v))
    meses = (pd.date_range(x - pd.DateOffset(months=2), x, freq="MS") if serie_ == "Trimestre"
             else pd.date_range(f"{x}-01-01", f"{x}-12-01", freq="MS"))
    v = s.reindex(meses).dropna()
    if v.empty:
        return np.nan, 0
    w = np.array([_peso(prog, m) for m in v.index], float)
    return float((v.values * w).sum() / w.sum()), len(v)


def _dpt(a, b):
    """Diferença em pontos com seta: ▲ +0,35 pt."""
    if a is None or b is None or pd.isna(a) or pd.isna(b):
        return "<span style='color:#8a8984'>sem dado</span>"
    d = a - b
    cls, seta = ("up", "▲") if d > 0 else ("down", "▼")
    return f"<span class='{cls}'>{seta} {br(abs(d))} pt</span>"


def media_parcial(prog, met, ano, ate_mes):
    s = serie(prog, met).dropna()
    v = s[(s.index.year == ano) & (s.index.month <= ate_mes)]
    if v.empty:
        return np.nan, 0
    w = np.array([_peso(prog, m) for m in v.index], float)
    return float((v.values * w).sum() / w.sum()), len(v)


# =================================================================================== mapa de calor e curva do ano (com janela expandida)
MEDIDAS = {"v": "valor do mês", "m": "variação vs mês anterior (pt)", "a": "variação vs mesmo mês do ano anterior (pt)"}
DIVERG = ([[0, "#ff6b5e"], [.35, "#6b2f33"], [.5, "#131c31"], [.65, "#24476f"], [1, "#6aa6f0"]] if ESCURO else
          [[0, "#b42318"], [.35, "#f4b6ae"], [.5, "#f6f7fb"], [.65, "#a9c8f2"], [1, "#1c5cab"]])
CORES_ANOS = ["#aab6cf" if ESCURO else "#52514e", "#7b5cff", "#00a3a3", "#eb6834", "#c0392b", "#8a8984", "#2e7d32", "#b07d00"]


def tabela_tv(prog, met, med):
    """Ano × mês da série: valor, variação vs mês anterior ou vs mesmo mês do ano anterior (em pontos)."""
    s = serie(prog, met).dropna()
    anos = sorted(set(s.index.year), reverse=True)
    tab = pd.DataFrame([[s.get(pd.Timestamp(a, m, 1), np.nan) for m in range(1, 13)] for a in anos], index=anos, columns=MESES)
    if med == "m":
        flat = tab.sort_index().stack(future_stack=True)
        tab = (flat - flat.shift(1)).unstack().sort_index(ascending=False)
    elif med == "a":
        tab = tab - tab.shift(-1)
    tab.index.name = "Ano"
    return tab


def fig_calor_tv(tab, med, h, texto=True):
    t = tab.sort_index()
    z = t.values.astype(float)
    if med == "v":
        kw = dict(colorscale=SEQ, colorbar=dict(thickness=10, outlinewidth=0, tickfont=dict(size=10), tickformat=",.1f"),
                  hovertemplate="<b>%{y}</b> · %{x}: %{z:.2f}<extra></extra>")
        txt = [[("" if pd.isna(v) else br(v, 1)) for v in r] for r in z]
    else:
        lim = float(np.nanpercentile(np.abs(z), 95)) if np.isfinite(z).any() else 1
        kw = dict(colorscale=DIVERG, zmid=0, zmin=-lim, zmax=lim,
                  colorbar=dict(thickness=10, outlinewidth=0, tickfont=dict(size=10), tickformat="+,.1f"),
                  hovertemplate="<b>%{y}</b> · %{x}: %{z:+.2f} pt<extra></extra>")
        txt = [[("" if pd.isna(v) else sinal(v, 1)) for v in r] for r in z]
    fig = go.Figure(go.Heatmap(z=z, x=list(t.columns), y=[str(a) for a in t.index], xgap=2, ygap=2,
                               text=txt if texto else None, texttemplate="%{text}" if texto else None, textfont=dict(size=9), **kw))
    layout(fig, h).update_yaxes(autorange="reversed", tickformat="", dtick=1, tickfont=dict(size=10))
    fig.update_xaxes(tickangle=0, tickfont=dict(size=10))
    return fig


def fig_curva_tv(prog, met, anos, banda, h):
    s = serie(prog, met)
    ano_atual = int(s.dropna().index.year.max())
    fig = go.Figure()
    if banda:
        ant = [a for a in sorted(set(s.dropna().index.year)) if a < ano_atual and a not in anos]
        if ant:
            tab = pd.DataFrame({a: [s.get(pd.Timestamp(a, m, 1), np.nan) for m in range(1, 13)] for a in ant}, index=MESES)
            fig.add_scatter(x=MESES, y=tab.max(axis=1), mode="lines", line=dict(width=0), hoverinfo="skip", showlegend=False)
            fig.add_scatter(x=MESES, y=tab.min(axis=1), mode="lines", line=dict(width=0), fill="tonexty",
                            fillcolor="rgba(138,137,132,.16)", name=f"mín–máx dos outros anos ({ant[0]}–{ant[-1]})", hoverinfo="skip")
    outros = sorted([a for a in anos if a != ano_atual], reverse=True)
    for k, a in enumerate(outros + ([ano_atual] if ano_atual in anos else [])):
        cor = COR_PROG.get(prog, AZUL) if a == ano_atual else CORES_ANOS[k % len(CORES_ANOS)]
        est = dict(color=cor, width=2.6) if a == ano_atual else dict(color=cor, width=1.8, dash="dash" if k == 0 else "dot")
        y = [s.get(pd.Timestamp(a, m, 1), np.nan) for m in range(1, 13)]
        fig.add_scatter(x=MESES, y=y, mode="lines+markers", name=str(a), line=est,
                        marker=dict(size=7 if a == ano_atual else 5, color=cor, line=dict(color=CARTAO, width=1.5)),
                        hovertemplate=f"<b>{a}</b> · %{{x}}: %{{y:.2f}}<extra></extra>")
    layout(fig, h, legenda=True)
    return fig, s, ano_atual


def _guarda(dest, origem):
    st.session_state[dest] = st.session_state[origem]


def _dialogo(titulo):
    import inspect
    kw = {"width": "large"}
    if "on_dismiss" in inspect.signature(st.dialog).parameters:
        kw["on_dismiss"] = "rerun"
    return st.dialog(titulo, **kw)


def _estado_foco(foco, met, progs):
    ss = st.session_state
    if ss.get("_foco_ult") != (foco, met):          # trocar o programa em foco (ou a métrica) leva os dois quadros junto
        ss["_foco_ult"] = (foco, met)
        ss["hm_prog"] = ss["cv_prog"] = foco
        ss["hm_met"] = ss["cv_met"] = met
        ss.pop("cv_anos", None)
    ss.setdefault("hm_med", "v")
    ss.setdefault("cv_banda", True)
    for k in ("hm_prog", "cv_prog"):
        if ss.get(k) not in progs:
            ss[k] = foco


@_dialogo("Mapa de calor · detalhes")
def janela_calor():
    ss = st.session_state
    progs = [p for p in tv.PROGRAMAS if p in set(BASE["programa"])]
    c = st.columns(3)
    c[0].selectbox("Faixa ou programa", progs, index=progs.index(ss["hm_prog"]), format_func=nome_p, key="hm_prog_w",
                   on_change=_guarda, args=("hm_prog", "hm_prog_w"))
    c[1].selectbox("Métrica", tv.METRICAS, index=tv.METRICAS.index(ss["hm_met"]), format_func=lambda m: f"{m} ({tv.SIGLA[m]})",
                   key="hm_met_w", on_change=_guarda, args=("hm_met", "hm_met_w"))
    c[2].selectbox("Mostrar", list(MEDIDAS), index=list(MEDIDAS).index(ss["hm_med"]), format_func=MEDIDAS.get, key="hm_med_w",
                   on_change=_guarda, args=("hm_med", "hm_med_w"))
    prog, met, med = ss["hm_prog"], ss["hm_met"], ss["hm_med"]
    tab = tabela_tv(prog, met, med)
    s = serie(prog, met).dropna()
    if len(s):
        ult = s.index.max()
        m1, n1 = media_parcial(prog, met, ult.year, ult.month)
        m0, _ = media_parcial(prog, met, ult.year - 1, ult.month)
        st.markdown(f"""<div class="mini">
            <div>Maior mês da série<b>{br(s.max())}</b>{rot_mes(s.idxmax())}</div>
            <div>Menor mês da série<b>{br(s.min())}</b>{rot_mes(s.idxmin())}</div>
            <div>Média parcial de {ult.year} ({n1} meses)<b>{br(m1)}</b>{sinal(m1 - m0) + ' pt vs mesmo período de ' + str(ult.year - 1) if pd.notna(m0) else ''}</div>
            <div>Meses na série<b>{len(s)}</b>desde {rot_mes(s.index.min())}</div></div>""", unsafe_allow_html=True)
    if med == "v":                          # média do ano (ponderada pelas exibições) ao lado dos meses
        ma = tv.media_anual(serie(prog, met), prog)
        tab = tab.assign(ano=[ma["media"].get(a, np.nan) for a in tab.index])
    st.plotly_chart(fig_calor_tv(tab, med, 32 * len(tab) + 70), config=CFG, key="dlg_calor")
    out = BASE.copy()
    out["mes"] = out["mes"].dt.strftime("%Y-%m")
    b = st.columns([1.2, 1.4, 1])
    b[0].download_button("⬇️ Exportar tabela (CSV)", tab.to_csv(sep=";", decimal=",").encode("utf-8-sig"),
                         file_name=f"tv_{prog}_{met}.csv".replace(" ", "_"), mime="text/csv", key="dlg_dl_tab")
    b[1].download_button("⬇️ Exportar base mensal (CSV)", out.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
                         file_name="tv_mensal.csv", mime="text/csv", key="dlg_dl_base")
    if b[2].button("Minimizar", icon=":material/close_fullscreen:", key="min_calor", type="primary"):
        st.rerun()


@_dialogo("Curva do ano · detalhes")
def janela_curva():
    ss = st.session_state
    progs = [p for p in tv.PROGRAMAS if p in set(BASE["programa"])]
    c = st.columns([1.3, 1, 2.2, 1.2])
    c[0].selectbox("Faixa ou programa", progs, index=progs.index(ss["cv_prog"]), format_func=nome_p, key="cv_prog_w",
                   on_change=_guarda, args=("cv_prog", "cv_prog_w"))
    c[1].selectbox("Métrica", tv.METRICAS, index=tv.METRICAS.index(ss["cv_met"]), key="cv_met_w",
                   on_change=_guarda, args=("cv_met", "cv_met_w"))
    s = serie(ss["cv_prog"], ss["cv_met"]).dropna()
    anos_disp = sorted(set(s.index.year), reverse=True)
    atual = anos_disp[0]
    padrao = [a for a in ss.get("cv_anos", [atual, atual - 1]) if a in anos_disp] or [atual]
    c[2].multiselect("Anos", anos_disp, default=padrao, key="cv_anos_w", on_change=_guarda, args=("cv_anos", "cv_anos_w"))
    c[3].toggle("Faixa dos outros anos", value=ss["cv_banda"], key="cv_banda_w", on_change=_guarda, args=("cv_banda", "cv_banda_w"))
    anos = ss.get("cv_anos", padrao) or padrao
    fig, s, ano_atual = fig_curva_tv(ss["cv_prog"], ss["cv_met"], anos, ss["cv_banda"], 430)
    st.plotly_chart(fig, config=CFG, key="dlg_curva")
    piv = pd.DataFrame([[s.get(pd.Timestamp(a, m, 1), np.nan) for m in range(1, 13)] for a in sorted(anos, reverse=True)],
                       index=sorted(anos, reverse=True), columns=MESES)
    cur = piv.loc[ano_atual].dropna() if ano_atual in piv.index else pd.Series(dtype=float)
    mini = ""
    if len(cur):
        mini += (f"<div>Melhor mês de {ano_atual}<b>{br(cur.max())}</b>{cur.idxmax()}</div>"
                 f"<div>Pior mês de {ano_atual}<b>{br(cur.min())}</b>{cur.idxmin()}</div>")
        for a in [x for x in piv.index if x != ano_atual][:2]:
            ant = piv.loc[a, cur.index].mean()
            if pd.notna(ant):
                mini += (f"<div>{ano_atual} vs {a} (mesmos meses)<b>{sinal(cur.mean() - ant)} pt</b>"
                         f"{br(cur.mean())} vs {br(ant)}</div>")
    st.markdown(f'<div class="mini">{mini}</div>', unsafe_allow_html=True)
    t = piv.copy()
    t["média"] = piv.mean(axis=1)
    t.index.name = "Ano"
    with st.expander("Tabela com os valores", expanded=False):
        st.dataframe(t.map(lambda v: "" if pd.isna(v) else br(v)), width="stretch")
    if st.button("Minimizar", icon=":material/close_fullscreen:", key="min_curva", type="primary"):
        st.rerun()


def _dupla(a, b, larg=(1, 1)):
    """Duas posições lado a lado; se só uma das duas for mostrada, ela ocupa a linha toda."""
    if a and b:
        c = st.columns(list(larg))
        return c[0], c[1]
    return st.container(), st.container()


def _meses_do_periodo(serie_, periodos):
    if serie_ == "Mês":
        return list(periodos)
    if serie_ == "Trimestre":
        return sorted({m for x in periodos for m in pd.date_range(x - pd.DateOffset(months=2), x, freq="MS")})
    return sorted({m for a in periodos for m in pd.date_range(f"{a}-01-01", f"{a}-12-01", freq="MS")})


def extras_tv(sel, met, serie_, periodos, p0, p1, foco, progs):
    """Visualizações extras escolhidas no rodapé (🧩), duas por linha."""
    pedidas = [c for c in VIS_EXTRA if mostra(c)]
    if not pedidas:
        return
    rot = [_rot_per(x, serie_) for x in periodos]
    faixa_txt = f"{rot[0]} a {rot[-1]}" if rot else ""
    un = {"Mês": "mês", "Trimestre": "trimestre", "Ano": "ano"}[serie_]
    rotx = lambda fig: fig.update_xaxes(tickangle=-45 if len(rot) > 8 else 0, tickfont=dict(size=10))   # noqa: E731

    def outra():
        m2 = "Share" if met == "Audiência" else "Audiência"
        with cartao(f"{m2} ({tv.SIGLA[m2]}) · mesmo período", faixa_txt):
            fig = go.Figure()
            for p in sel:
                v = [_valor_per(p, m2, x, serie_)[0] for x in periodos]
                fig.add_scatter(x=rot, y=v, name=nome_p(p), mode="lines+markers", line=dict(color=COR_PROG.get(p, CINZA), width=2.4),
                                marker=dict(size=6), hovertemplate=f"<b>{nome_p(p)}</b> · %{{x}}: %{{y:.2f}}<extra></extra>")
            layout(fig, 300, legenda=True)
            rotx(fig)
            st.plotly_chart(fig, config=CFG, key="v_x_outra")

    def variacao(chave, titulo, desloc):
        with cartao(titulo, f"{tv.SIGLA[met]} · diferença em pontos · {faixa_txt}"):
            fig = go.Figure()
            for p in sel:
                v = []
                for x in periodos:
                    a = _valor_per(p, met, x, serie_)[0]
                    b = _valor_per(p, met, desloc(x), serie_)[0]
                    v.append(a - b if pd.notna(a) and pd.notna(b) else np.nan)
                fig.add_bar(x=rot, y=v, name=nome_p(p), marker_color=COR_PROG.get(p, CINZA),
                            hovertemplate=f"<b>{nome_p(p)}</b> · %{{x}}: %{{y:+.2f}} pt<extra></extra>")
            layout(fig, 300, legenda=True).update_layout(barmode="group")
            fig.update_yaxes(zeroline=True, zerolinecolor=EIXO, tickformat="+,.1f")
            rotx(fig)
            st.plotly_chart(fig, config=CFG, key=chave)

    def yoy():
        variacao("v_x_yoy", f"Variação vs mesmo {un} do ano anterior",
                 (lambda x: x - 1) if serie_ == "Ano" else (lambda x: x - pd.DateOffset(years=1)))

    def mm():
        variacao("v_x_mm", f"Variação vs {un} anterior", (lambda x: x - 1) if serie_ == "Ano" else
                 (lambda x: x - pd.DateOffset(months=1 if serie_ == "Mês" else 3)))

    def tendencia():
        meses = _meses_do_periodo(serie_, periodos)
        if len(meses) < 13:
            meses = list(pd.date_range(meses[-1] - pd.DateOffset(months=35), meses[-1], freq="MS")) if meses else meses
        with cartao(f"Tendência · média móvel de 12 meses", f"{tv.SIGLA[met]} · {rot_mes(meses[0])} a {rot_mes(meses[-1])}"):
            fig = go.Figure()
            for p in sel:
                s_ = serie(p, met)
                mm12 = s_.rolling(12, min_periods=12).mean().reindex(meses)
                fig.add_scatter(x=[rot_mes(m) for m in meses], y=s_.reindex(meses).values, name=nome_p(p) + " (mês)", mode="lines",
                                line=dict(color=COR_PROG.get(p, CINZA), width=1, dash="dot"), opacity=.5, showlegend=False,
                                hovertemplate=f"<b>{nome_p(p)}</b> · %{{x}}: %{{y:.2f}}<extra></extra>")
                fig.add_scatter(x=[rot_mes(m) for m in meses], y=mm12.values, name=nome_p(p), mode="lines",
                                line=dict(color=COR_PROG.get(p, CINZA), width=2.8),
                                hovertemplate=f"<b>{nome_p(p)}</b> · %{{x}}<br>média de 12 meses: %{{y:.2f}}<extra></extra>")
            layout(fig, 300, legenda=True)
            fig.update_xaxes(tickangle=-45, tickfont=dict(size=10), nticks=14)
            st.plotly_chart(fig, config=CFG, key="v_x_tendencia")

    def indice():
        alvo = [p for p in sel if p != tv.FAIXA]
        with cartao(f"Índice vs TV Bahia (6h às 24h)", f"{tv.SIGLA[met]} do programa ÷ {tv.SIGLA[met]} da faixa × 100 · {faixa_txt}"):
            if not alvo:
                st.markdown('<div class="vs">Escolha ao menos um programa (além da faixa) no topo.</div>', unsafe_allow_html=True)
                return
            fig = go.Figure()
            for p in alvo:
                v = []
                for x in periodos:
                    a, b = _valor_per(p, met, x, serie_)[0], _valor_per(tv.FAIXA, met, x, serie_)[0]
                    v.append(a / b * 100 if pd.notna(a) and pd.notna(b) and b else np.nan)
                fig.add_scatter(x=rot, y=v, name=nome_p(p), mode="lines+markers", line=dict(color=COR_PROG.get(p, CINZA), width=2.4),
                                hovertemplate=f"<b>{nome_p(p)}</b> · %{{x}}: índice %{{y:.0f}}<extra></extra>")
            fig.add_hline(y=100, line=dict(color=CINZA, dash="dot", width=1))
            layout(fig, 300, legenda=True)
            fig.update_yaxes(tickformat=",.0f")
            rotx(fig)
            st.plotly_chart(fig, config=CFG, key="v_x_indice")

    def ranking():
        ult = BASE["mes"].max()
        vals = sorted([(p, serie(p, met).get(ult, np.nan)) for p in progs if pd.notna(serie(p, met).get(ult, np.nan))],
                      key=lambda t: t[1])
        with cartao(f"Ranking dos programas · {rot_mes(ult)}", f"{tv.SIGLA[met]} · selecionados em cor"):
            fig = go.Figure(go.Bar(y=[nome_p(p) for p, _ in vals], x=[v for _, v in vals], orientation="h",
                                   marker_color=[COR_PROG.get(p, CINZA) if p in sel else CINZA_CLARO for p, _ in vals],
                                   text=[br(v) for _, v in vals], textposition="outside", cliponaxis=False,
                                   hovertemplate="<b>%{y}</b>: %{x:.2f}<extra></extra>"))
            layout(fig, 320)
            fig.update_xaxes(showgrid=True, gridcolor=GRADE)
            st.plotly_chart(fig, config=CFG, key="v_x_ranking")

    def sazonal():
        s_ = serie(foco, met).dropna()
        ano_f = int(s_.index.year.max())
        with cartao(f"Sazonalidade por mês · {nome_p(foco)}",
                    f"{tv.SIGLA[met]} de cada mês de {s_.index.year.min()} a {ano_f} · ◆ = {ano_f}"):
            fig = go.Figure()
            fig.add_box(x=[MESES[m - 1] for m in s_.index.month], y=s_.values, marker_color=COR_PROG.get(foco, AZUL),
                        boxmean=True, showlegend=False, name=nome_p(foco), hovertemplate="%{x}: %{y:.2f}<extra></extra>")
            at = s_[s_.index.year == ano_f]
            fig.add_scatter(x=[MESES[m - 1] for m in at.index.month], y=at.values, mode="markers", name=str(ano_f),
                            marker=dict(symbol="diamond", size=10, color=TINTA, line=dict(color=CARTAO, width=1)),
                            hovertemplate=f"{ano_f} · %{{x}}: %{{y:.2f}}<extra></extra>")
            layout(fig, 300, legenda=True)
            fig.update_xaxes(categoryorder="array", categoryarray=MESES)
            st.plotly_chart(fig, config=CFG, key="v_x_sazonal")

    funcs = {"outra": outra, "yoy": yoy, "mm": mm, "tendencia": tendencia, "indice": indice, "ranking": ranking,
             "sazonal": sazonal}
    for k in range(0, len(pedidas), 2):
        par = pedidas[k:k + 2]
        cols = st.columns(2) if len(par) == 2 else [st.container()]
        for col, cod in zip(cols, par):
            with col:
                funcs[cod]()


def pagina_desempenho():
    if BASE.empty:
        st.warning("A base mensal está vazia: falta o arquivo dados/tv_mensal.csv no repositório.")
        return
    # a faixa (6h ou 7h às 24h) é escolhida só no seletor acima das abas e entra sempre nos gráficos; aqui, só os programas
    faixa = faixa_atual()
    progs = [p for p in tv.PROGRAMAS if p in set(BASE["programa"]) and p not in diario.FAIXAS]
    f = st.columns([3.6, 1.2, 1.0, 2.2])
    ordem_do_arraste("p1_progs", "p1_ordem_txt", progs, nome_p)
    if "p1_progs" not in st.session_state:
        st.session_state["p1_progs"] = [p for p in PADRAO_P1 if p in progs]
    elif any(p not in progs for p in st.session_state["p1_progs"]):
        st.session_state["p1_progs"] = [p for p in st.session_state["p1_progs"] if p in progs]
    with f[0]:
        sel_progs = st.multiselect("Programas", progs, key="p1_progs", format_func=nome_p, placeholder="Escolha os programas",
                                   help=f"A faixa ({nome_p(faixa)}) vem do seletor \"Faixa horária de referência\", acima das abas, "
                                        "e aparece sempre nos gráficos. Arraste os quadros para mudar a ordem dos programas.")
        arrastar_selecionados("p1_progs", "p1_ordem_txt")
    sel = ([faixa] if faixa in set(BASE["programa"]) else []) + list(sel_progs)
    met = f[1].selectbox("Métrica", tv.METRICAS, key="p1_met", format_func=lambda m: f"{m} ({tv.SIGLA[m]})")
    serie_ = f[2].selectbox("Série", ["Mês", "Trimestre", "Ano"], key="p1_serie",
                            help="Trimestre e ano = média dos meses ponderada pelo número de exibições (como o acumulado oficial).")
    pers = _periodos(sel, met, serie_)
    if not pers:
        st.warning("Sem dados para a seleção.")
        return
    n_pad = {"Mês": 13, "Trimestre": 8, "Ano": len(pers)}[serie_]
    p0, p1 = f[3].select_slider("Período", options=pers, value=(pers[max(0, len(pers) - n_pad)], pers[-1]),
                                format_func=lambda x: _rot_per(x, serie_), key=f"p1_per_{serie_}")
    periodos = [x for x in pers if p0 <= x <= p1]
    st.session_state["_filtros_txt"] = (f"Faixa: {nome_p(faixa)} · Programas: {', '.join(nome_p(p) for p in sel_progs) or 'nenhum'} · "
                                        f"Métrica: {met.lower()} · "
                                        f"Série: {serie_.lower()} · Período: {_rot_per(p0, serie_)} a {_rot_per(p1, serie_)}")

    # ---- KPIs: último mês e média do ano (parcial) de cada programa selecionado
    ult = BASE["mes"].max()
    ano = ult.year
    lista = []
    for p in sel:
        s = serie(p, met)
        v = s.get(ult, np.nan)
        ant, aa = s.get(ult - pd.DateOffset(months=1), np.nan), s.get(ult - pd.DateOffset(years=1), np.nan)
        cor = COR_PROG.get(p, CINZA)
        lista.append((f"{nome_p(p)} · {rot_mes(ult)}", br(v),
                      f"{_dpt(v, ant)} vs mês anterior ({rot_mes(ult - pd.DateOffset(months=1))})<br>"
                      f"{_dpt(v, aa)} vs mesmo mês do ano anterior ({rot_mes(ult - pd.DateOffset(years=1))})", cor))
        m1, n1 = media_parcial(p, met, ano, ult.month)
        m0, _ = media_parcial(p, met, ano - 1, ult.month)
        parcial = ult.month < 12
        lista.append((f"{nome_p(p)} · média {ano}" + (f" (jan–{tv.MESES[ult.month - 1]})" if parcial else ""), br(m1),
                      ("média parcial" if parcial else "média do ano") + f" de {ano} · {_dpt(m1, m0)} vs " +
                      (f"média parcial de {ano - 1} (mesmo período)" if parcial else f"média de {ano - 1}"), cor))
    kpis(lista)

    if mostra("evolucao"):
        # ---- evolução
        nome_s = {"Mês": "mês", "Trimestre": "trimestre", "Ano": "ano"}[serie_]
        with cartao(f"Evolução por {nome_s} · {met.lower()}", f"{tv.SIGLA[met]} · {_rot_per(p0, serie_)} a {_rot_per(p1, serie_)}"):
            rot = [_rot_per(x, serie_) for x in periodos]
            fig = go.Figure()
            n_barras = len(periodos) * len(sel)
            for p in sel:
                vals = [_valor_per(p, met, x, serie_) for x in periodos]
                v = [a for a, _ in vals]
                info = [("ano incompleto: " + str(n) + " meses" if serie_ == "Ano" and 0 < n < 12 else "") for _, n in vals]
                fig.add_bar(x=rot, y=v, name=nome_p(p), marker_color=COR_PROG.get(p, CINZA),
                            text=[br(x, 1) for x in v] if n_barras <= 40 else None, textposition="outside",
                            textfont=dict(size=9), cliponaxis=False, customdata=info,
                            hovertemplate=f"<b>{nome_p(p)}</b> · %{{x}}: %{{y:.2f}} %{{customdata}}<extra></extra>")
            layout(fig, 340, legenda=True).update_layout(barmode="group", bargap=.22, bargroupgap=.06)
            if len(periodos) > 8:
                fig.update_xaxes(tickangle=-45, tickfont=dict(size=10))
            st.plotly_chart(fig, config=CFG, key="v_evol")

    # ---- desempenho do último mês (todas as séries) + média anual (cada um pode ser tirado no rodapé)
    _cd, _ca = _dupla(mostra("desempenho"), mostra("anual"), (1.1, 1))
    if mostra("desempenho"):
        with _cd, cartao(f"Desempenho · {rot_mes(ult)}", f"todos os programas · selecionados em destaque"):
            m_ant, m_aa = ult - pd.DateOffset(months=1), ult - pd.DateOffset(years=1)

            def _d(a, b):
                if pd.isna(a) or pd.isna(b):
                    return "<td class='n' style='color:#8a8984'>–</td>"
                return f"<td class='n' style='color:{SOBE if a > b else DESCE}'>{sinal(a - b)}</td>"
            linhas = ""
            for p in progs:
                cel = ""
                for m in tv.METRICAS:
                    s = serie(p, m)
                    v = s.get(ult, np.nan)
                    cel += f"<td class='n'><b>{br(v)}</b></td>" + _d(v, s.get(m_ant, np.nan)) + _d(v, s.get(m_aa, np.nan))
                estilo = f" style='background:{REALCE}'" if p in sel else ""
                linhas += (f"<tr{estilo}><td><span style='color:{COR_PROG.get(p, CINZA)}'>■</span> "
                           f"{'<b>' + nome_p(p) + '</b>' if p in sel else nome_p(p)}</td>{cel}</tr>")
            st.markdown(f"<div style='overflow-x:auto'><table class='rk'><tr><th></th><th class='n'>Aud.</th>"
                        f"<th class='n'>Δ mês ant.<br>{rot_mes(m_ant)}</th><th class='n'>Δ ano ant.<br>{rot_mes(m_aa)}</th>"
                        f"<th class='n'>Share</th><th class='n'>Δ mês ant.<br>{rot_mes(m_ant)}</th><th class='n'>Δ ano ant.<br>{rot_mes(m_aa)}</th></tr>"
                        f"{linhas}</table></div>", unsafe_allow_html=True)
    if mostra("anual"):
        with _ca, cartao(f"Média anual · {met.lower()}", "média ponderada pelas exibições · barra clara = ano incompleto"):
            fig = go.Figure()
            for p in sel:
                ma = tv.media_anual(serie(p, met), p)
                ma = ma[ma.index >= 2020]
                fig.add_bar(x=[str(a) for a in ma.index], y=ma["media"], name=nome_p(p),
                            marker=dict(color=COR_PROG.get(p, CINZA), opacity=[1 if n == 12 else .5 for n in ma["meses"]]),
                            customdata=[f"{n} meses" + (" · ano incompleto" if n < 12 else "") for n in ma["meses"]],
                            hovertemplate=f"<b>{nome_p(p)}</b> · %{{x}}: %{{y:.2f}} (%{{customdata}})<extra></extra>")
            layout(fig, 300, legenda=True).update_layout(barmode="group", bargap=.25, bargroupgap=.05)
            fig.update_xaxes(type="category", categoryorder="category ascending")
            st.plotly_chart(fig, config=CFG, key="v_media_anual")

    # ---- programa em foco
    if mostra("curva") or mostra("calor") or mostra("sazonal"):
        foco = st.segmented_control("Programa em foco nos gráficos abaixo", sel, default=sel[0], format_func=nome_p,
                                    key="p1_foco_" + "_".join(sel)) or sel[0]
    else:
        foco = sel[0]
    _estado_foco(foco, met, progs)
    ss = st.session_state
    _cc, _cm = _dupla(mostra("curva"), mostra("calor"), (1, 1))
    if mostra("curva"):
        with _cc:
            anos_c = ss.get("cv_anos") or [ano, ano - 1]
            with cartao(f"Curva do ano · {nome_p(ss['cv_prog'])}",
                        f"{ss['cv_met'].lower()} · " + " vs ".join(str(a) for a in sorted(anos_c, reverse=True))):
                if st.button("", icon=":material/open_in_full:", key="exp_curva", help="Expandir: mais anos, faixa e detalhes"):
                    janela_curva()
                fig, _, _ = fig_curva_tv(ss["cv_prog"], ss["cv_met"], anos_c, ss["cv_banda"], 300)
                st.plotly_chart(fig, config=CFG, key="v_curva")
    if mostra("calor"):
        with _cm:
            with cartao(f"Mapa de calor · {nome_p(ss['hm_prog'])}", f"{ss['hm_met'].lower()} · {MEDIDAS[ss['hm_med']]}"):
                if st.button("", icon=":material/open_in_full:", key="exp_calor", help="Expandir: filtros, valores e exportação"):
                    janela_calor()
                st.plotly_chart(fig_calor_tv(tabela_tv(ss["hm_prog"], ss["hm_met"], ss["hm_med"]), ss["hm_med"], 300),
                                config=CFG, key="v_calor")

    if mostra("comparativo"):
        # ---- comparativo em linhas
        with cartao(f"Comparativo · {met.lower()}", f"{_rot_per(p0, serie_)} a {_rot_per(p1, serie_)}"):
            rot = [_rot_per(x, serie_) for x in periodos]
            fig = go.Figure()
            un = {"Mês": "mês", "Trimestre": "trimestre", "Ano": "ano"}[serie_]
            for p in sel:
                v = np.array([_valor_per(p, met, x, serie_)[0] for x in periodos], float)
                if np.all(np.isnan(v)):
                    continue
                if serie_ == "Ano":
                    ant = [_valor_per(p, met, x - 1, serie_)[0] for x in periodos]
                    aa = [np.nan] * len(periodos)
                else:
                    passo = pd.DateOffset(months=1 if serie_ == "Mês" else 3)
                    ant = [_valor_per(p, met, x - passo, serie_)[0] for x in periodos]
                    aa = [_valor_per(p, met, x - pd.DateOffset(years=1), serie_)[0] for x in periodos]
                info = [("" if pd.isna(b) else f"<br>{sinal(a - b)} pt vs {un} anterior") +
                        ("" if pd.isna(c) else f"<br>{sinal(a - c)} pt vs mesmo {un} do ano anterior") for a, b, c in zip(v, ant, aa)]
                ok = np.where(~np.isnan(v))[0]
                ultimo = int(ok[-1])
                fig.add_scatter(x=rot, y=v, name=nome_p(p), mode="lines+markers+text", line=dict(color=COR_PROG.get(p, CINZA), width=2.5),
                                marker=dict(size=6), text=[br(x) if k == ultimo else "" for k, x in enumerate(v)],
                                textposition="middle right", textfont=dict(size=11, color=COR_PROG.get(p, CINZA)), customdata=info,
                                hovertemplate=f"<b>{nome_p(p)}</b> · %{{x}}: %{{y:.2f}}%{{customdata}}<extra></extra>")
            layout(fig, 320, legenda=True)
            fig.update_xaxes(tickangle=-45 if len(periodos) > 8 else 0, tickfont=dict(size=10), range=[-0.3, len(periodos) - 0.35])
            st.plotly_chart(fig, config=CFG, key="v_linhas")

    extras_tv(sel, met, serie_, periodos, p0, p1, foco, progs)
    st.markdown('<div class="rodape">Audiência (Rat%) e share (Shr%) · TT Domicílios · Grande Salvador · Kantar IBOPE (Instar). '
                'Δ em pontos (pt). Programas: média dos dias em que vão ao ar.</div>', unsafe_allow_html=True)


with paginas[0]:
    st.session_state["_aba_atual"] = "Visão geral"
    pagina_desempenho()


# =================================================================================== PÁGINA 3 · RESULTADOS DETALHADOS
def _cel_p(p):
    s = tv.semaforo(p)
    return f"<td class='n' style='background:{COR_SEM_CLARO[s]}'>{tv.fmt_p(p)}</td>"


def pagina_visao():
    if not R:
        secao(2, "Metas e projeções por programa", "modelo mensal")
        st.info("Nenhuma rodada do modelo mensal dos programas. Envie a planilha resultado_projecao_*.xlsx em ⚙ Atualizar dados (no rodapé).")
        return
    F = R["fech"]
    vs = R.get("vs")
    secao(2, "Metas e projeções por programa", f"modelo mensal · rodada com dados até {CORTE:%d/%m/%Y} · comparação com a rodada de {ANT}")
    lista, cards = [], ""
    progs = F.drop(index=tv.FAIXA, level=0, errors="ignore")
    grupos = {s_: [ix for ix, p in progs["p100"].items() if tv.semaforo(p) == s_] for s_ in COR_SEM if s_ != "–"}
    rot = {"Provável": "prováveis (≥ 80%)", "Indefinido": "indefinidas (20–80%)", "Improvável": "improváveis (< 20%)"}
    for s_, ixs in grupos.items():
        lista.append((f"Programas · {rot[s_]}", str(len(ixs)), f"de {len(progs)} metas 100% (audiência e share)", COR_SEM[s_]))
    n_tot = max(1, len(progs))
    seg = "".join(f'<i style="width:{len(ixs) / n_tot * 100:.1f}%; background:{COR_SEM[s_]}"></i>' for s_, ixs in grupos.items())
    nums = "".join(f'<div><b style="color:{COR_SEM[s_]}">{len(ixs)}</b>{rot[s_]}</div>' for s_, ixs in grupos.items())
    lst = (f'<div class="lst"><span style="color:{COR_SEM["Provável"]}">Prováveis:</span> {_lista(_agrupa(grupos["Provável"]))}<br>'
           f'<span style="color:{COR_SEM["Indefinido"]}">Em aberto:</span> {_lista(_agrupa(grupos["Indefinido"]))}<br>'
           f'<span style="color:{COR_SEM["Improvável"]}">Improváveis:</span> {_lista(_agrupa(grupos["Improvável"]))}</div>')
    cards += (f'<div class="gcard resumo" style="--c:{AZUL}; display:block"><div class="gtxt"><div class="gk">Programas · '
              f'{len(progs)} metas 100% (audiência e share)</div><div class="seg">{seg}</div><div class="gnum">{nums}</div>{lst}'
              f'</div></div>')
    _registra_kpis(lista)
    st.markdown(f'<div class="hero">{cards}</div>', unsafe_allow_html=True)

    # ---- painel da meta 100%
    with cartao("Painel da meta 100%", f"chance de fechar {ANO} na meta 100% · barra = fechamento projetado em % da meta · "
                                       f"variação vs rodada de {ANT}"):
        blocos = ""
        for prog in [p for p in tv.PROGRAMAS if p in F.index.get_level_values(0)]:
            cel = ""
            for met in tv.METRICAS:
                if (prog, met) not in F.index:
                    continue
                p = F.loc[(prog, met), "p100"]
                s = tv.semaforo(p)
                d = dpp(vs.loc[(prog, met), "dp"]) if vs is not None and (prog, met) in vs.index else ""
                pm = F.loc[(prog, met), "fech"] / F.loc[(prog, met), "meta100"] * 100
                cel += (f'<div class="c" style="background:{COR_SEM[s]}" title="fecha em {br(F.loc[(prog, met), "fech"])} · '
                        f'meta {br(F.loc[(prog, met), "meta100"])}"><div class="m">{met}</div>'
                        f'<div class="p">{tv.fmt_p(p)}</div><div class="bar"><i style="width:{min(pm, 115) / 1.15:.0f}%"></i></div>'
                        f'<div class="x">{br(pm, 1)}% da meta{" · " + d if d else ""}</div></div>')
            blocos += f'<div class="pg"><div class="n">{nome_p(prog)} <span>· {tv.DIAS_TXT.get(prog, "")}</span></div><div class="par">{cel}</div></div>'
        st.markdown(f'<div class="painel">{blocos}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="rodape">Verde ≥ 80% · amarelo 20–80% · vermelho &lt; 20%</div>', unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1, cartao("Fechamento projetado em % da meta 100%", "acima de 100% = meta atingida no cenário central"):
        fig = go.Figure()
        ordem = [p for p in tv.PROGRAMAS if p in F.index.get_level_values(0)][::-1]
        for i, met in enumerate(tv.METRICAS):
            v = [F.loc[(p, met), "fech"] / F.loc[(p, met), "meta100"] * 100 if (p, met) in F.index else np.nan for p in ordem]
            sem = [tv.semaforo(F.loc[(p, met), "p100"]) if (p, met) in F.index else "–" for p in ordem]
            fig.add_bar(y=ordem, x=v, orientation="h", name=met, xaxis=f"x{i + 1 if i else ''}",
                        marker_color=[COR_SEM[s] for s in sem], text=[f"{br(x, 1)}%" for x in v], textposition="outside",
                        textfont=dict(size=10), cliponaxis=False,
                        customdata=[[tv.fmt_p(F.loc[(p, met), 'p100']), br(F.loc[(p, met), 'fech']), br(F.loc[(p, met), 'meta100'])]
                                    if (p, met) in F.index else ["", "", ""] for p in ordem],
                        hovertemplate="<b>%{y} · " + met + "</b><br>fechamento %{customdata[1]} · meta %{customdata[2]}"
                                      "<br>%{x:.1f}% da meta · chance %{customdata[0]}<extra></extra>")
        lo = min(90, np.nanmin([F["fech"] / F["meta100"] * 100]) - 2)
        layout(fig, 400).update_layout(
            xaxis=dict(domain=[0, .47], range=[lo, 115], ticksuffix="%", title_text="Audiência", title_font=dict(size=11)),
            xaxis2=dict(domain=[.53, 1], range=[lo, 115], ticksuffix="%", title_text="Share", title_font=dict(size=11),
                        showgrid=False, linecolor=EIXO, tickfont=dict(size=11)),
            bargap=.35)
        for ax in ("x", "x2"):
            fig.add_shape(type="line", xref=ax, yref="paper", x0=100, x1=100, y0=0, y1=1, line=dict(color=TINTA, width=1, dash="dot"))
        fig.update_yaxes(tickfont=dict(size=11))
        fig.update_xaxes(tickformat=".0f", gridcolor=GRADE, showgrid=True)
        st.plotly_chart(fig, config=CFG, key="v_pct_meta")

    with c2, cartao(f"O que mudou desde {ANT}", "chance da meta 100% · rodada anterior → agora"):
        if vs is None:
            st.info("A planilha desta rodada não traz a comparação com a rodada anterior.")
        else:
            v = vs.reindex([(p, m) for p in tv.PROGRAMAS for m in tv.METRICAS if (p, m) in vs.index])[::-1]
            rot_y = [f"{p} · {'aud.' if m == 'Audiência' else 'share'}" for p, m in v.index]
            fig = go.Figure()
            for x0, x1, cor in [(0, 20, "rgba(198,40,40,.07)"), (20, 80, "rgba(245,166,35,.09)"), (80, 100, "rgba(46,125,50,.08)")]:
                fig.add_vrect(x0=x0, x1=x1, fillcolor=cor, line_width=0, layer="below")
            for y, a, b in zip(rot_y, v["p_ant"] * 100, v["p"] * 100):
                fig.add_scatter(x=[a, b], y=[y, y], mode="lines", line=dict(color=CINZA_CLARO, width=2), hoverinfo="skip", showlegend=False)
            fig.add_scatter(x=v["p_ant"] * 100, y=rot_y, mode="markers", name=f"rodada de {ANT}",
                            marker=dict(size=8, color=CARTAO, line=dict(color=CINZA, width=1.5)),
                            hovertemplate="%{y}<br>" + ANT + ": %{x:.1f}%<extra></extra>")
            fig.add_scatter(x=v["p"] * 100, y=rot_y, mode="markers", name="agora",
                            marker=dict(size=10, color=[COR_SEM[tv.semaforo(p)] for p in v["p"]],
                                        symbol=["star" if str(m).upper().startswith("MUDOU") else "circle" for m in v.get("mudou", [""] * len(v))]),
                            customdata=[dpp(x) for x in v["dp"]],
                            hovertemplate="%{y}<br>agora: %{x:.1f}% (%{customdata})<extra></extra>")
            layout(fig, 400, legenda=True).update_xaxes(range=[-2, 102], ticksuffix="%", showgrid=True, gridcolor=GRADE,
                                                         tickvals=[0, 20, 50, 80, 100])
            fig.update_yaxes(tickfont=dict(size=10))
            st.plotly_chart(fig, config=CFG, key="v_mudou")
            mud = [f"{p} ({'aud.' if m == 'Audiência' else 'share'})" for (p, m), x in vs["mudou"].items()
                   if str(x).upper().startswith("MUDOU")] if "mudou" in vs else []
            if mud:
                st.markdown(f'<div class="rodape">★ trocou de cor: {_lista(mud)}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="rodape">Fonte: Kantar IBOPE (Instar) · TT Domicílios · Grande Salvador · metas do BI. '
                f'Chance = parcela dos cenários simulados (Monte Carlo) em que o fechamento do ano fica na meta ou acima.</div>',
                unsafe_allow_html=True)


def _exib(prog, met):
    """(exibições até o corte, exibições em cada mês restante) — da planilha da rodada ou pelo calendário."""
    meses = list(mensal_proj(prog, met).index)
    try:
        a = R["acum"].loc[(prog, met)]
        n = float(a[next(c for c in a.index if str(c).startswith("exib. até"))])
        w = [float(x) for x in str(a[next(c for c in a.index if str(c).startswith("exib.") and "/" in str(c) and "até" not in str(c))]).split("/")]
        if len(w) == len(meses):
            return n, np.array(w)
    except (KeyError, StopIteration, ValueError, TypeError):
        pass
    n = tv.n_exib(prog, pd.Timestamp(ANO, 1, 1), CORTE)
    return float(n), np.array([tv.n_exib(prog, m, m + pd.offsets.MonthEnd(0)) for m in meses], float)


def _nivel(v, r):
    for m, rot in [("meta120", "Meta 120%"), ("meta100", "Meta 100%"), ("meta75", "Meta 75%")]:
        if v >= r[m] - 1e-9:
            return rot
    return "abaixo da 75%"


def grafico_ano(prog, met, chave):
    r = linha(prog, met)
    s = serie(prog, met)
    atual = s[str(ANO)].dropna() if len(s) else s
    antes = s[str(ANO - 1)].dropna() if len(s) else s
    pm = mensal_proj(prog, met)
    cor = AZUL            # realizado em azul e projeção em laranja nas duas métricas (como na apresentação)
    fig = go.Figure()
    xm = lambda idx: [MESES[d.month - 1] for d in idx]   # noqa: E731
    if len(pm) and len(atual):
        x = xm([atual.index[-1]] + list(pm.index))
        base = [atual.iloc[-1]]
        fig.add_scatter(x=x + x[::-1], y=base + list(pm["s95"]) + (base + list(pm["i95"]))[::-1], fill="toself", mode="lines",
                        fillcolor="rgba(235,104,52,.12)", line=dict(width=0), name="faixa 95%", hoverinfo="skip")
        fig.add_scatter(x=x + x[::-1], y=base + list(pm["s80"]) + (base + list(pm["i80"]))[::-1], fill="toself", mode="lines",
                        fillcolor="rgba(235,104,52,.25)", line=dict(width=0), name="faixa 80%", hoverinfo="skip")
    if len(antes):
        fig.add_scatter(x=xm(antes.index), y=antes.values, mode="lines", name=str(ANO - 1),
                        line=dict(color=CINZA_CLARO, width=1.5, dash="dot"),
                        hovertemplate=f"{ANO - 1} · %{{x}}: %{{y:.2f}}<extra></extra>")
    bi = metas_bi(prog, met)
    if len(bi):
        bi = bi[bi.index.year == ANO]
        fig.add_scatter(x=xm(bi.index), y=bi.values, mode="lines+markers", name="meta mensal 100% (BI)",
                        line=dict(color=TINTA, width=1.2), marker=dict(symbol="square", size=6, color=TINTA),
                        hovertemplate="meta BI · %{x}: %{y:.2f}<extra></extra>")
    if len(atual):
        fig.add_scatter(x=xm(atual.index), y=atual.values, mode="lines+markers+text", name=f"realizado {ANO}",
                        line=dict(color=cor, width=2.5), marker=dict(size=7, color=cor),
                        text=[br(v, 1) for v in atual.values], textposition="top center", textfont=dict(size=10, color=cor),
                        hovertemplate=f"{ANO} · %{{x}}: %{{y:.2f}}<extra></extra>")
    if len(pm) and len(atual):
        x = xm([atual.index[-1]] + list(pm.index))
        fig.add_scatter(x=x, y=[atual.iloc[-1]] + list(pm["proj"]), mode="lines+markers+text", name="projeção",
                        line=dict(color=LARANJA, width=2, dash="dash"), marker=dict(size=[0] + [7] * len(pm), color=LARANJA),
                        text=[""] + [br(v, 2) for v in pm["proj"]], textposition="bottom center",
                        textfont=dict(size=10, color=LARANJA),
                        customdata=[["", ""]] + [[f"{br(a)}–{br(b)}", f"{br(c)}–{br(d)}"] for a, b, c, d in
                                                 zip(pm["i80"], pm["s80"], pm["i95"], pm["s95"])],
                        hovertemplate="projeção · %{x}: %{y:.2f}<br>faixa 80%: %{customdata[0]}<br>faixa 95%: %{customdata[1]}<extra></extra>")
    if r is not None and len(pm):
        xr = xm(pm.index)
        fig.add_scatter(x=xr, y=[r["nec100"]] * len(xr), mode="lines", name=f"média necessária p/ meta 100% ({br(r['nec100'])})",
                        line=dict(color="#c62828", width=1.5, dash="dash"),
                        hovertemplate=f"média necessária em {REST} para a meta 100%: {br(r['nec100'])}<extra></extra>")
    layout(fig, 340, legenda=True)
    fig.update_xaxes(categoryorder="array", categoryarray=MESES)
    fig.update_yaxes(tickformat=",.1f")
    st.plotly_chart(fig, config=CFG, key=chave)


def _chave_slug(txt):
    """Texto -> trecho seguro para chave de elemento ('Bom Dia Sábado' -> 'bom_dia_sabado')."""
    import re
    import unicodedata
    t = unicodedata.normalize("NFKD", str(txt)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")


def pagina_programas():
    if BASE.empty:
        st.warning("A base mensal está vazia: falta o arquivo dados/tv_mensal.csv no repositório. Suba a pasta dados/ "
                   "ou envie a planilha consolidada em ⚙ Atualizar dados (no rodapé).")
        return
    progs = [p for p in tv.PROGRAMAS if p in set(BASE["programa"])]
    if R:                       # a ficha mostra só faixas e programas que entram na projeção (o 7h às 24h fica de fora)
        progs = [p for p in progs if p in R["fech"].index.get_level_values(0)] or progs
    f = st.columns([2.2, 5])
    prog = st.segmented_control("Faixa ou programa", progs, default=progs[0], key="p2_prog", format_func=nome_p) or progs[0]
    st.markdown(f'<div class="vs" style="margin:-4px 0 6px">{nome_p(prog)} · {tv.DIAS_TXT.get(prog, "")}</div>', unsafe_allow_html=True)
    with st.container(key=f"ficha_{_chave_slug(prog)}"):        # novo programa = ficha nova: anel, números e linhas animam

        # ---- KPIs por métrica
        if R:
            lista, leituras, cards = [], [], ""
            for met in tv.METRICAS:
                r = linha(prog, met)
                if r is None:
                    continue
                sem = tv.semaforo(r["p100"])
                d, dl = "", ""
                vs = R.get("vs")
                if vs is not None and (prog, met) in vs.index:
                    dl = dpp(vs.loc[(prog, met), 'dp'])
                    d = f" · {dl} vs {ANT}"
                folga = r["proj_rest"] - r["nec100"]
                lista += [(f"{met} · acumulado até {CORTE:%d/%m}", br(r["acum"]), f"média de jan a {MESES[CORTE.month - 1]}/{ANO}", COR_MET[met]),
                          (f"{met} · fechamento {ANO}", br(r["fech"]), f"faixa 95%: {br(r['ic_inf'])}–{br(r['ic_sup'])}", COR_MET[met]),
                          (f"{met} · chance da meta 100% ({br(r['meta100'])})", tv.fmt_p(r["p100"]), f"{sem_html(sem)}{d}", COR_SEM[sem]),
                          (f"{met} · média necessária em {REST}", br(r["nec100"]),
                           f"projeção {br(r['proj_rest'])} · {'folga' if folga >= 0 else 'déficit'} de "
                           f"<span class='{'up' if folga >= 0 else 'down'}'>{sinal(folga)} pt</span>", COR_MET[met])]
                leituras.append(f"<b>{met}:</b> fecha em {br(r['fech'])} (faixa 95%: {br(r['ic_inf'])}–{br(r['ic_sup'])}); "
                                f"para a meta 100% ({br(r['meta100'])}) precisa de média {br(r['nec100'])} em {REST}, "
                                f"e a projeção é {br(r['proj_rest'])}. Chance: <b>{tv.fmt_p(r['p100'])}</b> ({sem.lower()}).")
                pct = max(0.0, min(100.0, float(r["p100"]) * 100))
                cor_f = SOBE if folga >= 0 else DESCE
                cards += (f'<div class="gcard" data-m="{met}" style="--c:{COR_SEM[sem]}"><div class="anel" style="--p:{pct:.1f}"><div class="meio">'
                          f'<div><div class="gv">{tv.fmt_p(r["p100"])}</div><div class="gl">chance da<br>meta 100%</div></div></div></div>'
                          f'<div class="gtxt"><div class="gk">{met} ({tv.SIGLA[met]}) · meta 100% = {br(r["meta100"])}</div>'
                          f'<div class="gf">fecha em <b>{br(r["fech"])}</b> <span style="color:{CINZA}; font-size:.78rem">'
                          f'({br(r["ic_inf"])}–{br(r["ic_sup"])})</span></div>'
                          f'<div>acumulado até {CORTE:%d/%m}: <b>{br(r["acum"])}</b></div>'
                          f'<div>{REST}: precisa de <b>{br(r["nec100"])}</b> · projeção <b>{br(r["proj_rest"])}</b> · '
                          f'<b style="color:{cor_f}">{"folga" if folga >= 0 else "déficit"} {sinal(folga)} pt</b></div>'
                          f'<div style="margin-top:6px"><span class="chip">{sem}</span>{(dl + " vs " + ANT) if dl else ""}</div></div></div>')
            _registra_kpis(lista)
            if cards:
                st.markdown(f'<div class="hero">{cards}</div>', unsafe_allow_html=True)

            # ---- gráficos do ano
            cols = st.columns(2)
            for col, met in zip(cols, tv.METRICAS):
                with col, cartao(f"{nome_p(prog)} · {met} ({tv.SIGLA[met]}) · {ANO}", f"realizado, projeção de {REST} e média necessária"):
                    grafico_ano(prog, met, f"v_ano_{met}")

            # ---- cenários de leitura rápida
            with cartao(f"Cenários de leitura rápida · se {REST} repetir…", "fechamento do ano em cada cenário e meta alcançada"):
                linhas = ""
                for met in tv.METRICAS:
                    r = linha(prog, met)
                    s = serie(prog, met)
                    if r is None or not len(s):
                        continue
                    atual = s[str(ANO)].dropna()
                    n, w = _exib(prog, met)
                    fech = lambda v: (r["acum"] * n + v * w.sum()) / (n + w.sum())   # noqa: E731
                    cen = [(f"pior mês de {ANO} ({rot_mes(atual.idxmin(), False)})", atual.min()),
                           (f"média de jan a {MESES[CORTE.month - 1]}", r["acum"]),
                           ("projeção (Combinação)", r["proj_rest"]),
                           (f"melhor mês de {ANO} ({rot_mes(atual.idxmax(), False)})", atual.max())]
                    for i, (rot, v) in enumerate(cen):
                        fv = fech(v)
                        nv = _nivel(fv, r)
                        corn = {"Meta 120%": COR_SEM["Provável"], "Meta 100%": COR_SEM["Provável"], "Meta 75%": COR_SEM["Indefinido"]}.get(nv, COR_SEM["Improvável"])
                        linhas += (f"<tr><td>{met if i == 0 else ''}</td><td>{rot}</td><td class='n'>{br(v)}</td>"
                                   f"<td class='n'><b>{br(fv)}</b></td><td style='color:{corn}; font-weight:600'>{nv}</td></tr>")
                st.markdown("<table class='rk'><tr><th>Métrica</th><th>Se a média de " + REST + " for…</th><th class='n'>média</th>"
                            "<th class='n'>fechamento</th><th>nível</th></tr>" + linhas + "</table>", unsafe_allow_html=True)
        else:
            st.info("Sem rodada de projeção carregada: o painel mostra só o histórico.")

def pagina_resultados():
    if not R:
        st.warning("Nenhuma rodada de projeção carregada.")
        return
    F = R["fech"]
    abas_r = st.tabs(["📋 Metas por programa", "🧪 Sensibilidade", "🎯 Acompanhamento do mês", "✅ Validação e backtest"])
    with abas_r[0]:
        met = st.segmented_control("Métrica", tv.METRICAS, default="Audiência", key="p3_met") or "Audiência"
        with cartao(f"Resultados detalhados · {met} ({tv.SIGLA[met]})",
                    f"acumulado até {CORTE:%d/%m}, fechamento projetado, média necessária e chance de cada meta"):
            linhas = ""
            for prog in tv.PROGRAMAS:
                if (prog, met) not in F.index:
                    continue
                r = F.loc[(prog, met)]
                linhas += (f"<tr><td><b>{prog}</b></td><td class='n'>{br(r['acum'])}</td>"
                           f"<td class='n'><b>{br(r['fech'])}</b> <span style='color:{CINZA}'>({br(r['ic_inf'])}–{br(r['ic_sup'])})</span></td>"
                           f"<td class='n'>{br(r['meta100'])}</td><td class='n'>{br(r['nec100'])}</td><td class='n'>{br(r['proj_rest'])}</td>"
                           + _cel_p(r["p75"]) + _cel_p(r["p100"]) + _cel_p(r["p120"]) + "</tr>")
            st.markdown(f"<div style='overflow-x:auto'><table class='rk'><tr><th>Faixa / programa</th><th class='n'>Acum. {CORTE:%d/%m}</th>"
                        f"<th class='n'>Fechamento (faixa 95%)</th><th class='n'>Meta 100%</th><th class='n'>Média nec. {REST}</th>"
                        f"<th class='n'>Média proj. {REST}</th><th class='n'>P(75%)</th><th class='n'>P(100%)</th><th class='n'>P(120%)</th></tr>"
                        f"{linhas}</table></div>", unsafe_allow_html=True)
            st.markdown('<div class="rodape">Verde ≥ 80% · amarelo 20–80% · vermelho &lt; 20%. Metas 75%, 100% e 120% do BI.</div>',
                        unsafe_allow_html=True)
    with abas_r[1]:
        # ---- sensibilidade
        sens = R.get("sens")
        if sens is not None:
            with cartao("Sensibilidade · chance da meta 100% mudando uma hipótese de cada vez",
                        "em vermelho: a hipótese muda a cor do semáforo"):
                cols = [c for c in sens.columns if c not in ("oficial", "p viés", "melhor individual") and "proj." not in str(c)]
                mostrar = st.toggle("Mostrar só as séries em que alguma hipótese muda a cor", value=False, key="p3_sens")
                linhas = ""
                for (prog, m), r in sens.iterrows():
                    of = r["oficial"]
                    muda = any(pd.notna(r[c]) and tv.semaforo(r[c]) != tv.semaforo(of) for c in cols)
                    if mostrar and not muda:
                        continue
                    cel = "".join(
                        "<td class='n' style='color:#8a8984'>—</td>" if pd.isna(r[c]) else
                        f"<td class='n' style='{'color:#c62828; font-weight:700' if tv.semaforo(r[c]) != tv.semaforo(of) else ''}'>{tv.fmt_p(r[c])}</td>"
                        for c in cols)
                    linhas += (f"<tr><td>{prog} · {'aud.' if m == 'Audiência' else 'share'}</td>"
                               f"<td class='n' style='background:{COR_SEM_CLARO[tv.semaforo(of)]}'><b>{tv.fmt_p(of)}</b></td>{cel}"
                               f"<td style='color:{CINZA}'>{r.get('melhor individual', '')}</td></tr>")
                cab = "".join(f"<th class='n'>{c}</th>" for c in cols)
                st.markdown(f"<div style='overflow-x:auto'><table class='rk'><tr><th>Série</th><th class='n'>Oficial</th>{cab}"
                            f"<th>Melhor modelo individual</th></tr>{linhas}</table></div>", unsafe_allow_html=True)
    with abas_r[2]:
        # ---- acompanhamento do último mês
        ac = R.get("acomp")
        c1, c2 = st.columns([3, 2])
        if ac is not None:
            mes_ac = R["meta"].get("mes_acomp", "último mês")
            col_proj = next((c for c in ac.columns if str(c).startswith("proj. ") and "pipeline" not in str(c)), None)
            with c1, cartao(f"{mes_ac.capitalize()}: projetado × realizado", "posição do realizado na distribuição projetada"):
                v = ac.reindex([(p, m) for p in tv.PROGRAMAS for m in tv.METRICAS if (p, m) in ac.index])[::-1]
                rot_y = [f"{p} · {'aud.' if m == 'Audiência' else 'share'}" for p, m in v.index]
                fig = go.Figure()
                fig.add_vrect(x0=2.5, x1=97.5, fillcolor="rgba(235,104,52,.10)", line_width=0, layer="below")
                fig.add_vrect(x0=10, x1=90, fillcolor="rgba(235,104,52,.16)", line_width=0, layer="below")
                fig.add_vline(x=50, line=dict(color=CINZA, width=1, dash="dot"))
                dentro = v["percentil"].between(.1, .9)
                fig.add_scatter(x=v["percentil"] * 100, y=rot_y, mode="markers",
                                marker=dict(size=10, color=[AZUL if d else "#c62828" for d in dentro]),
                                customdata=np.c_[[br(x) for x in v["realizado"]], [br(x) for x in v[col_proj]] if col_proj else [""] * len(v),
                                                 v["faixa 80%"].astype(str).str.replace(".", ","), v["posição"]],
                                hovertemplate="%{y}<br>realizado %{customdata[0]} · projetado %{customdata[1]}<br>faixa 80%: %{customdata[2]}"
                                              "<br>%{customdata[3]}<extra></extra>")
                layout(fig, 420).update_xaxes(range=[0, 100], ticksuffix="%", tickvals=[2.5, 10, 50, 90, 97.5], showgrid=False,
                                              title_text="percentil do realizado na projeção (faixa 80% = 10–90 · faixa 95% = 2,5–97,5)",
                                              title_font=dict(size=10))
                fig.update_yaxes(tickfont=dict(size=10))
                st.plotly_chart(fig, config=CFG, key="v_acomp")
            with c2:
                n = len(v)
                d80 = int(v["percentil"].between(.1, .9).sum())
                f95 = v[~v["percentil"].between(.025, .975)]
                kpis([("Dentro da faixa de 80%", f"{d80} de {n}", f"esperado ≈ {round(.8 * n)}", AZUL),
                      ("Fora da faixa de 95%", f"{len(f95)} de {n}",
                       (", ".join(f"{p} ({'aud.' if m == 'Audiência' else 'share'})" for p, m in f95.index) or "nenhuma") +
                       f" · esperado ≈ {max(1, round(.05 * n))}", "#c62828")])
                erro_col = next((c for c in ac.columns if str(c).startswith("erro")), None)
                if erro_col:
                    txt = []
                    for m in tv.METRICAS:
                        e = ac.xs(m, level=1)[erro_col]
                        txt.append(f"<b>{m}:</b> erro médio {sinal(e.mean())} · {int((e > 0).sum())} de {len(e)} acima do projetado")
                    st.markdown('<div class="leitura">' + "<br>".join(txt) + "</div>", unsafe_allow_html=True)
    with abas_r[3]:
        # ---- validação
        mae = R.get("mae")
        if mae is not None:
            with cartao("Validação · erro médio absoluto (pt)", "reprojeções do passado, até 3 meses à frente"):
                mods = [c for c in ["Combinação", "Média 12m", "ETS(A,N,A)", "Nível local + sazonal + eventos", "AR(1) + sazonal + eventos"] if c in mae]
                v = mae.reindex([(p, m) for p in tv.PROGRAMAS for m in tv.METRICAS if (p, m) in mae.index])
                linhas = ""
                for (p, m), r in v.iterrows():
                    melhor = min(mods, key=lambda c: r[c] if pd.notna(r[c]) else 1e9)
                    linhas += (f"<tr><td>{p} · {'aud.' if m == 'Audiência' else 'share'}</td>" +
                               "".join(f"<td class='n' style='{'font-weight:700; color:' + SOBE if c == melhor else ''}'>{br(r[c])}</td>" for c in mods) + "</tr>")
                curto = {"Combinação": "Comb.", "Média 12m": "Méd. 12m", "ETS(A,N,A)": "ETS", "Nível local + sazonal + eventos": "Nív. local",
                         "AR(1) + sazonal + eventos": "AR(1)"}
                st.markdown("<div style='overflow-x:auto; max-height:360px'><table class='rk'><tr><th>Série</th>" +
                            "".join(f"<th class='n' title='{c}'>{curto[c]}</th>" for c in mods) + f"</tr>{linhas}</table></div>",
                            unsafe_allow_html=True)
                st.markdown('<div class="rodape">Em verde, o menor erro da série.</div>', unsafe_allow_html=True)

        bt = R.get("backtest")
        if bt is not None:
            with cartao("Backtest do fechamento anual", f"o mesmo procedimento aplicado em {CORTE:%d/%m} de anos anteriores"):
                col_err = "erro"
                dentro = bt["dentro da margem?"].astype(str).str.lower().eq("sim")
                kpis([("Fechamentos dentro da margem", f"{int(dentro.sum())} de {len(bt)}", "margem = meia-largura da faixa 95% atual", SOBE),
                      ("Erro médio absoluto · audiência", br(bt.loc[bt["metrica"] == "Audiência", col_err].abs().mean()), "pt", AZUL),
                      ("Erro médio absoluto · share", br(bt.loc[bt["metrica"] == "Share", col_err].abs().mean()), "pt", LARANJA)])
                t = bt.copy()
                t["série"] = t["programa"] + " · " + t["metrica"].map({"Audiência": "aud.", "Share": "share"})
                t = t[["série", "ano", "acum. jan–set" if "acum. jan–set" in t else t.columns[3], "projetado", "realizado", "erro",
                       "meia-largura IC95 atual", "dentro da margem?"]]
                st.dataframe(t.style.format({c: "{:.2f}" for c in t.columns if t[c].dtype.kind == "f"}, decimal=","),
                             hide_index=True, width="stretch", height=300)


def pagina_diaria(faixa):
    rods, erros = carregar_diarias(_assinatura_diarias())
    lista = rods.get(faixa, [])
    secao(1, f"Faixa {faixa} · modelo diário",
          "combinação do modelo diário (regressão dinâmica dia a dia) com o modelo mensal · notebook da faixa")
    if not lista:
        st.info(f"Nenhuma rodada do **modelo diário** para a faixa **{faixa}**. Envie a planilha "
                f"`projecao_{ANO}_{faixa[0]}h24h_diario_AAAAMMDD.xlsx` em **⚙ Atualizar dados → Enviar uma rodada da projeção**.")
        return
    opcoes = [r["corte"] for r in lista]
    corte = st.selectbox("Rodada (dados até)", opcoes, format_func=lambda d: f"{d:%d/%m/%Y}", key=f"rd_{faixa}") if len(lista) > 1 else opcoes[0]
    r = next(x for x in lista if x["corte"] == corte)
    res, ano = r["res"], r["ano"] or ANO
    # ---- anéis: chance da meta 100% (audiência e share)
    cards, kp = "", []
    for met in ("Audiência", "Share"):
        if met not in res.index:
            continue
        x = res.loc[met]
        p = float(x.get("P(100%)", np.nan))
        sem = str(x.get("semáforo 100%", ""))
        cor = diario.semaforo_cor(sem)
        nec = x.get("média nec. 100% (dias restantes)")
        cards += (f'<div class="gcard" data-m="{met}" style="--c:{cor}"><div class="anel" style="--p:{max(0, min(100, p * 100)):.1f}"><div class="meio">'
                  f'<div><div class="gv">{tv.fmt_p(p)}</div><div class="gl">chance da<br>meta 100%</div></div></div></div>'
                  f'<div class="gtxt"><div class="gk">{faixa} · {met}</div>'
                  f'<div class="gf">fecha em <b>{br(x["fechamento"])}</b> <span style="color:{CINZA}; font-size:.78rem">'
                  f'({br(x["IC95 inf"])}–{br(x["IC95 sup"])})</span></div>'
                  f'<div>meta 100%: <b>{br(x["meta 100%"])}</b>' + (f' · precisa de <b>{br(nec)}</b> nos dias restantes' if pd.notna(nec) else "") +
                  f'</div><div>75%: {tv.fmt_p(x.get("P(75%)", np.nan))} · 120%: {tv.fmt_p(x.get("P(120%)", np.nan))}</div>'
                  f'<div style="margin-top:6px"><span class="chip">{sem}</span></div></div></div>')
        kp.append((f"{faixa} · {met} · chance da meta 100% (diário)", tv.fmt_p(p),
                   f"fechamento {br(x['fechamento'])} ({br(x['IC95 inf'])}–{br(x['IC95 sup'])}) · {sem}", cor))
    _registra_kpis(kp)
    st.markdown(f'<div class="hero">{cards}</div>', unsafe_allow_html=True)
    met = st.segmented_control("Métrica", ["Audiência", "Share"], default="Audiência", key=f"rdm_{faixa}") or "Audiência"
    col_s = "rat" if met == "Audiência" else "shr"
    c1, c2 = st.columns([1.2, 1])
    # ---- ano mês a mês: realizado + projeção com faixas
    with c1, cartao(f"{faixa} · {met} · {ano} mês a mês", f"realizado e projeção com faixas de 80% e 95% · rodada com dados até {corte:%d/%m/%Y}"):
        fig = go.Figure()
        serie = r["serie"]
        if serie is not None and col_s in serie:
            s_ = serie[serie.index.year == ano][col_s]
            fig.add_scatter(x=[rot_mes(m) for m in s_.index], y=s_.values, name=f"realizado {ano}", mode="lines+markers",
                            line=dict(color=COR_MET[met], width=2.6), hovertemplate="%{x}: %{y:.2f}<extra>realizado</extra>")
            s0 = serie[serie.index.year == ano - 1][col_s]
            fig.add_scatter(x=[rot_mes(m.replace(year=ano)) for m in s0.index], y=s0.values, name=str(ano - 1), mode="lines",
                            line=dict(color=CINZA, width=1.4, dash="dot"), hovertemplate="%{x}: %{y:.2f}<extra>" + str(ano - 1) + "</extra>")
        pm = r["mensal"][r["mensal"]["métrica"] == met].dropna(subset=["mes"])
        if len(pm):
            xs = [rot_mes(m) for m in pm["mes"]]
            for lo, hi, nome, alfa in (("IC95 inf", "IC95 sup", "faixa 95%", .12), ("IC80 inf", "IC80 sup", "faixa 80%", .22)):
                fig.add_scatter(x=xs, y=pm[hi], mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip")
                fig.add_scatter(x=xs, y=pm[lo], mode="lines", line=dict(width=0), fill="tonexty", name=nome,
                                fillcolor=f"rgba(235,104,52,{alfa})", hoverinfo="skip")
            fig.add_scatter(x=xs, y=pm["projeção"], name="projeção", mode="lines+markers", line=dict(color=LARANJA, width=2.4, dash="dash"),
                            hovertemplate="%{x}: %{y:.2f}<extra>projeção</extra>")
        if met in res.index:
            fig.add_hline(y=float(res.loc[met, "meta 100%"]), line=dict(color=TINTA2, dash="dot", width=1),
                          annotation_text=f"meta 100% · {br(res.loc[met, 'meta 100%'])}", annotation_position="top left")
        layout(fig, 330, legenda=True)
        fig.update_xaxes(categoryorder="array", categoryarray=[rot_mes(pd.Timestamp(ano, m, 1)) for m in range(1, 13)])
        st.plotly_chart(fig, config=CFG, key=f"v_rd_ano_{faixa}")
    # ---- caminho diário projetado
    with c2, cartao(f"{faixa} · {met} · dia a dia até dezembro", "projeção do modelo diário · fins de semana destacados"):
        d = r["diaria"]
        if col_s in d:
            fig = go.Figure()
            fim_sem = d.index.dayofweek >= 5
            fig.add_scatter(x=d.index, y=d[col_s], mode="lines", line=dict(color=COR_MET[met], width=1.6), name="projeção diária",
                            hovertemplate="%{x|%a %d/%m}: %{y:.2f}<extra></extra>")
            fig.add_scatter(x=d.index[fim_sem], y=d[col_s][fim_sem], mode="markers", name="sábado e domingo",
                            marker=dict(size=6, color=LARANJA), hovertemplate="%{x|%a %d/%m}: %{y:.2f}<extra>fim de semana</extra>")
            layout(fig, 330, legenda=True)
            st.plotly_chart(fig, config=CFG, key=f"v_rd_dia_{faixa}")
    # ---- composição da projeção, efeitos, dia da semana, validação
    c1, c2 = st.columns(2)
    comp = r["comp"]
    if comp is not None:
        sfx = "aud" if met == "Audiência" else "shr"
        cols = [c for c in ("dias realizados", f"parcial {sfx}", f"diário {sfx}", f"mensal {sfx}", f"comb {sfx}") if c in comp]
        with c1, cartao("Como a projeção de cada mês é montada", "dias já realizados + projeção do diário e do mensal · combinação = média dos dois"):
            t = comp[cols].copy()
            t.columns = [c.replace(f" {sfx}", "").replace("comb", "combinação") for c in cols]
            t.index.name = "mês"
            for c in t.columns:
                t[c] = [("" if pd.isna(v) else (f"{int(v)}" if c == "dias realizados" else br(v))) for v in t[c]]
            st.dataframe(t, width="stretch")
    ef = r["efeitos"]
    with c2:
        if ef is not None and "audiência (pts, aprox.)" in ef:
            e = ef["audiência (pts, aprox.)"].dropna().sort_values()
            with cartao("O que move a audiência", "efeito médio na audiência do dia, em pontos, estimado no modelo diário"):
                fig = go.Figure(go.Bar(y=[str(i) for i in e.index], x=e.values, orientation="h",
                                       marker_color=[SOBE if v > 0 else DESCE for v in e.values],
                                       text=[sinal(v, 2) for v in e.values], textposition="outside", cliponaxis=False,
                                       hovertemplate="<b>%{y}</b>: %{x:+.2f} pt<extra></extra>"))
                layout(fig, 70 + 26 * len(e))
                fig.update_xaxes(zeroline=True, zerolinecolor=EIXO)
                st.plotly_chart(fig, config=CFG, key=f"v_rd_ef_{faixa}")
    c1, c2 = st.columns(2)
    dsem = r["dsem"]
    with c1:
        if dsem is not None and "audiência (pts, aprox.)" in dsem:
            with cartao("Dia da semana", "efeito na audiência do dia vs segunda-feira, em pontos"):
                v = dsem["audiência (pts, aprox.)"]
                fig = go.Figure(go.Bar(x=["segunda"] + [str(i) for i in v.index], y=[0] + list(v.values),
                                       marker_color=[CINZA] + [SOBE if x > 0 else DESCE for x in v.values],
                                       hovertemplate="%{x}: %{y:+.2f} pt<extra></extra>"))
                layout(fig, 280)
                fig.update_yaxes(zeroline=True, zerolinecolor=EIXO)
                st.plotly_chart(fig, config=CFG, key=f"v_rd_dsem_{faixa}")
    val = r["val"]
    with c2:
        if val is not None and isinstance(val.index, pd.MultiIndex):
            col = f"{'aud' if met == 'Audiência' else 'shr'} |erro| médio"
            if col in val:
                t = val[col].unstack("modelo").reindex(list(dict.fromkeys(val.index.get_level_values(0))))
                with cartao("Validação · erro médio por horizonte", f"{met} · |erro| médio em pontos nos últimos meses (corte no mesmo dia do mês)"):
                    fig = go.Figure()
                    for mo, cor in (("mensal", CINZA_CLARO), ("diário", AZUL), ("comb", LARANJA)):
                        if mo in t:
                            fig.add_bar(x=[str(i) for i in t.index], y=t[mo].values, name="combinação" if mo == "comb" else mo, marker_color=cor,
                                        hovertemplate="%{x}: %{y:.3f} pt<extra>" + mo + "</extra>")
                    layout(fig, 280, legenda=True).update_layout(barmode="group")
                    st.plotly_chart(fig, config=CFG, key=f"v_rd_val_{faixa}")
    if r["cmp"] is not None and len(r["cmp"]):
        with cartao("Comparação com a rodada anterior", "projeção e chance antes e agora"):
            t = r["cmp"].copy()
            st.dataframe(t.map(lambda v: br(v) if isinstance(v, (int, float, np.floating)) and pd.notna(v) else v), width="stretch", hide_index=True)
    if erros:
        st.caption("Planilhas do modelo diário com problema: " + "; ".join(f"{k} ({v})" for k, v in erros.items()))


with paginas[1]:
    st.session_state["_aba_atual"] = "Projeções e metas"
    with st.container(key=f"diario_{_chave_slug(faixa_atual())}"):   # trocar a faixa remonta a seção (anima de novo)
        pagina_diaria(faixa_atual())                     # ① faixa escolhida: modelo diário
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    pagina_visao()                                       # ② a ④ programas: modelo mensal
    if R:
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        secao(3, "Ficha do programa", "acumulado, fechamento, chance e o que precisa acontecer até dezembro")
        pagina_programas()
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        secao(4, "Resultados detalhados dos programas", "tabelas, sensibilidade, acompanhamento do último mês e validação do método")
        pagina_resultados()


# =================================================================================== PÁGINA 5 · ATUALIZAR DADOS
@protegido("rodada_diaria.excluir", "tv_rodadas", detalhe=lambda nome, *a, **k: dict(recurso_id=nome))
def _excluir_rodada_diaria(nome):
    """Exclui uma rodada do modelo diário: no banco (tv_rodadas) ou, na demonstração, o arquivo da sessão."""
    if _banco_ativo():
        banco.excluir("tv_rodadas", nome_arquivo=nome)
    for pasta in (PASTA_DIARIAS, PASTA_RODADAS_BANCO):
        cam = os.path.join(pasta, os.path.basename(nome))
        if os.path.exists(cam):
            os.remove(cam)
    return nome


def _permissao_ok(chave=None):
    """Permissão para gravar (login corporativo, permissão "atualizar"). A negativa vai para a auditoria."""
    if pode_gravar():
        return True
    registra("painel.gravar", resultado="negado", recurso_tipo="painel", erro_codigo="sem_permissao_atualizar")
    return False


def _detalhe_gravacao(caminho, conteudo=None, msg=None, *a, **k):
    """Nome da ação na auditoria conforme o arquivo gravado."""
    nome = os.path.basename(str(caminho))
    if os.path.abspath(str(caminho)) == os.path.abspath(ARQ_PAR):
        return dict(acao="parametros.salvar", recurso_tipo="painel_parametros", recurso_id="tv", recurso_rotulo=msg)
    if nome.lower().endswith(".xlsx"):
        acao = "rodada_diaria.upload" if "diario" in nome.lower() else "rodada.upload"
        return dict(acao=acao, recurso_tipo="tv_rodadas", recurso_id=nome, recurso_rotulo=msg)
    return dict(acao="arquivo.salvar", recurso_tipo="arquivo", recurso_id=nome, recurso_rotulo=msg)


@protegido("arquivo.salvar", "arquivo", detalhe=_detalhe_gravacao)
def _gravar(caminho, conteudo, msg):
    """Grava no banco de dados (e na pasta de trabalho local). Devolve True/False, ou None na demonstração."""
    os.makedirs(os.path.dirname(caminho) or ".", exist_ok=True)
    with open(caminho, "wb") as fh:
        fh.write(conteudo)
    if MODO_DEMO:
        return None                                   # demonstração: vale só nesta sessão do app
    if _banco_ativo():
        try:
            if os.path.abspath(caminho) == os.path.abspath(ARQ_PAR):
                banco.salvar_parametros("tv", {k: v for k, v in json.loads(conteudo.decode("utf-8")).items() if k != "senha"})
            elif caminho.lower().endswith(".xlsx"):
                banco.gravar_rodada(os.path.basename(caminho), conteudo)
            return True
        except Exception as ex:
            st.session_state["msg_erro"] = f"Não consegui gravar no banco de dados ({ex.__class__.__name__})."
            return False
    return None


def _salvar_par(par, msg):
    _gravar(ARQ_PAR, json.dumps(par, ensure_ascii=False, indent=2).encode("utf-8"), msg)


@protegido("audiencia.upload", "tv_audiencia_mensal")
def _salvar_base(nova, descricao):
    os.makedirs("backups", exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if os.path.exists(ARQ_BASE):
        bk = os.path.join("backups", f"tv_mensal_{ts}.csv")
        shutil.copy(ARQ_BASE, bk)
    tv.gravar_base(nova, ARQ_BASE)
    _gravar(ARQ_BASE, open(ARQ_BASE, "rb").read(), f"Base mensal: {descricao}")
    par = dict(PAR)
    par["dados"] = {"descricao": descricao, "atualizado_em": datetime.now().strftime("%d/%m/%Y %H:%M")}
    _salvar_par(par, f"Parâmetros: {descricao}")


def _recarrega(msg):
    st.cache_data.clear()
    st.session_state["msg_ok"] = msg
    st.session_state["up_nonce"] = st.session_state.get("up_nonce", 0) + 1
    st.rerun()


def pagina_atualizar():
    for k, fn in (("msg_ok", st.success), ("msg_erro", st.error)):
        if st.session_state.get(k):
            fn(st.session_state.pop(k))
    N = st.session_state.get("up_nonce", 0)
    ult = BASE["mes"].max() if len(BASE) else None
    _cortes = {f: _corte_diario(f) for f in diario.FAIXAS}
    kpis([("Modelo diário", " · ".join(f"{f[:2]} {c:%d/%m}" for f, c in _cortes.items() if c is not None) or "–",
           "faixas · dados até, por faixa (6h e 7h às 24h)", TOPO),
          ("Modelo mensal", f"{CORTE:%d/%m/%Y}" if CORTE is not None else "–", f"programas · {ATIVA or 'nenhuma rodada'}", AZUL),
          ("Base mensal", rot_mes(ult) if ult is not None else "–",
           f"{BASE.groupby(['programa', 'metrica']).ngroups} séries · {PAR.get('dados', {}).get('descricao', '')}", AZUL),
          ("Onde fica salvo", "Banco de dados" if _banco_ativo() else "Só nesta sessão",
           "banco da empresa" if _banco_ativo() else "demonstração: perde-se quando o app reinicia", CINZA)])
    tem_senha = False                       # login corporativo: sem senha (a permissão vem do gateway)
    if MODO_DEMO:
        st.segmented_control("Simular perfil (só na demonstração)", list(PERFIS_DEMO), default="Pode atualizar",
                             key="perfil_demo", help="No Labs, quem é o usuário e o que ele pode fazer vem do login corporativo.")
    _u = usuario_atual()
    if not pode_gravar():
        quem = f"{_u.nome} ({_u.email})" if _u else "Usuário não identificado"
        st.warning(f"**{quem}** · Seu perfil permite apenas consulta: os dados aparecem normalmente, mas não é possível "
                   f"enviar planilhas nem alterar parâmetros. Para receber o acesso, fale com a TI.")
        return
    if _u:
        st.caption(f"Conectado como **{_u.nome}** ({_u.email}) · " + ("na demonstração, nada é gravado de verdade." if MODO_DEMO
                   else "as alterações feitas aqui ficam registradas na auditoria."))

    c1, c2 = st.columns(2)
    # ---- 1. nova rodada
    with c1, cartao("1 · Enviar uma rodada da projeção",
                    "faixas: a planilha do notebook diário (projecao_AAAA_6h24h_diario_AAAAMMDD.xlsx ou …_7h24h_…) · "
                    "programas: a planilha do notebook mensal (resultado_projecao_*.xlsx). O painel reconhece qual é qual."):
        up = st.file_uploader("Planilha de resultado", type=["xlsx"], key=f"up_rod_{N}",
                              help="modelo diário das faixas (projecao_2026_6h24h_diario_*.xlsx / …7h24h…) ou modelo mensal "
                                   "dos programas (resultado_projecao_*.xlsx)")
        if up is not None and diario.eh_rodada_diaria(up):
            try:
                rd = diario.ler_rodada_diaria(up, up.name)
                up.seek(0)
                x = rd["res"]
                st.markdown(f"<div class='leitura'>Modelo diário · <b>{rd['faixa']}</b> · dados até <b>{rd['corte']:%d/%m/%Y}</b><br>"
                            + "<br>".join(f"{m}: fechamento {br(x.loc[m, 'fechamento'])}, chance da meta 100% {tv.fmt_p(x.loc[m, 'P(100%)'])}"
                                          for m in x.index) + "</div>", unsafe_allow_html=True)
                if st.button("Salvar a rodada do modelo diário", type="primary", key="bt_rd"):
                    if not _permissao_ok("pw_rd"):
                        st.error("Seu perfil permite apenas consulta.")
                    else:
                        destino = os.path.join(PASTA_DIARIAS, os.path.basename(up.name))
                        _gravar(destino, up.getvalue(), f"Modelo diário {rd['faixa']} com dados até {rd['corte']:%d/%m/%Y}")
                        st.cache_data.clear()
                        st.session_state["msg_ok"] = f"Rodada do modelo diário ({rd['faixa']}) salva."
                        st.rerun()
            except Exception as ex:
                st.error(f"Não consegui ler a planilha do modelo diário: {ex}")
            up = None
        if up is not None:
            try:
                Rn = tv.ler_resultado(up)
                m = Rn["meta"]
                st.markdown(f"<div class='leitura'>Dados até <b>{m['corte']:%d/%m/%Y}</b> · projeção de <b>{m['meses_rest']}</b> · "
                            f"{len(_so_programas(Rn)['fech'])} séries de programas · comparação com a rodada de {m.get('anterior', '–')}"
                            + "</div>", unsafe_allow_html=True)
                destino = os.path.join(PASTA_RODADAS, f"rodada_{m['corte']:%Y-%m-%d}.xlsx")
                if os.path.exists(destino):
                    st.markdown(f"<div class='aviso'>Já existe uma rodada com dados até {m['corte']:%d/%m/%Y}: ela será substituída.</div>",
                                unsafe_allow_html=True)
                if st.button("Adicionar rodada", type="primary", key="bt_rod"):
                    if not _permissao_ok("pw_rod"):
                        st.error("Seu perfil permite apenas consulta.")
                    else:
                        _gravar(destino, up.getvalue(), f"Rodada da projeção com dados até {m['corte']:%d/%m/%Y}")
                        par = dict(PAR)
                        par["rodada_ativa"] = None          # volta a usar a mais recente
                        _salvar_par(par, "Rodada ativa: mais recente")
                        _recarrega(f"Rodada com dados até {m['corte']:%d/%m/%Y} adicionada e em uso.")
            except Exception as ex:
                st.error(f"Não consegui ler a planilha: {ex}")

    # ---- 2. dados mensais
    with c2, cartao("2 · Enviar dados mensais",
                    "a planilha consolidada do ano (ex.: prog_e_faixa_jan_a_set.xlsx): nome da faixa/programa na 1ª linha, "
                    "AUDIÊNCIA e SHARE na 2ª e o mês à esquerda de cada bloco. Meses revisados pela Kantar substituem os antigos. "
                    "Também aceita a planilha do Instar com a coluna Datas e Rat%/Shr% (uma aba por faixa, ex.: 07h às 24h)."):
        if _banco_ativo():
            st.info("**Dados mensais vindos do banco de dados da empresa**, carregados pela aplicação de carga da TI. "
                    "Aqui ficam só as rodadas da projeção, a rodada exibida e as metas mensais do BI.")
        else:
            up = st.file_uploader("Planilha consolidada", type=["xlsx"], key=f"up_mes_{N}")
            ano_up = st.number_input("Ano da planilha", min_value=2015, max_value=2100, value=int(ANO), step=1, key="ano_up")
            if up is not None:
                try:
                    novo, ign = tv.ler_consolidado(up, int(ano_up))
                    if novo.empty:                       # formato "Datas × Rat%/Shr%", uma aba por faixa (ex.: 07h às 24h)
                        up.seek(0)
                        novo, ign = tv.ler_por_datas(up), []
                    novo["origem"] = f"{up.name}"
                    if novo.empty:
                        st.error("Não encontrei meses nem programas conhecidos na planilha.")
                    else:
                        m, n, a = tv.mesclar(BASE, novo)
                        st.markdown(f"<div class='leitura'>{novo['programa'].nunique()} faixas/programas · meses de "
                                    f"{rot_mes(novo['mes'].min())} a {rot_mes(novo['mes'].max())} · <b>{len(n)}</b> valores novos · "
                                    f"<b>{len(a)}</b> alterados" + (f"<br>Ignorados (não são da Globo/TV Bahia): {', '.join(ign)}" if ign else "")
                                    + "</div>", unsafe_allow_html=True)
                        if len(a):
                            t = a[["programa", "metrica", "mes", "valor_ant", "valor"]].copy()
                            t["mes"] = t["mes"].map(rot_mes)
                            t["dif"] = t["valor"] - t["valor_ant"]
                            st.dataframe(t.rename(columns={"valor_ant": "antes", "valor": "agora"}).style.format(
                                {"antes": "{:.2f}", "agora": "{:.2f}", "dif": "{:+.2f}"}, decimal=","), hide_index=True,
                                width="stretch", height=min(40 + 35 * len(t), 240))
                        if st.button("Aplicar atualização", type="primary", key="bt_mes", disabled=not (len(n) or len(a))):
                            if not _permissao_ok("pw_mes"):
                                st.error("Seu perfil permite apenas consulta.")
                            else:
                                _salvar_base(m, f"upload {up.name}")
                                _recarrega(f"Base mensal atualizada: {len(n)} novos, {len(a)} alterados.")
                except Exception as ex:
                    st.error(f"Não consegui ler a planilha: {ex}")

        # ---- 3. rodadas

    with cartao("3 · Rodadas do modelo diário", "o painel mostra a mais recente de cada faixa; as anteriores podem ser escolhidas "
                "na aba Projeções e metas"):
        rods_d, erros_d = carregar_diarias(_assinatura_diarias())
        linhas = [{"Faixa": f, "Dados até": f"{r['corte']:%d/%m/%Y}" if r["corte"] is not None else "–", "Arquivo": r["nome"]}
                  for f in diario.FAIXAS for r in rods_d.get(f, [])]
        linhas += [{"Faixa": "erro de leitura", "Dados até": "", "Arquivo": f"{k} ({v[:60]})"} for k, v in erros_d.items()]
        if linhas:
            st.dataframe(pd.DataFrame(linhas), hide_index=True, width="stretch")
            nomes = [l["Arquivo"] for l in linhas if l["Faixa"] != "erro de leitura"]
            c = st.columns([2.4, 1])
            esc = c[0].selectbox("Rodada", nomes, key="rd_del_esc") if nomes else None
            if esc and c[1].button("Excluir esta rodada", key="bt_rd_del"):
                if not _permissao_ok("pw_rd_del"):
                    st.error("Seu perfil permite apenas consulta.")
                else:
                    _excluir_rodada_diaria(esc)
                    carregar_diarias.clear()
                    st.session_state["msg_ok"] = f"Rodada {esc} excluída."
                    st.rerun()
        else:
            st.markdown('<div class="vs">Nenhuma rodada do modelo diário ainda.</div>', unsafe_allow_html=True)

    with cartao("4 · Rodadas do modelo mensal (programas)", "escolha qual rodada os programas mostram ou exclua uma rodada"):
        linhas = []
        for nome in rodadas_disponiveis():
            nm = os.path.basename(nome)
            info = RODADAS.get(nm, {})
            if "erro" in info:
                linhas.append({"Arquivo": nm, "Dados até": "erro de leitura", "Projeção de": info["erro"][:60], "Séries": "", "Em uso": ""})
            else:
                mm = info.get("meta", {})
                linhas.append({"Arquivo": nm, "Dados até": f"{mm['corte']:%d/%m/%Y}" if mm.get("corte") is not None else "–",
                               "Projeção de": mm.get("meses_rest", ""), "Séries": len(info.get("fech", [])),
                               "Em uso": "✔" if nm == ATIVA else ""})
        if linhas:
            st.dataframe(pd.DataFrame(linhas), hide_index=True, width="stretch")
        ops = ["(mais recente, automático)"] + list(_ord)
        atual = PAR.get("rodada_ativa") if PAR.get("rodada_ativa") in _ord else ops[0]
        c = st.columns([2, 1, 1])
        esc = c[0].selectbox("Rodada exibida", ops, index=ops.index(atual), key="rod_esc")
        if c[1].button("Usar esta rodada", key="bt_rod_usar"):
            if not _permissao_ok("pw_rodg"):
                st.error("Seu perfil permite apenas consulta.")
            else:
                par = dict(PAR)
                par["rodada_ativa"] = None if esc.startswith("(") else esc
                _salvar_par(par, f"Rodada exibida: {esc}")
                _recarrega(f"O painel agora mostra: {esc}.")
        if c[2].button("Excluir esta rodada", key="bt_rod_del", disabled=esc.startswith("(")):
            if not _permissao_ok("pw_rodg"):
                st.error("Seu perfil permite apenas consulta.")
            else:
                cam = caminho_rodada(esc)
                os.remove(cam)
                registra("rodada.excluir", recurso_tipo="tv_rodadas", recurso_id=esc)
                if _banco_ativo():
                    banco.excluir("tv_rodadas", nome_arquivo=esc)
                if PAR.get("rodada_ativa") == esc:
                    par = dict(PAR)
                    par["rodada_ativa"] = None
                    _salvar_par(par, "Rodada exibida: mais recente")
                _recarrega(f"Rodada {esc} excluída.")

    c1, c2 = st.columns(2)
    # ---- 5. metas mensais do BI (programas)
    with c1, cartao("5 · Metas mensais do BI (programas)", "usadas só nos gráficos dos programas (os quadrados pretos); "
                    "as metas anuais vêm da rodada"):
        regs = [{"série": k, "mês": m, "meta": v} for k, d in PAR.get("metas_mensais_bi", {}).items() for m, v in d.items()]
        ops_s = [f"{p}|{m}" for p in tv.PROGRAMAS if p not in diario.FAIXAS for m in tv.METRICAS]
        ed = st.data_editor(pd.DataFrame(regs, columns=["série", "mês", "meta"]), num_rows="dynamic", hide_index=True,
                            width="stretch", key=f"ed_bi_{N}",
                            column_config={"série": st.column_config.SelectboxColumn("série", options=ops_s, required=True),
                                           "mês": st.column_config.TextColumn("mês (AAAA-MM)", required=True),
                                           "meta": st.column_config.NumberColumn("meta 100%", format="%.2f", required=True)})
        if st.button("Salvar metas mensais", key="bt_bi"):
            if not _permissao_ok("pw_bi"):
                st.error("Seu perfil permite apenas consulta.")
            else:
                novo = {}
                for _, r in ed.dropna().iterrows():
                    novo.setdefault(r["série"], {})[str(r["mês"])[:7]] = float(r["meta"])
                par = dict(PAR)
                par["metas_mensais_bi"] = novo
                _salvar_par(par, "Metas mensais do BI")
                _recarrega("Metas mensais salvas.")

    # ---- 6. versões anteriores
    with c2, cartao("6 · Versões anteriores da base mensal", "cada atualização guarda uma cópia da base anterior"):
        bks = sorted(glob.glob(os.path.join("backups", "tv_mensal_*.csv")), reverse=True)
        if not bks:
            st.markdown('<div class="vs">Nenhuma versão anterior ainda.</div>', unsafe_allow_html=True)
        else:
            rot = lambda b: datetime.strptime(os.path.basename(b)[10:25], "%Y%m%d_%H%M%S").strftime("%d/%m/%Y %H:%M:%S")  # noqa: E731
            b = st.selectbox("Versão", bks, format_func=rot, key="bk_sel")
            if st.button("Restaurar esta versão", key="bt_bk"):
                if not _permissao_ok("pw_bk"):
                    st.error("Seu perfil permite apenas consulta.")
                else:
                    _salvar_base(tv.ler_base(b), f"restaurada a versão de {rot(b)}")
                    _recarrega(f"Versão de {rot(b)} restaurada.")


# =================================================================================== relatório em PDF
st.session_state["_graf"] = st.session_state.get("_graf_run", [])
st.session_state["_kpis"] = st.session_state.get("_kpis_run", [])


@_dialogo("Exportar relatório em PDF")
def janela_pdf():
    import relatorio
    ss = st.session_state
    graf, kps = ss.get("_graf", []), ss.get("_kpis", [])
    titulo = st.text_input("Título do relatório", value="Painel de Audiência · TV", key="pdf_titulo")
    st.markdown('<div class="vs">Escolha o que entra no relatório. Os gráficos saem com os filtros que estão na tela agora.</div>',
                unsafe_allow_html=True)
    def _itens(aba, padrao, pref):
        """Caixas de seleção dos cartões e gráficos de uma aba. Devolve (gráficos marcados, cartões marcados)."""
        itens = [g for g in graf if g["aba"] == aba]
        blocos = [k for k in kps if k["aba"] == aba]
        gs, cs = [], []
        if blocos and st.checkbox("Cartões de indicadores", value=padrao, key=f"{pref}_k"):
            for b in blocos:
                cs += b["cartoes"]
        cols = st.columns(2)
        vistos = set()
        for i, g in enumerate(itens):
            if g["chave"] in vistos:
                continue
            vistos.add(g["chave"])
            if cols[i % 2].checkbox(g["titulo"] or g["chave"], value=padrao, key=f"{pref}_g_{g['chave']}"):
                gs.append(g)
        return gs, cs

    st.markdown("**Visão geral**")
    escolhidos, cartoes = _itens("Visão geral", True, "pdf_vg")
    proj_g, proj_c = [], []
    if any(g["aba"] == "Projeções e metas" for g in graf):
        st.markdown("**Projeções e metas**")
        if st.toggle("Incluir as projeções no relatório (entram nas últimas páginas)", value=False, key="pdf_proj"):
            proj_g, proj_c = _itens("Projeções e metas", True, "pdf_pj")
    c = st.columns([1.2, 1.4, 2])
    if c[0].button("Gerar PDF", type="primary", key="pdf_gerar", disabled=not (escolhidos or cartoes or proj_g or proj_c)):
        with st.spinner("Montando o relatório…"):
            ss["_pdf_bytes"] = relatorio.gera_pdf(
                [(g["titulo"], g["sub"], g["fig"]) for g in escolhidos], cartoes=cartoes, titulo=titulo,
                final={"titulo": "Projeções e metas", "cartoes": proj_c,
                       "graficos": [(g["titulo"], g["sub"], g["fig"]) for g in proj_g]} if (proj_g or proj_c) else None,
                subtitulo="Globo · TV Bahia · Faixa 6h às 24h e programas locais · TT Domicílios · Grande Salvador · Kantar IBOPE (Instar)",
                logo_b64=LOGO_B64, filtros=(("DEMONSTRAÇÃO · DADOS FICTÍCIOS · " if PAR.get("demo") else "") + ss.get("_filtros_txt", "")),
                marca="DADOS FICTÍCIOS" if PAR.get("demo") else None,
                fonte="Fonte: Kantar IBOPE (Instar) · relatório gerado pelo Painel de Audiência")
    if ss.get("_pdf_bytes"):
        c[1].download_button("⬇️ Baixar PDF", ss["_pdf_bytes"], file_name=f"painel_tv_{datetime.now():%Y%m%d_%H%M}.pdf",
                             mime="application/pdf", key="pdf_baixar", type="primary")
        c[2].markdown(f'<div class="vs" style="margin-top:8px">{len(escolhidos) + len(proj_g)} gráfico(s) · '
                      f'{len(cartoes) + len(proj_c)} cartão(ões)' + (" · projeções no fim" if (proj_g or proj_c) else "") + '</div>',
                      unsafe_allow_html=True)


if st.session_state.pop("_abrir_pdf", False):
    st.session_state.pop("_pdf_bytes", None)
    janela_pdf()

VERSAO_PAINEL = "10/11/2026 · Labs · cabeçalho animado"
st.session_state["_aba_atual"] = ""          # o que vem depois (rodapé, atualização) não entra no relatório
_rodape = st.container(key="notas")
with _rodape, st.expander("🧩 Visualizações da tela inicial"):
    st.markdown('<div class="vs">Marque o que deve aparecer na Visão geral. As padrão já vêm marcadas; para tirar uma '
                'visualização, basta desmarcar. A escolha fica no link da página.</div>', unsafe_allow_html=True)
    st.pills("Visualizações", list(VIS_TODAS), selection_mode="multi", default=st.session_state["vis_sel"], key="vis_w",
             format_func=lambda c: ("★ " if c in VIS_PADRAO else "＋ ") + VIS_TODAS[c], on_change=_guarda_vis,
             label_visibility="collapsed")
    if st.button("Voltar ao padrão", key="vis_padrao"):
        st.session_state["vis_sel"] = list(VIS_PADRAO)
        st.session_state.pop("vis_w", None)
        st.query_params.pop("vis", None)
        st.rerun()
    st.markdown('<div class="vs">★ padrão · ＋ visualização extra</div>', unsafe_allow_html=True)
_rodape.markdown(f'<div class="vs" style="margin:2px 0 0">Versão do painel: {VERSAO_PAINEL} · Streamlit {st.__version__}</div>',
                 unsafe_allow_html=True)
with _rodape, st.expander("⚙ Atualizar dados"):
    pagina_atualizar()


# =================================================================================== PÁGINA 6 · NOTAS
with _rodape, st.expander("ⓘ Notas metodológicas"):
    with cartao("Como ler o painel"):
        st.markdown(f"""
**Audiência (Rat%)** e **share (Shr%)** da Globo (TV Bahia), TT Domicílios, Grande Salvador, Kantar IBOPE (Instar).
A faixa é a **6h às 24h**; os programas usam a média dos dias em que vão ao ar ({", ".join(f"{p}: {d.lower()}" for p, d in tv.DIAS_TXT.items() if p != tv.FAIXA)}).

**Média do ano**: média dos meses ponderada pelo número de exibições de cada mês, a mesma conta do acumulado oficial
(no histórico, a diferença para a linha "ANO" oficial fica em centésimos).

**Chance da meta**: parcela dos cenários simulados em que o fechamento do ano fica na meta ou acima.
Semáforo da meta 100%: **muito provável** ≥ 90% · **provável** 66–90% · **indefinido** 33–66% · **improvável** 10–33% ·
**muito improvável** < 10%.

**Média necessária**: média que os dias que faltam precisam ter para o ano fechar exatamente na meta 100%.
Se ela está dentro da faixa da projeção, a meta está em jogo.
""")
    with cartao("Como a projeção é feita"):
        st.markdown("""
A projeção vem do notebook diário de cada faixa (o painel lê a planilha de resultado que ele exporta):

1. **Dados**: audiência e share **diários** de cada faixa (6h às 24h e 7h às 24h), do Instar; o ano é fechado somando os
   dias já realizados com a projeção dos dias que faltam.
2. **Modelo diário**: regressão dinâmica dia a dia, com dia da semana, feriados, jogos, horário eleitoral e Copa do Mundo.
3. **Combinação**: a projeção de cada mês combina o modelo diário com um modelo mensal da própria faixa (média dos dois).
4. **Validação**: reprojeções do passado com corte no mesmo dia do mês; o erro médio de cada horizonte aparece na aba.
5. **Probabilidade**: simulação de cenários que vira o fechamento do ano, as faixas de 80% e 95% e a chance de cada meta
   (75%, 100% e 120%), com o semáforo de cinco níveis.

Cada faixa tem o seu notebook (`notebooks/Projecao_2026_6h24h_diario.ipynb` e `…7h24h…`); o painel mostra a rodada mais
recente da faixa escolhida no seletor acima das abas.

**Programas** (modelo mensal, notebook `Projecao_2026_mensal_programas.ipynb`): série mensal desde 2020, janela depois da
quebra estrutural de 2022, efeitos de sazonalidade, Copa, horário eleitoral e mudanças de patamar ("degraus"),
combinação de 4 modelos (média de 12 meses, Holt-Winters, nível local e AR(1)), validação em 24 reprojeções do passado
e 200 mil cenários para a chance de cada meta. Semáforo dos programas: **provável** ≥ 80% · **indefinido** 20–80% ·
**improvável** < 20%. A **sensibilidade** refaz a chance mudando uma hipótese de cada vez.
""")
    with cartao("Atualização"):
        st.markdown("""
- **Nova rodada**: faixas, rode o notebook diário e envie `projecao_2026_6h24h_diario_AAAAMMDD.xlsx` (ou `…7h24h…`); programas, rode o notebook mensal e envie `resultado_projecao_*.xlsx`. As duas vão em **⚙ Atualizar dados**, no rodapé; o painel reconhece qual é qual e guarda as anteriores.
- **Dados mensais**: envie a planilha consolidada do ano. Meses novos entram na base; meses revisados substituem os antigos (e a versão anterior fica guardada).
- Tudo o que é enviado aqui fica gravado no banco de dados do painel e registrado na auditoria.
""")


# =================================================================================== ASSISTENTE (mini chat lateral)
# Fase 1: respostas prontas, calculadas com os dados do painel (chat.py), sem IA. A aba com a seta fica na borda
# esquerda da tela; o quadro desliza ao abrir e fechar. Tudo roda num fragmento: conversar não recarrega o painel.
_CHAT_CSS = """
<style>
.st-key-chat_aba {position:fixed !important; left:0; top:44vh; z-index:1000300; width:auto !important;
    transition:left .45s cubic-bezier(.2,.8,.2,1);}
.st-key-chat_aba [data-testid="stElementContainer"]:has(.chat-aberto) {display:none;}
.st-key-chat_aba button {width:34px; min-width:34px; height:48px; min-height:0; padding:0; border-radius:0 12px 12px 0;
    border:1px solid rgba(255,255,255,.18); border-left:none; color:#fff !important;
    background:linear-gradient(160deg, #2a78d6, #7b5cff); box-shadow:0 4px 16px rgba(42,120,214,.45);
    animation:chamar 4s ease-in-out infinite;}
.st-key-chat_aba button p {font-size:22px; font-weight:700; line-height:1; margin:0;}
.st-key-chat_aba button:hover {filter:brightness(1.12); width:40px;}
@keyframes chamar {{ 0%,100% {{box-shadow:0 4px 16px rgba(42,120,214,.45);}} 50% {{box-shadow:0 4px 26px rgba(123,92,255,.75);}} }}
.stApp:has(.chat-aberto) .st-key-chat_aba {left:min(384px, 94vw);}
.stApp:has(.chat-aberto) .st-key-chat_aba button {animation:none;}

.st-key-chat_painel {position:fixed !important; left:12px; top:92px; bottom:16px; z-index:1000250;
    width:min(372px, calc(94vw - 12px)) !important; padding:14px 14px 10px; border-radius:16px; gap:8px !important;
    background:__FUNDO__; border:1px solid __BORDA__; box-shadow:0 18px 50px rgba(0,0,0,.45);
    transform:translateX(calc(-100% - 40px)); visibility:hidden;
    transition:transform .45s cubic-bezier(.2,.8,.2,1), visibility 0s linear .45s;}
.stApp:has(.chat-aberto) .st-key-chat_painel {transform:none; visibility:visible;
    transition:transform .45s cubic-bezier(.2,.8,.2,1), visibility 0s;}
.st-key-chat_painel .chat-cab {display:flex; align-items:center; gap:10px; padding-bottom:8px; border-bottom:1px solid __BORDA__;}
.st-key-chat_painel .chat-ico {width:30px; height:30px; border-radius:9px; display:grid; place-items:center; font-size:16px;
    background:linear-gradient(160deg, #2a78d6, #7b5cff); color:#fff;}
.st-key-chat_painel .chat-tit {font-weight:700; font-size:.92rem; color:__TEXTO__;}
.st-key-chat_painel .chat-sub {font-size:.7rem; color:__SUAVE__;}
.st-key-chat_painel [data-testid="stElementContainer"]:has(.chat-msgs) {flex:1 1 0; min-height:0;}
.st-key-chat_painel [data-testid="stElementContainer"]:has(.chat-msgs) [data-testid="stMarkdown"],
.st-key-chat_painel [data-testid="stElementContainer"]:has(.chat-msgs) [data-testid="stMarkdownContainer"] {height:100%;}
.st-key-chat_painel .chat-msgs {height:100%; overflow-y:auto; padding:4px 2px; display:flex; flex-direction:column-reverse; gap:8px;}
.st-key-chat_sug {width:100% !important; max-width:100%; min-width:0;}
.st-key-chat_sug [data-testid="stButtonGroup"] {width:100%; min-width:0;}
.st-key-chat_sug div:has(> button) {flex-wrap:nowrap !important; overflow-x:auto; padding-bottom:4px; scrollbar-width:thin;}
.st-key-chat_sug button {flex:0 0 auto; white-space:nowrap;}
.st-key-chat_painel .msg {max-width:88%; padding:8px 11px; border-radius:12px; font-size:.8rem; line-height:1.45;
    animation:pop .25s ease-out both;}
.st-key-chat_painel .msg.bot {align-self:flex-start; background:__BOLHA__; color:__TEXTO__; border-top-left-radius:4px;}
.st-key-chat_painel .msg.eu {align-self:flex-end; background:#2a78d6; color:#fff; border-top-right-radius:4px;}
.st-key-chat_painel .msg .it {display:block; padding-left:12px; position:relative; margin-top:3px;}
.st-key-chat_painel .msg .it::before {content:"•"; position:absolute; left:2px; opacity:.7;}
.st-key-chat_painel [data-testid="stPills"] button {font-size:.7rem; padding:2px 9px; min-height:0;}
.st-key-chat_painel [data-testid="stChatInput"] textarea {font-size:.82rem;}
.st-key-chat_painel .msg .sub {display:block; padding-left:12px; margin-top:2px; opacity:.85; font-size:.76rem;}
.st-key-chat_painel [data-testid="stChatInput"] > div {background:__CAMPO__ !important; border-color:__BORDA__ !important;}
.st-key-chat_painel [data-testid="stChatInput"] textarea {color:__TEXTO__ !important; -webkit-text-fill-color:__TEXTO__;}
.st-key-chat_painel [data-testid="stChatInput"] textarea::placeholder {color:__SUAVE__ !important; -webkit-text-fill-color:__SUAVE__;}
@media (prefers-reduced-motion: reduce) {{ .st-key-chat_painel, .st-key-chat_aba {{transition:none !important;}} }}
</style>
""".replace("{{", "{").replace("}}", "}")
for _k, _v in {"__FUNDO__": "#111a2e" if ESCURO else "#ffffff", "__BORDA__": "#24324f" if ESCURO else "#dfe4ee",
               "__TEXTO__": "#e8edf7" if ESCURO else "#1d2433", "__SUAVE__": "#8f9bb5" if ESCURO else "#6b7385",
               "__BOLHA__": "#1b2742" if ESCURO else "#eef2f9",
               "__CAMPO__": "#0d1526" if ESCURO else "#ffffff"}.items():
    _CHAT_CSS = _CHAT_CSS.replace(_k, _v)
st.markdown(_CHAT_CSS, unsafe_allow_html=True)


def _chat_alterna():
    st.session_state["chat_aberto"] = not st.session_state.get("chat_aberto", False)


def _chat_pergunta(txt):
    txt = (txt or "").strip()
    if not txt:
        return
    msgs = st.session_state.setdefault("chat_msgs", [("bot", chat.BOAS_VINDAS)])
    try:
        resp = chat.responder(txt, BASE, R)
    except Exception:                 # uma pergunta com problema não derruba o painel
        resp = "Tive um problema para calcular essa resposta. Tente perguntar de outro jeito."
    msgs += [("eu", txt[:500]), ("bot", resp)]
    del msgs[1:-40]                   # guarda só as últimas mensagens da sessão


def _chat_digitou():
    _chat_pergunta(st.session_state.get("chat_txt"))


def _chat_sugestao():
    v = st.session_state.get("chat_sug")
    st.session_state["chat_sug"] = None
    _chat_pergunta(v)


@st.fragment
def assistente():
    aberto = st.session_state.get("chat_aberto", False)
    with st.container(key="chat_aba"):
        st.button("‹" if aberto else "›", key="chat_botao", on_click=_chat_alterna)
        if aberto:
            st.markdown('<span class="chat-aberto"></span>', unsafe_allow_html=True)
    with st.container(key="chat_painel"):
        msgs = st.session_state.setdefault("chat_msgs", [("bot", chat.BOAS_VINDAS)])
        bolhas = "".join(f'<div class="msg {q}">{chat.para_html(t)}</div>' for q, t in reversed(msgs))
        st.markdown('''<div class="chat-cab"><div class="chat-ico">💬</div><div><div class="chat-tit">Assistente do painel</div>
<div class="chat-sub">versão inicial · respostas prontas a partir dos dados do painel</div></div></div>''',
                    unsafe_allow_html=True)
        st.markdown(f'<div class="chat-msgs">{bolhas}</div>', unsafe_allow_html=True)
        st.pills("Sugestões", chat.SUGESTOES, key="chat_sug", on_change=_chat_sugestao, label_visibility="collapsed")
        st.chat_input("Pergunte sobre a audiência…", key="chat_txt", on_submit=_chat_digitou, max_chars=500)


assistente()
