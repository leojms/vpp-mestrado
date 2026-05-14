import pandas as pd
import numpy as np

print("Iniciando o processamento dos dados da ANEEL...")

# ==========================================
# 1. CARREGAR OS DADOS E LIMPAR CABEÇALHOS
# ==========================================
caminho_continuidade = 'indicadores-continuidade-coletivos-2020-2029.csv'
caminho_compensacao = 'indicadores-continuidade-coletivos-compensacao-2020-2029.csv'

df_cont = pd.read_csv(caminho_continuidade, sep=';', decimal=',', encoding='latin1', on_bad_lines='skip')
df_comp = pd.read_csv(caminho_compensacao, sep=';', decimal=',', encoding='latin1', on_bad_lines='skip')

df_cont.columns = df_cont.columns.str.strip()
df_comp.columns = df_comp.columns.str.strip()

col_id = [c for c in df_cont.columns if 'IdeConj' in c][0]
col_dsc = [c for c in df_cont.columns if 'DscConj' in c][0]
col_val = [c for c in df_cont.columns if 'VlrIndice' in c or 'VlrCompensacao' in c][0]

# ==========================================
# 2. PREPARAR DADOS E FILTRAR A COELBA
# ==========================================
df_cont[col_id] = df_cont[col_id].astype(str).str.strip().str.replace('.0', '', regex=False)
df_comp[col_id] = df_comp[col_id].astype(str).str.strip().str.replace('.0', '', regex=False)

df_cont['SigAgente'] = df_cont['SigAgente'].astype(str).str.strip()
df_comp['SigAgente'] = df_comp['SigAgente'].astype(str).str.strip()

df_cont_coelba = df_cont[df_cont['SigAgente'].str.contains('COELBA', case=False, na=False)]
df_comp_coelba = df_comp[df_comp['SigAgente'].str.contains('COELBA', case=False, na=False)]

# ==========================================
# NOVO: EXPORTAR OS DADOS BRUTOS DA COELBA
# ==========================================
print("Exportando as planilhas originais filtradas apenas para a COELBA...")
df_cont_coelba.to_csv('Continuidade_Bruto_Coelba.csv', sep=',', decimal='.', index=False, encoding='utf-8')
df_comp_coelba.to_csv('Compensacao_Bruto_Coelba.csv', sep=',', decimal='.', index=False, encoding='utf-8')
print("-> 'Continuidade_Bruto_Coelba.csv' gerado.")
print("-> 'Compensacao_Bruto_Coelba.csv' gerado.")

# ==========================================
# 3. FILTRAR INDICADORES E CLASSIFICAR MULTAS
# ==========================================
df_cont_coelba.loc[:, 'SigIndicador'] = df_cont_coelba['SigIndicador'].astype(str).str.strip()
df_comp_coelba.loc[:, 'SigIndicador'] = df_comp_coelba['SigIndicador'].astype(str).str.strip()

# Continuidade (DEC/FEC - Cálculo por Média)
df_cont_alvo = df_cont_coelba[df_cont_coelba['SigIndicador'].isin(['DEC', 'FEC'])]

# Compensação: Filtrar famílias PG e COMP
indicadores_vpp = df_comp_coelba['SigIndicador'].str.startswith('PG') | \
                  df_comp_coelba['SigIndicador'].str.startswith('COMP')
df_comp_alvo = df_comp_coelba[indicadores_vpp].copy()

# FUNÇÃO PARA SEPARAR AS COLUNAS DE CUSTO
def classificar_multa(sigla):
    sigla = str(sigla).upper()
    if 'TRP' in sigla: # Tensão em Regime Permanente
        return 'Custo_Violacao_Tensao_R$'
    elif sigla.startswith('PG'): # Demais pagamentos (PG) são interrupções
        return 'Custo_Violacao_Continuidade_R$'
    elif sigla.startswith('COMP'): # Compensações gerais de indicadores
        return 'Custo_Compensacao_Geral_R$'
    else:
        return 'Outros'

df_comp_alvo.loc[:, 'Categoria_Multa'] = df_comp_alvo['SigIndicador'].apply(classificar_multa)

# ==========================================
# 4. AGRUPAR E CALCULAR
# ==========================================
if len(df_cont_alvo) > 0 and len(df_comp_alvo) > 0:
    print("\nCalculando médias de continuidade e detalhando multas...")
    
    # DEC e FEC Médios
    ranking_continuidade = df_cont_alvo.groupby(
        [col_id, col_dsc, 'SigIndicador']
    )[col_val].mean().unstack().reset_index()

    # Transformando as categorias de multa em colunas (Pivot) e somando
    ranking_compensacao = df_comp_alvo.pivot_table(
        index=[col_id, col_dsc],
        columns='Categoria_Multa',
        values=col_val,
        aggfunc='sum',
        fill_value=0
    ).reset_index()
    
    # Garantir que as colunas existam mesmo se tudo for zero
    for col in ['Custo_Violacao_Tensao_R$', 'Custo_Violacao_Continuidade_R$', 'Custo_Compensacao_Geral_R$']:
        if col not in ranking_compensacao.columns:
            ranking_compensacao[col] = 0.0

    # Calcular o Total Geral
    ranking_compensacao['Total_Compensacao_R$'] = (
        ranking_compensacao['Custo_Violacao_Tensao_R$'] + 
        ranking_compensacao['Custo_Violacao_Continuidade_R$'] + 
        ranking_compensacao['Custo_Compensacao_Geral_R$']
    )

    # ==========================================
    # 5. CRUZAMENTO FINAL E EXPORTAÇÃO
    # ==========================================
    ranking_final = pd.merge(
        ranking_continuidade, 
        ranking_compensacao, 
        on=[col_id, col_dsc], 
        how='inner'
    )

    if len(ranking_final) > 0:
        # Ordenar pelo maior prejuízo financeiro total
        ranking_final = ranking_final.sort_values(by='Total_Compensacao_R$', ascending=False)
        
        # Selecionar e ordenar as colunas para exibição/exportação
        colunas_finais = [
            col_dsc, 'DEC', 'FEC', 
            'Custo_Violacao_Continuidade_R$', 
            'Custo_Violacao_Tensao_R$', 
            'Custo_Compensacao_Geral_R$', 
            'Total_Compensacao_R$'
        ]
        
        print("\n--- TOP 10 CONJUNTOS PARA ALOCAÇÃO DA VPP (Ordem de Prejuízo) ---")
        print(ranking_final[colunas_finais].head(10).to_string(float_format="{:.2f}".format))
        
        # Exportar CSV padrão americano (Decimal=Ponto, Separador=Vírgula)
        ranking_final[colunas_finais].to_csv('Alvos_VPP_Coelba.csv', sep=',', decimal='.', index=False, encoding='utf-8')
        
        print("\nSucesso! Arquivo 'Alvos_VPP_Coelba.csv' gerado (Formato Ponto/Vírgula).")
    else:
        print("\nERRO: O cruzamento das tabelas resultou em vazio.")
else:
    print("\nERRO: Os filtros deixaram as tabelas vazias.")