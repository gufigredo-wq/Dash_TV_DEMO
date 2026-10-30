"""Leitura dos dados de TV (Kantar IBOPE/Instar · TT Domicílios · Grande Salvador) e dos resultados da projeção.

Duas fontes:
  * base mensal (dados/tv_mensal.csv): uma linha por programa × métrica × mês;
  * rodadas da projeção (dados/rodadas/*.xlsx): a planilha de resultado exportada pelo notebook
    (fechamento_e_metas, projecao_mensal, vs_rodada_DD-MM, setembro_proj_x_real, sensibilidade, acumulado_DD-MM,
    backtest_fechamento, validacao_MAE).
"""
import re
import unicodedata

import numpy as np
import pandas as pd

PROGRAMAS = ["6h às 24h", "7h às 24h", "Jornal da Manhã", "Bahia Meio Dia", "Globo Esporte", "BATV", "Bom Dia Sábado",
             "Conexão Bahia", "Panela de Bairro", "Mosaico Baiano", "Bahia Rural"]
FAIXA = "6h às 24h"
FAIXA_7 = "7h às 24h"          # recorte só para consulta: não entra na projeção
METRICAS = ["Audiência", "Share"]
SIGLA = {"Audiência": "Rat%", "Share": "Shr%"}

TODOS, SEG_SEX, SEG_SAB, SAB, DOM = list(range(7)), [0, 1, 2, 3, 4], [0, 1, 2, 3, 4, 5], [5], [6]
DIAS_EXIBICAO = {"6h às 24h": TODOS, "7h às 24h": TODOS, "Jornal da Manhã": SEG_SEX, "Bahia Meio Dia": SEG_SEX, "Globo Esporte": SEG_SAB,
                 "BATV": SEG_SAB, "Bom Dia Sábado": SAB, "Conexão Bahia": SAB, "Panela de Bairro": SAB,
                 "Mosaico Baiano": SAB, "Bahia Rural": DOM}
DIAS_TXT = {"6h às 24h": "Todos os dias", "7h às 24h": "Todos os dias", "Jornal da Manhã": "Seg a Sex", "Bahia Meio Dia": "Seg a Sex",
            "Globo Esporte": "Seg a Sáb", "BATV": "Seg a Sáb", "Bom Dia Sábado": "Sábado", "Conexão Bahia": "Sábado",
            "Panela de Bairro": "Sábado", "Mosaico Baiano": "Sábado", "Bahia Rural": "Domingo"}

MESES = "jan fev mar abr mai jun jul ago set out nov dez".split()
MESES_PT = {"JANEIRO": 1, "FEVEREIRO": 2, "MARCO": 3, "ABRIL": 4, "MAIO": 5, "JUNHO": 6, "JULHO": 7,
            "AGOSTO": 8, "SETEMBRO": 9, "OUTUBRO": 10, "NOVEMBRO": 11, "DEZEMBRO": 12}
COLUNAS = ["programa", "metrica", "mes", "valor", "origem"]


def _norm(t):
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t).strip().upper()


NOME_PROG = {_norm(p): p for p in PROGRAMAS}
NOME_PROG.update({"6H AS 24H": FAIXA, "06H AS 24H": FAIXA, "7H AS 24H": FAIXA_7, "07H AS 24H": FAIXA_7,
                  "07H AS 24": FAIXA_7, "7H AS 24": FAIXA_7, "MOSAICO": "Mosaico Baiano"})


# ===================================================================================== base mensal
def ler_base(caminho):
    d = pd.read_csv(caminho)
    d["mes"] = pd.to_datetime(d["mes"].astype(str).str[:7] + "-01")
    d["valor"] = pd.to_numeric(d["valor"], errors="coerce")
    return d.dropna(subset=["valor"]).reindex(columns=COLUNAS)


def gravar_base(d, caminho):
    d = d.copy()
    d["mes"] = pd.to_datetime(d["mes"]).dt.strftime("%Y-%m")
    d.sort_values(["programa", "metrica", "mes"]).to_csv(caminho, index=False)


def mesclar(base, novo):
    """Junta `novo` à base (o novo prevalece). Devolve (base nova, linhas novas, linhas alteradas)."""
    chave = ["programa", "metrica", "mes"]
    b = base.copy()
    m = b.merge(novo[chave + ["valor"]], on=chave, how="outer", suffixes=("_ant", ""), indicator=True)
    novos = m[m["_merge"] == "right_only"]
    alt = m[(m["_merge"] == "both") & ((m["valor"] - m["valor_ant"]).abs() > 1e-6)]
    junto = pd.concat([b, novo]).drop_duplicates(chave, keep="last").sort_values(chave).reset_index(drop=True)
    return junto, novos, alt


def serie(base, programa, metrica):
    d = base[(base["programa"] == programa) & (base["metrica"] == metrica)]
    if d.empty:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([], freq="MS"))
    return d.set_index(pd.to_datetime(d["mes"]))["valor"].astype(float).sort_index().asfreq("MS")


def n_exib(programa, ini, fim):
    """Nº de exibições do programa entre duas datas (dias da semana de exibição)."""
    d = pd.date_range(ini, fim, freq="D")
    return int(np.isin(d.weekday, DIAS_EXIBICAO.get(programa, TODOS)).sum())


def media_anual(s, programa):
    """Média de cada ano ponderada pelo nº de exibições de cada mês (como o acumulado oficial)."""
    s = s.dropna()
    if s.empty:
        return pd.DataFrame(columns=["media", "meses"])
    w = pd.Series([n_exib(programa, m, m + pd.offsets.MonthEnd(0)) for m in s.index], index=s.index, dtype=float)
    g = pd.DataFrame({"v": s * w, "w": w, "n": 1}).groupby(s.index.year).sum()
    return pd.DataFrame({"media": g["v"] / g["w"], "meses": g["n"].astype(int)})


def ler_consolidado(arq, ano):
    """Planilha consolidada do ano (ex.: prog_e_faixa_jan_a_set.xlsx): 1ª linha com o nome da faixa/programa,
    2ª com AUDIÊNCIA/SHARE e, à esquerda de cada bloco, a coluna com o nome do mês. Blocos com outro nome
    (ex.: SBT na faixa horária) ficam de fora."""
    raw = pd.read_excel(arq, header=None)
    linhas = [r for r in range(len(raw)) if _norm(raw.iat[r, 0]) in MESES_PT]
    recs, ignorados = [], []
    lin_nome = next((r for r in range(min(5, len(raw))) if sum(_norm(x) in NOME_PROG for x in raw.iloc[r]) >= 2), 0)
    for c in range(1, raw.shape[1]):
        nome = _norm(raw.iat[lin_nome, c])
        if not nome or nome == "NAN":
            continue
        if nome not in NOME_PROG:
            ignorados.append(str(raw.iat[lin_nome, c]).strip())
            continue
        prog = NOME_PROG[nome]
        for r in linhas:
            rot = _norm(raw.iat[r, c - 1])
            if rot not in MESES_PT:
                continue
            mes = pd.Timestamp(ano, MESES_PT[rot], 1)
            for k, met in enumerate(METRICAS):
                v = pd.to_numeric(raw.iat[r, c + k], errors="coerce")
                if pd.notna(v):
                    recs.append(dict(programa=prog, metrica=met, mes=mes, valor=float(v), origem=f"consolidado {ano}"))
    return pd.DataFrame(recs, columns=COLUNAS), sorted(set(ignorados))


MESES_EN = {"JANUARY": 1, "FEBRUARY": 2, "MARCH": 3, "APRIL": 4, "MAY": 5, "JUNE": 6, "JULY": 7, "AUGUST": 8,
            "SEPTEMBER": 9, "OCTOBER": 10, "NOVEMBER": 11, "DECEMBER": 12}


def _data_en(txt):
    """' January 22' / 'January 2022' -> Timestamp(2022, 1, 1)."""
    p = _norm(txt).split()
    if len(p) != 2 or p[0] not in MESES_EN or not p[1].isdigit():
        return None
    a = int(p[1])
    return pd.Timestamp(a + 2000 if a < 100 else a, MESES_EN[p[0]], 1)


def ler_por_datas(arq):
    """Planilha do Instar com uma coluna 'Datas' (' January 22'…) e colunas Rat% / Shr% da Globo, uma aba por faixa ou
    programa (o nome da aba diz qual: ex. '07h às 24h'). Usa a primeira coluna Rat% e a primeira Shr% de cada aba."""
    recs = []
    for nome_aba, raw in pd.read_excel(arq, header=None, sheet_name=None).items():
        prog = NOME_PROG.get(_norm(nome_aba))
        if not prog:
            continue
        cab = {}
        for r in range(min(6, len(raw))):
            for c in range(raw.shape[1]):
                t = _norm(raw.iat[r, c])
                if t.startswith("RAT%") and "Audiência" not in cab:
                    cab["Audiência"] = c
                elif t.startswith("SHR%") and "Share" not in cab:
                    cab["Share"] = c
        for r in range(len(raw)):
            for c in range(raw.shape[1]):
                mes = _data_en(raw.iat[r, c]) if isinstance(raw.iat[r, c], str) else None
                if mes is None:
                    continue
                for met, col in cab.items():
                    v = pd.to_numeric(raw.iat[r, col], errors="coerce")
                    if pd.notna(v):
                        recs.append(dict(programa=prog, metrica=met, mes=mes, valor=float(v), origem=f"{nome_aba}"))
                break
    return pd.DataFrame(recs, columns=COLUNAS)


# ===================================================================================== resultado da projeção
_RENOMEAR = [  # (padrão no nome da coluna, nome interno) — os nomes do notebook mudam com a data de corte
    (r"^acum\.", "acum"), (r"^fechamento$", "fech"), (r"^IC95 inf", "ic_inf"), (r"^IC95 sup", "ic_sup"),
    (r"^média proj\.", "proj_rest"), (r"^meta 75%", "meta75"), (r"^P\(75%\)", "p75"), (r"^média nec\. 75%", "nec75"),
    (r"^meta 100%", "meta100"), (r"^P\(100%\)", "p100"), (r"^média nec\. 100%", "nec100"), (r"^meta 120%", "meta120"),
    (r"^P\(120%\)", "p120"), (r"^média nec\. 120%", "nec120"), (r"^semáforo", "semaforo"), (r"^fronteira", "fronteira"),
    (r"^degrau", "degrau"), (r"^incerteza", "incerteza"), (r"^MAE", "mae"), (r"^viés médio", "vies"), (r"^p viés", "p_vies"),
]


def _renomeia(cols, regras):
    out = {}
    for c in cols:
        for pad, novo in regras:
            if re.search(pad, str(c)) and novo not in out.values():
                out[c] = novo
                break
    return out


def _prog_met(df):
    df = df.copy()
    df["programa"] = df["programa"].ffill()
    if "métrica" in df:
        df["métrica"] = df["métrica"].ffill()
        df = df.rename(columns={"métrica": "metrica"})
    return df


def _separa_serie(df, col="série"):
    df = df.copy()
    pm = df[col].astype(str).str.split(" · ", n=1, expand=True)
    df["programa"], df["metrica"] = pm[0].str.strip(), pm[1].str.strip()
    return df


def _mes(txt):
    m, a = str(txt).split("/")
    return pd.Timestamp(int(a), MESES.index(m.strip().lower()[:3]) + 1, 1)


def ler_resultado(arq):
    """Lê a planilha de resultado do notebook. Devolve um dicionário com as tabelas padronizadas e os metadados
    da rodada (data de corte, ano, meses projetados, data da rodada anterior)."""
    x = pd.read_excel(arq, sheet_name=None)
    nomes = list(x)
    if "fechamento_e_metas" not in nomes or "projecao_mensal" not in nomes:
        raise ValueError("A planilha não tem as abas fechamento_e_metas e projecao_mensal do notebook.")
    R = {}
    f = _prog_met(x["fechamento_e_metas"])
    f = f.rename(columns=_renomeia(f.columns, _RENOMEAR))
    R["fech"] = f.set_index(["programa", "metrica"])
    pm = _prog_met(x["projecao_mensal"])
    pm["programa"], pm["metrica"] = pm["programa"].ffill(), pm["metrica"].ffill()
    pm["mes"] = pm["mês"].map(_mes)
    R["mensal"] = pm.rename(columns={"projeção": "proj", "IC80 inf": "i80", "IC80 sup": "s80", "IC95 inf": "i95",
                                     "IC95 sup": "s95"})[["programa", "metrica", "mes", "proj", "i80", "s80", "i95", "s95"]]
    acum_col = next(c for c in x["fechamento_e_metas"].columns if str(c).startswith("acum."))
    dd_mm = re.search(r"(\d{2})/(\d{2})", acum_col)
    ano = int(R["mensal"]["mes"].dt.year.min()) if len(R["mensal"]) else pd.Timestamp.today().year
    corte = pd.Timestamp(ano, int(dd_mm.group(2)), int(dd_mm.group(1))) if dd_mm else None
    rest = next((c for c in x["fechamento_e_metas"].columns if str(c).startswith("média proj.")), "")
    meta = {"corte": corte, "ano": ano, "meses_rest": rest.replace("média proj.", "").strip(),
            "ultimo_mes": (corte.replace(day=1) if corte is not None else None)}
    vs = next((n for n in nomes if n.startswith("vs_rodada")), None)
    if vs:
        v = _prog_met(x[vs])
        ant = re.search(r"(\d{2})-(\d{2})", vs)
        meta["anterior"] = f"{ant.group(1)}/{ant.group(2)}" if ant else "rodada anterior"
        reg = [(r"^fech\. agora", "fech"), (r"^fech\.", "fech_ant"), (r"^P100 agora", "p"), (r"^P100", "p_ant"),
               (r"^Δ P100", "dp"), (r"^semáforo agora", "sem"), (r"^semáforo", "sem_ant"), (r"^mudou", "mudou")]
        R["vs"] = v.rename(columns=_renomeia(v.columns, reg)).set_index(["programa", "metrica"])
    for nome, chave in [("sensibilidade", "sens")]:
        if nome in x:
            R[chave] = _prog_met(x[nome]).set_index(["programa", "metrica"])
    sp = next((n for n in nomes if n.endswith("_proj_x_real")), None)
    if sp:
        R["acomp"] = _separa_serie(x[sp]).set_index(["programa", "metrica"])
        meta["mes_acomp"] = sp.split("_")[0]
    ac = next((n for n in nomes if n.startswith("acumulado")), None)
    if ac:
        R["acum"] = _separa_serie(x[ac]).set_index(["programa", "metrica"])
    if "backtest_fechamento" in x:
        R["backtest"] = _prog_met(x["backtest_fechamento"])
    if "validacao_MAE" in x:
        v = x["validacao_MAE"].rename(columns={x["validacao_MAE"].columns[0]: "série"})
        R["mae"] = _separa_serie(v).set_index(["programa", "metrica"])
    R["meta"] = meta
    return R


def semaforo(p):
    if p is None or pd.isna(p):
        return "–"
    return "Provável" if p >= .8 else ("Indefinido" if p >= .2 else "Improvável")


def fmt_p(p):
    if p is None or pd.isna(p):
        return "–"
    if p < 0.001:
        return "<0,1%"
    if p > 0.999:
        return ">99,9%"
    return f"{p * 100:.1f}%".replace(".", ",")
