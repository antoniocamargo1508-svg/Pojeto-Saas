from __future__ import annotations

import sys
from pathlib import Path

# When Streamlit runs this file directly, the package root may not be on sys.path.
root_path = Path(__file__).resolve().parent.parent
if str(root_path) not in sys.path:
    sys.path.insert(0, str(root_path))

import altair as alt
import pandas as pd
import streamlit as st

from mvp.utils import (
    build_unplanned_report,
    compute_monthly_evolution,
    compute_monthly_evolution_by_type,
    compute_revenue_expense_counts,
    compute_summary_metrics,
    compute_top_variance_categories,
    compute_type_breakdown,
    dataframe_to_excel_bytes,
    format_currency,
    parse_file,
    validate_uploaded_df,
)

HAS_PLOTLY = False
try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    HAS_PLOTLY = True
except ModuleNotFoundError:
    go = None  # type: ignore[assignment]
    make_subplots = None  # type: ignore[assignment]


st.set_page_config(
    page_title="Controle Orcamentario - Basico",
    layout="wide",
    initial_sidebar_state="expanded",
)


APP_TITLE = "Controle Orcamentario (Basico)"
APP_SUBTITLE = "Versao avulsa: upload manual + dashboard + exportacao. Sem historico em nuvem."
TEMPLATE_PATH = Path(__file__).resolve().parent / "upload_template.csv"

MESES_ABREV: dict[int, str] = {
    1: "Jan",
    2: "Fev",
    3: "Mar",
    4: "Abr",
    5: "Mai",
    6: "Jun",
    7: "Jul",
    8: "Ago",
    9: "Set",
    10: "Out",
    11: "Nov",
    12: "Dez",
}

TYPE_DISPLAY = {
    "revenue": "Receita",
    "expense": "Despesa",
}


def apply_global_style() -> None:
    st.markdown(
        """
        <style>
          .stApp { background: #fbfcfe; }
          [data-testid="stSidebar"] { background: #f7f8fa; border-right: 1px solid #e7eaef; }
          h1, h2, h3 { letter-spacing: -0.02em; }
          .block-container { padding-top: 2rem; padding-bottom: 3rem; }
          div[data-testid="stMetricValue"] { font-size: 1.35rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_app_header(title: str, subtitle: str) -> None:
    st.markdown(f"## {title}")
    st.caption(subtitle)


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


def format_percent(value: float | None, digits: int = 1) -> str:
    if value is None or pd.isna(value):
        return "0,0%"
    formatted = f"{float(value):.{digits}f}%"
    return formatted.replace(".", ",")


def _month_label(series: pd.Series) -> pd.Series:
    raw = series.copy()
    as_text = raw.astype(str).str.strip()

    parsed = pd.to_datetime(raw, errors="coerce")
    year_from_dt = parsed.dt.year.astype("Int64")
    month_from_dt = parsed.dt.month.astype("Int64")

    extracted = as_text.str.extract(r"(?P<year>\d{4})[-/](?P<month>\d{1,2})")
    year = extracted["year"].astype("Int64").fillna(year_from_dt)
    month = extracted["month"].astype("Int64").fillna(month_from_dt)

    month_label = month.map(MESES_ABREV).fillna(month.astype(str))
    label = month_label.astype(str) + "/" + year.astype(str)
    return label.where(year.notna(), as_text)


def get_month_filter_label(month: int) -> str:
    if int(month) == 0:
        return "Todos os meses"
    return MESES_ABREV.get(int(month), f"Mês {month}")


def show_viz(viz: object) -> None:
    if HAS_PLOTLY:
        st.plotly_chart(viz, use_container_width=True)  # type: ignore[arg-type]
    else:
        st.altair_chart(viz, use_container_width=True)  # type: ignore[arg-type]


def render_monthly_budget_actual_figure(
    monthly: pd.DataFrame,
    title: str,
    *,
    absolute_values: bool = False,
    color_actual: str = "#0f766e",
    color_budgeted: str = "#94a3b8",
) -> object:
    data = monthly.copy()
    data["month_label"] = _month_label(data["month_year"])
    data["budgeted"] = pd.to_numeric(data.get("budgeted"), errors="coerce").fillna(0.0)
    data["actual"] = pd.to_numeric(data.get("actual"), errors="coerce").fillna(0.0)
    if absolute_values:
        data["budgeted"] = data["budgeted"].abs()
        data["actual"] = data["actual"].abs()
    data["difference"] = data["actual"] - data["budgeted"]

    if HAS_PLOTLY:
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(
            go.Bar(
                name="Orcado",
                x=data["month_label"],
                y=data["budgeted"],
                marker_color=color_budgeted,
                hovertemplate="Mes=%{x}<br>Orcado=%{y:,.2f}<extra></extra>",
            ),
            secondary_y=False,
        )
        fig.add_trace(
            go.Bar(
                name="Realizado",
                x=data["month_label"],
                y=data["actual"],
                marker_color=color_actual,
                hovertemplate="Mes=%{x}<br>Realizado=%{y:,.2f}<extra></extra>",
            ),
            secondary_y=False,
        )
        fig.add_trace(
            go.Scatter(
                name="Desvio (Real - Orc)",
                x=data["month_label"],
                y=data["difference"],
                mode="lines+markers",
                line=dict(color="#2563eb", width=3),
                hovertemplate="Mes=%{x}<br>Desvio=%{y:,.2f}<extra></extra>",
            ),
            secondary_y=True,
        )
        fig.update_layout(
            title=title,
            barmode="group",
            template="simple_white",
            height=420,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            margin=dict(l=10, r=10, t=60, b=10),
        )
        fig.update_xaxes(tickangle=0)
        fig.update_yaxes(title_text="Valor (R$)", secondary_y=False)
        fig.update_yaxes(title_text="Desvio (R$)", secondary_y=True, showgrid=False)
        return fig

    long = data.melt(
        id_vars=["month_label"],
        value_vars=["budgeted", "actual"],
        var_name="metric",
        value_name="value",
    )
    long["metric"] = long["metric"].map({"budgeted": "Orcado", "actual": "Realizado"}).fillna(long["metric"])
    months_sorted = data["month_label"].dropna().unique().tolist()

    bars = (
        alt.Chart(long)
        .mark_bar(cornerRadiusTopLeft=5, cornerRadiusTopRight=5)
        .encode(
            x=alt.X("month_label:N", title="Mes", sort=months_sorted, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("value:Q", title="Valor (R$)"),
            color=alt.Color(
                "metric:N",
                title="",
                scale=alt.Scale(domain=["Orcado", "Realizado"], range=[color_budgeted, color_actual]),
                legend=alt.Legend(orient="top"),
            ),
            tooltip=[
                alt.Tooltip("month_label:N", title="Mes"),
                alt.Tooltip("metric:N", title="Metrica"),
                alt.Tooltip("value:Q", title="Valor", format=",.2f"),
            ],
        )
    )

    line = (
        alt.Chart(data)
        .mark_line(color="#2563eb", point=True, strokeWidth=3)
        .encode(
            x=alt.X("month_label:N", sort=months_sorted, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("difference:Q", title="Desvio (R$)"),
            tooltip=[
                alt.Tooltip("month_label:N", title="Mes"),
                alt.Tooltip("difference:Q", title="Desvio", format=",.2f"),
            ],
        )
    )

    return alt.layer(bars, line).resolve_scale(y="independent").properties(height=420, title=title)


def render_variance_bar_figure(top_variance: pd.DataFrame, title: str) -> object:
    data = top_variance.copy()
    if data.empty:
        return alt.Chart(pd.DataFrame({"category": [], "difference": []})).mark_bar()
    data["difference"] = pd.to_numeric(data.get("difference"), errors="coerce").fillna(0.0)
    data = data.sort_values("difference", ascending=True)

    if HAS_PLOTLY:
        colors = ["#16a34a" if value <= 0 else "#dc2626" for value in data["difference"].tolist()]
        fig = go.Figure(
            data=[
                go.Bar(
                    x=data["difference"],
                    y=data["category"],
                    orientation="h",
                    marker_color=colors,
                    hovertemplate="Categoria=%{y}<br>Desvio=%{x:,.2f}<extra></extra>",
                )
            ]
        )
        fig.update_layout(
            title=title,
            template="simple_white",
            height=420,
            margin=dict(l=10, r=10, t=60, b=10),
        )
        fig.update_xaxes(title_text="Desvio (Real - Orc)")
        fig.update_yaxes(title_text="")
        return fig

    return (
        alt.Chart(data)
        .mark_bar()
        .encode(
            x=alt.X("difference:Q", title="Desvio (Real - Orc)"),
            y=alt.Y("category:N", title="", sort=None),
            color=alt.condition(alt.datum.difference > 0, alt.value("#dc2626"), alt.value("#16a34a")),
            tooltip=[
                alt.Tooltip("category:N", title="Categoria"),
                alt.Tooltip("difference:Q", title="Desvio", format=",.2f"),
            ],
        )
        .properties(height=420, title=title)
    )


def main() -> None:
    apply_global_style()
    render_app_header(APP_TITLE, APP_SUBTITLE)

    with st.sidebar:
        st.markdown("### Menu")
        page = st.radio("Navegacao", ["Upload", "Dashboard"], index=0)
        st.markdown("---")
        st.caption("Upgrade: Premium inclui historico na nuvem, multiusuario, alertas e automacoes.")

    if "df_uploaded" not in st.session_state:
        st.session_state.df_uploaded = pd.DataFrame()

    if page == "Upload":
        st.subheader("Upload")
        if TEMPLATE_PATH.exists():
            with open(TEMPLATE_PATH, "rb") as template_file:
                st.download_button(
                    label="Download do modelo (CSV)",
                    data=template_file,
                    file_name="modelo_controle_orcamentario.csv",
                    mime="text/csv",
                    use_container_width=True,
                )

        uploaded_file = st.file_uploader("Escolha um arquivo", type=["csv", "xls", "xlsx"])
        if uploaded_file is None:
            return

        try:
            df = validate_uploaded_df(parse_file(uploaded_file))
            st.session_state.df_uploaded = df
            st.success(f"Arquivo carregado: {len(df)} linhas.")
            st.dataframe(df.head(25), use_container_width=True, hide_index=True)
        except Exception as exc:
            st.error(f"Erro ao processar o arquivo: {exc}")
        return

    df = st.session_state.df_uploaded
    if df is None or df.empty:
        st.info("Nenhum dado carregado. Va em Upload.")
        return

    working = df.copy()
    working["date"] = pd.to_datetime(working["date"], errors="coerce")
    working["year"] = working["date"].dt.year
    working["month"] = working["date"].dt.month
    working["record_type"] = working.get("record_type", working.get("type", "expense")).astype(str).str.lower()

    with st.sidebar:
        st.markdown("#### Filtros")
        anos = sorted(working["year"].dropna().unique().astype(int).tolist())
        ano_escolhido = st.selectbox("Ano", anos, index=len(anos) - 1 if anos else 0, key="filtro_ano")
        working = working[working["year"] == int(ano_escolhido)].copy()

        month = st.selectbox(
            "Mês",
            [0] + list(range(1, 13)),
            index=0,
            format_func=get_month_filter_label,
            key="filtro_mes",
        )
        if int(month) != 0:
            working = working[working["month"] == int(month)].copy()

        categorias = sorted(working["category"].dropna().astype(str).unique().tolist())
        categorias_sel = st.multiselect("Categoria", categorias, key="filtro_categoria")
        if categorias_sel:
            working = working[working["category"].isin(categorias_sel)].copy()

        tipos = sorted(working["record_type"].dropna().astype(str).unique().tolist())
        tipos_display = [TYPE_DISPLAY.get(t, t.title()) for t in tipos]
        selected_display = st.multiselect("Tipo", tipos_display)
        if selected_display:
            selected_types = [t for t, display in TYPE_DISPLAY.items() if display in selected_display]
            selected_types += [t for t in tipos if t.title() in selected_display and t not in selected_types]
            working = working[working["record_type"].isin(selected_types)].copy()

    metrics = compute_summary_metrics(working)
    counts = compute_revenue_expense_counts(working)
    type_summary = compute_type_breakdown(working)
    unplanned = build_unplanned_report(working)

    revenue_actual = float(type_summary.loc[type_summary["record_type"] == "revenue", "actual"].sum())
    expense_actual = float(type_summary.loc[type_summary["record_type"] == "expense", "actual"].sum())
    net_actual = revenue_actual - expense_actual

    st.markdown("### Resumo")
    row1 = st.columns(4)
    with row1[0]:
        render_summary_card_with_tone("Receita (Real)", format_currency(revenue_actual), tone="good")
    with row1[1]:
        render_summary_card_with_tone("Despesa (Real)", format_currency(expense_actual), tone="warn")
    with row1[2]:
        render_summary_card_with_tone("Resultado (Real)", format_currency(net_actual), tone="good" if net_actual >= 0 else "bad")
    with row1[3]:
        render_summary_card_with_tone("Nao previsto", str(metrics["unplanned_count"]), tone="warn" if metrics["unplanned_count"] else "good")

    st.markdown("---")
    st.subheader("Evolucao mensal (ano filtrado)")
    monthly_by_type = compute_monthly_evolution_by_type(working)
    monthly_total = compute_monthly_evolution(working)
    if monthly_by_type.empty and monthly_total.empty:
        st.info("Sem dados para evolucao mensal.")
    else:
        tab_expense, tab_revenue, tab_total = st.tabs(["Despesa", "Receita", "Total"])
        with tab_expense:
            expense_monthly = monthly_by_type[monthly_by_type["record_type"] == "expense"].copy()
            if expense_monthly.empty:
                st.info("Sem dados de despesa.")
            else:
                show_viz(
                    render_monthly_budget_actual_figure(
                        expense_monthly,
                        "Despesa - Orcado x Realizado (mensal)",
                        absolute_values=True,
                        color_actual="#dc2626",
                    )
                )
        with tab_revenue:
            revenue_monthly = monthly_by_type[monthly_by_type["record_type"] == "revenue"].copy()
            if revenue_monthly.empty:
                st.info("Sem dados de receita.")
            else:
                show_viz(
                    render_monthly_budget_actual_figure(
                        revenue_monthly,
                        "Receita - Orcado x Realizado (mensal)",
                        absolute_values=True,
                        color_actual="#2563eb",
                    )
                )
        with tab_total:
            if monthly_total.empty:
                st.info("Sem dados totais.")
            else:
                show_viz(
                    render_monthly_budget_actual_figure(
                        monthly_total,
                        "Total - Orcado x Realizado (mensal)",
                        absolute_values=True,
                    )
                )

    st.markdown("---")
    st.subheader("Disciplina Orcamentaria (categorias)")
    expense_df = working.copy()
    expense_df = expense_df[expense_df["record_type"].astype(str).str.lower() == "expense"].copy()
    top_variance = compute_top_variance_categories(expense_df, top_n=10) if not expense_df.empty else pd.DataFrame()
    if not top_variance.empty:
        show_viz(render_variance_bar_figure(top_variance, "Top categorias com maior desvio (Despesa)"))
    else:
        st.info("Sem dados suficientes para ranking de desvio.")

    if not unplanned.empty:
        with st.expander("Lancamentos nao previstos (detalhe)", expanded=False):
            if "difference" not in unplanned.columns:
                unplanned = unplanned.copy()
                if "actual" in unplanned.columns and "budgeted" in unplanned.columns:
                    unplanned["difference"] = pd.to_numeric(unplanned["actual"], errors="coerce") - pd.to_numeric(
                        unplanned["budgeted"], errors="coerce"
                    )
                elif "actual" in unplanned.columns:
                    unplanned["difference"] = pd.to_numeric(unplanned["actual"], errors="coerce")
            sort_cols = [col for col in ["month_year", "difference"] if col in unplanned.columns]
            view_unplanned = unplanned.sort_values(by=sort_cols, ascending=[False] * len(sort_cols)) if sort_cols else unplanned.copy()
            st.dataframe(view_unplanned.head(50), use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("Exportar")
    cols_export = st.columns(2)
    with cols_export[0]:
        st.download_button(
            label="Exportar recorte",
            data=dataframe_to_excel_bytes(working.sort_values(by="date", ascending=False), sheet_name="Recorte"),
            file_name="controle_orcamentario_basico_recorte.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    with cols_export[1]:
        export_unplanned = dataframe_to_excel_bytes(unplanned, sheet_name="NaoPrevisto") if not unplanned.empty else dataframe_to_excel_bytes(pd.DataFrame(), sheet_name="NaoPrevisto")
        st.download_button(
            label="Exportar nao previsto",
            data=export_unplanned,
            file_name="controle_orcamentario_basico_nao_previsto.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

    st.markdown("---")
    st.subheader("Qualidade dos dados")
    row_q = st.columns(4)
    row_q[0].metric("Lancamentos", str(len(working)))
    row_q[1].metric("Categorias", str(int(working["category"].nunique())) if "category" in working.columns else "0")
    row_q[2].metric("Receitas/Despesas", f"{counts['revenues']}/{counts['expenses']}")
    row_q[3].metric("Sem orcado", str(metrics["missing_budgeted"]))


if __name__ == "__main__":
    main()

