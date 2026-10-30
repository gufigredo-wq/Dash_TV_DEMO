"""Modelo diário da TV (notebooks Projecao_2026_6h24h_diario e Projecao_2026_7h24h_diario): leitura da planilha de
resultado, uma por faixa (6h às 24h ou 7h às 24h) e por data de corte, e leitura da exportação diária por programa do
Instar Analytics (para a tabela tv_audiencia_diaria).

Planilha de resultado (saída do notebook, ex.: projecao_2026_6h24h_diario_20261026.xlsx), abas:
  fechamento_e_metas  uma linha por métrica: fechamento, IC80/IC95, metas 75/100/120%, P(meta), média necessária nos
                      dias restantes, semáforo (Muito provável … Muito improvável)
  projecao_mensal     métrica, mês, projeção, IC80/IC95
  componentes         por mês: dias realizados, parcial, diário, mensal e combinação (aud e shr)
  validacao           por horizonte e modelo: |erro| médio, viés, comparação com o mensal
  efeitos, dia_da_semana, vs_rodada_anterior, serie_mensal, projecao_diaria
"""
import glob
import os
import re
import unicodedata

import numpy as np
import pandas as pd

FAIXAS = ["6h às 24h", "7h às 24h"]
SEMAFORO_5 = ["Muito provável", "Provável", "Indefinido", "Improvável", "Muito improvável"]
_ABAS = {"fechamento_e_metas", "projecao_mensal", "projecao_diaria"}
MESES_PT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def _chave(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


def faixa_do_nome(nome):
    """'projecao_2026_7h24h_diario_20261026.xlsx' -> '7h às 24h' (None se o nome não disser)."""
    k = _chave(os.path.basename(str(nome)))
    if "7h24h" in k or "07h24h" in k or "07has24h" in k:
        return "7h às 24h"
    if "6h24h" in k or "06h24h" in k or "06has24h" in k:
        return "6h às 24h"
    return None


def eh_rodada_diaria(arq):
    """Planilha de resultado do modelo diário (tem as abas fechamento_e_metas, projecao_mensal e projecao_diaria)."""
    try:
        abas = set(pd.ExcelFile(arq).sheet_names)
        if hasattr(arq, "seek"):
            arq.seek(0)
        return _ABAS <= abas
    except Exception:
        if hasattr(arq, "seek"):
            arq.seek(0)
        return False


def _mes(txt):
    """'out/2026' -> Timestamp(2026-10-01)."""
    m = re.match(r"^\s*([a-zç]{3})\w*\s*/\s*(\d{4})", str(txt).lower())
    return pd.Timestamp(int(m[2]), MESES_PT.index(m[1][:3]) + 1, 1) if m and m[1][:3] in MESES_PT else pd.NaT


def ler_rodada_diaria(arq, nome=None):
    """Lê a planilha de resultado do modelo diário. Devolve um dicionário com faixa, corte e as tabelas."""
    nome = nome or (arq if isinstance(arq, str) else getattr(arq, "name", "arquivo"))
    x = pd.read_excel(arq, sheet_name=None)
    res = x["fechamento_e_metas"]
    res = res.set_index(res.columns[0])
    res.index = [str(i) for i in res.index]
    mensal = x["projecao_mensal"].copy()
    mensal["mes"] = mensal["mês"].map(_mes)
    diaria = x["projecao_diaria"].copy()
    diaria = diaria.set_index(diaria.columns[0])
    diaria.index = pd.to_datetime(diaria.index)
    serie = x.get("serie_mensal")
    if serie is not None:
        serie = serie.set_index(serie.columns[0])
        serie.index = pd.to_datetime(serie.index)
    comp = x.get("componentes")
    if comp is not None:
        comp = comp.set_index(comp.columns[0])
    val = x.get("validacao")
    if val is not None and {"horizonte", "modelo"} <= set(val.columns):
        val["horizonte"] = val["horizonte"].ffill()          # índice duplo vem com células mescladas
        val = val.set_index(["horizonte", "modelo"])
    ef = x.get("efeitos")
    if ef is not None:
        ef = ef.set_index(ef.columns[0])
    dsem = x.get("dia_da_semana")
    if dsem is not None:
        dsem = dsem.set_index(dsem.columns[0])
    corte = diaria.index.min() - pd.Timedelta(days=1) if len(diaria) else None
    m = re.search(r"(20\d{2})(\d{2})(\d{2})", os.path.basename(str(nome)))
    if m:
        corte = pd.Timestamp(int(m[1]), int(m[2]), int(m[3]))
    faixa = faixa_do_nome(nome) or "6h às 24h"
    return {"faixa": faixa, "corte": corte, "nome": os.path.basename(str(nome)), "res": res, "mensal": mensal,
            "diaria": diaria, "serie": serie, "comp": comp, "val": val, "efeitos": ef, "dsem": dsem,
            "cmp": x.get("vs_rodada_anterior"), "ano": int(mensal["mes"].dropna().dt.year.max()) if mensal["mes"].notna().any() else None}


def arquivos_diarios(pastas):
    arqs = []
    for p in pastas:
        arqs += glob.glob(os.path.join(p, "*.xlsx"))
    return sorted({a for a in arqs if "diario" in _chave(os.path.basename(a)) and not os.path.basename(a).startswith("~$")})


def carregar_rodadas(arquivos):
    """{faixa: [rodadas da mais recente para a mais antiga]}; uma planilha com problema não derruba as demais."""
    out, erros = {f: [] for f in FAIXAS}, {}
    for a in arquivos:
        try:
            r = ler_rodada_diaria(a)
            out.setdefault(r["faixa"], []).append(r)
        except Exception as ex:
            erros[os.path.basename(a)] = str(ex)[:150]
    for f in out:
        out[f].sort(key=lambda r: r["corte"] or pd.Timestamp(0), reverse=True)
    return out, erros


# ------------------------------------------------------------------------------------------------ dados diários
def ler_instar_programas(arq, nomes_prog=None):
    """Exportação diária por programa do Instar Analytics (aba 'Crosstab': Nome Programa, Data, Rat%, Shr%).
    Devolve programa, data, rat, shr — base para a tabela tv_audiencia_diaria. `nomes_prog` traduz o nome do Instar
    para o nome do painel (ex.: tv.NOME_PROG); nomes sem tradução ficam com o nome do Instar em caixa de título."""
    raw = pd.read_excel(arq, sheet_name="Crosstab", header=None)
    lin = next(i for i in range(10) if _chave(raw.iat[i, 0]) == "nomeprograma")
    d = raw.iloc[lin + 1:, :4].dropna(subset=[0, 1])
    d.columns = ["programa", "data", "rat", "shr"]
    d["data"] = pd.to_datetime(d["data"], dayfirst=True, errors="coerce")
    d[["rat", "shr"]] = d[["rat", "shr"]].apply(pd.to_numeric, errors="coerce")
    nomes_prog = nomes_prog or {}
    norm = {_chave(k): v for k, v in nomes_prog.items()}
    extra = {"batvss": "BATV", "batvsb": "BATV", "bomdiasabado": "Bom Dia Sábado", "jornaldamanha": "Jornal da Manhã",
             "conexaobahia": "Conexão Bahia"}
    d["programa"] = [norm.get(_chave(p)) or extra.get(_chave(p)) or str(p).strip().title() for p in d["programa"]]
    d = d.dropna(subset=["data"]).groupby(["programa", "data"], as_index=False)[["rat", "shr"]].mean()
    return d.sort_values(["programa", "data"]).reset_index(drop=True)


def semaforo_cor(s):
    return {"Muito provável": "#1b5e20", "Provável": "#2e7d32", "Indefinido": "#f5a623", "Improvável": "#c62828",
            "Muito improvável": "#8e1b1b"}.get(str(s), "#8a8984")
