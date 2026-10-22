import os
import time
import traceback
from datetime import date, datetime, timedelta

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
import psycopg2
from psycopg2.extras import RealDictCursor

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = FastAPI(title="Radar de Pré-Vencidos | Prevenção de Perdas")

DB_CONFIG = {
    "dbname": os.getenv("DB_NAME", "sbfarma_esc_20240807"),
    "user": os.getenv("DB_USER", "gestao_estoque"),
    "password": os.getenv("DB_PASSWORD"),
    "host": os.getenv("DB_HOST", "144.22.186.71"),
    "port": int(os.getenv("DB_PORT", 5432)),
    "connect_timeout": 15,
}

if not DB_CONFIG["password"]:
    print(
        "AVISO: variável de ambiente DB_PASSWORD não definida. "
        "Configure-a no .env (dev) ou nas variáveis do provedor (prod)."
    )

CACHE_TTL_SEGUNDOS = 900
CACHE_DASHBOARD = {"chave": None, "timestamp": 0, "dados": None}

LOJAS_EXCLUIDAS = (
    "14-2", "20", "26", "40", "41", "BKP", "CLOUD", "ESC",
)

# Para indicadores de já vencido, considerar somente validade a partir de jan/2026
DATA_MINIMA_VENCIDO = date(2026, 1, 1)

CATEGORIAS_VALIDAS = (
    "ETICO",
    "GENERICOS",
    "SIMILARES",
    "DIAMANTES",
    "PERFUMARIA",
    "CONVENIENCIA",
    "LEITES E FRALDAS",
)

CATEGORIAS_LABELS = {
    "ETICO": "Éticos",
    "GENERICOS": "Genéricos",
    "SIMILARES": "Similares",
    "DIAMANTES": "Diamantes",
    "PERFUMARIA": "Perfumaria",
    "CONVENIENCIA": "Conveniência",
    "LEITES E FRALDAS": "Leites e Fraldas",
}

# Filtros de sanidade para bases legadas (quantidades e validades inconsistentes)
FILTRO_QUALIDADE_PREVENCIDO = """
    ip.quantidadeinicial BETWEEN 0 AND 100000
    AND ip.datavalidade < DATE '2100-01-01'
"""

SALDO_PREVENCIDO = "GREATEST(ip.quantidadeinicial - ip.quantidademovimentada, 0)"

# Custo mais recente por produto/loja (base usada pelo BI do gestor)
CUSTO_PRODUTO_CTE = """,
custo_prod AS (
    SELECT DISTINCT ON (produtoid, unidadenegocioid)
           produtoid, unidadenegocioid, custo
    FROM custoproduto
    ORDER BY produtoid, unidadenegocioid, id DESC
)
"""


# Classificação de produto reaproveitada por todas as consultas.
# O CASE usa os mesmos caminhos do sistema de gestão (PRINCIPAL > 1..7).
PRODUTO_CATEGORIA_CTE = """
WITH prod_cat AS (
    SELECT p.id AS produtoid,
        CASE
            WHEN c.caminho LIKE 'PRINCIPAL > 1%%' THEN 'ETICO'
            WHEN c.caminho LIKE 'PRINCIPAL > 2%%' THEN 'GENERICOS'
            WHEN c.caminho LIKE 'PRINCIPAL > 3%%' THEN 'SIMILARES'
            WHEN c.caminho LIKE 'PRINCIPAL > 4%%' THEN 'DIAMANTES'
            WHEN c.caminho LIKE 'PRINCIPAL > 5%%' THEN 'PERFUMARIA'
            WHEN c.caminho LIKE 'PRINCIPAL > 6%%' THEN 'CONVENIENCIA'
            WHEN c.caminho LIKE 'PRINCIPAL > 7%%' THEN 'LEITES E FRALDAS'
            ELSE 'OUTRO'
        END AS categoria
    FROM produto p
    LEFT JOIN LATERAL (
        SELECT c.caminho
        FROM classificacaoproduto cp
        INNER JOIN classificacao c ON c.id = cp.classificacaoid
        WHERE cp.produtoid = p.id
          AND c.caminho ILIKE '%%PRINCIPAL%%'
          AND c.caminho NOT LIKE 'PRINCIPAL > 9%%'
          AND c.caminho NOT LIKE 'PRINCIPAL > 8%%'
        LIMIT 1
    ) c ON TRUE
)
"""


def get_db_connection():
    return psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)


def to_float(valor):
    return float(valor) if valor is not None else 0.0


def to_int(valor):
    return int(valor) if valor is not None else 0


def parse_periodo(data_inicio, data_fim):
    try:
        inicio = datetime.strptime(data_inicio, "%Y-%m-%d").date()
        fim = datetime.strptime(data_fim, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Datas devem estar no formato YYYY-MM-DD.")
    if inicio > fim:
        raise HTTPException(status_code=400, detail="data_inicio não pode ser maior que data_fim.")
    return inicio, fim


def parse_categorias(valor):
    if not valor:
        return tuple(CATEGORIAS_VALIDAS)
    normalizadas = []
    for item in str(valor).split(","):
        chave = item.strip().upper().replace("_", " ")
        if chave == "LEITES FRALDAS":
            chave = "LEITES E FRALDAS"
        if chave in CATEGORIAS_VALIDAS and chave not in normalizadas:
            normalizadas.append(chave)
    if not normalizadas:
        raise HTTPException(status_code=400, detail="Selecione ao menos uma categoria válida.")
    return tuple(normalizadas)


@app.get("/api/status")
def status_cache():
    return {
        "ttl_segundos": CACHE_TTL_SEGUNDOS,
        "dashboard": {
            "timestamp": CACHE_DASHBOARD["timestamp"],
            "carregado": CACHE_DASHBOARD["dados"] is not None,
            "chave": CACHE_DASHBOARD["chave"],
        },
    }


@app.get("/api/dashboard")
def dashboard(
    data_inicio: str = None,
    data_fim: str = None,
    dias_sem_venda: int = 90,
    categorias: str = None,
    forcar_atualizacao: bool = False,
):
    hoje = date.today()
    data_inicio = data_inicio or (hoje - timedelta(days=90)).isoformat()
    data_fim = data_fim or hoje.isoformat()
    inicio, fim = parse_periodo(data_inicio, data_fim)
    dias_sem_venda = max(7, min(int(dias_sem_venda), 365))
    categorias_sel = parse_categorias(categorias)

    chave = (inicio.isoformat(), fim.isoformat(), dias_sem_venda, categorias_sel)
    agora = time.time()

    if (
        not forcar_atualizacao
        and CACHE_DASHBOARD["dados"] is not None
        and CACHE_DASHBOARD["chave"] == chave
        and (agora - CACHE_DASHBOARD["timestamp"]) < CACHE_TTL_SEGUNDOS
    ):
        return CACHE_DASHBOARD["dados"]

    try:
        dados = montar_dashboard(inicio, fim, dias_sem_venda, categorias_sel)
    except Exception as exc:
        print("=== ERRO AO MONTAR DASHBOARD DE PRÉ-VENCIDOS ===")
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"status": "erro", "mensagem": str(exc), "detalhes": traceback.format_exc()},
        )

    CACHE_DASHBOARD["chave"] = chave
    CACHE_DASHBOARD["timestamp"] = agora
    CACHE_DASHBOARD["dados"] = dados
    return dados


def montar_dashboard(inicio, fim, dias_sem_venda, categorias):
    conn = get_db_connection()
    cur = conn.cursor()
    excl = LOJAS_EXCLUIDAS
    por_loja = {}

    def loja(codigo):
        if codigo not in por_loja:
            por_loja[codigo] = {
                "codigo": codigo,
                "nome": None,
                "estoque_lotes": 0,
                "estoque_skus": 0,
                "estoque_qtd": 0.0,
                "estoque_valor": 0.0,
                "vendas_valor": 0.0,
                "vendas_qtd": 0.0,
                "vendas_itens": 0,
                "transferencias_valor": 0.0,
                "transferencias_qtd": 0.0,
                "prevencao_itens": 0,
                "prevencao_movimentada": 0.0,
                "prevencao_vendidas": 0.0,
                "prevencao_baixadas": 0.0,
                "prevencao_valor_vendido": 0.0,
                "prevencao_valor_baixado": 0.0,
                "vencido_valor": 0.0,
                "d30_valor": 0.0,
                "d60_valor": 0.0,
                "d90_valor": 0.0,
                "saldo_prevencao_qtd": 0.0,
                "sem_venda_lotes": 0,
                "sem_venda_qtd": 0.0,
                "sem_venda_valor": 0.0,
                "sem_lote_itens": 0,
                "sem_lote_qtd": 0.0,
                "sem_lote_valor": 0.0,
            }
        return por_loja[codigo]

    try:
        # ---------- VENDAS DE ITENS COM LOTE DE PREVENÇÃO ----------
        cur.execute(
            PRODUTO_CATEGORIA_CTE
            + """
            SELECT ue.codigo,
                   COALESCE(SUM(iv.valortotal), 0)::float AS valor,
                   COALESCE(SUM(iv.quantidade), 0)::float AS qtd,
                   COUNT(*) AS itens
            FROM itemvenda iv
            INNER JOIN venda v ON v.id = iv.vendaid
            INNER JOIN itemprevencido ip ON ip.id = iv.itemprevencidoid
            INNER JOIN embalagem emb ON emb.id = ip.embalagemid
            INNER JOIN prod_cat pc ON pc.produtoid = emb.produtoid
            INNER JOIN unidadenegocio ue ON ue.id = v.unidadenegocioid
            WHERE iv.status = 'F'
              AND v.status = 'F'
              AND iv.datahora >= %s
              AND iv.datahora < (%s::date + INTERVAL '1 day')
              AND pc.categoria IN %s
              AND ue.codigo NOT IN %s
            GROUP BY ue.codigo
            """,
            (inicio, fim, categorias, excl),
        )
        for r in cur.fetchall():
            l = loja(r["codigo"])
            l["vendas_valor"] = to_float(r["valor"])
            l["vendas_qtd"] = to_float(r["qtd"])
            l["vendas_itens"] = to_int(r["itens"])

        # ---------- TRANSFERÊNCIAS DE ITENS EM PREVENÇÃO ----------
        cur.execute(
            PRODUTO_CATEGORIA_CTE
            + """
            SELECT ue.codigo,
                   COALESCE(SUM(it.valortotal), 0)::float AS valor,
                   COALESCE(SUM(it.quantidade), 0)::float AS qtd
            FROM itemtransferencia it
            INNER JOIN transferencia t ON t.id = it.transferenciaid
            INNER JOIN itemprevencido ip ON ip.id = it.itemprevencidoid
            INNER JOIN embalagem emb ON emb.id = ip.embalagemid
            INNER JOIN prod_cat pc ON pc.produtoid = emb.produtoid
            INNER JOIN unidadenegocio ue ON ue.id = t.unidadenegociodestinoid
            WHERE t.status = 'R'
              AND t.datahora >= %s
              AND t.datahora < (%s::date + INTERVAL '1 day')
              AND pc.categoria IN %s
              AND ue.codigo NOT IN %s
            GROUP BY ue.codigo
            """,
            (inicio, fim, categorias, excl),
        )
        for r in cur.fetchall():
            l = loja(r["codigo"])
            l["transferencias_valor"] = to_float(r["valor"])
            l["transferencias_qtd"] = to_float(r["qtd"])

        # ---------- CONVERSÃO DOS LOTES INCLUÍDOS NO PERÍODO ----------
        cur.execute(
            PRODUTO_CATEGORIA_CTE
            + f""",
            prev AS (
                SELECT ip.id, ue.codigo, ip.quantidadeinicial, ip.quantidademovimentada
                FROM itemprevencido ip
                INNER JOIN embalagem emb ON emb.id = ip.embalagemid
                INNER JOIN prod_cat pc ON pc.produtoid = emb.produtoid
                INNER JOIN unidadenegocio ue ON ue.id = ip.unidadenegocioid
                WHERE ip.datahorainclusao >= %s
                  AND ip.datahorainclusao < (%s::date + INTERVAL '1 day')
                  AND {FILTRO_QUALIDADE_PREVENCIDO}
                  AND pc.categoria IN %s
                  AND ue.codigo NOT IN %s
            ),
            vend AS (
                SELECT iv.itemprevencidoid, SUM(iv.quantidade) AS qtd, SUM(iv.valortotal) AS valor
                FROM itemvenda iv
                INNER JOIN prev p ON p.id = iv.itemprevencidoid
                WHERE iv.status = 'F'
                GROUP BY iv.itemprevencidoid
            ),
            baix AS (
                SELECT ib.itemprevencidoid, SUM(ib.quantidade) AS qtd, SUM(ib.valortotal) AS valor
                FROM itembaixaestoque ib
                INNER JOIN prev p ON p.id = ib.itemprevencidoid
                WHERE ib.status = 'F'
                GROUP BY ib.itemprevencidoid
            )
            SELECT p.codigo,
                   COUNT(*) AS itens,
                   COALESCE(SUM(p.quantidadeinicial), 0)::float AS entradas,
                   COALESCE(SUM(p.quantidademovimentada), 0)::float AS movimentada,
                   COALESCE(SUM(v.qtd), 0)::float AS vendidas,
                   COALESCE(SUM(v.valor), 0)::float AS valor_vendido,
                   COALESCE(SUM(b.qtd), 0)::float AS baixadas,
                   COALESCE(SUM(b.valor), 0)::float AS valor_baixado
            FROM prev p
            LEFT JOIN vend v ON v.itemprevencidoid = p.id
            LEFT JOIN baix b ON b.itemprevencidoid = p.id
            GROUP BY p.codigo
            """,
            (inicio, fim, categorias, excl),
        )
        for r in cur.fetchall():
            l = loja(r["codigo"])
            l["prevencao_itens"] = to_int(r["itens"])
            l["prevencao_movimentada"] = to_float(r["movimentada"])
            l["prevencao_vendidas"] = to_float(r["vendidas"])
            l["prevencao_baixadas"] = to_float(r["baixadas"])
            l["prevencao_valor_vendido"] = to_float(r["valor_vendido"])
            l["prevencao_valor_baixado"] = to_float(r["valor_baixado"])

        # ---------- POSSÍVEIS VENDAS SEM VÍNCULO DE LOTE ----------
        # Venda de produto/loja que possuía lote de prevenção ativo na data,
        # mas o item vendido não aponta para um itemprevencido.
        cur.execute(
            PRODUTO_CATEGORIA_CTE
            + """
            SELECT ue.codigo,
                   COUNT(*) AS itens,
                   COALESCE(SUM(iv.quantidade), 0)::float AS qtd,
                   COALESCE(SUM(iv.valortotal), 0)::float AS valor
            FROM itemvenda iv
            INNER JOIN venda v ON v.id = iv.vendaid
            INNER JOIN embalagem emb ON emb.id = iv.embalagemid
            INNER JOIN prod_cat pc ON pc.produtoid = emb.produtoid
            INNER JOIN unidadenegocio ue ON ue.id = v.unidadenegocioid
            WHERE iv.status = 'F'
              AND v.status = 'F'
              AND iv.datahora >= %s
              AND iv.datahora < (%s::date + INTERVAL '1 day')
              AND iv.itemprevencidoid IS NULL
              AND pc.categoria IN %s
              AND ue.codigo NOT IN %s
              AND EXISTS (
                  SELECT 1 FROM itemprevencido ip
                  WHERE ip.embalagemid = iv.embalagemid
                    AND ip.unidadenegocioid = iv.unidadenegocioid
                    AND ip.datahorainclusao <= iv.datahora
                    AND (ip.datahoraencerramento IS NULL OR ip.datahoraencerramento >= iv.datahora)
                    AND ip.quantidadeinicial BETWEEN 0 AND 100000
                    AND ip.datavalidade < DATE '2100-01-01'
              )
            GROUP BY ue.codigo
            """,
            (inicio, fim, categorias, excl),
        )
        for r in cur.fetchall():
            l = loja(r["codigo"])
            l["sem_lote_itens"] = to_int(r["itens"])
            l["sem_lote_qtd"] = to_float(r["qtd"])
            l["sem_lote_valor"] = to_float(r["valor"])

        # ---------- LOTES ATIVOS: ESTOQUE, EXPOSIÇÃO, MENSAL E SEM VENDA ----------
        # Valorização pelo custo atual do cadastro do produto/loja.
        cur.execute(
            PRODUTO_CATEGORIA_CTE
            + CUSTO_PRODUTO_CTE
            + f"""
            SELECT ip.id,
                   ue.codigo,
                   ue.nome,
                   emb.produtoid,
                   emb.descricao,
                   pc.categoria,
                   COALESCE(ip.lote, '-') AS lote,
                   ip.datavalidade,
                   {SALDO_PREVENCIDO}::float AS saldo,
                   COALESCE(cp.custo, 0)::float AS custo
            FROM itemprevencido ip
            INNER JOIN embalagem emb ON emb.id = ip.embalagemid
            INNER JOIN prod_cat pc ON pc.produtoid = emb.produtoid
            INNER JOIN unidadenegocio ue ON ue.id = ip.unidadenegocioid
            LEFT JOIN custo_prod cp
                   ON cp.produtoid = emb.produtoid
                  AND cp.unidadenegocioid = ip.unidadenegocioid
            INNER JOIN estoque est
                   ON est.embalagemid = ip.embalagemid
                  AND est.unidadenegocioid = ip.unidadenegocioid
            WHERE ip.status = 'A'
              AND {FILTRO_QUALIDADE_PREVENCIDO}
              AND {SALDO_PREVENCIDO} > 0
              AND COALESCE(est.estoque, 0) >= {SALDO_PREVENCIDO}
              AND pc.categoria IN %s
              AND ue.codigo NOT IN %s
            """,
            (categorias, excl),
        )
        lotes_ativos = cur.fetchall()

        cur.execute(
            """
            SELECT DISTINCT itemprevencidoid
            FROM itemvenda
            WHERE status = 'F'
              AND itemprevencidoid IS NOT NULL
              AND datahora >= CURRENT_DATE - %s
            """,
            (dias_sem_venda,),
        )
        lotes_vendidos_periodo = {r["itemprevencidoid"] for r in cur.fetchall()}

        hoje = date.today()
        mes_ini = hoje.replace(day=1)
        mes_fim = date(mes_ini.year + 1, mes_ini.month, 1)
        limite_90 = hoje + timedelta(days=90)

        vencimentos_mensal_map = {}
        skus_por_loja = {}
        top_vencendo = []
        top_sem_venda = []

        for r in lotes_ativos:
            codigo = r["codigo"]
            l = loja(codigo)
            l["nome"] = r["nome"]
            saldo = to_float(r["saldo"])
            valor = saldo * to_float(r["custo"])
            validade = r["datavalidade"]
            validade_data = validade.date() if hasattr(validade, "date") else validade
            dias = (validade_data - hoje).days
            mes = validade_data.strftime("%Y-%m")

            l["estoque_lotes"] += 1
            l["estoque_qtd"] += saldo
            l["estoque_valor"] += valor
            l["saldo_prevencao_qtd"] += saldo
            skus_por_loja.setdefault(codigo, set()).add(r["produtoid"])

            if dias < 0:
                if validade_data >= DATA_MINIMA_VENCIDO:
                    l["vencido_valor"] += valor
            elif dias < 30:
                l["d30_valor"] += valor
            elif dias < 60:
                l["d60_valor"] += valor
            elif dias < 90:
                l["d90_valor"] += valor

            if mes_ini <= validade_data < mes_fim:
                chave_mes = (codigo, mes)
                if chave_mes not in vencimentos_mensal_map:
                    vencimentos_mensal_map[chave_mes] = {
                        "loja": codigo,
                        "nome": r["nome"],
                        "mes": mes,
                        "qtd": 0.0,
                        "valor": 0.0,
                    }
                vencimentos_mensal_map[chave_mes]["qtd"] += saldo
                vencimentos_mensal_map[chave_mes]["valor"] += valor

            item = {
                "loja": codigo,
                "descricao": r["descricao"],
                "categoria": CATEGORIAS_LABELS.get(r["categoria"], r["categoria"]),
                "lote": r["lote"],
                "validade": validade_data.isoformat(),
                "dias": dias,
                "qtd": saldo,
                "valor": valor,
            }

            if validade_data >= DATA_MINIMA_VENCIDO and validade_data < limite_90:
                top_vencendo.append(item)

            if r["id"] not in lotes_vendidos_periodo:
                l["sem_venda_lotes"] += 1
                l["sem_venda_qtd"] += saldo
                l["sem_venda_valor"] += valor
                top_sem_venda.append(item)

        for codigo, produtos in skus_por_loja.items():
            por_loja[codigo]["estoque_skus"] = len(produtos)

        vencimentos_mensal = sorted(
            vencimentos_mensal_map.values(),
            key=lambda x: (x["mes"], x["loja"]),
        )
        top_vencendo.sort(key=lambda x: (x["dias"], -x["valor"]))
        top_vencendo = top_vencendo[:200]
        top_sem_venda.sort(key=lambda x: -x["valor"])
        top_sem_venda = top_sem_venda[:200]

        # ---------- TOP POSSÍVEIS VENDAS SEM LOTE ----------
        cur.execute(
            PRODUTO_CATEGORIA_CTE
            + """
            SELECT ue.codigo,
                   iv.datahora::date::text AS data,
                   emb.descricao,
                   pc.categoria,
                   iv.quantidade::float AS qtd,
                   iv.valortotal::float AS valor
            FROM itemvenda iv
            INNER JOIN venda v ON v.id = iv.vendaid
            INNER JOIN embalagem emb ON emb.id = iv.embalagemid
            INNER JOIN prod_cat pc ON pc.produtoid = emb.produtoid
            INNER JOIN unidadenegocio ue ON ue.id = v.unidadenegocioid
            WHERE iv.status = 'F'
              AND v.status = 'F'
              AND iv.datahora >= %s
              AND iv.datahora < (%s::date + INTERVAL '1 day')
              AND iv.itemprevencidoid IS NULL
              AND pc.categoria IN %s
              AND ue.codigo NOT IN %s
              AND EXISTS (
                  SELECT 1 FROM itemprevencido ip
                  WHERE ip.embalagemid = iv.embalagemid
                    AND ip.unidadenegocioid = iv.unidadenegocioid
                    AND ip.datahorainclusao <= iv.datahora
                    AND (ip.datahoraencerramento IS NULL OR ip.datahoraencerramento >= iv.datahora)
                    AND ip.quantidadeinicial BETWEEN 0 AND 100000
                    AND ip.datavalidade < DATE '2100-01-01'
              )
            ORDER BY iv.valortotal DESC
            LIMIT 200
            """,
            (inicio, fim, categorias, excl),
        )
        top_sem_lote = [
            {
                "loja": r["codigo"],
                "data": r["data"],
                "descricao": r["descricao"],
                "categoria": CATEGORIAS_LABELS.get(r["categoria"], r["categoria"]),
                "qtd": to_float(r["qtd"]),
                "valor": to_float(r["valor"]),
            }
            for r in cur.fetchall()
        ]
    finally:
        cur.close()
        conn.close()

    # ---------- CONSOLIDAÇÃO E SCORE DE RISCO ----------
    lojas = list(por_loja.values())
    for l in lojas:
        disp = l["prevencao_vendidas"] + l["prevencao_baixadas"]
        l["conversao_pct"] = round(
            (l["prevencao_vendidas"] / l["prevencao_movimentada"]) * 100, 1
        ) if l["prevencao_movimentada"] > 0 else 0.0
        l["perda_pct"] = round((l["prevencao_baixadas"] / disp) * 100, 1) if disp > 0 else 0.0
        l["risco_score"] = 0.0
        l["risco_nivel"] = "Baixo"
        l["intervencao_imediata"] = False
        l["motivos"] = []

    max_vencido = max((l["vencido_valor"] for l in lojas), default=0) or 1.0
    max_d30 = max((l["d30_valor"] for l in lojas), default=0) or 1.0
    max_d60_90 = max(((l["d60_valor"] + l["d90_valor"]) for l in lojas), default=0) or 1.0
    max_sem_venda = max((l["sem_venda_valor"] for l in lojas), default=0) or 1.0

    for l in lojas:
        l["risco_score"] = round(
            3.0 * (l["vencido_valor"] / max_vencido)
            + 2.0 * (l["d30_valor"] / max_d30)
            + 1.0 * ((l["d60_valor"] + l["d90_valor"]) / max_d60_90)
            + 1.5 * (l["sem_venda_valor"] / max_sem_venda),
            2,
        )

    lojas.sort(key=lambda x: x["risco_score"], reverse=True)
    for pos, l in enumerate(lojas):
        if pos < 3:
            l["risco_nivel"] = "Crítico"
            l["intervencao_imediata"] = True
        elif pos < 8:
            l["risco_nivel"] = "Alto"
            l["intervencao_imediata"] = True
        elif pos < 15:
            l["risco_nivel"] = "Médio"
        else:
            l["risco_nivel"] = "Baixo"

        if l["vencido_valor"] > 0:
            l["motivos"].append("Estoque já vencido")
        if l["d30_valor"] > 0:
            l["motivos"].append("Vence em até 30 dias")
        if l["sem_venda_lotes"] > 0:
            l["motivos"].append("Lotes sem venda")
        if l["prevencao_movimentada"] > 0 and l["conversao_pct"] < 60:
            l["motivos"].append("Conversão abaixo de 60%")
        if l["sem_lote_valor"] > 0:
            l["motivos"].append("Vendas sem vínculo de lote")

    kpis = {
        "estoque_lotes": sum(l["estoque_lotes"] for l in lojas),
        "estoque_skus": sum(l["estoque_skus"] for l in lojas),
        "estoque_qtd": sum(l["estoque_qtd"] for l in lojas),
        "estoque_valor": sum(l["estoque_valor"] for l in lojas),
        "vendas_valor": sum(l["vendas_valor"] for l in lojas),
        "vendas_qtd": sum(l["vendas_qtd"] for l in lojas),
        "vendas_itens": sum(l["vendas_itens"] for l in lojas),
        "transferencias_valor": sum(l["transferencias_valor"] for l in lojas),
        "transferencias_qtd": sum(l["transferencias_qtd"] for l in lojas),
        "prevencao_itens": sum(l["prevencao_itens"] for l in lojas),
        "prevencao_movimentada": sum(l["prevencao_movimentada"] for l in lojas),
        "prevencao_vendidas": sum(l["prevencao_vendidas"] for l in lojas),
        "prevencao_baixadas": sum(l["prevencao_baixadas"] for l in lojas),
        "prevencao_valor_vendido": sum(l["prevencao_valor_vendido"] for l in lojas),
        "prevencao_valor_baixado": sum(l["prevencao_valor_baixado"] for l in lojas),
        "vencido_valor": sum(l["vencido_valor"] for l in lojas),
        "d30_valor": sum(l["d30_valor"] for l in lojas),
        "d60_valor": sum(l["d60_valor"] for l in lojas),
        "d90_valor": sum(l["d90_valor"] for l in lojas),
        "saldo_prevencao_qtd": sum(l["saldo_prevencao_qtd"] for l in lojas),
        "sem_venda_lotes": sum(l["sem_venda_lotes"] for l in lojas),
        "sem_venda_qtd": sum(l["sem_venda_qtd"] for l in lojas),
        "sem_venda_valor": sum(l["sem_venda_valor"] for l in lojas),
        "sem_lote_itens": sum(l["sem_lote_itens"] for l in lojas),
        "sem_lote_qtd": sum(l["sem_lote_qtd"] for l in lojas),
        "sem_lote_valor": sum(l["sem_lote_valor"] for l in lojas),
        "lojas_criticas": sum(1 for l in lojas if l["risco_nivel"] == "Crítico"),
        "lojas_intervencao": sum(1 for l in lojas if l["intervencao_imediata"]),
    }
    kpis["conversao_pct"] = round(
        (kpis["prevencao_vendidas"] / kpis["prevencao_movimentada"]) * 100, 1
    ) if kpis["prevencao_movimentada"] > 0 else 0.0
    kpis["perda_pct"] = round(
        (kpis["prevencao_baixadas"] /
         (kpis["prevencao_vendidas"] + kpis["prevencao_baixadas"])) * 100, 1
    ) if (kpis["prevencao_vendidas"] + kpis["prevencao_baixadas"]) > 0 else 0.0

    return {
        "periodo": {
            "data_inicio": inicio.isoformat(),
            "data_fim": fim.isoformat(),
            "dias_sem_venda": dias_sem_venda,
        },
        "categorias": [
            {"chave": chave, "nome": CATEGORIAS_LABELS[chave]}
            for chave in CATEGORIAS_VALIDAS
        ],
        "categorias_selecionadas": list(categorias),
        "kpis": kpis,
        "lojas": lojas,
        "vencimentos_mensal": vencimentos_mensal,
        "top_vencendo": top_vencendo,
        "top_sem_venda": top_sem_venda,
        "top_sem_lote": top_sem_lote,
        "ultima_atualizacao": time.time(),
        "observacoes": [
            "Universo restrito aos lotes ativos de itemprevencido (status A) das categorias selecionadas.",
            "Estoque em prevenção considerando apenas lotes com saldo positivo e estoque atual igual ou maior que o saldo.",
            "Valor = saldo em prevenção × custo atual do cadastro do produto/loja (custoproduto).",
            "Vendas de pré-vencidos usam o valor efetivamente vendido (itemvenda.valortotal).",
            "Transferências consideram apenas operações recebidas (status R) de itens em prevenção.",
            "Informações de já vencido consideram somente validades a partir de janeiro de 2026.",
            "Lojas excluídas: 14-2, 20, 26, 40, 41, BKP, CLOUD e ESC.",
            "Vendas sem lote são uma sinalização: mesmo produto/loja com lote ativo na data, mas venda sem itemprevencidoid.",
            "Registros com quantidade acima de 100.000 ou validade após 2100 são desconsiderados.",
        ],
    }


app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def read_root():
    return FileResponse("static/index.html")
