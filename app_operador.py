import pandas as pd
import numpy as np
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests
import base64
from datetime import datetime
import time
import streamlit as st
import re
import unicodedata

st.set_page_config(page_title="GSAN OS", page_icon="📱", layout="centered")

# ==========================================
# TRADUÇÃO FORÇADA DOS BOTÕES (CSS HACK)
# ==========================================
st.markdown("""
    <style>
    button[title="Take photo"] { color: transparent !important; position: relative; }
    button[title="Take photo"]::after { 
        content: "📸 Tirar Foto"; 
        color: white !important; 
        position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%); 
        font-size: 16px; font-weight: bold; width: 100%;
    }
    
    button[title="Clear photo"] { color: transparent !important; position: relative; }
    button[title="Clear photo"]::after { 
        content: "🗑️ Limpar"; 
        color: white !important; 
        position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%); 
        font-size: 16px; font-weight: bold; width: 100%;
    }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# CONFIGURAÇÕES DA PLANILHA E SERVIDOR DE FOTOS
# ==========================================
IMGBB_API_KEY = "dc43a47e760fb70d50f9578108cddf3b"

COL_MATRICULA = "Informe a Matrícula do Imóvel"
COL_CIDADE = "Informe cidade do Serviço"
COL_BAIRRO = "Informe o BAIRRO de Campina Grande"
COL_SERVICO = "Qual o Serviço ?"
COL_CONCLUSAO = "Conclusão"

# ==========================================
# CONEXÃO E FUNÇÕES DE DADOS
# ==========================================
@st.cache_resource
def obter_conexao():
    creds = ServiceAccountCredentials.from_json_keyfile_name(
        "credenciais.json", 
        ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    )
    return creds

def fazer_upload_foto(foto_bytes):
    try:
        url = "https://api.imgbb.com/1/upload"
        foto_b64 = base64.b64encode(foto_bytes).decode('utf-8')
        payload = {"key": IMGBB_API_KEY, "image": foto_b64}
        resposta = requests.post(url, data=payload)
        
        if resposta.status_code == 200:
            return resposta.json()['data']['url']
        else:
            msg_erro = resposta.json().get('error', {}).get('message', 'Erro desconhecido')
            st.error(f"Erro no servidor ImgBB: {msg_erro}")
            return "FALHA_NO_UPLOAD"
    except Exception as e:
        st.error(f"Erro de conexão ao processar imagem: {e}")
        return "FALHA_NO_UPLOAD"

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

def definir_status(row):
    conclusao_original = str(row.get(COL_CONCLUSAO, "")).upper()
    conclusao = ''.join(c for c in unicodedata.normalize('NFD', conclusao_original) if unicodedata.category(c) != 'Mn')
    
    if "EXECUTAD" in conclusao or "FIZ O SERVICO" in conclusao:
        return "EXECUTADA", "#4CAF50" # Verde
    elif "DEVOLVID" in conclusao:
        return "DEVOLVIDA", "#F44336" # Vermelho
    else:
        return "PENDENTE", "#FF9800" # Laranja

def carregar_tarefas(operador):
    try:
        creds = obter_conexao()
        client = gspread.authorize(creds)
        
        aba_coords = client.open("Cópia de Controle Calçadas e Paredes TESTE").worksheet("PARAMETROS_MATRICULA")
        df_coords = pd.DataFrame(aba_coords.get_all_records())
        df_coords['Matrícula'] = df_coords['Matrícula'].astype(str).apply(lambda x: x.split('.')[0]).str.strip()
        df_coords = df_coords.drop_duplicates(subset=['Matrícula'], keep='last')
        
        aba_respostas = client.open("Cópia de Controle Calçadas e Paredes TESTE").worksheet("Respostas ao formulário 1")
        df_respostas = pd.DataFrame(aba_respostas.get_all_records())
        df_respostas.columns = df_respostas.columns.str.strip()
        
        if "Operador Atribuído" not in df_respostas.columns:
            return pd.DataFrame()
            
        df_respostas['OS'] = "OS-" + (df_respostas.index + 2).astype(str)
        df_respostas[COL_MATRICULA] = df_respostas[COL_MATRICULA].astype(str).apply(lambda x: x.split('.')[0]).str.strip()
        df_respostas = df_respostas[df_respostas[COL_MATRICULA] != ""]
        
        # Limpa os espaços e preenche vazios gerados pelas execuções
        if "Data Programada" not in df_respostas.columns:
            df_respostas["Data Programada"] = ""
            
        df_respostas['Data Programada'] = df_respostas['Data Programada'].astype(str).replace(r'^\s*$', np.nan, regex=True).replace('None', np.nan).replace('nan', np.nan)
        df_respostas['Data Programada'] = df_respostas.groupby(COL_MATRICULA)['Data Programada'].ffill()
        df_respostas['Data Programada'] = df_respostas['Data Programada'].fillna('')
        
        df_respostas['Operador Atribuído'] = df_respostas['Operador Atribuído'].astype(str).replace(r'^\s*$', np.nan, regex=True).replace('None', np.nan).replace('nan', np.nan)
        df_respostas['Operador Atribuído'] = df_respostas.groupby(COL_MATRICULA)['Operador Atribuído'].ffill()
        df_respostas['Operador Atribuído'] = df_respostas['Operador Atribuído'].fillna('')

        df_respostas = df_respostas.drop_duplicates(subset=[COL_MATRICULA], keep='last')
        
        data_hoje = datetime.now().strftime("%d/%m/%Y")
        
        # O ".str.strip()" aqui é a vacina contra espaços digitados sem querer
        df_tarefas = df_respostas[
            (df_respostas["Operador Atribuído"].astype(str).str.strip() == operador.strip()) & 
            (df_respostas["Data Programada"].astype(str).str.strip() == data_hoje)
        ].copy()
        
        if df_tarefas.empty: return pd.DataFrame()
            
        df_completo = pd.merge(df_tarefas, df_coords, left_on=COL_MATRICULA, right_on='Matrícula', how='inner')
        return df_completo
    except Exception as e:
        st.error(f"Erro ao descarregar as tarefas: {e}")
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
    except: return None

def salvar_linha_segura(aba, nova_linha):
    coluna_a = aba.col_values(1)
    proxima_linha = len(coluna_a) + 1
    intervalo = f"A{proxima_linha}:J{proxima_linha}"
    
    try:
        try:
            aba.update(range_name=intervalo, values=[nova_linha], value_input_option='USER_ENTERED')
        except TypeError:
            aba.update(intervalo, [nova_linha], value_input_option='USER_ENTERED')
    except Exception:
        aba.add_rows(10)
        try:
            aba.update(range_name=intervalo, values=[nova_linha], value_input_option='USER_ENTERED')
        except TypeError:
            aba.update(intervalo, [nova_linha], value_input_option='USER_ENTERED')

def registrar_execucao(matricula, servico, operador, cidade, bairro, f1, f2, f3):
    creds = obter_conexao()
    client = gspread.authorize(creds)
    planilha = client.open("Cópia de Controle Calçadas e Paredes TESTE")
    aba = planilha.worksheet("Respostas ao formulário 1")
    
    agora = datetime.now()
    data_formatada = agora.strftime("%d/%m/%Y %H:%M:%S")
    
    link1 = fazer_upload_foto(f1) if f1 else ""
    if link1 == "FALHA_NO_UPLOAD": return False
    link2 = fazer_upload_foto(f2) if f2 else ""
    if link2 == "FALHA_NO_UPLOAD": return False
    link3 = fazer_upload_foto(f3) if f3 else ""
    if link3 == "FALHA_NO_UPLOAD": return False
    
    nova_linha = [
        data_formatada, matricula, servico, 
        "Executado ( Eu fiz o serviço )", operador, 
        link1, link2, link3, cidade, bairro
    ]
    
    salvar_linha_segura(aba, nova_linha)
    return True

def registrar_devolucao(matricula, servico, cidade, bairro, motivo, operador, foto_bytes):
    creds = obter_conexao()
    client = gspread.authorize(creds)
    planilha = client.open("Cópia de Controle Calçadas e Paredes TESTE")
    aba = planilha.worksheet("Respostas ao formulário 1")
    
    agora = datetime.now()
    data_formatada = agora.strftime("%d/%m/%Y %H:%M:%S")
    
    link_foto = fazer_upload_foto(foto_bytes) if foto_bytes else ""
    if link_foto == "FALHA_NO_UPLOAD": return False
    
    conclusao_devolucao = f"DEVOLVIDO: {motivo}"
    
    nova_linha = [
        data_formatada, matricula, servico, 
        conclusao_devolucao, operador, 
        link_foto, "", "", cidade, bairro
    ]
    
    salvar_linha_segura(aba, nova_linha)
    return True

# ==========================================
# INTERFACE MOBILE (APP)
# ==========================================
st.markdown("<h2 style='text-align: center; color: #1E88E5;'>📱 APP OPERAÇÃO</h2>", unsafe_allow_html=True)

if "os_aberta" not in st.session_state:
    st.session_state.os_aberta = None
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False
if "ultimo_operador" not in st.session_state:
    st.session_state.ultimo_operador = None

operador = st.selectbox("👷 Identifique-se:", ["", "Julio Cesar", "Joseilton", "Alberth"])

if operador != st.session_state.ultimo_operador:
    st.session_state.autenticado = False
    st.session_state.ultimo_operador = operador
    st.session_state.os_aberta = None

if operador:
    st.divider()
    banco_senhas = {"Alberth": "123", "Julio Cesar": "456", "Joseilton": "789"}
    
    if not st.session_state.autenticado:
        with st.form(key=f"form_login_{operador}"):
            senha_digitada = st.text_input("🔑 Digite sua senha de acesso:", type="password")
            botao_entrar = st.form_submit_button("Entrar no Sistema", use_container_width=True)
            
            if botao_entrar:
                if senha_digitada == banco_senhas[operador]:
                    st.session_state.autenticado = True
                    st.rerun()
                else:
                    st.error("❌ Senha incorreta! Por favor, tente novamente.")
                
    if st.session_state.autenticado:
        
        if st.session_state.os_aberta is not None:
            with st.spinner("Carregando detalhes..."):
                df_tarefas = carregar_tarefas(operador)
                
            if not df_tarefas.empty:
                df_tarefas['Bairro_Exibicao'] = df_tarefas.apply(extrair_bairro_inteligente, axis=1)
                matricula_ativa = st.session_state.os_aberta
                df_filtrado = df_tarefas[df_tarefas[COL_MATRICULA].astype(str) == str(matricula_ativa)]
                
                if df_filtrado.empty:
                    st.warning("Ordem de serviço não encontrada ou já processada.")
                    if st.button("⬅️ Voltar", use_container_width=True):
                        st.session_state.os_aberta = None
                        st.rerun()
                else:
                    row = df_filtrado.iloc[0]
                    matricula = row[COL_MATRICULA]
                    servico = row[COL_SERVICO]
                    os_num = row['OS']
                    lat, lon = row.get('Coordenada X'), row.get('Coordenada Y')
                    lat = limpar_coordenadas(lat, 'lat')
                    lon = limpar_coordenadas(lon, 'lon')
                    endereco = row.get('Endereço', 'Endereço não informado')
                    cidade_bairro = row[COL_CIDADE].title()
                    nome_bairro = row['Bairro_Exibicao'].title()
                    
                    if st.button("⬅️ Voltar para a Lista", use_container_width=True):
                        st.session_state.os_aberta = None
                        st.rerun()
                    
                    st.markdown(f"## 📄 {os_num}")
                    st.markdown(f"### 📍 {nome_bairro} / {cidade_bairro}")
                    st.info(f"**Endereço:** {endereco}")
                    st.warning(f"**Serviço:** {servico}")
                    st.code(f"Matrícula: {matricula}")
                    
                    st.write("---")
                    if pd.notna(lat) and pd.notna(lon):
                        link_gps = f"https://www.google.com/maps/dir/?api=1&destination={lat},{lon}"
                        st.link_button("🧭 Iniciar Navegação GPS (Google Maps)", link_gps, use_container_width=True)
                        st.caption("Dica: Após clicar em Navegar, minimize ou volte para o app para ativar o mapa flutuante!")
                    
                    st.write("📸 **Registos Fotográficos**")
                    foto1 = st.camera_input("Foto 1 (Obrigatória)", key=f"cam1_{matricula}")
                    foto2 = st.camera_input("Foto 2 (Opcional)", key=f"cam2_{matricula}")
                    foto3 = st.camera_input("Foto 3 (Opcional)", key=f"cam3_{matricula}")
                    
                    st.write("---")
                    
                    chave_devolucao = f"devolver_{matricula}"
                    if chave_devolucao not in st.session_state:
                        st.session_state[chave_devolucao] = False
                    
                    if st.session_state[chave_devolucao]:
                        st.error("⚠️ Processo de Devolução de OS")
                        motivo_dev = st.text_area("Motivo detalhado da devolução:", key=f"texto_dev_{matricula}")
                        
                        c_cancel, c_confirm = st.columns(2)
                        with c_cancel:
                            if st.button("❌ Cancelar", key=f"canc_dev_{matricula}", use_container_width=True):
                                st.session_state[chave_devolucao] = False
                                st.rerun()
                        with c_confirm:
                            if st.button("✅ Confirmar Devolução", key=f"conf_dev_{matricula}", type="primary", use_container_width=True):
                                texto_motivo = motivo_dev.strip()
                                if len(texto_motivo) < 5:
                                    st.error("Escreva um motivo detalhado.")
                                else:
                                    f_bytes = foto1.getvalue() if foto1 is not None else None
                                    with st.spinner("Devolvendo..."):
                                        sucesso = registrar_devolucao(matricula, servico, cidade_bairro, nome_bairro, texto_motivo, operador, f_bytes)
                                        if sucesso:
                                            st.session_state.os_aberta = None
                                            st.session_state[chave_devolucao] = False
                                            st.success("OS devolvida com sucesso!")
                                            time.sleep(2)
                                            st.rerun()
                                        else:
                                            st.error("Falha no envio.")
                    else:
                        col1, col2 = st.columns(2)
                        with col1:
                            if st.button("↩️ Solicitar Devolução", key=f"btn_devolver_{matricula}", use_container_width=True):
                                st.session_state[chave_devolucao] = True
                                st.rerun()
                        with col2:
                            if st.button("✅ FINALIZAR SERVIÇO", key=f"btn_{matricula}", type="primary", use_container_width=True):
                                if foto1 is not None:
                                    f1_bytes = foto1.getvalue()
                                    f2_bytes = foto2.getvalue() if foto2 is not None else None
                                    f3_bytes = foto3.getvalue() if foto3 is not None else None
                                    with st.spinner("Encerrando..."):
                                        sucesso = registrar_execucao(matricula, servico, operador, cidade_bairro, nome_bairro, f1_bytes, f2_bytes, f3_bytes)
                                        if sucesso:
                                            st.session_state.os_aberta = None
                                            st.success("Serviço concluído!")
                                            time.sleep(2)
                                            st.rerun()
                                        else:
                                            st.error("Falha no envio.")
                                else:
                                    st.warning("⚠️ A Foto 1 é obrigatória!")

        else:
            col1, col2 = st.columns([3, 1])
            with col1:
                st.write(f"🔓 Logado como: **{operador}**")
            with col2:
                if st.button("🚪 Sair", use_container_width=True):
                    st.session_state.autenticado = False
                    st.rerun()
            
            with st.spinner("Atualizando roteiro..."):
                df_tarefas = carregar_tarefas(operador)
                
            if not df_tarefas.empty:
                df_tarefas['lat'] = df_tarefas['Coordenada X'].apply(lambda x: limpar_coordenadas(x, 'lat'))
                df_tarefas['lon'] = df_tarefas['Coordenada Y'].apply(lambda y: limpar_coordenadas(y, 'lon'))
                
                df_tarefas['Bairro_Exibicao'] = df_tarefas.apply(extrair_bairro_inteligente, axis=1)
                df_tarefas[['Status', 'Cor_Status']] = df_tarefas.apply(definir_status, axis=1, result_type='expand')
                df_tarefas = df_tarefas.sort_values(by=[COL_CIDADE, 'Bairro_Exibicao', 'Endereço'])
                
                aba_lista, aba_mapa = st.tabs(["📋 LISTA", "🗺️ MAPA"])
                
                with aba_lista:
                    qtd_pendentes = len(df_tarefas[df_tarefas['Status'] == 'PENDENTE'])
                    
                    if qtd_pendentes == 0:
                        st.balloons()
                        st.markdown("""
                        <div style="background-color: #1b5e20; padding: 20px; border-radius: 10px; text-align: center; border: 2px solid #4CAF50; margin-bottom: 20px;">
                            <h2 style="color: white; margin-bottom: 10px;">🍻 CABOCO BOM DA PESTE!</h2>
                            <p style="color: white; font-size: 18px; margin-bottom: 0;">Botou pra torar! O roteiro de hoje tá todo matado. Pode encostar a viatura, lavar as mãos e pegar o beco, que o serviço tá no mato! 😎🔧</p>
                        </div>
                        """, unsafe_allow_html=True)
                    else:
                        st.success(f"📍 Roteiro de Hoje: {len(df_tarefas)} serviços no total ({qtd_pendentes} pendentes).")
                    
                    cidades_unicas = sorted(df_tarefas[COL_CIDADE].unique())
                    
                    for cidade in cidades_unicas:
                        st.markdown(f"<h3 style='color: #4fc3f7; padding-top: 15px; border-bottom: 1px solid #555; padding-bottom: 5px;'>🏙️ {cidade.upper()}</h3>", unsafe_allow_html=True)
                        
                        df_cidade = df_tarefas[df_tarefas[COL_CIDADE] == cidade]
                        bairros_cidade = sorted(df_cidade['Bairro_Exibicao'].unique())
                        
                        for bairro in bairros_cidade:
                            df_bairro = df_cidade[df_cidade['Bairro_Exibicao'] == bairro]
                            nome_bairro_tela = bairro.title()
                            
                            exp_aberto = len(df_bairro[df_bairro['Status'] == 'PENDENTE']) > 0
                            
                            with st.expander(f"🗺️ {nome_bairro_tela} ({len(df_bairro)} serviços)", expanded=exp_aberto):
                                for index, row in df_bairro.iterrows():
                                    matricula = row[COL_MATRICULA]
                                    servico = row[COL_SERVICO]
                                    endereco = row.get('Endereço', 'Endereço não informado')
                                    status = row['Status']
                                    cor_badge = row['Cor_Status']
                                    
                                    st.markdown(f"""
                                    <div style="border: 1px solid #444; border-radius: 8px; padding: 15px; margin-bottom: 15px; background-color: #1e1e1e;">
                                        <div style="background-color: {cor_badge}; color: white; display: inline-block; padding: 4px 8px; border-radius: 4px; font-size: 11px; font-weight: bold; margin-bottom: 12px;">
                                            {status}
                                        </div>
                                        <div style="font-size: 18px; font-weight: bold; color: white;">Matrícula: {matricula}</div>
                                        <div style="font-size: 14px; margin-top: 8px; color: #ccc;">{endereco}</div>
                                        <div style="font-size: 12px; color: #888; margin-top: 12px;">Serviço</div>
                                        <div style="font-size: 14px; color: white; font-weight: 500;">{servico}</div>
                                    </div>
                                    """, unsafe_allow_html=True)
                                    
                                    if status == "PENDENTE":
                                        if st.button("📂 Abrir Ordem", key=f"abrir_{matricula}", use_container_width=True):
                                            st.session_state.os_aberta = matricula
                                            st.rerun()
                                    else:
                                        st.caption(f"✔️ Serviço registrado como {status.lower()} hoje.")
                                    
                                    st.write("") 

                with aba_mapa:
                    st.info("Visualização geográfica das ordens do dia.")
                    df_mapa = df_tarefas.dropna(subset=['lat', 'lon']).copy()
                    if not df_mapa.empty:
                        st.map(df_mapa, latitude='lat', longitude='lon', color='Cor_Status', use_container_width=True)
                    else:
                        st.warning("Nenhuma coordenada válida encontrada para exibir o mapa.")
            else:
                st.markdown("""
                <div style="background-color: #e65100; padding: 20px; border-radius: 10px; text-align: center; border: 2px solid #ff9800; margin-bottom: 20px;">
                    <h2 style="color: white; margin-bottom: 10px;">😎 TÁ DE FOLGA, CHEFIA?</h2>
                    <p style="color: white; font-size: 18px; margin-bottom: 0;">O roteiro de hoje tá mais limpo que bolso de liso. Não tem ordem programada pra você não. Fica na maciota aí até o controle despachar alguma coisa!</p>
                </div>
                """, unsafe_allow_html=True)