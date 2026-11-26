"""Identidade visual dos times nos painéis: BANDEIRAS das seleções e selos com o PADRÃO DE CORES do uniforme dos clubes
(listras, faixas, metades), com a sigla em branco. Não usa escudos nem logotipos (que são marcas dos clubes): só cores,
listras e a sigla. Tudo em SVG gerado aqui, sem imagens externas (funciona no Labs, sem internet).

selo(nome, tam)  -> HTML (SVG) redondo do time ou seleção
nome(nome)       -> nome para exibir, com acentos ("VITORIA BA" -> "Vitória", "COREIA SUL" -> "Coreia do Sul")
"""

VERSAO_MODULO = "27/11/2026"           # o streamlit_app.py confere: arquivos da mesma entrega têm a mesma versão
import html
import itertools
import math
import re

# ---------------------------------------------------------------------------------------------- nomes do Instar
_ALIAS = {"INTER RS": "INTERNACIONAL", "RB BRAGANTIN": "BRAGANTINO", "SPORT RECIFE": "SPORT", "VASCO": "VASCO DA GAMA",
          "BAHIA FEIRA": "BAHIA DE FEIRA", "COREIA SUL": "COREIA DO SUL", "ATL ALAGOINH": "ATLETICO BA",
          "ARAB SAUDITA": "ARABIA SAUDITA", "NV ZELANDIA": "NOVA ZELANDIA", "REPUB TCHECA": "REPUBLICA TCHECA",
          "AFRICA SUL": "AFRICA DO SUL", "PAIS GALES": "PAIS DE GALES"}

_NOMES = {"VITORIA BA": "Vitória", "SAO PAULO": "São Paulo", "GREMIO": "Grêmio", "CEARA": "Ceará", "ATLETICO MG": "Atlético-MG",
          "ATLETICO GO": "Atlético-GO", "ATLETICO BA": "Atlético-BA", "ATHLETICO PR": "Athletico-PR", "BOTAFOGO RJ": "Botafogo",
          "BOTAFOGO SP": "Botafogo-SP", "VASCO DA GAMA": "Vasco", "AMERICA MG": "América-MG", "CRICIUMA": "Criciúma",
          "GOIAS": "Goiás", "BRAGANTINO": "Bragantino", "INTERNACIONAL": "Internacional", "BAHIA DE FEIRA": "Bahia de Feira",
          "JEQUIE": "Jequié", "VITORIA DA CONQUISTA": "Vitória da Conquista", "FLUMINENSE FEIRA": "Fluminense de Feira",
          "AVAI": "Avaí", "PAYSANDU": "Paysandu", "PONTE PRETA": "Ponte Preta", "ABC RN": "ABC", "CRB": "CRB", "REAL MADRID": "Real Madrid",
          "COREIA DO SUL": "Coreia do Sul", "JAPAO": "Japão", "SUICA": "Suíça", "SERVIA": "Sérvia", "ESCOCIA": "Escócia",
          "FRANCA": "França", "CROACIA": "Croácia", "NIGERIA": "Nigéria", "SUECIA": "Suécia", "AUSTRALIA": "Austrália",
          "BOLIVIA": "Bolívia", "COLOMBIA": "Colômbia", "MEXICO": "México", "ITALIA": "Itália", "BELGICA": "Bélgica",
          "TUNISIA": "Tunísia", "PANAMA": "Panamá", "CANADA": "Canadá", "IRA": "Irã", "ARABIA SAUDITA": "Arábia Saudita",
          "CAMAROES": "Camarões", "ARGELIA": "Argélia", "AUSTRIA": "Áustria", "BIELORUSSIA": "Bielorrússia", "BOSNIA": "Bósnia",
          "COSTA MARFIM": "Costa do Marfim", "GUINE": "Guiné", "HUNGRIA": "Hungria", "INDIA": "Índia", "JORDANIA": "Jordânia",
          "NOVA ZELANDIA": "Nova Zelândia", "PAIS DE GALES": "País de Gales", "POLONIA": "Polônia",
          "REPUBLICA TCHECA": "República Tcheca", "TURQUIA": "Turquia", "UZBEQUISTAO": "Uzbequistão", "AFRICA DO SUL": "África do Sul",
          "EUA": "EUA", "HOLANDA": "Holanda", "ALEMANHA": "Alemanha", "ESPANHA": "Espanha", "INGLATERRA": "Inglaterra",
          "MARROCOS": "Marrocos", "DINAMARCA": "Dinamarca", "NORUEGA": "Noruega", "SENEGAL": "Senegal", "CABO VERDE": "Cabo Verde",
          "COSTA RICA": "Costa Rica", "SINGAPURA": "Singapura", "CATAR": "Catar", "EGITO": "Egito", "GANA": "Gana",
          "JAMAICA": "Jamaica", "HAITI": "Haiti", "CONGO": "Congo"}

# ---------------------------------------------------------------------------------------------- clubes: padrão + cores
# padrões: liso, listras_v, listras_h, finas_v (listras finas alternadas), faixa_diag, faixa_h, metades_v
VERMELHO, PRETO, BRANCO, AZUL, VERDE, AMARELO = "#d71920", "#141414", "#ffffff", "#1d4f9e", "#00843d", "#f2c300"
CLUBES = {
    "FLAMENGO": ("FLA", "listras_h", [VERMELHO, PRETO]),
    "VASCO DA GAMA": ("VAS", "faixa_diag", [PRETO, BRANCO]),
    "BAHIA": ("BAH", "metades_v", [AZUL, VERMELHO, BRANCO]),
    "VITORIA BA": ("VIT", "listras_v", [VERMELHO, PRETO]),
    "GREMIO": ("GRE", "finas_v", ["#0d80bf", PRETO, BRANCO]),
    "FLUMINENSE": ("FLU", "finas_v", ["#7a1d2e", "#00613c", BRANCO]),
    "PALMEIRAS": ("PAL", "liso", ["#006437", BRANCO]),
    "CORINTHIANS": ("COR", "liso", [PRETO, BRANCO]),
    "SAO PAULO": ("SAO", "faixa_h", [BRANCO, VERMELHO, PRETO]),
    "BOTAFOGO RJ": ("BOT", "listras_v", [PRETO, BRANCO]),
    "INTERNACIONAL": ("INT", "liso", [VERMELHO, BRANCO]),
    "ATLETICO MG": ("CAM", "listras_v", [PRETO, BRANCO]),
    "CRUZEIRO": ("CRU", "liso", ["#1d3fa0", BRANCO]),
    "FORTALEZA": ("FOR", "listras_h", [VERMELHO, AZUL, BRANCO]),
    "CEARA": ("CEA", "listras_v", [PRETO, BRANCO]),
    "SANTOS": ("SAN", "listras_v", [BRANCO, PRETO]),
    "BRAGANTINO": ("RBB", "faixa_h", [BRANCO, VERMELHO]),
    "SPORT": ("SPT", "listras_v", [VERMELHO, PRETO]),
    "JUVENTUDE": ("JUV", "listras_v", [VERDE, BRANCO]),
    "MIRASSOL": ("MIR", "listras_v", [AMARELO, "#007a33"]),
    "ATHLETICO PR": ("CAP", "listras_v", [VERMELHO, PRETO]),
    "ATLETICO GO": ("ACG", "listras_v", [VERMELHO, PRETO]),
    "AMERICA MG": ("AME", "listras_v", [VERDE, PRETO]),
    "CHAPECOENSE": ("CHA", "liso", [VERDE, BRANCO]),
    "CORITIBA": ("CFC", "listras_h", ["#00613c", BRANCO]),
    "CRICIUMA": ("CRI", "listras_v", [AMARELO, PRETO]),
    "GOIAS": ("GOI", "liso", [VERDE, BRANCO]),
    "REMO": ("REM", "liso", ["#13294b", BRANCO]),
    "PAYSANDU": ("PAY", "listras_v", [AZUL, BRANCO]),
    "PONTE PRETA": ("PON", "listras_h", [PRETO, BRANCO]),
    "GUARANI": ("GUA", "liso", [VERDE, BRANCO]),
    "CRB": ("CRB", "listras_h", [VERMELHO, BRANCO]),
    "ABC RN": ("ABC", "liso", [PRETO, BRANCO]),
    "AVAI": ("AVA", "listras_h", [AZUL, BRANCO]),
}


def _canon(t):
    t = re.sub(r"\s+", " ", str(t or "")).strip().upper()
    t = re.sub(r"\s+2T$", "", t)                      # "FLUMINENSE 2T" = transmissão do 2º tempo
    return _ALIAS.get(t, t)


def nome(t):
    """Nome para exibir (com acentos); a transmissão do 2º tempo ganha "(2º tempo)"."""
    bruto = re.sub(r"\s+", " ", str(t or "")).strip().upper()
    c = _canon(bruto)
    base = _NOMES.get(c) or " ".join(w.upper() if (len(w) == 2 and k == len(c.split()) - 1 and len(c.split()) > 1) else w.capitalize()
                                     for k, w in enumerate(c.split()))
    return base + (" (2º tempo)" if bruto.endswith(" 2T") else "")


# ---------------------------------------------------------------------------------------------- desenho
_ids = itertools.count()


def _faixas(cores, horizontal, pesos=None):
    pesos = pesos or [1] * len(cores)
    tot, pos, out = sum(pesos), 0, []
    for c, p in zip(cores, pesos):
        tam = 100 * p / tot
        out.append(f'<rect x="0" y="{pos:.2f}" width="100" height="{tam + .3:.2f}" fill="{c}"/>' if horizontal else
                   f'<rect x="{pos:.2f}" y="0" width="{tam + .3:.2f}" height="100" fill="{c}"/>')
        pos += tam
    return "".join(out)


def _estrela(cx, cy, r, cor):
    pts = []
    for k in range(10):
        a = math.pi / 2 + k * math.pi / 5
        rr = r if k % 2 == 0 else r * .42
        pts.append(f"{cx + rr * math.cos(a):.1f},{cy - rr * math.sin(a):.1f}")
    return f'<polygon points="{" ".join(pts)}" fill="{cor}"/>'


def _cruz_nordica(fundo, cruz, miolo=None):
    s = f'<rect width="100" height="100" fill="{fundo}"/><rect x="28" y="0" width="20" height="100" fill="{cruz}"/>' \
        f'<rect x="0" y="40" width="100" height="20" fill="{cruz}"/>'
    if miolo:
        s += f'<rect x="33" y="0" width="10" height="100" fill="{miolo}"/><rect x="0" y="45" width="100" height="10" fill="{miolo}"/>'
    return s


def _clube(padrao, cores):
    c = cores
    if padrao == "liso":
        return f'<rect width="100" height="100" fill="{c[0]}"/>' + (f'<circle cx="50" cy="50" r="44" fill="none" stroke="{c[1]}" '
                                                                     f'stroke-width="5" opacity=".9"/>' if len(c) > 1 else "")
    if padrao == "listras_v":
        return _faixas((c * 4)[:7], horizontal=False)
    if padrao == "listras_h":
        return _faixas((c * 4)[:7], horizontal=True)
    if padrao == "finas_v":                         # tricolor de listras: as duas cores fortes, com fio branco entre elas
        seq = []
        for k in range(6):
            seq += [c[k % 2], c[2]]
        return _faixas(seq[:11], horizontal=False, pesos=[3, 1] * 5 + [3])
    if padrao == "faixa_diag":
        return f'<rect width="100" height="100" fill="{c[0]}"/><polygon points="0,62 62,0 84,0 0,84" fill="{c[1]}"/>'
    if padrao == "faixa_h":
        faixas = c[1:]
        h = 30 / len(faixas)
        return f'<rect width="100" height="100" fill="{c[0]}"/>' + "".join(
            f'<rect x="0" y="{35 + k * h:.1f}" width="100" height="{h + .3:.1f}" fill="{cor}"/>' for k, cor in enumerate(faixas))
    if padrao == "metades_v":                       # duas metades com um fio entre elas (o tricolor do Bahia)
        return (f'<rect width="50" height="100" fill="{c[0]}"/><rect x="50" width="50" height="100" fill="{c[1]}"/>'
                f'<rect x="46.5" width="7" height="100" fill="{c[2]}"/>')
    return f'<rect width="100" height="100" fill="{c[0]}"/>'


def _bandeira(p):
    """Bandeiras simplificadas (proporções e símbolos reduzidos para caber num círculo pequeno)."""
    h, v = (lambda *cs, w=None: _faixas(list(cs), True, w)), (lambda *cs, w=None: _faixas(list(cs), False, w))
    B = {
        "BRASIL": '<rect width="100" height="100" fill="#009b3a"/><polygon points="50,14 92,50 50,86 8,50" fill="#fedf00"/>'
                  '<circle cx="50" cy="50" r="19" fill="#002776"/><path d="M32,47 Q50,40 68,52" stroke="#fff" stroke-width="3" fill="none"/>',
        "ARGENTINA": h("#74acdf", "#ffffff", "#74acdf") + '<circle cx="50" cy="50" r="8" fill="#f6b40e"/>',
        "URUGUAI": h(*(["#ffffff", "#0038a8"] * 4 + ["#ffffff"])) + '<rect width="44" height="44" fill="#fff"/><circle cx="22" cy="22" r="11" fill="#fcd116"/>',
        "ALEMANHA": h("#000000", "#dd0000", "#ffce00"), "FRANCA": v("#0055a4", "#ffffff", "#ef4135"),
        "ITALIA": v("#009246", "#ffffff", "#ce2b37"), "ESPANHA": h("#aa151b", "#f1bf00", "#aa151b", w=[1, 2, 1]),
        "PORTUGAL": v("#006600", "#ff0000", w=[2, 3]) + '<circle cx="40" cy="50" r="13" fill="#ffcc00"/><circle cx="40" cy="50" r="7" fill="#ff0000"/>',
        "HOLANDA": h("#ae1c28", "#ffffff", "#21468b"), "BELGICA": v("#000000", "#fdda24", "#ef3340"),
        "INGLATERRA": '<rect width="100" height="100" fill="#fff"/><rect x="40" width="20" height="100" fill="#ce1124"/><rect y="40" width="100" height="20" fill="#ce1124"/>',
        "ESCOCIA": '<rect width="100" height="100" fill="#005eb8"/><path d="M0,0 L100,100 M100,0 L0,100" stroke="#fff" stroke-width="18"/>',
        "PAIS DE GALES": h("#ffffff", "#00b140") + '<circle cx="50" cy="50" r="18" fill="#c8102e"/>',
        "EUA": h(*(["#b22234", "#ffffff"] * 3 + ["#b22234"])) + '<rect width="50" height="54" fill="#3c3b6e"/>'
               + "".join(f'<circle cx="{10 + 15 * (k % 3)}" cy="{12 + 15 * (k // 3)}" r="3" fill="#fff"/>' for k in range(9)),
        "CANADA": v("#d52b1e", "#ffffff", "#d52b1e", w=[1, 2, 1]) + '<polygon points="50,28 60,48 56,70 50,62 44,70 40,48" fill="#d52b1e"/>',
        "MEXICO": v("#006847", "#ffffff", "#ce1126") + '<circle cx="50" cy="50" r="9" fill="#8c5a2b"/>',
        "COLOMBIA": h("#fcd116", "#003893", "#ce1126", w=[2, 1, 1]), "EQUADOR": h("#ffdd00", "#034ea2", "#ed1c24", w=[2, 1, 1]),
        "VENEZUELA": h("#fcd116", "#00247d", "#cf142b"), "BOLIVIA": h("#d52b1e", "#f9e300", "#007934"),
        "PARAGUAI": h("#d52b1e", "#ffffff", "#0038a8"), "PERU": v("#d91023", "#ffffff", "#d91023"),
        "CHILE": h("#ffffff", "#d52b1e") + '<rect width="40" height="50" fill="#0039a6"/>' + _estrela(20, 25, 11, "#fff"),
        "JAPAO": '<rect width="100" height="100" fill="#fff"/><circle cx="50" cy="50" r="24" fill="#bc002d"/>',
        "COREIA DO SUL": '<rect width="100" height="100" fill="#fff"/><path d="M28,50 A22,22 0 0 1 72,50 Z" fill="#cd2e3a"/>'
                         '<path d="M28,50 A22,22 0 0 0 72,50 Z" fill="#0047a0"/>',
        "SUICA": '<rect width="100" height="100" fill="#da291c"/><rect x="42" y="22" width="16" height="56" fill="#fff"/><rect x="22" y="42" width="56" height="16" fill="#fff"/>',
        "SERVIA": h("#c6363c", "#0c4076", "#ffffff"), "CROACIA": h("#ff0000", "#ffffff", "#171796")
                  + '<rect x="40" y="36" width="20" height="24" fill="#fff" stroke="#ff0000" stroke-width="3"/>',
        "DINAMARCA": _cruz_nordica("#c8102e", "#ffffff"), "NORUEGA": _cruz_nordica("#ba0c2f", "#ffffff", "#00205b"),
        "SUECIA": _cruz_nordica("#006aa7", "#fecc00"), "POLONIA": h("#ffffff", "#dc143c"),
        "AUSTRIA": h("#ed2939", "#ffffff", "#ed2939"), "HUNGRIA": h("#ce2939", "#ffffff", "#477050"),
        "REPUBLICA TCHECA": h("#ffffff", "#d7141a") + '<polygon points="0,0 50,50 0,100" fill="#11457e"/>',
        "BIELORUSSIA": h("#c8313e", "#4aa657", w=[2, 1]),
        "BOSNIA": '<rect width="100" height="100" fill="#002395"/><polygon points="30,0 80,0 80,100" fill="#fecb00"/>',
        "TURQUIA": '<rect width="100" height="100" fill="#e30a17"/><circle cx="42" cy="50" r="20" fill="#fff"/><circle cx="48" cy="50" r="16" fill="#e30a17"/>'
                   + _estrela(68, 50, 9, "#fff"),
        "MARROCOS": '<rect width="100" height="100" fill="#c1272d"/>' + _estrela(50, 52, 22, "#006233"),
        "TUNISIA": '<rect width="100" height="100" fill="#e70013"/><circle cx="50" cy="50" r="22" fill="#fff"/><circle cx="54" cy="50" r="14" fill="#e70013"/>',
        "EGITO": h("#ce1126", "#ffffff", "#000000"), "ARGELIA": v("#006233", "#ffffff") + '<circle cx="50" cy="50" r="16" fill="#d21034"/>',
        "SENEGAL": v("#00853f", "#fdef42", "#e31b23") + _estrela(50, 52, 11, "#00853f"),
        "GANA": h("#ce1126", "#fcd116", "#006b3f") + _estrela(50, 52, 11, "#000"), "NIGERIA": v("#008751", "#ffffff", "#008751"),
        "CAMAROES": v("#007a5e", "#ce1126", "#fcd116") + _estrela(50, 52, 10, "#fcd116"),
        "COSTA MARFIM": v("#f77f00", "#ffffff", "#009e60"), "GUINE": v("#ce1126", "#fcd116", "#009460"),
        "CONGO": '<rect width="100" height="100" fill="#007fff"/><polygon points="0,78 78,0 100,0 100,22 22,100 0,100" fill="#ce1021"/>'
                 + _estrela(22, 22, 12, "#f7d618"),
        "CABO VERDE": '<rect width="100" height="100" fill="#003893"/>' + '<rect y="54" width="100" height="16" fill="#fff"/><rect y="58" width="100" height="8" fill="#cf2027"/>',
        "AFRICA DO SUL": h("#de3831", "#007a4d", "#002395") + '<polygon points="0,10 40,50 0,90" fill="#000"/>',
        "ARABIA SAUDITA": '<rect width="100" height="100" fill="#006c35"/><rect x="22" y="62" width="56" height="6" fill="#fff"/>',
        "CATAR": v("#ffffff", "#8a1538", w=[1, 3]), "IRA": h("#239f40", "#ffffff", "#da0000"),
        "JORDANIA": h("#000000", "#ffffff", "#007a3d") + '<polygon points="0,0 52,50 0,100" fill="#ce1126"/>',
        "UZBEQUISTAO": h("#0099b5", "#ffffff", "#1eb53a"), "INDIA": h("#ff9933", "#ffffff", "#138808") + '<circle cx="50" cy="50" r="9" fill="none" stroke="#000080" stroke-width="3"/>',
        "SINGAPURA": h("#ef3340", "#ffffff"),
        "NOVA ZELANDIA": '<rect width="100" height="100" fill="#012169"/>' + "".join(_estrela(x, y, 7, "#c8102e") for x, y in ((70, 30), (82, 50), (62, 55), (70, 75))),
        "AUSTRALIA": '<rect width="100" height="100" fill="#012169"/>' + "".join(_estrela(x, y, 6, "#fff") for x, y in ((70, 25), (85, 45), (60, 50), (72, 75), (30, 72))),
        "JAMAICA": '<rect width="100" height="100" fill="#009b3a"/><polygon points="0,0 50,50 0,100" fill="#000"/><polygon points="100,0 50,50 100,100" fill="#000"/>'
                   '<path d="M0,0 L100,100 M100,0 L0,100" stroke="#fed100" stroke-width="13"/>',
        "HAITI": h("#00209f", "#d21034"),
        "PANAMA": '<rect width="50" height="50" fill="#fff"/><rect x="50" width="50" height="50" fill="#da121a"/>'
                  '<rect y="50" width="50" height="50" fill="#072357"/><rect x="50" y="50" width="50" height="50" fill="#fff"/>'
                  + _estrela(25, 25, 9, "#072357") + _estrela(75, 75, 9, "#da121a"),
        "COSTA RICA": h("#002b7f", "#ffffff", "#ce1126", "#ffffff", "#002b7f", w=[1, 1, 2, 1, 1]),
    }
    return B.get(p)


def _sigla_generica(c):
    w = [x for x in c.split() if x not in ("FC", "EC", "SC", "DE", "DA", "DO")]
    if not w:
        return "?"
    return (w[0][:3] if len(w) == 1 or (len(w) == 2 and len(w[1]) == 2) else (w[0][0] + w[1][0] + (w[2][0] if len(w) > 2 else ""))).upper()


def selo(t, tam=34):
    """Selo redondo: bandeira (seleção) ou padrão do uniforme com a sigla em branco (clube)."""
    c = _canon(t)
    if not c:
        return ""
    i = next(_ids)
    corpo, sigla = _bandeira(c), None
    if corpo is None:
        if c in CLUBES:
            sigla, padrao, cores = CLUBES[c]
            corpo = _clube(padrao, cores)
        else:                                       # time sem cores cadastradas: selo neutro, cor estável pelo nome
            paleta = ["#2f4b7c", "#665191", "#a05195", "#d45087", "#f95d6a", "#ff7c43", "#3f7f5f", "#5b6b7f"]
            corpo = f'<rect width="100" height="100" fill="{paleta[sum(map(ord, c)) % len(paleta)]}"/>'
            sigla = _sigla_generica(c)
    txt = ""
    if sigla:
        fs = 34 if len(sigla) <= 3 else 28
        txt = (f'<text x="50" y="50" dy=".35em" text-anchor="middle" font-family="Inter, Segoe UI, Arial, sans-serif" font-weight="800" '
               f'font-size="{fs}" fill="#fff" stroke="rgba(0,0,0,.6)" stroke-width="6" paint-order="stroke" '
               f'letter-spacing="-.5">{html.escape(sigla)}</text>')
    tit = html.escape(nome(t))
    return (f'<svg class="fu-selo" width="{tam}" height="{tam}" viewBox="0 0 100 100" role="img" aria-label="{tit}">'
            f'<title>{tit}</title><defs><clipPath id="sl{i}"><circle cx="50" cy="50" r="48"/></clipPath></defs>'
            f'<g clip-path="url(#sl{i})">{corpo}</g>{txt}'
            f'<circle cx="50" cy="50" r="48" fill="none" stroke="rgba(0,0,0,.25)" stroke-width="3"/></svg>')


def eh_selecao(t):
    return _bandeira(_canon(t)) is not None
