"""Assistente do painel de TV · fase 1: respostas PRONTAS, calculadas com os dados do próprio painel (sem IA).

A interface (streamlit_app.py) só chama `responder(texto, base, rodada)`. Na fase 2, essa mesma função passa a chamar o
LLM (Gemini) com as consultas como ferramentas; a interface não muda.
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
        linhas.append(f'<span class="it">{l[2:]}</span>' if l.startswith("• ") else
                      f'<span class="sub">{l[2:]}</span>' if l.startswith("  ") else l)
    return "<br>".join(linhas).replace("</span><br>", "</span>")


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
