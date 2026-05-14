import os
from contextlib import closing
from dotenv import load_dotenv, find_dotenv
import sqlite3
import pandas as pd
from fastapi import FastAPI, HTTPException, Security
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

load_dotenv(find_dotenv())

app = FastAPI(
    title="API do DSO (Simulação)",
    description="Endpoints para telemetria de alimentadores e barras da rede de distribuição.",
    version="1.0.0"
)

_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DSO = os.path.join(_DIR, "dso_database.db")

_API_KEY = os.environ.get("VPP_API_KEY", "dev-key-change-in-production")
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)


def _verify_key(key: str = Security(_api_key_header)) -> str:
    if key != _API_KEY:
        raise HTTPException(status_code=403, detail="API Key inválida.")
    return key

# ==========================================
# MODELOS DE REQUISIÇÃO (PAYLOAD)
# ==========================================


class FiltroTelemetria(BaseModel):
    alimentador: str
    timestamp: str  # Formato esperado: "YYYY-MM-DD HH:MM:SS"

# ==========================================
# ENDPOINT 1: DADOS DO ALIMENTADOR (Visão Global)
# ==========================================


@app.post("/dados_alimentador")
def obter_dados_alimentador(filtro: FiltroTelemetria, _: str = Security(_verify_key)):
    query = """
        SELECT * FROM telemetria_alimentador
        WHERE alimentador_id = ? AND timestamp = ?
    """
    with closing(sqlite3.connect(DB_DSO)) as conn:
        conn.row_factory = sqlite3.Row
        df = pd.read_sql_query(query, conn, params=(
            filtro.alimentador, filtro.timestamp))

    if df.empty:
        raise HTTPException(
            status_code=404, detail="Dados não encontrados para este alimentador neste horário.")

    return df.iloc[0].to_dict()

# ==========================================
# ENDPOINT 2: DADOS POR BARRA (Visão Granular)
# ==========================================


@app.post("/dados_barra")
def obter_dados_barra(filtro: FiltroTelemetria, _: str = Security(_verify_key)):
    query = """
        SELECT id_barra, p_kw, q_kvar
        FROM telemetria_barras
        WHERE timestamp = ?
    """
    with closing(sqlite3.connect(DB_DSO)) as conn:
        conn.row_factory = sqlite3.Row
        df = pd.read_sql_query(query, conn, params=(filtro.timestamp,))

    if df.empty:
        raise HTTPException(
            status_code=404, detail="Nenhuma telemetria de barra encontrada para este horário.")

    return df.to_dict(orient="records")

# Rota raiz de teste


@app.get("/")
def read_root():
    return {"status": "API do DSO Online. Aguardando requisições da VPP..."}
