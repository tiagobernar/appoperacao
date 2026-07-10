import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import re
import unicodedata
from datetime import datetime

st.set_page_config(page_title="Gestão de Rotas", page_icon="🗺️", layout="wide")

# ==========================================
# CONTROLE DE ACESSO (SESSION STATE)
# ==========================================
if "admin_logado" not in st.session_state:
    st.session_state.admin_logado = False
if "admin_user" not in st.session_state:
    st.session_state.admin_user = ""

# ==========================================
# MAPEAMENTO EXATO DE COLUNAS DA PLANILHA
# ==========================================
COL_DATA = "Carimbo de data/hora" 
COL_MATRICULA = "Informe a Matrícula do Imóvel"
COL_CIDADE = "Informe cidade do Serviço"
COL_BAIRRO = "Informe o BAIRRO de Campina Grande"
COL_SERVICO = "Qual o Serviço ?"
COL_CONCLUSAO = "Conclusão"

# ==========================================
# CONEXÃO E PROCESSAMENTO DE DADOS
# ==========================================
@st.cache_resource
def obter_conexao():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    try:
        import json
        credenciais = json.loads(st.secrets["credenciais_json"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(credenciais, scope)
    except Exception:
        creds = ServiceAccountCredentials.from_json_keyfile_name("credenciais.json", scope)
    return gspread.authorize(creds)

def extrair_bairro_inteligente(row):
    bairro_form = str(row.get(COL_BAIRRO, "")).strip()
    if bairro_form and bairro_form.lower() not in ['nan', 'none', '']:
        return bairro_form.upper()
    
    endereco = str(row.get('Endereço', '')).upper().strip()
    cidade = str(row.get(COL_CIDADE, '')).upper().strip()
    
    def remover_acentos(txt):
        return ''.join(c for c in unicodedata.normalize('NFD', txt) if unicodedata.category(c) != 'Mn')
        
    cidade_norm = remover_acentos(cidade)
    
    if endereco and endereco != 'NAN' and endereco != 'ENDEREÇO NÃO ENCONTRADO':
        texto_limpo = re.sub(r'\s*PB\s*\d{5}-?\d{3}\s*$', '', endereco)
        texto_limpo = re.sub(r'\s*PB\s*$', '', texto_limpo)
        
        endereco_norm = remover_acentos(texto_limpo)
        
        if cidade_norm and cidade_norm in endereco_norm:
            idx = endereco_norm.rfind(cidade_norm)
            parte_antes_cidade = texto_limpo[:idx].strip()
            
            partes = parte_antes_cidade.split('-')
            bairro_extraido = partes[-1].strip()
            if bairro_extraido:
                return bairro_extraido.upper()
                
        partes = texto_limpo.split('-')
        if len(partes) > 1:
            return partes[-1].replace(cidade, "").strip().upper()
            
    return "BAIRRO NÃO IDENTIFICADO"

@st.cache_data(ttl=60) 
def carregar_dados():
    try:
        client = obter_conexao()
        
        aba_coords = client.open("Cópia de Controle Calçadas e Paredes TESTE").worksheet("PARAMETROS_MATRICULA")
        df_coords = pd.DataFrame(aba_coords.get_all_records())
        df_coords['Matrícula'] = df_coords['Matrícula'].astype(str).apply(lambda x: x.split('.')[0]).str.strip()
        df_coords = df_coords.drop_duplicates(subset=['Matrícula'], keep='last')
        
        aba_respostas = client.open("Cópia de Controle Calçadas e Paredes TESTE").worksheet("Respostas ao formulário 1")
        df_respostas = pd.DataFrame(aba_respostas.get_all_records())
        df_respostas.columns = df_respostas.columns.str.strip()
        
        df_respostas['Linha_Planilha'] = df_respostas.index + 2
        df_respostas['OS'] = "OS-" + df_respostas['Linha_Planilha'].astype(str)
        
        if "Operador Atribuído" not in df_respostas.columns:
            df_respostas["Operador Atribuído"] = ""
            
        if "Data Programada" not in df_respostas.columns:
            df_respostas["Data Programada"] = ""
            
        df_respostas[COL_MATRICULA] = df_respostas[COL_MATRICULA].astype(str).apply(lambda x: x.split('.')[0]).str.strip()
        df_respostas = df_respostas[df_respostas[COL_MATRICULA] != ""]
        
        df_respostas = df_respostas.drop_duplicates(subset=[COL_MATRICULA], keep='last')
        df_respostas[COL_CONCLUSAO] = df_respostas[COL_CONCLUSAO].astype(str).str.strip().str.upper()
        df_respostas[COL_SERVICO] = df_respostas[COL_SERVICO].astype(str).str.strip().str.upper()
        
        df_pendentes = df_respostas[
            (~df_respostas[COL_CONCLUSAO].str.contains("EXECUTAD", na=False)) &
            (~df_respostas[COL_CONCLUSAO].str.contains("GERADO", na=False))
        ]
        
        df_pendentes = df_pendentes[
            df_pendentes[COL_SERVICO].str.contains("PAREDE|INSTALA|ASSENTAMENTO|TAMPA", regex=True, na=False)
        ]
        
        df_pendentes[COL_CIDADE] = df_pendentes[COL_CIDADE].fillna("NÃO INFORMADA").astype(str).str.strip().str.upper()
        df_pendentes[COL_BAIRRO] = df_pendentes[COL_BAIRRO].fillna("").astype(str).str.strip().str.upper()
        df_pendentes[COL_DATA] = df_pendentes[COL_DATA].astype(str).str.split(' ').str[0]
        
        df_completo = pd.merge(df_pendentes, df_coords, left_on=COL_MATRICULA, right_on='Matrícula', how='inner')
        
        if 'Endereço' not in df_completo.columns:
            df_completo['Endereço'] = "Endereço não encontrado"
            
        df_completo[COL_BAIRRO] = df_completo.apply(extrair_bairro_inteligente, axis=1)
            
        return df_completo
        
    except Exception as e:
        st.error(f"Erro ao cruzar os dados: {e}")
        return pd.DataFrame()

def limpar_coordenadas(valor, tipo):
    try:
        texto = str(valor).replace(".", "").replace(",", "").strip()
        if not texto or texto in ["ERRO", "Sem X", "Sem Y", ""]: return None
        sinal = -1 if texto.startswith('-') else 1
        nums = texto.replace('-', '')
        if not nums.isdigit(): return None
        if tipo == 'lat': return sinal * float(nums[0] + "." + nums[1:])
        elif tipo == 'lon': return sinal * float(nums[:2] + "." + nums[2:])
    except:
        return None

def mover_para_pasta(df_alvo, nome_operador, data_programada=""):
    client = obter_conexao()
    planilha = client.open("Cópia de Controle Calçadas e Paredes TESTE")
    aba = planilha.worksheet("Respostas ao formulário 1")
    
    header = aba.row_values(1)
    
    if "Operador Atribuído" not in header:
        col_idx_op = len(header) + 1
        aba.update_cell(1, col_idx_op, "Operador Atribuído")
        header.append("Operador Atribuído")
    else:
        col_idx_op = header.index("Operador Atribuído") + 1

    if "Data Programada" not in header:
        col_idx_data = len(header) + 1
        aba.update_cell(1, col_idx_data, "Data Programada")
        header.append("Data Programada")
    else:
        col_idx_data = header.index("Data Programada") + 1

    celulas_para_atualizar = []
    for linha in df_alvo['Linha_Planilha']:
        celulas_para_atualizar.append(gspread.Cell(row=int(linha), col=col_idx_op, value=nome_operador))
        celulas_para_atualizar.append(gspread.Cell(row=int(linha), col=col_idx_data, value=data_programada))
    
    if celulas_para_atualizar:
        aba.update_cells(celulas_para_atualizar)
        
    idx_inicio = min(col_idx_op, col_idx_data) - 1
    idx_fim = max(col_idx_op, col_idx_data) 
    
    body_ocultar = {
        "requests": [{
            "updateDimensionProperties": {
                "range": {
                    "sheetId": aba.id,
                    "dimension": "COLUMNS",
                    "startIndex": idx_inicio,
                    "endIndex": idx_fim
                },
                "properties": {
                    "hiddenByUser": True
                },
                "fields": "hiddenByUser"
            }
        }]
    }
    planilha.batch_update(body_ocultar)
    
    st.cache_data.clear() 

# ==========================================
# INTERFACE DO APLICATIVO E LOGIN
# ==========================================
banco_senhas_admin = {
    "Tiago": "883237",
    "Gabriel": "123456"
}

if not st.session_state.admin_logado:
    st.markdown("<br><br><br>", unsafe_allow_html=True) 
    col1, col2, col3 = st.columns([1, 1, 1]) 
    
    with col2:
        st.markdown("<h2 style='text-align: center; color: #1E88E5;'>🔐 Acesso Restrito</h2>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: center; color: gray;'>Gestão de Despacho e Rotas GSAN</p>", unsafe_allow_html=True)
        st.divider()
        
        with st.form(key="form_login_admin"):
            admin_selecionado = st.selectbox("👤 Programador:", ["", "Tiago", "Gabriel"])
            senha_admin = st.text_input("🔑 Senha:", type="password")
            
            st.markdown("<br>", unsafe_allow_html=True)
            botao_entrar = st.form_submit_button("Entrar no Sistema", type="primary", use_container_width=True)
            
            if botao_entrar:
                if admin_selecionado == "":
                    st.warning("⚠️ Por favor, selecione seu usuário.")
                elif senha_admin == banco_senhas_admin.get(admin_selecionado):
                    st.session_state.admin_logado = True
                    st.session_state.admin_user = admin_selecionado
                    st.rerun()
                else:
                    st.error("❌ Senha incorreta!")

# ==========================================
# TELA PRINCIPAL (LIBERADA APÓS O LOGIN)
# ==========================================
if st.session_state.admin_logado:
    st.sidebar.markdown(f"👤 **Logado como:** {st.session_state.admin_user}")
    if st.sidebar.button("🚪 Sair do Sistema", use_container_width=True):
        st.session_state.admin_logado = False
        st.session_state.admin_user = ""
        st.rerun()
        
    st.sidebar.divider()
    
    st.title("🗺️ Centro de Despacho e Rotas")

    with st.spinner("A carregar as Caixas de Entrada e as Pastas dos Operadores..."):
        df = carregar_dados()

    if not df.empty:
        df['lat'] = df['Coordenada X'].apply(lambda x: limpar_coordenadas(x, 'lat'))
        df['lon'] = df['Coordenada Y'].apply(lambda y: limpar_coordenadas(y, 'lon'))
        df = df.dropna(subset=['lat', 'lon'])
        df = df[df[COL_CIDADE].astype(bool) & (df[COL_CIDADE] != "NONE") & (df[COL_CIDADE] != "")]

        aba_caixa_entrada, aba_pasta_operadores = st.tabs(["📥 Caixa de Entrada (Aguardando Despacho)", "📂 Pastas dos Operadores"])

        with aba_caixa_entrada:
            df_caixa = df[df["Operador Atribuído"] == ""].copy()
            
            st.sidebar.header("🔍 Filtros: Caixa de Entrada")
            lista_cidades = sorted(df_caixa[COL_CIDADE].unique().tolist())
            cidade_selecionada = st.sidebar.selectbox("Cidade:", ["Todas as Cidades"] + lista_cidades, key="cid_caixa")
            
            if cidade_selecionada != "Todas as Cidades":
                df_caixa = df_caixa[df_caixa[COL_CIDADE] == cidade_selecionada]
                
            lista_bairros = sorted([b for b in df_caixa[COL_BAIRRO].unique().tolist() if b.strip() != ""])
            
            bairro_selecionado = "Todos os Bairros"
            if lista_bairros:
                bairro_selecionado = st.sidebar.selectbox("Bairro:", ["Todos os Bairros"] + lista_bairros, key="bai_caixa")
                if bairro_selecionado != "Todos os Bairros":
                    df_caixa = df_caixa[df_caixa[COL_BAIRRO] == bairro_selecionado]
                    
            st.sidebar.divider()
            operadores_oficiais = ["Julio Cesar", "Joseilton", "Alberth"]
            operador_destino = st.sidebar.selectbox("👷 Enviar Rotas Marcadas Para:", operadores_oficiais, key="op_destino")
            
            data_escolhida = st.sidebar.date_input("📅 Data da Programação:", format="DD/MM/YYYY")
            data_formatada = data_escolhida.strftime("%d/%m/%Y")

            st.subheader("Pendentes Globais (Tela Cheia)")
            if not df_caixa.empty:
                marcar_todos = st.checkbox("☑️ Selecionar todos os pendentes listados abaixo", key="chk_todos_caixa")
                df_caixa.insert(0, "✔️", marcar_todos)
                
                df_caixa['Data_Real'] = pd.to_datetime(df_caixa[COL_DATA], dayfirst=True, errors='coerce')
                
                if cidade_selecionada == "Todas as Cidades" and bairro_selecionado == "Todos os Bairros":
                    df_caixa = df_caixa.sort_values(by=['Data_Real', COL_CIDADE, COL_BAIRRO]).reset_index(drop=True)
                else:
                    df_caixa = df_caixa.sort_values(by=[COL_CIDADE, COL_BAIRRO, 'Endereço']).reset_index(drop=True)
                
                df_caixa = df_caixa.drop(columns=['Data_Real'])
                
                df_editado_caixa = st.data_editor(
                    df_caixa[['✔️', 'OS', COL_DATA, COL_MATRICULA, COL_CIDADE, COL_BAIRRO, 'Endereço', COL_SERVICO, 'Linha_Planilha', 'lat', 'lon']], 
                    use_container_width=True, 
                    hide_index=True, 
                    height=450,
                    disabled=["OS", COL_DATA, COL_MATRICULA, COL_CIDADE, COL_BAIRRO, "Endereço", COL_SERVICO], 
                    column_config={
                        "✔️": st.column_config.CheckboxColumn("Selecione", width="small"),
                        "OS": st.column_config.TextColumn("OS", width="small"),
                        COL_DATA: st.column_config.TextColumn("Data", width="small"),
                        COL_MATRICULA: st.column_config.TextColumn("Matrícula", width="small"),
                        COL_CIDADE: st.column_config.TextColumn("Cidade", width="medium"),
                        COL_BAIRRO: st.column_config.TextColumn("Bairro", width="medium"),
                        "Endereço": st.column_config.TextColumn("Endereço", width="large"),
                        COL_SERVICO: st.column_config.TextColumn("Serviço", width="large"),
                        "Linha_Planilha": None, "lat": None, "lon": None
                    }
                )
                
                df_selecionado_caixa = df_editado_caixa[df_editado_caixa["✔️"] == True]
                st.info(f"📍 Selecionadas: {len(df_selecionado_caixa)} de {len(df_caixa)} pendentes")
                
                if st.button(f"🚀 Despachar {len(df_selecionado_caixa)} ordens para o dia {data_formatada}", use_container_width=True):
                    if len(df_selecionado_caixa) > 0:
                        mover_para_pasta(df_selecionado_caixa, operador_destino, data_formatada)
                        st.success(f"Ordens enviadas com sucesso para {operador_destino} no dia {data_formatada}!")
                        st.rerun()
                    else:
                        st.warning("⚠️ Marque pelo menos uma caixinha na tabela acima para poder despachar.")
                
                st.write("---")
                st.subheader("🗺️ Mapa de Distribuição Global")
                st.map(df_caixa[['lat', 'lon']], height=450)
            else:
                st.success("Nenhuma ordem pendente nesta seleção.")

        with aba_pasta_operadores:
            st.sidebar.header("📂 Visualizar Pasta")
            
            operadores_com_servico = sorted([op for op in df["Operador Atribuído"].unique() if op.strip() != ""])
            
            if operadores_com_servico:
                operador_pasta = st.sidebar.radio("Ver tarefas de:", operadores_com_servico, key="op_pasta")
                df_pasta = df[df["Operador Atribuído"] == operador_pasta].copy()
                
                datas_programadas = sorted([str(d) for d in df_pasta["Data Programada"].unique() if str(d).strip() != ""])
                if datas_programadas:
                    st.sidebar.markdown("---")
                    st.sidebar.markdown("**📅 Filtrar por Data Programada:**")
                    data_filtro = st.sidebar.radio("", ["Todas as Datas"] + datas_programadas, label_visibility="collapsed")
                    
                    if data_filtro != "Todas as Datas":
                        df_pasta = df_pasta[df_pasta["Data Programada"] == data_filtro]
                
                st.subheader(f"Rotas Atuais de {operador_pasta} (Tela Cheia)")
                
                marcar_todos_pasta = st.checkbox("☑️ Selecionar todos os serviços desta pasta", key="chk_todos_pasta")
                df_pasta.insert(0, "✔️", marcar_todos_pasta)
                
                df_pasta = df_pasta.sort_values(by=[COL_CIDADE, COL_BAIRRO, 'Endereço']).reset_index(drop=True)
                
                df_editado_pasta = st.data_editor(
                    df_pasta[['✔️', 'OS', 'Data Programada', COL_DATA, COL_MATRICULA, COL_CIDADE, COL_BAIRRO, 'Endereço', COL_SERVICO, 'Linha_Planilha', 'lat', 'lon']], 
                    use_container_width=True, 
                    hide_index=True, 
                    height=450,
                    disabled=["OS", "Data Programada", COL_DATA, COL_MATRICULA, COL_CIDADE, COL_BAIRRO, "Endereço", COL_SERVICO],
                    column_config={
                        "✔️": st.column_config.CheckboxColumn("Selecione", width="small"),
                        "OS": st.column_config.TextColumn("OS", width="small"),
                        "Data Programada": st.column_config.TextColumn("Agendado", width="medium"),
                        COL_DATA: st.column_config.TextColumn("Data Criação", width="small"),
                        COL_MATRICULA: st.column_config.TextColumn("Matrícula", width="small"),
                        COL_CIDADE: st.column_config.TextColumn("Cidade", width="medium"),
                        COL_BAIRRO: st.column_config.TextColumn("Bairro", width="medium"), 
                        "Endereço": st.column_config.TextColumn("Endereço", width="large"),
                        COL_SERVICO: st.column_config.TextColumn("Serviço", width="large"),
                        "Linha_Planilha": None, "lat": None, "lon": None
                    }
                )
                
                df_selecionado_devolver = df_editado_pasta[df_editado_pasta["✔️"] == True]
                st.info(f"📍 Rota atual de {operador_pasta} tem {len(df_pasta)} serviços listados nesta seleção.")
                
                if st.button(f"↩️ Devolver {len(df_selecionado_devolver)} ordens marcadas à Caixa de Entrada", use_container_width=True):
                    if len(df_selecionado_devolver) > 0:
                        mover_para_pasta(df_selecionado_devolver, "", "") 
                        st.success("Tarefas devolvidas para a caixa de entrada!")
                        st.rerun()
                    else:
                        st.warning("⚠️ Marque pelo menos uma caixinha para devolver.")

                st.write("---")
                st.subheader(f"🗺️ Mapa da Rota Dedicada - {operador_pasta}")
                if not df_pasta.empty: 
                    st.map(df_pasta[['lat', 'lon']], height=450)
            else:
                st.success("📭 Nenhuma rota atribuída aos operadores ainda. As pastas estão limpas!")
    else:
        st.success("Tudo limpo! Nenhuma ordem pendente no sistema.")
