"""Dados FICTÍCIOS do painel de TV, gerados na hora (modo demonstração).

Gera, no formato que o painel lê: a base mensal (dados/tv_mensal.csv, 2020 a set/2026, faixas 6h e 7h às 24h e programas),
uma rodada do modelo mensal por programa (dados/rodadas/), uma rodada do modelo diário para cada faixa
(dados/rodadas_diarias/) e o parametros_tv.json com metas fictícias e a chave "demo". Semente fixa: sempre os mesmos números."""
import json
import math
import os

import numpy as np
import openpyxl
import pandas as pd

import tv

AVISO = "DADOS FICTÍCIOS · gerados para demonstração · não representam a audiência real"


def _cdf(x):
    return 0.5 * (1 + math.erf(float(x) / math.sqrt(2)))


def serie_mensal(rng, meses, nivel, tend_ano, amp_saz, fase, ruido, ar=.55):
    n = len(meses)
    e = np.zeros(n)
    for i in range(n):
        e[i] = (e[i - 1] * ar if i else 0) + rng.normal(0, ruido)
    t = np.arange(n) / 12
    saz = amp_saz * np.sin(2 * np.pi * (np.array([m.month for m in meses]) - fase) / 12)
    return nivel * (1 + tend_ano * t) * (1 + saz) * (1 + e)


def _gera_mensal(destino, RNG):
    pasta = os.path.join(destino, "dados")
    os.makedirs(os.path.join(pasta, "rodadas"), exist_ok=True)
    meses = pd.date_range("2020-01-01", "2026-09-01", freq="MS")
    # nível de audiência, de share, tendência anual, amplitude sazonal, mês de pico
    cfg = {"6h às 24h": (14.3, 37.0, .004, .05, 7), "7h às 24h": (14.6, 37.4, .004, .05, 7),
           "Jornal da Manhã": (11.6, 49.0, .01, .05, 6), "Bahia Meio Dia": (10.6, 25.5, -.006, .06, 7),
           "Globo Esporte": (11.8, 27.5, .006, .07, 6), "BATV": (24.2, 44.5, .004, .05, 7),
           "Bom Dia Sábado": (8.0, 42.0, -.01, .07, 5), "Conexão Bahia": (9.7, 37.0, .006, .06, 8),
           "Panela de Bairro": (11.4, 33.0, .02, .06, 6), "Mosaico Baiano": (11.0, 28.0, .015, .07, 7),
           "Bahia Rural": (8.3, 46.0, -.004, .05, 4)}
    regs = []
    for prog, (na, ns, td, amp, pico) in cfg.items():
        aud = serie_mensal(RNG, meses, na, td, amp, pico - 3, ruido=.035)
        shr = serie_mensal(RNG, meses, ns, td * .5, amp * .5, pico - 3, ruido=.02)
        for m, a, s in zip(meses, aud, shr):
            regs.append(dict(programa=prog, metrica="Audiência", mes=m.strftime("%Y-%m"), valor=round(float(a), 6), origem="DEMO fictício"))
            regs.append(dict(programa=prog, metrica="Share", mes=m.strftime("%Y-%m"), valor=round(float(s), 6), origem="DEMO fictício"))
    base = pd.DataFrame(regs)
    base.to_csv(os.path.join(pasta, "tv_mensal.csv"), index=False)
    base["mes"] = pd.to_datetime(base["mes"] + "-01")

    # ---- rodada de projeção fictícia (mesmas abas e colunas da planilha do notebook)
    corte = pd.Timestamp("2026-09-30")
    rest = [pd.Timestamp(2026, m, 1) for m in (10, 11, 12)]
    progs = [p for p in tv.PROGRAMAS if p != tv.FAIXA_7]
    fech_rows, mens_rows, vs_rows, ac_rows, sens_rows, acum_rows, bt_rows, mae_rows = ([] for _ in range(8))
    modelos = ["ETS(A,N,A)", "Média 12m", "AR(1) + sazonal + eventos", "Nível local + sazonal + eventos"]
    for prog in progs:
        for met in tv.METRICAS:
            s = tv.serie(base, prog, met)
            dias = tv.DIAS_EXIBICAO[prog]
            w_m = lambda m: tv.n_exib(prog, m, m + pd.offsets.MonthEnd(0))   # noqa: E731
            atual = s["2026"].dropna()
            n_ate = sum(w_m(m) for m in atual.index)
            acum = float(np.average(atual.values, weights=[w_m(m) for m in atual.index]))
            nivel = atual.mean() / s["2025-01":"2025-09"].mean()
            proj = np.array([s.get(m - pd.DateOffset(years=1)) * nivel for m in rest], float)
            mae = abs(float(np.mean(atual.values))) * RNG.uniform(.035, .06)
            sig = mae * 1.25
            w = np.array([w_m(m) for m in rest], float)
            fech = (acum * n_ate + (proj * w).sum()) / (n_ate + w.sum())
            sd_f = (w * sig).sum() / (n_ate + w.sum()) * .8
            m100 = round(fech * RNG.uniform(.955, 1.045), 2)
            m75, m120 = round(m100 * .98, 2), round(m100 * 1.02, 2)
            P = {k: float(1 - _cdf((v - fech) / sd_f)) for k, v in (("75", m75), ("100", m100), ("120", m120))}
            nec = {k: (v * (n_ate + w.sum()) - acum * n_ate) / w.sum() for k, v in (("75", m75), ("100", m100), ("120", m120))}
            sem = tv.semaforo(P["100"])
            degrau = "—" if RNG.random() < .4 else f"{['mar', 'mai', 'ago', 'nov'][RNG.integers(0, 4)]}/{RNG.integers(2023, 2026)}"
            fech_rows.append({"programa": prog, "métrica": met, "acum. 30/09": acum, "fechamento": fech,
                              "IC95 inf": fech - 1.96 * sd_f, "IC95 sup": fech + 1.96 * sd_f, "média proj. out–dez": float(np.average(proj, weights=w)),
                              "meta 75%": m75, "P(75%)": P["75"], "média nec. 75%": nec["75"], "meta 100%": m100, "P(100%)": P["100"],
                              "média nec. 100%": nec["100"], "meta 120%": m120, "P(120%)": P["120"], "média nec. 120%": nec["120"],
                              "semáforo 100%": sem, "fronteira?": "sim" if (.12 < P["100"] < .28 or .72 < P["100"] < .88) else None,
                              "degrau": degrau, "incerteza": "oficial", "MAE (validação)": mae, "viés médio": RNG.normal(0, mae * .2),
                              "p viés": RNG.uniform(.05, .95)})
            for m, pv in zip(rest, proj):
                mens_rows.append({"programa": prog, "métrica": met, "mês": f"{tv.MESES[m.month - 1]}/{m.year}", "projeção": pv,
                                  "IC80 inf": pv - 1.2816 * sig, "IC80 sup": pv + 1.2816 * sig,
                                  "IC95 inf": pv - 1.96 * sig, "IC95 sup": pv + 1.96 * sig})
            p_ant = float(np.clip(P["100"] + RNG.normal(0, .06), 0, 1))
            vs_rows.append({"programa": prog, "métrica": met, "fech. 23/09": round(fech + RNG.normal(0, sd_f * .3), 2),
                            "fech. agora": fech, "P100 23/09": p_ant, "P100 agora": P["100"], "Δ P100 (p.p.)": (P["100"] - p_ant) * 100,
                            "semáforo 23/09": tv.semaforo(p_ant), "semáforo agora": sem,
                            "mudou?": "MUDOU" if tv.semaforo(p_ant) != sem else None})
            real = float(atual.iloc[-1])
            pr = real - RNG.normal(0, sig * .8)
            pct = float(_cdf((real - pr) / sig))
            ac_rows.append({"série": f"{prog} · {met}", "proj. 23/09": round(pr, 2), "proj. pipeline": pr,
                            "faixa 80%": f"{pr - 1.2816 * sig:.2f}–{pr + 1.2816 * sig:.2f}",
                            "faixa 95%": f"{pr - 1.96 * sig:.2f}–{pr + 1.96 * sig:.2f}", "realizado": real,
                            "erro (real − proj. 23/09)": real - pr, "percentil": pct,
                            "posição": "dentro da 80%" if .1 <= pct <= .9 else ("dentro da 95%" if .025 <= pct <= .975 else "fora da 95%")})
            jit = lambda: float(np.clip(P["100"] + RNG.normal(0, .04), 0, 1))   # noqa: E731
            sens_rows.append({"programa": prog, "métrica": met, "oficial": P["100"], "p viés": fech_rows[-1]["p viés"],
                              "com viés (se p<0,05)": jit(), "out sem eleição (proj.)": float(proj[0] * 1.004),
                              "sem efeito eleitoral em out": jit(), "incerteza degrau oficial": None if degrau == "—" else jit(),
                              "melhor individual": modelos[RNG.integers(0, 4)], "só o melhor modelo individual": jit(),
                              "3 exibições a menos no passado": None if prog == tv.FAIXA else jit()})
            exib_rest = "/".join(str(int(x)) for x in w)
            acum_rows.append({"série": f"{prog} · {met}", "acum. oficial 20/09": acum + RNG.normal(0, .01),
                              "recalculado pelo calendário": acum, "diferença": RNG.normal(0, .005), "set parcial": real + RNG.normal(0, .1),
                              "set fechado": real, "21–30/09 (implícito)": real + RNG.normal(0, .15), "exib. 21–30/09": 10 if dias == tv.TODOS else 2,
                              "acum. 30/09": acum, "exib. até 30/09": n_ate, "exib. out/nov/dez": exib_rest})
            for ano in (2024, 2025):
                sa = s[str(ano)].dropna()
                ws_ = [w_m(m) for m in sa.index]
                realizado = float(np.average(sa.values, weights=ws_))
                ac_js = float(np.average(sa[:9].values, weights=ws_[:9]))
                projetado = realizado + RNG.normal(0, sd_f * .7)
                bt_rows.append({"programa": prog, "métrica": met, "ano": ano, "acum. jan–set": ac_js, "projetado": projetado,
                                "realizado": realizado, "erro": projetado - realizado, "erro se usasse só o acumulado": ac_js - realizado,
                                "meia-largura IC95 atual": 1.96 * sd_f, "dentro da margem?": "sim" if abs(projetado - realizado) <= 1.96 * sd_f else "não"})
            vals = {m_: mae * RNG.uniform(1.0, 1.25) for m_ in modelos}
            melhor = min(vals, key=vals.get)
            mae_rows.append({"série": f"{prog} · {met}", "Combinação": mae, **vals, "Combinação (degrau na origem)": None,
                             "piora ao reestimar degrau %": None, "Combinação é a melhor?": "sim" if mae <= vals[melhor] else "não",
                             "melhor individual": melhor, "ganho do melhor individual %": (vals[melhor] / mae - 1) * -100})
    arq = os.path.join(pasta, "rodadas", "rodada_2026-09-30.xlsx")
    with pd.ExcelWriter(arq) as xw:
        pd.DataFrame(fech_rows).to_excel(xw, sheet_name="fechamento_e_metas", index=False)
        pd.DataFrame(mens_rows).to_excel(xw, sheet_name="projecao_mensal", index=False)
        pd.DataFrame(vs_rows).to_excel(xw, sheet_name="vs_rodada_23-09", index=False)
        pd.DataFrame(ac_rows).to_excel(xw, sheet_name="setembro_proj_x_real", index=False)
        pd.DataFrame(sens_rows).to_excel(xw, sheet_name="sensibilidade", index=False)
        pd.DataFrame(acum_rows).to_excel(xw, sheet_name="acumulado_30-09", index=False)
        pd.DataFrame(bt_rows).to_excel(xw, sheet_name="backtest_fechamento", index=False)
        pd.DataFrame(mae_rows).rename(columns={"série": ""}).to_excel(xw, sheet_name="validacao_MAE", index=False)
    f6 = {r["métrica"]: r for r in fech_rows if r["programa"] == tv.FAIXA}
    par = {"demo": True,
           "metas_mensais_bi": {f"6h às 24h|{met}": {f"2026-{m:02d}": round(float(f6[met]["meta 100%"]) * k, 2)
                                                     for m, k in ((10, 1.02), (11, 1.0), (12, .94))} for met in tv.METRICAS},
           "rodada_ativa": None, "dados": {"descricao": "DADOS FICTÍCIOS de demonstração", "atualizado_em": "21/10/2026"}}
    json.dump(par, open(os.path.join(destino, "parametros_tv.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # ---- planilha de teste para o envio mensal (formato do consolidado do ano, jan–set/2026)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Planilha1"
    progs_c = [p for p in tv.PROGRAMAS if p != tv.FAIXA_7]
    cab1, cab2 = [None], [None]
    for p in progs_c:
        cab1 += [p.upper(), None, None]
        cab2 += ["AUDIÊNCIA", "SHARE", None]
    ws.append(cab1)
    ws.append(cab2)
    nomes = ["JANEIRO", "FEVEREIRO", "MARÇO", "ABRIL", "MAIO", "JUNHO", "JULHO", "AGOSTO", "SETEMBRO"]
    for k, nm in enumerate(nomes):
        linha = [nm]
        for p in progs_c:
            m = pd.Timestamp(2026, k + 1, 1)
            linha += [round(float(tv.serie(base, p, "Audiência").get(m)), 2), round(float(tv.serie(base, p, "Share").get(m)), 2), nm]
        ws.append(linha[:-1])
    ws.append([])
    ws.append([AVISO])
    wb.save(os.path.join(destino, "TESTE_envio_mensal_DEMO_2026.xlsx"))
    return base


def _rodada_diaria_base(caminho, faixa="6h às 24h", corte="2026-10-26", seed=1):
    rng = np.random.default_rng(seed)
    corte = pd.Timestamp(corte)
    base = 14.6 if faixa.startswith("6") else 14.9
    meses = pd.date_range("2026-10-01", "2026-12-01", freq="MS")
    MES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
    rot = lambda m: f"{MES[m.month - 1]}/{m.year}"          # noqa: E731
    res = []
    for met, b, metas in (("Audiência", base, [base - .3, base, base + .3]), ("Share", 37.2, [35.0, 37.6, 39.0])):
        f = b + rng.normal(0, .1)
        lin = {"métrica": met, "fechamento": f, "IC80 inf": f - .12, "IC80 sup": f + .12, "IC95 inf": f - .2, "IC95 sup": f + .2}
        for n, mt in zip(["75%", "100%", "120%"], metas):
            lin[f"meta {n}"] = mt
            lin[f"P({n})"] = float(np.clip(.5 + (f - mt) * 2.5, .001, .999))
        lin["média nec. 100% (dias restantes)"] = metas[1] + .4
        lin["média proj. (dias restantes)"] = f + .2 if met == "Audiência" else np.nan
        p = lin["P(100%)"]
        lin["semáforo 100%"] = ("Muito provável" if p >= .9 else "Provável" if p >= .66 else "Indefinido" if p >= .33
                               else "Improvável" if p >= .1 else "Muito improvável")
        res.append(lin)
    mensal = []
    for m in meses:
        for met, b in (("Audiência", base), ("Share", 37.2)):
            v = b + rng.normal(0, .3)
            mensal.append({"métrica": met, "mês": rot(m), "projeção": v, "IC80 inf": v - .5, "IC80 sup": v + .5,
                           "IC95 inf": v - .8, "IC95 sup": v + .8})
    comp = pd.DataFrame({"dias realizados": [corte.day, 0, 0]}, index=[rot(m) for m in meses])
    for met, b in (("aud", base), ("shr", 37.2)):
        comp[f"parcial {met}"] = [b + .1, np.nan, np.nan]
        for k in ("diário", "mensal", "comb"):
            comp[f"{k} {met}"] = b + rng.normal(0, .2, 3)
    dias = pd.date_range(corte + pd.Timedelta(days=1), "2026-12-31")
    shr = 37.2 + 1.5 * np.sin(np.arange(len(dias)) / 7 * 2 * np.pi) + rng.normal(0, .6, len(dias))
    tl = 39 + rng.normal(0, 1, len(dias))
    diaria = pd.DataFrame({"shr": shr, "tl": tl, "rat": shr * tl / 100}, index=dias)
    serie = pd.DataFrame({"rat": base + rng.normal(0, .4, 22), "tl": 39 + rng.normal(0, .5, 22), "dias": 30},
                         index=pd.date_range("2025-01-01", "2026-10-01", freq="MS"))
    serie["shr"] = 100 * serie.rat / serie.tl
    val = pd.DataFrame([{"horizonte": h, "modelo": mo, "n": 24, "aud |erro| médio": e, "aud vs mensal %": 0, "aud viés": 0,
                         "shr |erro| médio": e * 2, "shr vs mensal %": 0, "shr viés": 0}
                        for h in ("resto do mês", "mês seguinte", "2 meses") for mo, e in (("mensal", .30), ("diário", .26), ("comb", .22))])
    ef = pd.DataFrame({"share (pts)": [1.2, -.8, .9], "TL (pts)": [.5, -.3, 1.1], "p share": [.01, .2, .04]},
                      index=["jogo baiano", "feriado", "HGPE"])
    ef["audiência (pts, aprox.)"] = ef["share (pts)"] * .39 + ef["TL (pts)"] * .37
    dsem = pd.DataFrame({"share (pts)": rng.normal(0, 1, 6), "TL (pts)": rng.normal(0, 1, 6)},
                        index=["terça", "quarta", "quinta", "sexta", "sábado", "domingo"])
    dsem["audiência (pts, aprox.)"] = dsem["share (pts)"] * .39
    cmp = pd.DataFrame([{"métrica": "Audiência", "item": "fechamento", "anterior": base - .1, "atual": res[0]["fechamento"]},
                        {"métrica": "Audiência", "item": "P(meta 100%)", "anterior": .6, "atual": res[0]["P(100%)"]}])
    cmp["diferença"] = cmp.atual - cmp.anterior
    with pd.ExcelWriter(caminho) as xw:
        pd.DataFrame(res).set_index("métrica").to_excel(xw, sheet_name="fechamento_e_metas")
        pd.DataFrame(mensal).to_excel(xw, sheet_name="projecao_mensal", index=False)
        comp.to_excel(xw, sheet_name="componentes")
        val.set_index(["horizonte", "modelo"]).to_excel(xw, sheet_name="validacao")
        ef.to_excel(xw, sheet_name="efeitos")
        dsem.to_excel(xw, sheet_name="dia_da_semana")
        cmp.to_excel(xw, sheet_name="vs_rodada_anterior", index=False)
        serie.to_excel(xw, sheet_name="serie_mensal")
        diaria.to_excel(xw, sheet_name="projecao_diaria")
    return caminho


def gera(destino="."):
    """Cria destino/dados/... e destino/parametros_tv.json com dados fictícios."""
    _gera_mensal(destino, np.random.default_rng(20261021))
    _gera_diario(destino)


def _gera_diario(destino):
    base = tv.ler_base(os.path.join(destino, "dados", "tv_mensal.csv"))
    for faixa, seed in (("6h às 24h", 11), ("7h às 24h", 12)):
        arq = os.path.join(destino, "dados", "rodadas_diarias", f"projecao_2026_{faixa[0]}h24h_diario_20261026.xlsx")
        os.makedirs(os.path.dirname(arq), exist_ok=True)
        _rodada_diaria_base(arq, faixa, corte="2026-10-26", seed=seed)
        x = pd.read_excel(arq, sheet_name=None)
        aud = tv.serie(base, faixa, "Audiência"); shr = tv.serie(base, faixa, "Share")
        gen_aud = 14.6 if faixa.startswith("6") else 14.9
        d_aud = float(aud["2026"].mean()) - gen_aud
        d_shr = float(shr["2026"].mean()) - 37.2
        f = x["fechamento_e_metas"]
        for col in f.columns:
            if col not in ("métrica", "semáforo 100%") and not col.startswith("P("):
                f[col] = f[col].astype(float)
                f.loc[f["métrica"] == "Audiência", col] = f.loc[f["métrica"] == "Audiência", col] + d_aud
                f.loc[f["métrica"] == "Share", col] = f.loc[f["métrica"] == "Share", col] + d_shr
        m = x["projecao_mensal"]
        for col in ("projeção", "IC80 inf", "IC80 sup", "IC95 inf", "IC95 sup"):
            m[col] = m[col].astype(float)
            m.loc[m["métrica"] == "Audiência", col] += d_aud
            m.loc[m["métrica"] == "Share", col] += d_shr
        c = x["componentes"]
        for col in c.columns:
            if col.endswith(" aud"):
                c[col] = c[col] + d_aud
            elif col.endswith(" shr"):
                c[col] = c[col] + d_shr
        dia = x["projecao_diaria"]
        dia["shr"] = dia["shr"] + d_shr
        dia["rat"] = dia["shr"] * dia["tl"] / 100
        meses = pd.date_range("2025-01-01", "2026-09-01", freq="MS")
        serie = pd.DataFrame({"rat": aud.reindex(meses).values, "shr": shr.reindex(meses).values}, index=meses)
        serie["tl"] = serie["rat"] / serie["shr"] * 100
        serie["dias"] = [pd.Period(m, "M").days_in_month for m in meses]
        x["serie_mensal"] = serie.rename_axis("mês").reset_index()
        cmp = x["vs_rodada_anterior"]
        cmp[["anterior", "atual"]] = cmp[["anterior", "atual"]].astype(float)
        cmp.loc[cmp["item"] == "fechamento", ["anterior", "atual"]] += d_aud
        with pd.ExcelWriter(arq) as xw:
            for nome, df in x.items():
                idx = nome in ("componentes", "efeitos", "dia_da_semana", "projecao_diaria")
                df.to_excel(xw, sheet_name=nome, index=False)


if __name__ == "__main__":
    gera(".")
    print("dados fictícios gerados em ./dados e ./parametros_tv.json")
