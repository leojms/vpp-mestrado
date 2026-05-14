# Contexto do Projeto — VPP Control Center
> Arquivo gerado para onboarding no Claude Code. Contém todo o contexto da pesquisa de mestrado, arquitetura atual, código existente e roadmap de evolução.

---

## 1. Visão Geral da Pesquisa

**Instituição:** SENAI CIMATEC  
**Programa:** Mestrado em Engenharia (IA / Otimização de Redes)  
**Tema:** Plataforma de Virtual Power Plant (VPP) para melhoria de resiliência energética e indicadores de qualidade em redes de distribuição radiais.  
**Case de Aplicação:** Alimentador REG09V2 — Coelba — Oeste Baiano (região de Correntina / BA)

---

## 2. O Problema

### 2.1 Impacto Socioeconômico
- **Agronegócio em risco:** O Oeste Baiano é uma região de forte produção agrícola (soja, algodão), extremamente dependente de energia para irrigação. Quedas e subtensões causam **perdas de safra**, parada de bombas e queima de equipamentos.
- **Infraestrutura no limite:** Linhas de distribuição longas, operando próximas à capacidade máxima, com dificuldade de expansão (CAPEX elevado para reforços).
- **Desincentivo ao desenvolvimento local:** Confiabilidade precária inibe a instalação de novos empreendimentos.

### 2.2 Problemas do Setor Elétrico (visão da Distribuidora)
- **DEC / FEC violados:** Indicadores de continuidade acima das metas da ANEEL geram compensações compulsórias (**COMPCONT**).
- **Transgressão de Tensão em Regime Permanente (TRP):** Tensões fora dos limites do PRODIST Módulo 8 (0,92 a 1,05 pu) geram **Pagamentos por Má Qualidade (PG)**.
- **Operação às cegas:** Ausência de visibilidade e controle dos Recursos Energéticos Distribuídos (REDs) conectados à rede.
- **CAPEX pesado:** Reforços de infraestrutura em alimentadores longos do interior são muito caros.

---

## 3. A Solução: VPP Control Center

Plataforma que agrega e despacha DERs (Distributed Energy Resources) de forma otimizada — especificamente **Usinas Fotovoltaicas** e **Sistemas de Armazenamento (BESS)** — para:

1. Corrigir o perfil de tensão nas pontas de linha.
2. Aliviar sobrecargas térmicas nos trechos críticos.
3. Minimizar multas regulatórias (COMPCONT + TRP/PG).
4. Postergar investimentos pesados em infraestrutura.

### 3.1 Três Componentes Principais

| Componente | Descrição |
|---|---|
| **API do DSO** | Interface com a distribuidora (Coelba). Expõe telemetria de rede via FastAPI. Dados de carga estimados via BDGD. |
| **Motor da VPP** | Cérebro do sistema: OpenDSS (fluxo de potência) + ML (previsão solar/carga) + MILP (otimização de despacho). |
| **Dashboard SCADA** | Interface do operador: mapa geoespacial, telemetria em tempo real, indicadores financeiros e regulatórios. |

---

## 4. Arquitetura Tecnológica

### 4.1 Stack Atual (MVP / V1)

```
Python 3.11 | FastAPI | SQLite | GeoPandas | Pandas | Streamlit | PyDeck (Mapbox)
```

### 4.2 Stack Planejada (motor de IA)

```
OpenDSS (py-dss-interface ou opendssdirect.py) | PuLP ou OR-Tools (MILP) | scikit-learn / Prophet (ML)
```

### 4.3 Camadas do Sistema

```
[BDGD / GeoJSON]  →  [OpenDSS]  →  [Motor IA (ML + MILP)]  →  [API FastAPI]  →  [Dashboard Streamlit]
        ↑___________________________ Loop de Retroalimentação ___________________________↑
```

### 4.4 Separação de Bancos de Dados

- **`dso_database.db`** — Banco da distribuidora (Coelba). Contém `telemetria_alimentador` e `telemetria_barras`. A VPP **não acessa diretamente** — apenas via API.
- **`vpp_database.db`** — Banco da VPP. Contém `mapa_vpp` (dados para renderização geoespacial) e `previsao_tempo` (GHI, temperatura, vento).

---

## 5. Código Existente (MVP com dados dummy)

### 5.1 API do DSO — `api_dso.py` (FastAPI)

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import sqlite3
import pandas as pd

app = FastAPI(
    title="API do DSO (Simulação)",
    description="Endpoints para telemetria de alimentadores e barras da rede de distribuição.",
    version="1.0.0"
)

class FiltroTelemetria(BaseModel):
    alimentador: str
    timestamp: str  # Formato: "YYYY-MM-DD HH:MM:SS"

def get_db_connection():
    conn = sqlite3.connect('dso_database.db', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

@app.post("/dados_alimentador")
def obter_dados_alimentador(filtro: FiltroTelemetria):
    conn = get_db_connection()
    query = """
        SELECT * FROM telemetria_alimentador 
        WHERE alimentador_id = ? AND timestamp = ?
    """
    df = pd.read_sql_query(query, conn, params=(filtro.alimentador, filtro.timestamp))
    conn.close()
    if df.empty:
        raise HTTPException(status_code=404, detail="Dados não encontrados.")
    return df.iloc[0].to_dict()

@app.post("/dados_barra")
def obter_dados_barra(filtro: FiltroTelemetria):
    conn = get_db_connection()
    query = """
        SELECT id_barra, p_kw, q_kvar 
        FROM telemetria_barras 
        WHERE timestamp = ?
    """
    df = pd.read_sql_query(query, conn, params=(filtro.timestamp,))
    conn.close()
    if df.empty:
        raise HTTPException(status_code=404, detail="Nenhuma telemetria encontrada.")
    return df.to_dict(orient="records")

@app.get("/")
def read_root():
    return {"status": "API do DSO Online."}
```

### 5.2 Dashboard — `dashboard.py` (Streamlit + PyDeck)

Arquivo completo com ~200 linhas. Estrutura principal:

```python
import streamlit as st
import geopandas as gpd
import pydeck as pdk
import pandas as pd
import numpy as np
import sqlite3
import requests

# Configurações
MAPBOX_API_KEY = "..."  # Mover para variável de ambiente
URL_API_DSO = "http://localhost:8000"

# Navegação lateral: Dashboard | Telemetria | Previsões | Financeiro
# Slider temporal: 288 janelas de 5 min (2024-05-15 00:00 a 23:55)

# Módulos:
# - Dashboard: Mapa PyDeck geoespacial com Sobrecarga(%) e Tensão(pu) por trecho
# - Telemetria: Consume API DSO via requests.post()
# - Previsões: GHI, Temperatura, Vento do banco VPP
# - Financeiro: Cards estáticos (a ser derivado computacionalmente)
```

**Problemas conhecidos no código atual (a corrigir):**
1. **SQL Injection** no dashboard — usa f-string na query. Corrigir para `params=(timestamp,)`.
2. **Conexões SQLite sem `with`** — risco de leak se a query falhar. Usar context manager.
3. **`check_same_thread=False` sem connection pool** na API — aceitável para MVP, registrar como limitação.
4. **Chave Mapbox exposta no código** — mover para `os.environ.get("MAPBOX_API_KEY")`.
5. **Fator geográfico heurístico** — substituir por modelo físico de queda de tensão por impedância.
6. **Módulo financeiro estático** — valores fixos (R$ 45.200,00) a serem derivados computacionalmente.

### 5.3 Script de Geração de Dados — `gerar_bancos.py`

Gera os dois bancos SQLite com dados sintéticos (dummy):
- Lê `alimentador.geojson` com GeoPandas.
- Calcula fator geográfico (distância de cada trecho à subestação).
- Gera 288 janelas de 5 minutos simulando carga, tensão, sobrecarga e meteorologia.
- Popula `dso_database.db` e `vpp_database.db`.

---

## 6. Roadmap Tecnológico

### Fase 1 — Curto Prazo (Base Sólida)
- [ ] Integrar dados reais de carga via **BDGD** (Base de Dados Geográfica da Distribuidora — Coelba)
- [ ] Substituir fator geográfico heurístico por modelo de queda de tensão: `ΔV = (P·R + Q·X) / V`
- [ ] Conectar **OpenDSS** ao backend como solver de fluxo de potência real (`opendssdirect.py` ou `py-dss-interface`)
- [ ] Corrigir SQL injection e gerenciamento de conexões SQLite
- [ ] Mover chave Mapbox para variável de ambiente (`.env`)

### Fase 2 — Médio Prazo (Inteligência da VPP)
- [ ] **Previsão de geração solar:** modelo físico `P_solar = GHI × Área × η_painel` alimentado pelas variáveis meteorológicas já simuladas
- [ ] **Previsão de carga:** SARIMA ou Prophet, treinado com dados históricos do ONS/INMET para o Nordeste
- [ ] **Otimizador MILP** com PuLP ou OR-Tools:
  ```
  Minimizar: perdas_técnicas(kW) + custo_multa_TRP + custo_COMPCONT
  Sujeito a:
    tensao[barra]    ∈ [0.92, 1.05] pu    # PRODIST Módulo 8
    corrente[trecho] ≤ capacidade_térmica
    soc_bess[t]      ∈ [0.20, 0.90]       # Limites de SoC da bateria
    p_solar[t]       ≤ p_solar_previsto[t]
  ```
- [ ] Derivar indicadores financeiros (COMPCONT, TRP/PG) computacionalmente a partir dos dados de simulação
- [ ] Validar resultados contra dados históricos reais do ONS/INMET

### Fase 3 — Longo Prazo (Contribuição Científica)
- [ ] Fechar o loop completo: despacho ótimo → redução de TRP medida → cálculo de ROI
- [ ] Simulação de 24h com KPIs comparativos (cenário com VPP vs. sem VPP)
- [ ] Documentação e validação da metodologia para defesa de dissertação
- [ ] Publicação de artigo científico com os resultados

---

## 7. Fluxo de Dados (Visão Alvo — Pós-MVP)

```
BDGD (Coelba)
    │
    ▼
GeoJSON + Parâmetros de Rede (R, X por trecho)
    │
    ▼
OpenDSS ◄─────────────────────────────────────────┐
    │  Fluxo de Potência                           │
    ▼                                              │
Resultados: V[barra], I[trecho], Perdas P/Q        │
    │                                              │
    ├──► API DSO (FastAPI)                         │
    │       └──► Dashboard SCADA (Streamlit)       │
    │                                              │
    └──► Motor da VPP                              │
            ├── ML: Previsão Solar (GHI × η)       │
            ├── ML: Previsão de Carga (Prophet)    │
            ├── MILP: Otimizador de Despacho       │
            │         (PuLP / OR-Tools)            │
            └── Setpoints Ótimos (BESS + Inversores)
                    │
                    └──────────────────────────────┘
                         (realimenta o OpenDSS)
```

---

## 8. Terminologia do Domínio

| Termo | Significado |
|---|---|
| **VPP** | Virtual Power Plant — agregador virtual de DERs |
| **DSO** | Distribution System Operator — operadora da rede de distribuição (Coelba) |
| **DER** | Distributed Energy Resource — geração solar, BESS, etc. |
| **BESS** | Battery Energy Storage System — sistema de armazenamento por baterias |
| **REG09V2** | Código do alimentador real da Coelba no Oeste Baiano |
| **BDGD** | Base de Dados Geográfica da Distribuidora — fonte oficial da ANEEL com parâmetros da rede |
| **DEC / FEC** | Duração / Frequência Equivalente de Interrupção por consumidor |
| **COMPCONT** | Compensação financeira compulsória por violação de DEC/FEC |
| **TRP** | Transgressão de Tensão em Regime Permanente |
| **PG** | Pagamento por Má Qualidade (decorrente de TRP) |
| **PRODIST Módulo 8** | Regulamento da ANEEL que define limites de tensão: adequada 0,93–1,05 pu, precária 0,90–0,92 pu |
| **SCADA** | Supervisory Control and Data Acquisition — sistema de supervisão e controle |
| **GHI** | Global Horizontal Irradiance — irradiância solar horizontal global (W/m²) |
| **MILP** | Mixed Integer Linear Programming — programação linear inteira mista |
| **SoC** | State of Charge — estado de carga da bateria (%) |
| **pu** | Per Unit — sistema por unidade usado em engenharia elétrica |

---

## 9. Arquivos do Projeto

```
vpp_project/
├── alimentador.geojson        # GeoJSON do alimentador REG09V2
├── gerar_bancos.py            # Script de geração de dados sintéticos
├── dso_database.db            # Banco do DSO (telemetria_alimentador, telemetria_barras)
├── vpp_database.db            # Banco da VPP (mapa_vpp, previsao_tempo)
├── api_dso.py                 # FastAPI — API do DSO (rodar com uvicorn)
├── dashboard.py               # Streamlit — Dashboard VPP
└── requirements.txt           # (a criar)
```

**Para rodar o MVP:**
```bash
# Terminal 1 — API do DSO
uvicorn api_dso:app --reload --port 8000

# Terminal 2 — Dashboard
streamlit run dashboard.py
```

---

## 10. Contexto para o Claude Code

Este projeto está na **transição do MVP (V1 com dados dummy) para o sistema real**. As principais tarefas de desenvolvimento são:

1. **Integrar OpenDSS** como backend de fluxo de potência, substituindo os dados gerados sinteticamente.
2. **Construir o motor de otimização** (MILP) que calcula setpoints ótimos para BESS e inversores fotovoltaicos.
3. **Desenvolver modelos de ML** para previsão de geração solar e carga.
4. **Conectar o pipeline completo:** BDGD → OpenDSS → Motor IA → API → Dashboard.
5. **Corrigir os bugs de segurança** listados na Seção 5.2.

O objetivo final da dissertação é **demonstrar quantitativamente** que o despacho otimizado pela VPP reduz transgressões de TRP e custos com COMPCONT no alimentador REG09V2, com simulação validada de 24 horas.
