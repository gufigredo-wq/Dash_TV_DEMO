"""Cria as tabelas no banco e carrega os arquivos do repositório (uso pela TI na implantação, ou para recarregar).

    python carga_banco.py --url "postgresql+psycopg://usuario:senha@servidor:5432/audiencia" --criar
    python carga_banco.py --criar --apenas-criar            # só cria as tabelas (url em PAINEL_DB_URL)

No repositório do rádio carrega: dados/*.xlsx e radio_movel.csv (radio_audiencia), dados/demografico/*.xlsx
(radio_demografico) e parametros.json (painel_parametros, painel='radio').
No repositório da TV carrega: dados/tv_mensal.csv (tv_audiencia_mensal), dados/diario/*.xlsx (tv_audiencia_diaria),
dados/rodadas/*.xlsx e dados/rodadas_diarias/*.xlsx (tv_rodadas) e
parametros_tv.json (painel_parametros, painel='tv').
A aplicação de carga da TI pode gravar direto nas mesmas tabelas (contrato em ESQUEMA_BANCO.md)."""
import argparse
import glob
import json
import os
import sys

import pandas as pd

AQUI = os.path.dirname(os.path.abspath(__file__))
os.chdir(AQUI)
sys.path.insert(0, AQUI)
import banco  # noqa: E402


def carga_radio():
    import modelos as M
    d = pd.DataFrame(columns=M.COLUNAS)
    arqs = sorted(glob.glob(os.path.join("dados", "*.xlsx")) + glob.glob(os.path.join("dados", "*.csv")))
    for a in arqs:
        d = M.mesclar(d, M.ler_arquivo(a))[0]
        print(f"  lido {a}")
    if os.path.exists("radio_movel.csv"):
        d = M.mesclar(d, pd.read_csv("radio_movel.csv", parse_dates=["inicio", "fim"]))[0]
        print("  lido radio_movel.csv")
    if len(d):
        print(f"radio_audiencia: {banco.gravar('radio_audiencia', d)} linhas")
    try:
        import demografico as DM
        dm = DM.carregar()
        if len(dm):
            print(f"radio_demografico: {banco.gravar('radio_demografico', dm)} linhas")
    except ImportError:
        pass
    if os.path.exists("parametros.json"):
        print(f"painel_parametros (radio): {banco.salvar_parametros('radio', json.load(open('parametros.json', encoding='utf-8')))} chaves")


def carga_tv():
    import tv
    if os.path.exists(os.path.join("dados", "tv_mensal.csv")):
        b = tv.ler_base(os.path.join("dados", "tv_mensal.csv"))
        print(f"tv_audiencia_mensal: {banco.gravar('tv_audiencia_mensal', b)} linhas")
    import diario
    for a in sorted(glob.glob(os.path.join("dados", "diario", "*.xlsx"))):        # exportações diárias do Instar
        try:
            d = diario.ler_instar_programas(a, tv.NOME_PROG)
            d["origem"] = os.path.basename(a)
            print(f"tv_audiencia_diaria: {banco.gravar('tv_audiencia_diaria', d)} linhas ({os.path.basename(a)})")
        except Exception as ex:
            print(f"  {os.path.basename(a)}: não li como exportação diária por programa ({ex})")
    for a in sorted(glob.glob(os.path.join("dados", "rodadas_diarias", "*.xlsx"))):   # modelo diário (por faixa)
        banco.gravar_rodada(os.path.basename(a), open(a, "rb").read())
        print(f"tv_rodadas (diário): {os.path.basename(a)}")
    for a in sorted(glob.glob(os.path.join("dados", "rodadas", "*.xlsx"))):
        corte = None
        try:
            corte = tv.ler_resultado(a)["meta"].get("corte")
        except Exception:
            pass
        banco.gravar_rodada(os.path.basename(a), open(a, "rb").read(), corte)
        print(f"tv_rodadas: {os.path.basename(a)}")
    if os.path.exists("parametros_tv.json"):
        print(f"painel_parametros (tv): {banco.salvar_parametros('tv', json.load(open('parametros_tv.json', encoding='utf-8')))} chaves")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", help="endereço SQLAlchemy do banco (senão usa PAINEL_DB_URL)")
    ap.add_argument("--criar", action="store_true", help="cria as tabelas que faltarem")
    ap.add_argument("--apenas-criar", action="store_true", help="só cria as tabelas, sem carregar arquivos")
    a = ap.parse_args()
    if a.url:
        os.environ["PAINEL_DB_URL"] = a.url
    if not banco.ativo():
        sys.exit("Informe --url ou a variável PAINEL_DB_URL.")
    if a.criar or a.apenas_criar:
        banco.criar_tabelas()
        print("tabelas conferidas/criadas:", ", ".join(banco.TABELAS))
    if not a.apenas_criar:
        carga_radio() if os.path.exists("modelos.py") else carga_tv()
