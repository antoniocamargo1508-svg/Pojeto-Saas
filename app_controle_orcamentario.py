import re
import unicodedata
from io import BytesIO
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


st.set_page_config(
    page_title="Controle Orcamentario",
    layout="wide",
    initial_sidebar_state="expanded",
)


BASE_DIR = Path(__file__).resolve().parent
PATH_ORCADO = BASE_DIR / "orcado.xlsx"
PATH_DIM_CC = BASE_DIR / "dim_centro_custo.xlsx"
PATH_DIM_CONTAS = BASE_DIR / "dim_plano_contas.xlsx"
PATH_DIM_CONTAS_DRE = BASE_DIR / "dim_contas_DRE.xlsx"

MESES_MAP = {
    "jan": 1,
    "fev": 2,
    "mar": 3,
    "abr": 4,
    "mai": 5,
    "jun": 6,
    "jul": 7,
    "ago": 8,
    "set": 9,
    "out": 10,
    "nov": 11,
    "dez": 12,
}

MESES_NOMES = {
    1: "Janeiro",
    2: "Fevereiro",
    3: "Marco",
    4: "Abril",
    5: "Maio",
    6: "Junho",
    7: "Julho",
    8: "Agosto",
    9: "Setembro",
    10: "Outubro",
    11: "Novembro",
    12: "Dezembro",
}

DETAIL_COLUMNS = [
    "ano",
    "mes",
    "centro_custo",
    "gestor",
    "area_setor",
    "conta",
    "descricao_conta",
    "tipo_despesa",
    "categoria_despesas",
    "classificacao_dre",
    "orcado_original",
    "saldo_mes_anterior",
    "orcamento_disponivel",
    "realizado",
    "saldo_final",
    "desvio_vs_orcado",
    "desvio_vs_disponivel",
    "status",
    "tipo_despesa_dim",
]


def slugify(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(text))
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower().strip()
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
    return normalized.strip("_")


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [slugify(col) for col in df.columns]
    return df


def get_file_signature(path: Path) -> str:
    stats = path.stat()
    return f"{path.name}:{stats.st_mtime_ns}:{stats.st_size}"


def get_glob_signature(pattern: str) -> str:
    files = sorted(BASE_DIR.glob(pattern))
    if not files:
        return pattern
    return "|".join(get_file_signature(file) for file in files)


def format_currency(value: float) -> str:
    if value is None or pd.isna(value):
        return "R$ 0,00"
    formatted = f"R$ {value:,.2f}"
    return formatted.replace(",", "X").replace(".", ",").replace("X", ".")


def format_number_br(value: float) -> str:
    if value is None or pd.isna(value):
        return "0,00"
    formatted = f"{value:,.2f}"
    return formatted.replace(",", "X").replace(".", ",").replace("X", ".")


def format_percent(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "n/d"
    formatted = f"{value * 100:,.1f}%"
    return formatted.replace(",", "X").replace(".", ",").replace("X", ".")


def clean_text_value(value: object) -> object:
    if pd.isna(value):
        return pd.NA
    text = str(value).strip()
    if not text:
        return pd.NA
    normalized = slugify(text)
    if normalized in {"nao_informado", "nao_encontrado", "not_found", "nan", "none"}:
        return pd.NA
    return text


def safe_divide(numerator: float, denominator: float) -> float | None:
    if denominator is None or pd.isna(denominator) or abs(float(denominator)) <= 0.005:
        return None
    return float(numerator) / float(denominator)


def invert_ratio(value: float | None) -> float | None:
    if value is None or pd.isna(value):
        return None
    return 1 - float(value)


def normalize_expense_type_bucket(value: object) -> str:
    cleaned = clean_text_value(value)
    if pd.isna(cleaned):
        return "Outros"
    normalized = slugify(str(cleaned))
    if normalized.startswith("fix"):
        return "Fixa"
    if normalized.startswith("variavel"):
        return "Variavel"
    return "Outros"


def get_month_name(month: int) -> str:
    return MESES_NOMES.get(int(month), f"Mes {month}")


def get_month_filter_label(month: int) -> str:
    if int(month) == 0:
        return "Todos os meses"
    return get_month_name(int(month))


def resolve_period_selection(visao: str, mes_escolhido: int) -> tuple[str, int]:
    visao_resolvida = str(visao).strip()
    if visao_resolvida not in {"Mensal", "Acumulado"}:
        visao_resolvida = "Mensal"

    try:
        mes_resolvido = int(mes_escolhido)
    except (TypeError, ValueError):
        mes_resolvido = 0

    if mes_resolvido not in range(0, 13):
        mes_resolvido = 0

    return visao_resolvida, mes_resolvido


def build_period_labels(visao: str, mes_escolhido: int) -> tuple[str, str, str]:
    month_label = get_month_filter_label(mes_escolhido)
    if visao == "Mensal":
        return (
            f"Periodo ativo: Mensal | {month_label}",
            f"Resumo Mensal - {month_label}",
            f"Realizado Nao Previsto - {month_label}",
        )

    if mes_escolhido == 0:
        return (
            "Periodo ativo: Acumulado | Todos os meses",
            "Resumo Acumulado - Todos os meses",
            "Realizado Nao Previsto Acumulado - Todos os meses",
        )

    month_name = get_month_name(mes_escolhido)
    return (
        f"Periodo ativo: Acumulado | Ate {month_name}",
        f"Resumo Acumulado - Ate {month_name}",
        f"Realizado Nao Previsto Acumulado - Ate {month_name}",
    )


def build_period_context(visao: str, mes_escolhido: int) -> dict[str, str | int]:
    visao, mes_escolhido = resolve_period_selection(visao, mes_escolhido)
    periodo_ativo, titulo_resumo, titulo_nao_previsto = build_period_labels(visao, mes_escolhido)
    return {
        "visao": visao,
        "mes_escolhido": mes_escolhido,
        "periodo_ativo": periodo_ativo,
        "titulo_resumo": titulo_resumo,
        "titulo_nao_previsto": titulo_nao_previsto,
    }


def classify_status(value: float) -> str:
    if pd.isna(value):
        return "Sem dado"
    if value < -0.005:
        return "Estourado"
    if abs(value) <= 0.005:
        return "Zerado"
    return "Disponivel"


def summarize_realizado_nao_previsto_row(row: pd.Series) -> str:
    has_budget_cc = bool(row.get("orcado_no_cc_previsto", False))
    has_budget_line = bool(row.get("orcado_na_linha", False))

    if not has_budget_cc:
        return "Centro de custo nao previsto"
    if not has_budget_line:
        return "Conta nao prevista no centro de custo"
    return "Previsto"


def require_columns(df: pd.DataFrame, columns: list[str], source_name: str) -> None:
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise KeyError(f"{source_name} sem colunas obrigatorias: {', '.join(missing)}")


def parse_budget_year(value: str) -> int | None:
    match = re.search(r"-(\d{2,4})$", str(value))
    if not match:
        return None
    year_token = match.group(1)
    if len(year_token) == 2:
        return 2000 + int(year_token)
    return int(year_token)


@st.cache_data(show_spinner="Carregando orcado...")
def load_budget_data(_signature: str) -> pd.DataFrame:
    budget = pd.read_excel(PATH_ORCADO, engine="openpyxl")
    require_columns(budget, ["CentroCusto", "ClasseCusto"], "orcado.xlsx")

    month_cols = [column for column in budget.columns if re.match(r"^[a-z]{3}-\d{2,4}$", str(column).lower())]
    if not month_cols:
        raise ValueError("orcado.xlsx nao possui colunas mensais no formato jan-26, fev-26, etc.")

    id_vars = [column for column in budget.columns if column not in month_cols]
    budget_long = budget.melt(
        id_vars=id_vars,
        value_vars=month_cols,
        var_name="mes_ref",
        value_name="orcado_original",
    )

    budget_long["mes_prefix"] = budget_long["mes_ref"].astype(str).str.split("-").str[0].str.lower()
    budget_long["mes"] = budget_long["mes_prefix"].map(MESES_MAP)
    budget_long["ano"] = budget_long["mes_ref"].map(parse_budget_year)
    budget_long["centro_custo"] = budget_long["CentroCusto"].astype("Int64").astype(str).replace("<NA>", "SEM_CC")
    budget_long["conta"] = budget_long["ClasseCusto"].astype("Int64").astype(str).replace("<NA>", "SEM_CONTA")
    if "Tipo Despesa" in budget.columns:
        budget_long["tipo_despesa"] = budget_long["Tipo Despesa"].fillna("Nao informado").astype(str).str.strip()
    else:
        budget_long["tipo_despesa"] = "Nao informado"
    budget_long["orcado_original"] = pd.to_numeric(
        budget_long["orcado_original"], errors="coerce"
    ).fillna(0.0)

    budget_long = budget_long.dropna(subset=["mes", "ano"])

    return (
        budget_long[["ano", "mes", "centro_custo", "conta", "tipo_despesa", "orcado_original"]]
        .groupby(["ano", "mes", "centro_custo", "conta", "tipo_despesa"], as_index=False)
        .agg(orcado_original=("orcado_original", "sum"))
    )


@st.cache_data(show_spinner="Carregando realizado SAP...")
def load_actual_data(_signature: str) -> pd.DataFrame:
    files = sorted(BASE_DIR.glob("FAGLL03H_*.xlsx"))
    if not files:
        raise FileNotFoundError("Nenhum arquivo FAGLL03H_*.xlsx encontrado na pasta do projeto.")

    frames = [pd.read_excel(file, engine="openpyxl") for file in files]
    actual = pd.concat(frames, ignore_index=True)

    # Limpar espaços em branco dos nomes das colunas (comum no SAP)
    actual.columns = [str(c).strip() for c in actual.columns]

    require_columns(
        actual,
        ["Conta do Razão", "Período contábil", "Valor em moeda da empresa", "Exercício"],
        "FAGLL03H_*.xlsx",
    )

    actual["ano"] = pd.to_numeric(actual["Exercício"], errors="coerce").astype("Int64")
    actual["mes"] = pd.to_numeric(actual["Período contábil"], errors="coerce").astype("Int64")
    actual["conta"] = actual["Conta do Razão"].astype("Int64").astype(str).replace("<NA>", "SEM_CONTA")
    centro_custo_col = actual["Centro custo"] if "Centro custo" in actual.columns else pd.Series(pd.NA, index=actual.index)
    actual["centro_custo"] = centro_custo_col.astype("Int64").astype(str).replace("<NA>", "SEM_CC")
    actual["realizado"] = pd.to_numeric(
        actual["Valor em moeda da empresa"], errors="coerce"
    ).fillna(0.0)

    despesas = actual["conta"].str.startswith(("5", "6"), na=False)
    actual = actual[despesas].copy()
    actual = actual.dropna(subset=["ano", "mes"])

    # Busca flexível para Coluna de Texto
    texto_col = next((c for c in actual.columns if c.lower() == "texto"), None)
    actual["Texto Lançamento (SAP)"] = actual[texto_col] if texto_col else ""

    # Busca flexível e prioritária para Fornecedor (Nome1)
    # Procuramos exatamente pela string informada ou variações comuns
    fornecedor_col = None
    targets = ["Conta do Fornecedor: Nome1", "Nome 1", "Nome do fornecedor", "Fornecedor"]
    
    # Tenta encontrar por match exato (limpo) ou parcial
    for t in targets:
        found = next((c for c in actual.columns if t.lower() in c.lower()), None)
        if found:
            fornecedor_col = found
            break

    actual["Fornecedor (SAP)"] = actual[fornecedor_col] if fornecedor_col else "N/D"

    return actual

@st.cache_data(show_spinner="Carregando dimensoes...")
def load_dimensions(_dim_cc_signature: str, _dim_contas_signature: str, _dim_contas_dre_signature: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    dim_cc = normalize_columns(pd.read_excel(PATH_DIM_CC, engine="openpyxl"))
    dim_contas = normalize_columns(pd.read_excel(PATH_DIM_CONTAS, engine="openpyxl"))
    dim_contas_dre = normalize_columns(pd.read_excel(PATH_DIM_CONTAS_DRE, engine="openpyxl"))

    require_columns(dim_cc, ["centrocusto", "area", "linha_do_dre", "gestor"], "dim_centro_custo.xlsx")
    require_columns(dim_contas, ["conta", "descricao"], "dim_plano_contas.xlsx")

    dim_cc = dim_cc.rename(
        columns={
            "centrocusto": "centro_custo",
            "area": "area_setor",
            "linha_do_dre": "classificacao_dre_cc",
        }
    )
    dim_cc["centro_custo"] = dim_cc["centro_custo"].astype("Int64").astype(str)
    dim_cc = dim_cc.drop_duplicates(subset=["centro_custo"])

    dim_contas = dim_contas.rename(
        columns={
            "classificacao": "categoria_despesas",
            "tipo_despesa": "tipo_despesa_dim",
        }
    )
    dim_contas["conta"] = dim_contas["conta"].astype("Int64").astype(str)
    if "tipo_despesa_dim" not in dim_contas.columns:
        dim_contas["tipo_despesa_dim"] = pd.NA
    dim_contas["categoria_despesas"] = dim_contas["categoria_despesas"].apply(clean_text_value)
    dim_contas["tipo_despesa_dim"] = dim_contas["tipo_despesa_dim"].apply(clean_text_value)
    dim_contas["descricao"] = dim_contas["descricao"].apply(clean_text_value)
    dim_contas["score_tipo"] = dim_contas["tipo_despesa_dim"].notna().astype(int)
    dim_contas["score_categoria"] = dim_contas["categoria_despesas"].notna().astype(int)
    dim_contas["score_descricao"] = dim_contas["descricao"].notna().astype(int)
    dim_contas = (
        dim_contas.sort_values(
            ["conta", "score_tipo", "score_categoria", "score_descricao"],
            ascending=[True, False, False, False],
        )
        .drop_duplicates(subset=["conta"], keep="first")
        .drop(columns=["score_tipo", "score_categoria", "score_descricao"])
    )
    dim_contas = dim_contas[["conta", "descricao", "categoria_despesas", "tipo_despesa_dim"]]

    if "classe_de_custo" in dim_contas_dre.columns:
        dim_contas_dre = dim_contas_dre.rename(
            columns={
                "classe_de_custo": "conta",
                "linha_do_dre": "classificacao_dre_conta",
            }
        )
        dim_contas_dre["conta"] = dim_contas_dre["conta"].astype("Int64").astype(str)
        dim_contas_dre = dim_contas_dre[["conta", "classificacao_dre_conta"]].drop_duplicates(subset=["conta"])
    else:
        dim_contas_dre = pd.DataFrame(columns=["conta", "classificacao_dre_conta"])

    dim_contas = dim_contas.merge(dim_contas_dre, on="conta", how="left")
    dim_contas["classificacao_dre"] = dim_contas["classificacao_dre_conta"]
    dim_contas = dim_contas.drop(columns=["classificacao_dre_conta"])

    return dim_cc, dim_contas


def add_carry_over(group: pd.DataFrame) -> pd.DataFrame:
    group = group.sort_values("mes").copy()
    group["saldo_mes_anterior"] = (group["orcado_original"] - group["realizado"]).cumsum().shift(fill_value=0.0)
    group["orcamento_disponivel"] = group["orcado_original"] + group["saldo_mes_anterior"]
    group["saldo_final"] = group["orcamento_disponivel"] - group["realizado"]
    group["desvio_vs_orcado"] = group["realizado"] - group["orcado_original"]
    group["desvio_vs_disponivel"] = group["realizado"] - group["orcamento_disponivel"]
    group["status"] = group["saldo_final"].apply(classify_status)
    return group


@st.cache_data(show_spinner="Calculando controle orcamentario...")
def build_budget_control(
    budget_signature: str,
    actual_signature: str,
    dim_cc_signature: str,
    dim_contas_signature: str,
    dim_contas_dre_signature: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    budget = load_budget_data(budget_signature)
    actual_raw = load_actual_data(actual_signature)
    dim_cc, dim_contas = load_dimensions(dim_cc_signature, dim_contas_signature, dim_contas_dre_signature)

    # Agrupar realizado para o merge com orçamento (evita duplicação de linhas de budget)
    actual_grouped = (
        actual_raw[["ano", "mes", "centro_custo", "conta", "realizado"]]
        .groupby(["ano", "mes", "centro_custo", "conta"], as_index=False)
        .sum()
    )

    merge_keys = ["ano", "mes", "centro_custo", "conta"]
    monthly = budget.merge(actual_grouped, on=merge_keys, how="outer")
    monthly["orcado_original"] = monthly["orcado_original"].fillna(0.0)
    monthly["realizado"] = monthly["realizado"].fillna(0.0)
    monthly["tipo_despesa"] = monthly["tipo_despesa"].fillna("Nao informado")

    all_keys = monthly[["ano", "centro_custo", "conta", "tipo_despesa"]].drop_duplicates()
    years = sorted(all_keys["ano"].dropna().astype(int).unique().tolist())

    calendar_parts = []
    for year in years:
        year_keys = all_keys[all_keys["ano"] == year].copy()
        year_calendar = pd.DataFrame({"mes": list(range(1, 13))})
        year_keys["key"] = 1
        year_calendar["key"] = 1
        calendar_parts.append(year_keys.merge(year_calendar, on="key").drop(columns="key"))

    calendar = pd.concat(calendar_parts, ignore_index=True) if calendar_parts else monthly[["ano", "mes", "centro_custo", "conta", "tipo_despesa"]].copy()
    monthly = calendar.merge(monthly, on=["ano", "mes", "centro_custo", "conta", "tipo_despesa"], how="left")
    monthly["orcado_original"] = monthly["orcado_original"].fillna(0.0)
    monthly["realizado"] = monthly["realizado"].fillna(0.0)
    monthly["tipo_despesa"] = monthly["tipo_despesa"].fillna("Nao informado")

    monthly_parts = []
    for _, group in monthly.groupby(["ano", "centro_custo", "conta", "tipo_despesa"], sort=False):
        monthly_parts.append(add_carry_over(group))
    monthly = pd.concat(monthly_parts, ignore_index=True)

    monthly = monthly.merge(dim_cc, on="centro_custo", how="left")
    monthly = monthly.merge(dim_contas, on="conta", how="left")
    monthly["classificacao_dre"] = monthly["classificacao_dre"].fillna(monthly["classificacao_dre_cc"])
    monthly["tipo_despesa_orcamento"] = monthly["tipo_despesa"].apply(clean_text_value)
    monthly["categoria_despesas"] = monthly["categoria_despesas"].apply(clean_text_value)
    monthly["tipo_despesa_dim"] = monthly["tipo_despesa_dim"].apply(clean_text_value)
    monthly["tipo_despesa"] = monthly["tipo_despesa_dim"].fillna(monthly["tipo_despesa_orcamento"])
    monthly["tipo_despesa"] = monthly["tipo_despesa"].fillna("Nao informado")
    monthly["tipo_despesa_dim"] = monthly["tipo_despesa_dim"].fillna(monthly["tipo_despesa"])
    monthly["categoria_despesas"] = monthly["categoria_despesas"].fillna("Nao classificado")
    monthly["descricao_conta"] = monthly["descricao"].fillna(monthly["conta"])
    monthly = monthly.drop(columns=["descricao", "classificacao_dre_cc"])

    # Enriquecer a base analítica com dimensões para que os filtros funcionem nela também
    actual_enriched = actual_raw.merge(dim_cc, on="centro_custo", how="left")
    actual_enriched = actual_enriched.merge(dim_contas, on="conta", how="left")
    actual_enriched["classificacao_dre"] = actual_enriched["classificacao_dre"].fillna(actual_enriched["classificacao_dre_cc"])
    actual_enriched["descricao_conta"] = actual_enriched["descricao"].fillna(actual_enriched["conta"])
    
    if "tipo_despesa_dim" in actual_enriched.columns:
        actual_enriched["tipo_despesa"] = actual_enriched["tipo_despesa_dim"].fillna("Realizado SAP")

    monthly["ano"] = monthly["ano"].astype(int)
    monthly["mes"] = monthly["mes"].astype(int)
    for column in [
        "orcado_original",
        "saldo_mes_anterior",
        "orcamento_disponivel",
        "realizado",
        "saldo_final",
        "desvio_vs_orcado",
        "desvio_vs_disponivel",
    ]:
        monthly[column] = monthly[column].round(2)

    return monthly, actual_enriched


@st.cache_data(show_spinner="Calculando realizado nao previsto...")
def build_unplanned_report(control: pd.DataFrame) -> pd.DataFrame:
    working = control.copy()

    budget_cc = (
        working.groupby(["ano", "centro_custo"], as_index=False)["orcado_original"]
        .sum()
        .rename(columns={"orcado_original": "orcado_total_cc"})
    )
    budget_cc["orcado_no_cc_previsto"] = budget_cc["orcado_total_cc"] > 0

    budget_line = working[["ano", "centro_custo", "conta", "tipo_despesa", "orcado_original"]].copy()
    budget_line["orcado_na_linha"] = budget_line["orcado_original"] > 0
    budget_line = (
        budget_line.groupby(["ano", "centro_custo", "conta", "tipo_despesa"], as_index=False)["orcado_na_linha"]
        .max()
    )

    actuals = working[working["realizado"] > 0].copy()
    actuals = actuals.merge(
        budget_cc[["ano", "centro_custo", "orcado_no_cc_previsto"]],
        on=["ano", "centro_custo"],
        how="left",
    )
    actuals = actuals.merge(
        budget_line,
        on=["ano", "centro_custo", "conta", "tipo_despesa"],
        how="left",
    )
    actuals["orcado_no_cc_previsto"] = actuals["orcado_no_cc_previsto"].fillna(False)
    actuals["orcado_na_linha"] = actuals["orcado_na_linha"].fillna(False)
    actuals["motivo_nao_previsto"] = actuals.apply(summarize_realizado_nao_previsto_row, axis=1)

    report = actuals[actuals["motivo_nao_previsto"] != "Previsto"].copy()
    report["impacto_no_mes"] = report["realizado"]

    return report[
        [
            "ano",
            "mes",
            "centro_custo",
            "gestor",
            "area_setor",
            "conta",
            "descricao_conta",
            "tipo_despesa",
            "categoria_despesas",
            "classificacao_dre",
            "tipo_despesa_dim",
            "realizado",
            "impacto_no_mes",
            "motivo_nao_previsto",
        ]
    ].sort_values(["mes", "centro_custo", "conta"])


def apply_filters(df: pd.DataFrame, unplanned: pd.DataFrame, actual_raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, int, int, str]:
    filtered = df.copy()
    filtered_unplanned = unplanned.copy()
    filtered_actual = actual_raw.copy()

    with st.sidebar:
        st.header("Filtros")
        if st.button("Refresh", use_container_width=True, key="refresh_app_button"):
            st.session_state["_refresh_nonce"] = get_file_signature(Path(__file__))
            st.cache_data.clear()
            st.rerun()

        anos = sorted(filtered["ano"].dropna().astype(int).unique().tolist())
        ano_escolhido = st.selectbox(
            "Ano",
            anos,
            index=len(anos) - 1 if anos else 0,
            key="filtro_ano_estavel",
        )
        filtered = filtered[filtered["ano"] == ano_escolhido]
        filtered_unplanned = filtered_unplanned[filtered_unplanned["ano"] == ano_escolhido]
        filtered_actual = filtered_actual[filtered_actual["ano"] == ano_escolhido]

        visao = st.radio(
            "Visao",
            ["Mensal", "Acumulado"],
            horizontal=True,
            key="filtro_visao_estavel",
        )
        mes_escolhido = st.selectbox(
            "Mes de referencia",
            [0] + list(range(1, 13)),
            index=0,
            format_func=get_month_filter_label,
            key="filtro_mes_estavel",
        )

        areas = sorted(filtered["area_setor"].dropna().astype(str).unique().tolist())
        areas_sel = st.multiselect("Area / Setor", areas)
        if areas_sel:
            filtered = filtered[filtered["area_setor"].isin(areas_sel)]
            filtered_unplanned = filtered_unplanned[filtered_unplanned["area_setor"].isin(areas_sel)]
            filtered_actual = filtered_actual[filtered_actual["area_setor"].isin(areas_sel)]

        gestores = sorted(filtered["gestor"].dropna().astype(str).unique().tolist())
        gestores_sel = st.multiselect("Gestor", gestores)
        if gestores_sel:
            filtered = filtered[filtered["gestor"].isin(gestores_sel)]
            filtered_unplanned = filtered_unplanned[filtered_unplanned["gestor"].isin(gestores_sel)]
            filtered_actual = filtered_actual[filtered_actual["gestor"].isin(gestores_sel)]

        ccs = sorted(filtered["centro_custo"].dropna().astype(str).unique().tolist())
        ccs_sel = st.multiselect("Centro de Custo", ccs)
        if ccs_sel:
            filtered = filtered[filtered["centro_custo"].isin(ccs_sel)]
            filtered_unplanned = filtered_unplanned[filtered_unplanned["centro_custo"].isin(ccs_sel)]
            filtered_actual = filtered_actual[filtered_actual["centro_custo"].isin(ccs_sel)]

        contas = sorted(filtered["conta"].dropna().astype(str).unique().tolist())
        contas_sel = st.multiselect("Conta", contas)
        if contas_sel:
            filtered = filtered[filtered["conta"].isin(contas_sel)]
            filtered_unplanned = filtered_unplanned[filtered_unplanned["conta"].isin(contas_sel)]
            filtered_actual = filtered_actual[filtered_actual["conta"].isin(contas_sel)]

        tipos_despesa = sorted(filtered["tipo_despesa"].dropna().astype(str).unique().tolist())
        tipos_despesa_sel = st.multiselect("Tipo Despesa", tipos_despesa)
        if tipos_despesa_sel:
            filtered = filtered[filtered["tipo_despesa"].isin(tipos_despesa_sel)]
            filtered_unplanned = filtered_unplanned[filtered_unplanned["tipo_despesa"].isin(tipos_despesa_sel)]
            filtered_actual = filtered_actual[filtered_actual["tipo_despesa"].isin(tipos_despesa_sel)]

        categorias = sorted(filtered["categoria_despesas"].dropna().astype(str).unique().tolist())
        categorias_sel = st.multiselect("Categoria", categorias)
        if categorias_sel:
            filtered = filtered[filtered["categoria_despesas"].isin(categorias_sel)]
            filtered_unplanned = filtered_unplanned[filtered_unplanned["categoria_despesas"].isin(categorias_sel)]
            filtered_actual = filtered_actual[filtered_actual["categoria_despesas"].isin(categorias_sel)]

        dres = sorted(filtered["classificacao_dre"].dropna().astype(str).unique().tolist())
        dre_sel = st.multiselect("Linha DRE", dres)
        if dre_sel:
            filtered = filtered[filtered["classificacao_dre"].isin(dre_sel)]
            filtered_unplanned = filtered_unplanned[filtered_unplanned["classificacao_dre"].isin(dre_sel)]
            filtered_actual = filtered_actual[filtered_actual["classificacao_dre"].isin(dre_sel)]

    return filtered, filtered_unplanned, filtered_actual, int(ano_escolhido), int(mes_escolhido), str(visao)


def apply_period_filter(df: pd.DataFrame, mes_escolhido: int, visao: str) -> pd.DataFrame:
    if mes_escolhido == 0:
        return df.copy()
    if visao == "Mensal":
        return df[df["mes"] == mes_escolhido].copy()
    return df[df["mes"] <= mes_escolhido].copy()


def build_snapshot(df: pd.DataFrame, mes_escolhido: int, visao: str) -> pd.DataFrame:
    group_cols = [
        "ano",
        "centro_custo",
        "gestor",
        "area_setor",
        "conta",
        "descricao_conta",
        "tipo_despesa",
        "categoria_despesas",
        "classificacao_dre",
        "tipo_despesa_dim",
    ]

    period_df = apply_period_filter(df, mes_escolhido, visao)

    if visao == "Mensal":
        return period_df[DETAIL_COLUMNS].sort_values(["centro_custo", "conta"])

    upto = period_df.sort_values(["ano", "centro_custo", "conta", "mes"]).copy()
    aggregated = (
        upto.groupby(group_cols, dropna=False)
        .agg(
            orcado_original=("orcado_original", "sum"),
            saldo_mes_anterior=("saldo_mes_anterior", "last"),
            orcamento_disponivel=("orcamento_disponivel", "last"),
            realizado=("realizado", "sum"),
            saldo_final=("saldo_final", "last"),
        )
        .reset_index()
    )
    aggregated["mes"] = mes_escolhido if mes_escolhido != 0 else 0
    aggregated["desvio_vs_orcado"] = aggregated["realizado"] - aggregated["orcado_original"]
    aggregated["desvio_vs_disponivel"] = aggregated["realizado"] - aggregated["orcamento_disponivel"]
    aggregated["status"] = aggregated["saldo_final"].apply(classify_status)
    return aggregated[DETAIL_COLUMNS].sort_values(["centro_custo", "conta"])


def render_summary_card(title: str, value: str) -> None:
    st.markdown(
        f"""
        <div style="
            background:#f7f8fa;
            border:1px solid #d9dde3;
            border-radius:14px;
            padding:16px 18px;
            min-height:110px;
            display:flex;
            flex-direction:column;
            justify-content:space-between;
        ">
            <div style="font-size:0.92rem;color:#516071;font-weight:600;">{title}</div>
            <div style="
                font-size:1.55rem;
                line-height:1.2;
                color:#16202a;
                font-weight:700;
                word-break:break-word;
                overflow-wrap:anywhere;
            ">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_summary_card_with_tone(title: str, value: str, tone: str = "neutral") -> None:
    palette = {
        "neutral": {"bg": "#f7f8fa", "border": "#d9dde3", "title": "#516071", "value": "#16202a"},
        "good": {"bg": "#eef8f1", "border": "#b7ddc2", "title": "#2f6b3d", "value": "#184d28"},
        "bad": {"bg": "#fff1f0", "border": "#efc2be", "title": "#9a3b32", "value": "#7f231a"},
        "warn": {"bg": "#fff7e8", "border": "#f0d49a", "title": "#916522", "value": "#6b4c16"},
    }
    colors = palette.get(tone, palette["neutral"])
    st.markdown(
        f"""
        <div style="
            background:{colors['bg']};
            border:1px solid {colors['border']};
            border-radius:14px;
            padding:16px 18px;
            min-height:110px;
            display:flex;
            flex-direction:column;
            justify-content:space-between;
        ">
            <div style="font-size:0.92rem;color:{colors['title']};font-weight:600;">{title}</div>
            <div style="
                font-size:1.55rem;
                line-height:1.2;
                color:{colors['value']};
                font-weight:700;
                word-break:break-word;
                overflow-wrap:anywhere;
            ">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def compute_summary_totals(snapshot: pd.DataFrame, visao: str, mes_escolhido: int) -> tuple[float, float, float, float, float, int]:
    if visao == "Mensal" and mes_escolhido == 0:
        latest_snapshot = (
            snapshot.sort_values(["ano", "centro_custo", "conta", "tipo_despesa", "mes"])
            .groupby(["ano", "centro_custo", "conta", "tipo_despesa"], as_index=False)
            .tail(1)
        )
        total_orcado = snapshot["orcado_original"].sum()
        total_realizado = snapshot["realizado"].sum()
        total_saldo_anterior = latest_snapshot["saldo_mes_anterior"].sum()
        total_disponivel = latest_snapshot["orcamento_disponivel"].sum()
        total_saldo = latest_snapshot["saldo_final"].sum()
        total_estourados = int((latest_snapshot["saldo_final"] < 0).sum())
        return (
            total_orcado,
            total_saldo_anterior,
            total_disponivel,
            total_realizado,
            total_saldo,
            total_estourados,
        )

    total_orcado = snapshot["orcado_original"].sum()
    total_saldo_anterior = snapshot["saldo_mes_anterior"].sum()
    total_disponivel = snapshot["orcamento_disponivel"].sum()
    total_realizado = snapshot["realizado"].sum()
    total_saldo = snapshot["saldo_final"].sum()
    total_estourados = int((snapshot["saldo_final"] < 0).sum())
    return (
        total_orcado,
        total_saldo_anterior,
        total_disponivel,
        total_realizado,
        total_saldo,
        total_estourados,
    )


def get_effective_snapshot(snapshot: pd.DataFrame, visao: str, mes_escolhido: int) -> pd.DataFrame:
    if snapshot.empty:
        return snapshot.copy()
    if visao == "Mensal" and mes_escolhido == 0:
        return (
            snapshot.sort_values(["ano", "centro_custo", "conta", "tipo_despesa", "mes"])
            .groupby(["ano", "centro_custo", "conta", "tipo_despesa"], as_index=False)
            .tail(1)
            .copy()
        )
    return snapshot.copy()


def get_reference_month(period_df: pd.DataFrame, mes_escolhido: int) -> int | None:
    if mes_escolhido != 0:
        return int(mes_escolhido)
    if period_df.empty:
        return None
    months_with_actuals = period_df.loc[period_df["realizado"].abs() > 0.005, "mes"]
    if not months_with_actuals.empty:
        return int(months_with_actuals.max())
    return int(period_df["mes"].max())


def build_management_indicators(
    snapshot: pd.DataFrame,
    filtered: pd.DataFrame,
    filtered_unplanned: pd.DataFrame,
    mes_escolhido: int,
    visao: str,
) -> dict[str, float | int | None]:
    period_df = apply_period_filter(filtered, mes_escolhido, visao)
    unplanned_period = apply_period_filter(filtered_unplanned, mes_escolhido, visao)
    reference_month = get_reference_month(period_df, mes_escolhido)

    total_orcado = snapshot["orcado_original"].sum()
    total_realizado = snapshot["realizado"].sum()
    total_saldo = snapshot["saldo_final"].sum()
    total_capacidade = total_realizado + total_saldo
    total_unplanned = unplanned_period["realizado"].sum()
    desvio_total = snapshot["desvio_vs_orcado"].sum()
    tipo_mix = snapshot.copy()
    tipo_mix["tipo_bucket"] = tipo_mix["tipo_despesa"].apply(normalize_expense_type_bucket)
    tipo_mix["realizado_mix"] = tipo_mix["realizado"].clip(lower=0.0)
    total_realizado_mix = float(tipo_mix["realizado_mix"].sum())
    realizado_por_tipo = tipo_mix.groupby("tipo_bucket", dropna=False)["realizado_mix"].sum()
    mix_fixa = safe_divide(float(realizado_por_tipo.get("Fixa", 0.0)), total_realizado_mix)
    mix_variavel = safe_divide(float(realizado_por_tipo.get("Variavel", 0.0)), total_realizado_mix)
    mix_outros = safe_divide(float(realizado_por_tipo.get("Outros", 0.0)), total_realizado_mix)

    execucao_orcado = safe_divide(total_realizado, total_orcado)
    consumo_disponivel = safe_divide(total_realizado, total_capacidade)
    eficiencia_orcamentaria = invert_ratio(consumo_disponivel)
    indice_nao_previsto = safe_divide(total_unplanned, total_realizado)

    variacao_mensal = None
    mes_referencia_nome = "n/d"
    mes_anterior_nome = "n/d"
    projected_total = None
    projected_gap = None
    forecast_criterio = "Media acumulada do periodo"
    gasto_medio_mensal = None

    if reference_month is not None:
        monthly_realized = (
            filtered.groupby("mes", as_index=False)["realizado"]
            .sum()
            .sort_values("mes")
        )
        monthly_realized = monthly_realized[monthly_realized["mes"] <= reference_month]
        current_row = monthly_realized[monthly_realized["mes"] == reference_month]
        previous_row = monthly_realized[monthly_realized["mes"] == (reference_month - 1)]

        mes_referencia_nome = get_month_name(reference_month)
        if not previous_row.empty:
            mes_anterior_nome = get_month_name(reference_month - 1)
            valor_atual = float(current_row["realizado"].iloc[0]) if not current_row.empty else 0.0
            valor_anterior = float(previous_row["realizado"].iloc[0])
            variacao_mensal = safe_divide(valor_atual - valor_anterior, valor_anterior)

        if visao == "Acumulado" and len(monthly_realized) >= 3:
            media_referencia = float(monthly_realized.tail(3)["realizado"].mean())
            projected_total = media_referencia * 12
            forecast_criterio = "Media movel dos ultimos 3 meses fechados"
            gasto_medio_mensal = media_referencia
        elif visao == "Acumulado":
            meses_base = max(reference_month, 1)
            realizado_acumulado = period_df[period_df["mes"] <= reference_month]["realizado"].sum()
            projected_total = (realizado_acumulado / meses_base) * 12
            gasto_medio_mensal = realizado_acumulado / meses_base if meses_base else None
        else:
            valor_mes = float(current_row["realizado"].iloc[0]) if not current_row.empty else 0.0
            projected_total = valor_mes * 12
            forecast_criterio = f"Annualizacao do mes de {mes_referencia_nome}"
            gasto_medio_mensal = valor_mes

        orcado_anual = (
            filtered.groupby(["ano", "centro_custo", "conta", "tipo_despesa"], dropna=False)["orcado_original"]
            .sum()
            .sum()
        )
        projected_gap = projected_total - float(orcado_anual)

    return {
        "execucao_orcado": execucao_orcado,
        "consumo_disponivel": consumo_disponivel,
        "eficiencia_orcamentaria": eficiencia_orcamentaria,
        "indice_nao_previsto": indice_nao_previsto,
        "desvio_total": desvio_total,
        "gasto_medio_mensal": gasto_medio_mensal,
        "mix_fixa": mix_fixa,
        "mix_variavel": mix_variavel,
        "mix_outros": mix_outros,
        "variacao_mensal": variacao_mensal,
        "forecast_total": projected_total,
        "forecast_gap": projected_gap,
        "forecast_criterio": forecast_criterio,
        "mes_referencia": reference_month,
        "mes_referencia_nome": mes_referencia_nome,
        "mes_anterior_nome": mes_anterior_nome,
    }


def render_summary(snapshot: pd.DataFrame, period_context: dict[str, str | int]) -> None:
    visao = str(period_context["visao"])
    mes_escolhido = int(period_context["mes_escolhido"])
    st.caption(str(period_context["periodo_ativo"]))
    st.markdown(f"## {period_context['titulo_resumo']}")

    (
        total_orcado,
        total_saldo_anterior,
        total_disponivel,
        total_realizado,
        total_saldo,
        total_estourados,
    ) = compute_summary_totals(snapshot, visao, mes_escolhido)

    row1 = st.columns(3)
    row2 = st.columns(3)

    with row1[0]:
        render_summary_card_with_tone("Orcado", format_currency(total_orcado))
    with row1[1]:
        tone = "good" if total_saldo_anterior >= 0 else "bad"
        render_summary_card_with_tone("Saldo Anterior", format_currency(total_saldo_anterior), tone=tone)
    with row1[2]:
        tone = "good" if total_disponivel >= 0 else "bad"
        render_summary_card_with_tone("Disponivel", format_currency(total_disponivel), tone=tone)
    with row2[0]:
        render_summary_card_with_tone("Realizado", format_currency(total_realizado))
    with row2[1]:
        tone = "good" if total_saldo >= 0 else "bad"
        render_summary_card_with_tone("Saldo Final", format_currency(total_saldo), tone=tone)
    with row2[2]:
        tone = "warn" if total_estourados == 0 else "bad"
        render_summary_card_with_tone("Itens Estourados", f"{total_estourados}", tone=tone)


def render_management_summary(
    snapshot: pd.DataFrame,
    filtered: pd.DataFrame,
    filtered_unplanned: pd.DataFrame,
    period_context: dict[str, str | int],
) -> None:
    visao = str(period_context["visao"])
    mes_escolhido = int(period_context["mes_escolhido"])
    indicadores = build_management_indicators(snapshot, filtered, filtered_unplanned, mes_escolhido, visao)

    st.markdown("### Indicadores Gerenciais")
    cols = st.columns(4)

    with cols[0]:
        eficiencia = indicadores["eficiencia_orcamentaria"]
        tone = "good" if (eficiencia or 0) > 0 else "bad"
        render_summary_card_with_tone(
            "% Eficiencia Orcamentaria",
            format_percent(eficiencia),
            tone=tone,
        )
    with cols[1]:
        desvio_total = float(indicadores["desvio_total"] or 0.0)
        tone = "good" if desvio_total <= 0 else "bad"
        render_summary_card_with_tone("Desvio vs Orcado", format_currency(desvio_total), tone=tone)
    with cols[2]:
        tone = "warn" if (indicadores["indice_nao_previsto"] or 0) <= 0.05 else "bad"
        render_summary_card_with_tone("Gastos Nao Previstos", format_percent(indicadores["indice_nao_previsto"]), tone=tone)
    with cols[3]:
        tone = "good" if (indicadores["variacao_mensal"] or 0) <= 0 else "warn"
        render_summary_card_with_tone(
            "Variacao Mensal",
            format_percent(indicadores["variacao_mensal"]),
            tone=tone,
        )

    cols2 = st.columns(4)
    with cols2[0]:
        gasto_medio = indicadores["gasto_medio_mensal"]
        render_summary_card_with_tone("Gasto Medio Mensal", format_currency(gasto_medio), tone="neutral")
    with cols2[1]:
        tone = "good" if (indicadores["mix_fixa"] or 0) >= 0.5 else "neutral"
        render_summary_card_with_tone("Mix Despesa Fixa", format_percent(indicadores["mix_fixa"]), tone=tone)
    with cols2[2]:
        tone = "warn" if (indicadores["mix_variavel"] or 0) <= 0.4 else "bad"
        render_summary_card_with_tone("Mix Despesa Variavel", format_percent(indicadores["mix_variavel"]), tone=tone)
    with cols2[3]:
        gap = indicadores["forecast_gap"]
        tone = "good" if (gap or 0) <= 0 else "bad"
        titulo_gap = "Folga Orcamentaria Projetada" if (gap or 0) <= 0 else "Risco de Estouro Anual"
        render_summary_card_with_tone(titulo_gap, format_currency(abs(gap) if gap is not None else None), tone=tone)

    cols3 = st.columns(1)
    with cols3[0]:
        tone = "good" if (indicadores["forecast_gap"] or 0) <= 0 else "bad"
        render_summary_card_with_tone("Forecast Fechamento", format_currency(indicadores["forecast_total"]), tone=tone)

    st.caption(
        "Eficiencia Orcamentaria representa a folga restante do orcamento disponivel "
        f"apos o realizado. Forecast anualizado por {indicadores['forecast_criterio']} ate "
        f"{indicadores['mes_referencia_nome']}. Variacao mensal compara "
        f"{indicadores['mes_referencia_nome']} vs {indicadores['mes_anterior_nome']}."
    )


def render_budget_discipline(snapshot: pd.DataFrame) -> None:
    if snapshot.empty:
        return

    working = snapshot.copy()
    working["desvio_percentual"] = working.apply(
        lambda row: safe_divide(row["desvio_vs_orcado"], row["orcado_original"]),
        axis=1,
    )

    aderentes = working["desvio_percentual"].apply(
        lambda value: value is not None and not pd.isna(value) and abs(float(value)) <= 0.05
    )
    cobertura = working["orcado_original"].abs() > 0.005
    base_aderencia = working[cobertura].copy()

    aderencia_pct = None
    if not base_aderencia.empty:
        aderencia_pct = aderentes.loc[base_aderencia.index].mean()

    total_aderentes = int(aderentes.loc[base_aderencia.index].sum()) if not base_aderencia.empty else 0
    total_linhas = int(len(base_aderencia))

    st.markdown("### Disciplina Orcamentaria")
    cols = st.columns(2)
    with cols[0]:
        tone = "good" if (aderencia_pct or 0) >= 0.7 else "warn" if (aderencia_pct or 0) >= 0.5 else "bad"
        render_summary_card_with_tone("% Aderencia ao Orcado", format_percent(aderencia_pct), tone=tone)
    with cols[1]:
        render_summary_card_with_tone("Linhas Dentro da Tolerancia", f"{total_aderentes}/{total_linhas}", tone="neutral")

    ofensores = (
        working[working["desvio_vs_orcado"] > 0]
        .sort_values(["desvio_vs_orcado", "realizado"], ascending=[False, False])
        .loc[
            :,
            [
                "centro_custo",
                "gestor",
                "area_setor",
                "conta",
                "descricao_conta",
                "tipo_despesa",
                "categoria_despesas",
                "orcado_original",
                "realizado",
                "desvio_vs_orcado",
                "saldo_final",
            ],
        ]
        .head(10)
    )

    if ofensores.empty:
        st.success("Nenhum ofensor com desvio positivo para os filtros selecionados.")
        return

    st.markdown("#### Top 10 Ofensores")
    ofensores_exibicao = format_dataframe_br(
        ofensores,
        ["orcado_original", "realizado", "desvio_vs_orcado", "saldo_final"],
    )
    st.dataframe(
        ofensores_exibicao,
        use_container_width=True,
        hide_index=True,
    )


def render_executive_alerts(
    snapshot: pd.DataFrame,
    filtered: pd.DataFrame,
    filtered_unplanned: pd.DataFrame,
    period_context: dict[str, str | int],
) -> None:
    if snapshot.empty:
        return

    visao = str(period_context["visao"])
    mes_escolhido = int(period_context["mes_escolhido"])
    effective_snapshot = get_effective_snapshot(snapshot, visao, mes_escolhido)
    report_unplanned = apply_period_filter(filtered_unplanned, mes_escolhido, visao)
    if visao == "Mensal" and mes_escolhido == 0 and not report_unplanned.empty:
        mes_referencia = int(effective_snapshot["mes"].max())
        report_unplanned = report_unplanned[report_unplanned["mes"] == mes_referencia].copy()

    total_realizado = float(effective_snapshot["realizado"].sum())
    total_unplanned = float(report_unplanned["realizado"].sum()) if not report_unplanned.empty else 0.0
    pct_unplanned = safe_divide(total_unplanned, total_realizado) or 0.0
    total_linhas = int(len(effective_snapshot))
    if visao == "Mensal":
        qtd_estourados = int((effective_snapshot["desvio_vs_orcado"] > 0).sum())
        texto_estouro = f"{qtd_estourados} linhas estouraram o orcado no mes ({format_percent(safe_divide(qtd_estourados, total_linhas))} do total)." if total_linhas else "Nenhuma linha elegivel no mes."
    else:
        qtd_estourados = int((effective_snapshot["saldo_final"] < 0).sum())
        texto_estouro = f"{qtd_estourados} linhas estao estouradas no fechamento do periodo ({format_percent(safe_divide(qtd_estourados, total_linhas))} do total)." if total_linhas else "Nenhuma linha elegivel no periodo."
    pct_estourados = safe_divide(qtd_estourados, total_linhas) or 0.0

    desvio_medio_ponderado = None
    if "desvio_vs_orcado" in effective_snapshot.columns and "orcado_original" in effective_snapshot.columns:
        base_desvio = effective_snapshot.copy()
        base_desvio["desvio_percentual"] = base_desvio.apply(
            lambda row: safe_divide(row["desvio_vs_orcado"], row["orcado_original"]),
            axis=1,
        )
        base_desvio = base_desvio.dropna(subset=["desvio_percentual"]).copy()
        if not base_desvio.empty:
            base_desvio["peso_realizado"] = base_desvio["realizado"].clip(lower=0.0)
            soma_pesos = float(base_desvio["peso_realizado"].sum())
            if soma_pesos > 0:
                desvio_medio_ponderado = float(
                    (base_desvio["desvio_percentual"].abs() * base_desvio["peso_realizado"]).sum() / soma_pesos
                )
            else:
                desvio_medio_ponderado = float(base_desvio["desvio_percentual"].abs().mean())

    alertas = []
    if pct_estourados >= 0.2:
        alertas.append(("bad", texto_estouro))
    elif qtd_estourados > 0:
        alertas.append(("warn", texto_estouro))
    else:
        alertas.append(("good", "Nenhuma linha estourada no contexto atual."))

    if pct_unplanned >= 0.1:
        alertas.append(("bad", f"Gastos nao previstos representam {format_percent(pct_unplanned)} do realizado."))
    elif pct_unplanned >= 0.05:
        alertas.append(("warn", f"Gastos nao previstos representam {format_percent(pct_unplanned)} do realizado."))
    else:
        alertas.append(("good", f"Gastos nao previstos em nivel controlado: {format_percent(pct_unplanned)} do realizado."))

    if desvio_medio_ponderado is not None:
        if desvio_medio_ponderado >= 0.3:
            alertas.append(("bad", f"Desvio medio absoluto ponderado vs orcado em {format_percent(desvio_medio_ponderado)}."))
        elif desvio_medio_ponderado >= 0.15:
            alertas.append(("warn", f"Desvio medio absoluto ponderado vs orcado em {format_percent(desvio_medio_ponderado)}."))
        else:
            alertas.append(("good", f"Desvio medio absoluto ponderado vs orcado em {format_percent(desvio_medio_ponderado)}."))

    st.markdown("### Alertas Executivos")
    for tone, texto in alertas:
        if tone == "bad":
            st.error(texto)
        elif tone == "warn":
            st.warning(texto)
        else:
            st.success(texto)


def render_risk_drivers(snapshot: pd.DataFrame, filtered_unplanned: pd.DataFrame, period_context: dict[str, str | int]) -> None:
    if snapshot.empty:
        return

    visao = str(period_context["visao"])
    mes_escolhido = int(period_context["mes_escolhido"])
    effective_snapshot = get_effective_snapshot(snapshot, visao, mes_escolhido)
    report_unplanned = apply_period_filter(filtered_unplanned, mes_escolhido, visao)
    if visao == "Mensal" and mes_escolhido == 0 and not report_unplanned.empty and not effective_snapshot.empty:
        mes_referencia = int(effective_snapshot["mes"].max())
        report_unplanned = report_unplanned[report_unplanned["mes"] == mes_referencia].copy()

    st.markdown("### Principais Vetores de Risco")

    causas = (
        report_unplanned.groupby("motivo_nao_previsto", as_index=False)["realizado"]
        .sum()
        .sort_values("realizado", ascending=False)
        .head(5)
    )

    risco_cc = (
        effective_snapshot.groupby(["centro_custo", "gestor", "area_setor"], dropna=False)[["saldo_final", "desvio_vs_orcado"]]
        .sum()
        .reset_index()
        .sort_values(["saldo_final", "desvio_vs_orcado"], ascending=[True, False])
        .head(5)
    )

    risco_conta = (
        effective_snapshot.groupby(["conta", "descricao_conta", "tipo_despesa", "categoria_despesas"], dropna=False)[
            ["saldo_final", "desvio_vs_orcado"]
        ]
        .sum()
        .reset_index()
        .sort_values(["saldo_final", "desvio_vs_orcado"], ascending=[True, False])
        .head(5)
    )

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### Top 5 Causas do Nao Previsto")
        if causas.empty:
            st.success("Sem causas de nao previsto para os filtros selecionados.")
        else:
            st.dataframe(
                format_dataframe_br(causas, ["realizado"]),
                use_container_width=True,
                hide_index=True,
            )

    with col2:
        st.markdown("#### Top 5 Centros de Custo em Risco")
        if risco_cc.empty:
            st.success("Sem centros de custo em risco para os filtros selecionados.")
        else:
            st.dataframe(
                format_dataframe_br(risco_cc, ["saldo_final", "desvio_vs_orcado"]),
                use_container_width=True,
                hide_index=True,
            )

    st.markdown("#### Top 5 Contas em Risco")
    if risco_conta.empty:
        st.success("Sem contas em risco para os filtros selecionados.")
    else:
        st.dataframe(
            format_dataframe_br(risco_conta, ["saldo_final", "desvio_vs_orcado"]),
            use_container_width=True,
            hide_index=True,
        )


def render_monthly_evolution(df: pd.DataFrame) -> None:
    evolution = (
        df.groupby("mes", as_index=False)[["orcado_original", "realizado", "saldo_final"]]
        .sum()
        .sort_values("mes")
    )
    if evolution.empty:
        st.info("Sem dados para evolucao mensal.")
        return

    evolution["mes_nome"] = evolution["mes"].map(MESES_NOMES)
    evolution["mes_nome"] = evolution["mes"].map(get_month_name)

    fig = go.Figure()
    fig.add_trace(go.Bar(name="Orcado", x=evolution["mes_nome"], y=evolution["orcado_original"], marker_color="lightgray"))
    fig.add_trace(go.Bar(name="Realizado", x=evolution["mes_nome"], y=evolution["realizado"], marker_color="steelblue"))
    fig.add_trace(
        go.Scatter(
            name="Saldo Final",
            x=evolution["mes_nome"],
            y=evolution["saldo_final"],
            mode="lines+markers",
            line=dict(color="darkgreen", width=3),
        )
    )
    fig.update_layout(
        title="Evolucao Mensal do Controle Orcamentario",
        barmode="group",
        template="simple_white",
        yaxis_title="Valor (R$)",
        legend_title="",
    )
    st.plotly_chart(fig, use_container_width=True)


def render_management_charts(
    filtered: pd.DataFrame,
    filtered_unplanned: pd.DataFrame,
    period_context: dict[str, str | int],
) -> None:
    visao = str(period_context["visao"])
    mes_escolhido = int(period_context["mes_escolhido"])
    base = apply_period_filter(filtered, mes_escolhido, visao)
    if base.empty:
        return
    reference_month = get_reference_month(base, mes_escolhido)
    if reference_month is not None:
        base = base[base["mes"] <= reference_month].copy()

    monthly = (
        base.groupby("mes", as_index=False)[["orcado_original", "orcamento_disponivel", "realizado"]]
        .sum()
        .sort_values("mes")
    )
    if monthly.empty:
        return

    monthly["execucao_pct"] = monthly.apply(
        lambda row: safe_divide(row["realizado"], row["orcado_original"]),
        axis=1,
    )
    monthly["consumo_pct"] = monthly.apply(
        lambda row: safe_divide(row["realizado"], row["orcamento_disponivel"]),
        axis=1,
    )
    monthly["eficiencia_pct"] = monthly["consumo_pct"].apply(invert_ratio)
    unplanned_monthly = apply_period_filter(filtered_unplanned, mes_escolhido, visao)
    if reference_month is not None:
        unplanned_monthly = unplanned_monthly[unplanned_monthly["mes"] <= reference_month].copy()
    unplanned_monthly = unplanned_monthly.groupby("mes", as_index=False)["realizado"].sum().rename(
        columns={"realizado": "nao_previsto"}
    )
    monthly = monthly.merge(unplanned_monthly, on="mes", how="left")
    monthly["nao_previsto"] = monthly["nao_previsto"].fillna(0.0)
    monthly["nao_previsto_pct"] = monthly.apply(
        lambda row: safe_divide(row["nao_previsto"], row["realizado"]),
        axis=1,
    )
    monthly["mes_nome"] = monthly["mes"].map(get_month_name)

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            name="% Eficiencia Orcamentaria",
            x=monthly["mes_nome"],
            y=monthly["eficiencia_pct"],
            mode="lines+markers",
            line=dict(color="#2f6b3d", width=3),
        )
    )
    fig.add_trace(
        go.Scatter(
            name="% Consumo do Orcado",
            x=monthly["mes_nome"],
            y=monthly["execucao_pct"],
            mode="lines+markers",
            line=dict(color="#916522", width=3),
        )
    )
    fig.add_trace(
        go.Bar(
            name="% Nao Previsto",
            x=monthly["mes_nome"],
            y=monthly["nao_previsto_pct"],
            marker_color="#c96d5d",
            opacity=0.55,
        )
    )
    fig.update_layout(
        title="Indicadores Mensais de Consumo e Eficiencia Orcamentaria",
        template="simple_white",
        yaxis_title="Percentual",
        legend_title="",
    )
    fig.update_yaxes(tickformat=".0%")
    st.plotly_chart(fig, use_container_width=True)

    mix_base = base.copy()
    mix_base["tipo_bucket"] = mix_base["tipo_despesa"].apply(normalize_expense_type_bucket)
    mix_base["realizado_mix"] = mix_base["realizado"].clip(lower=0.0)
    monthly_mix = (
        mix_base.groupby(["mes", "tipo_bucket"], as_index=False)["realizado_mix"]
        .sum()
        .pivot(index="mes", columns="tipo_bucket", values="realizado_mix")
        .fillna(0.0)
        .reset_index()
        .sort_values("mes")
    )
    if not monthly_mix.empty:
        monthly_mix["mes_nome"] = monthly_mix["mes"].map(get_month_name)
        fig_mix = go.Figure()
        for bucket, color in [("Fixa", "#2f6b3d"), ("Variavel", "#916522"), ("Outros", "#7b8794")]:
            if bucket in monthly_mix.columns:
                fig_mix.add_trace(
                    go.Bar(
                        name=f"Despesa {bucket}",
                        x=monthly_mix["mes_nome"],
                        y=monthly_mix[bucket],
                        marker_color=color,
                    )
                )
        fig_mix.update_layout(
            title="Mix Mensal por Tipo de Despesa",
            barmode="stack",
            template="simple_white",
            yaxis_title="Valor (R$)",
            legend_title="",
        )
        st.plotly_chart(fig_mix, use_container_width=True)


def format_dataframe_br(df: pd.DataFrame, numeric_columns: list[str]) -> pd.DataFrame:
    formatted = df.copy()
    for column in numeric_columns:
        if column in formatted.columns:
            formatted[column] = formatted[column].apply(format_number_br)
    return formatted


def dataframe_to_excel_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            safe_sheet_name = sheet_name[:31]
            df.to_excel(writer, index=False, sheet_name=safe_sheet_name)
    output.seek(0)
    return output.getvalue()


def render_tables(snapshot: pd.DataFrame, actual_raw: pd.DataFrame) -> None:
    resumo_cc = (
        snapshot.groupby(["centro_custo", "gestor", "area_setor", "tipo_despesa"], dropna=False)[
            ["orcado_original", "saldo_mes_anterior", "orcamento_disponivel", "realizado", "saldo_final"]
        ]
        .sum()
        .reset_index()
        .sort_values("saldo_final")
    )
    resumo_cc_exibicao = format_dataframe_br(
        resumo_cc,
        ["orcado_original", "saldo_mes_anterior", "orcamento_disponivel", "realizado", "saldo_final"],
    )
    detalhe_base = snapshot.sort_values(["saldo_final", "centro_custo", "conta"])

    st.markdown("### Resumo por Centro de Custo")
    export_cols = st.columns(3)
    with export_cols[0]:
        st.download_button(
            label="Download Resumo CC",
            data=dataframe_to_excel_bytes({"Resumo_CC": resumo_cc}),
            file_name="resumo_centro_custo.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_resumo_cc_xlsx",
            use_container_width=True,
        )
    with export_cols[1]:
        st.download_button(
            label="Download Detalhe Conta",
            data=dataframe_to_excel_bytes({"Detalhe_Conta": detalhe_base}),
            file_name="detalhe_conta.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_detalhe_conta_xlsx",
            use_container_width=True,
        )
    with export_cols[2]:
        st.download_button(
            label="Download Base Analítica SAP (Razão Contábil)",
            data=dataframe_to_excel_bytes({"Base_Analitica_Razao": actual_raw}),
            file_name="base_analitica_razao_contabil.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_base_analitica_xlsx",
            use_container_width=True,
        )
    st.dataframe(
        resumo_cc_exibicao,
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("### Detalhe por Conta")
    detalhe_exibicao = format_dataframe_br(
        detalhe_base,
        [
            "orcado_original",
            "saldo_mes_anterior",
            "orcamento_disponivel",
            "realizado",
            "saldo_final",
            "desvio_vs_orcado",
            "desvio_vs_disponivel",
        ],
    )
    st.dataframe(
        detalhe_exibicao,
        use_container_width=True,
        hide_index=True,
    )


def render_quality_alerts(df: pd.DataFrame) -> None:
    sem_gestor = int(df["gestor"].isna().sum())
    sem_dre = int(df["classificacao_dre"].isna().sum())
    sem_categoria = int(df["categoria_despesas"].isna().sum())
    sem_tipo_dim = int(df["tipo_despesa_dim"].isna().sum())

    with st.expander("Alertas de qualidade da base"):
        st.write(f"Linhas sem gestor mapeado: {sem_gestor}")
        st.write(f"Linhas sem classificacao DRE: {sem_dre}")
        st.write(f"Linhas sem categoria de despesa: {sem_categoria}")
        st.write(f"Linhas sem tipo de despesa da dimensao: {sem_tipo_dim}")
        st.write("O saldo transportado considera centro de custo + conta, mes a mes, dentro do mesmo ano.")


def render_unplanned_report(unplanned: pd.DataFrame, period_context: dict[str, str | int]) -> None:
    visao = str(period_context["visao"])
    mes_escolhido = int(period_context["mes_escolhido"])
    report = apply_period_filter(unplanned, mes_escolhido, visao)
    st.markdown(f"### {period_context['titulo_nao_previsto']}")

    if report.empty:
        st.success("Nenhuma despesa realizada fora do previsto para os filtros selecionados.")
        return

    total_unplanned = report["realizado"].sum()
    cc_unplanned = int((report["motivo_nao_previsto"] == "Centro de custo nao previsto").sum())
    conta_unplanned = int((report["motivo_nao_previsto"] == "Conta nao prevista no centro de custo").sum())

    cols = st.columns(3)
    with cols[0]:
        render_summary_card_with_tone("Total Nao Previsto", format_currency(total_unplanned), tone="bad")
    with cols[1]:
        render_summary_card_with_tone("Lancamentos em CC Nao Previsto", str(cc_unplanned), tone="bad")
    with cols[2]:
        render_summary_card_with_tone("Lancamentos em Conta Nao Prevista", str(conta_unplanned), tone="warn")

    resumo_motivo = (
        report.groupby("motivo_nao_previsto", as_index=False)["realizado"]
        .sum()
        .sort_values("realizado", ascending=False)
    )
    resumo_motivo_exibicao = format_dataframe_br(resumo_motivo, ["realizado"])
    detalhe_report_base = report.sort_values(["realizado", "mes"], ascending=[False, True])
    st.markdown("#### Resumo por Motivo")
    export_cols = st.columns(2)
    with export_cols[0]:
        st.download_button(
            label="Download Resumo Motivo",
            data=dataframe_to_excel_bytes({"Resumo_Motivo": resumo_motivo}),
            file_name="resumo_nao_previsto.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_resumo_motivo_xlsx",
            use_container_width=True,
        )
    with export_cols[1]:
        st.download_button(
            label="Download Detalhe Nao Previsto",
            data=dataframe_to_excel_bytes({"Detalhe_Nao_Previsto": detalhe_report_base}),
            file_name="detalhe_nao_previsto.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_detalhe_nao_previsto_xlsx",
            use_container_width=True,
        )
    st.dataframe(
        resumo_motivo_exibicao,
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("#### Detalhe do Realizado Nao Previsto")
    detalhe_nao_previsto = format_dataframe_br(
        detalhe_report_base,
        ["realizado", "impacto_no_mes"],
    )
    st.dataframe(
        detalhe_nao_previsto,
        use_container_width=True,
        hide_index=True,
    )


def render_indicator_guide_legacy() -> None:
    with st.expander("Entenda os Indicadores"):
        st.markdown("### Como ler Mensal x Acumulado")
        st.write("Mensal mostra apenas o mes selecionado. Acumulado mostra como a linha fecha no periodo ate o mes escolhido.")
        st.markdown(
            """
            **Exemplo simples**

            Janeiro:
            Orcado = 100 | Realizado = 120 | Desvio vs Orcado = +20 | Saldo Final = -20
            Formula:
            Desvio vs Orcado = 120 - 100 = +20
            Saldo Final = 100 - 120 = -20

            Fevereiro:
            Orcado = 100 | Realizado = 90 | Desvio vs Orcado = -10 | Saldo Final = -10
            Formula:
            Desvio vs Orcado = 90 - 100 = -10
            Saldo Final = -20 + 100 - 90 = -10

            Marco:
            Orcado = 100 | Realizado = 80 | Desvio vs Orcado = -20 | Saldo Final = +10
            Formula:
            Desvio vs Orcado = 80 - 100 = -20
            Saldo Final = -10 + 100 - 80 = +10

            Leitura:
            - Mensal Janeiro: a linha estourou o orcado do mes em +20
            - Mensal Fevereiro: a linha ficou 10 abaixo do orcado do mes
            - Acumulado ate Fevereiro: a linha ainda fecha negativa em -10
            - Acumulado ate Marco: a linha recupera e passa a fechar positiva em +10
            """
        )

        st.markdown("### Resumo")
        st.write("Orcado: soma do orçamento do contexto selecionado.")
        st.write("Saldo Anterior: saldo transportado do mes anterior.")
        st.write("Disponivel: orcamento do periodo + saldo anterior.")
        st.write("Realizado: gasto apurado por Exercicio + Periodo contabil do SAP.")
        st.write("Saldo Final: disponivel - realizado.")
        st.write("Itens Estourados: quantidade de linhas com saldo final negativo.")

        st.markdown("### Indicadores Gerenciais")
        st.write("% Eficiencia Orcamentaria: folga restante do orcamento disponivel.")
        st.write("Desvio vs Orcado: realizado - orcado. Positivo significa gasto acima do orcado.")
        st.write("Gastos Nao Previstos: participacao do nao previsto sobre o realizado.")
        st.write("Variacao Mensal: variacao do realizado contra o mes anterior.")
        st.write("Gasto Medio Mensal: media usada para leitura gerencial e forecast.")
        st.write("Mix Despesa Fixa / Variavel: participacao do realizado por tipo de despesa.")
        st.write("Folga Orcamentaria Projetada / Risco de Estouro Anual: compara forecast com o orcado anual.")
        st.write("Forecast Fechamento: projecao anual com base na tendencia do realizado.")

        st.markdown("### Disciplina Orcamentaria")
        st.write("% Aderencia ao Orcado: percentual de linhas dentro da tolerancia de +/- 5%.")
        st.write("Linhas Dentro da Tolerancia: quantidade de linhas aderentes.")
        st.write("Top 10 Ofensores: maiores desvios positivos vs orcado.")

        st.markdown("### Alertas Executivos")
        st.write("Mensal: linhas que estouraram o orcado do mes.")
        st.write("Acumulado: linhas que fecham o periodo com saldo final negativo.")
        st.write("Gastos Nao Previstos: percentual do nao previsto sobre o realizado.")
        st.write("Desvio Medio Absoluto Ponderado: afastamento medio do orcado, ponderado pelo realizado.")

        st.markdown("### Vetores de Risco")
        st.write("Top 5 Causas do Nao Previsto: motivos com maior peso em R$.")
        st.write("Top 5 Centros de Custo em Risco: centros com pior saldo final e maior pressao orcamentaria.")
        st.write("Top 5 Contas em Risco: contas com pior saldo final e maior pressao orcamentaria.")

        st.markdown("### Guia Completo")
        st.write("Consulte o arquivo GUIA_INDICADORES.md na pasta do projeto para a documentacao completa.")


def render_indicator_guide() -> None:
    with st.expander("Entenda os Indicadores"):
        st.markdown("### Como ler Mensal x Acumulado")
        st.write("Mensal mostra apenas o mes selecionado. Acumulado mostra como a linha fecha no periodo ate o mes escolhido.")
        st.markdown(
            """
            **Exemplo simples**

            Janeiro:
            Orcado = 100 | Realizado = 120 | Desvio vs Orcado = +20 | Saldo Final = -20

            Fevereiro:
            Orcado = 100 | Realizado = 90 | Desvio vs Orcado = -10 | Saldo Final = -10

            Marco:
            Orcado = 100 | Realizado = 80 | Desvio vs Orcado = -20 | Saldo Final = +10

            Leitura:
            - Mensal Janeiro: a linha estourou o orcado do mes em +20
            - Mensal Fevereiro: a linha ficou 10 abaixo do orcado do mes
            - Acumulado ate Fevereiro: a linha ainda fecha negativa em -10
            - Acumulado ate Marco: a linha recupera e passa a fechar positiva em +10
            """
        )

        st.markdown("### Resumo")
        st.write("Orcado: total planejado para o contexto selecionado.")
        st.write("Saldo Anterior: saldo transportado do mes anterior.")
        st.write("Exemplo: se janeiro fechou com saldo final de 40, fevereiro comeca com saldo anterior de 40.")
        st.write("Na visao acumulada, o saldo anterior mostra a posicao trazida do fechamento imediatamente anterior ao periodo analisado.")
        st.write("Disponivel: capacidade de gasto no fechamento do periodo. Formula: orcado + saldo anterior.")
        st.write("Exemplo: se o saldo anterior e 40 e o orcado do mes e 100, o disponivel do mes sera 140.")
        st.write("Na visao acumulada, o card de Disponivel representa a capacidade no fechamento do periodo, e nao uma soma simples dos cards.")
        st.write("Realizado: gasto contabilizado no SAP por Exercicio + Periodo contabil.")
        st.write("Saldo Final: disponivel - realizado.")
        st.write("Exemplo: se o disponivel e 140 e o realizado e 90, o saldo final sera 50.")
        st.write("Na visao acumulada, o saldo final representa a sobra ou falta no fechamento do periodo.")
        st.write("Itens Estourados: quantidade de linhas com saldo final negativo.")

        st.markdown("### Indicadores Gerenciais")
        st.write("% Eficiencia Orcamentaria: folga restante dentro do disponivel. Quanto maior, melhor.")
        st.write("Desvio vs Orcado: quanto o gasto ficou acima ou abaixo do orcado. Positivo = estouro do orcado.")
        st.write("Gastos Nao Previstos: peso do nao previsto sobre o realizado.")
        st.write("Variacao Mensal: quanto o gasto subiu ou caiu contra o mes anterior.")
        st.write("Gasto Medio Mensal: media usada como referencia de leitura e projecao.")
        st.write("Mix Despesa Fixa / Variavel: participacao de cada tipo no total realizado.")
        st.write("Folga Orcamentaria Projetada / Risco de Estouro Anual: compara o forecast com o orcado anual.")
        st.write("Forecast Fechamento: projecao anual do gasto pela tendencia atual.")

        st.markdown("### Disciplina Orcamentaria")
        st.write("% Aderencia ao Orcado: percentual de linhas dentro da faixa de tolerancia de +/- 5%.")
        st.write("Linhas Dentro da Tolerancia: quantidade de linhas dentro da faixa considerada saudavel.")
        st.write("Top 10 Ofensores: linhas com maior desvio positivo vs orcado.")

        st.markdown("### Alertas Executivos")
        st.write("Linhas Estouradas: no Mensal olha o estouro do mes; no Acumulado olha o fechamento negativo do periodo.")
        st.write("Gastos Nao Previstos: percentual do nao previsto sobre o realizado.")
        st.write("Desvio Medio Absoluto Ponderado: afastamento medio do orcado, dando mais peso as linhas mais relevantes.")

        st.markdown("### Vetores de Risco")
        st.write("Top 5 Causas do Nao Previsto: principais motivos que geraram gasto fora do planejamento.")
        st.write("Top 5 Centros de Custo em Risco: centros com pior fechamento no contexto selecionado.")
        st.write("Top 5 Contas em Risco: contas com maior pressao orcamentaria no contexto selecionado.")

        st.markdown("### Guia Completo")
        st.write("Consulte o arquivo GUIA_INDICADORES.md na pasta do projeto para a versao completa e detalhada.")


def main() -> None:
    st.title("Controle Orcamentario com Saldo Transportado")
    st.caption(
        "O saldo de cada mes e carregado para o mes seguinte por centro de custo e conta."
    )

    budget_signature = get_file_signature(PATH_ORCADO)
    actual_signature = get_glob_signature("FAGLL03H_*.xlsx")
    dim_cc_signature = get_file_signature(PATH_DIM_CC)
    dim_contas_signature = get_file_signature(PATH_DIM_CONTAS)
    dim_contas_dre_signature = get_file_signature(PATH_DIM_CONTAS_DRE)
    app_signature = get_file_signature(Path(__file__))

    try:
        control, actual_raw = build_budget_control(
            budget_signature,
            actual_signature,
            dim_cc_signature,
            dim_contas_signature,
            dim_contas_dre_signature,
        )
        unplanned_report = build_unplanned_report(control)
    except Exception as error:
        st.error(f"Erro ao carregar a base: {error}")
        return

    control_previsto = control.groupby(["ano", "centro_custo"], as_index=False)["orcado_original"].sum()
    control_previsto = control_previsto[control_previsto["orcado_original"] > 0][["ano", "centro_custo"]]
    control_gerencial = control.merge(control_previsto, on=["ano", "centro_custo"], how="inner")

    filtered, filtered_unplanned, filtered_actual, ano_escolhido, mes_escolhido, visao = apply_filters(control_gerencial, unplanned_report, actual_raw)
    period_context = build_period_context(visao, mes_escolhido)
    visao = str(period_context["visao"])
    mes_escolhido = int(period_context["mes_escolhido"])
    actual_raw_period = apply_period_filter(filtered_actual, mes_escolhido, visao)

    st.caption(f"Versao da app: {app_signature}")
    st.caption(f"Carga dimensao plano de contas: {dim_contas_signature}")
    st.caption(f"Periodo aplicado: {period_context['periodo_ativo']}")
    st.caption("Secao correta: Indicadores Gerenciais")

    snapshot = build_snapshot(filtered, mes_escolhido, visao)
    if snapshot.empty:
        st.warning("Nenhum dado encontrado para os filtros selecionados.")
        return

    period_filtered = apply_period_filter(filtered, mes_escolhido, visao)

    render_summary(snapshot, period_context)
    render_management_summary(snapshot, filtered, filtered_unplanned, period_context)
    render_executive_alerts(snapshot, filtered, filtered_unplanned, period_context)
    render_risk_drivers(snapshot, filtered_unplanned, period_context)
    render_monthly_evolution(period_filtered)
    render_management_charts(filtered, filtered_unplanned, period_context)
    render_budget_discipline(snapshot)
    render_tables(snapshot, actual_raw_period)
    render_unplanned_report(filtered_unplanned, period_context)
    render_quality_alerts(filtered)
    render_indicator_guide()

    st.markdown("### Como rodar")
    st.code("streamlit run app_controle_orcamentario.py", language="bash")
    st.write(f"Ano em uso: {ano_escolhido}")


if __name__ == "__main__":
    main()
