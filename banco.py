"""Acesso ao banco de dados da empresa (opcional).

Quando há uma conexão configurada, os painéis leem a audiência, o demográfico, as rodadas de projeção e os parâmetros
do banco, carregados pela aplicação de carga da TI. Sem conexão, continuam lendo os arquivos do repositório (dados/).

Configuração (uma das duas):
    Secrets/arquivo .streamlit/secrets.toml:   [banco]
                                               url = "postgresql+psycopg://usuario:senha@servidor:5432/audiencia"
    Variável de ambiente:                      PAINEL_DB_URL=postgresql+psycopg://...

Qualquer banco aceito pelo SQLAlchemy funciona (PostgreSQL, SQL Server, MySQL, Oracle), com o driver correspondente
instalado (ex.: SQL Server: mssql+pyodbc://... com o ODBC Driver 18). As tabelas estão em TABELAS e em ESQUEMA_BANCO.md.
"""
import io
import json
import os
from datetime import datetime
from functools import lru_cache

import pandas as pd

# ------------------------------------------------------------------------------------------------ contrato das tabelas
TABELAS = {
    # audiência de rádio por banco (trimestre móvel) e emissora — EasyMedia, faixa 05h–05h
    "radio_audiencia": {
        "colunas": {"emissora": "texto(80)", "inicio": "data", "fim": "data", "opm": "número", "sht": "número",
                    "alcance": "número", "tmed": "texto(12)", "amostra_baixa": "booleano", "origem": "texto(200)",
                    "atualizado_em": "data e hora"},
        "chave": ["emissora", "fim"]},
    # demográfico do rádio: zonas (OPM#, AFIN%, ALCM#) e perfil (PS% por classe, idade e sexo)
    "radio_demografico": {
        "colunas": {"emissora": "texto(80)", "inicio": "data", "fim": "data", "faixa": "texto(8)", "tipo": "texto(12)",
                    "segmento": "texto(60)", "metrica": "texto(8)", "valor": "número", "amostra_baixa": "booleano",
                    "origem": "texto(200)", "atualizado_em": "data e hora"},
        "chave": ["emissora", "fim", "faixa", "tipo", "segmento", "metrica"]},
    # audiência mensal de TV por faixa/programa — Kantar IBOPE (Instar), TT Domicílios
    "tv_audiencia_mensal": {
        "colunas": {"programa": "texto(60)", "metrica": "texto(20)", "mes": "data", "valor": "número",
                    "origem": "texto(200)", "atualizado_em": "data e hora"},
        "chave": ["programa", "metrica", "mes"]},
    # audiência diária de TV por faixa ou programa (Instar Analytics): base dos modelos diários
    "tv_audiencia_diaria": {
        "colunas": {"programa": "texto(60)", "data": "data", "rat": "número", "shr": "número", "origem": "texto(200)",
                    "atualizado_em": "data e hora"},
        "chave": ["programa", "data"]},
    # rodadas da projeção de TV (modelo mensal e modelo diário de cada faixa): a planilha de resultado, guardada inteira
    "tv_rodadas": {
        "colunas": {"nome_arquivo": "texto(120)", "corte": "data", "conteudo": "binário", "atualizado_em": "data e hora"},
        "chave": ["nome_arquivo"]},
    # parâmetros editados nos painéis (números oficiais, previsão do BI, metas mensais, bancos excluídos, rodada ativa)
    "painel_parametros": {
        "colunas": {"painel": "texto(10)", "chave": "texto(60)", "valor": "texto longo (JSON)", "atualizado_em": "data e hora"},
        "chave": ["painel", "chave"]},
}


def url():
    """Endereço do banco: [banco] url nos Secrets ou a variável PAINEL_DB_URL. None = modo arquivos."""
    try:
        import streamlit as st
        u = st.secrets.get("banco", {}).get("url")
        if u:
            return str(u)
    except Exception:
        pass
    return os.environ.get("PAINEL_DB_URL") or None


def ativo():
    return bool(url())


@lru_cache(maxsize=4)
def _motor(endereco):
    from sqlalchemy import create_engine
    return create_engine(endereco, pool_pre_ping=True, future=True)


def motor():
    return _motor(url())


def _metadados():
    from sqlalchemy import Boolean, Column, Date, DateTime, Float, LargeBinary, MetaData, String, Table, Text
    tipos = {"texto(80)": String(80), "texto(12)": String(12), "texto(200)": String(200), "texto(8)": String(8),
             "texto(60)": String(60), "texto(20)": String(20), "texto(120)": String(120), "texto(10)": String(10),
             "data": Date, "data e hora": DateTime, "número": Float, "booleano": Boolean, "binário": LargeBinary,
             "texto longo (JSON)": Text}
    md = MetaData()
    for nome, t in TABELAS.items():
        Table(nome, md, *[Column(c, tipos[tp], primary_key=c in t["chave"], nullable=c not in t["chave"])
                          for c, tp in t["colunas"].items()])
    return md


def criar_tabelas():
    """Cria as tabelas que ainda não existem (não altera as existentes)."""
    _metadados().create_all(motor())


def ler(tabela, colunas=None):
    """Tabela inteira (ou só as colunas pedidas) como DataFrame."""
    from sqlalchemy import text
    cols = ", ".join(colunas) if colunas else "*"
    with motor().connect() as c:
        return pd.read_sql(text(f"SELECT {cols} FROM {tabela}"), c)


def assinatura(tabelas):
    """Muda quando o conteúdo das tabelas muda (data da última carga e nº de linhas): invalida o cache dos painéis."""
    from sqlalchemy import text
    out = []
    try:
        with motor().connect() as c:
            for t in tabelas:
                r = c.execute(text(f"SELECT COUNT(*), MAX(atualizado_em) FROM {t}")).fetchone()
                out.append((t, int(r[0] or 0), str(r[1])))
    except Exception as ex:                         # banco fora do ar: o painel avisa e mostra o que tiver em cache
        out.append(("erro", str(ex)[:120]))
    return tuple(out)


def gravar(tabela, df):
    """Grava (substitui) as linhas de `df` pela chave da tabela: apaga as chaves presentes e insere de novo, numa transação.
    Usado pelo script de carga e pelo painel para parâmetros e rodadas."""
    from sqlalchemy import and_, delete
    md = _metadados()
    t = md.tables[tabela]
    chave = TABELAS[tabela]["chave"]
    df = df.copy()
    df["atualizado_em"] = datetime.now()
    cols = [c for c in TABELAS[tabela]["colunas"] if c in df.columns]
    df = df[cols].drop_duplicates(chave, keep="last")
    linhas = df.astype(object).where(df.notna(), None).to_dict("records")
    with motor().begin() as c:
        for i in range(0, len(linhas), 500):
            lote = linhas[i:i + 500]
            for r in lote:
                c.execute(delete(t).where(and_(*[t.c[k] == r[k] for k in chave])))
            c.execute(t.insert(), lote)
    return len(linhas)


def excluir(tabela, **chave):
    """Apaga as linhas com a chave dada (ex.: excluir("tv_rodadas", nome_arquivo="rodada_2026-09-30.xlsx"))."""
    from sqlalchemy import and_, delete
    t = _metadados().tables[tabela]
    with motor().begin() as c:
        c.execute(delete(t).where(and_(*[t.c[k] == v for k, v in chave.items()])))


# ------------------------------------------------------------------------------------------------ atalhos dos painéis
def parametros(painel):
    """Parâmetros do painel ('radio' ou 'tv') como dicionário {chave: valor}."""
    try:
        d = ler("painel_parametros")
    except Exception:
        return {}
    d = d[d["painel"] == painel]
    out = {}
    for _, r in d.iterrows():
        try:
            out[r["chave"]] = json.loads(r["valor"])
        except (TypeError, ValueError):
            out[r["chave"]] = r["valor"]
    return out


def salvar_parametros(painel, par):
    """Grava cada chave do dicionário de parâmetros como uma linha (valor em JSON)."""
    linhas = [{"painel": painel, "chave": k, "valor": json.dumps(v, ensure_ascii=False, default=str)} for k, v in par.items()]
    return gravar("painel_parametros", pd.DataFrame(linhas)) if linhas else 0


def rodadas_para_pasta(pasta):
    """Copia as planilhas de rodada guardadas no banco para uma pasta local (o leitor de rodadas trabalha com arquivos)."""
    os.makedirs(pasta, exist_ok=True)
    try:
        d = ler("tv_rodadas", ["nome_arquivo", "conteudo"])
    except Exception:
        return []
    caminhos = []
    for _, r in d.iterrows():
        cam = os.path.join(pasta, os.path.basename(str(r["nome_arquivo"])))
        dados = r["conteudo"]
        dados = bytes(dados) if not isinstance(dados, bytes) else dados
        if not os.path.exists(cam) or os.path.getsize(cam) != len(dados):
            with open(cam, "wb") as f:
                f.write(dados)
        caminhos.append(cam)
    return caminhos


def gravar_rodada(nome_arquivo, conteudo, corte=None):
    return gravar("tv_rodadas", pd.DataFrame([{"nome_arquivo": nome_arquivo, "corte": corte, "conteudo": io.BytesIO(conteudo).getvalue()}]))
