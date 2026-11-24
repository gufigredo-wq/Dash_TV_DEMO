"""Futebol na TV: audiência (Rat%) e share (Shr%) dos jogos do Brasileirão Série A e da Seleção Brasileira, com a concorrência.

Mesmo formato das tabelas do BI "Relatório Partidas Futebol" (F_Audiência e F_Share, exportação do Instar): uma linha por
TRANSMISSÃO, com a emissora que transmitiu ("Emissora Transmissora"), o valor dela ("Reference:") e o que cada emissora marcou
no mesmo horário (GLOBO, RECORD, SBT, TV BAND, OCP, sem referência, Total Ligados Especial). A TVE Bahia não tem coluna própria:
o valor dela é o "Reference:" quando ela transmite (a mesma regra das medidas do BI).

• `ler_planilha()` lê a planilha (abas "Audiência" e "Share", ou F_Audiência/F_Share, ou CSV com a coluna "Métrica"),
  classifica a competição pelo "Quadro" e guarda só Série A e Seleção (os outros campeonatos são contados e ignorados).
• `modelo_xlsx()` gera a planilha modelo; `mesclar()` junta com o que existe; `gera_demo()` cria jogos FICTÍCIOS.
• Formato interno (longo): uma linha por jogo × métrica × emissora (COLUNAS).
"""
import io
import re
import unicodedata

import numpy as np
import pandas as pd

COLUNAS = ["data", "hora_inicio", "hora_fim", "dia_semana", "nome", "partida", "quadro", "competicao", "transmissora",
           "metrica", "emissora", "valor", "origem"]
CHAVE = ["data", "hora_inicio", "partida", "transmissora", "metrica", "emissora"]
JOGO = ["data", "hora_inicio", "partida", "transmissora"]   # o mesmo jogo pode passar em duas emissoras ao mesmo tempo

SERIE_A, SELECAO, SELECAO_F = "Brasileirão Série A", "Seleção Brasileira", "Seleção Brasileira (feminina)"
COPA, OUTROS, PRE_POS = "Copa do Mundo (outras seleções)", "Outros campeonatos", "Pré-jogo, pós-jogo e VT"
COMPETICOES = [SERIE_A, SELECAO, SELECAO_F, COPA, OUTROS, PRE_POS]
PRINCIPAIS = [SERIE_A, SELECAO]               # o padrão do filtro (o foco do painel)

TVB = "TV Bahia (Globo)"
# coluna do BI -> nome no painel (a ordem é a das legendas)
COLUNAS_BI = {"GLOBO": TVB, "RECORD": "Record", "SBT": "SBT", "TV BAND": "Band", "TVE BAHIA": "TVE Bahia", "OCP": "OCP",
              "Conteúdo de TV/Vídeo sem referência": "Sem referência", "Total Ligados Especial": "TLE (total ligados)"}
TRANSMISSORAS = {"GLOBO": TVB, "RECORD": "Record", "SBT": "SBT", "TV BAND": "Band", "TVE BAHIA": "TVE Bahia"}
EMISSORAS = [TVB, "Record", "SBT", "Band", "TVE Bahia", "OCP", "Sem referência", "TLE (total ligados)"]
AGREGADOS = {"OCP", "Sem referência", "TLE (total ligados)"}       # não disputam a "emissora mais vista"
DIAS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]


def _sa(t):
    return unicodedata.normalize("NFKD", str(t)).encode("ascii", "ignore").decode().upper().strip()


def classifica(quadro, partida="", nome=""):
    """Quadro do Instar (+ partida e nome do programa) -> competição do painel. Nada fica de fora: o que não é Série A
    nem Seleção vai para "Copa do Mundo (outras seleções)", "Outros campeonatos" ou "Pré-jogo, pós-jogo e VT"."""
    q, p, n = _sa(quadro), _sa(partida), _sa(nome)
    if not q:
        return None
    if q.startswith(("PRE JOGO", "POS JOGO")) or q.endswith(" VT") or " VT " in q:
        return PRE_POS
    fem = "FEM" in q or "FEMININA" in n
    brasil = "BRASIL" in p.replace("BRASILIENSE", "")
    if "SEL BRAS" in q:
        return SELECAO_F if fem else SELECAO
    if ("ELIMINAT COPA MUNDO" in q or "COPA DO MUNDO" in q or "COPA MUNDO" in q) and "MUNDIAL CLUBES" not in q:
        if brasil:
            return SELECAO_F if fem else SELECAO
        return COPA if not fem else OUTROS
    if "CAMP BRASILEIRO" in q and not any(s in q for s in ("SERIE B", "SERIE C", "SERIE D", "FEM", "SUB")):
        return SERIE_A
    return OUTROS


def _hora(v):
    """16:00 | datetime(1899-12-30 16:00) | 0,6667 (fração do dia do Excel) | time -> 'HH:MM'."""
    if v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() == "":
        return None
    if isinstance(v, (int, float, np.floating)) and 0 <= float(v) < 1:
        m = int(round(float(v) * 24 * 60))
        return f"{m // 60:02d}:{m % 60:02d}"
    if hasattr(v, "hour"):
        return f"{v.hour:02d}:{v.minute:02d}"
    m = re.search(r"(\d{1,2})[:h](\d{2})", str(v))
    return f"{int(m[1]):02d}:{m[2]}" if m else None


def _data(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        d = pd.to_datetime(v, dayfirst=isinstance(v, str) and "/" in v)
        return pd.Timestamp(d.year, d.month, d.day)
    except Exception:
        return None


def _num(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return np.nan
    if isinstance(v, (int, float, np.integer, np.floating)):
        return float(v)
    s = str(v).strip().replace("%", "")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return np.nan


def _metrica_da_aba(nome):
    n = _sa(nome)
    return "Share" if "SHARE" in n or "SHR" in n else "Audiência" if ("AUDI" in n or "RAT" in n) else None


def _cabecalho(df):
    for i in range(min(len(df), 20)):
        vals = [str(x).strip() for x in df.iloc[i].tolist()]
        if "Detalhe" in vals and ("Emissora Transmissora" in vals or "Emissora" in vals):
            return i, vals
    return None, None


def _linhas_da_aba(df, metrica, origem):
    i, cab = _cabecalho(df)
    if i is None:
        return None
    d = df.iloc[i + 1:].copy()
    d.columns = [c if c and c != "nan" else f"_c{k}" for k, c in enumerate(cab)]
    col_data = next((c for c in ("Data Inicio", "Data", "Data Início") if c in d.columns), None)
    col_tr = "Emissora Transmissora" if "Emissora Transmissora" in d.columns else "Emissora"
    out, fora = [], {}
    for _, r in d.iterrows():
        data = _data(r.get(col_data)) if col_data else None
        partida = str(r.get("Detalhe") or "").strip()
        quadro = str(r.get("Quadro") or "").strip()
        if partida in ("", "nan", "None"):             # pré-jogo, pós-jogo e cerimônias vêm sem "Detalhe"
            partida = quadro.title() if quadro and quadro != "nan" else ""
        if data is None or not partida:
            continue
        comp = classifica(quadro, partida, r.get("Nome") or "")
        if comp is None:
            fora.setdefault(quadro, set()).add((data, partida))
            continue
        met = metrica or ("Share" if _sa(r.get("Métrica", "")).startswith("SH") else "Audiência")
        trans = TRANSMISSORAS.get(_sa(r.get(col_tr)), str(r.get(col_tr)).strip().title())
        base = {"data": data, "hora_inicio": _hora(r.get("Hora Início") or r.get("Hora Inicio")),
                "hora_fim": _hora(r.get("Hora Fim")), "dia_semana": str(r.get("Dia da Semana") or "").strip() or DIAS[data.weekday()],
                "nome": str(r.get("Nome") or "").strip(), "partida": partida, "quadro": quadro, "competicao": comp,
                "transmissora": trans, "metrica": met, "origem": origem}
        if not base["hora_inicio"]:
            base["hora_inicio"] = "00:00"
        vals = {}
        for col, em in COLUNAS_BI.items():
            if col in d.columns:
                v = _num(r.get(col))
                if not (met == "Share" and em == "TLE (total ligados)"):           # no share, o total é sempre 100
                    vals[em] = v
        ref = _num(r.get("Reference:", r.get("Reference")))
        if pd.notna(ref):
            vals[trans] = ref                                                       # vale o valor da transmissora (regra do BI)
        for em, v in vals.items():
            if pd.notna(v):
                out.append({**base, "emissora": em, "valor": v})
    return out, fora


def ler_planilha(arquivo, nome=None):
    """Planilha no formato do BI -> (DataFrame em COLUNAS, avisos)."""
    nome = nome or getattr(arquivo, "name", "planilha")
    if str(nome).lower().endswith(".csv"):
        bruto = arquivo.read() if hasattr(arquivo, "read") else open(arquivo, "rb").read()
        txt = bruto.decode("utf-8-sig", errors="replace")
        abas = {"csv": pd.read_csv(io.StringIO(txt), sep=";" if txt.count(";") > txt.count(",") else ",", header=None, dtype=object)}
    else:
        abas = pd.read_excel(arquivo, sheet_name=None, header=None, dtype=object)
    linhas, fora, avisos, achou = [], {}, [], False
    for aba, df in abas.items():
        met = _metrica_da_aba(aba)
        r = _linhas_da_aba(df, met, f"{nome}:{aba}")
        if r is None:
            continue
        achou = True
        linhas += r[0]
        for k, v in r[1].items():
            fora.setdefault(k, set()).update(v)
    if not achou:
        return pd.DataFrame(columns=COLUNAS), ["Não encontrei o cabeçalho do BI (Detalhe, Emissora Transmissora…) em nenhuma aba."]
    out = pd.DataFrame(linhas, columns=COLUNAS)
    if fora:
        tot = len(set().union(*fora.values()))
        avisos.append(f"{tot} linha(s) sem quadro reconhecido ficaram de fora.")
    if not out.empty:
        out = out.drop_duplicates(CHAVE, keep="last").reset_index(drop=True)
        if set(out["metrica"]) == {"Audiência"}:
            avisos.append("A planilha só tem audiência: inclua a aba \"Share\" para ver o share dos jogos.")
    return out, avisos


def mesclar(atual, novo):
    """(base mesclada, jogos novos, jogos alterados). A chave é jogo (data+hora+partida) × métrica × emissora."""
    atual = atual.reindex(columns=COLUNAS) if atual is not None else pd.DataFrame(columns=COLUNAS)
    jogo = JOGO
    if atual.empty:
        return novo.reindex(columns=COLUNAS).reset_index(drop=True), novo[jogo].drop_duplicates().shape[0], 0
    a = atual.set_index(CHAVE)
    n = novo.set_index(CHAVE)
    comum = n.index.intersection(a.index)
    mudou = (n.loc[comum, "valor"].round(4) != a.loc[comum, "valor"].round(4)) if len(comum) else pd.Series(dtype=bool)
    jogos_novos = novo[jogo].drop_duplicates().merge(atual[jogo].drop_duplicates(), how="left", indicator=True)
    n_novos = int((jogos_novos["_merge"] == "left_only").sum())
    n_alt = len({k[:3] for k in mudou[mudou].index}) if len(mudou) else 0
    junto = pd.concat([a.drop(index=comum), n]).reset_index()
    return junto.reindex(columns=COLUNAS).sort_values(["data", "hora_inicio"]).reset_index(drop=True), n_novos, n_alt


def ler_csv(caminho):
    return pd.read_csv(caminho, parse_dates=["data"], dtype={"hora_inicio": str, "hora_fim": str}).reindex(columns=COLUNAS)


def jogos(df, metrica):
    """Uma linha por jogo, com o valor da transmissora ('valor') e uma coluna por emissora."""
    d = df[df["metrica"] == metrica]
    if d.empty:
        return pd.DataFrame()
    chave = JOGO
    info = d.drop_duplicates(chave)[chave + ["hora_fim", "dia_semana", "nome", "quadro", "competicao"]]
    larga = d.pivot_table(index=chave, columns="emissora", values="valor", aggfunc="last").reset_index()
    j = info.merge(larga, on=chave, how="left")
    j["valor"] = [r[r["transmissora"]] if r["transmissora"] in j.columns else np.nan for _, r in j.iterrows()]
    j["ano"] = pd.to_datetime(j["data"]).dt.year
    return j.sort_values(["data", "hora_inicio"]).reset_index(drop=True)


def modelo_xlsx():
    """Planilha modelo no formato das tabelas do BI (abas Audiência e Share) + Instruções."""
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    wb = openpyxl.Workbook()
    cab = ["Data Inicio", "Hora Início", "Hora Fim", "Nome", "Emissora Transmissora", "Dia da Semana", "Detalhe", "Quadro",
           "Ano", "Reference:", "GLOBO", "RECORD", "SBT", "TV BAND", "OCP", "Conteúdo de TV/Vídeo sem referência",
           "Total Ligados Especial", "Data Fim"]
    ex_a = [["2026-09-20", "16:00", "17:55", "FUTEBOL VES", "GLOBO", "Domingo", "BAHIA X FLAMENGO", "FUT CAMP BRASILEIRO VIVO", 2026,
             24.5, 24.5, 5.1, 3.6, 2.4, 4.2, 3.0, 48.9, "2026-09-20"],
            ["2026-09-09", "21:45", "23:40", "FUTEBOL NOT", "GLOBO", "Terça", "BRASIL X CHILE", "FUT ELIMINAT COPA MUNDO VIVO", 2026,
             27.3, 27.3, 4.4, 3.1, 2.0, 3.6, 2.8, 45.1, "2026-09-09"]]
    ex_s = [r[:9] + [50.1, 50.1, 10.4, 7.4, 4.9, 8.6, 6.1, 100, r[-1]] for r in ex_a[:1]] + \
           [ex_a[1][:9] + [60.5, 60.5, 9.8, 6.9, 4.4, 8.0, 6.2, 100, ex_a[1][-1]]]
    for aba, ex in (("Audiência", ex_a), ("Share", ex_s)):
        ws = wb.create_sheet(aba)
        ws.append(cab)
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="0B3FAE")
            c.alignment = Alignment(horizontal="center", wrap_text=True)
        for linha in ex:
            ws.append(linha)
        for k in range(1, len(cab) + 1):
            ws.column_dimensions[openpyxl.utils.get_column_letter(k)].width = 26 if k in (7, 8, 16) else 13
        ws.freeze_panes = "A2"
    ins = wb.active
    ins.title = "Instruções"
    for t in ["Planilha de futebol · Painel de Audiência · TV (mesmo formato das tabelas do BI \"Relatório Partidas Futebol\")",
              "",
              "Aba \"Audiência\" = F_Audiência (Rat%) · aba \"Share\" = F_Share (Shr%). Uma linha por transmissão.",
              "Colunas iguais às do BI. \"Reference:\" = valor da emissora que transmitiu; GLOBO, RECORD, SBT, TV BAND, OCP… = o que cada",
              "   emissora marcou no mesmo horário. A TVE Bahia não tem coluna: o valor dela é o \"Reference:\" quando ela transmite.",
              "Também serve a exportação do Instar Analytics (\"Competição de Faixas Horárias\": aba Rat% e aba Shr%), como vem.",
              "Todos os quadros entram. A aba abre no Brasileirão Série A (FUT CAMP BRASILEIRO VIVO) e na Seleção Brasileira",
              "   (amistosos, eliminatórias e Copa do Mundo com o Brasil); os outros campeonatos, a Copa sem o Brasil e o",
              "   pré/pós-jogo ficam disponíveis no filtro de competição.",
              "Data: AAAA-MM-DD ou DD/MM/AAAA. Hora: HH:MM. Decimais com vírgula ou ponto. Pode colar a exportação inteira do BI.",
              "",
              "Enviar: no painel de TV, ⚙ Atualizar dados → 8 · Futebol. Jogos já existentes (data+hora+partida) são substituídos.",
              "Fonte: Kantar IBOPE Media (Instar). Uso interno."]:
        ins.append([t])
    ins["A1"].font = Font(bold=True, size=13)
    ins.column_dimensions["A"].width = 120
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ------------------------------------------------------------------------------------- dados fictícios (demonstração)
_CLUBES = ["FLAMENGO", "PALMEIRAS", "CORINTHIANS", "SAO PAULO", "FLUMINENSE", "BOTAFOGO RJ", "VASCO DA GAMA", "GREMIO",
           "INTERNACIONAL", "ATLETICO MG", "CRUZEIRO", "FORTALEZA", "CEARA", "SANTOS", "BRAGANTINO", "SPORT", "JUVENTUDE",
           "MIRASSOL"]
_RIVAIS_SEL = ["ARGENTINA", "URUGUAI", "COLOMBIA", "EQUADOR", "PARAGUAI", "CHILE", "PERU", "VENEZUELA", "BOLIVIA"]
_AMISTOSOS = ["FRANCA", "SENEGAL", "JAPAO", "COREIA DO SUL", "MEXICO", "INGLATERRA", "ESPANHA", "CROACIA"]


def gera_demo(seed=20261112, ate="2026-10-31"):
    """Jogos FICTÍCIOS de 2023 a 2026 (Série A na Globo e, desde 2025, na Record; Seleção na Globo; Copa de 2026)."""
    rng = np.random.default_rng(seed)
    fim = pd.Timestamp(ate)
    jogos_ = []

    def add(data, hora, partida, quadro, trans, base, extra_tle=0):
        if data > fim:
            return
        jogos_.append((data, hora, partida, quadro, trans, base, extra_tle))

    for ano, ini, fim_temp, com_bahia, com_vitoria in ((2023, "2023-04-15", "2023-12-06", True, False),
                                                        (2024, "2024-04-13", "2024-12-08", True, True),
                                                        (2025, "2025-03-29", "2025-12-07", True, True),
                                                        (2026, "2026-01-28", "2026-12-02", True, True)):
        d = pd.Timestamp(ini)
        rodada = 0
        while d <= pd.Timestamp(fim_temp) and rodada < 38:
            if ano == 2026 and pd.Timestamp("2026-06-01") <= d <= pd.Timestamp("2026-07-22"):   # pausa da Copa
                d += pd.Timedelta(days=7)
                continue
            rodada += 1
            meio = rodada % 4 == 2                                   # algumas rodadas no meio da semana
            dia_globo = d - pd.Timedelta(days=3) if meio else d + pd.Timedelta(days=1)   # quarta (meio de semana) ou domingo
            locais = (["BAHIA"] if com_bahia else []) + (["VITORIA BA"] if com_vitoria else [])
            classico = locais == ["BAHIA", "VITORIA BA"] and rodada in (9, 28)
            if classico:
                casa, fora = ("BAHIA", "VITORIA BA") if rodada == 9 else ("VITORIA BA", "BAHIA")
                partida, tipo = f"{casa} X {fora}", 3
            elif rng.random() < .62 and locais:
                time = locais[rng.integers(len(locais))]
                adv = _CLUBES[rng.integers(len(_CLUBES))]
                partida, tipo = (f"{time} X {adv}" if rng.random() < .5 else f"{adv} X {time}"), 2
            else:
                a, b = rng.choice(_CLUBES, 2, replace=False)
                partida, tipo = f"{a} X {b}", (1 if "FLAMENGO" in (a, b) else 0)
            hora = "21:30" if meio else ("16:00" if rng.random() < .7 else "18:30")
            add(dia_globo, hora, partida, "FUT CAMP BRASILEIRO VIVO", "GLOBO", ("A", tipo, ano))
            if ano >= 2025:                                          # Record com um jogo por rodada
                a, b = rng.choice(_CLUBES, 2, replace=False)
                local = locais[rng.integers(len(locais))] if (locais and rng.random() < .25 and tipo < 2) else None
                p2 = f"{local} X {a}" if local else f"{a} X {b}"
                add(d, "18:30" if rng.random() < .6 else "21:00", p2, "FUT CAMP BRASILEIRO VIVO", "RECORD", ("A", 2 if local else 0, ano))
            d += pd.Timedelta(days=7)

    elim = [("2023-09-08", 0), ("2023-09-12", 1), ("2023-10-12", 2), ("2023-10-17", 3), ("2023-11-16", 4), ("2023-11-21", 5),
            ("2024-09-06", 6), ("2024-09-10", 7), ("2024-10-10", 8), ("2024-10-15", 0), ("2024-11-14", 1), ("2024-11-19", 2),
            ("2025-03-20", 3), ("2025-03-25", 4), ("2025-06-05", 5), ("2025-06-10", 6), ("2025-09-04", 7), ("2025-09-09", 8)]
    for k, (dt, r) in enumerate(elim):
        partida = f"BRASIL X {_RIVAIS_SEL[r]}" if k % 2 == 0 else f"{_RIVAIS_SEL[r]} X BRASIL"
        add(pd.Timestamp(dt), "21:45" if k % 3 else "20:00", partida, "FUT ELIMINAT COPA MUNDO VIVO", "GLOBO", ("S", 1, 0))
    for k, dt in enumerate(["2024-03-23", "2024-03-26", "2024-06-08", "2024-06-12", "2025-10-10", "2025-10-14",
                            "2025-11-15", "2026-03-26", "2026-03-31"]):
        add(pd.Timestamp(dt), "16:00" if k % 2 else "17:00", f"BRASIL X {_AMISTOSOS[k % len(_AMISTOSOS)]}",
            "FUT AMIST SEL BRASILEIRA VIVO", "GLOBO", ("S", 0, 0))
    copa = [("2026-06-13", "NIGERIA"), ("2026-06-19", "SUECIA"), ("2026-06-24", "AUSTRALIA"),
            ("2026-06-29", "GANA"), ("2026-07-04", "DINAMARCA"), ("2026-07-09", "PORTUGAL")]
    for k, (dt, adv) in enumerate(copa):                         # jogos e adversários inventados (dados fictícios)
        hora = ["19:00", "22:00", "18:00", "17:00", "16:00", "17:00"][k]
        add(pd.Timestamp(dt), hora, f"BRASIL X {adv}", "FUT COPA DO MUNDO VIVO", "GLOBO+SBT", ("C", k, 0))
        h0 = int(hora[:2]) - 1
        add(pd.Timestamp(dt), f"{h0:02d}:30", "PRE JOGO", "PRE JOGO", "GLOBO", ("P", 1, 0))
    for k, dt in enumerate(["2024-04-06", "2024-06-01", "2025-04-04", "2025-10-24", "2026-04-11", "2026-10-24"]):
        add(pd.Timestamp(dt), "11:00" if k % 2 else "17:00", f"BRASIL X {_AMISTOSOS[(k + 3) % len(_AMISTOSOS)]}",
            "FUT AMIST SEL BRASIL FEM VIVO", "GLOBO", ("F", 0, 0))

    # Copa do Mundo de 2026 sem o Brasil (Globo ou SBT)
    outras = ["ARGENTINA X MEXICO", "FRANCA X JAPAO", "ESPANHA X CROACIA", "INGLATERRA X EUA", "ALEMANHA X COREIA SUL",
              "PORTUGAL X URUGUAI", "HOLANDA X SENEGAL", "ITALIA X EQUADOR", "BELGICA X MARROCOS", "COLOMBIA X SUICA"]
    for k, p_ in enumerate(outras):
        add(pd.Timestamp("2026-06-12") + pd.Timedelta(days=2 * k + 1), ["13:00", "16:00", "22:00"][k % 3], p_,
            "FUT COPA DO MUNDO VIVO", "GLOBO" if k % 2 == 0 else "SBT", ("M", k % 3, 0))
    # Copa do Brasil (Globo), Baiano (TVE e Band, às vezes juntas) e Série B (Band e TVE ao mesmo tempo)
    for ano in (2023, 2024, 2025, 2026):
        for k in range(6):
            dt = pd.Timestamp(f"{ano}-04-19") + pd.Timedelta(days=21 * k)
            loc = ["BAHIA", "VITORIA BA"][k % 2]
            add(dt, "21:30", f"{loc} X {_CLUBES[(k * 3 + ano) % len(_CLUBES)]}", "FUT COPA DO BRASIL VIVO", "GLOBO", ("O", 1, ano))
        for k in range(8):
            dt = pd.Timestamp(f"{ano}-01-20") + pd.Timedelta(days=7 * k)
            adv = ["JACUIPENSE", "ATLETICO BA", "BAHIA DE FEIRA", "JUAZEIRENSE", "BARCELONA BA", "VITORIA DA CONQUISTA",
                   "JEQUIE", "FLUMINENSE FEIRA"][k]
            add(dt, "16:00", f"{['BAHIA', 'VITORIA BA'][k % 2]} X {adv}", "FUT CAMP BAIANO VIVO",
                "TVE BAHIA+TV BAND" if k % 3 == 0 else "TVE BAHIA", ("O", 2, ano))
        for k in range(5):
            dt = pd.Timestamp(f"{ano}-05-04") + pd.Timedelta(days=14 * k)
            add(dt, "16:00", f"{_CLUBES[(k + ano) % len(_CLUBES)]} X {_CLUBES[(k + ano + 5) % len(_CLUBES)]}",
                "FUT CAMP BRAS SERIE B VIVO", "TV BAND+TVE BAHIA", ("O", 3, ano))
    # pré-jogo de alguns clássicos da Série A
    for data, hora, partida, quadro, trans, info, _x in list(jogos_):
        if quadro == "FUT CAMP BRASILEIRO VIVO" and trans == "GLOBO" and info[1] == 3:
            add(data, f"{int(hora[:2]) - 1:02d}:30", "PRE JOGO", "PRE JOGO", "GLOBO", ("P", 2, info[2]))

    linhas = []
    for data, hora, partida, quadro, trans, (tipo_c, peso, ano), _extra in jogos_:
        transmissoras = trans.split("+")                        # "GLOBO+SBT": a mesma partida em duas emissoras
        trans = transmissoras[0]
        h = int(hora[:2])
        noite = h >= 20
        tle = (46 if not noite else 43) + rng.normal(0, 1.6) + (4 if tipo_c in "SC" else 0) + (6 if tipo_c == "C" else 0)
        if tipo_c == "A":
            ref = (11.5 + [0, 2.2, 8.5, 15][peso] + .4 * (ano - 2023) + rng.normal(0, 1.6)) * (.62 if trans == "RECORD" else 1)
        elif tipo_c == "S":
            ref = (16 if peso == 0 else 22) + rng.normal(0, 2.2)
        elif tipo_c == "C":
            ref = 31 + 2.2 * peso + rng.normal(0, 1.5)
        elif tipo_c == "M":                                     # Copa sem o Brasil
            ref = (14 + 2 * peso + rng.normal(0, 2)) * (.35 if trans == "SBT" else 1)
        elif tipo_c == "O":                                     # Copa do Brasil, Baiano, Série B
            ref = {1: 16 + rng.normal(0, 2.5), 2: 2.6 + rng.normal(0, .7), 3: 1.2 + rng.normal(0, .3)}[peso]
        elif tipo_c == "P":                                     # pré-jogo
            ref = 10 + 4 * (peso == 1) + rng.normal(0, 1.2)
        else:
            ref = 9 + rng.normal(0, 1.5)
        ref = float(np.clip(ref, 3, tle * .85))
        resto = tle - ref
        pesos = {"GLOBO": .44, "RECORD": .16, "SBT": .12, "TV BAND": .08, "TVE BAHIA": .02, "OCP": .12,
                 "Conteúdo de TV/Vídeo sem referência": .08}
        refs = {trans: ref}
        for t2 in transmissoras[1:]:                            # a 2ª emissora do jogo simultâneo
            refs[t2] = {"SBT": 7.5 + rng.normal(0, 1.8), "TV BAND": ref * 1.6, "TVE BAHIA": ref * .55}.get(t2, ref * .4)
        resto = tle - sum(refs.values())
        for t2 in refs:
            pesos.pop(t2, None)
        if trans != "GLOBO":
            pesos["GLOBO"] = .48                                       # a Globo segue forte com outra programação
        w = np.array(list(pesos.values())) * np.exp(rng.normal(0, .18, len(pesos)))
        vals = dict(zip(pesos, max(resto, 1) * w / w.sum()))
        vals.update(refs)
        cols_a = {c: round(vals.get(c, np.nan), 2) for c in ("GLOBO", "RECORD", "SBT", "TV BAND", "TVE BAHIA", "OCP",
                                                             "Conteúdo de TV/Vídeo sem referência")}
        cols_a["Total Ligados Especial"] = round(tle, 2)
        fim_h = f"{(h + 2) % 24:02d}:{hora[3:]}"
        nome_faixa = "FUTEBOL NOT" if noite else ("FUTEBOL MAT" if h < 12 else "FUTEBOL VES")
        if tipo_c == "P":
            fim_h, nome_faixa = f"{h + 1:02d}:00", "FUTEBOL PRE JOGO"
            partida = "Pre Jogo"
        for t_ in transmissoras:
            base = {"data": data, "hora_inicio": hora, "hora_fim": fim_h, "dia_semana": DIAS[data.weekday()], "nome": nome_faixa,
                    "partida": partida, "quadro": quadro, "competicao": classifica(quadro, partida, nome_faixa),
                    "transmissora": TRANSMISSORAS[t_], "origem": "demo"}
            for col, v in cols_a.items():
                em = COLUNAS_BI[col]
                linhas.append({**base, "metrica": "Audiência", "emissora": em, "valor": v})
                if em != "TLE (total ligados)":
                    linhas.append({**base, "metrica": "Share", "emissora": em, "valor": round(v / tle * 100, 2)})
    return pd.DataFrame(linhas).reindex(columns=COLUNAS)


def para_planilha_bi(df):
    """Formato interno -> planilha no formato do BI (abas Audiência e Share), em bytes .xlsx."""
    inv = {v: k for k, v in COLUNAS_BI.items()}
    inv_t = {v: k for k, v in TRANSMISSORAS.items()}
    buf = io.BytesIO()
    with pd.ExcelWriter(buf) as w:
        for met in ("Audiência", "Share"):
            j = jogos(df, met)
            if j.empty:
                continue
            out = pd.DataFrame({"Data Inicio": pd.to_datetime(j["data"]).dt.strftime("%Y-%m-%d"), "Hora Início": j["hora_inicio"],
                                "Hora Fim": j["hora_fim"], "Nome": j["nome"], "Emissora Transmissora": j["transmissora"].map(inv_t),
                                "Dia da Semana": j["dia_semana"], "Detalhe": j["partida"], "Quadro": j["quadro"],
                                "Ano": pd.to_datetime(j["data"]).dt.year, "Reference:": j["valor"]})
            for em, col in inv.items():
                out[col] = j[em] if em in j.columns else (100.0 if met == "Share" and em == "TLE (total ligados)" else np.nan)
            out["Data Fim"] = out["Data Inicio"]
            out.to_excel(w, sheet_name=met, index=False)
    return buf.getvalue()


def para_instar_analytics(df):
    """Formato interno -> planilha no layout do Instar Analytics ("Competição de Faixas Horárias": título, cabeçalho, linha
    Total, uma aba de Rat% e outra de Shr%), em bytes .xlsx. Serve para gerar arquivos de teste no mesmo formato da exportação."""
    import openpyxl
    inv_t = {v: k for k, v in TRANSMISSORAS.items()}
    cols_em = ["GLOBO", "RECORD", "SBT", "TV BAND", "TVE BAHIA", "OCP", "Conteúdo de TV/Vídeo sem referência", "Total Ligados Especial"]
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for met, aba, tit in (("Audiência", "etição de Faixas Horárias(Rat%)",
                           "Competição de Faixas Horárias (Rat%|Total Domicílios|Grande Salvador|Live)"),
                          ("Share", "(Shr%  Total Ligados Especial )",
                           "Competição de Faixas Horárias (Shr% [Total Ligados Especial]|Total Domicílios|Grande Salvador|Live)")):
        j = jogos(df, met)
        if j.empty:
            continue
        ws = wb.create_sheet(aba)
        ws.append([tit])
        ws.append(["Data", "Hora Início", "Duração", "Hora Fim", "Nome", "Emissora", "Dia da Semana", "Detalhe", "Quadro"] + cols_em)
        ws.append(["Total"] + [None] * 8 + [None] * len(cols_em))
        for _, r in j.iterrows():
            vals = [r.get(COLUNAS_BI[c]) if c in COLUNAS_BI else None for c in cols_em]
            if met == "Share":
                vals[-1] = 100
            pre = r["competicao"] == PRE_POS and str(r["partida"]).upper() == str(r["quadro"]).title().upper()
            ws.append([pd.Timestamp(r["data"]).strftime("%d/%m/%Y"), f"{r['hora_inicio']}:00", "01:55:00", f"{r['hora_fim'] or ''}:00",
                       r["nome"], inv_t.get(r["transmissora"], r["transmissora"]), r["dia_semana"],
                       None if pre else r["partida"], r["quadro"]] + [None if v is None or pd.isna(v) else float(v) for v in vals])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
