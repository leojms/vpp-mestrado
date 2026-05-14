# VPP Control Center

Plataforma de **Virtual Power Plant (VPP)** para monitoramento, controle e otimização de Recursos Energéticos Distribuídos (DERs) em redes de distribuição radiais. Aplicado ao alimentador **REG09V2** da Coelba, no Oeste Baiano.

---

## O Problema

O Oeste Baiano é uma região de forte produção agrícola (soja, algodão) com alta dependência energética para irrigação. O alimentador REG09V2 opera próximo à capacidade máxima com linhas longas, gerando problemas críticos tanto para consumidores quanto para a distribuidora:

| Perspectiva | Problema |
|---|---|
| **Consumidor** | Subtensões causam perda de safra, parada de bombas e queima de equipamentos |
| **Distribuidora** | DEC/FEC violados geram **COMPCONT** (compensações compulsórias à ANEEL) |
| **Regulatório** | Tensões fora de 0,92–1,05 pu (PRODIST Módulo 8) geram **TRP/PG** (Pagamentos por Má Qualidade) |
| **Infraestrutura** | Reforços de rede em zonas rurais têm CAPEX elevado |

---

## A Solução

O VPP Control Center agrega e despacha DERs — **usinas fotovoltaicas** e **sistemas de armazenamento (BESS)** — de forma otimizada para:

- Corrigir o perfil de tensão nas pontas de linha
- Aliviar sobrecargas térmicas em trechos críticos
- Minimizar multas regulatórias (COMPCONT + TRP/PG)
- Postergar investimentos pesados em infraestrutura

### Três Componentes Principais

| Componente | Tecnologia | Função |
|---|---|---|
| **API do DSO** | FastAPI | Interface com a distribuidora — expõe telemetria de alimentadores e barras |
| **Motor da VPP** | OpenDSS + ML + MILP | Fluxo de potência, previsão solar/carga e otimização de despacho |
| **Dashboard SCADA** | Streamlit + PyDeck | Mapa geoespacial, telemetria em tempo real, indicadores financeiros e regulatórios |

---

## Arquitetura

### Stack Atual (MVP)

```
Python 3.11 | FastAPI | SQLite | GeoPandas | Pandas | Streamlit | PyDeck (Mapbox)
```

### Stack Planejada (Motor de IA)

```
OpenDSS (opendssdirect.py) | PuLP / OR-Tools (MILP) | scikit-learn / Prophet (ML)
```

### Pipeline de Dados

```
[BDGD / GeoJSON]  →  [OpenDSS]  →  [Motor IA (ML + MILP)]  →  [API FastAPI]  →  [Dashboard Streamlit]
        ↑________________________________ Loop de Retroalimentação ________________________________↑
```

### Separação de Bancos

| Banco | Acesso | Tabelas |
|---|---|---|
| `dso_database.db` | Apenas via API (nunca direto) | `telemetria_alimentador`, `telemetria_barras` |
| `vpp_database.db` | Direto pela VPP | `mapa_vpp`, `previsao_tempo` |

---

## Estrutura do Projeto

```
vpp-mestrado/
├── alimentador.geojson          # GeoJSON do alimentador REG09V2
├── gerar_bancos.py              # Script de geração de dados sintéticos
├── requirements.txt
├── .env.example                 # Template de variáveis de ambiente
│
├── api/
│   └── api.py                   # FastAPI — endpoints de telemetria do DSO
│
├── dashboard/
│   └── dash.py                  # Streamlit — Dashboard SCADA
│
└── dec-fec/
    ├── dec_fec.py               # Processador de indicadores ANEEL (DEC/FEC/TRP/PG)
    ├── dominio-indicadores.csv  # Dicionário de indicadores ANEEL
    └── Alvos_VPP_Coelba.csv     # Top 10 alimentadores alvo por custo regulatório
```

> Os bancos `.db` não são versionados — gere-os localmente com `python gerar_bancos.py`.

---

## Como Rodar

### 1. Pré-requisitos

```bash
pip install -r requirements.txt
```

### 2. Variáveis de Ambiente

Copie `.env.example` para `.env` e preencha:

```bash
cp .env.example .env
```

```env
MAPBOX_API_KEY=sua-chave-mapbox-aqui
VPP_API_KEY=chave-secreta-da-api-vpp
```

### 3. Gerar os Bancos de Dados

```bash
python gerar_bancos.py
```

### 4. Subir os Serviços

```bash
# Terminal 1 — API do DSO
python -m uvicorn api.api:app --reload --port 8000

# Terminal 2 — Dashboard
python -m streamlit run dashboard/dash.py
```

### 5. Acessar

| Serviço | URL |
|---|---|
| Dashboard | http://localhost:8501 |
| API (Swagger) | http://localhost:8000/docs |

> Para testar os endpoints no Swagger, clique em **Authorize** e informe o valor de `VPP_API_KEY` do seu `.env`.

---

## Fluxo de Dados Alvo (Pós-MVP)

```
BDGD (Coelba)
    │
    ▼
GeoJSON + Parâmetros de Rede (R, X por trecho)
    │
    ▼
OpenDSS ◄──────────────────────────────────────────┐
    │  Fluxo de Potência                            │
    ▼                                               │
Resultados: V[barra], I[trecho], Perdas P/Q         │
    │                                               │
    ├──► API DSO (FastAPI)                          │
    │       └──► Dashboard SCADA (Streamlit)        │
    │                                               │
    └──► Motor da VPP                               │
            ├── ML: Previsão Solar (GHI × η)        │
            ├── ML: Previsão de Carga (Prophet)     │
            ├── MILP: Otimizador de Despacho        │
            │         (PuLP / OR-Tools)             │
            └── Setpoints Ótimos (BESS + Inversores)
                    │
                    └───────────────────────────────┘
                          (realimenta o OpenDSS)
```

### Formulação do Otimizador MILP

```
Minimizar:  perdas_técnicas(kW) + custo_TRP + custo_COMPCONT

Sujeito a:
  tensao[barra]    ∈ [0.92, 1.05] pu    # PRODIST Módulo 8
  corrente[trecho] ≤ capacidade_térmica
  soc_bess[t]      ∈ [0.20, 0.90]       # Limites de SoC
  p_solar[t]       ≤ p_solar_previsto[t]
```

---

## Roadmap

### Fase 1 — Base Sólida
- [x] Dashboard geoespacial com telemetria simulada
- [x] API FastAPI com autenticação por API Key
- [x] Processador de indicadores ANEEL (DEC/FEC/TRP/PG)
- [ ] Integrar dados reais de carga via BDGD
- [ ] Substituir fator heurístico por modelo físico `ΔV = (P·R + Q·X) / V`
- [ ] Conectar OpenDSS como solver de fluxo de potência real

### Fase 2 — Inteligência da VPP
- [ ] Previsão de geração solar: `P_solar = GHI × Área × η_painel`
- [ ] Previsão de carga: SARIMA / Prophet (dados ONS/INMET Nordeste)
- [ ] Otimizador MILP com PuLP ou OR-Tools
- [ ] Módulo financeiro derivado computacionalmente (COMPCONT + TRP/PG reais)

### Fase 3 — Validação
- [ ] Simulação completa de 24h no REG09V2
- [ ] KPIs comparativos: cenário com VPP vs. sem VPP
- [ ] Cálculo de ROI por redução de multas regulatórias

---

## Glossário

| Termo | Significado |
|---|---|
| **VPP** | Virtual Power Plant — agregador virtual de DERs |
| **DSO** | Distribution System Operator — operadora da rede (Coelba) |
| **DER** | Distributed Energy Resource — geração solar, BESS, etc. |
| **BESS** | Battery Energy Storage System — armazenamento por baterias |
| **REG09V2** | Código do alimentador Coelba no Oeste Baiano |
| **BDGD** | Base de Dados Geográfica da Distribuidora (fonte ANEEL) |
| **DEC / FEC** | Duração / Frequência Equivalente de Interrupção por consumidor |
| **COMPCONT** | Compensação financeira compulsória por violação de DEC/FEC |
| **TRP** | Transgressão de Tensão em Regime Permanente |
| **PG** | Pagamento por Má Qualidade (decorrente de TRP) |
| **PRODIST Módulo 8** | Regulamento ANEEL: tensão adequada 0,93–1,05 pu, precária 0,90–0,92 pu |
| **SCADA** | Supervisory Control and Data Acquisition |
| **GHI** | Global Horizontal Irradiance — irradiância solar (W/m²) |
| **MILP** | Mixed Integer Linear Programming |
| **SoC** | State of Charge — estado de carga da bateria (%) |
| **pu** | Per Unit — sistema por unidade usado em engenharia elétrica |
