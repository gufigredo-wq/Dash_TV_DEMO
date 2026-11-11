"""Concorrência da TV: audiência (Rat%) e share (Shr%) de cada emissora, por mês e por recorte.

Recorte = a faixa (6h às 24h, 7h às 24h) ou o HORÁRIO de um programa local (ex.: "BATV" = o que cada emissora marcou no
horário do BATV). Fonte: Kantar IBOPE (Instar), ranking de emissoras, TT Domicílios, Grande Salvador.

Planilha (formato longo, uma linha por mês × recorte × emissora):  Mês | Recorte | Emissora | Rat% | Shr%
• `modelo_xlsx()` gera a planilha modelo (aba "dados" + aba "Instruções"); o painel também lê CSV com as mesmas colunas.
• `ler_planilha()` lê e valida; `mesclar()` junta com o que já existe (mês+recorte+emissora repetidos são substituídos).
• `gera_demo()` cria concorrentes FICTÍCIOS coerentes com a base da TV Bahia (só para a demonstração e os testes).
"""
import io
import re
import unicodedata

import numpy as np
import pandas as pd

import tv

COLUNAS = ["mes", "recorte", "emissora", "rat", "shr", "origem"]
TV_BAHIA = "TV Bahia (Globo)"
OUTRAS = "Outras emissoras"                  # agregado opcional (TV paga, demais canais): aparece nos gráficos, fora do ranking
_APELIDOS = {"globo": TV_BAHIA, "tv bahia": TV_BAHIA, "rede globo": TV_BAHIA, "tv bahia globo": TV_BAHIA,
             "tv bahia (globo)": TV_BAHIA, "outras": OUTRAS, "outros": OUTRAS, "demais": OUTRAS, "outras emissoras": OUTRAS}
MESES = "jan fev mar abr mai jun jul ago set out nov dez".split()


def _sem_acento(t):
    return unicodedata.normalize("NFKD", str(t)).encode("ascii", "ignore").decode()


def normaliza_emissora(n):
    t = re.sub(r"\s+", " ", str(n or "")).strip()
    chave = _sem_acento(t).lower().strip()
    return _APELIDOS.get(chave, t)


def normaliza_recorte(n):
    """'06h às 24h', 'BATV', 'Jornal da Manha' -> nome do painel; None se não reconhece."""
    t = re.sub(r"\s+", " ", str(n or "")).strip()
    if not t:
        return None
    return tv.NOME_PROG.get(tv._norm(t)) or tv.NOME_PROG.get(tv._norm(re.sub(r"^(horario|horário) d[oa]s? ", "", t, flags=re.I)))


def _mes(v):
    """Data, 'AAAA-MM', 'MM/AAAA', 'set/26', 'set/2026' -> primeiro dia do mês."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, (pd.Timestamp, np.datetime64)) or hasattr(v, "year"):
        d = pd.Timestamp(v)
        return pd.Timestamp(d.year, d.month, 1)
    s = _sem_acento(v).strip().lower()
    m = re.match(r"^(\d{4})[-/.](\d{1,2})", s)
    if m:
        return pd.Timestamp(int(m[1]), int(m[2]), 1)
    m = re.match(r"^(\d{1,2})[-/.](\d{4})$", s)
    if m:
        return pd.Timestamp(int(m[2]), int(m[1]), 1)
    m = re.match(r"^([a-z]{3})[a-z]*[-/. ]?(\d{2}|\d{4})$", s)
    if m and m[1] in MESES:
        a = int(m[2])
        return pd.Timestamp(a + 2000 if a < 100 else a, MESES.index(m[1]) + 1, 1)
    return None


def _num(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return np.nan
    if isinstance(v, (int, float, np.integer, np.floating)):
        return float(v)
    s = str(v).strip().replace("%", "").replace(" ", "")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return np.nan


_CAB = {"mes": ("mes", "mês", "periodo", "período", "data", "datas"),
        "recorte": ("recorte", "faixa", "programa", "horario", "horário", "faixa/programa", "faixa ou programa"),
        "emissora": ("emissora", "canal", "rede"),
        "rat": ("rat%", "rat", "audiencia", "audiência", "rat %", "audiencia (rat%)", "audiência (rat%)"),
        "shr": ("shr%", "shr", "share", "shr %", "share (shr%)")}


def _acha_cabecalho(df):
    """Linha do cabeçalho (a que tem 'Emissora') e o mapa coluna -> campo."""
    for i in range(min(len(df), 30)):
        vals = [_sem_acento(x).strip().lower() if isinstance(x, str) else "" for x in df.iloc[i].tolist()]
        mapa = {}
        for j, v in enumerate(vals):
            for campo, nomes in _CAB.items():
                if campo not in mapa.values() and v in {_sem_acento(n) for n in nomes}:
                    mapa[j] = campo
        if "emissora" in mapa.values() and {"mes", "recorte"} <= set(mapa.values()):
            return i, mapa
    return None, None


def ler_planilha(arquivo, nome=None):
    """Planilha (.xlsx: aba 'dados' ou a primeira com o cabeçalho) ou CSV -> (DataFrame em COLUNAS, avisos)."""
    nome = nome or getattr(arquivo, "name", "planilha")
    avisos = []
    if str(nome).lower().endswith(".csv"):
        bruto = io.BytesIO(arquivo.read() if hasattr(arquivo, "read") else open(arquivo, "rb").read())
        txt = bruto.getvalue().decode("utf-8-sig", errors="replace")
        sep = ";" if txt.count(";") > txt.count(",") else ","
        abas = {"csv": pd.read_csv(io.StringIO(txt), sep=sep, header=None, dtype=object)}
    else:
        abas = pd.read_excel(arquivo, sheet_name=None, header=None, dtype=object)
        if "dados" in abas:
            abas = {"dados": abas["dados"], **{k: v for k, v in abas.items() if k != "dados"}}
    for aba, df in abas.items():
        i, mapa = _acha_cabecalho(df)
        if i is None:
            continue
        linhas, ignor_rec, ignor_mes = [], set(), 0
        for _, r in df.iloc[i + 1:].iterrows():
            reg = {campo: r.iloc[j] for j, campo in mapa.items()}
            if all((v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() == "") for v in reg.values()):
                continue
            mes, rec = _mes(reg.get("mes")), normaliza_recorte(reg.get("recorte"))
            em = normaliza_emissora(reg.get("emissora"))
            if mes is None:
                ignor_mes += 1
                continue
            if rec is None:
                ignor_rec.add(str(reg.get("recorte")))
                continue
            if not em:
                continue
            linhas.append({"mes": mes, "recorte": rec, "emissora": em, "rat": _num(reg.get("rat")),
                           "shr": _num(reg.get("shr")), "origem": f"{nome}:{aba}"})
        if ignor_mes:
            avisos.append(f"{ignor_mes} linha(s) sem mês reconhecido foram ignoradas.")
        if ignor_rec:
            avisos.append("Recortes não reconhecidos (ignorados): " + ", ".join(sorted(ignor_rec)[:8]) + ".")
        out = pd.DataFrame(linhas, columns=COLUNAS)
        if out.empty:
            continue
        out = out.drop_duplicates(["mes", "recorte", "emissora"], keep="last").reset_index(drop=True)
        soma = out.groupby(["mes", "recorte"])["shr"].sum()
        estouro = soma[soma > 101]
        if len(estouro):
            avisos.append(f"Atenção: em {len(estouro)} mês(es)/recorte(s) a soma dos shares passa de 100% "
                          f"(ex.: {estouro.index[0][1]} em {MESES[estouro.index[0][0].month - 1]}/{estouro.index[0][0]:%y}: "
                          f"{estouro.iloc[0]:.1f}%). Confira se não há emissora repetida.")
        if TV_BAHIA not in set(out["emissora"]):
            avisos.append(f"A planilha não tem a {TV_BAHIA}; os gráficos comparam só as emissoras enviadas.")
        return out, avisos
    return pd.DataFrame(columns=COLUNAS), ["Não encontrei o cabeçalho (Mês, Recorte, Emissora, Rat%, Shr%) em nenhuma aba."]


def mesclar(atual, novo):
    """(base mesclada, nº de linhas novas, nº de linhas alteradas). Mês+recorte+emissora repetidos: vale o envio novo."""
    chave = ["mes", "recorte", "emissora"]
    atual = atual.reindex(columns=COLUNAS) if atual is not None else pd.DataFrame(columns=COLUNAS)
    if atual.empty:
        return novo.reindex(columns=COLUNAS).reset_index(drop=True), len(novo), 0
    a = atual.set_index(chave)
    n = novo.set_index(chave)
    comum = n.index.intersection(a.index)
    alt = int(((n.loc[comum, ["rat", "shr"]].round(4) != a.loc[comum, ["rat", "shr"]].round(4)).any(axis=1)).sum()) if len(comum) else 0
    junto = pd.concat([a.drop(index=comum), n]).reset_index()
    return junto.reindex(columns=COLUNAS).sort_values(chave).reset_index(drop=True), len(n) - len(comum), alt


def ler_csv(caminho):
    d = pd.read_csv(caminho, parse_dates=["mes"])
    return d.reindex(columns=COLUNAS)


def modelo_xlsx():
    """Planilha modelo para preencher (aba dados com 3 linhas de exemplo + aba Instruções)."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.worksheet.datavalidation import DataValidation
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "dados"
    cab = ["Mês", "Recorte", "Emissora", "Rat%", "Shr%"]
    ws.append(cab)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="0B3FAE")
        c.alignment = Alignment(horizontal="center")
    for linha in (["2026-09", "6h às 24h", TV_BAHIA, 14.2, 36.7], ["2026-09", "6h às 24h", "Emissora B", 6.1, 15.8],
                  ["2026-09", "BATV", TV_BAHIA, 23.9, 45.6]):
        ws.append(linha)
    for col, larg in zip("ABCDE", (12, 22, 26, 9, 9)):
        ws.column_dimensions[col].width = larg
    ws.freeze_panes = "A2"
    lista = wb.create_sheet("recortes")
    for p in tv.PROGRAMAS:
        lista.append([p])
    lista.sheet_state = "hidden"
    dv = DataValidation(type="list", formula1=f"=recortes!$A$1:$A${len(tv.PROGRAMAS)}", allow_blank=True,
                        error="Use uma faixa ou um programa da lista.", errorTitle="Recorte")
    ws.add_data_validation(dv)
    dv.add("B2:B5000")
    ins = wb.create_sheet("Instruções", 0)
    textos = [
        "Planilha de concorrência · Painel de Audiência · TV",
        "",
        "Uma linha por mês × recorte × emissora, na aba \"dados\".",
        "Mês: AAAA-MM (ex.: 2026-09), uma data, 09/2026 ou set/26.",
        "Recorte: a faixa (6h às 24h ou 7h às 24h) ou o nome de um programa local, que significa o HORÁRIO do programa",
        "   (ex.: \"BATV\" = o que cada emissora marcou no horário do BATV). Há uma lista na coluna.",
        f"Emissora: o nome da emissora. Use \"{TV_BAHIA}\" para a TV Bahia (\"Globo\" e \"TV Bahia\" também são aceitos).",
        f"   \"{OUTRAS}\" (opcional) agrega TV paga e demais canais: aparece nos gráficos, mas fica fora do ranking.",
        "Rat% e Shr%: audiência e share do Instar (ranking de emissoras), TT Domicílios, Grande Salvador. Vírgula ou ponto.",
        "",
        "Enviar: no painel, ⚙ Atualizar dados → Concorrência. Mês+recorte+emissora já existentes são substituídos.",
        "Fonte: Kantar IBOPE Media (Instar). Uso interno.",
    ]
    for t in textos:
        ins.append([t])
    ins["A1"].font = Font(bold=True, size=13)
    ins.column_dimensions["A"].width = 110
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ------------------------------------------------------------------------------------- dados fictícios (demonstração)
EMISSORAS_DEMO = ["TV Mar Azul", "TV Cidade Alta", "Rede Horizonte", "TV Sertão"]


def gera_demo(base, seed=20261111):
    """Concorrentes FICTÍCIOS para cada mês e recorte da base: a TV Bahia usa os números da própria base; o resto do share
    se divide entre 4 emissoras inventadas e 'Outras emissoras', com tendências e sazonalidade suaves."""
    rng = np.random.default_rng(seed)
    b = base.copy()
    b["mes"] = pd.to_datetime(b["mes"])
    piv = b.pivot_table(index=["programa", "mes"], columns="metrica", values="valor").dropna()
    linhas = []
    pesos_base = np.array([.42, .27, .19, .12])           # divisão típica entre as 4 concorrentes
    for prog, g in piv.groupby(level=0):
        meses = g.index.get_level_values(1)
        n = len(meses)
        t = np.arange(n) / 12
        # cada concorrente com tendência própria e ruído com memória (AR)
        tend = np.array([.05, -.04, .03, -.02]) + rng.normal(0, .015, 4)
        ruido = np.zeros((n, 4))
        for k in range(1, n):
            ruido[k] = .6 * ruido[k - 1] + rng.normal(0, .045, 4)
        for i, (idx, row) in enumerate(g.iterrows()):
            rat_b, shr_b = float(row["Audiência"]), float(row["Share"])
            tle = rat_b / shr_b * 100 if shr_b else np.nan           # total de domicílios com TV ligada
            outras = np.clip(14 + 3 * np.sin(2 * np.pi * (meses[i].month / 12)) + rng.normal(0, .8), 8, 22)
            resto = max(100 - shr_b - outras, 5)
            w = pesos_base * np.exp(tend * t[i] + ruido[i])
            shr_c = resto * w / w.sum()
            linhas.append({"mes": meses[i], "recorte": prog, "emissora": TV_BAHIA, "rat": round(rat_b, 2), "shr": round(shr_b, 2)})
            for nome, s in zip(EMISSORAS_DEMO, shr_c):
                linhas.append({"mes": meses[i], "recorte": prog, "emissora": nome, "rat": round(s * tle / 100, 2), "shr": round(s, 2)})
            linhas.append({"mes": meses[i], "recorte": prog, "emissora": OUTRAS, "rat": round(outras * tle / 100, 2),
                           "shr": round(outras, 2)})
    out = pd.DataFrame(linhas)
    out["origem"] = "demo"
    return out.reindex(columns=COLUNAS)
