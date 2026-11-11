"""Assistente do painel de TV.

Dois modos, com a mesma interface (streamlit_app.py):
• IA (Gemini): `perguntar_ia(...)`. O modelo interpreta a pergunta e chama FERRAMENTAS de consulta; quem executa as
  consultas é o painel, nos dados internos (banco). O modelo recebe só o resultado de cada consulta, nunca a base inteira,
  e escreve a resposta com os números e uma leitura (insights). Chave em GEMINI_API_KEY (Secrets ou variável de ambiente).
• Respostas prontas: `responder(...)`, sem IA. É o que roda sem chave ou se a IA falhar.
"""
import html
import re
import unicodedata

import pandas as pd

FAIXA, FAIXA_7 = "6h às 24h", "7h às 24h"
MESES = "jan fev mar abr mai jun jul ago set out nov dez".split()

SUGESTOES = ["Como foi o último mês?", "Quais programas mais cresceram?", "Chance de bater a meta",
             "Maior audiência", "O que é rating e share?", "Como a projeção é feita?"]

BOAS_VINDAS = ("Olá! Sou o assistente do painel. Pergunte sobre a **audiência** e o **share** da TV Bahia, "
               "os **programas** ou as **metas**. Toque numa sugestão ou escreva do seu jeito, "
               "por exemplo: *como está o BATV?*")

APELIDOS = {  # texto normalizado -> programa (o nome completo de cada programa também vale)
    "jm": "Jornal da Manhã", "jornal da manha": "Jornal da Manhã",
    "bmd": "Bahia Meio Dia", "meio dia": "Bahia Meio Dia",
    "ge": "Globo Esporte", "globo esporte": "Globo Esporte",
    "batv": "BATV", "ba tv": "BATV",
    "bom dia sabado": "Bom Dia Sábado", "bds": "Bom Dia Sábado",
    "conexao": "Conexão Bahia", "panela": "Panela de Bairro", "mosaico": "Mosaico Baiano", "rural": "Bahia Rural",
    "6h": FAIXA, "6h as 24h": FAIXA, "6 as 24": FAIXA, "7h": FAIXA_7, "7h as 24h": FAIXA_7, "7 as 24": FAIXA_7,
}


# ---------------------------------------------------------------------------------------------- utilidades
def norm(t):
    t = unicodedata.normalize("NFKD", str(t)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9% ]+", " ", t)).strip()


def br(v, casas=2):
    return "–" if v is None or pd.isna(v) else f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def sinal(v, casas=2):
    return "–" if v is None or pd.isna(v) else ("+" if v > 0 else "") + br(v, casas)


def rot_mes(d):
    return f"{MESES[d.month - 1]}/{str(d.year)[2:]}"


def nome(p):
    return {FAIXA: "TV Bahia (6h às 24h)", FAIXA_7: "TV Bahia (7h às 24h)"}.get(p, p)


def para_html(md):
    """Markdown simples das respostas (negrito, itálico, quebras e itens) -> HTML seguro."""
    t = html.escape(md)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", t)
    linhas = []
    for l in t.split("\n"):
        m = re.match(r"^(\s*)(?:[•\-*]|\d+[.)])\s+(.*)$", l)
        if re.match(r"^#{1,6}\s+", l):
            linhas.append(f'<b class="tt">{re.sub(r"^#{1,6}\s+", "", l)}</b>')
        elif m and not l.startswith("**"):
            num = re.match(r"^\s*(\d+[.)])", l)
            cls = "sub" if len(m[1]) >= 2 else "it"
            linhas.append(f'<span class="{cls}">{(num[1] + " ") if num else ""}{m[2]}</span>')
        elif l.startswith("  ") and l.strip():
            linhas.append(f'<span class="sub">{l.strip()}</span>')
        else:
            linhas.append(l)
    out = "<br>".join(linhas)
    for tag in ("</span>", "</b>"):
        out = out.replace(tag + "<br>", tag)
    return re.sub(r"(<br>){3,}", "<br><br>", out).strip()


# ---------------------------------------------------------------------------------------------- consultas
def _serie(base, prog, met):
    s = base[(base["programa"] == prog) & (base["metrica"] == met)].set_index("mes")["valor"]
    s.index = pd.to_datetime(s.index)
    return s.dropna().sort_index()


def ultimo(base, prog, met):
    """Valor do último mês e variações vs mês anterior e vs mesmo mês do ano anterior."""
    s = _serie(base, prog, met)
    if s.empty:
        return None
    m = s.index.max()
    ant = s.get(m - pd.DateOffset(months=1))
    yoy = s.get(m - pd.DateOffset(years=1))
    return {"mes": m, "v": s[m], "dm": None if ant is None else s[m] - ant, "da": None if yoy is None else s[m] - yoy}


def programas(base):
    return [p for p in base["programa"].drop_duplicates() if p not in (FAIXA, FAIXA_7)]


def linha_rodada(rodada, prog, met):
    try:
        return rodada["fech"].loc[(prog, met)]
    except (KeyError, TypeError):
        return None


def _pct(p):
    if p is None or pd.isna(p):
        return "–"
    p *= 100
    return ">99,9%" if p > 99.9 else "<0,1%" if p < .1 else f"{br(p, 1)}%"


# ---------------------------------------------------------------------------------------------- respostas
def r_ultimo_mes(base):
    partes = []
    for prog in (FAIXA, FAIXA_7):
        a, s = ultimo(base, prog, "Audiência"), ultimo(base, prog, "Share")
        if a:
            partes.append(f"• **{nome(prog)}** em {rot_mes(a['mes'])}: audiência **{br(a['v'])}** "
                          f"({sinal(a['dm'])} pt vs mês anterior, {sinal(a['da'])} pt vs ano anterior)"
                          + (f" · share **{br(s['v'])}%** ({sinal(s['da'])} p.p. vs ano anterior)" if s else ""))
    if not partes:
        return "Ainda não há dados mensais carregados."
    return "Resumo do último mês:\n" + "\n".join(partes)


def r_ranking_variacao(base, met="Audiência", crescer=True):
    linhas = []
    for p in programas(base):
        u = ultimo(base, p, met)
        if u and u["da"] is not None:
            linhas.append((p, u["da"], u["v"], u["mes"]))
    if not linhas:
        return "Não encontrei meses suficientes para comparar com o ano anterior."
    linhas.sort(key=lambda x: x[1], reverse=crescer)
    top = [l for l in linhas if (l[1] > 0 if crescer else l[1] < 0)][:5]
    if not top:
        return ("Nenhum programa cresceu" if crescer else "Nenhum programa caiu") + \
               f" em {met.lower()} na comparação com o mesmo mês do ano anterior."
    un = "pt" if met == "Audiência" else "p.p."
    cab = ("Programas que **mais cresceram" if crescer else "Programas que **mais caíram") + \
          f"** em {met.lower()} (último mês vs mesmo mês do ano anterior):"
    return cab + "\n" + "\n".join(f"• **{p}** ({rot_mes(m)}): {br(v)}{'%' if met == 'Share' else ''} · **{sinal(d)} {un}**"
                                  for p, d, v, m in top)


def r_maior(base, met="Audiência"):
    linhas = [(p, ultimo(base, p, met)) for p in programas(base)]
    linhas = sorted([(p, u) for p, u in linhas if u], key=lambda x: x[1]["v"], reverse=True)[:5]
    if not linhas:
        return "Ainda não há dados mensais dos programas."
    suf = "%" if met == "Share" else ""
    return (f"Programas com **maior {met.lower()}** no último mês:\n" +
            "\n".join(f"• **{p}** ({rot_mes(u['mes'])}): {br(u['v'])}{suf}" for p, u in linhas))


def r_metas(base, rodada, met=None):
    if not rodada:
        return "Nenhuma rodada de projeção dos programas foi carregada ainda, então não sei as chances de meta."
    linhas = []
    for p in programas(base):
        for m in ([met] if met else ["Audiência", "Share"]):
            ln = linha_rodada(rodada, p, m)
            if ln is not None and pd.notna(ln.get("p100")):
                linhas.append((p, m, ln["p100"], ln.get("semaforo", "–")))
    if not linhas:
        return "A rodada carregada não tem chances de meta dos programas."
    linhas.sort(key=lambda x: x[2], reverse=True)
    prov = [l for l in linhas if l[2] >= .8]
    improv = [l for l in linhas if l[2] < .2]
    corte = rodada.get("meta", {}).get("corte")
    txt = f"Chance de bater a **meta 100%** em {rodada.get('meta', {}).get('ano', '')}" + \
          (f" (projeção de {corte:%d/%m})" if corte is not None else "") + ":\n"
    txt += "\n".join(f"• **{p}** · {m.lower()}: **{_pct(c)}** ({s})" for p, m, c, s in linhas[:8])
    if len(linhas) > 8:
        txt += f"\n…e mais {len(linhas) - 8}. Pergunte por um programa para ver o detalhe."
    txt += f"\n\n{len(prov)} prováveis e {len(improv)} improváveis."
    return txt


def r_programa(base, rodada, prog, met=None):
    mets = [met] if met else ["Audiência", "Share"]
    partes = []
    for m in mets:
        u = ultimo(base, prog, m)
        if not u:
            continue
        suf, un = ("%", "p.p.") if m == "Share" else ("", "pt")
        t = (f"• **{m}** em {rot_mes(u['mes'])}: **{br(u['v'])}{suf}** "
             f"({sinal(u['dm'])} {un} vs mês anterior, {sinal(u['da'])} {un} vs ano anterior)")
        ln = linha_rodada(rodada, prog, m) if prog not in (FAIXA, FAIXA_7) else None
        if ln is not None and pd.notna(ln.get("fech")):
            t += (f"\n  projeção de fechamento do ano: **{br(ln['fech'])}{suf}** "
                  f"(meta 100%: {br(ln.get('meta100'))}{suf}) · chance **{_pct(ln.get('p100'))}** · {ln.get('semaforo', '–')}")
        partes.append(t)
    if not partes:
        return f"Não encontrei dados de **{nome(prog)}**."
    extra = ("\n\nA projeção das faixas fica na aba *Projeções e metas*, seção ①." if prog in (FAIXA, FAIXA_7) else "")
    return f"**{nome(prog)}**\n" + "\n".join(partes) + extra


CONCEITOS = ("• **Audiência (Rat%)**: percentual dos domicílios da Grande Salvador com TV ligada na TV Bahia, "
             "na média do período. 1 ponto de rating = 1% dos domicílios.\n"
             "• **Share (Shr%)**: fatia da TV Bahia entre os domicílios que estavam com a TV ligada naquele momento.\n"
             "A audiência mede o tamanho do público; o share mede a disputa com as outras emissoras.")

PROJECAO = ("A projeção junta o que já aconteceu no ano com o que os modelos esperam para os meses que faltam:\n"
            "• **Faixas (6h e 7h às 24h)**: modelo **diário**, com dia da semana, feriados, jogos, horário eleitoral e Copa.\n"
            "• **Programas**: modelo **mensal**, combinando 4 modelos e validado em reprojeções do passado.\n"
            "• A **chance da meta** é a parcela de milhares de cenários simulados em que o ano fecha na meta ou acima.\n"
            "Os detalhes estão em *ⓘ Notas metodológicas*, no fim da página.")

AJUDA = ("Posso responder, por exemplo:\n"
         "• *como foi o último mês?*\n• *quais programas mais cresceram / caíram em share?*\n"
         "• *qual a chance de bater a meta?*\n• *como está o Globo Esporte?*\n"
         "• *qual programa tem a maior audiência?*\n• *o que é share?*")

NAO_SEI = ("Ainda não sei responder isso. Nesta primeira versão eu entendo perguntas sobre o último mês, "
           "crescimento ou queda, metas, ranking e cada programa. Experimente uma das sugestões.")


def _acha_programa(t, base):
    nomes = {norm(p): p for p in base["programa"].drop_duplicates()}
    for chave in sorted(list(nomes) + list(APELIDOS), key=len, reverse=True):    # o nome mais longo primeiro
        if re.search(rf"(?<![a-z0-9]){re.escape(chave)}(?![a-z0-9])", t):
            p = nomes.get(chave) or APELIDOS[chave]
            if p in nomes.values():
                return p
    return None


def responder(texto, base, rodada=None):
    """Pergunta em texto livre -> resposta em markdown simples (negrito, itálico, itens '• ')."""
    t = norm(texto)
    if not t:
        return AJUDA
    met = ("Share" if re.search(r"\bshare\b|\bshr\b|\bparticipacao\b", t) and not re.search(r"\brating\b|\baudiencia\b", t)
           else "Audiência" if re.search(r"\brating\b|\brat\b|\baudiencia\b", t) and "share" not in t else None)
    if re.search(r"\bo que (e|significa|sao)\b|\bdiferenca\b|\bsignifica\b|\bdefini", t) and \
            re.search(r"rating|share|audiencia|rat|shr", t):
        return CONCEITOS
    if re.search(r"\b(como|metodo|metodologia)\b.*\b(projec|calcul|model|feita|funciona)", t) or "metodologia" in t:
        return PROJECAO
    prog = _acha_programa(t, base)
    if prog and not re.search(r"\b(cresc|subi|cai|queda|perd|ranking|maior|lider)", t):
        return r_programa(base, rodada, prog, met)
    if re.search(r"\b(meta|metas|chance|bater|bate)\b", t):
        return r_metas(base, rodada, met)
    if re.search(r"\b(cresc\w*|subi\w*|ganh\w*|melhor\w*)\b", t):
        return r_ranking_variacao(base, met or "Audiência", crescer=True)
    if re.search(r"\b(cai\w*|caiu|queda|perd\w*|pior\w*|recu\w*)\b", t):
        return r_ranking_variacao(base, met or "Audiência", crescer=False)
    if re.search(r"\b(maior|lider\w*|ranking|top|mais assistid\w*)\b", t):
        return r_maior(base, met or "Audiência")
    if re.search(r"\b(ultimo mes|mes passado|resumo|como foi|como esta|como estamos|geral|tv bahia)\b", t):
        return r_ultimo_mes(base)
    if re.search(r"\b(oi|ola|bom dia|boa tarde|boa noite|e ai|opa)\b", t):
        return "Olá! " + AJUDA
    if re.search(r"\b(ajuda|help|o que voce|como usar|pode fazer)\b", t):
        return AJUDA
    if re.search(r"\b(obrigad\w*|valeu|show|otimo|perfeito)\b", t):
        return "Por nada! Se precisar de mais alguma coisa, é só perguntar."
    return NAO_SEI


# =====================================================================================================================
# MODO IA (Gemini) · ferramentas de consulta executadas pelo painel nos dados internos
# =====================================================================================================================
MODELO_PADRAO = "gemini-3.5-flash"
MAX_PASSOS = 6                     # consultas encadeadas por pergunta
MAX_LINHAS = 80                    # linhas devolvidas por consulta (o resto é resumido)
HISTORICO = 8                      # mensagens anteriores enviadas como contexto


class Fonte:
    """Os dados que as ferramentas consultam: base mensal, rodada mensal dos programas e rodadas diárias das faixas."""

    def __init__(self, base, rodada=None, diarias=None, demo=False):
        self.base = base.copy()
        self.base["mes"] = pd.to_datetime(self.base["mes"])
        self.rodada = rodada
        self.diarias = diarias or {}           # {faixa: [rodada mais recente primeiro, ...]} (diario.carregar_rodadas)
        self.demo = demo

    def series(self):
        return list(self.base["programa"].drop_duplicates())


def _r(v, casas=2):
    try:
        return None if v is None or pd.isna(v) else round(float(v), casas)
    except (TypeError, ValueError):
        return str(v)


def _mes_txt(d):
    return f"{d:%Y-%m}"


def _periodo(txt, padrao):
    if not txt:
        return padrao
    try:
        return pd.Timestamp(str(txt)[:7] + "-01")
    except Exception:
        return padrao


def _resolve(nomes, fonte):
    """Nomes vindos do modelo (com ou sem acento, apelidos) -> nomes da base."""
    if not nomes:
        return []
    if isinstance(nomes, str):
        nomes = [nomes]
    validos = fonte.series()
    out = []
    for n in nomes:
        alvo = _acha_programa(norm(n), fonte.base) or next((v for v in validos if norm(v) == norm(n)), None)
        if alvo and alvo not in out:
            out.append(alvo)
    return out


def _metricas(m):
    return ["Audiência", "Share"] if not m or m == "ambas" else [m]


def f_serie_mensal(fonte, series=None, metrica="ambas", inicio=None, fim=None, agregar="mes"):
    progs = _resolve(series, fonte) or [FAIXA]
    b = fonte.base
    fim_ = _periodo(fim, b["mes"].max())
    ini_ = _periodo(inicio, fim_ - pd.DateOffset(months=11))
    d = b[b["programa"].isin(progs) & b["metrica"].isin(_metricas(metrica)) & b["mes"].between(ini_, fim_)]
    if agregar == "ano":
        d = d.assign(ano=d["mes"].dt.year).groupby(["programa", "metrica", "ano"], as_index=False).agg(
            media=("valor", "mean"), meses=("valor", "size"))
        linhas = [{"serie": r.programa, "metrica": r.metrica, "ano": int(r.ano), "media_simples_dos_meses": _r(r.media),
                   "meses_com_dado": int(r.meses)} for r in d.itertuples()]
    else:
        d = d.sort_values(["programa", "metrica", "mes"])
        linhas = [{"serie": r.programa, "metrica": r.metrica, "mes": _mes_txt(r.mes), "valor": _r(r.valor)} for r in d.itertuples()]
    return {"series": progs, "periodo": f"{_mes_txt(ini_)} a {_mes_txt(fim_)}", "linhas": linhas}


def f_ranking(fonte, metrica="Audiência", criterio="valor", mes=None, ordem="desc", limite=10, incluir_faixas=False):
    b = fonte.base
    met = metrica if metrica in ("Audiência", "Share") else "Audiência"
    alvo = _periodo(mes, None)
    linhas = []
    for p in fonte.series():
        if p in (FAIXA, FAIXA_7) and not incluir_faixas:
            continue
        s = _serie(b, p, met)
        if s.empty:
            continue
        m = alvo if alvo is not None and alvo in s.index else s.index.max()
        v = s[m]
        dm = s.get(m - pd.DateOffset(months=1))
        da = s.get(m - pd.DateOffset(years=1))
        ano = s[(s.index.year == m.year) & (s.index <= m)].mean()
        linhas.append({"serie": p, "mes": _mes_txt(m), "valor": _r(v), "var_mes_anterior": _r(None if dm is None else v - dm),
                       "var_ano_anterior": _r(None if da is None else v - da), "media_ano_ate_o_mes": _r(ano)})
    chave = {"valor": "valor", "var_mes_anterior": "var_mes_anterior", "var_ano_anterior": "var_ano_anterior",
             "media_ano": "media_ano_ate_o_mes"}.get(criterio, "valor")
    linhas = [l for l in linhas if l[chave] is not None]
    linhas.sort(key=lambda l: l[chave], reverse=(ordem != "asc"))
    return {"metrica": met, "criterio": chave, "linhas": linhas[:max(1, min(int(limite or 10), 30))]}


def f_projecao_programas(fonte, programas=None, metrica="ambas"):
    R = fonte.rodada
    if not R or "fech" not in R:
        return {"erro": "nenhuma rodada de projeção dos programas carregada"}
    F = R["fech"]
    progs = _resolve(programas, fonte) or [p for p in F.index.get_level_values(0).unique() if p not in (FAIXA, FAIXA_7)]
    linhas = []
    for p in progs:
        for m in _metricas(metrica):
            try:
                x = F.loc[(p, m)]
            except KeyError:
                continue
            linhas.append({"programa": p, "metrica": m, "acumulado_ate_corte": _r(x.get("acum")),
                           "fechamento_projetado": _r(x.get("fech")), "faixa80": [_r(x.get("ic_inf")), _r(x.get("ic_sup"))],
                           "media_projetada_meses_restantes": _r(x.get("proj_rest")),
                           "meta75": _r(x.get("meta75")), "chance_meta75": _r(x.get("p75"), 4),
                           "meta100": _r(x.get("meta100")), "chance_meta100": _r(x.get("p100"), 4),
                           "media_necessaria_meta100": _r(x.get("nec100")),
                           "meta120": _r(x.get("meta120")), "chance_meta120": _r(x.get("p120"), 4),
                           "semaforo_meta100": x.get("semaforo"), "erro_medio_historico": _r(x.get("mae"))})
    meta = R.get("meta", {})
    return {"modelo": "mensal (programas)", "dados_ate": f"{meta['corte']:%Y-%m-%d}" if meta.get("corte") is not None else None,
            "meses_restantes": meta.get("meses_rest"), "ano": meta.get("ano"), "linhas": linhas}


def f_projecao_faixa(fonte, faixa=FAIXA, incluir_meses=True):
    fx = _resolve(faixa, fonte)
    fx = fx[0] if fx and fx[0] in (FAIXA, FAIXA_7) else FAIXA
    lista = fonte.diarias.get(fx) or []
    if not lista:
        return {"faixa": fx, "erro": "nenhuma rodada do modelo diário carregada para esta faixa"}
    r = lista[0]
    linhas = []
    for m, x in r["res"].iterrows():
        linhas.append({"metrica": m, "fechamento_projetado": _r(x.get("fechamento")),
                       "faixa80": [_r(x.get("IC80 inf")), _r(x.get("IC80 sup"))],
                       "meta75": _r(x.get("meta 75%")), "chance_meta75": _r(x.get("P(75%)"), 4),
                       "meta100": _r(x.get("meta 100%")), "chance_meta100": _r(x.get("P(100%)"), 4),
                       "meta120": _r(x.get("meta 120%")), "chance_meta120": _r(x.get("P(120%)"), 4),
                       "media_necessaria_dias_restantes": _r(x.get("média nec. 100% (dias restantes)")),
                       "media_projetada_dias_restantes": _r(x.get("média proj. (dias restantes)")),
                       "semaforo_meta100": x.get("semáforo 100%")})
    out = {"faixa": fx, "modelo": "diário", "dados_ate": f"{r['corte']:%Y-%m-%d}" if r.get("corte") is not None else None,
           "linhas": linhas}
    if incluir_meses and r.get("mensal") is not None:
        out["meses_projetados"] = [{"metrica": x["métrica"], "mes": _mes_txt(x["mes"]), "projecao": _r(x["projeção"]),
                                    "faixa80": [_r(x.get("IC80 inf")), _r(x.get("IC80 sup"))]}
                                   for _, x in r["mensal"].dropna(subset=["mes"]).iterrows()]
    return out


def f_comparar_periodos(fonte, series=None, metrica="ambas", a_inicio=None, a_fim=None, b_inicio=None, b_fim=None):
    progs = _resolve(series, fonte) or [FAIXA]
    b = fonte.base
    ult = b["mes"].max()
    pa = (_periodo(a_inicio, pd.Timestamp(ult.year, 1, 1)), _periodo(a_fim, ult))
    pb = (_periodo(b_inicio, pa[0] - pd.DateOffset(years=1)), _periodo(b_fim, pa[1] - pd.DateOffset(years=1)))
    linhas = []
    for p in progs:
        for m in _metricas(metrica):
            s = _serie(b, p, m)
            va, vb = s[(s.index >= pa[0]) & (s.index <= pa[1])], s[(s.index >= pb[0]) & (s.index <= pb[1])]
            linhas.append({"serie": p, "metrica": m, "media_a": _r(va.mean() if len(va) else None), "meses_a": len(va),
                           "media_b": _r(vb.mean() if len(vb) else None), "meses_b": len(vb),
                           "diferenca_a_menos_b": _r(va.mean() - vb.mean() if len(va) and len(vb) else None)})
    return {"periodo_a": f"{_mes_txt(pa[0])} a {_mes_txt(pa[1])}", "periodo_b": f"{_mes_txt(pb[0])} a {_mes_txt(pb[1])}",
            "observacao": "médias simples dos meses", "linhas": linhas}


_SERIES_TXT = "Nome da faixa ou do programa, como aparece no catálogo (ex.: 'BATV', '6h às 24h')."
FERRAMENTAS = {
    "serie_mensal": (f_serie_mensal, "Valores mensais (realizados) de audiência e/ou share de faixas e programas num período. "
                     "Use agregar='ano' para médias por ano.", {
        "series": {"type": "array", "items": {"type": "string"}, "description": _SERIES_TXT},
        "metrica": {"type": "string", "enum": ["Audiência", "Share", "ambas"]},
        "inicio": {"type": "string", "description": "Mês inicial AAAA-MM (padrão: 11 meses antes do fim)."},
        "fim": {"type": "string", "description": "Mês final AAAA-MM (padrão: último mês com dado)."},
        "agregar": {"type": "string", "enum": ["mes", "ano"]}}, ["series"]),
    "ranking": (f_ranking, "Ordena os programas de um mês por valor, variação vs mês anterior, variação vs mesmo mês do ano "
                "anterior ou média do ano até o mês.", {
        "metrica": {"type": "string", "enum": ["Audiência", "Share"]},
        "criterio": {"type": "string", "enum": ["valor", "var_mes_anterior", "var_ano_anterior", "media_ano"]},
        "mes": {"type": "string", "description": "Mês AAAA-MM (padrão: último mês de cada programa)."},
        "ordem": {"type": "string", "enum": ["desc", "asc"]},
        "limite": {"type": "integer"},
        "incluir_faixas": {"type": "boolean"}}, ["metrica", "criterio"]),
    "projecao_programas": (f_projecao_programas, "Projeção do ano dos PROGRAMAS (modelo mensal): fechamento projetado, faixa "
                           "de 80%, metas 75/100/120%, chance de cada meta, média necessária e semáforo.", {
        "programas": {"type": "array", "items": {"type": "string"}, "description": "Vazio = todos os programas."},
        "metrica": {"type": "string", "enum": ["Audiência", "Share", "ambas"]}}, []),
    "projecao_faixa": (f_projecao_faixa, "Projeção do ano das FAIXAS 6h às 24h ou 7h às 24h (modelo diário): fechamento, metas, "
                       "chances, média necessária nos dias restantes e projeção dos meses que faltam.", {
        "faixa": {"type": "string", "enum": [FAIXA, FAIXA_7]},
        "incluir_meses": {"type": "boolean"}}, ["faixa"]),
    "comparar_periodos": (f_comparar_periodos, "Compara a média de dois períodos (padrão: o ano até o último mês vs o mesmo "
                          "período do ano anterior).", {
        "series": {"type": "array", "items": {"type": "string"}, "description": _SERIES_TXT},
        "metrica": {"type": "string", "enum": ["Audiência", "Share", "ambas"]},
        "a_inicio": {"type": "string", "description": "AAAA-MM"}, "a_fim": {"type": "string", "description": "AAAA-MM"},
        "b_inicio": {"type": "string", "description": "AAAA-MM"}, "b_fim": {"type": "string", "description": "AAAA-MM"}},
        ["series"]),
}


def executar(nome, args, fonte):
    """Roda uma ferramenta com os argumentos do modelo. Nunca levanta exceção: erros voltam como {'erro': ...}."""
    if nome not in FERRAMENTAS:
        return {"erro": f"ferramenta desconhecida: {nome}"}
    func, _, props, _ = FERRAMENTAS[nome]
    limpos = {k: v for k, v in (args or {}).items() if k in props}
    try:
        out = func(fonte, **limpos)
    except Exception as ex:
        return {"erro": f"falha na consulta ({ex.__class__.__name__})"}
    if isinstance(out.get("linhas"), list) and len(out["linhas"]) > MAX_LINHAS:
        n = len(out["linhas"])
        out["linhas"] = out["linhas"][:MAX_LINHAS]
        out["aviso"] = f"mostrando {MAX_LINHAS} de {n} linhas; refine o período ou as séries"
    return out


def instrucoes(fonte):
    b = fonte.base
    ini, fim = (b["mes"].min(), b["mes"].max()) if len(b) else (None, None)
    R = fonte.rodada or {}
    corte = R.get("meta", {}).get("corte")
    diar = {fx: f"{l[0]['corte']:%d/%m/%Y}" for fx, l in fonte.diarias.items() if l and l[0].get("corte") is not None}
    from_dias = ", ".join(f"{p}" for p in fonte.series())
    return f"""Você é o assistente do Painel de Audiência de TV da Rede Bahia (TV Bahia, afiliada Globo).
Responda em português do Brasil, de forma curta e direta, para analistas de pesquisa, jornalismo e comercial.

DADOS (consulte SEMPRE pelas ferramentas; nunca invente números):
- Audiência (Rat%) e share (Shr%) mensais da TV Bahia, TT Domicílios, Grande Salvador, Kantar IBOPE (Instar).
- Séries disponíveis: {from_dias}.
- "6h às 24h" e "7h às 24h" são as FAIXAS (a emissora no dia todo); os demais são programas locais.
- Meses com dado: {_mes_txt(ini) if ini is not None else '–'} a {_mes_txt(fim) if fim is not None else '–'}.
- Projeção dos programas (modelo mensal): dados até {f"{corte:%d/%m/%Y}" if corte is not None else 'sem rodada'}.
- Projeção das faixas (modelo diário): {diar or 'sem rodada'}.
{"- ATENÇÃO: estes são DADOS FICTÍCIOS de demonstração." if fonte.demo else ""}

CONCEITOS: audiência = % dos domicílios com TV sintonizada na TV Bahia; share = fatia da TV Bahia entre os domicílios com
TV ligada. Variações de audiência em pontos (pt); de share em pontos percentuais (p.p.). A chance da meta é a parcela dos
cenários simulados em que o ano fecha na meta ou acima. Semáforo da meta 100%: provável, indefinido, improvável
(faixas também têm "muito provável" e "muito improvável").

COMO RESPONDER:
1. Use as ferramentas para buscar exatamente o que a pergunta pede (pode chamar mais de uma).
2. Comece pela resposta, com os números principais (formato brasileiro: 14,20; 36,7%; mês como set/26).
3. Depois, em 1 a 3 itens curtos, uma LEITURA com insights apoiados nos dados: tendência, comparação com o ano anterior,
   o que falta para a meta, riscos. Não especule causas que os dados não mostram; se sugerir uma hipótese, diga que é hipótese.
4. Sem tabelas e sem títulos grandes (o quadro é estreito); use itens com "- " e **negrito** nos números-chave.
5. Se o dado não existe nas ferramentas, diga que o painel não tem essa informação.
6. Fora do tema audiência/painel, recuse em uma frase e diga o que você consegue responder."""


def _declaracoes():
    from google.genai import types
    return [types.Tool(function_declarations=[
        types.FunctionDeclaration(name=n, description=d, parameters_json_schema={"type": "object", "properties": p, "required": r})
        for n, (_, d, p, r) in FERRAMENTAS.items()])]


def _texto(resp):
    partes = []
    for c in (resp.candidates or [])[:1]:
        for pt in (c.content.parts if c.content and c.content.parts else []):
            if getattr(pt, "text", None) and not getattr(pt, "thought", False):
                partes.append(pt.text)
    return "".join(partes).strip()


def perguntar_ia(pergunta, fonte, chave, modelo=None, historico=(), cliente=None):
    """Pergunta -> (resposta em markdown, consultas feitas [{'ferramenta', 'args'}]). Levanta exceção se a API falhar."""
    from google import genai
    from google.genai import types
    cli = cliente or genai.Client(api_key=chave)
    conteudos = [types.Content(role="user" if q == "eu" else "model", parts=[types.Part(text=t)])
                 for q, t in list(historico)[-HISTORICO:] if t]
    conteudos.append(types.Content(role="user", parts=[types.Part(text=pergunta)]))
    cfg = types.GenerateContentConfig(system_instruction=instrucoes(fonte), tools=_declaracoes(),
                                      automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
    consultas = []
    for _ in range(MAX_PASSOS):
        resp = cli.models.generate_content(model=modelo or MODELO_PADRAO, contents=conteudos, config=cfg)
        chamadas = resp.function_calls or []
        if not chamadas:
            txt = _texto(resp)
            return (txt or "Não consegui formular uma resposta. Tente perguntar de outro jeito."), consultas
        conteudos.append(resp.candidates[0].content)        # mantém a vez do modelo como veio (inclui assinaturas)
        partes = []
        for ch in chamadas:
            args = dict(ch.args or {})
            consultas.append({"ferramenta": ch.name, "args": args})
            partes.append(types.Part.from_function_response(name=ch.name, response=executar(ch.name, args, fonte)))
        conteudos.append(types.Content(role="user", parts=partes))
    # passou do limite de consultas: pede a resposta final sem ferramentas
    cfg_final = types.GenerateContentConfig(system_instruction=instrucoes(fonte))
    resp = cli.models.generate_content(model=modelo or MODELO_PADRAO, contents=conteudos, config=cfg_final)
    return (_texto(resp) or "A pergunta exigiu consultas demais. Tente algo mais específico."), consultas


def descreve_consulta(c):
    """Texto curto de uma consulta, para o item 'Como cheguei nisso'."""
    nomes = {"serie_mensal": "Série mensal", "ranking": "Ranking", "projecao_programas": "Projeção dos programas",
             "projecao_faixa": "Projeção da faixa", "comparar_periodos": "Comparação de períodos"}
    a = c.get("args") or {}
    det = " · ".join(f"{k}: {', '.join(map(str, v)) if isinstance(v, list) else v}" for k, v in a.items() if v not in (None, "", []))
    return f"{nomes.get(c.get('ferramenta'), c.get('ferramenta'))}" + (f" ({det})" if det else "")
