"""Relatório em PDF do painel: redesenha os gráficos do Plotly com o matplotlib (sem navegador nem kaleido) e monta as
páginas com o cabeçalho da Rede Bahia, os cartões de indicadores e os gráficos escolhidos.

Tipos de gráfico suportados: barras (verticais/horizontais, agrupadas/empilhadas), linhas e áreas (inclusive faixas
"tonexty"/"toself"), mapa de calor e caixa (box). Linhas de referência horizontais/verticais também são desenhadas.
"""
import base64
import io
import textwrap
from datetime import datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, to_rgba  # noqa: E402

AZUL_RB = "#001564"
TINTA, TINTA2, CINZA, GRADE = "#1f1f1e", "#52514e", "#8a8984", "#e6e8ee"
PAGINA = (11.69, 8.27)                       # A4 deitado, em polegadas
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8.5, "axes.edgecolor": "#d6d4d1",
                     "axes.labelcolor": TINTA2, "xtick.color": TINTA2, "ytick.color": TINTA2})


# ------------------------------------------------------------------------------------------------ utilidades
_DT = {"f8": "<f8", "f4": "<f4", "i1": "i1", "u1": "u1", "i2": "<i2", "u2": "<u2", "i4": "<i4", "u4": "<u4", "i8": "<i8"}


def _arr(v):
    """Vetores do Plotly: lista comum ou "typed array" ({'dtype', 'bdata', 'shape'}) das versões novas."""
    if isinstance(v, dict) and "bdata" in v:
        a = np.frombuffer(base64.b64decode(v["bdata"]), dtype=_DT.get(v.get("dtype", "f8"), v.get("dtype", "f8")))
        if v.get("shape"):
            a = a.reshape([int(x) for x in str(v["shape"]).split(",")])
        return a.tolist()
    if isinstance(v, np.ndarray):
        return v.tolist()
    return v


def _limpa(obj):
    """Converte recursivamente os vetores do Plotly em listas."""
    if isinstance(obj, dict):
        if "bdata" in obj:
            return _arr(obj)
        return {k: _limpa(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_limpa(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


def _cor(c, padrao="#2a78d6"):
    if c is None:
        return padrao
    if isinstance(c, str) and c.startswith("rgba("):
        v = [float(x) for x in c[5:-1].split(",")]
        return (v[0] / 255, v[1] / 255, v[2] / 255, v[3])
    if isinstance(c, str) and c.startswith("rgb("):
        v = [float(x) for x in c[4:-1].split(",")]
        return (v[0] / 255, v[1] / 255, v[2] / 255, 1)
    try:
        to_rgba(c)
        return c
    except (ValueError, TypeError):
        return padrao


def _lista(v, n):
    if v is None:
        return [None] * n
    if isinstance(v, (list, tuple, np.ndarray)):
        v = list(v)
        return (v + [v[-1] if v else None] * n)[:n]
    return [v] * n


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return np.nan


def _eh_data(vals):
    amostra = [v for v in vals if v is not None][:5]
    if not amostra or not all(isinstance(v, str) for v in amostra):
        return False
    try:
        pd.to_datetime(amostra, format="ISO8601")
        return all(len(v) >= 7 and v[:4].isdigit() and v[4] == "-" for v in amostra)
    except (ValueError, TypeError):
        return False


class _Eixo:
    """Converte valores de um eixo do Plotly (categorias, datas ou números) em posições do matplotlib."""

    def __init__(self):
        self.cats, self.tipo = [], None

    def registra(self, vals):
        vals = list(vals) if vals is not None else []
        if not vals:
            return
        if self.tipo is None:
            if _eh_data(vals):
                self.tipo = "data"
            elif all(isinstance(v, str) for v in vals if v is not None):
                self.tipo = "cat"
            else:
                self.tipo = "num"
        if self.tipo == "cat":
            for v in vals:
                if v not in self.cats:
                    self.cats.append(v)

    def pos(self, vals):
        vals = list(vals) if vals is not None else []
        if self.tipo == "cat":
            return np.array([self.cats.index(v) if v in self.cats else np.nan for v in vals], float)
        if self.tipo == "data":
            return np.array(pd.to_datetime(vals, format="ISO8601", errors="coerce"))
        return np.array([_num(v) for v in vals], float)


# ------------------------------------------------------------------------------------------------ plotly -> matplotlib
def _tabela(ax, tab):
    """Tabela simples: cabeçalho azul-claro, linhas alternadas, números alinhados à direita."""
    ax.set_axis_off()
    cols, linhas = tab["colunas"], tab["linhas"]
    if not linhas:
        return
    t = ax.table(cellText=linhas, colLabels=cols, loc="upper left", cellLoc="left", colLoc="left", bbox=[0, 0, 1, 1])
    t.auto_set_font_size(False)
    t.set_fontsize(7.5)
    for (i, j), cel in t.get_celld().items():
        cel.set_edgecolor("#e3e7f0")
        cel.set_linewidth(.5)
        txt = cel.get_text().get_text()
        if i == 0:
            cel.set_facecolor("#eef3fd")
            cel.get_text().set_fontweight("bold")
            cel.get_text().set_color(TINTA2)
        else:
            cel.set_facecolor("#ffffff" if i % 2 else "#f8f9fc")
            if txt.startswith("+"):
                cel.get_text().set_color("#0a7a0a")
            elif txt.startswith(("-", "−")) and len(txt) > 1:
                cel.get_text().set_color("#b42318")
        import re
        nucleo = re.sub(r"( OPM/ano|/ano| OPM|%|º)$", "", txt.strip())
        if i > 0 and j > 0 and re.fullmatch(r"[<>+\-−]?[\d.,]+", nucleo or "x"):
            cel.get_text().set_horizontalalignment("right")
            cel._loc = "right"


def desenha(ax, fig):
    """Desenha no `ax` a figura do Plotly (objeto ou dicionário) ou uma tabela ({"tabela": {...}})."""
    if isinstance(fig, dict) and "tabela" in fig:
        return _tabela(ax, fig["tabela"])
    import json as _json
    d = _json.loads(fig.to_json()) if hasattr(fig, "to_json") else fig
    d = _limpa(d)
    dados, lay = d.get("data", []), d.get("layout", {})
    ex, ey = _Eixo(), _Eixo()
    for eixo, nome in ((ex, "xaxis"), (ey, "yaxis")):        # ordem fixa das categorias (ex.: jan…dez), se o gráfico definir
        arr = (lay.get(nome, {}) or {}).get("categoryarray")
        if arr:
            eixo.tipo, eixo.cats = "cat", [str(v) for v in arr]
    horiz = any(t.get("type") == "bar" and t.get("orientation") == "h" for t in dados)
    for t in dados:
        if t.get("type") == "heatmap":
            continue
        ex.registra(t.get("x"))
        ey.registra(t.get("y"))
    barmode = lay.get("barmode", "group")
    barras = [t for t in dados if t.get("type") == "bar" and t.get("visible", True) is not False]
    nb = max(1, len(barras)) if barmode == "group" else 1
    acum_pos, acum_neg, ib = {}, {}, 0
    ultimo_y, legenda = None, False

    for t in dados:
        tipo = t.get("type", "scatter")
        nome = t.get("name")
        mostra_leg = t.get("showlegend", True) is not False and nome
        if tipo == "bar":
            cat_eixo, val_eixo = (ey, ex) if horiz else (ex, ey)
            cats = t.get("y") if horiz else t.get("x")
            vals = np.array([_num(v) for v in (t.get("x") if horiz else t.get("y"))], float)
            p = cat_eixo.pos(cats)
            mk = t.get("marker", {}) or {}
            cores = [_cor(c) for c in _lista(mk.get("color"), len(vals))]
            ops = _lista(mk.get("opacity"), len(vals))
            cores = [to_rgba(c, o if o is not None else 1) if not isinstance(c, tuple) else c for c, o in zip(cores, ops)]
            larg = 0.8 / nb if barmode == "group" else 0.75
            desl = (ib - (nb - 1) / 2) * larg if barmode == "group" else 0
            if barmode in ("stack", "relative"):
                base = np.array([(acum_pos if v >= 0 else acum_neg).get(k, 0) for k, v in zip(p, np.nan_to_num(vals))])
            else:
                base = np.zeros(len(vals))
            if horiz:
                ax.barh(p + desl, vals, height=larg * .78, left=base, color=cores, label=nome if mostra_leg else None,
                        edgecolor="white", linewidth=.4)
            else:
                ax.bar(p + desl, vals, width=larg * .92, bottom=base, color=cores, label=nome if mostra_leg else None)
            if barmode in ("stack", "relative"):
                for k, v in zip(p, np.nan_to_num(vals)):
                    alvo = acum_pos if v >= 0 else acum_neg
                    alvo[k] = alvo.get(k, 0) + v
            ib += 1
            legenda = legenda or bool(mostra_leg)
        elif tipo == "scatter":
            x, y = ex.pos(t.get("x")), ey.pos(t.get("y"))
            if not len(x):
                continue
            ln = t.get("line", {}) or {}
            mk = t.get("marker", {}) or {}
            cor = _cor(ln.get("color") or (mk.get("color") if isinstance(mk.get("color"), str) else None), "#2a78d6")
            modo = t.get("mode", "lines")
            fill = t.get("fill")
            fc = _cor(t.get("fillcolor"), None) if t.get("fillcolor") else to_rgba(cor, .2)
            if fill == "toself":
                ax.fill(x, y, color=fc, lw=0, label=nome if mostra_leg else None)
            elif fill == "tonexty" and ultimo_y is not None and len(ultimo_y[1]) == len(y):
                ax.fill_between(x, ultimo_y[1], y, color=fc, lw=0, label=nome if mostra_leg else None)
            larg = ln.get("width", 2)
            if "lines" in modo and larg:
                estilo = {"dash": "--", "dot": ":", "dashdot": "-."}.get(ln.get("dash"), "-")
                ax.plot(x, y, color=cor, lw=max(.8, larg * .7), ls=estilo, label=nome if (mostra_leg and fill not in ("toself", "tonexty")) else None)
            if "markers" in modo:
                tam = mk.get("size", 6)
                tam = np.nanmean([_num(v) for v in tam]) if isinstance(tam, (list, tuple)) else tam
                mcor = mk.get("color")
                mcor = [_cor(c) for c in _lista(mcor, len(x))] if isinstance(mcor, (list, tuple)) else _cor(mcor or cor)
                ax.scatter(x, y, s=(tam or 6) ** 2 * .35, c=mcor, zorder=3,
                           label=nome if (mostra_leg and "lines" not in modo) else None)
            ultimo_y = (x, y)
            legenda = legenda or bool(mostra_leg)
        elif tipo == "heatmap":
            z = np.array([[_num(v) for v in r] for r in t.get("z", [])], float)
            esc = t.get("colorscale")
            if isinstance(esc, (list, tuple)) and esc and isinstance(esc[0], (list, tuple)):
                cmap = LinearSegmentedColormap.from_list("p", [(float(a), _cor(c)) for a, c in esc])
            else:
                cmap = "Blues"
            vmin, vmax = t.get("zmin"), t.get("zmax")
            if t.get("zmid") is not None and vmin is None:
                lim = np.nanmax(np.abs(z - t["zmid"]))
                vmin, vmax = t["zmid"] - lim, t["zmid"] + lim
            im = ax.imshow(np.ma.masked_invalid(z), aspect="auto", cmap=cmap, vmin=vmin, vmax=vmax, interpolation="nearest")
            xs, ys = t.get("x") or list(range(z.shape[1])), t.get("y") or list(range(z.shape[0]))
            ax.set_xticks(range(len(xs)), [str(v) for v in xs], fontsize=7)
            ax.set_yticks(range(len(ys)), [str(v) for v in ys], fontsize=7)
            txt = t.get("text")
            if txt and z.size <= 220:
                for i, linha in enumerate(txt):
                    for j, v in enumerate(linha):
                        if v:
                            val = z[i, j]
                            claro = np.isfinite(val) and (vmax is not None and val > (vmin + (vmax - vmin) * .6))
                            ax.text(j, i, v, ha="center", va="center", fontsize=6, color="white" if claro else TINTA)
            plt.colorbar(im, ax=ax, fraction=.025, pad=.01).ax.tick_params(labelsize=7)
            if (lay.get("yaxis", {}) or {}).get("autorange") == "reversed":
                pass        # imshow já desenha a primeira linha em cima
            ax.grid(False)
            return
        elif tipo == "box":
            grupos = {}
            for xv, yv in zip(t.get("x") or [], t.get("y") or []):
                grupos.setdefault(xv, []).append(_num(yv))
            ks = list(grupos)
            cor = _cor((t.get("marker", {}) or {}).get("color") or (t.get("line", {}) or {}).get("color"))
            bp = ax.boxplot([grupos[k] for k in ks], positions=ex.pos(ks), widths=.55, patch_artist=True, showfliers=False)
            for b in bp["boxes"]:
                b.set(facecolor=to_rgba(cor, .35), edgecolor=cor)
            for parte in ("whiskers", "caps", "medians"):
                for el in bp[parte]:
                    el.set(color=cor)

    # linhas de referência (add_hline / add_vline)
    for sh in lay.get("shapes", []) or []:
        if sh.get("type") != "line":
            continue
        cor = _cor((sh.get("line", {}) or {}).get("color"), CINZA)
        estilo = {"dash": "--", "dot": ":"}.get((sh.get("line", {}) or {}).get("dash"), "-")
        if sh.get("y0") == sh.get("y1") and str(sh.get("xref", "")).endswith("domain") or sh.get("xref") == "paper":
            if sh.get("y0") == sh.get("y1"):
                ax.axhline(_num(sh["y0"]), color=cor, ls=estilo, lw=.9)
        if sh.get("x0") == sh.get("x1") and (str(sh.get("yref", "")).endswith("domain") or sh.get("yref") == "paper"):
            xv = ex.pos([sh["x0"]])[0] if ex.tipo else _num(sh["x0"])
            ax.axvline(xv, color=cor, ls=estilo, lw=.9)

    # eixos
    for eixo, ax_set, ticks in ((ex, ax.set_xticks, "x"), (ey, ax.set_yticks, "y")):
        if eixo.tipo == "cat":
            n = len(eixo.cats)
            passo = max(1, int(np.ceil(n / (16 if ticks == "x" else 30))))
            idx = list(range(0, n, passo))
            ax_set(idx, [str(eixo.cats[i]) for i in idx], fontsize=7)
            if ticks == "x" and n > 8:
                plt.setp(ax.get_xticklabels(), rotation=40, ha="right")
    if horiz:
        ax.invert_yaxis()
    yl = lay.get("yaxis", {}) or {}
    if yl.get("autorange") == "reversed" and not horiz:
        ax.invert_yaxis()
    if yl.get("range") and ey.tipo == "num":
        ax.set_ylim(*[_num(v) for v in yl["range"]])
    ax.grid(axis="x" if horiz else "y", color=GRADE, lw=.6)
    ax.set_axisbelow(True)
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)
    fmt = matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}".replace(",", ".") if (abs(v) >= 100 or abs(v - round(v)) < 1e-9)
                                          else f"{v:,.1f}".replace(".", ","))
    if horiz and ex.tipo == "num":          # formata só o eixo dos valores
        ax.xaxis.set_major_formatter(fmt)
    elif not horiz and ey.tipo == "num":
        ax.yaxis.set_major_formatter(fmt)
    if legenda:
        ax.legend(fontsize=7, frameon=False, ncol=min(6, max(1, len(dados))), loc="lower left", bbox_to_anchor=(0, 1.0),
                  borderaxespad=.2)


# ------------------------------------------------------------------------------------------------ páginas
def _cabecalho(fig, titulo, subtitulo, logo_b64):
    ax = fig.add_axes([0, .9, 1, .1])
    ax.set_axis_off()
    ax.add_patch(plt.Rectangle((0, 0), 1, 1, transform=ax.transAxes, color=AZUL_RB))
    ax.add_patch(plt.Rectangle((0, 0), 1, .05, transform=ax.transAxes, color="#00c2ff"))
    x0 = .03
    if logo_b64:
        img = plt.imread(io.BytesIO(base64.b64decode(logo_b64)), format="png")
        axl = fig.add_axes([.02, .912, .055, .075])
        axl.imshow(img)
        axl.set_axis_off()
        x0 = .09
    ax.text(x0, .62, titulo, color="white", fontsize=14, fontweight="bold", va="center", transform=ax.transAxes)
    ax.text(x0, .27, subtitulo, color="#b9c6ea", fontsize=8.5, va="center", transform=ax.transAxes)
    ax.text(.98, .45, datetime.now().strftime("gerado em %d/%m/%Y %H:%M"), color="#b9c6ea", fontsize=8, ha="right",
            va="center", transform=ax.transAxes)


def _rodape(fig, n, fonte):
    fig.text(.03, .02, fonte, fontsize=6.5, color=CINZA)
    fig.text(.97, .02, f"página {n}", fontsize=6.5, color=CINZA, ha="right")


def _cartoes(fig, cartoes, topo):
    """Cartões de indicadores em grade (até 5 por linha). Devolve a altura usada (fração da página)."""
    if not cartoes:
        return 0
    por_linha = 5
    linhas = int(np.ceil(len(cartoes) / por_linha))
    h, gap = .12, .015
    larg = (.94 - gap * (por_linha - 1)) / por_linha
    for i, (t, v, d, c) in enumerate(cartoes):
        lin, col = divmod(i, por_linha)
        x, y = .03 + col * (larg + gap), topo - (lin + 1) * h - lin * gap
        ax = fig.add_axes([x, y, larg, h])
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.set_axis_off()
        ax.add_patch(plt.Rectangle((0, 0), 1, 1, facecolor="white", edgecolor="#e3e7f0", lw=.8))
        ax.add_patch(plt.Rectangle((0, .955), 1, .045, color=_cor(c, "#2a78d6"), lw=0))
        ax.text(.05, .82, textwrap.shorten(t.upper(), 46, placeholder="…"), fontsize=6, color=TINTA2, fontweight="bold", va="top")
        ax.text(.05, .5, v, fontsize=15, color=TINTA, fontweight="bold", va="center")
        ax.text(.05, .2, "\n".join(textwrap.wrap(d, 48)[:2]), fontsize=5.6, color=CINZA, va="center", linespacing=1.2)
    return linhas * h + (linhas - 1) * gap + .02


def _horizontal(fig):
    if isinstance(fig, dict):
        return False
    try:
        return any(getattr(t, "orientation", None) == "h" for t in fig.data)
    except AttributeError:
        return False


def _altura(fig):
    """Altura do gráfico na página (fração de A4 deitado). Barras deitadas com muitos períodos ganham mais espaço,
    até a página inteira, para que cada barra e o seu rótulo fiquem separados. Tabelas: conforme o nº de linhas."""
    if isinstance(fig, dict) and "tabela" in fig:
        return min(.8, .1 + (len(fig["tabela"]["linhas"]) + 1) * .033)
    if not _horizontal(fig):
        return .36
    try:
        cats = set()
        for t in fig.data:
            if getattr(t, "orientation", None) == "h" and t.y is not None:
                cats.update(list(t.y))
        n = len(cats)
    except (AttributeError, TypeError):
        n = 12
    return min(.8, max(.36, .12 + n * .026))


def _paginas(pdf, graficos, cartoes, cab, fonte, n_pag, filtros="", secao="", marca=None, resumo=None):
    """Desenha uma sequência de páginas: a 1ª com seção/filtros e cartões; depois os gráficos, um embaixo do outro,
    cada um com a altura de que precisa (um gráfico que não cabe no espaço que sobra vai para a página seguinte)."""
    fila = list(graficos)
    primeira = True
    while primeira or fila:
        fig = plt.figure(figsize=PAGINA)
        n_pag += 1
        _cabecalho(fig, *cab)
        topo = .87
        if primeira:
            if secao:
                fig.text(.03, topo, secao, fontsize=12, fontweight="bold", color=AZUL_RB, va="top")
                topo -= .045
            if filtros:
                fig.text(.03, topo, filtros, fontsize=7.5, color=TINTA2, va="top")
                topo -= .04
            if resumo:                       # frases do resumo automático
                fig.text(.03, topo, "Resumo", fontsize=10, fontweight="bold", color=TINTA, va="top")
                topo -= .03
                for frase in resumo:
                    linhas_f = textwrap.wrap(frase, 175)
                    fig.text(.04, topo, "•  " + "\n    ".join(linhas_f), fontsize=7.8, color=TINTA2, va="top", linespacing=1.35)
                    topo -= .022 * len(linhas_f) + .008
                topo -= .015
            topo -= _cartoes(fig, cartoes or [], topo)
        base_pag = .06
        colocou = 0
        while fila:
            livre = topo - base_pag
            # o próximo da fila; se ele não couber no espaço que sobra, um dos seguintes que caiba sobe para cá
            idx = next((i for i, item in enumerate(fila) if _altura(item[2]) <= livre), None)
            if idx is None:
                if colocou == 0 and not primeira:
                    idx = 0                        # página vazia: o gráfico ocupa o espaço que houver
                else:
                    break
            t, sub, f = fila.pop(idx)
            alt = min(_altura(f), livre)
            fig.text(.03, topo - .005, t, fontsize=10, fontweight="bold", color=TINTA, va="top")
            if sub:
                fig.text(.03, topo - .03, sub, fontsize=7, color=CINZA, va="top")
            esq = .13 if _horizontal(f) else .07          # barras deitadas: espaço para os nomes dos bancos
            ax = fig.add_axes([esq, topo - alt + .01, .93 - esq, alt - .095])
            try:
                desenha(ax, f)
            except Exception as ex:       # um gráfico que não converte não derruba o relatório
                ax.set_axis_off()
                ax.text(.5, .5, f"Não foi possível desenhar este gráfico ({ex.__class__.__name__}).",
                        ha="center", va="center", color=CINZA, transform=ax.transAxes)
            topo -= alt + .035
            colocou += 1
        _rodape(fig, n_pag, fonte)
        if marca:                         # marca-d'água (ex.: "DADOS FICTÍCIOS" no ambiente de demonstração)
            fig.text(.5, .42, marca, rotation=24, fontsize=72, color=AZUL_RB, alpha=.07, ha="center", va="center",
                     fontweight="bold", zorder=100)
        pdf.savefig(fig)
        plt.close(fig)
        primeira = False
    return n_pag


def gera_pdf(graficos, cartoes=None, titulo="Painel de Audiência", subtitulo="", logo_b64=None, fonte="", filtros="",
             final=None, marca=None, resumo=None):
    """graficos: lista de (titulo, subtitulo, figura_plotly). cartoes: lista de (titulo, valor, descricao, cor).
    final: seção opcional que começa numa página nova no fim do relatório, ex. as projeções:
    {"titulo": "Projeções e metas", "cartoes": [...], "graficos": [...]}.
    Devolve os bytes do PDF."""
    buf = io.BytesIO()
    cab = (titulo, subtitulo, logo_b64)
    with PdfPages(buf) as pdf:
        n = 0
        if graficos or cartoes or resumo or not final:
            n = _paginas(pdf, graficos, cartoes, cab, fonte, n, filtros=filtros, marca=marca, resumo=resumo)
        if final and (final.get("graficos") or final.get("cartoes")):
            _paginas(pdf, final.get("graficos", []), final.get("cartoes", []), cab, fonte, n,
                     secao=final.get("titulo", ""), marca=marca)
    return buf.getvalue()
