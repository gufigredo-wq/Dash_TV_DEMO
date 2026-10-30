# Banco de dados dos Painéis de Audiência — contrato das tabelas

O painel de **TV** lê estas tabelas quando há uma conexão configurada (`[banco] url` nos Secrets do
Streamlit ou a variável de ambiente `PAINEL_DB_URL`, no formato do SQLAlchemy). A aplicação de carga da TI grava as
tabelas de **audiência** e **demográfico**; os painéis gravam só `painel_parametros` e `tv_rodadas`.

- Datas: `data` = dia 1º do mês (ex.: banco jul–set/2026 → `inicio` 2026-07-01, `fim` 2026-09-01).
- `atualizado_em`: data e hora da carga; os painéis usam `MAX(atualizado_em)` e o nº de linhas para saber quando recarregar.
- Carga por chave: para atualizar, apague as linhas com a mesma chave e insira de novo (é o que `banco.gravar()` faz).
- As tabelas podem ser criadas por `python carga_banco.py --url ... --apenas-criar` (SQLAlchemy cria no dialeto do banco).



## `tv_audiencia_mensal`

Audiência mensal de TV (Kantar IBOPE/Instar, TT Domicílios). `programa` ex.: '6h às 24h', '7h às 24h', 'Jornal da Manhã', 'BATV'…; `metrica` ∈ 'Audiência' (Rat%), 'Share' (Shr%); `mes` = dia 1º do mês.

| coluna | tipo | chave |
|---|---|---|
| `programa` | texto(60) | sim |
| `metrica` | texto(20) | sim |
| `mes` | data | sim |
| `valor` | número |  |
| `origem` | texto(200) |  |
| `atualizado_em` | data e hora |  |

## `tv_audiencia_diaria`

Audiência diária de TV por faixa ou programa (Instar Analytics, TT Domicílios, Grande Salvador). `programa` ex.: '6h às 24h', '7h às 24h', 'Jornal da Manhã', 'BATV'…; `rat` = Rat% do dia, `shr` = Shr% do dia; `data` = o dia. É a base dos modelos diários das faixas (notebooks em `notebooks/`).

| coluna | tipo | chave |
|---|---|---|
| `programa` | texto(60) | sim |
| `data` | data | sim |
| `rat` | número |  |
| `shr` | número |  |
| `origem` | texto(200) |  |
| `atualizado_em` | data e hora |  |

## `tv_rodadas`

Rodadas da projeção de TV, guardadas inteiras (`conteudo`): a planilha do modelo mensal por programa (`resultado_projecao_*.xlsx`) e as do modelo diário de cada faixa (`projecao_2026_6h24h_diario_*.xlsx`, `projecao_2026_7h24h_diario_*.xlsx`; o nome indica a faixa e a data de corte). Gravada pelo painel (Atualizar dados → Enviar uma rodada) ou pela carga.

| coluna | tipo | chave |
|---|---|---|
| `nome_arquivo` | texto(120) | sim |
| `corte` | data |  |
| `conteudo` | binário |  |
| `atualizado_em` | data e hora |  |

## `painel_parametros`

Parâmetros editados nos painéis, um por linha, com o valor em JSON: `painel` ∈ radio, tv. Rádio: oficial, previsao_bi, excluidos, dados. TV: metas_mensais_bi, rodada_ativa, dados.

| coluna | tipo | chave |
|---|---|---|
| `painel` | texto(10) | sim |
| `chave` | texto(60) | sim |
| `valor` | texto longo (JSON) |  |
| `atualizado_em` | data e hora |  |

## Exemplo (PostgreSQL)

```sql
CREATE TABLE tv_audiencia_mensal (programa varchar(60) NOT NULL, metrica varchar(20) NOT NULL, mes date NOT NULL,
  valor double precision, origem varchar(200), atualizado_em timestamp, PRIMARY KEY (programa, metrica, mes));
-- as demais seguem o mesmo padrão (ou use: python carga_banco.py --url ... --apenas-criar)
```

> `painel_parametros` é a mesma tabela nos dois painéis (coluna `painel` = 'radio' ou 'tv'): os painéis de rádio e TV podem usar o mesmo banco. O `banco.py` cria todas as tabelas do contrato completo; as do outro painel ficam vazias.
