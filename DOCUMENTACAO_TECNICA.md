# Painel de Audiência · TV — documentação técnica

Audiência (Rat%) e share (Shr%) mensais da Globo/TV Bahia na Grande Salvador (Kantar IBOPE/Instar, TT Domicílios): faixas
6h e 7h às 24h e programas locais, com as rodadas da projeção do fechamento do ano e relatórios em PDF.

| Arquivo | Função |
|---|---|
| `streamlit_app.py` | Interface: Visão geral (desempenho, extras), Projeções e metas (panorama, ficha, resultados detalhados), Atualizar dados, PDF |
| `diario.py` | Modelo diário por faixa: leitura da planilha de resultado dos notebooks diários (6h e 7h às 24h) e da exportação diária por programa do Instar Analytics |
| `notebooks/` | Notebooks de projeção: diário 6h às 24h, diário 7h às 24h e mensal por programa |
| `tv.py` | Programas, calendário de exibições, leitura da base mensal, das planilhas consolidadas e da planilha de resultado do notebook |
| `relatorio.py` | PDF (redesenha os gráficos com Matplotlib) |
| `banco.py` / `carga_banco.py` | Banco de dados da empresa (SQLAlchemy) e carga inicial a partir dos arquivos |
| `dados/tv_mensal.csv` | Base mensal (programa, métrica, mês, valor, origem) — modo arquivos |
| `dados/rodadas_diarias/*.xlsx` | Resultados do modelo diário (um arquivo por faixa e data de corte) |
| `dados/diario/*.xlsx` | Exportação diária por programa do Instar Analytics (carga de `tv_audiencia_diaria`) |
| `dados/rodadas/*.xlsx` | Planilhas de resultado das rodadas da projeção (notebook) |
| `parametros_tv.json` | Metas mensais do BI, rodada exibida, descrição da última atualização |

**Faixas**: um seletor acima das abas separa **6h às 24h** e **7h às 24h** (Visão geral e modelo diário).

**Projeção**: o painel não calcula; lê a planilha `resultado_projecao_*.xlsx` gerada pelo notebook de projeção (abas
fechamento_e_metas, projecao_mensal, vs_rodada_DD-MM, setembro_proj_x_real, sensibilidade, acumulado, backtest, validação).

**Banco de dados**: com `[banco] url` nos Secrets (ou `PAINEL_DB_URL`), lê `tv_audiencia_mensal`, `tv_rodadas` (modelos mensal e diário) e
`painel_parametros` (contrato em `ESQUEMA_BANCO.md`). Nesse modo, a base mensal vem da aplicação de carga da TI; o painel
continua recebendo as rodadas da projeção e as metas do BI (gravadas em `tv_rodadas` e `painel_parametros`).

**Executar**: `pip install -r requirements.txt && streamlit run streamlit_app.py`. Testes: `pytest testes -q`.
Hospedagem: igual ao painel de rádio (serviço atrás de proxy reverso com WebSocket habilitado; 1–2 GB de RAM bastam).
