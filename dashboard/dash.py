import os
from contextlib import closing
from dotenv import load_dotenv
import streamlit as st
import geopandas as gpd
import pydeck as pdk
import pandas as pd
import numpy as np
import sqlite3
import requests
import warnings

_DIR = os.path.dirname(os.path.abspath(__file__))
_ENV_PATH = os.path.abspath(os.path.join(_DIR, "..", ".env"))
load_dotenv(_ENV_PATH, override=True)

# Ocultar alertas para manter o terminal limpo
warnings.filterwarnings('ignore')

# ==========================================
# 1. CONFIGURAÇÕES INICIAIS
# ==========================================
st.set_page_config(page_title="VPP Control Center", layout="wide")
st.title("⚡ Virtual Power Plant - Operação DSO")

MAPBOX_API_KEY = os.environ.get("MAPBOX_API_KEY", "")
VPP_API_KEY = os.environ.get("VPP_API_KEY", "")
URL_API_DSO = "http://localhost:8000"


GEOJSON_PATH = os.path.join(_DIR, "..", "alimentador.geojson")
DB_VPP = os.path.join(_DIR, "vpp_database.db")

# ==========================================
# 2. CONTROLE DE TEMPO E NAVEGAÇÃO
# ==========================================
st.sidebar.header("🕹️ Navegação")
menu = st.sidebar.radio(
    "Selecione a Visualização:",
    ("📊 Dashboard", "📡 Telemetria", "☁️ Previsões", "💰 Financeiro")
)

st.sidebar.markdown("---")
st.sidebar.header("⏱️ Relógio de Simulação")

# Gerar a lista de horários de 5 em 5 min
tempos_simulacao = pd.date_range(start="2024-05-15 00:00", end="2024-05-15 23:55", freq="5min")
tempos_str = tempos_simulacao.strftime('%Y-%m-%d %H:%M:%S').tolist()

# Slider que controla todo o Dashboard
timestamp_atual = st.sidebar.select_slider(
    "Horário da Operação:",
    options=tempos_str,
    value=tempos_str[12 * 14] # Começa às 14:00 por padrão
)

# ==========================================
# 3. FUNÇÕES DE CARREGAMENTO
# ==========================================
@st.cache_data
def carregar_geojson():
    gdf = gpd.read_file(GEOJSON_PATH)
    gdf['id_trecho'] = gdf.index.astype(str)
    
    # Lógica geográfica para garantir pintura uniforme (Zonas)
    gdf['centro_x'] = gdf.geometry.centroid.x
    gdf['centro_y'] = gdf.geometry.centroid.y
    ref_x = gdf['centro_x'].min()
    ref_y = gdf['centro_y'].max()
    gdf['distancia_ref'] = np.sqrt((gdf['centro_x'] - ref_x)**2 + (gdf['centro_y'] - ref_y)**2)
    
    # Gerar os 3 ativos solares fixos para não pularem ao mudar o tempo
    np.random.seed(42)
    solar_indices = np.random.choice(gdf.index, 3, replace=False)
    solar_sites = gdf.loc[solar_indices].copy()
    solar_sites['lon'] = solar_sites.geometry.centroid.x
    solar_sites['lat'] = solar_sites.geometry.centroid.y
    icon_data = {"url": "https://img.icons8.com/color/100/solar-panel.png", "width": 128, "height": 128, "anchorY": 128}
    solar_sites['icon_data'] = [icon_data for _ in range(len(solar_sites))]
    
    return gdf, solar_sites

def buscar_dados_mapa_vpp(timestamp):
    with closing(sqlite3.connect(DB_VPP)) as conn:
        df = pd.read_sql_query("SELECT * FROM mapa_vpp WHERE timestamp = ?", conn, params=(timestamp,))
    return df

def buscar_previsao_vpp(timestamp):
    with closing(sqlite3.connect(DB_VPP)) as conn:
        df = pd.read_sql_query("SELECT * FROM previsao_tempo WHERE timestamp = ?", conn, params=(timestamp,))
    return df.iloc[0] if not df.empty else None

# ==========================================
# 4. TELAS DO DASHBOARD
# ==========================================

if menu == "📊 Dashboard":
    st.header("📍 Monitorização e Fluxo de Potência")
    st.caption(f"Última atualização de campo: {timestamp_atual}")
    
    # Alternador de Visão
    tipo_mapa = st.radio("Visualizar Variável:", ["Sobrecarga (%)", "Tensão (pu)"], horizontal=True)
    
    gdf_base, solar_sites = carregar_geojson()
    df_dados = buscar_dados_mapa_vpp(timestamp_atual)
    
    # Mesclar GeoJSON com os dados do SQLite
    gdf_rede = gdf_base.merge(df_dados, on='id_trecho', how='left')
    
    # Aplicar Fator Geográfico para garantir a continuidade visual (Tronco -> Ponta)
    max_dist = gdf_rede['distancia_ref'].max()
    gdf_rede['fator_geo'] = 0.5 + (gdf_rede['distancia_ref'] / max_dist) 
    
    colors = []
    textos_tooltip = []
    
    for _, row in gdf_rede.iterrows():
        if tipo_mapa == "Sobrecarga (%)":
            # Força o tronco a ter carga menor e a ponta a ter carga maior
            val_ajustado = row['sobrecarga_perc'] * row['fator_geo']
            
            if val_ajustado < 50: colors.append([0, 255, 0, 200])       # Verde
            elif val_ajustado < 90: colors.append([255, 255, 0, 200])   # Amarelo
            else: colors.append([255, 0, 0, 255])                       # Vermelho
            textos_tooltip.append(f"{val_ajustado:.2f} %")
            
        else: # Tensão (pu)
            # Tensão cai ao longo da distância
            val_ajustado = row['tensao_pu'] - (row['fator_geo'] * 0.05) + 0.02
            
            if val_ajustado > 0.95: colors.append([0, 255, 0, 200])     # Verde (Bom)
            elif val_ajustado > 0.92: colors.append([255, 255, 0, 200]) # Amarelo (Atenção)
            else: colors.append([255, 0, 0, 255])                       # Vermelho (Subtensão)
            textos_tooltip.append(f"{val_ajustado:.4f} pu")

    gdf_rede['color'] = colors
    gdf_rede['valor_formatado'] = textos_tooltip

    # Renderização do PyDeck
    centro_lon = gdf_rede.geometry.centroid.x.mean()
    centro_lat = gdf_rede.geometry.centroid.y.mean()

    camada_rede = pdk.Layer(
        "GeoJsonLayer", data=gdf_rede, opacity=0.9, stroked=True,
        get_line_color="color", get_line_width=4, line_width_min_pixels=3, pickable=True
    )
    camada_ativos = pdk.Layer(
        "IconLayer", data=solar_sites, get_icon="icon_data", get_size=4, size_scale=12,
        get_position=["lon", "lat"], pickable=True
    )

    st.pydeck_chart(pdk.Deck(
        map_style="mapbox://styles/mapbox/dark-v11", 
        initial_view_state=pdk.ViewState(latitude=centro_lat, longitude=centro_lon, zoom=15, pitch=40),
        layers=[camada_rede, camada_ativos],
        api_keys={"mapbox": MAPBOX_API_KEY},
        tooltip={"html": "<b>ID:</b> {id_trecho} <br> <b>Valor:</b> {valor_formatado}", "style": {"color": "white", "backgroundColor": "black"}}
    ))

    # Legenda Dinâmica Lateral
    st.sidebar.markdown("---")
    st.sidebar.subheader("📌 Status dos Trechos")
    
    if tipo_mapa == "Sobrecarga (%)":
        st.sidebar.markdown("🟢 **< 50%**: Operação Normal")
        st.sidebar.markdown("🟡 **50% - 90%**: Carga Elevada")
        st.sidebar.markdown("🔴 **> 90%**: Sobrecarga")
    else:
        st.sidebar.markdown("🟢 **> 0.95 pu**: Tensão Estável")
        st.sidebar.markdown("🟡 **0.92 - 0.95 pu**: Queda de Tensão")
        st.sidebar.markdown("🔴 **< 0.92 pu**: Subtensão (Crítico)")
    
    st.sidebar.write("") 
    col_icon, col_text = st.sidebar.columns([1, 5])
    with col_icon: st.image("https://img.icons8.com/color/100/solar-panel.png", width=30)
    with col_text: st.markdown("**Ativos Solares**: Usinas Fotovoltaicas da VPP")

elif menu == "📡 Telemetria":
    st.header("📡 Módulo de Telemetria (API do DSO)")
    st.caption(f"Sincronizado via SAGE. Timestamp: {timestamp_atual}")
    
    payload = {"alimentador": "REG09V2", "timestamp": timestamp_atual}
    headers = {"X-API-Key": VPP_API_KEY}

    try:
        # Chamada 1: Alimentador Global
        res_alim = requests.post(f"{URL_API_DSO}/dados_alimentador", json=payload, headers=headers)
        
        if res_alim.status_code == 200:
            dados_alim = res_alim.json()
            st.subheader("Visão Global - Alimentador REG09V2")
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Potência Ativa", f"{dados_alim['p_total_kw']} kW")
            c2.metric("Potência Reativa", f"{dados_alim['q_total_kvar']} kVAr")
            c3.metric("Perdas Ativas", f"{dados_alim['perdas_p_kw']} kW")
            c4.metric("Perdas Reativas", f"{dados_alim['perdas_q_kvar']} kVAr")
            c5.metric("Desvio Tensão", f"{dados_alim['desvio_tensao_pu']} pu")
        else:
            st.error("Erro ao buscar dados do alimentador na API.")

        st.markdown("---")
        
        # Chamada 2: Barras Específicas
        res_barras = requests.post(f"{URL_API_DSO}/dados_barra", json=payload, headers=headers)
        if res_barras.status_code == 200:
            lista_barras = res_barras.json()
            df_barras = pd.DataFrame(lista_barras)
            
            st.subheader("Visão Granular - Telemetria por Barra")
            barra_selecionada = st.selectbox("Selecione a Barra/Trecho:", df_barras['id_barra'].unique())
            
            dados_barra = df_barras[df_barras['id_barra'] == barra_selecionada].iloc[0]
            cb1, cb2 = st.columns(2)
            cb1.metric(f"Potência Ativa (Barra {barra_selecionada})", f"{dados_barra['p_kw']} kW")
            cb2.metric(f"Potência Reativa (Barra {barra_selecionada})", f"{dados_barra['q_kvar']} kVAr")
            
    except requests.exceptions.ConnectionError:
        st.error("🚨 API do DSO offline. Verifique se o Uvicorn (FastAPI) está rodando no terminal.")

elif menu == "☁️ Previsões":
    st.header("☁️ Recursos Renováveis e Meteorologia")
    st.caption(f"Dados atualizados para a janela: {timestamp_atual}")
    
    prev = buscar_previsao_vpp(timestamp_atual)
    
    if prev is not None:
        cp1, cp2, cp3 = st.columns(3)
        cp1.metric("☀️ Irradiância Global (GHI)", f"{prev['ghi_w_m2']} W/m²")
        cp2.metric("🌡️ Temperatura", f"{prev['temperatura_c']} °C")
        cp3.metric("🌬️ Velocidade do Vento", f"{prev['vento_m_s']} m/s")
        
        st.info("Nota: A VPP utiliza estes dados para calcular o potencial de injeção das usinas solares fotovoltaicas distribuídas no trecho Rio das Éguas (Oeste Baiano).")
    else:
        st.warning("Sem dados de previsão para este horário.")

elif menu == "💰 Financeiro":
    st.header("💰 Gestão de Fluxo de Caixa e ROI")
    st.caption("Visão Consolidada de Operação da VPP")
    
    # Dados Estáticos Simulados para demonstrar viabilidade
    st.subheader("Benefícios Econômicos Estimados (Ciclo Atual)")
    
    cf1, cf2, cf3 = st.columns(3)
    cf1.metric("📉 Redução de COMPCONT", "R$ 45.200,00", "+12% vs mês anterior")
    cf2.metric("⚡ Multas TRP Evitadas", "R$ 18.500,00", "+5% vs mês anterior")
    cf3.metric("💸 Receita Arbitragem", "R$ 8.900,00", "-2% vs mês anterior")
    
    st.markdown("---")
    st.write("""
    **Justificativa de Despacho:**
    A atuação integrada dos inversores fotovoltaicos e sistemas de armazenamento (BESS) reduziu 
    significativamente as transgressões de tensão em regime permanente (TRP) nas pontas do alimentador REG09V2, 
    refletindo diretamente na mitigação dos pagamentos por má qualidade (PG) mapeados pela ANEEL.
    """)