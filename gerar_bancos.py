import sqlite3
import pandas as pd
import numpy as np
import geopandas as gpd
from datetime import datetime, timedelta
import warnings

warnings.filterwarnings('ignore')

print("Iniciando a Fábrica de Dados da VPP e DSO (Com Física Geográfica)...")

# ==========================================
# 0. LER IDs REAIS E CALCULAR GEOGRAFIA
# ==========================================
fator_geo_dict = {}

try:
    gdf = gpd.read_file('alimentador.geojson')
    trechos_ids = gdf.index.astype(str).tolist()
    print(f"-> Sucesso: {len(trechos_ids)} trechos encontrados no GeoJSON.")
    
    # NOVA LÓGICA: Calcular a distância da Subestação AQUI NO BACKEND
    gdf['centro_x'] = gdf.geometry.centroid.x
    gdf['centro_y'] = gdf.geometry.centroid.y
    ref_x = gdf['centro_x'].min() # Assumindo o extremo do mapa como subestação
    ref_y = gdf['centro_y'].max()
    
    gdf['distancia_ref'] = np.sqrt((gdf['centro_x'] - ref_x)**2 + (gdf['centro_y'] - ref_y)**2)
    max_dist = gdf['distancia_ref'].max() if gdf['distancia_ref'].max() > 0 else 1
    
    # Cria um fator que varia de ~0.5 (Início da rede) até 1.5 (Fim da rede)
    gdf['fator_geo'] = 0.5 + (gdf['distancia_ref'] / max_dist)
    
    # Transforma num dicionário fácil de buscar pelo ID do trecho
    fator_geo_dict = dict(zip(gdf.index.astype(str), gdf['fator_geo']))
    
except Exception as e:
    print(f"Aviso: 'alimentador.geojson' não encontrado. Usando IDs genéricos.")
    trechos_ids = [str(i) for i in range(50)]
    fator_geo_dict = {str(i): np.random.uniform(0.6, 1.4) for i in range(50)}

# ==========================================
# 1. GERAR A BASE DE TEMPO (288 pontos)
# ==========================================
data_simulacao = "2024-05-15"
tempos = pd.date_range(start=f"{data_simulacao} 00:00", end=f"{data_simulacao} 23:55", freq="5min")
horas_decimais = tempos.hour + tempos.minute / 60.0

# ==========================================
# 2. BANCO DA VPP (Previsão do Tempo e Mapa)
# ==========================================
print("\nGerando Banco de Dados da VPP (vpp_database.db)...")
conn_vpp = sqlite3.connect('vpp_database.db')

# --- 2A. Previsão do Tempo ---
ghi_base = np.where((horas_decimais > 6) & (horas_decimais < 18), 950 * np.sin(np.pi * (horas_decimais - 6) / 12), 0)
ghi_com_ruido = np.clip(ghi_base + np.random.normal(0, 15, len(ghi_base)), 0, 1200)
ghi_final = np.where((horas_decimais > 6) & (horas_decimais < 18), ghi_com_ruido, 0)
temperatura = 22 + 13 * np.sin(np.pi * (horas_decimais - 6) / 14) 
temperatura = np.clip(temperatura + np.random.normal(0, 0.5, len(temperatura)), 15, 45)
vento = 6 + 3 * np.cos(np.pi * horas_decimais / 12) + np.random.normal(0, 0.5, len(horas_decimais))

df_previsao = pd.DataFrame({
    'timestamp': tempos.strftime('%Y-%m-%d %H:%M:%S'),
    'ghi_w_m2': np.round(ghi_final, 2),
    'temperatura_c': np.round(temperatura, 2),
    'vento_m_s': np.round(vento, 2)
})
df_previsao.to_sql('previsao_tempo', conn_vpp, if_exists='replace', index=False)

# --- 2B. Dados do Mapa (Sobrecarga e Tensão) ---
curva_base_carga = 30 + 50 * np.exp(-0.5 * ((horas_decimais - 19)/2)**2) + 20 * np.exp(-0.5 * ((horas_decimais - 12)/3)**2)

n_trechos = len(trechos_ids)
p_nominal_base_por_trecho = 2000.0 / n_trechos if n_trechos > 0 else 1.0

mapa_dados = []
telemetria_barras = []

for trecho_id in trechos_ids:
    # O multiplicador agora é fortemente guiado pela geografia do trecho
    fator_base = fator_geo_dict.get(trecho_id, 1.0)
    # Adicionamos um ruído de apenas +- 8% para dar naturalidade
    multiplicador_trecho = fator_base * np.random.uniform(0.92, 1.08) 
    
    carga_trecho = curva_base_carga * multiplicador_trecho + np.random.normal(0, 1.5, len(tempos))
    carga_trecho = np.clip(carga_trecho, 10, 130)
    
    # Física de Tensão: Queda base pela distância + Queda pelo fluxo de carga no horário
    # Fator base (0.5 a 1.5). Então pontas de linha já perdem ~3% de tensão naturalmente.
    queda_distancia = (fator_base - 0.5) * 0.03 
    tensao_pu = 1.05 - queda_distancia - (carga_trecho / 100.0) * 0.08 + np.random.normal(0, 0.003, len(tempos))
    
    p_nominal_este_trecho = p_nominal_base_por_trecho * multiplicador_trecho
    
    for i, t in enumerate(tempos):
        timestamp_str = t.strftime('%Y-%m-%d %H:%M:%S')
        mapa_dados.append((trecho_id, timestamp_str, round(carga_trecho[i], 2), round(tensao_pu[i], 4)))
        
        p_kw = p_nominal_este_trecho * (carga_trecho[i] / 100.0)
        q_kvar = p_kw * 0.5 + np.random.normal(0, p_kw * 0.02) 
        
        telemetria_barras.append((trecho_id, timestamp_str, round(p_kw, 2), round(q_kvar, 2)))

df_mapa = pd.DataFrame(mapa_dados, columns=['id_trecho', 'timestamp', 'sobrecarga_perc', 'tensao_pu'])
df_mapa.to_sql('mapa_vpp', conn_vpp, if_exists='replace', index=False)
print("-> Tabela 'mapa_vpp' criada com dependência geográfica.")
conn_vpp.close()

# ==========================================
# 3. BANCO DA DSO (Telemetria)
# ==========================================
print("\nGerando Banco de Dados do DSO (dso_database.db)...")
conn_dso = sqlite3.connect('dso_database.db')

df_barras = pd.DataFrame(telemetria_barras, columns=['id_barra', 'timestamp', 'p_kw', 'q_kvar'])
df_barras.to_sql('telemetria_barras', conn_dso, if_exists='replace', index=False)

alimentador_dados = []
for i, t in enumerate(tempos):
    timestamp_str = t.strftime('%Y-%m-%d %H:%M:%S')
    
    df_momento = df_barras[df_barras['timestamp'] == timestamp_str]
    df_tensao_momento = df_mapa[df_mapa['timestamp'] == timestamp_str]
    
    total_p = df_momento['p_kw'].sum()
    total_q = df_momento['q_kvar'].sum()
    
    fator_perda_p = np.random.uniform(0.07, 0.12)
    fator_perda_q = np.random.uniform(0.07, 0.12)
    
    perdas_p = total_p * fator_perda_p
    perdas_q = total_q * fator_perda_q
    
    pior_tensao = df_tensao_momento['tensao_pu'].min()
    desvio_pu = round(1.0 - pior_tensao, 4) if pior_tensao < 1.0 else 0.0
    
    alimentador_dados.append((
        'REG09V2', timestamp_str, round(total_p, 2), round(total_q, 2),
        round(perdas_p, 2), round(perdas_q, 2), desvio_pu
    ))

colunas_alim = ['alimentador_id', 'timestamp', 'p_total_kw', 'q_total_kvar', 'perdas_p_kw', 'perdas_q_kvar', 'desvio_tensao_pu']
df_alim = pd.DataFrame(alimentador_dados, columns=colunas_alim)
df_alim.to_sql('telemetria_alimentador', conn_dso, if_exists='replace', index=False)
print("-> Tabela 'telemetria_alimentador' atualizada.")
conn_dso.close()

print("\n🚀 Bancos atualizados. O Streamlit agora pode ler dados geograficamente consistentes direto da fonte!")