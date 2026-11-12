"""PIPECO · assistente do painel de TV.

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

SUGESTOES = ["Como foi o último mês?", "Concorrência no último mês", "Quais programas mais cresceram?", "Chance de bater a meta",
             "Maior audiência", "O que é rating e share?", "Como a projeção é feita?"]

BOAS_VINDAS = ("Olá! Sou o **PIPECO**, o assistente do painel. Pergunte sobre a **audiência** e o **share** da TV Bahia, "
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


def r_concorrencia(conc, rec=FAIXA, met="Share"):
    if conc is None or len(conc) == 0:
        return "O painel ainda não tem dados de concorrência. Eles são enviados em ⚙ Atualizar dados → Concorrência."
    f = Fonte(pd.DataFrame(columns=["programa", "metrica", "mes", "valor"]), conc=conc)
    r = f_conc_ranking(f, rec, met)
    if r.get("erro"):
        return r["erro"]
    suf = "%" if met == "Share" else ""
    txt = f"**Concorrência** · {r['recorte']} · {met.lower()} em {_mes_rot(r['mes'])}:\n" + "\n".join(
        f"• {l['posicao']}º **{l['emissora']}**: {br(l['valor'])}{suf}"
        + (f" ({sinal(l['var_ano_anterior'])} vs ano anterior)" if l.get("var_ano_anterior") is not None else "")
        for l in r["linhas"] if l.get("posicao"))
    if r.get("vantagem_tv_bahia_sobre_melhor_concorrente") is not None:
        v = r["vantagem_tv_bahia_sobre_melhor_concorrente"]
        txt += (f"\n\nA TV Bahia está **{br(abs(v))} {r['unidade']} {'à frente' if v >= 0 else 'atrás'}** da "
                f"{r['melhor_concorrente']}" + (f" (um ano antes: {sinal(r['vantagem_um_ano_antes'])})."
                                                if r.get("vantagem_um_ano_antes") is not None else "."))
    return txt


def responder(texto, base, rodada=None, conc=None):
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
    eh_conc = re.search(r"\b(concorr\w*|emissoras?|vantagem|vice|segunda colocada|lideranca|outras emissoras)\b", t)
    if not eh_conc and conc is not None and len(conc):
        eh_conc = any(norm(e) in t for e in set(conc["emissora"]) if norm(e) not in ("tv bahia globo",))
    if eh_conc:
        rec = _acha_programa(t, base) if len(base) else None
        return r_concorrencia(conc, rec or FAIXA, "Audiência" if met == "Audiência" else "Share")
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
MODELO_RESERVA = "gemini-3.5-flash-lite"   # entra quando o principal cai ou estoura o limite de requisições
# erros que justificam tentar o modelo reserva: modelo inexistente, tempo esgotado, limite de requisições, servidor fora
CODIGOS_RESERVA = {404, 408, 429, 500, 502, 503, 504}
PAUSA_PRINCIPAL = {429: 60, 503: 60, 500: 30, 502: 30, 504: 30, 408: 30, 404: 600}   # segundos usando só a reserva
_ESTADO = {"principal_pausado_ate": 0.0}  # vale para o servidor todo: o limite de requisições é da chave, não da sessão
MAX_PASSOS = 6                     # consultas encadeadas por pergunta
MAX_LINHAS = 80                    # linhas devolvidas por consulta (o resto é resumido)
HISTORICO = 8                      # mensagens anteriores enviadas como contexto


class Fonte:
    """Os dados que as ferramentas consultam: base mensal, rodada mensal dos programas e rodadas diárias das faixas."""

    def __init__(self, base, rodada=None, diarias=None, demo=False, conc=None):
        self.base = base.copy()
        self.base["mes"] = pd.to_datetime(self.base["mes"])
        self.rodada = rodada
        self.diarias = diarias or {}           # {faixa: [rodada mais recente primeiro, ...]} (diario.carregar_rodadas)
        self.demo = demo
        c = conc.copy() if conc is not None else pd.DataFrame(columns=["mes", "recorte", "emissora", "rat", "shr"])
        c["mes"] = pd.to_datetime(c["mes"])
        self.conc = c                          # concorrência: mês × recorte × emissora (rat, shr)

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


TVB, OUTRAS = "TV Bahia (Globo)", "Outras emissoras"      # mesmos nomes do concorrencia.py


def _rec(fonte, recorte):
    """Recorte pedido -> nome da base de concorrência (faixa ou programa = horário do programa)."""
    recs = list(dict.fromkeys(fonte.conc["recorte"]))
    if recorte in recs:
        return recorte
    alvo = (_resolve(recorte, fonte) or [None])[0] if recorte else None
    return alvo if alvo in recs else (FAIXA if FAIXA in recs else (recs[0] if recs else None))


def _emis(fonte, nomes):
    todas = list(dict.fromkeys(fonte.conc["emissora"]))
    if not nomes:
        return todas
    out = []
    for n in ([nomes] if isinstance(nomes, str) else nomes):
        t = norm(n)
        alvo = TVB if t in ("globo", "tv bahia", "rede globo", "tv bahia globo") else \
            next((e for e in todas if norm(e) == t), None) or next((e for e in todas if t and t in norm(e)), None)
        if alvo and alvo not in out:
            out.append(alvo)
    return out


def _col(metrica):
    return ("shr", "p.p.") if metrica != "Audiência" else ("rat", "pt")


def _vantagem(g, col):
    """Linhas de um mês × recorte (índice = emissora) -> (vantagem da TV Bahia, melhor concorrente) ou (None, None)."""
    rivais = g.drop([TVB, OUTRAS], errors="ignore")[col].dropna()
    if TVB not in g.index or rivais.empty:
        return None, None
    return float(g.loc[TVB, col] - rivais.max()), rivais.idxmax()


def f_conc_ranking(fonte, recorte=None, metrica="Share", mes=None):
    C = fonte.conc
    if C.empty:
        return {"erro": "o painel não tem dados de concorrência carregados"}
    rec = _rec(fonte, recorte)
    D = C[C["recorte"] == rec]
    alvo = _periodo(mes, D["mes"].max())
    alvo = alvo if alvo in set(D["mes"]) else D["mes"].max()
    col, un = _col(metrica)
    U = D[D["mes"] == alvo].set_index("emissora")
    A = D[D["mes"] == alvo - pd.DateOffset(years=1)].set_index("emissora")
    M = D[D["mes"] == alvo - pd.DateOffset(months=1)].set_index("emissora")
    ordem = [e for e in U.sort_values(col, ascending=False).index if e != OUTRAS]
    linhas = [{"posicao": k + 1, "emissora": e, "valor": _r(U.loc[e, col]),
               "var_mes_anterior": _r(U.loc[e, col] - M.loc[e, col]) if e in M.index else None,
               "var_ano_anterior": _r(U.loc[e, col] - A.loc[e, col]) if e in A.index else None} for k, e in enumerate(ordem)]
    if OUTRAS in U.index:
        linhas.append({"posicao": None, "emissora": OUTRAS, "valor": _r(U.loc[OUTRAS, col]), "agregado": True})
    van, quem = _vantagem(U, col)
    van_a, _ = _vantagem(A, col) if len(A) else (None, None)
    return {"recorte": rec if rec in (FAIXA, FAIXA_7) else f"horário do {rec}", "metrica": metrica, "unidade": un,
            "mes": _mes_txt(alvo), "lider": ordem[0] if ordem else None,
            "vantagem_tv_bahia_sobre_melhor_concorrente": _r(van), "melhor_concorrente": quem,
            "vantagem_um_ano_antes": _r(van_a), "linhas": linhas}


def f_conc_serie(fonte, recorte=None, emissoras=None, metrica="Share", inicio=None, fim=None):
    C = fonte.conc
    if C.empty:
        return {"erro": "o painel não tem dados de concorrência carregados"}
    rec = _rec(fonte, recorte)
    D = C[C["recorte"] == rec]
    col, un = _col(metrica)
    fim_ = _periodo(fim, D["mes"].max())
    ini_ = _periodo(inicio, fim_ - pd.DateOffset(months=11))
    ems = _emis(fonte, emissoras)
    D = D[D["emissora"].isin(ems) & D["mes"].between(ini_, fim_)].sort_values(["emissora", "mes"])
    return {"recorte": rec if rec in (FAIXA, FAIXA_7) else f"horário do {rec}", "metrica": metrica, "unidade": un,
            "periodo": f"{_mes_txt(ini_)} a {_mes_txt(fim_)}",
            "linhas": [{"emissora": r.emissora, "mes": _mes_txt(r.mes), "valor": _r(getattr(r, col))} for r in D.itertuples()]}


def f_conc_vantagem(fonte, recorte=None, metrica="Share", mes=None, inicio=None, fim=None):
    """Com recorte: a vantagem mês a mês. Sem recorte (ou 'todos'): todos os recortes num mês."""
    C = fonte.conc
    if C.empty:
        return {"erro": "o painel não tem dados de concorrência carregados"}
    col, un = _col(metrica)
    linhas = []
    if recorte and norm(recorte) not in ("todos", "todos os horarios", "todos os recortes"):
        rec = _rec(fonte, recorte)
        D = C[C["recorte"] == rec]
        fim_ = _periodo(fim, D["mes"].max())
        ini_ = _periodo(inicio, fim_ - pd.DateOffset(months=11))
        for m, g in D[D["mes"].between(ini_, fim_)].groupby("mes"):
            van, quem = _vantagem(g.set_index("emissora"), col)
            if van is not None:
                linhas.append({"mes": _mes_txt(m), "vantagem": _r(van), "melhor_concorrente": quem})
        return {"modo": "por mês", "recorte": rec if rec in (FAIXA, FAIXA_7) else f"horário do {rec}", "metrica": metrica,
                "unidade": un, "periodo": f"{_mes_txt(ini_)} a {_mes_txt(fim_)}", "linhas": linhas}
    alvo = _periodo(mes, C["mes"].max())
    alvo = alvo if alvo in set(C["mes"]) else C["mes"].max()
    U = C[C["mes"] == alvo]
    A = C[C["mes"] == alvo - pd.DateOffset(years=1)]
    for rec, g in U.groupby("recorte"):
        van, quem = _vantagem(g.set_index("emissora"), col)
        if van is None:
            continue
        ga = A[A["recorte"] == rec].set_index("emissora")
        van_a, _ = _vantagem(ga, col) if len(ga) else (None, None)
        linhas.append({"recorte": rec if rec in (FAIXA, FAIXA_7) else f"horário do {rec}", "vantagem": _r(van),
                       "melhor_concorrente": quem, "vantagem_um_ano_antes": _r(van_a),
                       "valor_tv_bahia": _r(g.set_index("emissora").loc[TVB, col])})
    linhas.sort(key=lambda l: l["vantagem"])
    return {"modo": "todos os recortes", "mes": _mes_txt(alvo), "metrica": metrica, "unidade": un, "linhas": linhas}


_SERIES_TXT = "Nome da faixa ou do programa, como aparece no catálogo (ex.: 'BATV', '6h às 24h')."
_REC_TXT = ("Faixa ('6h às 24h', '7h às 24h') ou nome de um programa local, que significa o HORÁRIO do programa "
            "(ex.: 'BATV' = o que cada emissora marcou no horário do BATV). Padrão: 6h às 24h.")
FERRAMENTAS = {
    "concorrencia_ranking": (f_conc_ranking, "CONCORRÊNCIA: ranking das emissoras (TV Bahia e concorrentes) num mês e recorte, "
                             "com variações vs mês anterior e vs ano anterior, a líder e a vantagem da TV Bahia sobre a melhor "
                             "concorrente.", {
        "recorte": {"type": "string", "description": _REC_TXT},
        "metrica": {"type": "string", "enum": ["Share", "Audiência"]},
        "mes": {"type": "string", "description": "AAAA-MM (padrão: o mais recente)."}}, []),
    "concorrencia_serie": (f_conc_serie, "CONCORRÊNCIA: valores mensais de audiência ou share das emissoras num recorte e período.", {
        "recorte": {"type": "string", "description": _REC_TXT},
        "emissoras": {"type": "array", "items": {"type": "string"}, "description": "Vazio = todas."},
        "metrica": {"type": "string", "enum": ["Share", "Audiência"]},
        "inicio": {"type": "string", "description": "AAAA-MM"}, "fim": {"type": "string", "description": "AAAA-MM"}}, []),
    "concorrencia_vantagem": (f_conc_vantagem, "CONCORRÊNCIA: vantagem da TV Bahia sobre a melhor concorrente (positiva = TV Bahia "
                              "na frente). Com recorte: mês a mês no período. Com recorte='todos': todos os horários num mês, "
                              "do mais apertado ao mais folgado, com a vantagem de um ano antes.", {
        "recorte": {"type": "string", "description": _REC_TXT + " Use 'todos' para comparar os horários."},
        "metrica": {"type": "string", "enum": ["Share", "Audiência"]},
        "mes": {"type": "string", "description": "AAAA-MM (modo todos os horários)"},
        "inicio": {"type": "string", "description": "AAAA-MM"}, "fim": {"type": "string", "description": "AAAA-MM"}}, []),
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
    C = fonte.conc
    conc_txt = (f"- CONCORRÊNCIA (ferramentas concorrencia_*): {', '.join(dict.fromkeys(C['emissora']))}; "
                f"{_mes_txt(C['mes'].min())} a {_mes_txt(C['mes'].max())}; recortes: {', '.join(dict.fromkeys(C['recorte']))} "
                f"(um programa = o horário dele). '{OUTRAS}' é um agregado (TV paga e demais), fora do ranking.\n"
                if len(C) else "- CONCORRÊNCIA: sem dados carregados no painel.\n")
    return f"""Você é o PIPECO, o assistente do Painel de Audiência de TV da Rede Bahia (TV Bahia, afiliada Globo).
Se perguntarem quem você é, apresente-se como PIPECO.
Responda em português do Brasil, de forma curta e direta, para analistas de pesquisa, jornalismo e comercial.

DADOS (consulte SEMPRE pelas ferramentas; nunca invente números):
- Audiência (Rat%) e share (Shr%) mensais da TV Bahia, TT Domicílios, Grande Salvador, Kantar IBOPE (Instar).
- Séries disponíveis: {from_dias}.
- "6h às 24h" e "7h às 24h" são as FAIXAS (a emissora no dia todo); os demais são programas locais.
- Meses com dado: {_mes_txt(ini) if ini is not None else '–'} a {_mes_txt(fim) if fim is not None else '–'}.
{conc_txt.rstrip()}
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


def _pergunta_um_modelo(cli, modelo, conteudos_ini, fonte):
    from google.genai import types
    conteudos = list(conteudos_ini)
    cfg = types.GenerateContentConfig(system_instruction=instrucoes(fonte), tools=_declaracoes(),
                                      automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
    consultas = []
    for _ in range(MAX_PASSOS):
        resp = cli.models.generate_content(model=modelo, contents=conteudos, config=cfg)
        chamadas = resp.function_calls or []
        if not chamadas:
            txt = _texto(resp)
            return (txt or "Não consegui formular uma resposta. Tente perguntar de outro jeito."), consultas
        conteudos.append(resp.candidates[0].content)        # mantém a vez do modelo como veio (inclui assinaturas)
        partes = []
        for ch in chamadas:
            args = dict(ch.args or {})
            res = executar(ch.name, args, fonte)
            consultas.append({"ferramenta": ch.name, "args": args, "resultado": res})     # o resultado também alimenta o gráfico
            partes.append(types.Part.from_function_response(name=ch.name, response=res))
        conteudos.append(types.Content(role="user", parts=partes))
    # passou do limite de consultas: pede a resposta final sem ferramentas
    resp = cli.models.generate_content(model=modelo, contents=conteudos,
                                       config=types.GenerateContentConfig(system_instruction=instrucoes(fonte)))
    return (_texto(resp) or "A pergunta exigiu consultas demais. Tente algo mais específico."), consultas


def _justifica_reserva(ex):
    """Erro em que vale tentar o modelo reserva? Devolve o código (ou 0 para falhas de rede), ou None."""
    codigo = getattr(ex, "code", None)
    if isinstance(codigo, int):
        return codigo if codigo in CODIGOS_RESERVA else None
    nome = ex.__class__.__name__.lower()
    return 0 if ("timeout" in nome or "connect" in nome or "network" in nome) else None


def perguntar_ia(pergunta, fonte, chave, modelo=None, historico=(), cliente=None, reserva=None, agora=None):
    """Pergunta -> (resposta em markdown, consultas [{'ferramenta', 'args'}], modelo que respondeu).

    Tenta o modelo principal; se ele cair ou estourar o limite (429, 5xx, tempo esgotado, modelo inexistente), refaz a
    pergunta do zero no modelo reserva e deixa o principal em pausa por alguns segundos. Levanta exceção se os dois falharem."""
    import time
    from google import genai
    from google.genai import types
    agora = agora if agora is not None else time.time()
    cli = cliente or genai.Client(api_key=chave)
    principal, reserva = modelo or MODELO_PADRAO, reserva if reserva is not None else MODELO_RESERVA
    conteudos = [types.Content(role="user" if q == "eu" else "model", parts=[types.Part(text=t)])
                 for q, t in list(historico)[-HISTORICO:] if t]
    conteudos.append(types.Content(role="user", parts=[types.Part(text=pergunta)]))
    ordem = [principal] if not reserva or reserva == principal else (
        [reserva] if agora < _ESTADO["principal_pausado_ate"] else [principal, reserva])
    for k, mod in enumerate(ordem):
        try:
            txt, consultas = _pergunta_um_modelo(cli, mod, conteudos, fonte)
            return txt, consultas, mod
        except Exception as ex:
            codigo = _justifica_reserva(ex)
            ultimo = k == len(ordem) - 1
            if mod == principal and codigo is not None:
                _ESTADO["principal_pausado_ate"] = agora + PAUSA_PRINCIPAL.get(codigo, 30)
            if ultimo or codigo is None:
                raise
    raise RuntimeError("nenhum modelo disponível")


def descreve_consulta(c):
    """Texto curto de uma consulta, para o item 'Como cheguei nisso'."""
    nomes = {"serie_mensal": "Série mensal", "ranking": "Ranking", "projecao_programas": "Projeção dos programas",
             "projecao_faixa": "Projeção da faixa", "comparar_periodos": "Comparação de períodos",
             "concorrencia_ranking": "Concorrência · ranking", "concorrencia_serie": "Concorrência · série",
             "concorrencia_vantagem": "Concorrência · vantagem"}
    a = c.get("args") or {}
    det = " · ".join(f"{k}: {', '.join(map(str, v)) if isinstance(v, list) else v}" for k, v in a.items() if v not in (None, "", []))
    return f"{nomes.get(c.get('ferramenta'), c.get('ferramenta'))}" + (f" ({det})" if det else "")


# =====================================================================================================================
# GRÁFICOS DAS RESPOSTAS · SVG desenhado com os resultados das próprias consultas (os números são os mesmos da resposta)
# =====================================================================================================================
PALETA = ["#2a78d6", "#eb6834", "#7b5cff", "#1baf7a", "#e87ba4", "#eda100", "#00a3a3", "#8a8984"]
COR_SOBE, COR_DESCE = "#1baf7a", "#e34948"
COR_SEMAFORO = {"muito provável": "#005f00", "provável": "#008300", "indefinido": "#eda100", "improvável": "#e34948",
                "muito improvável": "#a8302f"}
_L, _ALT_LIN = 300, 150          # largura do desenho e altura da área das linhas (o SVG se ajusta à largura da bolha)


def _esc(t):
    return html.escape(str(t), quote=True)


def _curto(t, n=17):
    t = str(t)
    return t if len(t) <= n else t[:n - 1] + "…"


def _escala(vals, zero=False):
    v = [x for x in vals if x is not None and pd.notna(x)]
    if not v:
        return 0, 1
    lo, hi = min(v), max(v)
    if zero:
        lo, hi = min(lo, 0), max(hi, 0)
    if hi == lo:
        hi, lo = hi + (abs(hi) * .05 or 1), lo - (abs(lo) * .05 or 1)
    pad = (hi - lo) * .08
    return (lo if zero and lo == 0 else lo - pad), (hi if zero and hi == 0 else hi + pad)


def _svg(alt, corpo, titulo):
    return (f'<svg class="graf" viewBox="0 0 {_L} {alt}" role="img" aria-label="{_esc(titulo)}" '
            f'font-family="inherit" font-size="9" fill="currentColor">'
            f'<text x="0" y="11" font-size="10" font-weight="700">{_esc(_curto(titulo, 58))}</text>{corpo}</svg>')


def _legenda(itens, y):
    out, x = "", 0
    n = 24 if len(itens) <= 2 else 16
    for nome_, cor in itens[:4]:
        out += (f'<rect x="{x}" y="{y - 7}" width="9" height="9" rx="2" fill="{cor}"/>'
                f'<text x="{x + 12}" y="{y + 1}" opacity=".8">{_esc(_curto(nome_, n))}</text>')
        x += 14 + min(len(str(nome_)), n) * 5 + 8
    return out


def svg_linhas(series, titulo, fmt):
    """series: [(nome, cor, [(rótulo_x, valor), ...], faixa opcional [(lo, hi), ...])]."""
    xs = list(dict.fromkeys(x for s in series for x, _ in s[2]))
    if len(xs) < 2:
        return None
    todos = [y for s in series for _, y in s[2]] + [v for s in series for f in (s[3] if len(s) > 3 and s[3] else []) for v in f]
    lo, hi = _escala(todos)
    y0, y1, x0, x1 = 34, 34 + _ALT_LIN - 34, 34, _L - 30
    px = lambda i: x0 + i * (x1 - x0) / (len(xs) - 1)                                    # noqa: E731
    py = lambda v: y1 - (v - lo) / (hi - lo) * (y1 - y0)                                  # noqa: E731
    corpo = _legenda([(s[0], s[1]) for s in series], 24) if len(series) > 1 else ""
    for k in range(4):                                                                    # grade e eixo y
        v = lo + (hi - lo) * k / 3
        corpo += (f'<line x1="{x0}" x2="{x1}" y1="{py(v):.1f}" y2="{py(v):.1f}" stroke="currentColor" stroke-opacity=".12"/>'
                  f'<text x="{x0 - 4}" y="{py(v) + 3:.1f}" text-anchor="end" opacity=".6">{_esc(fmt(v))}</text>')
    passo = max(1, -(-(len(xs) - 1) // 5))
    mostrar = list(range(0, len(xs), passo))
    if mostrar[-1] != len(xs) - 1:                                                        # o último sempre aparece,
        if len(xs) - 1 - mostrar[-1] < passo * .6 and len(mostrar) > 1:                   # no lugar do penúltimo se estiver perto
            mostrar[-1] = len(xs) - 1
        else:
            mostrar.append(len(xs) - 1)
    for i in mostrar:                                                                     # rótulos do eixo x (até ~6)
        corpo += f'<text x="{px(i):.1f}" y="{y1 + 13}" text-anchor="middle" opacity=".6">{_esc(_curto(xs[i], 10))}</text>'
    for s in series:
        cor, pts = s[1], s[2]
        idx = [(xs.index(x), y) for x, y in pts if y is not None and pd.notna(y)]
        if len(s) > 3 and s[3]:
            fx = [(xs.index(x), f) for (x, _), f in zip(pts, s[3]) if f and None not in f]
            if fx:
                pol = " ".join(f"{px(i):.1f},{py(f[1]):.1f}" for i, f in fx) + " " + \
                      " ".join(f"{px(i):.1f},{py(f[0]):.1f}" for i, f in reversed(fx))
                corpo += f'<polygon points="{pol}" fill="{cor}" fill-opacity=".16"/>'
        if not idx:
            continue
        lin = " ".join(f"{px(i):.1f},{py(y):.1f}" for i, y in idx)
        corpo += (f'<polyline points="{lin}" fill="none" stroke="{cor}" stroke-width="2" stroke-linejoin="round" '
                  f'stroke-linecap="round" pathLength="1" class="traco"/>')
        i, y = idx[-1]
        corpo += (f'<circle cx="{px(i):.1f}" cy="{py(y):.1f}" r="2.8" fill="{cor}"/>'
                  f'<text x="{px(i) + 4:.1f}" y="{py(y) + 3:.1f}" font-weight="700" fill="{cor}">{_esc(fmt(y))}</text>')
    return _svg(y1 + 20, corpo, titulo)


def svg_barras(itens, titulo, fmt, ref=None):
    """Barras horizontais: [(rótulo, valor, cor, texto opcional)]; aceita negativos (linha do zero). ref = (valor, rótulo)."""
    itens = [i for i in itens if i[1] is not None and pd.notna(i[1])][:14]
    if not itens:
        return None
    vals = [i[1] for i in itens] + ([ref[0]] if ref else [])
    lo, hi = _escala(vals, zero=True)
    x0 = int(min(132, max(60, 8 + max(len(str(i[0])) for i in itens) * 4.7)))
    x1, y0, h = _L - 46, 24, 17
    px = lambda v: x0 + (v - lo) / (hi - lo) * (x1 - x0)                                  # noqa: E731
    corpo = ""
    for k, it in enumerate(itens):
        rot, v, cor = it[0], it[1], it[2]
        txt = it[3] if len(it) > 3 and it[3] else fmt(v)
        y = y0 + k * h
        a, b = sorted((px(0), px(v)))
        corpo += (f'<text x="{x0 - 5}" y="{y + 11}" text-anchor="end" opacity=".8">{_esc(_curto(rot, 28))}</text>'
                  f'<rect x="{a:.1f}" y="{y + 2}" width="{max(b - a, 1.5):.1f}" height="{h - 6}" rx="3" fill="{cor}" class="barra"/>'
                  f'<text x="{(b if v >= 0 else px(0)) + 4:.1f}" y="{y + 11}" font-weight="600">{_esc(txt)}</text>')
    base = y0 + len(itens) * h
    if lo < 0 < hi:
        corpo += f'<line x1="{px(0):.1f}" x2="{px(0):.1f}" y1="{y0}" y2="{base}" stroke="currentColor" stroke-opacity=".35"/>'
    if ref:
        corpo += (f'<line x1="{px(ref[0]):.1f}" x2="{px(ref[0]):.1f}" y1="{y0 - 4}" y2="{base}" stroke="currentColor" '
                  f'stroke-dasharray="3 3" stroke-opacity=".7"/>'
                  f'<text x="{px(ref[0]):.1f}" y="{base + 11}" text-anchor="middle" opacity=".75">{_esc(ref[1])}</text>')
    return _svg(base + (16 if ref else 6), corpo, titulo)


def svg_grupos(categorias, grupos, titulo, fmt):
    """Barras verticais agrupadas: categorias no eixo x; grupos = [(nome, cor, [valor por categoria])]."""
    if not categorias or not grupos:
        return None
    vals = [v for g in grupos for v in g[2]]
    lo, hi = _escala(vals, zero=True)
    y0, y1, x0, x1 = 36, 140, 34, _L - 4
    py = lambda v: y1 - (v - lo) / (hi - lo) * (y1 - y0)                                  # noqa: E731
    larg_cat = (x1 - x0) / len(categorias)
    lb = min(22, larg_cat * .8 / len(grupos))
    corpo = _legenda([(g[0], g[1]) for g in grupos], 24)
    for k in range(4):
        v = lo + (hi - lo) * k / 3
        corpo += (f'<line x1="{x0}" x2="{x1}" y1="{py(v):.1f}" y2="{py(v):.1f}" stroke="currentColor" stroke-opacity=".12"/>'
                  f'<text x="{x0 - 4}" y="{py(v) + 3:.1f}" text-anchor="end" opacity=".6">{_esc(fmt(v))}</text>')
    for c, cat in enumerate(categorias):
        cx = x0 + larg_cat * (c + .5)
        for g, (_, cor, vs) in enumerate(grupos):
            v = vs[c] if c < len(vs) else None
            if v is None or pd.isna(v):
                continue
            bx = cx - lb * len(grupos) / 2 + g * lb
            a, b = sorted((py(0), py(v)))
            corpo += f'<rect x="{bx:.1f}" y="{a:.1f}" width="{lb - 1.5:.1f}" height="{max(b - a, 1.5):.1f}" rx="2" fill="{cor}" class="barra"/>'
            if len(categorias) * len(grupos) <= 10:
                corpo += f'<text x="{bx + lb / 2:.1f}" y="{a - 3:.1f}" text-anchor="middle" font-size="8">{_esc(fmt(v))}</text>'
        corpo += f'<text x="{cx:.1f}" y="{y1 + 12}" text-anchor="middle" opacity=".7">{_esc(_curto(cat, 12))}</text>'
    return _svg(y1 + 18, corpo, titulo)


def svg_faixas(itens, titulo, fmt, ref=None):
    """Projeções: [(rótulo, centro, lo, hi, cor)] como faixa (80%) com o centro marcado. ref = (valor, rótulo)."""
    itens = [i for i in itens if i[1] is not None and pd.notna(i[1])][:10]
    if not itens:
        return None
    vals = [v for i in itens for v in i[1:4] if v is not None and pd.notna(v)] + ([ref[0]] if ref else [])
    lo, hi = _escala(vals)
    x0, x1, y0, h = 92, _L - 40, 24, 19
    px = lambda v: x0 + (v - lo) / (hi - lo) * (x1 - x0)                                  # noqa: E731
    corpo = ""
    for k, (rot, c, a, b, cor) in enumerate(itens):
        y = y0 + k * h
        corpo += f'<text x="{x0 - 5}" y="{y + 11}" text-anchor="end" opacity=".8">{_esc(_curto(rot))}</text>'
        if a is not None and b is not None and pd.notna(a) and pd.notna(b):
            corpo += f'<rect x="{px(a):.1f}" y="{y + 4}" width="{max(px(b) - px(a), 2):.1f}" height="{h - 9}" rx="4" fill="{cor}" fill-opacity=".28"/>'
        corpo += (f'<circle cx="{px(c):.1f}" cy="{y + 8.5}" r="3.6" fill="{cor}"/>'
                  f'<text x="{max(px(b) if b is not None and pd.notna(b) else px(c), px(c)) + 5:.1f}" y="{y + 11}" font-weight="600">{_esc(fmt(c))}</text>')
    base = y0 + len(itens) * h
    if ref:
        corpo += (f'<line x1="{px(ref[0]):.1f}" x2="{px(ref[0]):.1f}" y1="{y0 - 2}" y2="{base}" stroke="currentColor" '
                  f'stroke-dasharray="3 3" stroke-opacity=".7"/>'
                  f'<text x="{px(ref[0]):.1f}" y="{base + 11}" text-anchor="middle" opacity=".75">{_esc(ref[1])}</text>')
    return _svg(base + 16, corpo, titulo + " · faixa de 80%")


def _mes_rot(aaaamm):
    try:
        a, m = str(aaaamm)[:7].split("-")
        return f"{MESES[int(m) - 1]}/{a[2:]}"
    except Exception:
        return str(aaaamm)


def _per_rot(txt):
    """'2025-10 a 2026-09' -> 'out/25 a set/26'."""
    return re.sub(r"(\d{4})-(\d{2})", lambda m: f"{MESES[int(m[2]) - 1]}/{m[1][2:]}", str(txt or ""))


def graficos(consultas, cores=None, maximo=2):
    """Gráficos (SVG) a partir dos resultados das consultas da resposta. Devolve até `maximo` desenhos."""
    cores = cores or {}
    cor = lambda s, k: cores.get(s) or PALETA[k % len(PALETA)]                            # noqa: E731
    f2 = lambda v: br(v)                                                                   # noqa: E731
    out = []
    for c in consultas or []:
        r = c.get("resultado") or {}
        L = r.get("linhas") or []
        f = c.get("ferramenta")
        if r.get("erro") or not L:
            continue
        try:
            if f == "serie_mensal" and "ano" in L[0]:
                anos = sorted({l["ano"] for l in L})
                for met in dict.fromkeys(l["metrica"] for l in L):
                    ss = list(dict.fromkeys(l["serie"] for l in L if l["metrica"] == met))
                    gs = [(nome(s), cor(s, k), [next((l["media_simples_dos_meses"] for l in L if l["serie"] == s and l["metrica"] == met
                                                     and l["ano"] == a), None) for a in anos]) for k, s in enumerate(ss)]
                    out.append(svg_grupos([str(a) for a in anos], gs, f"{met} · média por ano", f2))
            elif f == "serie_mensal":
                for met in dict.fromkeys(l["metrica"] for l in L):
                    ss = list(dict.fromkeys(l["serie"] for l in L if l["metrica"] == met))
                    series = [(nome(s), cor(s, k), [(_mes_rot(l["mes"]), l["valor"]) for l in L if l["serie"] == s and l["metrica"] == met])
                              for k, s in enumerate(ss)]
                    out.append(svg_linhas(series, f"{met} · {_per_rot(r.get('periodo', ''))}", f2))
            elif f == "ranking":
                ch = r.get("criterio", "valor")
                var = ch.startswith("var")
                itens = [(nome(l["serie"]), l[ch], (COR_SOBE if l[ch] >= 0 else COR_DESCE) if var else cor(l["serie"], k),
                          sinal(l[ch]) if var else None) for k, l in enumerate(L)]
                rot = {"valor": "valor", "var_mes_anterior": "variação vs mês anterior", "var_ano_anterior": "variação vs ano anterior",
                       "media_ano": "média do ano"}.get(ch, ch)
                out.append(svg_barras(itens, f"{r.get('metrica', '')} · {rot}", f2))
            elif f == "projecao_programas":
                itens = sorted([(f"{l['programa']} · {'aud.' if l['metrica'] == 'Audiência' else 'share'}",
                                 (l.get("chance_meta100") or 0) * 100, COR_SEMAFORO.get(str(l.get("semaforo_meta100")).lower(), PALETA[7]),
                                 _pct(l.get("chance_meta100"))) for l in L if l.get("chance_meta100") is not None],
                               key=lambda x: -x[1])
                out.append(svg_barras(itens, "Chance de bater a meta 100%", lambda v: f"{br(v, 0)}%"))
            elif f == "projecao_faixa":
                meses = r.get("meses_projetados") or []
                for k, l in enumerate(L):
                    met = l["metrica"]
                    linhas = [(_mes_rot(m["mes"]), m["projecao"], *(m.get("faixa80") or [None, None]), cor(met, k))
                              for m in meses if m["metrica"] == met]
                    linhas.append(("Ano · fechamento", l.get("fechamento_projetado"), *(l.get("faixa80") or [None, None]),
                                   COR_SEMAFORO.get(str(l.get("semaforo_meta100")).lower(), PALETA[0])))
                    ref = (l["meta100"], f"meta 100% = {br(l['meta100'])}") if l.get("meta100") is not None else None
                    out.append(svg_faixas(linhas, f"{nome(r.get('faixa'))} · {met}", f2, ref))
            elif f == "comparar_periodos":
                for met in dict.fromkeys(l["metrica"] for l in L):
                    ls = [l for l in L if l["metrica"] == met]
                    out.append(svg_grupos([nome(l["serie"]) for l in ls],
                                          [(_per_rot(r.get("periodo_a", "A")), PALETA[0], [l["media_a"] for l in ls]),
                                           (_per_rot(r.get("periodo_b", "B")), PALETA[7], [l["media_b"] for l in ls])], f"{met} · comparação", f2))
            elif f == "concorrencia_ranking":
                un = r.get("unidade", "")
                suf = "%" if r.get("metrica") != "Audiência" else ""
                rivais = [l["emissora"] for l in L if l["emissora"] not in (TVB, OUTRAS)]
                itens = [(l["emissora"], l["valor"], "#2a78d6" if l["emissora"] == TVB else "#8a8984" if l["emissora"] == OUTRAS
                          else PALETA[1 + rivais.index(l["emissora"]) % 6], f"{br(l['valor'])}{suf}") for l in L]
                out.append(svg_barras(itens, f"{r.get('metrica')} · {r.get('recorte')} · {_mes_rot(r.get('mes'))}",
                                      lambda v: f"{br(v)}{suf}"))
            elif f == "concorrencia_serie":
                ult = {l["emissora"]: l["valor"] for l in L}                     # ordem = posição no último mês (cores do ranking)
                ems = sorted(dict.fromkeys(l["emissora"] for l in L),
                             key=lambda e: (e != TVB, e == OUTRAS, -(ult.get(e) or 0)))
                rivais = [e for e in ems if e not in (TVB, OUTRAS)]
                series = [(e, "#2a78d6" if e == TVB else "#8a8984" if e == OUTRAS else PALETA[1 + rivais.index(e) % 6],
                           [(_mes_rot(l["mes"]), l["valor"]) for l in L if l["emissora"] == e]) for e in ems]
                out.append(svg_linhas(series[:5], f"{r.get('metrica')} · {r.get('recorte')}", f2))
            elif f == "concorrencia_vantagem":
                un = r.get("unidade", "")
                rot = (lambda l: _mes_rot(l["mes"])) if r.get("modo") == "por mês" else (lambda l: l["recorte"].replace("horário do ", ""))
                itens = [(rot(l), l["vantagem"], "#1baf7a" if l["vantagem"] >= 0 else "#e34948", sinal(l["vantagem"])) for l in L]
                rivais_v = list(dict.fromkeys(l["melhor_concorrente"] for l in L))
                tit = (f"Vantagem · {r.get('recorte')}" if r.get("modo") == "por mês" else f"Vantagem por horário · {_mes_rot(r.get('mes'))}")
                tit += f" · {un} vs " + (rivais_v[0] if len(rivais_v) == 1 else "melhor concorrente")
                out.append(svg_barras(itens, tit, lambda v: sinal(v)))
        except Exception:                 # um gráfico que não deu certo não pode atrapalhar a resposta
            continue
    vistos, final = set(), []
    for g in out:
        if g and g not in vistos:
            vistos.add(g)
            final.append(g)
    return final[:maximo]


# ícone do PIPECO (PNG 128×128 com fundo transparente, embutido para não depender de outro arquivo no repositório)
PIPECO_PNG = "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"
