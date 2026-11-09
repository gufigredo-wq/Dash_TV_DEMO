"""Testes automáticos do painel de TV, no cenário de produção do Labs: os dados vêm só do banco (PAINEL_DB_URL).

Cada execução monta um banco SQLite temporário com dados FICTÍCIOS (demo_dados.py + carga_banco.py); nenhum dado real é
usado e o repositório não precisa da pasta dados/.

    pip install -r requirements.txt pytest
    pytest testes -q
"""
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

# usuário de desenvolvimento com acesso total (fora do Labs, a biblioteca labs_streamlit usa LABS_DEV_USER_EMAIL)
os.environ.setdefault("LABS_DEV_USER_EMAIL", "testes@redebahia.com.br")
os.environ.pop("PAINEL_MODO", None)
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from streamlit.testing.v1 import AppTest  # noqa: E402

IGNORAR = shutil.ignore_patterns("cache_rodadas", "__pycache__", "testes", "dados", "demo_runtime", "backups",
                                 "parametros_tv.json", "MODO_DEMO")


@pytest.fixture(scope="session")
def app_banco():
    """Cópia do painel + banco SQLite carregado com dados fictícios. Devolve (caminho do app, PAINEL_DB_URL)."""
    d = tempfile.mkdtemp()
    app = os.path.join(d, "app")
    shutil.copytree(RAIZ, app, ignore=IGNORAR)
    import demo_dados
    demo_dados.gera(app)                                   # dados/ e parametros_tv.json fictícios, só para a carga
    import json
    arq_par = os.path.join(app, "parametros_tv.json")
    par = json.load(open(arq_par, encoding="utf-8"))
    par.pop("demo", None)                                  # no banco, como em produção (sem a faixa de demonstração)
    json.dump(par, open(arq_par, "w", encoding="utf-8"), ensure_ascii=False)
    url = f"sqlite:///{os.path.join(d, 'teste.db')}"
    r = subprocess.run([sys.executable, os.path.join(app, "carga_banco.py"), "--url", url, "--criar"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    shutil.rmtree(os.path.join(app, "dados"))               # o painel não pode depender de arquivos locais
    os.remove(os.path.join(app, "parametros_tv.json"))
    yield os.path.join(app, "streamlit_app.py"), url
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture(autouse=True)
def _ambiente_limpo():
    """Cada teste começa e termina com as mesmas variáveis de ambiente (as reexecuções do painel usam as do teste)."""
    chaves = ("PAINEL_DB_URL", "LABS_DEV_MODULOS", "LABS_DEV_USER_EMAIL")
    antes = {k: os.environ.get(k) for k in chaves}
    yield
    for k, v in antes.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _abre(app, url, modulos=None, email="testes@redebahia.com.br"):
    """Abre o painel com o banco `url` e o usuário de desenvolvimento dado (valem também para os at.run() seguintes)."""
    for k, v in {"PAINEL_DB_URL": url, "LABS_DEV_MODULOS": modulos, "LABS_DEV_USER_EMAIL": email}.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    at = AppTest.from_file(app, default_timeout=300)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


# ------------------------------------------------------------------------------------------------ painel
def test_abre_pelo_banco(app_banco):
    at = _abre(*app_banco)
    assert [t.label for t in at.tabs][:2] == ["Visão geral", "Projeções e metas"]
    abas = {g["aba"] for g in at.session_state["_graf"]}
    assert {"Visão geral", "Projeções e metas"} <= abas
    assert not any('class="demo"' in m.value for m in at.markdown)          # não é a demonstração


def test_series_e_modo_escuro(app_banco):
    at = _abre(*app_banco)
    for sv in ("Trimestre", "Ano"):
        at.selectbox(key="p1_serie").set_value(sv)
        at.run()
        assert not at.exception
    at.button(key="tema_btn").click()
    at.run()
    assert not at.exception and at.session_state["tema_escuro"] is True


def test_faixas_e_modelo_diario(app_banco):
    at = _abre(*app_banco)
    # a faixa vem só do seletor acima das abas: o campo da Visão geral tem só programas
    assert not any(p in ("6h às 24h", "7h às 24h") for p in at.session_state["p1_progs"])
    assert "Faixa: TV Bahia (6h às 24h)" in at.session_state["_filtros_txt"]
    assert any(g["chave"] == "v_rd_ano_6h às 24h" for g in at.session_state["_graf"])   # rodada diária veio do banco
    at.segmented_control(key="faixa_ref").set_value("7h às 24h")
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert "Faixa: TV Bahia (7h às 24h)" in at.session_state["_filtros_txt"]
    assert "6h às 24h" not in at.session_state["_filtros_txt"]
    assert any(g["chave"] == "v_rd_ano_7h às 24h" for g in at.session_state["_graf"])
    # Projeções: a faixa vem do modelo diário; os programas, do modelo mensal (sem a faixa, para não aparecer duas vezes)
    proj = [g for g in at.session_state["_graf"] if g["aba"] == "Projeções e metas"]
    assert any(g["chave"].startswith("v_rd_") for g in proj)
    mensal = [g for g in proj if not g["chave"].startswith("v_rd_")]
    assert mensal, "faltam as metas e projeções por programa"
    for g in mensal:
        assert "às 24h" not in g["fig"].to_json(), g["chave"]


def test_pdf(app_banco):
    import relatorio
    at = _abre(*app_banco)
    g = at.session_state["_graf"]
    b = relatorio.gera_pdf([(x["titulo"], x["sub"], x["fig"]) for x in g if x["aba"] == "Visão geral"],
                           cartoes=at.session_state["_kpis"][0]["cartoes"], titulo="teste")
    assert b.startswith(b"%PDF")


# ------------------------------------------------------------------------------------------------ banco indisponível
def test_sem_banco_configurado_mostra_nao_disponivel(app_banco):
    app, _ = app_banco
    os.environ.pop("PAINEL_DB_URL", None)
    at = AppTest.from_file(app, default_timeout=300)
    at.run()
    assert any("Não disponível" in e.value for e in at.error)
    assert not at.tabs                                    # não mostra nada de arquivos locais


def test_banco_fora_do_ar_mostra_nao_disponivel(app_banco):
    app, _ = app_banco
    at = _abre(app, "sqlite:////caminho/que/nao/existe/banco.db")
    assert any("Não disponível" in e.value for e in at.error)
    assert not at.tabs


# ------------------------------------------------------------------------------------------------ perfis de acesso
def test_perfil_so_consulta(app_banco):
    """Quem não tem a permissão 'atualizar' vê os dados, mas a área de atualização não oferece envio nem alteração."""
    at = _abre(*app_banco, modulos="acesso")
    assert any("Seu perfil permite apenas consulta" in w.value for w in at.warning)
    assert len(at.get("file_uploader")) == 0
    assert any(g["aba"] == "Visão geral" for g in at.session_state["_graf"])          # consulta continua normal


def test_perfil_com_permissao_de_atualizar(app_banco):
    at = _abre(*app_banco, modulos="atualizar")
    assert not any("Seu perfil permite apenas consulta" in w.value for w in at.warning)
    assert len(at.get("file_uploader")) >= 1


def test_sem_usuario_identificado_so_consulta(app_banco):
    at = _abre(*app_banco, email=None)
    assert any("Usuário não identificado" in w.value for w in at.warning)
    assert len(at.get("file_uploader")) == 0


# ------------------------------------------------------------------------------------------------ demonstração e leitores
def test_modo_demonstracao():
    """Com o arquivo MODO_DEMO, o painel gera os dados fictícios e não usa banco nem a pasta dados/."""
    with tempfile.TemporaryDirectory() as d:
        app = os.path.join(d, "app")
        shutil.copytree(RAIZ, app, ignore=IGNORAR)
        open(os.path.join(app, "MODO_DEMO"), "w").close()
        os.environ.pop("PAINEL_DB_URL", None)
        at = AppTest.from_file(os.path.join(app, "streamlit_app.py"), default_timeout=300)
        at.run()
        assert not at.exception, [e.value for e in at.exception]
        assert any('class="demo"' in m.value for m in at.markdown)
        assert any(g["chave"] == "v_rd_ano_6h às 24h" for g in at.session_state["_graf"])


def test_leitores_diarios():
    import openpyxl
    import diario
    import rodada_diaria_exemplo
    import tv
    with tempfile.TemporaryDirectory() as d:
        a = rodada_diaria_exemplo.gera(os.path.join(d, "projecao_2026_7h24h_diario_20261026.xlsx"), "7h às 24h")
        r = diario.ler_rodada_diaria(a)
        assert r["faixa"] == "7h às 24h" and str(r["corte"].date()) == "2026-10-26" and set(r["res"].index) == {"Audiência", "Share"}
        # exportação diária por programa no formato do Instar Analytics (aba Crosstab), com números fictícios
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Crosstab"
        ws.append(["Relatório fictício"])
        ws.append(["Nome Programa", "Data", "Rat%", "Shr%"])
        for prog in ("JORNAL DA MANHA", "BATV SS", "BATV SB"):
            for dia in range(1, 11):
                ws.append([prog, f"{dia:02d}/10/2026", 10 + dia / 10, 30 + dia / 5])
        arq = os.path.join(d, "instar.xlsx")
        wb.save(arq)
        p = diario.ler_instar_programas(arq, tv.NOME_PROG)
        assert set(p["programa"]) == {"Jornal da Manhã", "BATV"} and len(p) == 20
