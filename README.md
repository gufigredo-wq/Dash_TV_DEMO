# Painel de Audiência · TV

Audiência (Rat%) e share (Shr%) mensais da TV Bahia (Globo) na Grande Salvador — Kantar IBOPE/Instar, TT Domicílios:
faixas 6h e 7h às 24h e programas locais.

- **Faixa horária de referência** (acima das abas): **6h às 24h** ou **7h às 24h**. A Visão geral passa a mostrar a faixa
  escolhida e as Projeções mostram o modelo diário dessa faixa.
- **Visão geral**: cartões do último mês e da média parcial do ano, evolução, desempenho de todos os programas, média
  anual, curva do ano, mapa de calor, comparativo; mais visualizações em **🧩 Visualizações da tela inicial** (rodapé).
- **Projeções e metas**: ① modelo diário da faixa escolhida (chance das metas, ano mês a mês com faixas, caminho dia a
  dia, como a projeção é montada, efeitos, dia da semana, validação); ② a ④ modelo mensal por programa: panorama das metas, painel da meta 100%, ficha de cada programa e resultados detalhados, a
  partir da planilha de resultado do notebook de projeção.
- **📄 Exportar PDF** e **🌙 Modo escuro** no cabeçalho; **⚙ Atualizar dados** no rodapé.

## Notebooks de projeção (`notebooks/`)
- `Projecao_2026_6h24h_diario.ipynb` e `Projecao_2026_7h24h_diario.ipynb`: modelo diário de cada faixa (mesmo código,
  parâmetros da faixa). Saída: `projecao_2026_6h24h_diario_AAAAMMDD.xlsx` → enviar em ⚙ Atualizar dados.
- `Projecao_2026_mensal_programas.ipynb`: modelo mensal da faixa 6h e dos programas. Saída: `resultado_projecao_*.xlsx`.

## Rodar
```
pip install -r requirements.txt
streamlit run streamlit_app.py
pytest testes -q
```
Dados: banco da empresa (`[banco] url` nos Secrets ou `PAINEL_DB_URL`; contrato em `ESQUEMA_BANCO.md`; carga inicial
`python carga_banco.py --url "..." --criar`) ou, sem banco, `dados/tv_mensal.csv` e `dados/rodadas/`.
Testes no Azure DevOps: `azure-pipelines.yml`. Detalhes técnicos: `DOCUMENTACAO_TECNICA.md`.
