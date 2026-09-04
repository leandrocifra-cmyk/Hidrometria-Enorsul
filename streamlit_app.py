import os
import time
import math
import hmac
import hashlib
import datetime as dt
import urllib.parse
import urllib.request
import duckdb
import streamlit as st


# ==========================================================
# CONFIGURAÇÃO
# ==========================================================

st.set_page_config(
    page_title="Gestão Comercial",
    page_icon="💧",
    layout="wide",
)

APP_VERSION = "v25.4-2026-09-04"
PASTA_DADOS = "data"

ARQUIVO_RMR = os.path.join(PASTA_DADOS, "RMR.parquet")
ARQUIVO_INTERIOR = os.path.join(PASTA_DADOS, "Interior.parquet")
ARQUIVOS_FONTE = [ARQUIVO_RMR, ARQUIVO_INTERIOR]

ARQUIVO_PARQUET = os.path.join(
    PASTA_DADOS,
    "base_pernambuco_analitica_v23.parquet",
)

os.makedirs(PASTA_DADOS, exist_ok=True)


# ==========================================================
# CLOUDFLARE R2 - DOWNLOAD PRIVADO DAS BASES
# ==========================================================

def obter_config_r2():
    """Retorna a configuração privada do R2 a partir do Streamlit Secrets."""
    try:
        bloco = st.secrets.get("r2", {})
    except Exception:
        bloco = {}

    campos = (
        "access_key_id",
        "secret_access_key",
        "endpoint_url",
        "bucket",
    )

    config = {campo: str(bloco.get(campo, "")).strip() for campo in campos}

    if not all(config.values()):
        return None

    config["endpoint_url"] = config["endpoint_url"].rstrip("/")
    return config


def _assinar_chave_r2(chave, mensagem):
    return hmac.new(chave, mensagem.encode("utf-8"), hashlib.sha256).digest()


def baixar_objeto_r2(nome_objeto, destino):
    """Baixa um objeto privado do Cloudflare R2 usando AWS Signature V4."""
    config = obter_config_r2()

    if not config:
        raise RuntimeError(
            "As credenciais do Cloudflare R2 não estão configuradas nos Secrets do Streamlit."
        )

    endpoint = config["endpoint_url"]
    bucket = config["bucket"]
    access_key = config["access_key_id"]
    secret_key = config["secret_access_key"]

    parsed = urllib.parse.urlparse(endpoint)
    host = parsed.netloc

    caminho_objeto = "/" + "/".join(
        urllib.parse.quote(parte, safe="-_.~")
        for parte in (bucket, nome_objeto)
    )
    url = f"{endpoint}{caminho_objeto}"

    agora = dt.datetime.now(dt.timezone.utc)
    amz_date = agora.strftime("%Y%m%dT%H%M%SZ")
    data_curta = agora.strftime("%Y%m%d")
    regiao = "auto"
    servico = "s3"
    payload_hash = hashlib.sha256(b"").hexdigest()

    canonical_headers = (
        f"host:{host}\n"
        f"x-amz-content-sha256:{payload_hash}\n"
        f"x-amz-date:{amz_date}\n"
    )
    signed_headers = "host;x-amz-content-sha256;x-amz-date"
    canonical_request = (
        "GET\n"
        f"{caminho_objeto}\n"
        "\n"
        f"{canonical_headers}\n"
        f"{signed_headers}\n"
        f"{payload_hash}"
    )

    credential_scope = f"{data_curta}/{regiao}/{servico}/aws4_request"
    string_to_sign = (
        "AWS4-HMAC-SHA256\n"
        f"{amz_date}\n"
        f"{credential_scope}\n"
        + hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
    )

    k_date = _assinar_chave_r2(("AWS4" + secret_key).encode("utf-8"), data_curta)
    k_region = _assinar_chave_r2(k_date, regiao)
    k_service = _assinar_chave_r2(k_region, servico)
    k_signing = _assinar_chave_r2(k_service, "aws4_request")
    signature = hmac.new(
        k_signing,
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    authorization = (
        "AWS4-HMAC-SHA256 "
        f"Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, "
        f"Signature={signature}"
    )

    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Host": host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
            "Authorization": authorization,
        },
    )

    os.makedirs(os.path.dirname(destino) or ".", exist_ok=True)
    temporario = destino + ".part"

    try:
        with urllib.request.urlopen(request, timeout=180) as resposta, open(temporario, "wb") as saida:
            while True:
                bloco = resposta.read(8 * 1024 * 1024)
                if not bloco:
                    break
                saida.write(bloco)
        os.replace(temporario, destino)
    except Exception:
        if os.path.exists(temporario):
            os.remove(temporario)
        raise


def garantir_bases_locais(forcar=False):
    """Garante RMR.parquet e Interior.parquet no runtime do Streamlit."""
    pares = [
        ("RMR.parquet", ARQUIVO_RMR),
        ("Interior.parquet", ARQUIVO_INTERIOR),
    ]

    pendentes = [
        (nome, caminho)
        for nome, caminho in pares
        if forcar or not os.path.exists(caminho)
    ]

    if not pendentes:
        return False

    config = obter_config_r2()
    if not config:
        return False

    for nome, caminho in pendentes:
        baixar_objeto_r2(nome, caminho)

    return True


# ==========================================================
# ESTILO
# ==========================================================

st.markdown(
    """
    <style>
    /* ======================================================
       V25 - BLACK PIANO + VISÃO GERAL + LOGIN + RMR/INTERIOR + R2
       ====================================================== */

    html, body, [class*="css"] {
        color: #F4F4F4;
    }

    .stApp {
        background:
            radial-gradient(circle at 15% 10%, rgba(255,255,255,0.045), transparent 28%),
            radial-gradient(circle at 85% 0%, rgba(255,255,255,0.025), transparent 22%),
            linear-gradient(180deg, #050505 0%, #090909 42%, #030303 100%);
    }

    [data-testid="stAppViewContainer"] {
        background: transparent;
    }

    [data-testid="stHeader"] {
        background: rgba(0,0,0,0.80);
        border-bottom: 1px solid rgba(255,255,255,0.08);
        backdrop-filter: blur(12px);
    }

    .block-container {
        padding-top: 3.5rem;
        padding-bottom: 2rem;
        max-width: 1600px;
    }

    /* SIDEBAR */
    [data-testid="stSidebar"] {
        background:
            linear-gradient(180deg, #050505 0%, #0A0A0A 45%, #020202 100%);
        border-right: 1px solid rgba(255,255,255,0.10);
        box-shadow: 10px 0 24px rgba(0,0,0,0.35);
    }

    [data-testid="stSidebar"] * {
        color: #F2F2F2;
    }

    /* TÍTULOS */
    h1, h2, h3 {
        color: #FFFFFF !important;
        letter-spacing: -0.02em;
    }

    h1 {
        text-shadow: 0 2px 18px rgba(255,255,255,0.06);
    }

    /* CARDS / MÉTRICAS */
    [data-testid="stMetric"] {
        background:
            linear-gradient(145deg, rgba(28,28,28,0.98), rgba(5,5,5,0.98));
        border: 1px solid rgba(255,255,255,0.10);
        border-radius: 14px;
        padding: 14px 16px;
        box-shadow:
            inset 0 1px 0 rgba(255,255,255,0.06),
            0 10px 25px rgba(0,0,0,0.26);
    }

    [data-testid="stMetricLabel"] {
        color: #BDBDBD !important;
        font-weight: 600;
    }

    [data-testid="stMetricValue"] {
        font-size: 1.55rem;
        color: #FFFFFF !important;
        font-weight: 700;
    }

    /* RADIOS / NAVEGAÇÃO */
    div[data-testid="stRadio"] > div {
        gap: 0.65rem;
    }

    div[data-testid="stRadio"] label {
        background: linear-gradient(180deg, #171717, #0A0A0A);
        border: 1px solid rgba(255,255,255,0.10);
        border-radius: 10px;
        padding: 7px 12px;
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.04);
    }

    /* INPUTS */
    [data-baseweb="input"] > div,
    [data-baseweb="select"] > div,
    [data-baseweb="textarea"] > div {
        background: #0B0B0B !important;
        border-color: rgba(255,255,255,0.12) !important;
        color: #FFFFFF !important;
    }

    input, textarea {
        color: #FFFFFF !important;
    }

    /* MULTISELECT TAGS */
    [data-baseweb="tag"] {
        background: #1C1C1C !important;
        color: #FFFFFF !important;
        border: 1px solid rgba(255,255,255,0.12);
    }

    /* ======================================================
       V24.3 - TEMA NATIVO DARK + BLACK PIANO
       Mantém lógica, cálculos e integração R2 inalterados.
       ====================================================== */

    /* INPUTS / NUMBER INPUT / LOGIN - Streamlit atual */
    [data-testid="stTextInput"] [data-baseweb="input"],
    [data-testid="stNumberInput"] [data-baseweb="input"],
    [data-testid="stTextArea"] [data-baseweb="textarea"],
    [data-testid="stDateInput"] [data-baseweb="input"],
    [data-testid="stTimeInput"] [data-baseweb="input"] {
        background: #0B0B0B !important;
        border: 1px solid rgba(255,255,255,0.16) !important;
        border-radius: 8px !important;
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.035) !important;
    }

    [data-testid="stTextInput"] input,
    [data-testid="stNumberInput"] input,
    [data-testid="stTextArea"] textarea,
    [data-testid="stDateInput"] input,
    [data-testid="stTimeInput"] input {
        background: transparent !important;
        color: #FFFFFF !important;
        -webkit-text-fill-color: #FFFFFF !important;
        caret-color: #FFFFFF !important;
    }

    [data-testid="stTextInput"] input::placeholder,
    [data-testid="stNumberInput"] input::placeholder,
    [data-testid="stTextArea"] textarea::placeholder {
        color: #7F7F7F !important;
        -webkit-text-fill-color: #7F7F7F !important;
        opacity: 1 !important;
    }

    /* Corrige autofill branco do navegador na tela de login */
    input:-webkit-autofill,
    input:-webkit-autofill:hover,
    input:-webkit-autofill:focus,
    textarea:-webkit-autofill,
    select:-webkit-autofill {
        -webkit-text-fill-color: #FFFFFF !important;
        -webkit-box-shadow: 0 0 0 1000px #0B0B0B inset !important;
        box-shadow: 0 0 0 1000px #0B0B0B inset !important;
        caret-color: #FFFFFF !important;
        transition: background-color 9999s ease-out 0s;
    }

    /* Botões +/- do number_input */
    [data-testid="stNumberInput"] button {
        background: #111111 !important;
        color: #EDEDED !important;
        border-color: rgba(255,255,255,0.12) !important;
    }

    [data-testid="stNumberInput"] button:hover {
        background: #1C1C1C !important;
        color: #FFFFFF !important;
    }

    [data-testid="stNumberInput"] button svg {
        fill: #EDEDED !important;
        color: #EDEDED !important;
    }

    /* MULTISELECT / SELECT - fecha o fundo branco do BaseWeb */
    [data-testid="stMultiSelect"] [data-baseweb="select"] > div,
    [data-testid="stSelectbox"] [data-baseweb="select"] > div,
    [data-testid="stSelectbox"] [data-baseweb="select"],
    [data-testid="stMultiSelect"] [data-baseweb="select"] {
        background: #0B0B0B !important;
        color: #FFFFFF !important;
        border-color: rgba(255,255,255,0.16) !important;
    }

    [data-testid="stMultiSelect"] input,
    [data-testid="stSelectbox"] input {
        color: #FFFFFF !important;
        -webkit-text-fill-color: #FFFFFF !important;
    }

    [data-testid="stMultiSelect"] svg,
    [data-testid="stSelectbox"] svg {
        fill: #DADADA !important;
        color: #DADADA !important;
    }

    /* Menus suspensos dos selects/multiselects */
    [data-baseweb="popover"] > div,
    [data-baseweb="menu"],
    [role="listbox"],
    [role="option"] {
        background: #101010 !important;
        color: #F3F3F3 !important;
    }

    [role="option"]:hover,
    [aria-selected="true"][role="option"] {
        background: #222222 !important;
        color: #FFFFFF !important;
    }

    /* FORMULÁRIO DE LOGIN */
    [data-testid="stForm"] {
        background: linear-gradient(145deg, rgba(20,20,20,0.98), rgba(5,5,5,0.99)) !important;
        border: 1px solid rgba(255,255,255,0.10) !important;
        border-radius: 16px !important;
        padding: 1rem !important;
    }

    [data-testid="stForm"] label,
    [data-testid="stForm"] p {
        color: #EDEDED !important;
    }

    /* DATAFRAME - moldura e superfícies auxiliares */
    [data-testid="stDataFrame"],
    [data-testid="stDataFrameResizable"],
    [data-testid="stDataFrame"] > div {
        background: #090909 !important;
        color: #F3F3F3 !important;
    }

    [data-testid="stDataFrame"] button {
        background: #121212 !important;
        color: #F3F3F3 !important;
        border-color: rgba(255,255,255,0.10) !important;
    }

    [data-testid="stDataFrame"] svg {
        color: #D9D9D9 !important;
        fill: #D9D9D9 !important;
    }

    /* BOTÕES */
    .stButton > button,
    .stDownloadButton > button {
        background: linear-gradient(180deg, #202020 0%, #080808 100%);
        color: #FFFFFF;
        border: 1px solid rgba(255,255,255,0.14);
        border-radius: 10px;
        box-shadow:
            inset 0 1px 0 rgba(255,255,255,0.08),
            0 6px 16px rgba(0,0,0,0.28);
        transition: 0.15s ease-in-out;
    }

    .stButton > button:hover,
    .stDownloadButton > button:hover {
        border-color: rgba(255,255,255,0.30);
        transform: translateY(-1px);
        background: linear-gradient(180deg, #2A2A2A 0%, #0D0D0D 100%);
    }

    /* EXPANDERS */
    [data-testid="stExpander"] {
        background: linear-gradient(180deg, rgba(18,18,18,0.96), rgba(7,7,7,0.96));
        border: 1px solid rgba(255,255,255,0.09);
        border-radius: 12px;
    }

    /* DATAFRAMES */
    [data-testid="stDataFrame"] {
        border: 1px solid rgba(255,255,255,0.09);
        border-radius: 12px;
        overflow: hidden;
        box-shadow: 0 10px 24px rgba(0,0,0,0.20);
    }

    /* ALERTAS */
    [data-testid="stAlert"] {
        border-radius: 12px;
        border: 1px solid rgba(255,255,255,0.10);
        background: rgba(18,18,18,0.92);
    }

    /* DIVISORES */
    hr {
        border-color: rgba(255,255,255,0.08) !important;
    }

    /* CAPTIONS */
    .stCaption, [data-testid="stCaptionContainer"] {
        color: #A9A9A9 !important;
    }

    /* SCROLLBAR */
    ::-webkit-scrollbar {
        width: 10px;
        height: 10px;
    }

    ::-webkit-scrollbar-track {
        background: #050505;
    }

    ::-webkit-scrollbar-thumb {
        background: #262626;
        border-radius: 10px;
        border: 2px solid #050505;
    }

    ::-webkit-scrollbar-thumb:hover {
        background: #343434;
    }

    /* LOGIN */
    .login-shell {
        max-width: 460px;
        margin: 7vh auto 1rem auto;
        padding: 34px 34px 26px 34px;
        background:
            linear-gradient(145deg, rgba(28,28,28,0.98), rgba(4,4,4,0.99));
        border: 1px solid rgba(255,255,255,0.11);
        border-radius: 20px;
        box-shadow:
            inset 0 1px 0 rgba(255,255,255,0.07),
            0 28px 70px rgba(0,0,0,0.52);
        text-align: center;
    }

    .login-brand {
        font-size: 0.82rem;
        font-weight: 700;
        letter-spacing: 0.18em;
        color: #9B9B9B;
        margin-bottom: 10px;
    }

    .login-title {
        font-size: 2rem;
        font-weight: 800;
        color: #FFFFFF;
        letter-spacing: -0.03em;
        margin-bottom: 6px;
    }

    .login-subtitle {
        color: #A8A8A8;
        font-size: 0.95rem;
        margin-bottom: 2px;
    }

    .login-footer {
        color: #777777;
        font-size: 0.78rem;
        text-align: center;
        margin-top: 16px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ==========================================================
# AUTENTICAÇÃO - USUÁRIO/SENHA ÚNICOS DA EQUIPE
# ==========================================================

def obter_credencial_auth(nome):
    """
    Ordem de leitura:
    1) Streamlit Secrets: [auth] username / password
    2) Variáveis de ambiente: AUTH_USERNAME / AUTH_PASSWORD
    """
    try:
        bloco_auth = st.secrets.get("auth", {})
        valor = bloco_auth.get(nome)
        if valor is not None and str(valor).strip():
            return str(valor)
    except Exception:
        pass

    env_map = {
        "username": "AUTH_USERNAME",
        "password": "AUTH_PASSWORD",
    }

    valor_env = os.getenv(env_map[nome])
    if valor_env is not None and str(valor_env).strip():
        return str(valor_env)

    return None


def autenticar():
    usuario_correto = obter_credencial_auth("username")
    senha_correta = obter_credencial_auth("password")

    if not usuario_correto or not senha_correta:
        st.markdown(
            """
            <div class="login-shell">
                <div class="login-brand">ENORSUL • AQUA PERNAMBUCO</div>
                <div class="login-title">Acesso ao Painel</div>
                <div class="login-subtitle">
                    Credenciais ainda não configuradas.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.error(
            "Configure o usuário e a senha nos Secrets do Streamlit Cloud "
            "antes de liberar o painel."
        )
        st.code(
            '[auth]\nusername = "enorsul"\npassword = "SUA_SENHA_FORTE_AQUI"',
            language="toml",
        )
        st.stop()

    if st.session_state.get("autenticado", False):
        return True

    st.markdown(
        """
        <div class="login-shell">
            <div class="login-brand">ENORSUL • AQUA PERNAMBUCO</div>
            <div class="login-title">Gestão Comercial</div>
            <div class="login-subtitle">
                Informe as credenciais da equipe para acessar o painel.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    centro_esq, centro, centro_dir = st.columns([1, 1.05, 1])

    with centro:
        with st.form("form_login", clear_on_submit=False):
            usuario = st.text_input(
                "Usuário",
                placeholder="Digite o usuário",
                autocomplete="username",
            )

            senha = st.text_input(
                "Senha",
                type="password",
                placeholder="Digite a senha",
                autocomplete="current-password",
            )

            entrar = st.form_submit_button(
                "Entrar",
                use_container_width=True,
            )

        if entrar:
            usuario_ok = hmac.compare_digest(
                str(usuario).strip(),
                usuario_correto,
            )
            senha_ok = hmac.compare_digest(
                str(senha),
                senha_correta,
            )

            if usuario_ok and senha_ok:
                st.session_state["autenticado"] = True
                st.session_state["usuario_logado"] = usuario_correto
                st.rerun()
            else:
                st.error("Usuário ou senha inválidos.")

    st.markdown(
        '<div class="login-footer">Acesso restrito à equipe autorizada.</div>',
        unsafe_allow_html=True,
    )

    st.stop()


autenticar()

# Botão de saída disponível durante toda a sessão autenticada.
with st.sidebar:
    st.caption("🔐 Acesso autenticado")
    if st.button(
        "Sair",
        use_container_width=True,
        key="logout_global_v23",
    ):
        st.session_state["autenticado"] = False
        st.session_state.pop("usuario_logado", None)
        st.rerun()


# ==========================================================
# FUNÇÕES AUXILIARES
# ==========================================================

def sql_texto(valor):
    return str(valor).replace("'", "''")


def sql_in(coluna, valores):
    if not valores:
        return None

    valores_sql = ", ".join(
        f"'{sql_texto(v)}'"
        for v in valores
    )

    return f"{coluna} IN ({valores_sql})"


def montar_where(condicoes):
    condicoes_validas = [
        c for c in condicoes if c
    ]

    if not condicoes_validas:
        return ""

    return "WHERE " + " AND ".join(condicoes_validas)


def formatar_inteiro(valor):
    try:
        numero = int(float(valor or 0))
        texto = f"{numero:,}".replace(",", ".")

        # impede o st.metric de converter novamente
        return texto + "\u200b"

    except Exception:
        return "0\u200b"


def formatar_decimal(valor, casas=1):
    try:
        if valor is None:
            return "-"

        return (
            f"{float(valor):.{casas}f}"
            .replace(".", ",")
        )

    except Exception:
        return "-"


def formatar_percentual(valor, casas=1):
    try:
        if valor is None:
            return "-"

        return (
            f"{float(valor):.{casas}f}"
            .replace(".", ",")
            + "%"
        )

    except Exception:
        return "-"


def formatar_volume(valor):
    try:
        valor = float(valor or 0)
    except Exception:
        valor = 0

    sinal = "-" if valor < 0 else ""
    valor = abs(valor)

    if valor >= 1_000_000:
        return (
            sinal
            + f"{valor / 1_000_000:.2f}".replace(".", ",")
            + " mi m³"
        )

    if valor >= 1_000:
        return (
            sinal
            + f"{valor / 1_000:.1f}".replace(".", ",")
            + " mil m³"
        )

    return (
        sinal
        + f"{valor:,.0f}".replace(",", ".")
        + " m³"
    )


def formatar_moeda(valor):
    """Formata KPIs monetários no padrão brasileiro, sem abreviação de escala."""
    try:
        if valor is None:
            return "R$ 0,00"
        valor = float(valor)
        if math.isnan(valor):
            return "R$ 0,00"
    except Exception:
        return "R$ 0,00"

    sinal = "-" if valor < 0 else ""
    texto = f"{abs(valor):,.2f}"
    texto = texto.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{sinal}R$ {texto}"

def formatar_moeda_tabela(valor):
    """Formata moeda no padrão brasileiro apenas para exibição em tabelas."""
    try:
        if valor is None:
            return "R$ 0,00"
        valor = float(valor)
        if math.isnan(valor):
            return "R$ 0,00"
    except Exception:
        return str(valor) if valor is not None else "R$ 0,00"

    sinal = "-" if valor < 0 else ""
    texto = f"{abs(valor):,.2f}"
    texto = texto.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{sinal}R$ {texto}"


def exibir_dataframe(df, **kwargs):
    """Exibe cópia formatada sem alterar o DataFrame numérico usado nos cálculos/exportações."""
    df_exibicao = df.copy()

    for coluna in df_exibicao.columns:
        nome = str(coluna)
        if "(R$" in nome or nome.startswith("R$ "):
            df_exibicao[coluna] = df_exibicao[coluna].map(formatar_moeda_tabela)

    st.dataframe(df_exibicao, **kwargs)


def versao_base():
    arquivos = [ARQUIVO_PARQUET] + ARQUIVOS_FONTE
    mtimes = [
        os.path.getmtime(caminho)
        for caminho in arquivos
        if os.path.exists(caminho)
    ]
    return max(mtimes) if mtimes else 0


# ==========================================================
# DUCKDB
# ==========================================================

@st.cache_data(show_spinner=False, max_entries=500)
def consultar_df(sql, versao):
    con = duckdb.connect(database=":memory:")

    try:
        return con.execute(sql).fetchdf()
    finally:
        con.close()


@st.cache_data(show_spinner=False, max_entries=500)
def consultar_lista(sql, versao):
    con = duckdb.connect(database=":memory:")

    try:
        resultado = con.execute(sql).fetchall()

        return [
            linha[0]
            for linha in resultado
            if linha[0] is not None
            and str(linha[0]).strip() != ""
        ]

    finally:
        con.close()


@st.cache_data(show_spinner=False, max_entries=500)
def consultar_linha(sql, versao):
    con = duckdb.connect(database=":memory:")

    try:
        return con.execute(sql).fetchone()
    finally:
        con.close()


# ==========================================================
# IDENTIFICAR COLUNAS DAS BASES PARQUET
# ==========================================================

def identificar_colunas_parquet(caminho_arquivo):
    con = duckdb.connect(database=":memory:")
    caminho = caminho_arquivo.replace("'", "''")

    try:
        resultado = con.execute(
            f"""
            DESCRIBE
            SELECT *
            FROM read_parquet('{caminho}')
            LIMIT 1
            """
        ).fetchall()

        return [linha[0] for linha in resultado]

    finally:
        con.close()


def validar_estrutura_fontes():
    colunas_rmr = identificar_colunas_parquet(ARQUIVO_RMR)
    colunas_interior = identificar_colunas_parquet(ARQUIVO_INTERIOR)

    if set(colunas_rmr) != set(colunas_interior):
        somente_rmr = sorted(set(colunas_rmr) - set(colunas_interior))
        somente_interior = sorted(set(colunas_interior) - set(colunas_rmr))
        raise ValueError(
            "As bases RMR e Interior possuem estruturas diferentes. "
            f"Somente RMR: {somente_rmr[:10]}; "
            f"Somente Interior: {somente_interior[:10]}."
        )

    return colunas_rmr


# ==========================================================
# CONSTRUIR PARQUET
# ==========================================================

def construir_parquet():

    faltantes = [
        caminho
        for caminho in ARQUIVOS_FONTE
        if not os.path.exists(caminho)
    ]

    if faltantes:
        nomes = ", ".join(faltantes)
        raise FileNotFoundError(
            f"Base(s) Parquet não encontrada(s): {nomes}"
        )

    colunas = validar_estrutura_fontes()

    mapa = {
        str(c).upper(): c
        for c in colunas
    }

    def campo(nome, padrao="NULL"):
        real = mapa.get(nome.upper())

        if real:
            return '"' + str(real).replace('"', '""') + '"'

        return padrao

    IMOV_ID = campo("IMOV_ID")
    EXCLUIDO = campo("EXCLUIDO")

    SITUACAO_AGUA = campo(
        "SITUACAO_LIGACAO_AGUA"
    )

    SITUACAO_ESGOTO = campo(
        "SITUACAO_ESGOTO"
    )

    GNM = campo("GERENCIA_REGIONAL")
    LOCALIDADE = campo("LOCALIDADE")
    MUNICIPIO = campo("MUNICIPIO")
    BAIRRO = campo("BAIRRO")
    PERFIL = campo("PERFIL_IMOVEL")
    CATEGORIA = campo("CATEGORIA_IMOVEL")
    SUBCATEGORIA = campo("SUBCATEGORIA")

    ECONOMIAS = campo(
        "QUANTIDADE_ECONOMIAS"
    )

    ECON_RESIDENCIAL = campo(
        "QTD_ECON_RESIDENCIAL"
    )

    ECON_COMERCIAL = campo(
        "QTD_ECON_COMERCIAL"
    )

    ECON_PUBLICO = campo(
        "QTD_ECON_PUBLICO"
    )

    ECON_INDUSTRIAL = campo(
        "QTD_ECON_INDUSTRIAL"
    )

    CONSUMO_MEDIDO = campo(
        "CONSUMO_MEDIDO"
    )

    CONSUMO_FATURADO = campo(
        "CONSUMO_FATURADO"
    )

    CONSUMO_MEDIO = campo(
        "CONSUMO_MEDIO"
    )

    HIDROMETRO = campo(
        "HIDROMETRO_AGUA"
    )

    CAPACIDADE = campo(
        "CAPACIDADE_HIDROMETRO_AGUA"
    )

    DATA_HD = campo(
        "DATA_INSTAL_HIDROMETRO_AGUA"
    )

    ANO_HD = campo(
        "ANO_FABRIC_HIDROMETRO_AGUA"
    )

    ANOM_LEITURA = campo(
        "ANORMALIDADE_LEITURA"
    )

    ANOM_CONSUMO = campo(
        "ANORMALIDADE_CONSUMO"
    )

    SIGLA_ANOM = campo(
        "SIGLA_ANORMALIDADE_CONSUMO"
    )

    PERCENTUAL_ESGOTO = campo(
        "PERCENTUAL_ESGOTO"
    )

    PERCENTUAL_COLETA_ESGOTO = campo(
        "PERCENTUAL_COLETA_ESGOTO"
    )

    VALOR_AGUA = campo(
        "VALOR_AGUA"
    )

    VALOR_ESGOTO = campo(
        "VALOR_ESGOTO"
    )

    TARIFA_CONSUMO = campo(
        "TARIFA_CONSUMO"
    )

    SISTEMA_ESGOTO = campo(
        "SISTEMA_ESGOTO"
    )

    CONTA_FATURADA = campo(
        "CONTA_FATURADA"
    )

    caminho_rmr = ARQUIVO_RMR.replace(
        "'",
        "''"
    )

    caminho_interior = ARQUIVO_INTERIOR.replace(
        "'",
        "''"
    )

    caminho_parquet = ARQUIVO_PARQUET.replace(
        "'",
        "''"
    )

    con = duckdb.connect(database=":memory:")
    con.execute("SET memory_limit='1500MB'")
    con.execute("SET threads=2")
    con.execute("SET preserve_insertion_order=false")

    sql = f"""
    COPY (

        WITH origem AS (

            SELECT

                CASE
                    WHEN filename LIKE '%RMR.parquet' THEN 'RMR'
                    WHEN filename LIKE '%Interior.parquet' THEN 'INTERIOR'
                    ELSE 'NÃO IDENTIFICADA'
                END
                    AS BASE_ORIGEM,

                CAST({IMOV_ID} AS VARCHAR)
                    AS MATRICULA,

                UPPER(
                    TRIM(
                        CAST({EXCLUIDO} AS VARCHAR)
                    )
                )
                    AS EXCLUIDO,

                UPPER(
                    TRIM(
                        CAST({SITUACAO_AGUA} AS VARCHAR)
                    )
                )
                    AS SITUACAO,

                UPPER(
                    TRIM(
                        CAST({SITUACAO_ESGOTO} AS VARCHAR)
                    )
                )
                    AS SITUACAO_ESGOTO,

                CAST({GNM} AS VARCHAR)
                    AS GNM,

                CAST({LOCALIDADE} AS VARCHAR)
                    AS LOCALIDADE,

                CAST({MUNICIPIO} AS VARCHAR)
                    AS MUNICIPIO,

                CAST({BAIRRO} AS VARCHAR)
                    AS BAIRRO,

                CAST({PERFIL} AS VARCHAR)
                    AS PERFIL,

                CAST({CATEGORIA} AS VARCHAR)
                    AS CATEGORIA,

                CAST({SUBCATEGORIA} AS VARCHAR)
                    AS SUBCATEGORIA,

                TRY_CAST(
                    {ECONOMIAS}
                    AS DOUBLE
                )
                    AS ECONOMIAS_RAW,

                COALESCE(
                    TRY_CAST(
                        {ECON_RESIDENCIAL}
                        AS DOUBLE
                    ),
                    0
                )
                    AS ECON_RESIDENCIAL,

                COALESCE(
                    TRY_CAST(
                        {ECON_COMERCIAL}
                        AS DOUBLE
                    ),
                    0
                )
                    AS ECON_COMERCIAL,

                COALESCE(
                    TRY_CAST(
                        {ECON_PUBLICO}
                        AS DOUBLE
                    ),
                    0
                )
                    AS ECON_PUBLICO,

                COALESCE(
                    TRY_CAST(
                        {ECON_INDUSTRIAL}
                        AS DOUBLE
                    ),
                    0
                )
                    AS ECON_INDUSTRIAL,

                TRY_CAST(
                    {CONSUMO_MEDIDO}
                    AS DOUBLE
                )
                    AS CONSUMO_MEDIDO,

                TRY_CAST(
                    {CONSUMO_FATURADO}
                    AS DOUBLE
                )
                    AS CONSUMO_FATURADO,

                TRY_CAST(
                    {CONSUMO_MEDIO}
                    AS DOUBLE
                )
                    AS CONSUMO_MEDIO,

                CAST(
                    {HIDROMETRO}
                    AS VARCHAR
                )
                    AS HIDROMETRO,

                CAST(
                    {CAPACIDADE}
                    AS VARCHAR
                )
                    AS CAPACIDADE_HD,

                CAST(
                    {DATA_HD}
                    AS VARCHAR
                )
                    AS DATA_HD_RAW,

                CAST(
                    {ANO_HD}
                    AS VARCHAR
                )
                    AS ANO_HD_RAW,

                CAST(
                    {ANOM_LEITURA}
                    AS VARCHAR
                )
                    AS ANOM_LEITURA,

                CAST(
                    {ANOM_CONSUMO}
                    AS VARCHAR
                )
                    AS ANOM_CONSUMO,

                CAST(
                    {SIGLA_ANOM}
                    AS VARCHAR
                )
                    AS SIGLA_ANOM,

                TRY_CAST(
                    {PERCENTUAL_ESGOTO}
                    AS DOUBLE
                )
                    AS PERCENTUAL_ESGOTO,

                TRY_CAST(
                    {PERCENTUAL_COLETA_ESGOTO}
                    AS DOUBLE
                )
                    AS PERCENTUAL_COLETA_ESGOTO,

                CASE
                    WHEN STRPOS(
                        TRIM(CAST({VALOR_AGUA} AS VARCHAR)),
                        ','
                    ) > 0
                    THEN TRY_CAST(
                        REPLACE(
                            REPLACE(
                                TRIM(CAST({VALOR_AGUA} AS VARCHAR)),
                                '.',
                                ''
                            ),
                            ',',
                            '.'
                        )
                        AS DOUBLE
                    )
                    ELSE TRY_CAST(
                        TRIM(CAST({VALOR_AGUA} AS VARCHAR))
                        AS DOUBLE
                    )
                END
                    AS VALOR_AGUA,

                CASE
                    WHEN STRPOS(
                        TRIM(CAST({VALOR_ESGOTO} AS VARCHAR)),
                        ','
                    ) > 0
                    THEN TRY_CAST(
                        REPLACE(
                            REPLACE(
                                TRIM(CAST({VALOR_ESGOTO} AS VARCHAR)),
                                '.',
                                ''
                            ),
                            ',',
                            '.'
                        )
                        AS DOUBLE
                    )
                    ELSE TRY_CAST(
                        TRIM(CAST({VALOR_ESGOTO} AS VARCHAR))
                        AS DOUBLE
                    )
                END
                    AS VALOR_ESGOTO,

                CAST(
                    {TARIFA_CONSUMO}
                    AS VARCHAR
                )
                    AS TARIFA_CONSUMO,

                CAST(
                    {SISTEMA_ESGOTO}
                    AS VARCHAR
                )
                    AS SISTEMA_ESGOTO,

                CAST(
                    {CONTA_FATURADA}
                    AS VARCHAR
                )
                    AS CONTA_FATURADA

            FROM read_parquet(
                ['{caminho_rmr}', '{caminho_interior}'],
                union_by_name=true,
                filename=true
            )
        ),

        tratamento AS (

            SELECT
                *,

                CASE
                    WHEN ECONOMIAS_RAW IS NULL
                         OR ECONOMIAS_RAW <= 0
                    THEN 1
                    ELSE ECONOMIAS_RAW
                END
                    AS ECONOMIAS,

                COALESCE(

                    TRY_STRPTIME(
                        TRIM(
                            SPLIT_PART(
                                DATA_HD_RAW,
                                ',',
                                1
                            )
                        ),
                        '%d/%m/%Y'
                    ),

                    TRY_STRPTIME(
                        TRIM(DATA_HD_RAW),
                        '%d/%m/%Y, %H:%M'
                    ),

                    TRY_CAST(
                        DATA_HD_RAW
                        AS TIMESTAMP
                    )

                )
                    AS DATA_HD_TRATADA,

                CASE

                    WHEN REGEXP_MATCHES(
                        TRIM(
                            COALESCE(
                                ANO_HD_RAW,
                                ''
                            )
                        ),
                        '^[12]\\.[0-9]{{3}}$'
                    )

                    THEN TRY_CAST(
                        REPLACE(
                            TRIM(ANO_HD_RAW),
                            '.',
                            ''
                        )
                        AS INTEGER
                    )

                    WHEN REGEXP_MATCHES(
                        TRIM(
                            COALESCE(
                                ANO_HD_RAW,
                                ''
                            )
                        ),
                        '^[12][0-9]{{3}}(\\.0+)?$'
                    )

                    THEN TRY_CAST(
                        TRY_CAST(
                            ANO_HD_RAW
                            AS DOUBLE
                        )
                        AS INTEGER
                    )

                    ELSE NULL

                END
                    AS ANO_HD_TRATADO

            FROM origem
        ),

        metricas AS (

            SELECT
                *,

                CASE

                    WHEN DATA_HD_TRATADA IS NOT NULL

                    THEN DATE_DIFF(
                        'year',
                        CAST(
                            DATA_HD_TRATADA
                            AS DATE
                        ),
                        CURRENT_DATE
                    )

                    WHEN ANO_HD_TRATADO
                         BETWEEN 1970
                         AND YEAR(CURRENT_DATE)

                    THEN
                        YEAR(CURRENT_DATE)
                        -
                        ANO_HD_TRATADO

                    ELSE NULL

                END
                    AS IDADE_HD,

                CONSUMO_MEDIDO
                /
                NULLIF(
                    ECONOMIAS,
                    0
                )
                    AS MEDIDO_M3_ECON,

                CONSUMO_FATURADO
                /
                NULLIF(
                    ECONOMIAS,
                    0
                )
                    AS FATURADO_M3_ECON,

                CONSUMO_MEDIO
                /
                NULLIF(
                    ECONOMIAS,
                    0
                )
                    AS MEDIO_M3_ECON,

                CASE

                    WHEN CONSUMO_MEDIO IS NOT NULL
                         AND CONSUMO_MEDIDO IS NOT NULL

                    THEN GREATEST(
                        CONSUMO_MEDIO
                        -
                        CONSUMO_MEDIDO,
                        0
                    )

                    ELSE NULL

                END
                    AS GAP_MEDICAO_M3,

                CASE

                    WHEN CONSUMO_MEDIO IS NOT NULL
                         AND CONSUMO_MEDIDO IS NOT NULL

                    THEN GREATEST(
                        (
                            CONSUMO_MEDIO
                            -
                            CONSUMO_MEDIDO
                        )
                        /
                        NULLIF(
                            ECONOMIAS,
                            0
                        ),
                        0
                    )

                    ELSE NULL

                END
                    AS GAP_M3_ECON,

                CASE

                    WHEN CONSUMO_FATURADO IS NOT NULL
                         AND CONSUMO_MEDIDO IS NOT NULL

                    THEN
                        CONSUMO_FATURADO
                        -
                        CONSUMO_MEDIDO

                    ELSE NULL

                END
                    AS DIF_FATURADO_MEDIDO_M3,

                CASE

                    WHEN CONSUMO_MEDIO > 0
                         AND CONSUMO_MEDIDO IS NOT NULL

                    THEN
                        (
                            CONSUMO_MEDIO
                            -
                            CONSUMO_MEDIDO
                        )
                        /
                        CONSUMO_MEDIO
                        *
                        100

                    ELSE NULL

                END
                    AS QUEDA_PCT,

                UPPER(
                    TRIM(
                        COALESCE(
                            ANOM_LEITURA,
                            ''
                        )
                    )
                )
                    AS LEITURA_UPPER,

                UPPER(
                    TRIM(
                        COALESCE(
                            ANOM_CONSUMO,
                            ''
                        )
                    )
                )
                    AS CONSUMO_UPPER,

                UPPER(
                    TRIM(
                        COALESCE(
                            SIGLA_ANOM,
                            ''
                        )
                    )
                )
                    AS SIGLA_UPPER,

                UPPER(
                    TRIM(
                        COALESCE(
                            PERFIL,
                            ''
                        )
                    )
                )
                    AS PERFIL_UPPER,

                UPPER(
                    TRIM(
                        COALESCE(
                            CATEGORIA,
                            ''
                        )
                    )
                )
                    AS CATEGORIA_UPPER,

                CASE

                    WHEN COALESCE(
                        PERCENTUAL_ESGOTO,
                        0
                    ) > 0

                    THEN PERCENTUAL_ESGOTO

                    WHEN COALESCE(
                        PERCENTUAL_COLETA_ESGOTO,
                        0
                    ) > 0

                    THEN PERCENTUAL_COLETA_ESGOTO

                    ELSE 100

                END
                    AS PERC_ESGOTO_CALC

            FROM tratamento
        ),

        classificacao AS (

            SELECT
                *,

                CASE
                    WHEN COALESCE(
                        TRIM(HIDROMETRO),
                        ''
                    ) <> ''
                    THEN 'COM HIDRÔMETRO'
                    ELSE 'SEM HIDRÔMETRO'
                END
                    AS STATUS_HD,

                CASE
                    WHEN MEDIDO_M3_ECON IS NULL
                    THEN 'SEM CONSUMO'

                    WHEN MEDIDO_M3_ECON <= 10
                    THEN '≤ 10 m³/economia'

                    ELSE '> 10 m³/economia'
                END
                    AS FAIXA_10_M3,

                CASE
                    WHEN ECONOMIAS = 1
                    THEN '1'

                    WHEN ECONOMIAS BETWEEN 2 AND 4
                    THEN '2–4'

                    WHEN ECONOMIAS BETWEEN 5 AND 10
                    THEN '5–10'

                    WHEN ECONOMIAS BETWEEN 11 AND 20
                    THEN '11–20'

                    WHEN ECONOMIAS BETWEEN 21 AND 50
                    THEN '21–50'

                    ELSE '50+'
                END
                    AS FAIXA_ECONOMIAS,

                CASE
                    WHEN CONSUMO_MEDIDO IS NULL
                    THEN 'SEM CONSUMO'

                    WHEN MEDIDO_M3_ECON = 0
                    THEN '0'

                    WHEN MEDIDO_M3_ECON < 5
                    THEN '>0 a <5'

                    WHEN MEDIDO_M3_ECON < 10
                    THEN '5 a <10'

                    WHEN MEDIDO_M3_ECON < 15
                    THEN '10 a <15'

                    WHEN MEDIDO_M3_ECON < 20
                    THEN '15 a <20'

                    WHEN MEDIDO_M3_ECON < 30
                    THEN '20 a <30'

                    WHEN MEDIDO_M3_ECON < 50
                    THEN '30 a <50'

                    ELSE '50+'
                END
                    AS FAIXA_MEDIDO_ECON,

                CASE
                    WHEN CONSUMO_FATURADO IS NULL
                    THEN 'SEM CONSUMO'

                    WHEN FATURADO_M3_ECON = 0
                    THEN '0'

                    WHEN FATURADO_M3_ECON < 5
                    THEN '>0 a <5'

                    WHEN FATURADO_M3_ECON < 10
                    THEN '5 a <10'

                    WHEN FATURADO_M3_ECON < 15
                    THEN '10 a <15'

                    WHEN FATURADO_M3_ECON < 20
                    THEN '15 a <20'

                    WHEN FATURADO_M3_ECON < 30
                    THEN '20 a <30'

                    WHEN FATURADO_M3_ECON < 50
                    THEN '30 a <50'

                    ELSE '50+'
                END
                    AS FAIXA_FATURADO_ECON,

                CASE
                    WHEN IDADE_HD IS NULL
                    THEN 'SEM IDADE'

                    WHEN IDADE_HD < 5
                    THEN '<5'

                    WHEN IDADE_HD < 8
                    THEN '5–7'

                    WHEN IDADE_HD < 10
                    THEN '8–9'

                    WHEN IDADE_HD < 15
                    THEN '10–14'

                    ELSE '15+'
                END
                    AS FAIXA_IDADE_HD,

                CASE

                    WHEN LEITURA_UPPER LIKE '%QUEBR%'
                    THEN 'HD QUEBRADO'

                    WHEN LEITURA_UPPER LIKE '%RETIR%'
                         OR LEITURA_UPPER LIKE '%RET/NLOCAL%'
                    THEN 'HD RETIRADO / NÃO LOCALIZADO'

                    WHEN LEITURA_UPPER LIKE '%INVERT%'
                    THEN 'HD INVERTIDO'

                    WHEN LEITURA_UPPER LIKE '%EMBAC%'
                    THEN 'HD EMBAÇADO'

                    WHEN LEITURA_UPPER LIKE '%DIVERG%'
                    THEN 'HD DIVERGENTE'

                    WHEN LEITURA_UPPER LIKE '%S LACRE%'
                         OR LEITURA_UPPER LIKE '%SEM LACRE%'
                    THEN 'HD SEM LACRE'

                    ELSE NULL

                END
                    AS OCORRENCIA_HD,

                CASE

                    WHEN LEITURA_UPPER LIKE '%BYPASS%'
                    THEN 'BYPASS'

                    WHEN LEITURA_UPPER LIKE '%BOMB%LIG%RED%'
                    THEN 'BOMBA LIGADA À REDE'

                    WHEN LEITURA_UPPER LIKE '%FORNEC%INDEV%'
                    THEN 'FORNECIMENTO INDEVIDO'

                    WHEN LEITURA_UPPER LIKE '%S LACRE%'
                         OR LEITURA_UPPER LIKE '%SEM LACRE%'
                    THEN 'HD SEM LACRE'

                    WHEN LEITURA_UPPER LIKE '%DIVERG%'
                    THEN 'HD DIVERGENTE'

                    WHEN LEITURA_UPPER LIKE '%RETIR%'
                         OR LEITURA_UPPER LIKE '%N LOCAL%'
                    THEN 'HD RETIRADO / NÃO LOCALIZADO'

                    ELSE NULL

                END
                    AS OCORRENCIA_FISCAL

            FROM metricas
        )

        SELECT *
        FROM classificacao

    )

    TO '{caminho_parquet}'

    (
        FORMAT PARQUET,
        COMPRESSION ZSTD,
        ROW_GROUP_SIZE 100000
    )
    """

    try:
        con.execute(sql)
    finally:
        con.close()

    st.cache_data.clear()


# ==========================================================
# VERIFICAR / BAIXAR BASES
# ==========================================================

faltantes = [
    caminho
    for caminho in ARQUIVOS_FONTE
    if not os.path.exists(caminho)
]

if faltantes:
    try:
        with st.spinner("Baixando bases Pernambuco do armazenamento seguro..."):
            garantir_bases_locais()
    except Exception as erro:
        st.error(
            "Não foi possível baixar as bases Pernambuco do armazenamento seguro."
        )
        st.caption(f"Detalhe técnico: {erro}")
        st.stop()

    faltantes = [
        caminho
        for caminho in ARQUIVOS_FONTE
        if not os.path.exists(caminho)
    ]

if faltantes:
    st.error(
        "Não encontrei todas as bases necessárias para o painel: "
        + ", ".join(f"`{caminho}`" for caminho in faltantes)
    )
    st.caption(
        "No Streamlit Cloud, configure o bloco `[r2]` nos Secrets. "
        "Localmente, mantenha `data/RMR.parquet` e `data/Interior.parquet`."
    )
    st.stop()


precisa_processar = not os.path.exists(ARQUIVO_PARQUET)

if os.path.exists(ARQUIVO_PARQUET):
    origem_mais_recente = max(
        os.path.getmtime(caminho)
        for caminho in ARQUIVOS_FONTE
    )
    precisa_processar = (
        origem_mais_recente > os.path.getmtime(ARQUIVO_PARQUET)
    )


if precisa_processar:

    st.info(
        "Preparando a base Pernambuco para análise a partir de RMR + Interior. "
        "Esse processo ocorre apenas quando uma das bases é nova ou atualizada."
    )

    with st.spinner("Preparando base Pernambuco..."):

        inicio = time.time()
        construir_parquet()
        tempo = time.time() - inicio

    st.success(
        f"Base Pernambuco preparada em {tempo / 60:.1f} minuto(s)."
    )

    st.rerun()


VERSAO = f"{versao_base()}|{APP_VERSION}"

CAMINHO_PARQUET_SQL = ARQUIVO_PARQUET.replace(
    "'",
    "''"
)

BASE = f"read_parquet('{CAMINHO_PARQUET_SQL}')"


# ==========================================================
# NAVEGAÇÃO PRINCIPAL — V25
# ==========================================================

# A Visão Geral passa a ser a abertura padrão do painel.
# As áreas de Hidrômetros e Recuperação permanecem preservadas.
area_id = st.radio(
    "Área",
    ["visao_geral", "hidrometros", "recuperacao"],
    horizontal=True,
    label_visibility="collapsed",
    format_func=lambda opcao: (
        "🌎 VISÃO GERAL"
        if opcao == "visao_geral"
        else (
            "💧 HIDRÔMETROS"
            if opcao == "hidrometros"
            else "🔎 RECUPERAÇÃO DE LIGAÇÕES"
        )
    ),
    key="area_principal_v25",
)

if area_id == "visao_geral":
    area = "🌎 VISÃO GERAL"
elif area_id == "hidrometros":
    area = "💧 HIDRÔMETROS"
else:
    area = "🔎 RECUPERAÇÃO DE LIGAÇÕES"


# ==========================================================
# PARÂMETROS / STATUS DA BASE
# ==========================================================

st.sidebar.success(
    "✅ Base Pernambuco pronta para análise"
)

st.sidebar.caption(
    f"Versão do painel: {APP_VERSION}"
)

st.sidebar.caption(
    "Selecione uma ou mais opções em cada filtro. "
    "Sem seleção = todos."
)


if st.sidebar.button(
    "🔄 Atualizar base Pernambuco",
    use_container_width=True,
):

    with st.spinner(
        "Atualizando RMR + Interior..."
    ):
        # No Streamlit Cloud, força novo download do R2.
        # Em ambiente local sem Secrets R2, apenas reconstrói com os arquivos locais.
        if obter_config_r2():
            garantir_bases_locais(forcar=True)
        construir_parquet()

    st.success(
        "Base Pernambuco atualizada."
    )

    st.rerun()


# A Visão Geral é factual e não depende das premissas de priorização.
# Mantemos os valores-padrão em memória para preservar as funções/CTEs existentes,
# mas escondemos esses controles na abertura macro.
if area_id != "visao_geral":

    st.sidebar.divider()
    st.sidebar.header("⚙️ Parâmetros")

    minimo_economia = st.sidebar.number_input(
        "Consumo mínimo por economia (m³)",
        min_value=1.0,
        max_value=50.0,
        value=10.0,
        step=1.0,
    )

    idade_prioritaria = st.sidebar.number_input(
        "Idade para priorizar troca (anos)",
        min_value=1,
        max_value=30,
        value=10,
    )

    queda_prioritaria = st.sidebar.slider(
        "Queda de consumo (%)",
        min_value=10,
        max_value=90,
        value=30,
        step=5,
    )

    fator_cortado = st.sidebar.slider(
        "Faturamento do cortado (% da água)",
        min_value=0,
        max_value=100,
        value=30,
        step=5,
        help=(
            "Premissa configurável para estimar o "
            "faturamento atual das ligações cortadas."
        ),
    )

else:
    minimo_economia = 10.0
    idade_prioritaria = 10
    queda_prioritaria = 30
    fator_cortado = 30


# ==========================================================
# TÍTULO DINÂMICO
# ==========================================================

if area_id == "visao_geral":
    titulo_area = "VISÃO GERAL | PERNAMBUCO"
    subtitulo_area = (
        "Panorama macro da base comercial, situação das ligações, "
        "consumo, faturamento e parque de hidrômetros"
    )
elif area_id == "hidrometros":
    titulo_area = "GESTÃO DE HIDRÔMETROS"
    subtitulo_area = (
        "Priorização de trocas, potencial de volume e "
        "ganho estimado de faturamento"
    )
else:
    titulo_area = "RECUPERAÇÃO DE LIGAÇÕES"
    subtitulo_area = (
        "Identificação de inativos, indícios de uso e "
        "potencial de recuperação de faturamento"
    )

st.markdown(
    f"""
    <div style="margin: 0 0 0.35rem 0;">
        <h1 style="margin:0; padding:0; font-size:3rem; line-height:1.15;">
            {titulo_area}
        </h1>
    </div>
    """,
    unsafe_allow_html=True,
)

st.caption("ENORSUL | PERNAMBUCO")
st.markdown(f"**{subtitulo_area}**")


# ==========================================================
# FILTROS GERAIS
# ==========================================================

st.sidebar.divider()
st.sidebar.header("🔎 Filtros Gerais")

condicoes_gerais = []


# ==========================================================
# BASE DE ORIGEM
# ==========================================================

bases_origem = consultar_lista(
    f"""
    SELECT DISTINCT BASE_ORIGEM
    FROM {BASE}
    WHERE
        BASE_ORIGEM IS NOT NULL
        AND TRIM(BASE_ORIGEM) <> ''
    ORDER BY BASE_ORIGEM
    """,
    VERSAO,
)


filtro_base_origem = st.sidebar.multiselect(
    "Base de Origem",
    bases_origem,
)


condicao = sql_in(
    "BASE_ORIGEM",
    filtro_base_origem,
)

if condicao:
    condicoes_gerais.append(condicao)


# ==========================================================
# GNM
# ==========================================================

gnms = consultar_lista(
    f"""
    SELECT DISTINCT GNM
    FROM {BASE}
    WHERE
        GNM IS NOT NULL
        AND TRIM(GNM) <> ''
    ORDER BY GNM
    """,
    VERSAO,
)


filtro_gnm = st.sidebar.multiselect(
    "GNM",
    gnms,
)


condicao = sql_in(
    "GNM",
    filtro_gnm,
)

if condicao:
    condicoes_gerais.append(condicao)


# ==========================================================
# LOCALIDADE
# ==========================================================

# Na Visão Geral, Localidade não é filtro executivo.
# Nas áreas detalhadas, a lógica original é preservada.
filtro_localidade = []

if area_id != "visao_geral":

    where_opcoes = montar_where(
        condicoes_gerais
    )

    localidades = consultar_lista(
        f"""
        SELECT DISTINCT LOCALIDADE
        FROM {BASE}
        {where_opcoes}
        {"AND" if where_opcoes else "WHERE"}
            LOCALIDADE IS NOT NULL
            AND TRIM(LOCALIDADE) <> ''
        ORDER BY LOCALIDADE
        """,
        VERSAO,
    )

    filtro_localidade = st.sidebar.multiselect(
        "Localidade",
        localidades,
    )

    condicao = sql_in(
        "LOCALIDADE",
        filtro_localidade,
    )

    if condicao:
        condicoes_gerais.append(condicao)


# ==========================================================
# MUNICÍPIO
# ==========================================================

where_opcoes = montar_where(
    condicoes_gerais
)


municipios = consultar_lista(
    f"""
    SELECT DISTINCT MUNICIPIO
    FROM {BASE}
    {where_opcoes}
    {"AND" if where_opcoes else "WHERE"}
        MUNICIPIO IS NOT NULL
        AND TRIM(MUNICIPIO) <> ''
    ORDER BY MUNICIPIO
    """,
    VERSAO,
)


filtro_municipio = st.sidebar.multiselect(
    "Município",
    municipios,
)


condicao = sql_in(
    "MUNICIPIO",
    filtro_municipio,
)

if condicao:
    condicoes_gerais.append(condicao)


# ==========================================================
# BAIRRO
# ==========================================================

# Bairro permanece disponível somente nas análises operacionais detalhadas.
filtro_bairro = []

if area_id != "visao_geral":

    where_opcoes = montar_where(
        condicoes_gerais
    )

    bairros = consultar_lista(
        f"""
        SELECT DISTINCT BAIRRO
        FROM {BASE}
        {where_opcoes}
        {"AND" if where_opcoes else "WHERE"}
            BAIRRO IS NOT NULL
            AND TRIM(BAIRRO) <> ''
        ORDER BY BAIRRO
        """,
        VERSAO,
    )

    filtro_bairro = st.sidebar.multiselect(
        "Bairro",
        bairros,
    )

    condicao = sql_in(
        "BAIRRO",
        filtro_bairro,
    )

    if condicao:
        condicoes_gerais.append(condicao)


# ==========================================================
# PERFIL
# ==========================================================

where_opcoes = montar_where(
    condicoes_gerais
)


perfis = consultar_lista(
    f"""
    SELECT DISTINCT PERFIL
    FROM {BASE}
    {where_opcoes}
    {"AND" if where_opcoes else "WHERE"}
        PERFIL IS NOT NULL
        AND TRIM(PERFIL) <> ''
    ORDER BY PERFIL
    """,
    VERSAO,
)


filtro_perfil = st.sidebar.multiselect(
    "Perfil",
    perfis,
)


condicao = sql_in(
    "PERFIL",
    filtro_perfil,
)

if condicao:
    condicoes_gerais.append(condicao)


# ==========================================================
# CATEGORIA
# ==========================================================

where_opcoes = montar_where(
    condicoes_gerais
)


categorias = consultar_lista(
    f"""
    SELECT DISTINCT CATEGORIA
    FROM {BASE}
    {where_opcoes}
    {"AND" if where_opcoes else "WHERE"}
        CATEGORIA IS NOT NULL
        AND TRIM(CATEGORIA) <> ''
    ORDER BY CATEGORIA
    """,
    VERSAO,
)


filtro_categoria = st.sidebar.multiselect(
    "Categoria",
    categorias,
)


condicao = sql_in(
    "CATEGORIA",
    filtro_categoria,
)

if condicao:
    condicoes_gerais.append(condicao)


# ==========================================================
# FUNÇÃO SQL - TARIFA DE ÁGUA
# ==========================================================
#
# Estrutura tarifária COMPESA / Resolução ARPE 289/2025.
#
# O consumo é dividido pela quantidade total de economias.
# Em matrícula com múltiplas categorias, cada grupo de
# economias recebe a tarifa da sua categoria.
#
# Quando os quantitativos por categoria não estão disponíveis,
# a categoria geral da matrícula é utilizada como fallback.
#
# ==========================================================

def tarifa_residencial_sql(consumo_economia):

    return f"""
    (
        CASE

            WHEN {consumo_economia} IS NULL
                 OR {consumo_economia} <= 0
            THEN 61.77

            WHEN {consumo_economia} <= 10
            THEN 61.77

            WHEN {consumo_economia} <= 20
            THEN
                61.77
                +
                ({consumo_economia} - 10)
                * 7.09

            WHEN {consumo_economia} <= 30
            THEN
                61.77
                +
                10 * 7.09
                +
                ({consumo_economia} - 20)
                * 8.42

            WHEN {consumo_economia} <= 50
            THEN
                61.77
                +
                10 * 7.09
                +
                10 * 8.42
                +
                ({consumo_economia} - 30)
                * 11.59

            WHEN {consumo_economia} <= 90
            THEN
                61.77
                +
                10 * 7.09
                +
                10 * 8.42
                +
                20 * 11.59
                +
                ({consumo_economia} - 50)
                * 13.74

            ELSE
                61.77
                +
                10 * 7.09
                +
                10 * 8.42
                +
                20 * 11.59
                +
                40 * 13.74
                +
                ({consumo_economia} - 90)
                * 26.40

        END
    )
    """


def tarifa_social_sql(consumo_economia):

    return f"""
    (
        CASE

            WHEN {consumo_economia} IS NULL
                 OR {consumo_economia} <= 15
            THEN 27.50

            WHEN {consumo_economia} <= 20
            THEN
                27.50
                +
                ({consumo_economia} - 15)
                * 7.09

            WHEN {consumo_economia} <= 30
            THEN
                27.50
                +
                5 * 7.09
                +
                ({consumo_economia} - 20)
                * 8.42

            WHEN {consumo_economia} <= 50
            THEN
                27.50
                +
                5 * 7.09
                +
                10 * 8.42
                +
                ({consumo_economia} - 30)
                * 11.59

            WHEN {consumo_economia} <= 90
            THEN
                27.50
                +
                5 * 7.09
                +
                10 * 8.42
                +
                20 * 11.59
                +
                ({consumo_economia} - 50)
                * 13.74

            ELSE
                27.50
                +
                5 * 7.09
                +
                10 * 8.42
                +
                20 * 11.59
                +
                40 * 13.74
                +
                ({consumo_economia} - 90)
                * 26.40

        END
    )
    """


def tarifa_vulneravel_sql(consumo_economia):

    return f"""
    (
        CASE

            WHEN {consumo_economia} IS NULL
                 OR {consumo_economia} <= 10
            THEN 10.39

            WHEN {consumo_economia} <= 20
            THEN
                10.39
                +
                ({consumo_economia} - 10)
                * 7.09

            WHEN {consumo_economia} <= 30
            THEN
                10.39
                +
                10 * 7.09
                +
                ({consumo_economia} - 20)
                * 8.42

            WHEN {consumo_economia} <= 50
            THEN
                10.39
                +
                10 * 7.09
                +
                10 * 8.42
                +
                ({consumo_economia} - 30)
                * 11.59

            WHEN {consumo_economia} <= 90
            THEN
                10.39
                +
                10 * 7.09
                +
                10 * 8.42
                +
                20 * 11.59
                +
                ({consumo_economia} - 50)
                * 13.74

            ELSE
                10.39
                +
                10 * 7.09
                +
                10 * 8.42
                +
                20 * 11.59
                +
                40 * 13.74
                +
                ({consumo_economia} - 90)
                * 26.40

        END
    )
    """


def tarifa_comercial_sql(consumo_economia):

    return f"""
    (
        CASE

            WHEN {consumo_economia} IS NULL
                 OR {consumo_economia} <= 10
            THEN 90.88

            ELSE
                90.88
                +
                ({consumo_economia} - 10)
                * 18.02

        END
    )
    """


def tarifa_industrial_sql(consumo_economia):

    return f"""
    (
        CASE

            WHEN {consumo_economia} IS NULL
                 OR {consumo_economia} <= 10
            THEN 113.88

            ELSE
                113.88
                +
                ({consumo_economia} - 10)
                * 24.14

        END
    )
    """


def tarifa_publico_sql(consumo_economia):

    return f"""
    (
        CASE

            WHEN {consumo_economia} IS NULL
                 OR {consumo_economia} <= 10
            THEN 87.84

            ELSE
                87.84
                +
                ({consumo_economia} - 10)
                * 13.32

        END
    )
    """


# ==========================================================
# TARIFA TOTAL POR MATRÍCULA
# ==========================================================

def tarifa_agua_sql(consumo_total):

    consumo_economia = (
        f"({consumo_total}) / NULLIF(ECONOMIAS, 0)"
    )

    residencial = tarifa_residencial_sql(
        consumo_economia
    )

    social = tarifa_social_sql(
        consumo_economia
    )

    vulneravel = tarifa_vulneravel_sql(
        consumo_economia
    )

    comercial = tarifa_comercial_sql(
        consumo_economia
    )

    industrial = tarifa_industrial_sql(
        consumo_economia
    )

    publico = tarifa_publico_sql(
        consumo_economia
    )

    return f"""
    (
        CASE

            -- TARIFA SOCIAL PERNAMBUCANA
            WHEN PERFIL_UPPER LIKE '%SOCIAL%'
                 AND PERFIL_UPPER NOT LIKE '%VULNER%'
            THEN
                ECONOMIAS
                *
                {social}

            -- TARIFA DE VULNERÁVEIS
            WHEN PERFIL_UPPER LIKE '%VULNER%'
            THEN
                ECONOMIAS
                *
                {vulneravel}

            -- QUANTITATIVO DE ECONOMIAS POR CATEGORIA
            WHEN
                COALESCE(ECON_RESIDENCIAL, 0)
                +
                COALESCE(ECON_COMERCIAL, 0)
                +
                COALESCE(ECON_PUBLICO, 0)
                +
                COALESCE(ECON_INDUSTRIAL, 0)
                > 0

            THEN

                COALESCE(
                    ECON_RESIDENCIAL,
                    0
                )
                *
                {residencial}

                +

                COALESCE(
                    ECON_COMERCIAL,
                    0
                )
                *
                {comercial}

                +

                COALESCE(
                    ECON_PUBLICO,
                    0
                )
                *
                {publico}

                +

                COALESCE(
                    ECON_INDUSTRIAL,
                    0
                )
                *
                {industrial}

            -- FALLBACK PELA CATEGORIA GERAL
            WHEN CATEGORIA_UPPER LIKE '%COMERCIAL%'
            THEN
                ECONOMIAS
                *
                {comercial}

            WHEN CATEGORIA_UPPER LIKE '%INDUSTR%'
            THEN
                ECONOMIAS
                *
                {industrial}

            WHEN CATEGORIA_UPPER LIKE '%PUBLIC%'
            THEN
                ECONOMIAS
                *
                {publico}

            ELSE
                ECONOMIAS
                *
                {residencial}

        END
    )
    """


# ==========================================================
# COMPONENTES DO SCORE HIDROMETRIA
# ==========================================================

POTENCIAL_VOLUME = f"""
LEAST(
    40,

    CASE
        WHEN QUEDA_PCT >= 60 THEN 15
        WHEN QUEDA_PCT >= {queda_prioritaria} THEN 10
        ELSE 0
    END

    +

    CASE
        WHEN GAP_M3_ECON >= 10 THEN 15
        WHEN GAP_M3_ECON >= 5 THEN 8
        ELSE 0
    END

    +

    CASE
        WHEN MEDIO_M3_ECON > {minimo_economia}
        THEN 5
        ELSE 0
    END

    +

    CASE
        WHEN ECONOMIAS >= 5
        THEN 5
        ELSE 0
    END
)
"""


RISCO_HD = f"""
LEAST(
    40,

    CASE
        WHEN OCORRENCIA_HD = 'HD QUEBRADO'
        THEN 35

        WHEN OCORRENCIA_HD = 'HD RETIRADO / NÃO LOCALIZADO'
        THEN 35

        WHEN OCORRENCIA_HD = 'HD INVERTIDO'
        THEN 28

        WHEN OCORRENCIA_HD = 'HD EMBAÇADO'
        THEN 24

        WHEN OCORRENCIA_HD = 'HD DIVERGENTE'
        THEN 12

        WHEN OCORRENCIA_HD = 'HD SEM LACRE'
        THEN 5

        ELSE 0
    END

    +

    CASE
        WHEN IDADE_HD >= 15
        THEN 10

        WHEN IDADE_HD >= {idade_prioritaria}
        THEN 5

        ELSE 0
    END
)
"""


RISCO_COMERCIAL = """
LEAST(
    20,

    GREATEST(

        CASE
            WHEN CONSUMO_UPPER LIKE '%BAIX%CONSUM%'
                 OR SIGLA_UPPER = 'BC'
            THEN 12
            ELSE 0
        END,

        CASE
            WHEN CONSUMO_UPPER LIKE '%LEIT N INFOR%'
                 OR SIGLA_UPPER = 'FL'
            THEN 10
            ELSE 0
        END,

        CASE
            WHEN CONSUMO_UPPER LIKE '%LEIT MN PROJ%'
                 OR SIGLA_UPPER = 'LP'
                 OR CONSUMO_UPPER LIKE '%LEIT MN ANT%'
                 OR SIGLA_UPPER = 'LM'
            THEN 10
            ELSE 0
        END,

        CASE
            WHEN LEITURA_UPPER LIKE '%RECOR%TAXA%MIN%'
            THEN 8
            ELSE 0
        END,

        CASE
            WHEN SIGLA_UPPER = 'MF'
            THEN 5
            ELSE 0
        END
    )
)
"""


# ==========================================================
# CTE HIDROMETRIA + SIMULAÇÃO FINANCEIRA
# ==========================================================

def cte_hidrometria():

    tarifa_atual = tarifa_agua_sql(
        "COALESCE(CONSUMO_FATURADO, CONSUMO_MEDIDO, 0)"
    )

    tarifa_potencial = tarifa_agua_sql(
        "COALESCE(CONSUMO_MEDIO, CONSUMO_FATURADO, CONSUMO_MEDIDO, 0)"
    )

    return f"""
    WITH componentes AS (

        SELECT
            *,

            {POTENCIAL_VOLUME}
                AS POTENCIAL_VOLUME,

            {RISCO_HD}
                AS RISCO_HD,

            {RISCO_COMERCIAL}
                AS RISCO_COMERCIAL

        FROM {BASE}

        WHERE
            EXCLUIDO = 'NAO'
            AND SITUACAO = 'LIGADO'
            AND STATUS_HD = 'COM HIDRÔMETRO'
    ),

    financeiro_base AS (

        SELECT
            *,

            {tarifa_atual}
                AS FAT_ATUAL_AGUA_SIM,

            {tarifa_potencial}
                AS FAT_POTENCIAL_AGUA_SIM,

            CASE
                WHEN SITUACAO_ESGOTO IN (
                    'LIGADO',
                    'FACTIVEL FATURAVEL',
                    'FACTÍVEL FATURÁVEL'
                )
                THEN 1
                ELSE 0
            END
                AS ESGOTO_FATURAVEL

        FROM componentes
    ),

    financeiro AS (

        SELECT
            *,

            CASE
                WHEN ESGOTO_FATURAVEL = 1
                THEN
                    FAT_ATUAL_AGUA_SIM
                    *
                    (
                        PERC_ESGOTO_CALC
                        /
                        100.0
                    )
                ELSE 0
            END
                AS FAT_ATUAL_ESGOTO_SIM,

            CASE
                WHEN ESGOTO_FATURAVEL = 1
                THEN
                    FAT_POTENCIAL_AGUA_SIM
                    *
                    (
                        PERC_ESGOTO_CALC
                        /
                        100.0
                    )
                ELSE 0
            END
                AS FAT_POTENCIAL_ESGOTO_SIM,

            COALESCE(
                VALOR_AGUA,
                0
            )
            +
            COALESCE(
                VALOR_ESGOTO,
                0
            )
                AS FAT_ATUAL_INFORMADO

        FROM financeiro_base
    ),

    score AS (

        SELECT
            *,

            -- Score de recuperação: mede somente oportunidade de volume/faturamento.
            -- Risco técnico do hidrômetro NÃO entra neste score.
            CASE
                WHEN COALESCE(GAP_MEDICAO_M3, 0) <= 0
                THEN 0
                ELSE LEAST(
                    60,
                    POTENCIAL_VOLUME
                    +
                    RISCO_COMERCIAL
                )
            END
                AS SCORE_RECUPERACAO,

            -- Score técnico: condição física/idade do hidrômetro.
            RISCO_HD
                AS SCORE_TECNICO,

            FAT_ATUAL_AGUA_SIM
            +
            FAT_ATUAL_ESGOTO_SIM
                AS FAT_ATUAL_TOTAL_SIM,

            FAT_POTENCIAL_AGUA_SIM
            +
            FAT_POTENCIAL_ESGOTO_SIM
                AS FAT_POTENCIAL_TOTAL_SIM

        FROM financeiro
    ),

    hidrometria_base AS (

        SELECT
            *,

            GREATEST(
                FAT_POTENCIAL_AGUA_SIM
                -
                FAT_ATUAL_AGUA_SIM,
                0
            )
                AS GANHO_AGUA_ESTIMADO,

            GREATEST(
                FAT_POTENCIAL_ESGOTO_SIM
                -
                FAT_ATUAL_ESGOTO_SIM,
                0
            )
                AS GANHO_ESGOTO_ESTIMADO,

            GREATEST(
                FAT_POTENCIAL_TOTAL_SIM
                -
                FAT_ATUAL_TOTAL_SIM,
                0
            )
                AS GANHO_TOTAL_ESTIMADO

        FROM score
    ),

    hidrometria AS (

        SELECT
            *,

            CASE
                WHEN COALESCE(GAP_MEDICAO_M3, 0) <= 0
                THEN 'SEM POTENCIAL DE VOLUME'

                WHEN QUEDA_PCT >= 60
                THEN 'QUEDA DE CONSUMO ≥ 60%'

                WHEN GAP_M3_ECON >= 10
                THEN 'ALTO POTENCIAL POR ECONOMIA'

                WHEN GAP_MEDICAO_M3 >= 20
                THEN 'ALTO POTENCIAL DE VOLUME'

                WHEN RISCO_COMERCIAL >= 10
                THEN 'RISCO DE PERDA'

                WHEN COALESCE(GANHO_TOTAL_ESTIMADO, 0) > 0
                THEN 'POTENCIAL FINANCEIRO IDENTIFICADO'

                ELSE 'BAIXO POTENCIAL DE RECUPERAÇÃO'
            END
                AS MOTIVO_RECUPERACAO_HD,

            CASE
                WHEN OCORRENCIA_HD = 'HD QUEBRADO'
                THEN 'HD QUEBRADO'

                WHEN OCORRENCIA_HD = 'HD RETIRADO / NÃO LOCALIZADO'
                THEN 'HD RETIRADO / NÃO LOCALIZADO'

                WHEN OCORRENCIA_HD = 'HD INVERTIDO'
                THEN 'HD INVERTIDO'

                WHEN OCORRENCIA_HD = 'HD EMBAÇADO'
                THEN 'HD EMBAÇADO'

                WHEN OCORRENCIA_HD = 'HD DIVERGENTE'
                THEN 'HD DIVERGENTE'

                WHEN OCORRENCIA_HD = 'HD SEM LACRE'
                THEN 'HD SEM LACRE'

                WHEN IDADE_HD >= 15
                THEN 'HIDRÔMETRO COM 15+ ANOS'

                WHEN IDADE_HD >= {idade_prioritaria}
                THEN 'IDADE DO HIDRÔMETRO'

                ELSE 'SEM PRIORIDADE TÉCNICA'
            END
                AS MOTIVO_TECNICO,

            CASE
                WHEN COALESCE(GAP_MEDICAO_M3, 0) <= 0
                THEN 'SEM POTENCIAL'

                WHEN SCORE_RECUPERACAO >= 45
                THEN 'MUITO ALTA'

                WHEN SCORE_RECUPERACAO >= 30
                THEN 'ALTA'

                WHEN SCORE_RECUPERACAO >= 15
                THEN 'MÉDIA'

                ELSE 'BAIXA'
            END
                AS PRIORIDADE_RECUPERACAO,

            CASE
                WHEN OCORRENCIA_HD IN (
                    'HD QUEBRADO',
                    'HD RETIRADO / NÃO LOCALIZADO'
                )
                THEN 'MUITO ALTA'

                WHEN OCORRENCIA_HD IN (
                    'HD INVERTIDO',
                    'HD EMBAÇADO'
                )
                THEN 'ALTA'

                WHEN SCORE_TECNICO >= 25
                THEN 'ALTA'

                WHEN SCORE_TECNICO >= 15
                THEN 'MÉDIA'

                WHEN SCORE_TECNICO > 0
                THEN 'BAIXA'

                ELSE 'SEM PRIORIDADE'
            END
                AS PRIORIDADE_TECNICA,

            -- aliases mantidos para preservar as telas e consultas existentes
            SCORE_RECUPERACAO
                AS SCORE_FINAL,

            MOTIVO_RECUPERACAO_HD
                AS MOTIVO_PRIORIDADE,

            PRIORIDADE_RECUPERACAO
                AS PRIORIDADE_HD

        FROM hidrometria_base
    )
    """


# ==========================================================
# CTE RECUPERAÇÃO DE LIGAÇÕES
# ==========================================================

def cte_recuperacao():

    tarifa_referencia = tarifa_agua_sql(
        """
        COALESCE(
            NULLIF(CONSUMO_MEDIO, 0),
            NULLIF(CONSUMO_MEDIDO, 0),
            NULLIF(CONSUMO_FATURADO, 0),
            0
        )
        """
    )

    tarifa_atual_cheia = tarifa_agua_sql(
        """
        COALESCE(
            NULLIF(CONSUMO_FATURADO, 0),
            NULLIF(CONSUMO_MEDIDO, 0),
            NULLIF(CONSUMO_MEDIO, 0),
            0
        )
        """
    )

    return f"""
    WITH universo AS (

        SELECT
            *,

            COALESCE(
                NULLIF(
                    CONSUMO_MEDIO,
                    0
                ),
                NULLIF(
                    CONSUMO_MEDIDO,
                    0
                ),
                NULLIF(
                    CONSUMO_FATURADO,
                    0
                ),
                0
            )
                AS CONSUMO_REFERENCIA_REC

        FROM {BASE}

        WHERE
            EXCLUIDO = 'NAO'
            AND
            (
                COALESCE(SITUACAO, '') <> 'LIGADO'
                OR OCORRENCIA_FISCAL IS NOT NULL
            )
    ),

    faturamento_base AS (

        SELECT
            *,

            CASE
                WHEN COALESCE(CONSUMO_REFERENCIA_REC, 0) > 0
                THEN {tarifa_referencia}
                ELSE 0
            END
                AS FAT_REGULAR_AGUA,

            {tarifa_atual_cheia}
                AS FAT_CHEIA_ATUAL_AGUA,

            CASE

                WHEN SITUACAO = 'CORTADO'
                THEN {fator_cortado / 100.0}

                WHEN SITUACAO = 'LIGADO'
                THEN 1.0

                ELSE 0.0

            END
                AS FATOR_SITUACAO_AGUA,

            CASE

                WHEN SITUACAO_ESGOTO IN (
                    'LIGADO',
                    'FACTIVEL FATURAVEL',
                    'FACTÍVEL FATURÁVEL'
                )
                THEN 1

                ELSE 0

            END
                AS ESGOTO_FATURAVEL

        FROM universo
    ),

    faturamento AS (

        SELECT
            *,

            FAT_CHEIA_ATUAL_AGUA
            *
            FATOR_SITUACAO_AGUA
                AS FAT_ATUAL_AGUA_SIM,

            CASE
                WHEN ESGOTO_FATURAVEL = 1
                THEN
                    FAT_REGULAR_AGUA
                    *
                    (
                        PERC_ESGOTO_CALC
                        /
                        100.0
                    )
                ELSE 0
            END
                AS FAT_REGULAR_ESGOTO,

            CASE
                WHEN ESGOTO_FATURAVEL = 1
                THEN
                    FAT_CHEIA_ATUAL_AGUA
                    *
                    (
                        PERC_ESGOTO_CALC
                        /
                        100.0
                    )
                ELSE 0
            END
                AS FAT_ATUAL_ESGOTO_SIM,

            COALESCE(
                VALOR_AGUA,
                0
            )
            +
            COALESCE(
                VALOR_ESGOTO,
                0
            )
                AS FAT_ATUAL_INFORMADO

        FROM faturamento_base
    ),

    componentes AS (

        SELECT
            *,

            FAT_ATUAL_AGUA_SIM
            +
            FAT_ATUAL_ESGOTO_SIM
                AS FAT_ATUAL_TOTAL_SIM,

            FAT_REGULAR_AGUA
            +
            FAT_REGULAR_ESGOTO
                AS FAT_REGULAR_TOTAL_SIM,

            GREATEST(
                FAT_REGULAR_AGUA
                +
                FAT_REGULAR_ESGOTO
                -
                (
                    FAT_ATUAL_AGUA_SIM
                    +
                    FAT_ATUAL_ESGOTO_SIM
                ),
                0
            )
                AS INCREMENTO_ESTIMADO_RS,

            CASE

                WHEN COALESCE(
                    SITUACAO,
                    ''
                ) <> 'LIGADO'

                THEN GREATEST(
                    CONSUMO_REFERENCIA_REC
                    -
                    COALESCE(
                        CONSUMO_FATURADO,
                        0
                    )
                    *
                    FATOR_SITUACAO_AGUA,
                    0
                )

                ELSE 0

            END
                AS INCREMENTO_ESTIMADO_M3,

            GREATEST(

                CASE
                    WHEN OCORRENCIA_FISCAL = 'BYPASS'
                    THEN 60
                    ELSE 0
                END,

                CASE
                    WHEN OCORRENCIA_FISCAL = 'BOMBA LIGADA À REDE'
                    THEN 55
                    ELSE 0
                END,

                CASE
                    WHEN OCORRENCIA_FISCAL = 'FORNECIMENTO INDEVIDO'
                    THEN 55
                    ELSE 0
                END,

                CASE
                    WHEN OCORRENCIA_FISCAL = 'HD SEM LACRE'
                    THEN 30
                    ELSE 0
                END,

                CASE
                    WHEN OCORRENCIA_FISCAL = 'HD DIVERGENTE'
                    THEN 25
                    ELSE 0
                END,

                CASE
                    WHEN OCORRENCIA_HD = 'HD RETIRADO / NÃO LOCALIZADO'
                    THEN 20
                    ELSE 0
                END

            )
                AS RISCO_OCORRENCIA_FISCAL,

            CASE
                WHEN COALESCE(
                    SITUACAO,
                    ''
                ) <> 'LIGADO'
                AND COALESCE(
                    CONSUMO_MEDIDO,
                    0
                ) > 0
                THEN 35
                ELSE 0
            END
                AS RISCO_CONSUMO_INATIVO,

            CASE
                WHEN COALESCE(
                    SITUACAO,
                    ''
                ) <> 'LIGADO'
                AND COALESCE(
                    CONSUMO_FATURADO,
                    0
                ) > 0
                THEN 15
                ELSE 0
            END
                AS RISCO_FATURAMENTO_INATIVO,

            CASE
                WHEN COALESCE(
                    SITUACAO,
                    ''
                ) <> 'LIGADO'
                AND COALESCE(
                    MEDIO_M3_ECON,
                    0
                ) > {minimo_economia}
                THEN 10
                ELSE 0
            END
                AS RISCO_HISTORICO_INATIVO,

            CASE
                WHEN ECONOMIAS >= 5
                THEN 10
                ELSE 0
            END
                AS PESO_ECONOMIAS

        FROM faturamento
    ),

    score AS (

        SELECT
            *,

            LEAST(
                100,
                RISCO_OCORRENCIA_FISCAL
                +
                RISCO_CONSUMO_INATIVO
                +
                RISCO_FATURAMENTO_INATIVO
                +
                RISCO_HISTORICO_INATIVO
                +
                PESO_ECONOMIAS
            )
                AS SCORE_FISCALIZACAO

        FROM componentes
    ),

    recuperacao AS (

        SELECT
            *,

            CASE

                WHEN OCORRENCIA_FISCAL = 'BYPASS'
                THEN 'BYPASS'

                WHEN OCORRENCIA_FISCAL = 'BOMBA LIGADA À REDE'
                THEN 'BOMBA LIGADA À REDE'

                WHEN OCORRENCIA_FISCAL = 'FORNECIMENTO INDEVIDO'
                THEN 'FORNECIMENTO INDEVIDO'

                WHEN COALESCE(SITUACAO, '') <> 'LIGADO'
                     AND COALESCE(CONSUMO_MEDIDO, 0) > 0
                THEN 'INATIVO COM CONSUMO MEDIDO'

                WHEN OCORRENCIA_FISCAL = 'HD SEM LACRE'
                THEN 'HD SEM LACRE'

                WHEN OCORRENCIA_FISCAL = 'HD DIVERGENTE'
                THEN 'HD DIVERGENTE'

                WHEN OCORRENCIA_HD = 'HD RETIRADO / NÃO LOCALIZADO'
                THEN 'HD RETIRADO / NÃO LOCALIZADO'

                WHEN COALESCE(SITUACAO, '') <> 'LIGADO'
                     AND COALESCE(CONSUMO_FATURADO, 0) > 0
                THEN 'INATIVO COM FATURAMENTO'

                WHEN COALESCE(SITUACAO, '') <> 'LIGADO'
                     AND ECONOMIAS >= 5
                THEN 'INATIVO COM VÁRIAS ECONOMIAS'

                ELSE 'VERIFICAÇÃO CADASTRAL'

            END
                AS MOTIVO_RECUPERACAO,

            CASE

                WHEN OCORRENCIA_FISCAL IN (
                    'BYPASS',
                    'BOMBA LIGADA À REDE',
                    'FORNECIMENTO INDEVIDO'
                )
                THEN 'CRÍTICA'

                WHEN SCORE_FISCALIZACAO >= 70
                THEN 'CRÍTICA'

                WHEN SCORE_FISCALIZACAO >= 50
                THEN 'ALTA'

                WHEN SCORE_FISCALIZACAO >= 30
                THEN 'MÉDIA'

                ELSE 'BAIXA'

            END
                AS PRIORIDADE_RECUPERACAO

        FROM score
    )
    """


# ==========================================================
# FORMATAÇÃO EXECUTIVA — k / M
# ==========================================================

def formatar_executivo(valor, casas=1):
    try:
        numero = float(valor or 0)
    except (TypeError, ValueError):
        numero = 0.0

    absoluto = abs(numero)

    if absoluto >= 1_000_000:
        return (
            f"{numero / 1_000_000:.{casas}f}"
            .replace(".", ",")
            + " M"
        )

    if absoluto >= 1_000:
        return (
            f"{numero / 1_000:.{casas}f}"
            .replace(".", ",")
            + " k"
        )

    if float(numero).is_integer():
        return formatar_inteiro(numero)

    return formatar_decimal(numero, casas)


def formatar_moeda_executiva(valor, casas=1):
    try:
        numero = float(valor or 0)
    except (TypeError, ValueError):
        numero = 0.0

    absoluto = abs(numero)

    if absoluto >= 1_000_000:
        return (
            "R$ "
            + f"{numero / 1_000_000:.{casas}f}".replace(".", ",")
            + " M"
        )

    if absoluto >= 1_000:
        return (
            "R$ "
            + f"{numero / 1_000:.{casas}f}".replace(".", ",")
            + " k"
        )

    return formatar_moeda(numero)




def formatar_volume_executivo(valor, casas=2):
    return (
        formatar_executivo(
            valor,
            casas,
        )
        + " m³"
    )


# ==========================================================
# VISÃO GERAL — V25
# ==========================================================

if area == "🌎 VISÃO GERAL":

    # A abertura usa a base completa sob os filtros macro:
    # Base de Origem → GNM → Município → Perfil → Categoria.
    # Nenhuma regra de score/priorização é aplicada aqui.
    where_macro = montar_where(
        condicoes_gerais
    )

    # CONTA_FATURADA é mantida como VARCHAR na base analítica.
    # Para os indicadores macro, convertemos explicitamente respeitando
    # o padrão brasileiro de milhar "." e decimal ",".
    conta_faturada_num_sql = """
        CASE
            WHEN STRPOS(
                TRIM(CAST(CONTA_FATURADA AS VARCHAR)),
                ','
            ) > 0
            THEN TRY_CAST(
                REPLACE(
                    REPLACE(
                        TRIM(CAST(CONTA_FATURADA AS VARCHAR)),
                        '.',
                        ''
                    ),
                    ',',
                    '.'
                )
                AS DOUBLE
            )
            ELSE TRY_CAST(
                TRIM(CAST(CONTA_FATURADA AS VARCHAR))
                AS DOUBLE
            )
        END
    """

    resumo_macro = consultar_linha(
        f"""
        SELECT

            COUNT(*) AS MATRICULAS,

            SUM(
                COALESCE(ECONOMIAS, 0)
            ) AS ECONOMIAS,

            SUM(
                CASE
                    WHEN SITUACAO = 'LIGADO'
                    THEN 1
                    ELSE 0
                END
            ) AS LIGADAS,

            SUM(
                CASE
                    WHEN SITUACAO = 'CORTADO'
                    THEN 1
                    ELSE 0
                END
            ) AS CORTADAS,

            SUM(
                CASE
                    WHEN SITUACAO LIKE '%SUPRIM%'
                         AND SITUACAO NOT LIKE '%PARC%'
                    THEN 1
                    ELSE 0
                END
            ) AS SUPRIMIDAS,

            SUM(
                CASE
                    WHEN SITUACAO LIKE 'FACT%'
                    THEN 1
                    ELSE 0
                END
            ) AS FACTIVEIS,

            SUM(
                CASE
                    WHEN SITUACAO LIKE '%PARC%'
                    THEN 1
                    ELSE 0
                END
            ) AS SUP_PARCIAL,

            SUM(
                CASE
                    WHEN SITUACAO = 'POTENCIAL'
                    THEN 1
                    ELSE 0
                END
            ) AS POTENCIAIS,

            SUM(
                CASE
                    WHEN SITUACAO = 'LIGADO'
                    THEN COALESCE(({conta_faturada_num_sql}), 0)
                    ELSE 0
                END
            ) AS CONTA_ATIVA,

            SUM(
                CASE
                    WHEN SITUACAO = 'LIGADO'
                    THEN COALESCE(CONSUMO_FATURADO, 0)
                    ELSE 0
                END
            )
            /
            NULLIF(
                SUM(
                    CASE
                        WHEN SITUACAO = 'LIGADO'
                        THEN 1
                        ELSE 0
                    END
                ),
                0
            ) AS TICKET_M3,

            SUM(
                CASE
                    WHEN SITUACAO = 'LIGADO'
                    THEN COALESCE(({conta_faturada_num_sql}), 0)
                    ELSE 0
                END
            )
            /
            NULLIF(
                SUM(
                    CASE
                        WHEN SITUACAO = 'LIGADO'
                        THEN 1
                        ELSE 0
                    END
                ),
                0
            ) AS TICKET_RS,

            SUM(
                CASE
                    WHEN SITUACAO = 'LIGADO'
                         AND STATUS_HD = 'COM HIDRÔMETRO'
                    THEN 1
                    ELSE 0
                END
            ) AS ATIVAS_COM_HD,

            SUM(
                CASE
                    WHEN SITUACAO = 'LIGADO'
                         AND STATUS_HD = 'SEM HIDRÔMETRO'
                    THEN 1
                    ELSE 0
                END
            ) AS ATIVAS_SEM_HD,

            SUM(
                CASE
                    WHEN SITUACAO = 'LIGADO'
                         AND STATUS_HD = 'COM HIDRÔMETRO'
                         AND IDADE_HD > 10
                    THEN 1
                    ELSE 0
                END
            ) AS HD_MAIS_10,

            SUM(
                CASE
                    WHEN SITUACAO = 'LIGADO'
                         AND (
                             COALESCE(LEITURA_UPPER, '') LIKE '%PARADO%'
                             OR COALESCE(CONSUMO_UPPER, '') LIKE '%PARADO%'
                         )
                    THEN 1
                    ELSE 0
                END
            ) AS HD_PARADO,

            SUM(
                CASE
                    WHEN SITUACAO = 'LIGADO'
                         AND COALESCE(CONSUMO_FATURADO, 0) = 0
                    THEN 1
                    ELSE 0
                END
            ) AS CONSUMO_ZERO,

            SUM(
                CASE
                    WHEN SITUACAO = 'LIGADO'
                         AND COALESCE(CONSUMO_FATURADO, 0) > 0
                         AND COALESCE(CONSUMO_FATURADO, 0) <= 5
                    THEN 1
                    ELSE 0
                END
            ) AS BAIXO_CONSUMO

        FROM {BASE}
        {where_macro}
        """,
        VERSAO,
    )

    (
        matriculas,
        economias,
        ligadas,
        cortadas,
        suprimidas,
        factiveis,
        sup_parcial,
        potenciais,
        conta_ativa,
        ticket_m3,
        ticket_rs,
        ativas_com_hd,
        ativas_sem_hd,
        hd_mais_10,
        hd_parado,
        consumo_zero,
        baixo_consumo,
    ) = resumo_macro

    ligadas_base = float(ligadas or 0)

    hidrometracao_ativa = (
        float(ativas_com_hd or 0)
        / ligadas_base
        * 100
        if ligadas_base > 0
        else 0
    )

    pct_sem_hd = (
        float(ativas_sem_hd or 0)
        / ligadas_base
        * 100
        if ligadas_base > 0
        else 0
    )

    economias_por_matricula = (
        float(economias or 0)
        / float(matriculas or 0)
        if float(matriculas or 0) > 0
        else 0
    )

    # Contexto dos filtros sem transformar a abertura em consulta cadastral.
    contexto_macro = []

    if filtro_base_origem:
        contexto_macro.append(
            "Base: " + ", ".join(map(str, filtro_base_origem))
        )

    if filtro_gnm:
        contexto_macro.append(
            "GNM: " + ", ".join(map(str, filtro_gnm))
        )

    if filtro_municipio:
        contexto_macro.append(
            "Município: " + ", ".join(map(str, filtro_municipio))
        )

    if filtro_perfil:
        contexto_macro.append(
            "Perfil: " + ", ".join(map(str, filtro_perfil))
        )

    if filtro_categoria:
        contexto_macro.append(
            "Categoria: " + ", ".join(map(str, filtro_categoria))
        )

    if contexto_macro:
        st.caption(
            "Visão filtrada | " + " • ".join(contexto_macro)
        )
    else:
        st.caption(
            "Visão consolidada de Pernambuco | RMR + Interior"
        )


    # ------------------------------------------------------
    # 1. BASE GERAL
    # ------------------------------------------------------

    st.subheader("Panorama da Base")

    c1, c2, c3, c4, c5 = st.columns(5)

    c1.metric(
        "Ligações",
        formatar_executivo(matriculas, 2),
    )

    c2.metric(
        "Economias",
        formatar_executivo(economias, 2),
    )

    c3.metric(
        "Economias por Ligação",
        formatar_decimal(economias_por_matricula, 2),
    )

    c4.metric(
        "Ligações ativas",
        formatar_executivo(ligadas, 2),
    )

    c5.metric(
        "Faturamento das Ligações Ativas",
        formatar_moeda_executiva(conta_ativa, 1),
    )


    # ------------------------------------------------------
    # 2. SITUAÇÃO DAS LIGAÇÕES
    # ------------------------------------------------------

    st.subheader("Situação das Ligações")

    s1, s2, s3, s4, s5, s6 = st.columns(6)

    s1.metric(
        "Ligações Ativas",
        formatar_executivo(ligadas, 1),
    )

    s2.metric(
        "Ligações Cortadas",
        formatar_executivo(cortadas, 1),
    )

    s3.metric(
        "Ligações Suprimidas",
        formatar_executivo(suprimidas, 1),
    )

    s4.metric(
        "Ligações Factíveis",
        formatar_executivo(factiveis, 1),
    )

    s5.metric(
        "Supressão Parcial",
        formatar_executivo(sup_parcial, 1),
    )

    s6.metric(
        "Ligações Potenciais",
        formatar_executivo(potenciais, 1),
    )

    df_situacao = consultar_df(
        f"""
        WITH situacao_normalizada AS (
            SELECT
                CASE
                    WHEN SITUACAO = 'LIGADO'
                    THEN 'Ligação Ativa'

                    WHEN SITUACAO = 'CORTADO'
                    THEN 'Ligação Cortada'

                    WHEN SITUACAO LIKE '%PARC%'
                    THEN 'Supressão Parcial'

                    WHEN SITUACAO LIKE '%SUPRIM%'
                    THEN 'Ligação Suprimida'

                    WHEN SITUACAO LIKE 'FACT%'
                    THEN 'Ligação Factível'

                    WHEN SITUACAO = 'POTENCIAL'
                    THEN 'Ligação Potencial'

                    ELSE 'Outras'
                END AS "Situação"
            FROM {BASE}
            {where_macro}
        )

        SELECT
            "Situação",
            COUNT(*) AS "Ligações",
            ROUND(
                COUNT(*) * 100.0
                / NULLIF(
                    SUM(COUNT(*)) OVER (),
                    0
                ),
                1
            ) AS "Percentual (%)"
        FROM situacao_normalizada
        GROUP BY 1
        ORDER BY
            CASE "Situação"
                WHEN 'Ligação Ativa' THEN 1
                WHEN 'Ligação Cortada' THEN 2
                WHEN 'Ligação Suprimida' THEN 3
                WHEN 'Ligação Factível' THEN 4
                WHEN 'Supressão Parcial' THEN 5
                WHEN 'Ligação Potencial' THEN 6
                ELSE 7
            END
        """,
        VERSAO,
    )

    exibir_dataframe(
        df_situacao,
        use_container_width=True,
        hide_index=True,
    )


    # ------------------------------------------------------
    # 3. CONSUMO E FATURAMENTO
    # ------------------------------------------------------

    st.subheader("Consumo e Faturamento")

    f1, f2, f3, f4 = st.columns(4)

    f1.metric(
        "Consumo médio por Ligação",
        f"{formatar_decimal(ticket_m3, 2)} m³",
    )

    f2.metric(
        "Faturamento médio por Ligação",
        formatar_moeda(ticket_rs),
    )

    f3.metric(
        "Consumo zero",
        formatar_executivo(consumo_zero, 1),
    )

    f4.metric(
        "Baixo consumo 1–5 m³",
        formatar_executivo(baixo_consumo, 1),
    )

    df_consumo_macro = consultar_df(
        f"""
        SELECT
            CASE
                WHEN COALESCE(CONSUMO_FATURADO, 0) = 0
                THEN '0'

                WHEN CONSUMO_FATURADO <= 5
                THEN '1–5'

                WHEN CONSUMO_FATURADO <= 10
                THEN '6–10'

                WHEN CONSUMO_FATURADO <= 20
                THEN '11–20'

                WHEN CONSUMO_FATURADO <= 30
                THEN '21–30'

                WHEN CONSUMO_FATURADO <= 50
                THEN '31–50'

                ELSE '>50'
            END AS "Faixa de consumo",
            COUNT(*) AS "Ligações"
        FROM {BASE}
        {where_macro}
        {"AND" if where_macro else "WHERE"}
            SITUACAO = 'LIGADO'
        GROUP BY 1
        ORDER BY
            CASE "Faixa de consumo"
                WHEN '0' THEN 1
                WHEN '1–5' THEN 2
                WHEN '6–10' THEN 3
                WHEN '11–20' THEN 4
                WHEN '21–30' THEN 5
                WHEN '31–50' THEN 6
                ELSE 7
            END
        """,
        VERSAO,
    )

    if not df_consumo_macro.empty:
        st.bar_chart(
            df_consumo_macro.set_index("Faixa de consumo"),
            use_container_width=True,
        )


    # ------------------------------------------------------
    # 4. PARQUE DE HIDRÔMETROS
    # ------------------------------------------------------

    st.subheader("Parque de Hidrômetros")

    h1, h2, h3, h4 = st.columns(4)

    h1.metric(
        "Hidrometração ativa",
        formatar_percentual(
            hidrometracao_ativa,
            1,
        ),
    )

    h2.metric(
        "Ligações Ativas sem HD",
        formatar_executivo(
            ativas_sem_hd,
            1,
        ),
        delta=(
            formatar_percentual(
                pct_sem_hd,
                1,
            )
            + " das ativas"
        ),
        delta_color="off",
    )

    h3.metric(
        "HD > 10 anos",
        formatar_executivo(
            hd_mais_10,
            1,
        ),
    )

    h4.metric(
        "HD parado",
        formatar_executivo(
            hd_parado,
            1,
        ),
    )

    df_idade_macro = consultar_df(
        f"""
        SELECT
            CASE
                WHEN IDADE_HD IS NULL
                THEN 'Sem idade'

                WHEN IDADE_HD <= 5
                THEN '0–5'

                WHEN IDADE_HD <= 10
                THEN '6–10'

                WHEN IDADE_HD <= 15
                THEN '11–15'

                WHEN IDADE_HD <= 20
                THEN '16–20'

                WHEN IDADE_HD <= 30
                THEN '21–30'

                ELSE '>30'
            END AS "Faixa de idade",
            COUNT(*) AS "Hidrômetros"
        FROM {BASE}
        {where_macro}
        {"AND" if where_macro else "WHERE"}
            SITUACAO = 'LIGADO'
            AND STATUS_HD = 'COM HIDRÔMETRO'
        GROUP BY 1
        ORDER BY
            CASE "Faixa de idade"
                WHEN '0–5' THEN 1
                WHEN '6–10' THEN 2
                WHEN '11–15' THEN 3
                WHEN '16–20' THEN 4
                WHEN '21–30' THEN 5
                WHEN '>30' THEN 6
                ELSE 7
            END
        """,
        VERSAO,
    )

    if not df_idade_macro.empty:
        st.bar_chart(
            df_idade_macro.set_index("Faixa de idade"),
            use_container_width=True,
        )

    st.caption(
        "A Visão Geral apresenta fatos da base. "
        "Scores, ganho estimado e modelos de priorização permanecem "
        "nas áreas de Hidrômetros e Recuperação de Ligações."
    )

    st.divider()

    st.markdown("### Pontos de Atenção")

    p1, p2, p3, p4 = st.columns(4)

    p1.metric(
        "Ligações Ativas sem HD",
        formatar_executivo(
            ativas_sem_hd,
            1,
        ),
    )

    p2.metric(
        "HD parado",
        formatar_executivo(
            hd_parado,
            1,
        ),
    )

    p3.metric(
        "HD > 10 anos",
        formatar_executivo(
            hd_mais_10,
            1,
        ),
    )

    p4.metric(
        "Ligações Cortadas",
        formatar_executivo(
            cortadas,
            1,
        ),
    )




# ==========================================================
# HIDRÔMETROS
# ==========================================================

if area == "💧 HIDRÔMETROS":

    tela = st.radio(
        "Visão",
        [
            "📊 Resumo",
            "🏢 Regiões",
            "💧 Oportunidade de Volume",
            "💰 Ganho Estimado",
            "🔧 Idade dos Hidrômetros",
            "⚠️ Problemas Identificados",
            "🔀 Cruzamentos",
            "📋 Lista de Imóveis",
        ],
        horizontal=True,
        label_visibility="collapsed",
    )


    condicoes_hd = list(
        condicoes_gerais
    )


    with st.sidebar.expander(
        "💧 Filtros dos Hidrômetros",
        expanded=True,
    ):

        filtro_10m3 = st.multiselect(
            "Consumo por economia",
            [
                "≤ 10 m³/economia",
                "> 10 m³/economia",
                "SEM CONSUMO",
            ],
            help=(
                "Filtro de direcionamento baseado "
                "no consumo medido dividido pela "
                "quantidade de economias."
            ),
        )

        condicao = sql_in(
            "FAIXA_10_M3",
            filtro_10m3,
        )

        if condicao:
            condicoes_hd.append(
                condicao
            )


        filtro_economias = st.multiselect(
            "Quantidade de economias",
            [
                "1",
                "2–4",
                "5–10",
                "11–20",
                "21–50",
                "50+",
            ],
        )

        condicao = sql_in(
            "FAIXA_ECONOMIAS",
            filtro_economias,
        )

        if condicao:
            condicoes_hd.append(
                condicao
            )


        filtro_medido = st.multiselect(
            "Consumo medido por economia (m³)",
            [
                "SEM CONSUMO",
                "0",
                ">0 a <5",
                "5 a <10",
                "10 a <15",
                "15 a <20",
                "20 a <30",
                "30 a <50",
                "50+",
            ],
        )

        condicao = sql_in(
            "FAIXA_MEDIDO_ECON",
            filtro_medido,
        )

        if condicao:
            condicoes_hd.append(
                condicao
            )


        filtro_faturado = st.multiselect(
            "Consumo faturado por economia (m³)",
            [
                "SEM CONSUMO",
                "0",
                ">0 a <5",
                "5 a <10",
                "10 a <15",
                "15 a <20",
                "20 a <30",
                "30 a <50",
                "50+",
            ],
        )

        condicao = sql_in(
            "FAIXA_FATURADO_ECON",
            filtro_faturado,
        )

        if condicao:
            condicoes_hd.append(
                condicao
            )


        filtro_idade = st.multiselect(
            "Idade do hidrômetro",
            [
                "<5",
                "5–7",
                "8–9",
                "10–14",
                "15+",
                "SEM IDADE",
            ],
        )

        condicao = sql_in(
            "FAIXA_IDADE_HD",
            filtro_idade,
        )

        if condicao:
            condicoes_hd.append(
                condicao
            )


        capacidades = consultar_lista(
            f"""
            SELECT DISTINCT CAPACIDADE_HD
            FROM {BASE}
            WHERE
                CAPACIDADE_HD IS NOT NULL
                AND TRIM(CAPACIDADE_HD) <> ''
            ORDER BY CAPACIDADE_HD
            """,
            VERSAO,
        )


        filtro_capacidade = st.multiselect(
            "Capacidade do hidrômetro",
            capacidades,
        )

        condicao = sql_in(
            "CAPACIDADE_HD",
            filtro_capacidade,
        )

        if condicao:
            condicoes_hd.append(
                condicao
            )


        filtro_prioridade = st.multiselect(
            "Prioridade de recuperação",
            [
                "MUITO ALTA",
                "ALTA",
                "MÉDIA",
                "BAIXA",
                "SEM POTENCIAL",
            ],
        )

        condicao = sql_in(
            "PRIORIDADE_RECUPERACAO",
            filtro_prioridade,
        )

        if condicao:
            condicoes_hd.append(
                condicao
            )


        filtro_prioridade_tecnica = st.multiselect(
            "Prioridade técnica",
            [
                "MUITO ALTA",
                "ALTA",
                "MÉDIA",
                "BAIXA",
                "SEM PRIORIDADE",
            ],
        )

        condicao = sql_in(
            "PRIORIDADE_TECNICA",
            filtro_prioridade_tecnica,
        )

        if condicao:
            condicoes_hd.append(
                condicao
            )


        st.divider()
        st.markdown("**🎯 Capacidade Operacional**")

        qtd_trocas = st.number_input(
            "Quantidade de trocas desejada",
            min_value=1,
            max_value=50000,
            value=500,
            step=100,
            key="parametro_qtd_trocas_v20",
            help=(
                "Premissa de simulação. Não limita o painel. "
                "Os cards e tabelas gerais continuam mostrando toda a base filtrada; "
                "somente o cenário de capacidade usa as melhores oportunidades "
                "até a quantidade informada."
            ),
        )

        st.caption(
            "Premissa de simulação — não limita as demais visões."
        )


    where_hd = montar_where(
        condicoes_hd
    )


# ==========================================================
# HIDROMETRIA - RESUMO
# ==========================================================

    if tela == "📊 Resumo":

        resumo = consultar_linha(
            f"""
            {cte_hidrometria()}

            SELECT

                COUNT(*),

                SUM(
                    CASE
                        WHEN PRIORIDADE_RECUPERACAO IN (
                            'MUITO ALTA',
                            'ALTA'
                        )
                        THEN 1
                        ELSE 0
                    END
                ),

                100.0
                *
                SUM(
                    CASE
                        WHEN PRIORIDADE_RECUPERACAO IN (
                            'MUITO ALTA',
                            'ALTA'
                        )
                        THEN 1
                        ELSE 0
                    END
                )
                /
                NULLIF(COUNT(*), 0),

                SUM(
                    CASE
                        WHEN PRIORIDADE_RECUPERACAO = 'MUITO ALTA'
                        THEN 1
                        ELSE 0
                    END
                ),

                SUM(
                    CASE
                        WHEN PRIORIDADE_RECUPERACAO = 'ALTA'
                        THEN 1
                        ELSE 0
                    END
                ),

                SUM(
                    COALESCE(
                        GAP_MEDICAO_M3,
                        0
                    )
                ),

                SUM(
                    COALESCE(
                        GANHO_TOTAL_ESTIMADO,
                        0
                    )
                ),

                AVG(IDADE_HD),

                AVG(SCORE_RECUPERACAO)

            FROM hidrometria

            {where_hd}
            """,
            VERSAO,
        )


        c1, c2, c3, c4, c5, c6, c7 = st.columns(7)


        c1.metric(
            "HDs Analisados",
            formatar_executivo(
                resumo[0],
                2,
            )
        )

        c2.metric(
            "HDs Prioritários",
            formatar_executivo(
                resumo[1],
                1,
            )
        )

        c3.metric(
            "Recup. Prioritária",
            formatar_percentual(resumo[2])
        )

        c4.metric(
            "Muito Alta",
            formatar_executivo(
                resumo[3],
                1,
            )
        )

        c5.metric(
            "Alta",
            formatar_executivo(
                resumo[4],
                1,
            )
        )

        c6.metric(
            "Volume Estimado",
            formatar_volume_executivo(
                resumo[5],
                2,
            )
        )

        c7.metric(
            "Ganho Estimado",
            formatar_moeda_executiva(
                resumo[6],
                2,
            )
        )


        c8, c9 = st.columns(2)

        c8.metric(
            "Idade Média",
            formatar_decimal(resumo[7])
            + " anos"
        )

        c9.metric(
            "Pontuação Média de Recuperação",
            formatar_decimal(resumo[8])
        )


        st.caption(
            "Volume e ganho financeiro são estimativas "
            "de priorização. Não representam recuperação "
            "garantida após a substituição."
        )


        # ======================================================
        # V20 - CENÁRIO DA CAPACIDADE OPERACIONAL - HIDRÔMETROS
        # ======================================================
        st.markdown(
            f"**🎯 Cenário da capacidade: {int(qtd_trocas):,} trocas**".replace(",", ".")
        )
        st.caption(
            "Resultado das melhores oportunidades dentro dos filtros atuais. "
            "A quantidade é apenas uma premissa de simulação e não limita o painel."
        )

        where_sim_hd = montar_where(
            condicoes_hd
            + [
                "("
                "COALESCE(GANHO_TOTAL_ESTIMADO, 0) > 0 "
                "OR COALESCE(GAP_MEDICAO_M3, 0) > 0"
                ")"
            ]
        )

        sim_hd = consultar_linha(
            f"""
            {cte_hidrometria()}

            , selecionados AS (
                SELECT *
                FROM hidrometria
                {where_sim_hd}
                ORDER BY
                    CASE PRIORIDADE_RECUPERACAO
                        WHEN 'MUITO ALTA' THEN 1
                        WHEN 'ALTA' THEN 2
                        WHEN 'MÉDIA' THEN 3
                        WHEN 'BAIXA' THEN 4
                        ELSE 5
                    END,
                    SCORE_RECUPERACAO DESC,
                    GANHO_TOTAL_ESTIMADO DESC,
                    GAP_MEDICAO_M3 DESC
                LIMIT {int(qtd_trocas)}
            )

            SELECT
                COUNT(*) AS QTD,
                SUM(COALESCE(GAP_MEDICAO_M3, 0)) AS VOLUME,
                SUM(COALESCE(GANHO_TOTAL_ESTIMADO, 0)) AS GANHO,
                AVG(COALESCE(GANHO_TOTAL_ESTIMADO, 0)) AS GANHO_MEDIO,
                SUM(CASE WHEN PRIORIDADE_RECUPERACAO = 'MUITO ALTA' THEN 1 ELSE 0 END) AS MUITO_ALTA,
                SUM(CASE WHEN PRIORIDADE_RECUPERACAO = 'ALTA' THEN 1 ELSE 0 END) AS ALTA
            FROM selecionados
            """,
            VERSAO,
        )

        s1, s2, s3, s4, s5, s6 = st.columns(6)

        s1.metric(
            "Trocas Selecionadas",
            formatar_executivo(sim_hd[0], 1),
        )
        s2.metric(
            "Volume Estimado",
            formatar_volume_executivo(sim_hd[1], 2),
        )
        s3.metric(
            "Ganho Estimado",
            formatar_moeda_executiva(sim_hd[2], 2),
        )
        s4.metric(
            "Ganho Médio / Troca",
            formatar_moeda(sim_hd[3]),
        )
        s5.metric(
            "Muito Alta",
            formatar_executivo(sim_hd[4], 1),
        )
        s6.metric(
            "Alta",
            formatar_executivo(sim_hd[5], 1),
        )

        st.caption(
            "Seleção recomendada = melhores oportunidades dentro dos filtros atuais. "
            "O resultado é estimado e não representa recuperação garantida."
        )

        with st.expander("📋 Ver seleção recomendada para a capacidade informada", expanded=False):
            limite_sim_hd = min(int(qtd_trocas), 3000)

            df_sim_hd = consultar_df(
                f"""
                {cte_hidrometria()}

                SELECT
                    MATRICULA AS "Matrícula",
                    GNM AS "GNM",
                    LOCALIDADE AS "Localidade",
                    MUNICIPIO AS "Município",
                    BAIRRO AS "Bairro",
                    PERFIL AS "Perfil",
                    CATEGORIA AS "Categoria",
                    ECONOMIAS AS "Economias",
                    PRIORIDADE_RECUPERACAO AS "Prioridade de Recuperação",
                    SCORE_RECUPERACAO AS "Pontuação",
                    ROUND(GAP_MEDICAO_M3, 1) AS "Volume Estimado (m³/mês)",
                    ROUND(GANHO_TOTAL_ESTIMADO, 2) AS "Ganho Estimado (R$/mês)",
                    MOTIVO_RECUPERACAO_HD AS "Motivo da Prioridade",
                    PRIORIDADE_TECNICA AS "Prioridade Técnica",
                    MOTIVO_TECNICO AS "Motivo Técnico"
                FROM hidrometria
                {where_sim_hd}
                ORDER BY
                    CASE PRIORIDADE_RECUPERACAO
                        WHEN 'MUITO ALTA' THEN 1
                        WHEN 'ALTA' THEN 2
                        WHEN 'MÉDIA' THEN 3
                        WHEN 'BAIXA' THEN 4
                        ELSE 5
                    END,
                    SCORE_RECUPERACAO DESC,
                    GANHO_TOTAL_ESTIMADO DESC,
                    GAP_MEDICAO_M3 DESC
                LIMIT {limite_sim_hd}
                """,
                VERSAO,
            )

            exibir_dataframe(
                df_sim_hd,
                use_container_width=True,
                hide_index=True,
            )

            st.download_button(
                "📥 Exportar seleção recomendada de trocas",
                df_sim_hd.to_csv(index=False).encode("utf-8-sig"),
                "selecao_recomendada_trocas.csv",
                "text/csv",
            )

            if int(qtd_trocas) > 3000:
                st.caption(
                    "A seleção total considera a quantidade informada. "
                    "A tabela é limitada às 3.000 primeiras linhas para manter o painel rápido."
                )


        st.subheader(
            "Prioridades"
        )


        prioridades_df = consultar_df(
            f"""
            {cte_hidrometria()}

            SELECT

                PRIORIDADE_RECUPERACAO
                    AS "Prioridade de Recuperação",

                COUNT(*)
                    AS "Hidrômetros",

                ROUND(
                    100.0
                    *
                    COUNT(*)
                    /
                    SUM(COUNT(*)) OVER (),
                    1
                )
                    AS "Percentual (%)",

                ROUND(
                    AVG(MEDIDO_M3_ECON),
                    1
                )
                    AS "Medido/Economia (m³)",

                ROUND(
                    AVG(FATURADO_M3_ECON),
                    1
                )
                    AS "Faturado/Economia (m³)",

                ROUND(
                    AVG(MEDIO_M3_ECON),
                    1
                )
                    AS "Médio/Economia (m³)",

                ROUND(
                    AVG(QUEDA_PCT),
                    1
                )
                    AS "Queda Média (%)",

                ROUND(
                    SUM(
                        COALESCE(
                            GAP_MEDICAO_M3,
                            0
                        )
                    ),
                    0
                )
                    AS "Volume Estimado (m³/mês)",

                ROUND(
                    SUM(
                        COALESCE(
                            GANHO_TOTAL_ESTIMADO,
                            0
                        )
                    ),
                    2
                )
                    AS "Ganho Estimado (R$/mês)",

                ROUND(
                    AVG(SCORE_RECUPERACAO),
                    1
                )
                    AS "Pontuação Média de Recuperação"

            FROM hidrometria

            {where_hd}

            GROUP BY PRIORIDADE_RECUPERACAO

            ORDER BY
                CASE PRIORIDADE_RECUPERACAO
                    WHEN 'MUITO ALTA' THEN 1
                    WHEN 'ALTA' THEN 2
                    WHEN 'MÉDIA' THEN 3
                    ELSE 4
                END
            """,
            VERSAO,
        )


        exibir_dataframe(
            prioridades_df,
            use_container_width=True,
            hide_index=True,
        )


# ==========================================================
# HIDROMETRIA - REGIÕES
# ==========================================================

    elif tela == "🏢 Regiões":

        st.subheader(
            "Oportunidades por Região"
        )


        df = consultar_df(
            f"""
            {cte_hidrometria()}

            SELECT

                GNM AS "GNM",

                LOCALIDADE
                    AS "Localidade",

                MUNICIPIO
                    AS "Município",

                COUNT(*)
                    AS "Hidrômetros",

                SUM(
                    CASE
                        WHEN PRIORIDADE_RECUPERACAO = 'MUITO ALTA'
                        THEN 1
                        ELSE 0
                    END
                )
                    AS "Muito Alta",

                SUM(
                    CASE
                        WHEN PRIORIDADE_RECUPERACAO = 'ALTA'
                        THEN 1
                        ELSE 0
                    END
                )
                    AS "Alta",

                ROUND(
                    100.0
                    *
                    SUM(
                        CASE
                            WHEN PRIORIDADE_RECUPERACAO IN (
                                'MUITO ALTA',
                                'ALTA'
                            )
                            THEN 1
                            ELSE 0
                        END
                    )
                    /
                    NULLIF(
                        COUNT(*),
                        0
                    ),
                    1
                )
                    AS "Prioritários (%)",

                ROUND(
                    AVG(MEDIDO_M3_ECON),
                    1
                )
                    AS "Medido/Economia (m³)",

                ROUND(
                    AVG(MEDIO_M3_ECON),
                    1
                )
                    AS "Médio/Economia (m³)",

                ROUND(
                    SUM(
                        COALESCE(
                            GAP_MEDICAO_M3,
                            0
                        )
                    ),
                    0
                )
                    AS "Volume Estimado (m³/mês)",

                ROUND(
                    SUM(
                        COALESCE(
                            GANHO_TOTAL_ESTIMADO,
                            0
                        )
                    ),
                    2
                )
                    AS "Ganho Estimado (R$/mês)",

                ROUND(
                    AVG(SCORE_RECUPERACAO),
                    1
                )
                    AS "Pontuação Média de Recuperação"

            FROM hidrometria

            {where_hd}

            GROUP BY
                GNM,
                LOCALIDADE,
                MUNICIPIO

            ORDER BY
                "Ganho Estimado (R$/mês)" DESC,
                "Volume Estimado (m³/mês)" DESC
            """,
            VERSAO,
        )


        exibir_dataframe(
            df,
            use_container_width=True,
            hide_index=True,
        )


        st.markdown(
            f"**🎯 Distribuição das {int(qtd_trocas):,} melhores trocas por região**".replace(",", ".")
        )
        st.caption(
            "Esta tabela usa a capacidade operacional informada no menu lateral, "
            "mas não altera a tabela geral acima."
        )

        where_sim_regiao = montar_where(
            condicoes_hd
            + [
                "("
                "COALESCE(GANHO_TOTAL_ESTIMADO, 0) > 0 "
                "OR COALESCE(GAP_MEDICAO_M3, 0) > 0"
                ")"
            ]
        )

        df_cap_regiao = consultar_df(
            f"""
            {cte_hidrometria()}

            , selecionados AS (
                SELECT *
                FROM hidrometria
                {where_sim_regiao}
                ORDER BY
                    CASE PRIORIDADE_RECUPERACAO
                        WHEN 'MUITO ALTA' THEN 1
                        WHEN 'ALTA' THEN 2
                        WHEN 'MÉDIA' THEN 3
                        WHEN 'BAIXA' THEN 4
                        ELSE 5
                    END,
                    SCORE_RECUPERACAO DESC,
                    GANHO_TOTAL_ESTIMADO DESC,
                    GAP_MEDICAO_M3 DESC
                LIMIT {int(qtd_trocas)}
            )

            SELECT
                GNM AS "GNM",
                LOCALIDADE AS "Localidade",
                MUNICIPIO AS "Município",
                COUNT(*) AS "Trocas Selecionadas",
                ROUND(SUM(COALESCE(GAP_MEDICAO_M3, 0)), 1)
                    AS "Volume Estimado (m³/mês)",
                ROUND(SUM(COALESCE(GANHO_TOTAL_ESTIMADO, 0)), 2)
                    AS "Ganho Estimado (R$/mês)",
                SUM(CASE WHEN PRIORIDADE_RECUPERACAO = 'MUITO ALTA' THEN 1 ELSE 0 END)
                    AS "Muito Alta",
                SUM(CASE WHEN PRIORIDADE_RECUPERACAO = 'ALTA' THEN 1 ELSE 0 END)
                    AS "Alta"
            FROM selecionados
            GROUP BY
                GNM,
                LOCALIDADE,
                MUNICIPIO
            ORDER BY
                "Trocas Selecionadas" DESC,
                "Ganho Estimado (R$/mês)" DESC
            """,
            VERSAO,
        )

        exibir_dataframe(
            df_cap_regiao,
            use_container_width=True,
            hide_index=True,
        )


# ==========================================================
# HIDROMETRIA - OPORTUNIDADE DE VOLUME
# ==========================================================

    elif tela == "💧 Oportunidade de Volume":

        st.subheader(
            "Consumo Medido × Médio × Faturado"
        )


        df = consultar_df(
            f"""
            {cte_hidrometria()}

            SELECT

                MATRICULA
                    AS "Matrícula",

                GNM
                    AS "GNM",

                LOCALIDADE
                    AS "Localidade",

                MUNICIPIO
                    AS "Município",

                BAIRRO
                    AS "Bairro",

                PERFIL
                    AS "Perfil",

                CATEGORIA
                    AS "Categoria",

                ECONOMIAS
                    AS "Economias",

                FAIXA_10_M3
                    AS "Faixa 10 m³/Economia",

                CAPACIDADE_HD
                    AS "Capacidade",

                ROUND(
                    CONSUMO_MEDIDO,
                    1
                )
                    AS "Medido (m³)",

                ROUND(
                    CONSUMO_FATURADO,
                    1
                )
                    AS "Faturado (m³)",

                ROUND(
                    CONSUMO_MEDIO,
                    1
                )
                    AS "Médio (m³)",

                ROUND(
                    MEDIDO_M3_ECON,
                    1
                )
                    AS "Medido/Economia (m³)",

                ROUND(
                    FATURADO_M3_ECON,
                    1
                )
                    AS "Faturado/Economia (m³)",

                ROUND(
                    MEDIO_M3_ECON,
                    1
                )
                    AS "Médio/Economia (m³)",

                ROUND(
                    QUEDA_PCT,
                    1
                )
                    AS "Queda (%)",

                ROUND(
                    GAP_MEDICAO_M3,
                    1
                )
                    AS "Volume Estimado (m³/mês)",

                ROUND(
                    GANHO_TOTAL_ESTIMADO,
                    2
                )
                    AS "Ganho Estimado (R$/mês)",

                SCORE_RECUPERACAO
                    AS "Pontuação de Recuperação",

                PRIORIDADE_RECUPERACAO
                    AS "Prioridade"

            FROM hidrometria

            {where_hd}

            ORDER BY
                GAP_MEDICAO_M3 DESC,
                GANHO_TOTAL_ESTIMADO DESC

            LIMIT 2000
            """,
            VERSAO,
        )


        exibir_dataframe(
            df,
            use_container_width=True,
            hide_index=True,
        )


# ==========================================================
# HIDROMETRIA - GANHO ESTIMADO
# ==========================================================

    elif tela == "💰 Ganho Estimado":

        st.subheader(
            "Potencial Financeiro das Trocas"
        )

        st.caption(
            "Compara o faturamento simulado com o consumo "
            "atual/faturado com o faturamento simulado "
            "utilizando o consumo médio de referência."
        )


        financeiro = consultar_linha(
            f"""
            {cte_hidrometria()}

            SELECT

                SUM(
                    COALESCE(
                        FAT_ATUAL_INFORMADO,
                        0
                    )
                ),

                SUM(
                    COALESCE(
                        FAT_ATUAL_TOTAL_SIM,
                        0
                    )
                ),

                SUM(
                    COALESCE(
                        FAT_POTENCIAL_TOTAL_SIM,
                        0
                    )
                ),

                SUM(
                    COALESCE(
                        GANHO_AGUA_ESTIMADO,
                        0
                    )
                ),

                SUM(
                    COALESCE(
                        GANHO_ESGOTO_ESTIMADO,
                        0
                    )
                ),

                SUM(
                    COALESCE(
                        GANHO_TOTAL_ESTIMADO,
                        0
                    )
                ),

                SUM(
                    COALESCE(
                        GAP_MEDICAO_M3,
                        0
                    )
                )

            FROM hidrometria

            {where_hd}
            """,
            VERSAO,
        )


        c1, c2, c3, c4 = st.columns(4)

        c1.metric(
            "Faturamento Atual Informado",
            formatar_moeda(
                financeiro[0]
            )
        )

        c2.metric(
            "Faturamento Atual Simulado",
            formatar_moeda(
                financeiro[1]
            )
        )

        c3.metric(
            "Faturamento Potencial Estimado",
            formatar_moeda(
                financeiro[2]
            )
        )

        c4.metric(
            "Ganho Total Estimado / mês",
            formatar_moeda(
                financeiro[5]
            )
        )


        c5, c6, c7 = st.columns(3)

        c5.metric(
            "Ganho Água / mês",
            formatar_moeda(
                financeiro[3]
            )
        )

        c6.metric(
            "Ganho Esgoto / mês",
            formatar_moeda(
                financeiro[4]
            )
        )

        c7.metric(
            "Volume Estimado / mês",
            formatar_volume(
                financeiro[6]
            )
        )


        st.info(
            "O faturamento potencial é uma simulação. "
            "O resultado efetivo deverá ser validado "
            "comparando consumo e faturamento antes e depois da troca."
        )


        df = consultar_df(
            f"""
            {cte_hidrometria()}

            SELECT

                MATRICULA
                    AS "Matrícula",

                GNM
                    AS "GNM",

                LOCALIDADE
                    AS "Localidade",

                MUNICIPIO
                    AS "Município",

                PERFIL
                    AS "Perfil",

                CATEGORIA
                    AS "Categoria",

                ECONOMIAS
                    AS "Economias",

                SITUACAO_ESGOTO
                    AS "Situação Esgoto",

                ROUND(
                    PERC_ESGOTO_CALC,
                    1
                )
                    AS "Esgoto (%)",

                FAIXA_10_M3
                    AS "Faixa 10 m³/Economia",

                ROUND(
                    CONSUMO_MEDIDO,
                    1
                )
                    AS "Medido (m³)",

                ROUND(
                    CONSUMO_FATURADO,
                    1
                )
                    AS "Faturado (m³)",

                ROUND(
                    CONSUMO_MEDIO,
                    1
                )
                    AS "Médio Referência (m³)",

                ROUND(
                    GAP_MEDICAO_M3,
                    1
                )
                    AS "Volume Estimado (m³/mês)",

                ROUND(
                    VALOR_AGUA,
                    2
                )
                    AS "Água Atual Informada (R$)",

                ROUND(
                    VALOR_ESGOTO,
                    2
                )
                    AS "Esgoto Atual Informado (R$)",

                ROUND(
                    FAT_ATUAL_TOTAL_SIM,
                    2
                )
                    AS "Atual Simulado (R$)",

                ROUND(
                    FAT_POTENCIAL_AGUA_SIM,
                    2
                )
                    AS "Potencial Água (R$)",

                ROUND(
                    FAT_POTENCIAL_ESGOTO_SIM,
                    2
                )
                    AS "Potencial Esgoto (R$)",

                ROUND(
                    FAT_POTENCIAL_TOTAL_SIM,
                    2
                )
                    AS "Potencial Total (R$)",

                ROUND(
                    GANHO_TOTAL_ESTIMADO,
                    2
                )
                    AS "Ganho Estimado (R$/mês)",

                PRIORIDADE_RECUPERACAO
                    AS "Prioridade de Recuperação",

                MOTIVO_RECUPERACAO_HD
                    AS "Motivo da Recuperação",

                PRIORIDADE_TECNICA
                    AS "Prioridade Técnica",

                MOTIVO_TECNICO
                    AS "Motivo Técnico"

            FROM hidrometria

            {where_hd}

            ORDER BY
                GANHO_TOTAL_ESTIMADO DESC,
                GAP_MEDICAO_M3 DESC

            LIMIT 3000
            """,
            VERSAO,
        )


        exibir_dataframe(
            df,
            use_container_width=True,
            hide_index=True,
        )


# ==========================================================
# HIDROMETRIA - IDADE
# ==========================================================

    elif tela == "🔧 Idade dos Hidrômetros":

        st.subheader(
            "Idade × Consumo × Volume × Ganho"
        )


        df = consultar_df(
            f"""
            {cte_hidrometria()}

            SELECT

                FAIXA_IDADE_HD
                    AS "Idade",

                COUNT(*)
                    AS "Hidrômetros",

                SUM(
                    CASE
                        WHEN PRIORIDADE_RECUPERACAO = 'MUITO ALTA'
                        THEN 1
                        ELSE 0
                    END
                )
                    AS "Muito Alta",

                SUM(
                    CASE
                        WHEN PRIORIDADE_RECUPERACAO = 'ALTA'
                        THEN 1
                        ELSE 0
                    END
                )
                    AS "Alta",

                ROUND(
                    AVG(MEDIDO_M3_ECON),
                    1
                )
                    AS "Medido/Economia (m³)",

                ROUND(
                    AVG(MEDIO_M3_ECON),
                    1
                )
                    AS "Médio/Economia (m³)",

                ROUND(
                    AVG(QUEDA_PCT),
                    1
                )
                    AS "Queda Média (%)",

                ROUND(
                    SUM(
                        COALESCE(
                            GAP_MEDICAO_M3,
                            0
                        )
                    ),
                    0
                )
                    AS "Volume Estimado (m³/mês)",

                ROUND(
                    SUM(
                        COALESCE(
                            GANHO_TOTAL_ESTIMADO,
                            0
                        )
                    ),
                    2
                )
                    AS "Ganho Estimado (R$/mês)",

                ROUND(
                    AVG(SCORE_RECUPERACAO),
                    1
                )
                    AS "Pontuação Média de Recuperação"

            FROM hidrometria

            {where_hd}

            GROUP BY
                FAIXA_IDADE_HD

            ORDER BY
                CASE FAIXA_IDADE_HD
                    WHEN '<5' THEN 1
                    WHEN '5–7' THEN 2
                    WHEN '8–9' THEN 3
                    WHEN '10–14' THEN 4
                    WHEN '15+' THEN 5
                    ELSE 6
                END
            """,
            VERSAO,
        )


        exibir_dataframe(
            df,
            use_container_width=True,
            hide_index=True,
        )


# ==========================================================
# HIDROMETRIA - PROBLEMAS
# ==========================================================

    elif tela == "⚠️ Problemas Identificados":

        st.subheader(
            "Problema × Consumo × Volume × Ganho"
        )


        df = consultar_df(
            f"""
            {cte_hidrometria()}

            SELECT

                COALESCE(
                    OCORRENCIA_HD,
                    NULLIF(
                        TRIM(ANOM_LEITURA),
                        ''
                    ),
                    'SEM OCORRÊNCIA'
                )
                    AS "Problema Identificado",

                COUNT(*)
                    AS "Hidrômetros",

                SUM(
                    CASE
                        WHEN PRIORIDADE_RECUPERACAO = 'MUITO ALTA'
                        THEN 1
                        ELSE 0
                    END
                )
                    AS "Muito Alta",

                SUM(
                    CASE
                        WHEN PRIORIDADE_RECUPERACAO = 'ALTA'
                        THEN 1
                        ELSE 0
                    END
                )
                    AS "Alta",

                ROUND(
                    AVG(MEDIDO_M3_ECON),
                    1
                )
                    AS "Medido/Economia (m³)",

                ROUND(
                    AVG(FATURADO_M3_ECON),
                    1
                )
                    AS "Faturado/Economia (m³)",

                ROUND(
                    AVG(MEDIO_M3_ECON),
                    1
                )
                    AS "Médio/Economia (m³)",

                ROUND(
                    AVG(QUEDA_PCT),
                    1
                )
                    AS "Queda Média (%)",

                ROUND(
                    SUM(
                        COALESCE(
                            GAP_MEDICAO_M3,
                            0
                        )
                    ),
                    0
                )
                    AS "Volume Estimado (m³/mês)",

                ROUND(
                    SUM(
                        COALESCE(
                            GANHO_TOTAL_ESTIMADO,
                            0
                        )
                    ),
                    2
                )
                    AS "Ganho Estimado (R$/mês)",

                ROUND(
                    AVG(SCORE_RECUPERACAO),
                    1
                )
                    AS "Pontuação Média de Recuperação"

            FROM hidrometria

            {where_hd}

            GROUP BY 1

            ORDER BY
                "Ganho Estimado (R$/mês)" DESC,
                "Muito Alta" DESC
            """,
            VERSAO,
        )


        exibir_dataframe(
            df,
            use_container_width=True,
            hide_index=True,
        )


# ==========================================================
# HIDROMETRIA - CRUZAMENTOS
# ==========================================================

    elif tela == "🔀 Cruzamentos":

        st.subheader(
            "Cruzamentos da Hidrometria"
        )

        st.caption(
            "Escolha duas dimensões para analisar juntas."
        )


        dimensoes = {
            "GNM": "GNM",
            "Localidade": "LOCALIDADE",
            "Município": "MUNICIPIO",
            "Bairro": "BAIRRO",
            "Perfil": "PERFIL",
            "Categoria": "CATEGORIA",
            "Faixa 10 m³/Economia": "FAIXA_10_M3",
            "Quantidade de Economias": "FAIXA_ECONOMIAS",
            "Idade do Hidrômetro": "FAIXA_IDADE_HD",
            "Consumo Medido/Economia": "FAIXA_MEDIDO_ECON",
            "Consumo Faturado/Economia": "FAIXA_FATURADO_ECON",
            "Capacidade do Hidrômetro": "CAPACIDADE_HD",
            "Situação do Esgoto": "SITUACAO_ESGOTO",
            "Problema do Hidrômetro": "OCORRENCIA_HD",
            "Prioridade de Recuperação": "PRIORIDADE_RECUPERACAO",
            "Motivo da Recuperação": "MOTIVO_RECUPERACAO_HD",
            "Prioridade Técnica": "PRIORIDADE_TECNICA",
            "Motivo Técnico": "MOTIVO_TECNICO",
        }


        col1, col2 = st.columns(2)


        eixo_1 = col1.selectbox(
            "Primeiro cruzamento",
            list(dimensoes.keys()),
            index=4,
        )


        eixo_2 = col2.selectbox(
            "Segundo cruzamento",
            list(dimensoes.keys()),
            index=6,
        )


        campo_1 = dimensoes[eixo_1]
        campo_2 = dimensoes[eixo_2]


        df = consultar_df(
            f"""
            {cte_hidrometria()}

            SELECT

                COALESCE(
                    CAST(
                        {campo_1}
                        AS VARCHAR
                    ),
                    'NÃO INFORMADO'
                )
                    AS "{eixo_1}",

                COALESCE(
                    CAST(
                        {campo_2}
                        AS VARCHAR
                    ),
                    'NÃO INFORMADO'
                )
                    AS "{eixo_2}",

                COUNT(*)
                    AS "Hidrômetros",

                SUM(
                    CASE
                        WHEN PRIORIDADE_RECUPERACAO IN (
                            'MUITO ALTA',
                            'ALTA'
                        )
                        THEN 1
                        ELSE 0
                    END
                )
                    AS "Prioritários",

                ROUND(
                    AVG(MEDIDO_M3_ECON),
                    1
                )
                    AS "Medido/Economia (m³)",

                ROUND(
                    AVG(MEDIO_M3_ECON),
                    1
                )
                    AS "Médio/Economia (m³)",

                ROUND(
                    SUM(
                        COALESCE(
                            GAP_MEDICAO_M3,
                            0
                        )
                    ),
                    0
                )
                    AS "Volume Estimado (m³/mês)",

                ROUND(
                    SUM(
                        COALESCE(
                            GANHO_TOTAL_ESTIMADO,
                            0
                        )
                    ),
                    2
                )
                    AS "Ganho Estimado (R$/mês)",

                ROUND(
                    AVG(SCORE_RECUPERACAO),
                    1
                )
                    AS "Pontuação Média de Recuperação"

            FROM hidrometria

            {where_hd}

            GROUP BY
                {campo_1},
                {campo_2}

            ORDER BY
                "Ganho Estimado (R$/mês)" DESC,
                "Volume Estimado (m³/mês)" DESC

            LIMIT 2000
            """,
            VERSAO,
        )


        exibir_dataframe(
            df,
            use_container_width=True,
            hide_index=True,
        )


# ==========================================================
# HIDROMETRIA - LISTA
# ==========================================================

    elif tela == "📋 Lista de Imóveis":

        st.subheader(
            "Prioridades para Troca"
        )


        limite = st.selectbox(
            "Quantidade exibida",
            [
                100,
                500,
                1000,
                5000,
                10000,
            ],
            index=1,
        )


        df = consultar_df(
            f"""
            {cte_hidrometria()}

            SELECT

                MATRICULA AS "Matrícula",

                PRIORIDADE_RECUPERACAO
                    AS "Prioridade de Recuperação",

                PRIORIDADE_TECNICA
                    AS "Prioridade Técnica",

                MOTIVO_RECUPERACAO_HD
                    AS "Motivo da Recuperação",

                MOTIVO_TECNICO
                    AS "Motivo Técnico",
                GNM AS "GNM",
                LOCALIDADE AS "Localidade",
                MUNICIPIO AS "Município",
                BAIRRO AS "Bairro",
                PERFIL AS "Perfil",
                CATEGORIA AS "Categoria",
                SUBCATEGORIA AS "Subcategoria",
                ECONOMIAS AS "Economias",

                FAIXA_10_M3
                    AS "Faixa 10 m³/Economia",

                CAPACIDADE_HD
                    AS "Capacidade",

                SITUACAO_ESGOTO
                    AS "Situação Esgoto",

                ROUND(
                    CONSUMO_MEDIDO,
                    1
                )
                    AS "Consumo Medido (m³)",

                ROUND(
                    CONSUMO_FATURADO,
                    1
                )
                    AS "Consumo Faturado (m³)",

                ROUND(
                    CONSUMO_MEDIO,
                    1
                )
                    AS "Consumo Médio (m³)",

                ROUND(
                    MEDIDO_M3_ECON,
                    1
                )
                    AS "Medido/Economia (m³)",

                ROUND(
                    FATURADO_M3_ECON,
                    1
                )
                    AS "Faturado/Economia (m³)",

                ROUND(
                    MEDIO_M3_ECON,
                    1
                )
                    AS "Médio/Economia (m³)",

                ROUND(
                    QUEDA_PCT,
                    1
                )
                    AS "Queda (%)",

                ROUND(
                    GAP_MEDICAO_M3,
                    1
                )
                    AS "Volume Estimado (m³/mês)",

                ROUND(
                    FAT_ATUAL_INFORMADO,
                    2
                )
                    AS "Faturamento Atual Informado (R$)",

                ROUND(
                    FAT_ATUAL_TOTAL_SIM,
                    2
                )
                    AS "Faturamento Atual Simulado (R$)",

                ROUND(
                    FAT_POTENCIAL_TOTAL_SIM,
                    2
                )
                    AS "Faturamento Potencial (R$)",

                ROUND(
                    GANHO_TOTAL_ESTIMADO,
                    2
                )
                    AS "Ganho Estimado (R$/mês)",

                IDADE_HD
                    AS "Idade HD",

                ANOM_LEITURA
                    AS "Problema de Leitura",

                ANOM_CONSUMO
                    AS "Problema de Consumo",

                RISCO_HD
                    AS "Risco do Hidrômetro",

                RISCO_COMERCIAL
                    AS "Risco de Perda",

                SCORE_RECUPERACAO
                    AS "Pontuação de Recuperação"

            FROM hidrometria

            {where_hd}

            ORDER BY

                CASE PRIORIDADE_RECUPERACAO
                    WHEN 'MUITO ALTA' THEN 1
                    WHEN 'ALTA' THEN 2
                    WHEN 'MÉDIA' THEN 3
                    ELSE 4
                END,

                GANHO_TOTAL_ESTIMADO DESC,
                GAP_MEDICAO_M3 DESC,
                SCORE_RECUPERACAO DESC

            LIMIT {limite}
            """,
            VERSAO,
        )


        exibir_dataframe(
            df,
            use_container_width=True,
            hide_index=True,
        )


        st.download_button(
            "📥 Exportar prioridades",
            df.to_csv(
                index=False
            ).encode(
                "utf-8-sig"
            ),
            "prioridades_hidrometros.csv",
            "text/csv",
        )


# ==========================================================
# RECUPERAÇÃO DE LIGAÇÕES
# ==========================================================

elif area == "🔎 RECUPERAÇÃO DE LIGAÇÕES":

    tela = st.radio(
        "Visão",
        [
            "📊 Resumo",
            "🚫 Situação das Ligações",
            "💰 Potencial de Recuperação",
            "🎯 Prioridades",
            "🔀 Cruzamentos",
            "🗂️ Consulta Geral",
        ],
        horizontal=True,
        label_visibility="collapsed",
    )


    condicoes_rec = list(
        condicoes_gerais
    )


    with st.sidebar.expander(
        "🔎 Filtros da Recuperação",
        expanded=True,
    ):

        where_opcoes_rec = montar_where(
            condicoes_gerais
        )


        situacoes = consultar_lista(
            f"""
            SELECT DISTINCT SITUACAO
            FROM {BASE}
            {where_opcoes_rec}
            {"AND" if where_opcoes_rec else "WHERE"}
                SITUACAO IS NOT NULL
                AND TRIM(SITUACAO) <> ''
            ORDER BY SITUACAO
            """,
            VERSAO,
        )


        filtro_situacao = st.multiselect(
            "Situação da ligação",
            situacoes,
            help=(
                "É possível selecionar várias situações, "
                "como CORTADO + SUPRIMIDO."
            ),
        )


        condicao = sql_in(
            "SITUACAO",
            filtro_situacao,
        )

        if condicao:
            condicoes_rec.append(
                condicao
            )


        filtro_status_hd = st.multiselect(
            "Situação do hidrômetro",
            [
                "COM HIDRÔMETRO",
                "SEM HIDRÔMETRO",
            ],
        )


        condicao = sql_in(
            "STATUS_HD",
            filtro_status_hd,
        )

        if condicao:
            condicoes_rec.append(
                condicao
            )


        filtro_indicio = st.multiselect(
            "Indício / ocorrência",
            [
                "BYPASS",
                "BOMBA LIGADA À REDE",
                "FORNECIMENTO INDEVIDO",
                "HD SEM LACRE",
                "HD DIVERGENTE",
                "HD RETIRADO / NÃO LOCALIZADO",
            ],
        )


        condicao = sql_in(
            "OCORRENCIA_FISCAL",
            filtro_indicio,
        )

        if condicao:
            condicoes_rec.append(
                condicao
            )


        filtro_consumo_inativo = st.multiselect(
            "Consumo em ligação inativa",
            [
                "COM CONSUMO",
                "SEM CONSUMO",
            ],
        )


        if filtro_consumo_inativo:

            sub = []

            if "COM CONSUMO" in filtro_consumo_inativo:
                sub.append(
                    "COALESCE(CONSUMO_MEDIDO, 0) > 0"
                )

            if "SEM CONSUMO" in filtro_consumo_inativo:
                sub.append(
                    "COALESCE(CONSUMO_MEDIDO, 0) <= 0"
                )

            if sub:
                condicoes_rec.append(
                    "("
                    +
                    " OR ".join(sub)
                    +
                    ")"
                )


        st.divider()
        st.markdown("**🎯 Capacidade Operacional**")

        qtd_fiscalizacoes = st.number_input(
            "Quantidade de fiscalizações desejada",
            min_value=1,
            max_value=50000,
            value=500,
            step=100,
            key="parametro_qtd_fiscalizacoes_v20",
            help=(
                "Premissa de simulação. Não limita o painel. "
                "Os cards e tabelas gerais continuam mostrando toda a base filtrada; "
                "somente o cenário de capacidade usa os melhores casos "
                "até a quantidade informada."
            ),
        )

        st.caption(
            "Premissa de simulação — não limita as demais visões."
        )


    where_rec = montar_where(
        condicoes_rec
    )


# ==========================================================
# RECUPERAÇÃO - RESUMO
# ==========================================================

    if tela == "📊 Resumo":

        resumo = consultar_linha(
            f"""
            {cte_recuperacao()}

            SELECT

                COUNT(*),

                SUM(
                    CASE
                        WHEN COALESCE(
                            SITUACAO,
                            ''
                        ) <> 'LIGADO'
                        THEN 1
                        ELSE 0
                    END
                ),

                SUM(
                    CASE
                        WHEN COALESCE(
                            SITUACAO,
                            ''
                        ) <> 'LIGADO'
                        AND COALESCE(
                            CONSUMO_MEDIDO,
                            0
                        ) > 0
                        THEN 1
                        ELSE 0
                    END
                ),

                SUM(
                    CASE
                        WHEN PRIORIDADE_RECUPERACAO = 'CRÍTICA'
                        THEN 1
                        ELSE 0
                    END
                ),

                SUM(
                    CASE
                        WHEN PRIORIDADE_RECUPERACAO = 'ALTA'
                        THEN 1
                        ELSE 0
                    END
                ),

                SUM(
                    COALESCE(
                        INCREMENTO_ESTIMADO_M3,
                        0
                    )
                ),

                SUM(
                    COALESCE(
                        INCREMENTO_ESTIMADO_RS,
                        0
                    )
                )

            FROM recuperacao

            {where_rec}
            """,
            VERSAO,
        )


        c1, c2, c3, c4, c5, c6, c7 = st.columns(7)


        c1.metric(
            "Casos p/ Análise",
            formatar_executivo(
                resumo[0],
                1,
            )
        )

        c2.metric(
            "Ligações Inativas",
            formatar_executivo(
                resumo[1],
                1,
            )
        )

        c3.metric(
            "Inativas c/ Consumo",
            formatar_executivo(
                resumo[2],
                1,
            )
        )

        c4.metric(
            "Prioridade Crítica",
            formatar_executivo(
                resumo[3],
                1,
            )
        )

        c5.metric(
            "Prioridade Alta",
            formatar_executivo(
                resumo[4],
                1,
            )
        )

        c6.metric(
            "Volume Estimado",
            formatar_volume_executivo(
                resumo[5],
                2,
            )
        )

        c7.metric(
            "Incremento Estimado",
            formatar_moeda_executiva(
                resumo[6],
                2,
            )
        )


        st.info(
            "Consumo, bypass ou outra ocorrência em ligação "
            "cortada, suprimida ou inativa é um indicativo "
            "para fiscalização e recuperação da ligação. "
            "Não representa confirmação automática de fraude."
        )


        # ======================================================
        # V20 - CENÁRIO DA CAPACIDADE OPERACIONAL - FISCALIZAÇÃO
        # ======================================================
        st.markdown(
            f"**🎯 Cenário da capacidade: {int(qtd_fiscalizacoes):,} fiscalizações**".replace(",", ".")
        )
        st.caption(
            "Resultado dos melhores casos dentro dos filtros atuais. "
            "A quantidade é apenas uma premissa de simulação e não limita o painel."
        )

        sim_rec = consultar_linha(
            f"""
            {cte_recuperacao()}

            , selecionados AS (
                SELECT *
                FROM recuperacao
                {where_rec}
                ORDER BY
                    CASE PRIORIDADE_RECUPERACAO
                        WHEN 'CRÍTICA' THEN 1
                        WHEN 'ALTA' THEN 2
                        WHEN 'MÉDIA' THEN 3
                        ELSE 4
                    END,
                    SCORE_FISCALIZACAO DESC,
                    INCREMENTO_ESTIMADO_RS DESC,
                    INCREMENTO_ESTIMADO_M3 DESC
                LIMIT {int(qtd_fiscalizacoes)}
            )

            SELECT
                COUNT(*) AS QTD,
                SUM(CASE WHEN PRIORIDADE_RECUPERACAO = 'CRÍTICA' THEN 1 ELSE 0 END) AS CRITICA,
                SUM(CASE WHEN PRIORIDADE_RECUPERACAO = 'ALTA' THEN 1 ELSE 0 END) AS ALTA,
                SUM(COALESCE(INCREMENTO_ESTIMADO_M3, 0)) AS VOLUME,
                SUM(COALESCE(INCREMENTO_ESTIMADO_RS, 0)) AS GANHO,
                AVG(COALESCE(INCREMENTO_ESTIMADO_RS, 0)) AS GANHO_MEDIO
            FROM selecionados
            """,
            VERSAO,
        )

        r1, r2, r3, r4, r5, r6 = st.columns(6)

        r1.metric(
            "Fiscalizações Selecionadas",
            formatar_executivo(sim_rec[0], 1),
        )
        r2.metric(
            "Prioridade Crítica",
            formatar_executivo(sim_rec[1], 1),
        )
        r3.metric(
            "Prioridade Alta",
            formatar_executivo(sim_rec[2], 1),
        )
        r4.metric(
            "Volume Estimado",
            formatar_volume_executivo(sim_rec[3], 2),
        )
        r5.metric(
            "Incremento Estimado",
            formatar_moeda_executiva(sim_rec[4], 2),
        )
        r6.metric(
            "Média / Fiscalização",
            formatar_moeda(sim_rec[5]),
        )

        st.caption(
            "Seleção recomendada = melhores casos dentro dos filtros atuais. "
            "Trata-se de uma priorização para fiscalização, não de confirmação de irregularidade."
        )

        with st.expander("📋 Ver seleção recomendada para a capacidade informada", expanded=False):
            limite_sim_rec = min(int(qtd_fiscalizacoes), 3000)

            df_sim_rec = consultar_df(
                f"""
                {cte_recuperacao()}

                SELECT
                    MATRICULA AS "Matrícula",
                    SITUACAO AS "Situação Água",
                    SITUACAO_ESGOTO AS "Situação Esgoto",
                    GNM AS "GNM",
                    LOCALIDADE AS "Localidade",
                    MUNICIPIO AS "Município",
                    BAIRRO AS "Bairro",
                    PERFIL AS "Perfil",
                    CATEGORIA AS "Categoria",
                    ECONOMIAS AS "Economias",
                    STATUS_HD AS "Hidrômetro",
                    OCORRENCIA_FISCAL AS "Indício / Ocorrência",
                    MOTIVO_RECUPERACAO AS "Motivo",
                    SCORE_FISCALIZACAO AS "Pontuação",
                    PRIORIDADE_RECUPERACAO AS "Prioridade",
                    ROUND(INCREMENTO_ESTIMADO_M3, 1) AS "Volume Estimado (m³/mês)",
                    ROUND(INCREMENTO_ESTIMADO_RS, 2) AS "Incremento Estimado (R$/mês)"
                FROM recuperacao
                {where_rec}
                ORDER BY
                    CASE PRIORIDADE_RECUPERACAO
                        WHEN 'CRÍTICA' THEN 1
                        WHEN 'ALTA' THEN 2
                        WHEN 'MÉDIA' THEN 3
                        ELSE 4
                    END,
                    SCORE_FISCALIZACAO DESC,
                    INCREMENTO_ESTIMADO_RS DESC,
                    INCREMENTO_ESTIMADO_M3 DESC
                LIMIT {limite_sim_rec}
                """,
                VERSAO,
            )

            exibir_dataframe(
                df_sim_rec,
                use_container_width=True,
                hide_index=True,
            )

            st.download_button(
                "📥 Exportar seleção recomendada de fiscalizações",
                df_sim_rec.to_csv(index=False).encode("utf-8-sig"),
                "selecao_recomendada_fiscalizacoes.csv",
                "text/csv",
            )

            if int(qtd_fiscalizacoes) > 3000:
                st.caption(
                    "A seleção total considera a quantidade informada. "
                    "A tabela é limitada às 3.000 primeiras linhas para manter o painel rápido."
                )


# ==========================================================
# RECUPERAÇÃO - SITUAÇÕES
# ==========================================================

    elif tela == "🚫 Situação das Ligações":

        st.subheader(
            "Situação × Consumo × Potencial Financeiro"
        )


        df = consultar_df(
            f"""
            {cte_recuperacao()}

            SELECT

                COALESCE(
                    NULLIF(
                        TRIM(SITUACAO),
                        ''
                    ),
                    'NÃO INFORMADA'
                )
                    AS "Situação",

                COUNT(*)
                    AS "Imóveis",

                SUM(
                    CASE
                        WHEN STATUS_HD = 'COM HIDRÔMETRO'
                        THEN 1
                        ELSE 0
                    END
                )
                    AS "Com Hidrômetro",

                SUM(
                    CASE
                        WHEN STATUS_HD = 'SEM HIDRÔMETRO'
                        THEN 1
                        ELSE 0
                    END
                )
                    AS "Sem Hidrômetro",

                SUM(
                    CASE
                        WHEN COALESCE(
                            CONSUMO_MEDIDO,
                            0
                        ) > 0
                        THEN 1
                        ELSE 0
                    END
                )
                    AS "Com Consumo Medido",

                ROUND(
                    100.0
                    *
                    SUM(
                        CASE
                            WHEN COALESCE(
                                CONSUMO_MEDIDO,
                                0
                            ) > 0
                            THEN 1
                            ELSE 0
                        END
                    )
                    /
                    NULLIF(
                        COUNT(*),
                        0
                    ),
                    1
                )
                    AS "Com Consumo (%)",

                ROUND(
                    SUM(
                        COALESCE(
                            INCREMENTO_ESTIMADO_M3,
                            0
                        )
                    ),
                    0
                )
                    AS "Volume Estimado (m³/mês)",

                ROUND(
                    SUM(
                        COALESCE(
                            FAT_ATUAL_TOTAL_SIM,
                            0
                        )
                    ),
                    2
                )
                    AS "Faturamento Atual Simulado (R$)",

                ROUND(
                    SUM(
                        COALESCE(
                            FAT_REGULAR_TOTAL_SIM,
                            0
                        )
                    ),
                    2
                )
                    AS "Faturamento Regularizado (R$)",

                ROUND(
                    SUM(
                        COALESCE(
                            INCREMENTO_ESTIMADO_RS,
                            0
                        )
                    ),
                    2
                )
                    AS "Incremento Estimado (R$/mês)"

            FROM recuperacao

            {where_rec}

            GROUP BY 1

            ORDER BY
                "Incremento Estimado (R$/mês)" DESC
            """,
            VERSAO,
        )


        exibir_dataframe(
            df,
            use_container_width=True,
            hide_index=True,
        )


# ==========================================================
# RECUPERAÇÃO - POTENCIAL FINANCEIRO
# ==========================================================

    elif tela == "💰 Potencial de Recuperação":

        st.subheader(
            "Potencial de Recuperação dos Inativos"
        )


        financeiro = consultar_linha(
            f"""
            {cte_recuperacao()}

            SELECT

                SUM(
                    COALESCE(
                        FAT_ATUAL_INFORMADO,
                        0
                    )
                ),

                SUM(
                    COALESCE(
                        FAT_ATUAL_TOTAL_SIM,
                        0
                    )
                ),

                SUM(
                    COALESCE(
                        FAT_REGULAR_TOTAL_SIM,
                        0
                    )
                ),

                SUM(
                    COALESCE(
                        INCREMENTO_ESTIMADO_RS,
                        0
                    )
                ),

                SUM(
                    COALESCE(
                        INCREMENTO_ESTIMADO_M3,
                        0
                    )
                )

            FROM recuperacao

            {where_rec}
            """,
            VERSAO,
        )


        df = consultar_df(
            f"""
            {cte_recuperacao()}

            SELECT

                MATRICULA
                    AS "Matrícula",

                SITUACAO
                    AS "Situação Água",

                SITUACAO_ESGOTO
                    AS "Situação Esgoto",

                GNM
                    AS "GNM",

                LOCALIDADE
                    AS "Localidade",

                MUNICIPIO
                    AS "Município",

                BAIRRO
                    AS "Bairro",

                PERFIL
                    AS "Perfil",

                CATEGORIA
                    AS "Categoria",

                ECONOMIAS
                    AS "Economias",

                STATUS_HD
                    AS "Hidrômetro",

                OCORRENCIA_FISCAL
                    AS "Indício / Ocorrência",

                ROUND(
                    CONSUMO_MEDIDO,
                    1
                )
                    AS "Consumo Medido (m³)",

                ROUND(
                    CONSUMO_FATURADO,
                    1
                )
                    AS "Consumo Faturado (m³)",

                ROUND(
                    CONSUMO_MEDIO,
                    1
                )
                    AS "Consumo Médio (m³)",

                ROUND(
                    CONSUMO_REFERENCIA_REC,
                    1
                )
                    AS "Consumo Referência (m³)",

                ROUND(
                    INCREMENTO_ESTIMADO_M3,
                    1
                )
                    AS "Volume Estimado (m³/mês)",

                ROUND(
                    FAT_ATUAL_INFORMADO,
                    2
                )
                    AS "Faturamento Atual Informado (R$)",

                ROUND(
                    FAT_ATUAL_TOTAL_SIM,
                    2
                )
                    AS "Atual Simulado (R$)",

                ROUND(
                    FAT_REGULAR_AGUA,
                    2
                )
                    AS "Regularizado Água (R$)",

                ROUND(
                    FAT_REGULAR_ESGOTO,
                    2
                )
                    AS "Regularizado Esgoto (R$)",

                ROUND(
                    FAT_REGULAR_TOTAL_SIM,
                    2
                )
                    AS "Regularizado Total (R$)",

                ROUND(
                    INCREMENTO_ESTIMADO_RS,
                    2
                )
                    AS "Incremento Estimado (R$/mês)",

                MOTIVO_RECUPERACAO
                    AS "Motivo",

                SCORE_FISCALIZACAO
                    AS "Pontuação",

                PRIORIDADE_RECUPERACAO
                    AS "Prioridade"

            FROM recuperacao

            {where_rec}

            ORDER BY
                INCREMENTO_ESTIMADO_RS DESC,
                SCORE_FISCALIZACAO DESC

            LIMIT 3000
            """,
            VERSAO,
        )


        # V10: o KPI de incremento usa a soma das mesmas linhas exibidas
        # sempre que o resultado filtrado couber integralmente na tabela.
        # Isso garante fechamento direto entre card e detalhamento.
        if len(df) < 3000:
            incremento_kpi = float(
                df["Incremento Estimado (R$/mês)"].fillna(0).sum()
            )
        else:
            incremento_kpi = float(financeiro[3] or 0)

        # V12: cards HTML para exibir exatamente as strings já formatadas.
        # Nenhum cálculo financeiro foi alterado nesta versão.
        # V13: nesta tela, valores financeiros são exibidos por extenso,
        # sem escala automática (mil/milhões). Isso elimina qualquer
        # ambiguidade visual e preserva exatamente o valor calculado.
        def moeda_card_exata(valor):
            try:
                valor = float(valor or 0)
            except Exception:
                valor = 0.0
            texto = f"{valor:,.2f}"
            texto = texto.replace(",", "X").replace(".", ",").replace("X", ".")
            return f"R$ {texto}"

        valores_cards = [
            ("Faturamento Atual Informado", moeda_card_exata(financeiro[0])),
            ("Atual Simulado", moeda_card_exata(financeiro[1])),
            ("Regularizado Estimado", moeda_card_exata(financeiro[2])),
            ("Incremento Estimado / mês", moeda_card_exata(incremento_kpi)),
            ("Volume Estimado / mês", formatar_volume(financeiro[4])),
        ]

        colunas_cards = st.columns(5)
        for coluna, (rotulo, valor) in zip(colunas_cards, valores_cards):
            with coluna:
                st.markdown(
                    f"""
                    <div style="padding: 0.15rem 0 0.65rem 0;">
                        <div style="font-size: 0.95rem; font-weight: 600; margin-bottom: 0.30rem;">
                            {rotulo}
                        </div>
                        <div style="font-size: 1.75rem; line-height: 1.15; white-space: nowrap;">
                            {valor}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        st.caption(
            f"Para ligações cortadas, a simulação atual considera "
            f"{fator_cortado}% da tarifa de água. Quando o esgoto estiver "
            f"LIGADO ou FACTÍVEL FATURÁVEL, o faturamento de esgoto é "
            f"mantido na situação atual e não é contado novamente como "
            f"recuperação. Essa premissa pode ser alterada no menu lateral."
        )

        # Validação de consistência entre os KPIs e os registros exibidos.
        # Quando o resultado filtrado cabe integralmente na tabela (menos de 3000 linhas),
        # os totais precisam fechar com os cards acima.
        if len(df) < 3000:
            controles = [
                ("Faturamento Atual Informado", "Faturamento Atual Informado (R$)", financeiro[0], 0.05),
                ("Atual Simulado", "Atual Simulado (R$)", financeiro[1], 0.05),
                ("Regularizado Estimado", "Regularizado Total (R$)", financeiro[2], 0.05),
                ("Incremento Estimado", "Incremento Estimado (R$/mês)", incremento_kpi, 0.05),
                ("Volume Estimado", "Volume Estimado (m³/mês)", financeiro[4], 0.15),
            ]

            divergencias = []
            for rotulo, coluna, total_card, tolerancia_por_linha in controles:
                total_tabela = float(df[coluna].fillna(0).sum())
                total_card = float(total_card or 0)
                tolerancia = max(0.05, len(df) * tolerancia_por_linha)
                if abs(total_tabela - total_card) > tolerancia:
                    divergencias.append(
                        f"{rotulo}: card={total_card:.2f} | tabela={total_tabela:.2f}"
                    )

            if divergencias:
                st.error(
                    "Divergência de consistência identificada: "
                    + " ; ".join(divergencias)
                )

        exibir_dataframe(
            df,
            use_container_width=True,
            hide_index=True,
        )


# ==========================================================
# RECUPERAÇÃO - PRIORIDADES
# ==========================================================

    elif tela == "🎯 Prioridades":

        st.subheader(
            "Prioridades de Recuperação"
        )


        limite = st.selectbox(
            "Quantidade exibida",
            [
                100,
                500,
                1000,
                5000,
                10000,
            ],
            index=1,
        )


        df = consultar_df(
            f"""
            {cte_recuperacao()}

            SELECT

                MATRICULA AS "Matrícula",
                SITUACAO AS "Situação Água",
                SITUACAO_ESGOTO AS "Situação Esgoto",
                GNM AS "GNM",
                LOCALIDADE AS "Localidade",
                MUNICIPIO AS "Município",
                BAIRRO AS "Bairro",
                PERFIL AS "Perfil",
                CATEGORIA AS "Categoria",
                ECONOMIAS AS "Economias",
                STATUS_HD AS "Hidrômetro",

                ROUND(
                    CONSUMO_MEDIDO,
                    1
                )
                    AS "Consumo Medido (m³)",

                ROUND(
                    CONSUMO_MEDIO,
                    1
                )
                    AS "Consumo Médio (m³)",

                ROUND(
                    INCREMENTO_ESTIMADO_M3,
                    1
                )
                    AS "Volume Estimado (m³/mês)",

                OCORRENCIA_FISCAL
                    AS "Indício / Ocorrência",

                MOTIVO_RECUPERACAO
                    AS "Motivo",

                ROUND(
                    FAT_ATUAL_TOTAL_SIM,
                    2
                )
                    AS "Atual Simulado (R$)",

                ROUND(
                    FAT_REGULAR_TOTAL_SIM,
                    2
                )
                    AS "Regularizado Estimado (R$)",

                ROUND(
                    INCREMENTO_ESTIMADO_RS,
                    2
                )
                    AS "Incremento Estimado (R$/mês)",

                SCORE_FISCALIZACAO
                    AS "Pontuação",

                PRIORIDADE_RECUPERACAO
                    AS "Prioridade"

            FROM recuperacao

            {where_rec}

            ORDER BY

                CASE PRIORIDADE_RECUPERACAO
                    WHEN 'CRÍTICA' THEN 1
                    WHEN 'ALTA' THEN 2
                    WHEN 'MÉDIA' THEN 3
                    ELSE 4
                END,

                SCORE_FISCALIZACAO DESC,
                INCREMENTO_ESTIMADO_RS DESC

            LIMIT {limite}
            """,
            VERSAO,
        )


        exibir_dataframe(
            df,
            use_container_width=True,
            hide_index=True,
        )


        st.download_button(
            "📥 Exportar prioridades",
            df.to_csv(
                index=False
            ).encode(
                "utf-8-sig"
            ),
            "prioridades_recuperacao_ligacoes.csv",
            "text/csv",
        )


# ==========================================================
# RECUPERAÇÃO - CRUZAMENTOS
# ==========================================================

    elif tela == "🔀 Cruzamentos":

        st.subheader(
            "Cruzamentos da Recuperação"
        )


        dimensoes_rec = {
            "Situação da Ligação": "SITUACAO",
            "Situação do Esgoto": "SITUACAO_ESGOTO",
            "Situação do Hidrômetro": "STATUS_HD",
            "GNM": "GNM",
            "Localidade": "LOCALIDADE",
            "Município": "MUNICIPIO",
            "Bairro": "BAIRRO",
            "Perfil": "PERFIL",
            "Categoria": "CATEGORIA",
            "Quantidade de Economias": "FAIXA_ECONOMIAS",
            "Indício / Ocorrência": "OCORRENCIA_FISCAL",
            "Motivo": "MOTIVO_RECUPERACAO",
            "Prioridade": "PRIORIDADE_RECUPERACAO",
        }


        col1, col2 = st.columns(2)


        eixo_1 = col1.selectbox(
            "Primeiro cruzamento",
            list(
                dimensoes_rec.keys()
            ),
            index=0,
            key="rec_eixo_1",
        )


        eixo_2 = col2.selectbox(
            "Segundo cruzamento",
            list(
                dimensoes_rec.keys()
            ),
            index=10,
            key="rec_eixo_2",
        )


        campo_1 = dimensoes_rec[eixo_1]
        campo_2 = dimensoes_rec[eixo_2]


        df = consultar_df(
            f"""
            {cte_recuperacao()}

            SELECT

                COALESCE(
                    CAST(
                        {campo_1}
                        AS VARCHAR
                    ),
                    'NÃO INFORMADO'
                )
                    AS "{eixo_1}",

                COALESCE(
                    CAST(
                        {campo_2}
                        AS VARCHAR
                    ),
                    'NÃO INFORMADO'
                )
                    AS "{eixo_2}",

                COUNT(*)
                    AS "Imóveis",

                SUM(
                    CASE
                        WHEN COALESCE(
                            CONSUMO_MEDIDO,
                            0
                        ) > 0
                        THEN 1
                        ELSE 0
                    END
                )
                    AS "Com Consumo Medido",

                ROUND(
                    SUM(
                        COALESCE(
                            INCREMENTO_ESTIMADO_M3,
                            0
                        )
                    ),
                    0
                )
                    AS "Volume Estimado (m³/mês)",

                ROUND(
                    SUM(
                        COALESCE(
                            INCREMENTO_ESTIMADO_RS,
                            0
                        )
                    ),
                    2
                )
                    AS "Incremento Estimado (R$/mês)",

                ROUND(
                    AVG(
                        SCORE_FISCALIZACAO
                    ),
                    1
                )
                    AS "Pontuação Média"

            FROM recuperacao

            {where_rec}

            GROUP BY
                {campo_1},
                {campo_2}

            ORDER BY
                "Incremento Estimado (R$/mês)" DESC,
                "Pontuação Média" DESC

            LIMIT 2000
            """,
            VERSAO,
        )


        exibir_dataframe(
            df,
            use_container_width=True,
            hide_index=True,
        )


# ==========================================================
# CONSULTA GERAL
# ==========================================================

    elif tela == "🗂️ Consulta Geral":

        st.subheader(
            "Consulta Geral da Base"
        )


        resumo = consultar_linha(
            f"""
            SELECT

                COUNT(*),

                SUM(
                    CASE
                        WHEN SITUACAO = 'LIGADO'
                        THEN 1
                        ELSE 0
                    END
                ),

                SUM(
                    CASE
                        WHEN COALESCE(
                            SITUACAO,
                            ''
                        ) <> 'LIGADO'
                        THEN 1
                        ELSE 0
                    END
                ),

                SUM(
                    CASE
                        WHEN STATUS_HD = 'COM HIDRÔMETRO'
                        THEN 1
                        ELSE 0
                    END
                ),

                SUM(
                    CASE
                        WHEN STATUS_HD = 'SEM HIDRÔMETRO'
                        THEN 1
                        ELSE 0
                    END
                ),

                SUM(
                    CASE
                        WHEN COALESCE(
                            EXCLUIDO,
                            ''
                        ) <> 'NAO'
                        THEN 1
                        ELSE 0
                    END
                )

            FROM {BASE}

            {where_rec}
            """,
            VERSAO,
        )


        c1, c2, c3, c4, c5, c6 = st.columns(6)


        c1.metric(
            "Total de Imóveis",
            formatar_inteiro(
                resumo[0]
            )
        )

        c2.metric(
            "Ligados",
            formatar_inteiro(
                resumo[1]
            )
        )

        c3.metric(
            "Outras Situações",
            formatar_inteiro(
                resumo[2]
            )
        )

        c4.metric(
            "Com Hidrômetro",
            formatar_inteiro(
                resumo[3]
            )
        )

        c5.metric(
            "Sem Hidrômetro",
            formatar_inteiro(
                resumo[4]
            )
        )

        c6.metric(
            "Excluídos",
            formatar_inteiro(
                resumo[5]
            )
        )


        limite = st.selectbox(
            "Quantidade exibida",
            [
                100,
                500,
                1000,
                5000,
                10000,
            ],
            index=1,
        )


        df = consultar_df(
            f"""
            SELECT

                MATRICULA
                    AS "Matrícula",

                SITUACAO
                    AS "Situação Água",

                SITUACAO_ESGOTO
                    AS "Situação Esgoto",

                EXCLUIDO
                    AS "Excluído",

                GNM
                    AS "GNM",

                LOCALIDADE
                    AS "Localidade",

                MUNICIPIO
                    AS "Município",

                BAIRRO
                    AS "Bairro",

                PERFIL
                    AS "Perfil",

                CATEGORIA
                    AS "Categoria",

                SUBCATEGORIA
                    AS "Subcategoria",

                ECONOMIAS
                    AS "Economias",

                STATUS_HD
                    AS "Situação do Hidrômetro",

                HIDROMETRO
                    AS "Hidrômetro",

                CAPACIDADE_HD
                    AS "Capacidade",

                IDADE_HD
                    AS "Idade",

                ROUND(
                    CONSUMO_MEDIDO,
                    1
                )
                    AS "Consumo Medido (m³)",

                ROUND(
                    CONSUMO_FATURADO,
                    1
                )
                    AS "Consumo Faturado (m³)",

                ROUND(
                    CONSUMO_MEDIO,
                    1
                )
                    AS "Consumo Médio (m³)",

                ROUND(
                    VALOR_AGUA,
                    2
                )
                    AS "Valor Água (R$)",

                ROUND(
                    VALOR_ESGOTO,
                    2
                )
                    AS "Valor Esgoto (R$)",

                ANOM_LEITURA
                    AS "Problema de Leitura",

                ANOM_CONSUMO
                    AS "Problema de Consumo"

            FROM {BASE}

            {where_rec}

            LIMIT {limite}
            """,
            VERSAO,
        )


        exibir_dataframe(
            df,
            use_container_width=True,
            hide_index=True,
        )


        st.caption(
            "A consulta considera toda a base. "
            "A quantidade exibida é limitada apenas "
            "para manter o painel rápido."
        )


# ==========================================================
# RODAPÉ
# ==========================================================

st.divider()

st.caption(
    "Enorsul | Gestão de Hidrômetros e Recuperação de Ligações | Pernambuco"
)