<p align="center">
  <img src="static/SB_farma_oficial_branco.png" alt="SB Farma" width="360">
</p>

<h1 align="center">Radar de Pré-Vencidos</h1>

<p align="center">
  <b>Prevenção de Perdas · Vencimentos · Estoque Parado · Conversão · Priorização de Lojas</b><br>
  Painel web para acompanhamento dos lotes em prevenção nas filiais da SB Farma
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.13-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/FastAPI-0.110-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/PostgreSQL-16-4169E1?style=flat-square&logo=postgresql&logoColor=white" alt="PostgreSQL">
  <img src="https://img.shields.io/badge/Tailwind_CSS-CDN-06B6D4?style=flat-square&logo=tailwindcss&logoColor=white" alt="Tailwind CSS">
  <img src="https://img.shields.io/badge/Chart.js-4-96588A?style=flat-square&logo=chartdotjs&logoColor=white" alt="Chart.js">
  <img src="https://img.shields.io/badge/Deploy-Vercel-000000?style=flat-square&logo=vercel&logoColor=white" alt="Vercel">
</p>

---

## 📌 Visão Geral

O **Radar de Pré-Vencidos** consolida, em um único painel, os principais indicadores de **prevenção de perdas** da rede:

- Quanto do estoque em regime de **prevenção de vencimento** realmente virou venda;
- O **estoque em prevenção** (unidades e valor a custo) e o **estoque já vencido**;
- O **valor em vendas** e o **valor em transferências** no período;
- A projeção de **vencimentos por loja e por mês**;
- Os **itens sem venda** durante um período configurável;
- **Vendas sem vínculo de lote** (risco de desconto não aplicado);
- Um **ranking de lojas** que exigem intervenção imediata, com score ponderado.

Os dados vêm diretamente do PostgreSQL do sistema de gestão, com **cache em memória de 15 minutos** para reduzir carga no banco. O layout segue o padrão glassmorphism do painel de transferências.

---

## ✨ Funcionalidades

### 🎯 Filtros
- **Período** de análise (data inicial e final);
- **Sem venda há N dias** (30, 60, 90, 180 ou 365);
- **Categorias** — chips com as 7 categorias estratégicas:
  `ETICO`, `GENERICOS`, `SIMILARES`, `DIAMANTES`, `PERFUMARIA`, `CONVENIENCIA` e `LEITES E FRALDAS`.

### 📊 KPIs do topo
| KPI | Descrição |
|-----|-----------|
| **Conversão pré-vencidos** | Unidades vendidas ÷ unidades movimentadas dos lotes incluídos no período |
| **Estoque em prevenção** | Unidades e lotes com saldo positivo e estoque atual suficiente |
| **Estoque a custo** | Saldo em prevenção × custo atual do cadastro do produto/loja |
| **Vendas de pré-vencidos** | Valor e peças vendidas vinculadas a lotes de prevenção |
| **Transferências de prevenção** | Valor e peças recebidas em transferências de lotes em prevenção |
| **Estoque já vencido** | Saldo em prevenção com validade anterior a hoje (a partir de jan/2026) |
| **Vence em até 30 dias** | Saldo em prevenção com validade nos próximos 30 dias |
| **Sem venda há N dias** | Lotes com saldo e sem nenhuma venda no período selecionado |
| **Vendas sem vínculo de lote** | Vendas de produtos com lote ativo na data, mas sem lote apontado |

### 📈 Gráficos
- **Vencimentos projetados por mês** — valor (barras) e unidades (linha) dos próximos 12 meses;
- **Exposição por faixa** — já vencido, 0–30, 31–60 e 61–90 dias;
- **Conversão de itens em prevenção** — destino das unidades: vendidas, baixadas ou outras saídas;
- **Estoque sem venda** — top 12 lojas por valor parado.

### 🗓️ Matriz de vencimentos por loja e mês
Tabela com heatmap (12 meses) mostrando o valor do saldo em prevenção por loja. Células mais intensas indicam maior exposição. Inclui filtro por loja e linha de total.

### 🚨 Ranking de intervenção imediata
Score ponderado e normalizado por loja:

```
score = 3,0 × (vencido / máx. vencido)
      + 2,0 × (0–30 dias / máx. 0–30)
      + 1,0 × (31–90 dias / máx. 31–90)
      + 1,5 × (estoque sem venda / máx. sem venda)
```

- **Top 3** → Crítico (intervenção imediata);
- **4 a 8** → Alto;
- **9 a 15** → Médio;
- **Demais** → Baixo.

O painel destaca as lojas críticas em um alerta no topo e sinaliza os motivos: estoque vencido, vencimento em 30 dias, itens parados e conversão abaixo de 60%.

### 🔎 Itens para ação
- **Vencidos e a vencer em 90 dias** — ordenados por urgência e valor, com lote e validade;
- **Sem venda no período** — maiores valores de estoque parado;
- **Possíveis vendas sem vínculo de lote** — maiores valores vendidos sem apontamento de lote.

Todas as listas têm filtro por loja e exibem até 200 itens.

---

## 🛠️ Stack Tecnológica

| Camada | Tecnologia |
|--------|-----------|
| Backend | **Python**, **FastAPI**, **Uvicorn**, **Psycopg2** (`RealDictCursor`), **python-dotenv** |
| Banco de Dados | **PostgreSQL** |
| Frontend | **HTML5**, **Tailwind CSS** (CDN), **Chart.js** |
| Deploy | **Vercel** (`@vercel/python`) |

---

## 📂 Estrutura do Projeto

```
radar-de-riscos/
├── main.py                  # API FastAPI, queries, KPIs, score de risco e cache
├── requirements.txt         # Dependências Python
├── vercel.json              # Configuração de deploy da Vercel
├── .env.example             # Exemplo de variáveis de ambiente
├── .env                     # Credenciais (gitignored — NÃO versionado)
├── .gitignore
└── static/
    ├── index.html           # Dashboard (KPIs, gráficos, matriz, ranking e itens)
    ├── icon-sb.png          # Favicon
    └── SB_farma_oficial_branco.png  # Logotipo
```

---

## 🔌 API

| Método | Rota | Parâmetros | Descrição |
|--------|------|------------|-----------|
| `GET` | `/` | — | Serve o dashboard (`static/index.html`) |
| `GET` | `/api/dashboard` | `data_inicio`, `data_fim`, `dias_sem_venda`, `categorias`, `forcar_atualizacao` | KPIs, lojas, matriz mensal, ranking e itens para ação |
| `GET` | `/api/status` | — | Idade do cache do dashboard (alimenta o indicador do header) |

**Exemplo:**

```bash
curl "http://127.0.0.1:8000/api/dashboard?data_inicio=2026-07-01&data_fim=2026-10-22&dias_sem_venda=90&categorias=ETICO,GENERICOS,SIMILARES&forcar_atualizacao=true"
```

- `data_inicio` / `data_fim`: formato `YYYY-MM-DD` (padrão: últimos 90 dias);
- `dias_sem_venda`: inteiro entre 7 e 365 (padrão `90`);
- `categorias`: lista separada por vírgula (padrão: todas as 7 categorias);
- `forcar_atualizacao=true`: ignora o cache e consulta o banco novamente.

---

## ▶️ Como Rodar Localmente

**1. Clone o repositório:**
```bash
git clone https://github.com/edudouraado/radar-de-riscos.git
cd radar-de-riscos
```

**2. Crie e ative um ambiente virtual:**
```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate
```

**3. Instale as dependências:**
```bash
pip install -r requirements.txt
```

**4. Configure as variáveis de ambiente** — crie um `.env` na raiz:
```env
DB_NAME=seu_banco
DB_USER=seu_usuario
DB_PASSWORD=sua_senha
DB_HOST=seu_host
DB_PORT=5432
```

**5. Suba o servidor:**
```bash
uvicorn main:app --reload
```

Acesse **http://127.0.0.1:8000/** 🎉

---

## 🔐 Variáveis de Ambiente

| Variável | Obrigatória | Descrição |
|----------|:-----------:|-----------|
| `DB_NAME` | ✅ | Nome do banco de dados |
| `DB_USER` | ✅ | Usuário do banco |
| `DB_PASSWORD` | ✅ | Senha do banco (**não embutida no código**) |
| `DB_HOST` | ✅ | Host do PostgreSQL |
| `DB_PORT` | ✅ | Porta do PostgreSQL (padrão `5432`) |

> ⚠️ **`DB_PASSWORD` é obrigatória.** Ela é lida **apenas** de variável de ambiente. Em produção, configure no painel do provedor (ex.: Vercel → *Settings → Environment Variables*).

---

## 🚀 Deploy (Vercel)

1. Conecte o repositório à Vercel (integração Git);
2. Adicione todas as variáveis `DB_*` em **Settings → Environment Variables**;
3. Faça o deploy (automático a cada push em `main`).

O `vercel.json` já configura o `@vercel/python` apontando para `main.py`.

> ⏱️ A primeira consulta após o cache expirar pode levar de 10 a 40 segundos, pois varre vendas, histórico e prevenção. As seguintes usam o cache de 15 minutos.

---

## 📏 Regras de Negócio

### Universo de análise
- Apenas lotes de **`itemprevencido` com `status = 'A'`**;
- Apenas as **7 categorias estratégicas** (classificação via `classificacao.caminho`);
- Apenas lojas válidas, excluindo as filiais de teste/sistema/delivery:
  `14-2`, `20`, `26`, `40`, `41`, `BKP`, `CLOUD` e `ESC`;
- **Já vencido**: consideradas somente validades a partir de **janeiro de 2026**.

### Saldo em prevenção
Um lote só entra nos indicadores quando:
1. `saldo = quantidadeinicial − quantidademovimentada` é **positivo**;
2. o **estoque atual** da embalagem na loja é **igual ou maior que o saldo**.

> Não é possível ter saldo de prevenção sem estoque correspondente ou com saldo maior que o estoque físico.

### Valorização
- **Estoque em prevenção** = `saldo × custo atual do cadastro` (`custoproduto.custo`, último registro por produto/loja);
- **Vendas de prevenção** = `itemvenda.valortotal` efetivamente praticado;
- **Transferências** = valor dos itens recebidos (`transferencia.status = 'R'`).

### Fontes de dados
| Indicador | Origem |
|-----------|--------|
| Vendas | `itemvenda` + `venda` (`status = 'F'`) |
| Transferências | `itemtransferencia` + `transferencia` (`status = 'R'` — recebida) |
| Estoque atual | `estoque` |
| Custo | `custoproduto` (último registro por produto/loja) |
| Prevenção / lotes | `itemprevencido` (`status = 'A'`) |
| Baixas | `itembaixaestoque` (`status = 'F'`) |
| Sem venda | `historicovenda` (vendas agregadas por loja/embalagem/dia) |
| Classificação | `classificacaoproduto` + `classificacao.caminho` |

### Conversão pré-vencidos
- Universo: itens de `itemprevencido` incluídos no período selecionado;
- Vendidas: soma de `itemvenda.quantidade` vinculadas ao item de prevenção;
- Baixadas: soma de `itembaixaestoque.quantidade` vinculadas ao item;
- **Conversão = vendidas ÷ movimentadas** (movimentação total registrada no item);
- **Perda = baixadas ÷ (vendidas + baixadas)**.

### Vencimentos
- Considera o saldo dos lotes ativos com estoque suficiente;
- Valorizado pelo custo atual do cadastro;
- A matriz cobre o mês atual + próximos 11 meses;
- O bloco "já vencido" ignora validades anteriores a jan/2026.

### Sanidade dos dados
A base legada possui alguns registros com quantidades e validades inconsistentes. Para evitar distorções:
- São ignorados itens com `quantidadeinicial > 100.000`;
- São ignoradas validades posteriores a **2100-01-01**.

> Exemplo encontrado na base: um item com mais de 1 milhão de unidades e outro com validade no ano 5301. Esses registros são excluídos dos cálculos.

---

## 🔒 Segurança

- Credenciais somente em variáveis de ambiente (`.env` em dev, *Environment Variables* em prod);
- O `.env` está no `.gitignore` e **não deve ser versionado**;
- O código não contém senhas embutidas;
- 🚨 Caso o repositório seja tornado público, troque a senha do banco — o histórico do Git preserva commits antigos.

---

## 📄 Licença

Uso interno — SB Farma. Todos os direitos reservados.
