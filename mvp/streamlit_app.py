from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

# Ensure the project root is on sys.path so `mvp.*` imports work when Streamlit runs from the file path.
root_path = Path(__file__).resolve().parent.parent
if str(root_path) not in sys.path:
    sys.path.insert(0, str(root_path))

from dotenv import find_dotenv, load_dotenv
import altair as alt
import pandas as pd
import streamlit as st

HAS_PLOTLY = False
try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    HAS_PLOTLY = True
except ModuleNotFoundError:
    go = None  # type: ignore[assignment]
    make_subplots = None  # type: ignore[assignment]

from mvp.auth import (
    authenticate_user,
    accept_tenant_invite,
    create_password_reset_token,
    create_tenant_invite,
    create_user,
    get_tenant_by_id,
    get_user_by_email,
    list_tenant_users,
    mark_user_welcome_completed,
    reset_password_with_code,
    set_tenant_plan,
    update_tenant_profile,
)
from mvp.database import init_db
from mvp.utils import (
    build_unplanned_report,
    compute_category_deviation,
    compute_data_quality_metrics,
    compute_forecast_12m,
    compute_moving_average_trends,
    compute_monthly_evolution,
    compute_monthly_evolution_by_type,
    compute_recurrence_and_expense_type,
    compute_revenue_expense_counts,
    compute_remaining_budget_and_runway,
    compute_summary_metrics,
    compute_top_category_concentration,
    compute_top_variance_categories,
    compute_type_breakdown,
    compute_smart_alerts,
    dataframe_to_excel_bytes,
    format_currency,
    get_system_smtp_config,
    get_tenant_records,
    get_tenant_uploads,
    localize_export_columns,
    parse_file,
    send_email_alert,
    send_system_email_alert,
    build_alert_notification_text,
    store_upload,
    validate_uploaded_df,
)


dotenv_path = find_dotenv(usecwd=True)
if dotenv_path:
    load_dotenv(dotenv_path)

st.set_page_config(
    page_title="Controle Orcamentario - SaaS MVP",
    layout="wide",
    initial_sidebar_state="expanded",
)


APP_TITLE = "Controle Orçamentário"
APP_SUBTITLE = "Dashboard genérico de Orçado x Real com upload Excel/CSV, alertas e exportação."
TEMPLATE_PATH = Path(__file__).resolve().parent / "upload_template.csv"
UPGRADE_URL = os.getenv("UPGRADE_URL")
DEFAULT_UPGRADE_URL = "https://seusite.com/upgrade"
MERCADO_PAGO_ACCESS_TOKEN = os.getenv("MERCADOPAGO_ACCESS_TOKEN")
MERCADO_PAGO_BASE_URL = os.getenv("BASE_URL", "http://localhost:8501")
MERCADO_PAGO_PREFERENCES_URL = "https://api.mercadopago.com/checkout/preferences"
PLAN_PRICE_LABEL = "R$59/mês"

MESES_NOMES: dict[int, str] = {
    1: "Janeiro",
    2: "Fevereiro",
    3: "Março",
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


def _normalize_tenant_plan(tenant) -> str:
    if not tenant:
        return "starter"
    plan = str(getattr(tenant, "plan", "starter") or "starter").strip().lower()
    return "pro" if plan == "pro" else "starter"


def get_plan_display_label(tenant) -> str:
    return "Pro" if _normalize_tenant_plan(tenant) == "pro" else "Starter"


def get_trial_days_left(tenant) -> int | None:
    trial_ends_at = getattr(tenant, "trial_ends_at", None)
    if not isinstance(trial_ends_at, datetime):
        return None
    delta = trial_ends_at - datetime.utcnow()
    if delta.total_seconds() <= 0:
        return None
    return int(delta.days) + 1


def is_pro_tenant(tenant) -> bool:
    if _normalize_tenant_plan(tenant) == "pro":
        return True
    return get_trial_days_left(tenant) is not None


def rerun_app() -> None:
    if hasattr(st, "rerun"):
        st.rerun()


def navigate_to_page(page: str) -> None:
    st.session_state.page_target = page


def handle_checkout_return() -> None:
    get_qparams = getattr(st, "experimental_get_query_params", None)
    set_qparams = getattr(st, "experimental_set_query_params", None)
    if not get_qparams:
        return

    params = get_qparams()
    status = params.get("checkout_result", [None])[0]
    if not status:
        return

    if status == "success":
        tenant_id = st.session_state.get("tenant_id")
        if tenant_id is not None:
            updated = set_tenant_plan(int(tenant_id), plan="pro", subscription_status="active")
            if updated:
                st.success("Pagamento confirmado. Plano Pro ativado com Mercado Pago.")
            else:
                st.warning("Pagamento confirmado, mas não foi possível atualizar o plano automaticamente.")
        else:
            st.success("Pagamento confirmado. Entre novamente para ver o plano atualizado.")
    elif status == "pending":
        st.info("Pagamento pendente no Mercado Pago. Assim que for confirmado, seu plano será ativado.")
    elif status == "failure":
        st.error("O pagamento não foi finalizado. Tente novamente ou entre em contato com o suporte.")

    if set_qparams:
        set_qparams()


def get_mercadopago_checkout_url(tenant) -> str | None:
    if not MERCADO_PAGO_ACCESS_TOKEN:
        return None

    tenant_id = getattr(tenant, "id", None) or getattr(tenant, "tenant_id", None) or "0"
    company_name = getattr(tenant, "name", None) or getattr(tenant, "company_name", None) or "sua empresa"
    payload = {
        "items": [
            {
                "title": "Plano Pro Mensal",
                "description": f"Assinatura Pro mensal para {company_name}",
                "quantity": 1,
                "currency_id": "BRL",
                "unit_price": 59.00,
            }
        ],
        "external_reference": str(tenant_id),
        "back_urls": {
            "success": f"{MERCADO_PAGO_BASE_URL}/?checkout_result=success",
            "pending": f"{MERCADO_PAGO_BASE_URL}/?checkout_result=pending",
            "failure": f"{MERCADO_PAGO_BASE_URL}/?checkout_result=failure",
        },
        "auto_return": "approved",
        "payment_methods": {
            "installments": 12,
        },
        "statement_descriptor": "PROCONTROLE",
    }

    request_data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        MERCADO_PAGO_PREFERENCES_URL,
        data=request_data,
        headers={
            "Authorization": f"Bearer {MERCADO_PAGO_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            response_body = response.read().decode("utf-8")
            preference = json.loads(response_body)
            return preference.get("init_point")
    except urllib.error.HTTPError as error:
        try:
            response_body = error.read().decode("utf-8")
            error_data = json.loads(response_body)
            st.error(f"Erro Mercado Pago: {error_data.get('message', error)}")
        except Exception:
            st.error(f"Erro Mercado Pago: {error}")
        return None
    except Exception as error:
        st.error(f"Erro ao gerar checkout Mercado Pago: {error}")
        return None


def render_upgrade_link(label: str, tenant=None) -> None:
    if MERCADO_PAGO_ACCESS_TOKEN and tenant is not None:
        if MERCADO_PAGO_BASE_URL.startswith("http://localhost") or MERCADO_PAGO_BASE_URL.startswith("https://localhost"):
            st.warning(
                "Você está usando credenciais do Mercado Pago com BASE_URL local. "
                "Para ativar a integração corretamente, configure `BASE_URL` com sua URL pública do Netlify ou domínio real, "
                "por exemplo: https://orcamentario-saas.netlify.app"
            )

        checkout_url = get_mercadopago_checkout_url(tenant)
        if checkout_url:
            safe_url = str(checkout_url).replace('"', '%22').replace("'", "%27")
            st.markdown(
                f'<a href="{safe_url}" target="_blank" rel="noopener noreferrer" '
                f'style="display:inline-block;padding:12px 18px;background:#2563eb;color:#fff;'
                f'border-radius:8px;text-decoration:none;font-size:1rem;">{label}</a>',
                unsafe_allow_html=True,
            )
            st.caption("Mercado Pago aceitará cartão de crédito e Pix quando habilitados na conta.")
            return

    if UPGRADE_URL:
        safe_url = str(UPGRADE_URL).replace('"', '%22').replace("'", "%27")
        st.markdown(
            f'<a href="{safe_url}" target="_blank" rel="noopener noreferrer" '
            f'style="display:inline-block;padding:12px 18px;background:#2563eb;color:#fff;'
            f'border-radius:8px;text-decoration:none;font-size:1rem;">{label}</a>',
            unsafe_allow_html=True,
        )
        st.write("URL de upgrade:")
        st.code(safe_url)
    else:
        internal_label = "Ver página de planos"
        st.button(internal_label, on_click=navigate_to_page, args=("Planos",), key=f"upgrade_button_internal")
        st.caption("Sem checkout externo configurado. Esta ação abre a página interna de planos.")


def render_plan_status_banner(tenant) -> None:
    if is_pro_tenant(tenant):
        if _normalize_tenant_plan(tenant) == "pro":
            st.success(f"Plano Pro ativo. Você já pode acessar todos os recursos de análise avançada por {PLAN_PRICE_LABEL}.")
            return

        days_left = get_trial_days_left(tenant)
        st.success(
            f"Teste grátis do Pro ativo por mais {days_left} dia{'s' if days_left != 1 else ''}. "
            "Aproveite a análise completa enquanto durar."
        )
        st.info(f"Após o trial, o Plano Pro será cobrado a partir de {PLAN_PRICE_LABEL}.")
        render_upgrade_link("Conheça os planos Pro e renove seu acesso ao término do trial", tenant)
        return

    st.warning(
        "Seu plano Starter oferece um dashboard básico. Atualize para o Pro para desbloquear insights avançados, "
        "análises de categoria e previsões mais detalhadas."
    )
    st.markdown(
        "- Top 10 categorias com maior desvio\n"
        "- Análise de riscos financeiros mais profunda\n"
        "- Melhor visão de previsão de estouro de orçamento"
    )
    render_upgrade_link(f"Atualize para o Pro agora por {PLAN_PRICE_LABEL}", tenant)


def render_upgrade_cta(tenant) -> None:
    if is_pro_tenant(tenant) and _normalize_tenant_plan(tenant) == "pro":
        return

    st.markdown("---")
    st.subheader("Melhore seu plano")
    if get_trial_days_left(tenant):
        st.info(
            "Seu trial Pro está ativo. Após o término do período de 7 dias, o Plano Pro será cobrado "
            f"a partir de {PLAN_PRICE_LABEL}."
        )
    else:
        st.error(
            "Seu plano Starter está ativo e o trial Pro terminou. Atualize agora para manter o acesso "
            "aos relatórios e previsões avançados."
        )

    st.markdown(
        "**Comparação de recursos**:\n"
        "- Starter: dashboard com uploads, métricas básicas, exportações e top 3 categorias.\n"
        f"- Pro: análises avançadas de desvio, previsões de estouro, top 10 categorias, alertas e relatórios detalhados por {PLAN_PRICE_LABEL}.\n"
    )
    render_upgrade_link(f"Ver planos e atualizar para Pro por {PLAN_PRICE_LABEL}", tenant)

APP_GUIDE = {
    "title": "Guia rapido para usar o MVP",
    "steps": [
        {
            "title": "1) Cadastre-se e entre",
            "description": "Crie um usuario com e-mail e senha. Em seguida, faca login para acessar o app.",
        },
        {
            "title": "2) Baixe o modelo",
            "description": "Em Upload, baixe o CSV de exemplo para ver o formato esperado.",
        },
        {
            "title": "3) Importe seus dados",
            "description": "Envie um Excel/CSV. O app valida colunas, normaliza datas e salva no banco.",
        },
        {
            "title": "4) Leia os alertas",
            "description": "No Dashboard, veja o resumo, desvios, não previsto e riscos por categoria.",
        },
        {
            "title": "5) Exporte relatorios",
            "description": "Baixe recortes em Excel para compartilhar com o time e auditar lancamentos.",
        },
    ],
}


def apply_global_style() -> None:
    st.markdown(
        """
        <style>
          .stApp { background: #fbfcfe; }
          [data-testid="stSidebar"] { background: #f7f8fa; border-right: 1px solid #e7eaef; }
          h1, h2, h3 { letter-spacing: -0.02em; margin-top: 1rem; margin-bottom: 0.5rem; }
          .block-container { padding-top: 2rem; padding-bottom: 3rem; }
          div[data-testid="stMetricValue"] { font-size: 1.35rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def initialize() -> None:
    init_db()
    apply_global_style()

    st.session_state.setdefault("user", None)
    st.session_state.setdefault("user_id", None)
    st.session_state.setdefault("tenant_id", None)
    st.session_state.setdefault("role", None)
    st.session_state.setdefault("message", None)
    st.session_state.setdefault("show_welcome", False)
    st.session_state.setdefault("_refresh_nonce", "0")
    st.session_state.setdefault("nav_page", "Dashboard")
    st.session_state.setdefault("page_target", None)
    st.session_state.setdefault("alert_auto_send", False)
    st.session_state.setdefault("smtp_provider", os.getenv("SMTP_PROVIDER", "Personalizado"))
    st.session_state.setdefault("alert_recipient_email", os.getenv("SMTP_RECIPIENT", ""))
    st.session_state.setdefault("smtp_server", os.getenv("SMTP_SERVER", ""))
    st.session_state.setdefault("smtp_port", int(os.getenv("SMTP_PORT", "587")) if os.getenv("SMTP_PORT") else 587)
    st.session_state.setdefault("smtp_user", os.getenv("SMTP_USER", ""))
    st.session_state.setdefault("smtp_password", os.getenv("SMTP_PASSWORD", ""))
    st.session_state.setdefault("smtp_sender", os.getenv("SMTP_FROM", ""))


def bump_refresh_nonce() -> None:
    st.session_state["_refresh_nonce"] = str(pd.Timestamp.utcnow().value)


@st.cache_data(show_spinner=False)
def load_user_records_cached(tenant_id: int, refresh_nonce: str) -> pd.DataFrame:
    _ = refresh_nonce
    return get_tenant_records(tenant_id)


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
            margin-bottom:4px;
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


def render_kpi_card(title: str, value: str, caption: str, accent: str = "#0f766e") -> None:
    st.markdown(
        f"""
        <div style='border-radius: 20px; padding: 18px 22px; background: white; box-shadow: 0 12px 30px rgba(15, 23, 42, 0.08); margin-bottom: 4px; width: calc(100% - 2px);'>
            <div style='font-size: 0.9rem; color: #64748b; margin-bottom: 10px; font-weight: 600;'>{title}</div>
            <div style='font-size: 1.8rem; font-weight: 700; color: {accent}; line-height: 1.1;'>{value}</div>
            <div style='font-size: 0.9rem; color: #475569; margin-top: 10px;'>{caption}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def format_percent(value: float | None, digits: int = 1) -> str:
    if value is None or pd.isna(value):
        return "0,0%"
    formatted = f"{float(value):.{digits}f}%"
    return formatted.replace(".", ",")


def get_month_name(month: int) -> str:
    return MESES_NOMES.get(int(month), f"Mes {month}")


def get_month_filter_label(month: int) -> str:
    if int(month) == 0:
        return "Todos os meses"
    return get_month_name(int(month))


def resolve_period_selection(view: str, month: int) -> tuple[str, int]:
    view_resolved = str(view).strip()
    if view_resolved not in {"Mensal", "Acumulado"}:
        view_resolved = "Mensal"

    try:
        month_resolved = int(month)
    except (TypeError, ValueError):
        month_resolved = 0

    if month_resolved not in range(0, 13):
        month_resolved = 0

    return view_resolved, month_resolved


def build_period_labels(view: str, month: int) -> tuple[str, str]:
    month_label = get_month_filter_label(month)
    if view == "Mensal":
        return (f"Periodo ativo: Mensal | {month_label}", f"Resumo Mensal - {month_label}")

    if month == 0:
        return ("Periodo ativo: Acumulado | Todos os meses", "Resumo Acumulado - Todos os meses")

    month_name = get_month_name(month)
    return (f"Periodo ativo: Acumulado | Ate {month_name}", f"Resumo Acumulado - Ate {month_name}")


def apply_period_filter(df: pd.DataFrame, month: int, view: str) -> pd.DataFrame:
    if df.empty:
        return df.copy()

    view, month = resolve_period_selection(view, month)
    if month == 0:
        return df.copy()

    working = df.copy()
    if "month" not in working.columns:
        working["month"] = pd.to_datetime(working["date"], errors="coerce").dt.month

    if view == "Mensal":
        return working[working["month"] == month].copy()

    return working[working["month"] <= month].copy()


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


def render_mix_donut_figure(revenue_actual: float, expense_actual: float) -> object:
    values = pd.DataFrame(
        {
            "tipo": ["Receita", "Despesa"],
            "valor": [max(float(revenue_actual), 0.0), max(float(expense_actual), 0.0)],
        }
    )

    if HAS_PLOTLY:
        fig = go.Figure(
            data=[
                go.Pie(
                    labels=values["tipo"],
                    values=values["valor"],
                    hole=0.55,
                    marker=dict(colors=["#2563eb", "#dc2626"]),
                    textinfo="percent",
                    hovertemplate="%{label}<br>%{value:,.2f}<extra></extra>",
                )
            ]
        )
        fig.update_layout(template="simple_white", height=340, margin=dict(l=10, r=10, t=10, b=10), showlegend=True)
        return fig

    return (
        alt.Chart(values)
        .mark_arc(innerRadius=70)
        .encode(
            theta=alt.Theta("valor:Q"),
            color=alt.Color("tipo:N", scale=alt.Scale(range=["#2563eb", "#dc2626"]), legend=alt.Legend(orient="bottom")),
            tooltip=[alt.Tooltip("tipo:N", title="Tipo"), alt.Tooltip("valor:Q", title="Valor", format=",.2f")],
        )
        .properties(height=340)
    )


def show_login() -> None:
    render_app_header(APP_TITLE, APP_SUBTITLE)
    st.markdown("---")
    st.subheader("Entre ou crie sua conta")

    tab_login, tab_register, tab_invite = st.tabs(["Login", "Cadastro", "Entrar com convite"])

    with tab_login:
        login_email = st.text_input("E-mail", key="login_email", placeholder="voce@empresa.com")
        login_password = st.text_input("Senha", type="password", key="login_password")
        if st.button("Entrar", type="primary"):
            user = authenticate_user(login_email, login_password)
            if user:
                st.session_state.user = user.email
                st.session_state.user_id = user.id
                st.session_state.tenant_id = user.tenant_id
                st.session_state.role = getattr(user, "role", "admin")
                st.session_state.show_welcome = user.is_first_login
                st.session_state.message = "Login realizado com sucesso."
                st.rerun()
            else:
                st.error("E-mail ou senha invalidos.")

        with st.expander("Esqueci minha senha", expanded=False):
            st.write(
                "Informe apenas o e-mail da sua conta. O código de recuperação será enviado automaticamente pelo sistema."
            )
            recover_email = st.text_input("E-mail de recuperação", key="recover_email", placeholder="voce@empresa.com")
            if st.button("Enviar código de recuperação", key="send_recovery_code"):
                if not recover_email:
                    st.error("Informe o e-mail para recuperação.")
                else:
                    token = create_password_reset_token(recover_email)
                    if not token:
                        st.error("E-mail não encontrado.")
                    else:
                        try:
                            send_system_email_alert(
                                recipient_email=recover_email,
                                subject="Código de recuperação de senha",
                                body=(
                                    f"Seu código de recuperação é: {token.code}\n"
                                    f"Válido por 30 minutos.\n\n"
                                    "Se você não solicitou, ignore esta mensagem."
                                ),
                            )
                            st.success("Código de recuperação enviado por e-mail. Verifique sua caixa de entrada.")
                        except Exception as error:
                            st.error(
                                "Não foi possível enviar o e-mail de recuperação automaticamente. Contate o administrador do sistema."
                            )
                            st.error(str(error))
            recovery_code = st.text_input("Código de recuperação", key="recovery_code")
            recovery_password = st.text_input("Nova senha", type="password", key="recovery_password")
            recovery_password_confirm = st.text_input(
                "Confirme a nova senha", type="password", key="recovery_password_confirm"
            )
            if st.button("Redefinir senha", key="reset_password"):
                if not recover_email or not recovery_code:
                    st.error("Informe e-mail e código para redefinir a senha.")
                elif recovery_password != recovery_password_confirm:
                    st.error("As senhas não coincidem.")
                else:
                    user = reset_password_with_code(recover_email, recovery_code, recovery_password)
                    if user:
                        st.success("Senha redefinida com sucesso. Faça login.")
                    else:
                        st.error("Código inválido ou expirado. Solicite um novo código.")

    with tab_register:
        register_email = st.text_input("E-mail", key="register_email", placeholder="voce@empresa.com")
        register_password = st.text_input("Senha", type="password", key="register_password")
        register_password_confirm = st.text_input("Confirme a senha", type="password", key="register_password_confirm")
        if st.button("Criar conta"):
            if len(register_password.encode("utf-8")) > 72:
                st.error(
                    "A senha e muito longa para o metodo de criptografia usado. "
                    "Use uma senha menor ou reduza caracteres especiais."
                )
            elif register_password != register_password_confirm:
                st.error("As senhas não coincidem.")
            elif get_user_by_email(register_email):
                st.error("Ja existe um usuario com este e-mail.")
            else:
                user = create_user(register_email, register_password)
                if user:
                    st.success("Conta criada com sucesso. Faca login.")
                else:
                    st.error("Não foi possível criar a conta. Tente novamente.")

    with tab_invite:
        st.write("Use este fluxo quando alguém da sua empresa te enviou um código de convite.")
        invite_email = st.text_input("Seu e-mail", key="invite_email", placeholder="voce@empresa.com")
        invite_code = st.text_input("Código de convite", key="invite_code")
        invite_password = st.text_input("Crie uma senha", type="password", key="invite_password")
        invite_password_confirm = st.text_input("Confirme a senha", type="password", key="invite_password_confirm")
        if st.button("Entrar na empresa", key="accept_invite_button"):
            if not invite_email or not invite_code:
                st.error("Informe e-mail e código.")
            elif invite_password != invite_password_confirm:
                st.error("As senhas não coincidem.")
            elif len(invite_password.encode("utf-8")) > 72:
                st.error("A senha é muito longa. Use uma senha menor.")
            else:
                user = accept_tenant_invite(invite_email, invite_code, invite_password)
                if not user:
                    st.error("Convite inválido/expirado ou e-mail já cadastrado.")
                else:
                    st.success("Usuário criado. Faça login.")

    st.markdown("---")
    st.caption("Dica: para despesas, use valores positivos e defina `Tipo = expense` no arquivo (quando aplicavel).")


def show_sidebar() -> str:
    with st.sidebar:
        st.markdown(f"### {APP_TITLE}")
        if st.session_state.user:
            st.caption(f"Logado como: {st.session_state.user}")

        page = st.radio(
            "Navegacao",
            ["Dashboard", "Upload", "Planos", "Guia rapido", "Minha conta"],
            key="nav_page",
        )

        st.markdown("---")
        if st.button("Refresh dados", use_container_width=True):
            bump_refresh_nonce()
            st.cache_data.clear()
            st.rerun()

        if st.button("Sair", use_container_width=True):
            st.session_state.user = None
            st.session_state.user_id = None
            st.session_state.tenant_id = None
            st.session_state.role = None
            st.session_state.show_welcome = False
            st.cache_data.clear()
            st.rerun()

    return page


def sidebar_filters(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    if df.empty:
        return df.copy(), df.copy(), {"view": "Mensal", "month": 0, "year": None, "period_caption": "", "resumo_title": ""}

    working = df.copy()
    working["date"] = pd.to_datetime(working["date"], errors="coerce")
    working["year"] = working["date"].dt.year
    working["month"] = working["date"].dt.month
    working["record_type"] = working.get("record_type", working.get("type", "expense")).astype(str).str.lower()

    with st.sidebar:
        st.markdown("#### Filtros")
        anos = sorted(working["year"].dropna().unique().astype(int).tolist())
        if not anos:
            return df.copy(), df.copy(), {"view": "Mensal", "month": 0, "year": None, "period_caption": "", "resumo_title": ""}

        ano_default_index = len(anos) - 1
        ano_escolhido = st.selectbox("Ano", anos, index=ano_default_index, key="filtro_ano")
        working = working[working["year"] == int(ano_escolhido)].copy()

        view = st.radio("Visao", ["Mensal", "Acumulado"], horizontal=True, key="filtro_visao")
        month = st.selectbox(
            "Mes de referencia",
            [0] + list(range(1, 13)),
            index=0,
            format_func=get_month_filter_label,
            key="filtro_mes",
        )

        categorias = sorted(working["category"].dropna().astype(str).unique().tolist())
        categorias_sel = st.multiselect("Categoria", categorias, key="filtro_categoria")
        if categorias_sel:
            working = working[working["category"].isin(categorias_sel)].copy()

        tipos = sorted(working["record_type"].dropna().astype(str).unique().tolist())
        tipos_display = [TYPE_DISPLAY.get(t, t.title()) for t in tipos]
        selected_display = st.multiselect("Tipo", tipos_display, key="filtro_tipo")
        if selected_display:
            selected_types = [t for t, display in TYPE_DISPLAY.items() if display in selected_display]
            selected_types += [t for t in tipos if t.title() in selected_display and t not in selected_types]
            working = working[working["record_type"].isin(selected_types)].copy()

    view, month = resolve_period_selection(view, month)
    period_caption, resumo_title = build_period_labels(view, month)
    period_df = apply_period_filter(working, month, view)
    context = {
        "view": view,
        "month": month,
        "year": int(ano_escolhido),
        "period_caption": period_caption,
        "resumo_title": resumo_title,
    }
    return working, period_df, context


def show_upload() -> None:
    render_app_header("Upload", "Importe um Excel/CSV e gere o dashboard com alertas e exportacao.")
    st.markdown("---")

    col1, col2 = st.columns([1, 1])
    with col1:
        st.subheader("1) Template")
        st.write("Baixe o modelo e adapte as colunas para o seu contexto.")
        if TEMPLATE_PATH.exists():
            with open(TEMPLATE_PATH, "rb") as template_file:
                st.download_button(
                    label="Download do modelo (CSV)",
                    data=template_file,
                    file_name="modelo_controle_orcamentario.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
        else:
            st.info("Template não encontrado. Você ainda pode importar com colunas equivalentes.")

    with col2:
        st.subheader("2) Upload")
        uploaded_file = st.file_uploader("Escolha um arquivo", type=["csv", "xls", "xlsx"])

    if uploaded_file is None:
        return

    try:
        df = parse_file(uploaded_file)
        df = validate_uploaded_df(df)

        st.subheader("Preview e validacao")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Linhas", str(len(df)))
        c2.metric("Meses", str(int(df["month_year"].nunique())) if "month_year" in df.columns else "0")
        c3.metric("Categorias", str(int(df["category"].nunique())) if "category" in df.columns else "0")
        c4.metric("Tipos", ", ".join(sorted(df["record_type"].astype(str).str.lower().unique().tolist()))[:30] or "-")

        st.dataframe(df.head(25), use_container_width=True, hide_index=True)

        if st.button("Processar e salvar", type="primary"):
            count = store_upload(st.session_state.tenant_id, st.session_state.user_id, uploaded_file.name, df)
            bump_refresh_nonce()
            message = f"Upload processado com sucesso. {count} registros salvos."
            if st.session_state.get("alert_auto_send", False):
                try:
                    alert_messages = _collect_alert_messages(df)
                    sent_channels = _send_alerts_if_configured(df, alert_messages=alert_messages)
                    if sent_channels:
                        message += f" Alertas enviados automaticamente por: {', '.join(sent_channels)}."
                    elif not alert_messages:
                        message += " Não havia alertas ativos para envio automático."
                    else:
                        config_status = _alert_configuration_status()
                        missing_parts = []
                        if not config_status["email_ready"]:
                            missing_parts.append("e-mail")
                        message += (
                            " O envio automático estava habilitado, mas o canal não estava configurado corretamente"
                            + (f": {', '.join(missing_parts)}." if missing_parts else ".")
                        )
                except Exception as error:
                    message += f" Falha ao enviar alertas automáticos: {error}"
            st.session_state.message = message
            st.session_state.nav_page = "Dashboard"
            st.rerun()
    except Exception as exc:
        st.error(f"Erro ao processar o arquivo: {exc}")


def _collect_alert_messages(df: pd.DataFrame) -> list[str]:
    df = df.copy()
    alert_messages: list[str] = []
    smart_alerts = compute_smart_alerts(df)
    for _, row in smart_alerts.iterrows():
        alert_messages.append(f"{row['alert']} — {row['category']}: {row['detail']}")

    metrics = compute_summary_metrics(df)
    if metrics["unplanned_count"]:
        alert_messages.append(f"Há {metrics['unplanned_count']} lançamentos não previstos.")
    if metrics["missing_budgeted"]:
        alert_messages.append(f"Há {metrics['missing_budgeted']} registros sem orçado.")
    if metrics["missing_actual"]:
        alert_messages.append(f"Há {metrics['missing_actual']} registros sem realizado.")
    return alert_messages


def _send_alerts_if_configured(df: pd.DataFrame, alert_messages: list[str] | None = None) -> list[str]:
    if alert_messages is None:
        alert_messages = _collect_alert_messages(df)
    if not alert_messages:
        return []

    ctx = {"period_caption": "Dados enviados"}
    working = df.copy()
    working["record_type"] = working.get("record_type", working.get("type", "expense")).astype(str).str.lower()
    working["budgeted"] = pd.to_numeric(working.get("budgeted"), errors="coerce")
    working["actual"] = pd.to_numeric(working.get("actual"), errors="coerce")

    expenses = working[working["record_type"] == "expense"].copy()
    expense_actual_abs = float(expenses["actual"].abs().sum()) if not expenses.empty else 0.0
    expense_budgeted_abs = float(expenses["budgeted"].abs().sum()) if not expenses.empty else 0.0
    budget_utilization = (expense_actual_abs / expense_budgeted_abs * 100) if expense_budgeted_abs > 0 else 0.0
    forecast_metrics = compute_forecast_12m(df)
    runway = compute_remaining_budget_and_runway(df)
    body = build_alert_notification_text(alert_messages, ctx, budget_utilization, forecast_metrics, runway)

    sent_channels: list[str] = []
    config_status = _alert_configuration_status()

    if config_status["email_ready"]:
        send_email_alert(
            recipient_email=config_status["recipient_email"],
            subject="Alerta de risco financeiro",
            body=body,
            smtp_server=config_status["smtp_server"],
            smtp_port=int(config_status["smtp_port"]),
            smtp_user=config_status["smtp_user"],
            smtp_password=config_status["smtp_password"],
            sender_email=config_status["smtp_sender"],
        )
        sent_channels.append("e-mail")

    return sent_channels


def _alert_configuration_status() -> dict[str, object]:
    recipient_email = st.session_state.get("alert_recipient_email", "")
    smtp_server = st.session_state.get("smtp_server", "")
    smtp_port = st.session_state.get("smtp_port", 587)
    smtp_user = st.session_state.get("smtp_user", "")
    smtp_password = st.session_state.get("smtp_password", "")
    smtp_sender = st.session_state.get("smtp_sender", "")

    email_ready = bool(recipient_email and smtp_server and smtp_user and smtp_password and smtp_sender)

    missing_email = []
    if not recipient_email:
        missing_email.append("destinatário do e-mail")
    if not smtp_server:
        missing_email.append("SMTP servidor")
    if not smtp_user:
        missing_email.append("SMTP usuário")
    if not smtp_password:
        missing_email.append("SMTP senha")
    if not smtp_sender:
        missing_email.append("e-mail remetente")

    return {
        "recipient_email": recipient_email,
        "smtp_server": smtp_server,
        "smtp_port": smtp_port,
        "smtp_user": smtp_user,
        "smtp_password": smtp_password,
        "smtp_sender": smtp_sender,
        "email_ready": email_ready,
        "missing_email": missing_email,
    }


def show_dashboard() -> None:
    render_app_header("Dashboard", "Resumo executivo, alertas e riscos por categoria (orcado x real).")

    df = load_user_records_cached(st.session_state.tenant_id, str(st.session_state.get("_refresh_nonce", "0")))
    if df.empty:
        st.info("Nenhum dado encontrado. Faca upload de um arquivo para gerar o dashboard.")
        if st.button("Ir para Upload", type="primary"):
            st.session_state.nav_page = "Upload"
            st.rerun()
        return

    filtered_year, period_df, ctx = sidebar_filters(df)
    st.caption(str(ctx["period_caption"]))
    st.markdown(f"## {ctx['resumo_title']}")

    tenant = get_tenant_by_id(int(st.session_state.tenant_id))
    if not tenant:
        st.error("Empresa não encontrada.")
        return

    is_pro = is_pro_tenant(tenant)
    render_plan_status_banner(tenant)

    filtered_year = filtered_year.copy()
    period_df = period_df.copy()
    filtered_year["budgeted"] = pd.to_numeric(filtered_year.get("budgeted"), errors="coerce")
    filtered_year["actual"] = pd.to_numeric(filtered_year.get("actual"), errors="coerce")
    period_df["budgeted"] = pd.to_numeric(period_df.get("budgeted"), errors="coerce")
    period_df["actual"] = pd.to_numeric(period_df.get("actual"), errors="coerce")

    metrics = compute_summary_metrics(period_df)
    counts = compute_revenue_expense_counts(period_df)
    type_summary = compute_type_breakdown(period_df)
    unplanned = build_unplanned_report(period_df)
    if not unplanned.empty:
        unplanned = unplanned.copy()
        if "month_year" not in unplanned.columns and "date" in unplanned.columns:
            unplanned["month_year"] = pd.to_datetime(unplanned["date"], errors="coerce").dt.strftime("%Y-%m")
        if "difference" not in unplanned.columns:
            if "actual" in unplanned.columns and "budgeted" in unplanned.columns:
                unplanned["difference"] = pd.to_numeric(unplanned["actual"], errors="coerce") - pd.to_numeric(
                    unplanned["budgeted"], errors="coerce"
                )
            elif "actual" in unplanned.columns:
                unplanned["difference"] = pd.to_numeric(unplanned["actual"], errors="coerce")

    category_deviation = compute_category_deviation(period_df)
    concentration = compute_top_category_concentration(period_df)
    moving_trends = compute_moving_average_trends(filtered_year)
    smart_alerts = compute_smart_alerts(period_df)
    recurrence = compute_recurrence_and_expense_type(period_df)
    runway = compute_remaining_budget_and_runway(period_df)
    forecast_metrics = compute_forecast_12m(period_df)
    quality = compute_data_quality_metrics(period_df)

    revenue_budgeted = float(type_summary.loc[type_summary["record_type"] == "revenue", "budgeted"].sum())
    revenue_actual = float(type_summary.loc[type_summary["record_type"] == "revenue", "actual"].sum())
    expense_budgeted = float(type_summary.loc[type_summary["record_type"] == "expense", "budgeted"].sum())
    expense_actual = float(type_summary.loc[type_summary["record_type"] == "expense", "actual"].sum())
    net_actual = revenue_actual - expense_actual

    expense_only = period_df.copy()
    if "record_type" in expense_only.columns:
        expense_only = expense_only[expense_only["record_type"].astype(str).str.lower() == "expense"].copy()
    expense_actual_abs = float(expense_only["actual"].abs().sum()) if not expense_only.empty else 0.0
    expense_budgeted_abs = float(expense_only["budgeted"].abs().sum()) if not expense_only.empty else 0.0
    budget_utilization = (expense_actual_abs / expense_budgeted_abs * 100) if expense_budgeted_abs > 0 else 0.0

    st.markdown("### Resumo")
    row1 = st.columns(4)
    with row1[0]:
        render_summary_card_with_tone("Receita (Real)", format_currency(revenue_actual), tone="good" if revenue_actual >= revenue_budgeted else "warn")
    with row1[1]:
        render_summary_card_with_tone("Despesa (Real)", format_currency(expense_actual), tone="bad" if expense_actual > expense_budgeted else "good")
    with row1[2]:
        render_summary_card_with_tone("Resultado (Real)", format_currency(net_actual), tone="good" if net_actual >= 0 else "bad")
    with row1[3]:
        tone = "good" if budget_utilization <= 100 else "warn" if budget_utilization <= 110 else "bad"
        render_summary_card_with_tone("Execução do orçamento", format_percent(budget_utilization), tone=tone)

    st.markdown("<div style='margin-bottom:8px;'></div>", unsafe_allow_html=True)
    st.markdown("### Indicadores Gerenciais")
    row2 = st.columns(4)
    with row2[0]:
        render_summary_card_with_tone("Lancamentos (recorte)", str(len(period_df)))
    with row2[1]:
        render_summary_card_with_tone("Categorias", str(int(period_df["category"].nunique())) if "category" in period_df.columns else "0")
    with row2[2]:
        render_summary_card_with_tone("Receitas / Despesas", f"{counts['revenues']} / {counts['expenses']}")
    with row2[3]:
        tone = "warn" if metrics["unplanned_count"] else "good"
        render_summary_card_with_tone("Não previsto", str(metrics["unplanned_count"]), tone=tone)

    row2b = st.columns(4)
    with row2b[0]:
        render_kpi_card(
            "Orçamento restante",
            format_currency(runway["budget_remaining"]),
            "Saldo de despesa antes do estouro",
            accent="#16a34a" if runway["budget_remaining"] >= 0 else "#dc2626",
        )
    with row2b[1]:
        days_to_run = str(runway["days_until_runout"]) if runway["days_until_runout"] is not None else "-"
        render_kpi_card(
            "Dias até estouro",
            days_to_run,
            "Com base no ritmo dos últimos 3 meses",
            accent="#2563eb" if runway["days_until_runout"] is None or runway["days_until_runout"] > 60 else "#f59e0b",
        )
    with row2b[2]:
        render_kpi_card(
            "Top 5 concentração",
            f"{concentration['top_share']:.1f}%",
            "Participação do gasto nas 5 maiores categorias",
            accent="#dc2626" if concentration["top_share"] >= 50 else "#0f766e",
        )
    with row2b[3]:
        render_kpi_card(
            "Prob. estouro",
            f"{forecast_metrics['overrun_probability']}%",
            "Probabilidade simplificada de estouro",
            accent="#dc2626" if forecast_metrics["overrun_probability"] >= 60 else "#f59e0b",
        )

    if not is_pro:
        st.markdown("<div style='margin-bottom:16px;'></div>", unsafe_allow_html=True)
        st.markdown("### Recomendações Pro")
        st.info(
            "O plano Starter mostra os principais KPIs do seu orçamento. Atualize para o Pro para ver o "
            "Top 10 categorias com maior desvio e análises de risco mais detalhadas." 
        )

    with st.expander("Guia de cálculo dos indicadores", expanded=False):
        st.markdown(
            """
            - **Execução do orçamento**: despesas reais / orçamento de despesas, expresso em %.
            - **% Execução (Despesa)**: compara o gasto realizado com o orçado para despesas.
            - **Desvio (Despesa)**: diferença entre o gasto realizado e o orçamento previsto.
            - **Índice não previsto**: quanto do gasto real não estava previsto no orçamento.
            - **Top 5 concentração**: quanto das despesas totais está concentrado nas 5 maiores categorias.
            - **Probabilidade de estouro**: estimativa simples de risco de ultrapassar o orçamento com base no padrão atual.
            - **Tendência 3M / 6M**: segue a série de receita e despesa com médias móveis, mostrando comportamento recente e estabilizado.
            - **Qualidade dos dados**: indica valores faltantes, datas inválidas e categorias muito genéricas.
            """,
        )

    revenue_only = period_df.copy()
    if "record_type" in revenue_only.columns:
        revenue_only = revenue_only[revenue_only["record_type"].astype(str).str.lower() == "revenue"].copy()
    revenue_actual_abs = float(revenue_only["actual"].abs().sum()) if not revenue_only.empty else 0.0
    revenue_budgeted_abs = float(revenue_only["budgeted"].abs().sum()) if not revenue_only.empty else 0.0

    unplanned_amount_abs = float(unplanned["actual"].abs().sum()) if not unplanned.empty and "actual" in unplanned.columns else 0.0
    unplanned_index_pct = (unplanned_amount_abs / expense_actual_abs * 100) if expense_actual_abs > 0 else None
    exec_expense_pct = (expense_actual_abs / expense_budgeted_abs * 100) if expense_budgeted_abs > 0 else None
    exec_revenue_pct = (revenue_actual_abs / revenue_budgeted_abs * 100) if revenue_budgeted_abs > 0 else None
    expense_variance = expense_actual_abs - expense_budgeted_abs

    st.markdown("<div style='margin-bottom:24px;'></div>", unsafe_allow_html=True)
    st.markdown("### Disciplina Orçamentária")
    row3 = st.columns(4)
    with row3[0]:
        tone = "good" if (exec_expense_pct or 0.0) <= 100 else "warn" if (exec_expense_pct or 0.0) <= 110 else "bad"
        render_summary_card_with_tone("% Execução (Despesa)", format_percent(exec_expense_pct), tone=tone)
    with row3[1]:
        tone = "good" if expense_variance <= 0 else "bad"
        render_summary_card_with_tone("Desvio (Despesa)", format_currency(expense_variance), tone=tone)
    with row3[2]:
        tone = "good" if (exec_revenue_pct or 0.0) >= 100 else "warn"
        render_summary_card_with_tone("% Execução (Receita)", format_percent(exec_revenue_pct), tone=tone)
    with row3[3]:
        tone = "good" if (unplanned_index_pct or 0.0) <= 5 else "warn" if (unplanned_index_pct or 0.0) <= 10 else "bad"
        render_summary_card_with_tone("Índice não previsto", format_percent(unplanned_index_pct), tone=tone)

    months_in_period = int(period_df["month_year"].nunique()) if "month_year" in period_df.columns else 0
    avg_monthly_expense = (expense_actual_abs / months_in_period) if months_in_period > 0 else None

    year_expense = filtered_year.copy()
    if "record_type" in year_expense.columns:
        year_expense = year_expense[year_expense["record_type"].astype(str).str.lower() == "expense"].copy()
    year_expense_budget = float(year_expense["budgeted"].abs().sum()) if not year_expense.empty else 0.0

    view = str(ctx.get("view") or "Mensal")
    selected_month = int(ctx.get("month") or 0)
    if selected_month == 0 and "month" in filtered_year.columns and not filtered_year["month"].dropna().empty:
        selected_month = int(filtered_year["month"].dropna().max())

    forecast_criterio = "n/d"
    forecast_total = None
    if view == "Mensal":
        base = expense_only.copy()
        if selected_month and "month" in base.columns:
            base = base[base["month"] == selected_month].copy()
        base_value = float(base["actual"].abs().sum()) if not base.empty else 0.0
        forecast_total = base_value * 12
        forecast_criterio = f"Annualizacao do mes {get_month_name(selected_month)}" if selected_month else "Annualizacao do periodo"
    elif view == "Acumulado":
        meses_base = max(selected_month, 1)
        forecast_total = (expense_actual_abs / meses_base) * 12 if meses_base else None
        forecast_criterio = "Projecao pela media do acumulado"

    forecast_gap = (float(forecast_total) - float(year_expense_budget)) if forecast_total is not None else None

    st.markdown("### Projeções")
    row4 = st.columns(4)
    with row4[0]:
        render_summary_card_with_tone("Gasto médio mensal", format_currency(avg_monthly_expense))
    with row4[1]:
        render_summary_card_with_tone("Forecast 12m base", format_currency(forecast_metrics["base_expense"]))
    with row4[2]:
        render_summary_card_with_tone("Forecast otimista", format_currency(forecast_metrics["optimistic_expense"]))
    with row4[3]:
        tone = "bad" if forecast_metrics["overrun_probability"] >= 60 else "warn" if forecast_metrics["overrun_probability"] >= 40 else "good"
        render_summary_card_with_tone(
            "Prob. estouro",
            f"{forecast_metrics['overrun_probability']}%",
            tone=tone,
        )

    st.markdown("<div style='margin-bottom:24px;'></div>", unsafe_allow_html=True)
    st.markdown("### Qualidade dos dados")
    quality_row = st.columns(4)
    with quality_row[0]:
        tone = "bad" if quality["missing_budgeted_pct"] >= 20 else "warn" if quality["missing_budgeted_pct"] >= 10 else "good"
        render_summary_card_with_tone("% sem orçado", format_percent(quality["missing_budgeted_pct"]), tone=tone)
    with quality_row[1]:
        tone = "bad" if quality["missing_actual_pct"] >= 20 else "warn" if quality["missing_actual_pct"] >= 10 else "good"
        render_summary_card_with_tone("% sem realizado", format_percent(quality["missing_actual_pct"]), tone=tone)
    with quality_row[2]:
        tone = "bad" if quality["invalid_dates_pct"] >= 10 else "warn" if quality["invalid_dates_pct"] > 0 else "good"
        render_summary_card_with_tone("Datas inválidas", f"{quality['invalid_dates']}", tone=tone)
    with quality_row[3]:
        tone = "bad" if quality["generic_category_pct"] >= 25 else "warn" if quality["generic_category_pct"] >= 10 else "good"
        render_summary_card_with_tone("Categorias genéricas", format_percent(quality["generic_category_pct"]), tone=tone)

    st.markdown("<div style='margin-bottom:24px;'></div>", unsafe_allow_html=True)
    st.markdown("### Tendência 3M / 6M")
    if moving_trends.empty:
        st.info("Sem dados para tendência de receita e despesa.")
    else:
        moving_trends = moving_trends.copy()
        if "period" in moving_trends.columns:
            moving_trends["month_label"] = (
                moving_trends["period"].dt.month.map(MESES_ABREV).fillna(moving_trends["period"].dt.month.astype(str))
                + "/"
                + moving_trends["period"].dt.year.astype(str)
            )
        else:
            moving_trends["month_label"] = _month_label(moving_trends["month_year"])
        moving_trends_long = moving_trends.melt(
            id_vars=["month_label", "record_type"],
            value_vars=["actual", "ma_3m", "ma_6m"],
            var_name="metric",
            value_name="value",
        )
        moving_trends_long["Tipo"] = (
            moving_trends_long["record_type"].astype(str).str.lower().map({"revenue": "Receita", "expense": "Despesa"}).fillna("Outros")
        )
        moving_trends_long["Linha"] = moving_trends_long["metric"].map(
            {
                "actual": "Realizado",
                "ma_3m": "Média móvel 3M",
                "ma_6m": "Média móvel 6M",
            }
        )
        month_order = list(dict.fromkeys(moving_trends_long["month_label"]))
        base_chart = alt.Chart(moving_trends_long).encode(
            x=alt.X("month_label:N", title="Mês", sort=month_order, axis=alt.Axis(labelAngle=-35)),
            y=alt.Y("value:Q", title="Valor (R$)", axis=alt.Axis(format="~s")),
            color=alt.Color(
                "Linha:N",
                title="Série",
                scale=alt.Scale(
                    domain=["Realizado", "Média móvel 3M", "Média móvel 6M"],
                    range=["#0f766e", "#2563eb", "#9333ea"],
                ),
            ),
            strokeDash=alt.StrokeDash(
                "Linha:N",
                title="Estilo",
                scale=alt.Scale(
                    domain=["Realizado", "Média móvel 3M", "Média móvel 6M"],
                    range=[[], [6, 3], [3, 3]],
                ),
            ),
            size=alt.Size(
                "Linha:N",
                legend=None,
                scale=alt.Scale(domain=["Realizado", "Média móvel 3M", "Média móvel 6M"], range=[3, 2, 2]),
            ),
            tooltip=[
                alt.Tooltip("month_label:N", title="Mês"),
                alt.Tooltip("Tipo:N", title="Tipo"),
                alt.Tooltip("Linha:N", title="Série"),
                alt.Tooltip("value:Q", title="Valor", format=",.2f"),
            ],
        )
        trend_chart = (
            alt.Chart(moving_trends_long)
            .mark_line(point=True)
            .encode(
                x=alt.X("month_label:N", title="Mês", sort=month_order, axis=alt.Axis(labelAngle=-35)),
                y=alt.Y("value:Q", title="Valor (R$)", axis=alt.Axis(format="~s")),
                color=alt.Color(
                    "Linha:N",
                    title="Série",
                    scale=alt.Scale(
                        domain=["Realizado", "Média móvel 3M", "Média móvel 6M"],
                        range=["#0f766e", "#2563eb", "#9333ea"],
                    ),
                ),
                strokeDash=alt.StrokeDash(
                    "Linha:N",
                    title="Estilo",
                    scale=alt.Scale(
                        domain=["Realizado", "Média móvel 3M", "Média móvel 6M"],
                        range=[[], [6, 3], [3, 3]],
                    ),
                ),
                tooltip=[
                    alt.Tooltip("month_label:N", title="Mês"),
                    alt.Tooltip("Tipo:N", title="Tipo"),
                    alt.Tooltip("Linha:N", title="Série"),
                    alt.Tooltip("value:Q", title="Valor", format=",.2f"),
                ],
            )
            .properties(width=420, height=260)
            .facet(column=alt.Column("Tipo:N", title=None, header=alt.Header(labelFontSize=12, titleFontSize=13, labelAngle=0)))
            .resolve_scale(y="independent")
        )
        st.altair_chart(trend_chart, use_container_width=True)

    st.markdown("### Desvio % por categoria")
    if category_deviation.empty:
        st.info("Sem dados de categoria para calcular desvio.")
    else:
        deviation_chart_data = category_deviation.head(12).copy()
        deviation_chart_data["pct_deviation_label"] = deviation_chart_data["pct_deviation"].map(lambda x: f"{x:.1f}%")
        chart = alt.Chart(deviation_chart_data).mark_bar().encode(
            x=alt.X("abs_impact:Q", title="Impacto R$"),
            y=alt.Y("category:N", sort="-x", title="Categoria"),
            color=alt.condition(alt.datum.difference > 0, alt.value("#dc2626"), alt.value("#16a34a")),
            tooltip=["category", "budgeted", "actual", "difference", "pct_deviation_label"],
        )
        st.altair_chart(chart, use_container_width=True)
        st.dataframe(
            deviation_chart_data.rename(
                columns={
                    "budgeted": "Orcado",
                    "actual": "Realizado",
                    "difference": "Desvio",
                    "pct_deviation": "% Desvio",
                    "abs_impact": "Impacto R$",
                }
            ).head(10),
            use_container_width=True,
            hide_index=True,
        )

    st.markdown("### Alertas inteligentes")
    if smart_alerts.empty:
        st.info("Nenhuma categoria acelerando ou fora da curva no recorte atual.")
    else:
        smart_alerts_display = smart_alerts.copy()
        smart_alerts_display["Tipo"] = smart_alerts_display["record_type"].map(TYPE_DISPLAY).fillna(smart_alerts_display["record_type"])
        smart_alerts_display = smart_alerts_display.rename(columns={
            "category": "Categoria",
            "alert": "Alerta",
            "detail": "Detalhe",
        })
        if "record_type" in smart_alerts_display.columns:
            smart_alerts_display = smart_alerts_display.drop(columns=["record_type"])
        st.dataframe(smart_alerts_display, use_container_width=True, hide_index=True)

    with st.expander("Como serão enviados os alertas por e-mail?", expanded=False):
        st.write(
            "Os alertas serão enviados por e-mail quando o sistema estiver configurado com SMTP. "
            "No dashboard você informa o destinatário e as credenciais, e o alerta é disparado para o gestor. "
            "Se a opção de envio automático estiver ativada, o disparo ocorre automaticamente após salvar um novo upload."
        )

    st.markdown("### Recorrencia e despesa fixa x variavel")
    recurrence_row = st.columns(3)
    recurrence_row[0].metric("Categorias recorrentes", f"{recurrence['recurrence_pct']:.0f}%")
    recurrence_row[1].metric("Despesa fixa", f"{recurrence['fixed_expense_pct']:.0f}%")
    recurrence_row[2].metric("Despesa variavel", f"{recurrence['variable_expense_pct']:.0f}%")

    with st.expander("Categorias recorrentes vs pontuais", expanded=False):
        st.write(
            f"Recorrentes: {len(recurrence['recurring_categories'])} categorias / "
            f"Pontuais: {len(recurrence['occasional_categories'])} categorias."
        )
        col_mix_1, col_mix_2 = st.columns([1, 1])
        with col_mix_1:
            show_viz(render_mix_donut_figure(revenue_actual_abs, expense_actual_abs))
        with col_mix_2:
            summary_table = type_summary.copy()
            if not summary_table.empty:
                summary_table["Tipo"] = summary_table["record_type"].map(TYPE_DISPLAY).fillna(summary_table["record_type"])
                summary_table["Orcado"] = summary_table["budgeted"].abs().map(format_currency)
                summary_table["Realizado"] = summary_table["actual"].abs().map(format_currency)
                summary_table["Desvio"] = (summary_table["actual"].abs() - summary_table["budgeted"].abs()).map(format_currency)
                st.dataframe(summary_table[["Tipo", "Orcado", "Realizado", "Desvio"]], use_container_width=True, hide_index=True)
            else:
                st.info("Sem dados para mix.")

    st.markdown("### Alertas Executivos")
    alerts: list[tuple[str, str]] = []
    if budget_utilization >= 110:
        alerts.append(("bad", "Execução acima de 110%: risco de estouro do orçamento."))
    elif budget_utilization >= 100:
        alerts.append(("warn", "Execução acima de 100%: revise categorias com desvio positivo."))
    else:
        alerts.append(("good", "Execução abaixo de 100% para o recorte atual."))

    if metrics["unplanned_count"]:
        alerts.append(("warn", f"Há {metrics['unplanned_count']} lançamentos não previstos no recorte."))
    if metrics["missing_budgeted"]:
        alerts.append(("warn", f"Ha {metrics['missing_budgeted']} registros sem orcado (pode distorcer a analise)."))
    if metrics["missing_actual"]:
        alerts.append(("warn", f"Ha {metrics['missing_actual']} registros sem realizado."))

    for tone, text in alerts:
        if tone == "bad":
            st.error(text)
        elif tone == "warn":
            st.warning(text)
        else:
            st.success(text)

    alert_messages = [text for _, text in alerts]
    with st.expander("Enviar alertas por e-mail", expanded=False):
        st.write(
            "Configure os dados de envio abaixo. O sistema irá enviar alertas ativos por e-mail quando houver risco relevante."
        )
        st.markdown(
            """
            - SMTP servidor: ex. `smtp.gmail.com` ou `smtp.office365.com`.
            - SMTP porta: normalmente `587` para TLS ou `465` para SSL.
            - SMTP usuário/senha: login do remetente.
            - E-mail remetente: e-mail autorizado pelo servidor SMTP.
            """
        )
        st.markdown(
            """
            **Passo a passo para cadastrar:**
            1. Escolha um provedor de e-mail no campo abaixo para preencher valores padrão.
            2. Se usar Gmail e tiver 2FA ativo, gere uma senha de app em `https://myaccount.google.com/apppasswords`.
            3. No Gmail use `smtp.gmail.com` e porta `587`.
            4. No Outlook/Office365 use `smtp.office365.com` e porta `587`.
            5. Se usar Zoho, use `smtp.zoho.com` e porta `587`.
            6. Confirme que o campo `SMTP usuário` é o e-mail completo e `SMTP senha` é a senha de app, não a senha comum.
            7. Preencha os campos e teste primeiro com o botão de envio manual.
            """
        )
        auto_send = st.checkbox(
            "Enviar alertas automaticamente após novo upload",
            key="alert_auto_send",
            value=st.session_state.get("alert_auto_send", False),
        )
        smtp_provider = st.selectbox(
            "Provedor SMTP",
            ["Personalizado", "Gmail", "Outlook/Office365", "Zoho"],
            key="smtp_provider",
        )

        provider_defaults = {
            "Gmail": ("smtp.gmail.com", 587),
            "Outlook/Office365": ("smtp.office365.com", 587),
            "Zoho": ("smtp.zoho.com", 587),
        }
        if smtp_provider in provider_defaults:
            default_server, default_port = provider_defaults[smtp_provider]
            if not st.session_state.get("smtp_server"):
                st.session_state["smtp_server"] = default_server
            if not st.session_state.get("smtp_port"):
                st.session_state["smtp_port"] = default_port

        recipient_email = st.text_input("E-mail destinatário", key="alert_recipient_email", placeholder="gestor@empresa.com")
        smtp_server = st.text_input(
            "SMTP servidor",
            key="smtp_server",
            value=st.session_state.get("smtp_server", os.getenv("SMTP_SERVER", "")),
        )
        smtp_port = st.number_input(
            "SMTP porta",
            key="smtp_port",
            value=int(st.session_state.get("smtp_port", os.getenv("SMTP_PORT", "587"))),
            min_value=1,
            max_value=65535,
        )
        smtp_user = st.text_input("SMTP usuário", key="smtp_user", value=st.session_state.get("smtp_user", os.getenv("SMTP_USER", "")))
        smtp_password = st.text_input(
            "SMTP senha",
            key="smtp_password",
            value=st.session_state.get("smtp_password", os.getenv("SMTP_PASSWORD", "")),
            type="password",
        )
        smtp_sender = st.text_input("E-mail remetente", key="smtp_sender", value=st.session_state.get("smtp_sender", os.getenv("SMTP_FROM", "")))

        if auto_send:
            st.info(
                "O envio automático estará ativo após salvar um novo upload, se houver alertas detectados e as credenciais estiverem preenchidas."
            )

        config_status = _alert_configuration_status()
        if config_status["email_ready"]:
            st.success("E-mail está configurado para envio automático e manual.")
        else:
            st.warning(
                "Configuração de e-mail incompleta: " + ", ".join(config_status["missing_email"])
            )

        send_buttons = st.columns([1])
        email_sent = False
        if send_buttons[0].button("Enviar alerta por e-mail"):
            if recipient_email and smtp_server and smtp_user and smtp_password and smtp_sender:
                try:
                    send_email_alert(
                        recipient_email=recipient_email,
                        subject="Alerta de risco financeiro",
                        body=build_alert_notification_text(alert_messages, ctx, budget_utilization, forecast_metrics, runway),
                        smtp_server=smtp_server,
                        smtp_port=smtp_port,
                        smtp_user=smtp_user,
                        smtp_password=smtp_password,
                        sender_email=smtp_sender,
                    )
                    st.success("Alerta por e-mail enviado com sucesso.")
                    email_sent = True
                except Exception as error:
                    st.error(f"Falha ao enviar e-mail: {error}")
            else:
                st.warning("Preencha o destinatário e as credenciais SMTP para enviar e-mail.")

        if not alert_messages:
            st.info("Não há alertas ativos para envio no momento.")

    st.markdown("---")
    st.subheader("Evolucao mensal (ano filtrado)")
    monthly_by_type = compute_monthly_evolution_by_type(filtered_year)
    monthly_total = compute_monthly_evolution(filtered_year)

    if monthly_by_type.empty and monthly_total.empty:
        st.info("Sem dados para evolucao mensal com os filtros atuais.")
    else:
        tab_expense, tab_revenue, tab_total = st.tabs(["Despesa", "Receita", "Total"])

        with tab_expense:
            expense_monthly = monthly_by_type[monthly_by_type["record_type"] == "expense"].copy()
            if expense_monthly.empty:
                st.info("Sem dados de despesa para o ano filtrado.")
            else:
                show_viz(
                    render_monthly_budget_actual_figure(
                        expense_monthly,
                        "Despesa - Orcado x Realizado (mensal)",
                        absolute_values=True,
                        color_actual="#dc2626",
                    ),
                )

        with tab_revenue:
            revenue_monthly = monthly_by_type[monthly_by_type["record_type"] == "revenue"].copy()
            if revenue_monthly.empty:
                st.info("Sem dados de receita para o ano filtrado.")
            else:
                show_viz(
                    render_monthly_budget_actual_figure(
                        revenue_monthly,
                        "Receita - Orcado x Realizado (mensal)",
                        absolute_values=True,
                        color_actual="#2563eb",
                    ),
                )

        with tab_total:
            if monthly_total.empty:
                st.info("Sem dados totais para o ano filtrado.")
            else:
                show_viz(
                    render_monthly_budget_actual_figure(
                        monthly_total,
                        "Total - Orcado x Realizado (mensal)",
                        absolute_values=True,
                        color_actual="#0f766e",
                    ),
                )

    st.markdown("---")
    st.subheader("Disciplina Orçamentária (categorias)")
    expense_df = period_df.copy()
    if "record_type" in expense_df.columns:
        expense_df = expense_df[expense_df["record_type"].astype(str).str.lower() == "expense"].copy()
    top_variance = compute_top_variance_categories(expense_df, top_n=10 if is_pro else 3) if not expense_df.empty else pd.DataFrame()
    if not top_variance.empty:
        if not is_pro:
            st.info(
                "O plano Starter mostra apenas as 3 maiores categorias. Atualize para o Pro "
                "para ver o Top 10 completo e relatórios de análise aprofundada."
            )
        show_viz(render_variance_bar_figure(top_variance, "Top categorias com maior desvio (Despesa)"))
    else:
        st.info("Sem dados suficientes para ranking de desvio por categoria.")

    if not unplanned.empty:
        with st.expander("Lançamentos não previstos (detalhe)", expanded=False):
            st.write("Despesas sem orcado ou acima do planejado para o recorte.")
            sort_cols = [col for col in ["month_year", "difference"] if col in unplanned.columns]
            if sort_cols:
                view_unplanned = unplanned.sort_values(by=sort_cols, ascending=[False] * len(sort_cols))
            else:
                view_unplanned = unplanned.copy()
            st.dataframe(view_unplanned.head(50), use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("Exportar")
    cols_export = st.columns([1, 1])
    with cols_export[0]:
        export_period_df = localize_export_columns(period_df.sort_values(by="date", ascending=False))
        st.download_button(
            label="Exportar recorte (periodo)",
            data=dataframe_to_excel_bytes(export_period_df, sheet_name="Recorte"),
            file_name="controle_orcamentario_recorte.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    with cols_export[1]:
        if unplanned.empty:
            export_unplanned = dataframe_to_excel_bytes(pd.DataFrame(), sheet_name="NaoPrevisto")
        else:
            export_sort_cols = [col for col in ["month_year", "difference"] if col in unplanned.columns]
            export_df = unplanned.sort_values(by=export_sort_cols, ascending=False) if export_sort_cols else unplanned.copy()
            export_unplanned = dataframe_to_excel_bytes(localize_export_columns(export_df), sheet_name="NaoPrevisto")
        st.download_button(
            label="Exportar não previsto",
            data=export_unplanned,
            file_name="controle_orcamentario_nao_previsto.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    st.caption("Exporta apenas os relatórios de dados em Excel. O PDF completo ficará para a próxima fase.")
    st.markdown("---")
    st.subheader("Registros recentes (recorte)")
    st.dataframe(period_df.sort_values(by="date", ascending=False).head(30), use_container_width=True, hide_index=True)


def show_my_account() -> None:
    render_app_header("Minha conta", "Preferências, equipe e histórico.")
    st.markdown("---")
    st.write(f"Usuário: **{st.session_state.user}**")

    tenant = get_tenant_by_id(int(st.session_state.tenant_id)) if st.session_state.get("tenant_id") else None
    if tenant:
        plan_label = get_plan_display_label(tenant)
        trial_days = get_trial_days_left(tenant)
        st.markdown(f"**Plano atual:** {plan_label}")
        if trial_days:
            st.success(f"Teste grátis do Pro ativo por mais {trial_days} dia{'s' if trial_days != 1 else ''}.")
        elif not is_pro_tenant(tenant):
            st.info("Seu plano Starter está ativo. Faça upgrade para o Pro no site para desbloquear recursos avançados.")
        render_upgrade_cta(tenant)

        if st.session_state.get("role") == "admin":
            st.markdown("---")
            st.subheader("Ações de teste do plano")
            test_cols = st.columns([1, 1])
            with test_cols[0]:
                if st.button("Ativar Pro (teste interno)", key="activate_pro_test"):
                    updated = set_tenant_plan(int(st.session_state.tenant_id), plan="pro", subscription_status="active")
                    if updated:
                        st.success("Plano alterado para Pro. Recarregue a página para ver todos os recursos.")
                        rerun_app()
            with test_cols[1]:
                if st.button("Reiniciar trial Starter", key="reset_starter_trial"):
                    updated = set_tenant_plan(
                        int(st.session_state.tenant_id),
                        plan="starter",
                        subscription_status="inactive",
                        trial_days=7,
                    )
                    if updated:
                        st.success("Trial Starter reiniciado por 7 dias. Recarregue a página para ver o estado atualizado.")
                        rerun_app()

    tab_profile, tab_company, tab_team, tab_uploads = st.tabs(["Perfil", "Empresa", "Equipe", "Histórico de uploads"])

    with tab_profile:
        st.caption(f"Tenant (empresa) ID: {st.session_state.tenant_id}")
        st.caption(f"Perfil: {st.session_state.get('role') or 'n/d'}")
        st.info("Em breve: planos, cobrança e configurações avançadas por empresa.")

    with tab_company:
        tenant = get_tenant_by_id(int(st.session_state.tenant_id))
        if not tenant:
            st.error("Empresa não encontrada.")
        else:
            st.subheader("Dados da empresa")
            company_name = st.text_input("Nome da empresa", value=str(getattr(tenant, "name", "")), key="company_name")
            billing_email = st.text_input(
                "E-mail de cobrança (opcional)",
                value=str(getattr(tenant, "billing_email", "") or ""),
                key="company_billing_email",
                placeholder="financeiro@empresa.com",
            )
            st.caption(f"Plano: {getattr(tenant, 'plan', 'free')} | Assinatura: {getattr(tenant, 'subscription_status', 'inactive')}")

            if st.button("Salvar empresa", key="save_company_button"):
                updated = update_tenant_profile(
                    int(st.session_state.tenant_id),
                    name=company_name,
                    billing_email=billing_email,
                )
                if updated:
                    st.success("Dados da empresa atualizados.")
                else:
                    st.error("Não foi possível salvar.")

    with tab_team:
        users = list_tenant_users(int(st.session_state.tenant_id))
        team_df = pd.DataFrame(
            [
                {
                    "email": u.email,
                    "role": getattr(u, "role", "member"),
                    "created_at": getattr(u, "created_at", None),
                }
                for u in users
            ]
        )
        st.subheader("Usuários da empresa")
        st.dataframe(team_df, use_container_width=True, hide_index=True)

        if (st.session_state.get("role") or "member") != "admin":
            st.info("Apenas administradores podem convidar novos usuários.")
        else:
            st.markdown("---")
            st.subheader("Convidar usuário")
            invite_target = st.text_input("E-mail para convite", key="invite_target_email", placeholder="colega@empresa.com")
            col_inv1, col_inv2 = st.columns([1, 2])
            with col_inv1:
                days = st.number_input("Validade (dias)", min_value=1, max_value=30, value=7, step=1, key="invite_days")
            with col_inv2:
                st.caption("Geramos um código para o e-mail informado. Você pode enviar por e-mail (se SMTP do sistema estiver configurado) ou copiar e mandar no WhatsApp.")

            if st.button("Gerar convite", key="generate_invite_button"):
                if not invite_target:
                    st.error("Informe o e-mail.")
                else:
                    invite = create_tenant_invite(int(st.session_state.tenant_id), invite_target, expires_minutes=int(days) * 24 * 60)
                    st.session_state["last_invite_code"] = invite.code
                    sent = False
                    try:
                        send_system_email_alert(
                            recipient_email=invite_target,
                            subject="Convite para acessar o Controle Orçamentário",
                            body=(
                                "Você foi convidado(a) para acessar o Controle Orçamentário.\n\n"
                                f"E-mail: {invite_target}\n"
                                f"Código: {invite.code}\n"
                                f"Validade: {int(days)} dia(s)\n\n"
                                "Para entrar: abra o app e vá em 'Entrar com convite'.\n"
                                "Se você não solicitou, ignore esta mensagem."
                            ),
                        )
                        sent = True
                    except Exception:
                        sent = False

                    st.success("Convite gerado." + (" E-mail enviado automaticamente." if sent else " Copie o código abaixo e envie ao usuário."))

            last_code = st.session_state.get("last_invite_code")
            if last_code:
                st.code(last_code)

    with tab_uploads:
        st.subheader("Histórico de uploads (empresa)")
        uploads_df = get_tenant_uploads(int(st.session_state.tenant_id))
        if uploads_df.empty:
            st.info("Nenhum upload encontrado ainda.")
        else:
            st.dataframe(uploads_df, use_container_width=True, hide_index=True)


def show_upgrade_page() -> None:
    render_app_header("Planos", "Escolha o plano certo para sua empresa e veja o que está incluído.")
    st.markdown("---")
    st.write(
        "O Plano Starter oferece um controle rápido de Orçado x Real, upload de arquivos, exportação e análise básica. "
        "O Plano Pro inclui insights avançados, top 10 categorias com maior desvio, previsões e alertas."
    )
    st.markdown("### Plano Pro - R$59/mês")
    st.markdown(
        "- Acesso ao dashboard completo de análise de variância e risco\n"
        "- Top 10 categorias com maior desvio\n"
        "- Previsões de estouro do orçamento\n"
        "- Relatórios detalhados e exportação refinada\n"
        "- Trial gratuito de 7 dias ao assinar"
    )
    tenant = get_tenant_by_id(int(st.session_state.tenant_id))
    if MERCADO_PAGO_ACCESS_TOKEN:
        render_upgrade_link("Assinar Pro com Mercado Pago", tenant)
    elif UPGRADE_URL:
        render_upgrade_link("Abrir página de upgrade")
        st.write("URL externa de upgrade:")
        st.code(UPGRADE_URL)
    else:
        st.info("A URL externa de upgrade ainda não está configurada. Esta é a página interna de planos.")
    st.markdown("---")
    st.write("Se quiser, entre em contato para configurar a cobrança e ativar o Plano Pro imediatamente.")


def show_welcome_screen() -> None:
    render_app_header("Bem-vindo", "Um painel pronto para virar SaaS (login, upload, dashboard e exportacao).")
    st.markdown("---")
    st.subheader("Primeiros passos")
    st.write("1) Acesse Upload e envie seu Excel/CSV.")
    st.write("2) Confirme o preview e salve.")
    st.write("3) Leia o Dashboard: resumo, alertas e riscos. Use o Guia de cálculo para entender cada indicador.")
    if st.button("Ir para Upload", type="primary"):
        mark_user_welcome_completed(st.session_state.user_id)
        st.session_state.show_welcome = False
        st.session_state.nav_page = "Upload"
        st.rerun()


def show_getting_started() -> None:
    render_app_header(APP_GUIDE["title"], "Fluxo principal para usar o software de forma rapida e eficiente.")
    st.markdown("---")

    for step in APP_GUIDE["steps"]:
        st.markdown(
            f"""
            <div style="padding:16px;border:1px solid #d9dde3;border-radius:16px;background:#f7f8fa;margin-bottom:12px;">
              <div style="font-weight:800;margin-bottom:6px;color:#16202a;">{step['title']}</div>
              <div style="color:#475467;font-size:0.97rem;">{step['description']}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("---")
    st.subheader("Como usar o template")
    st.write(
        "O modelo de upload e um exemplo simples. Voce pode usar colunas como `Data`, `Categoria`, "
        "`Orcado`, `Realizado/Valor` e (opcional) `Tipo`. O parser adapta variacoes comuns de nomes."
    )

    st.markdown("---")
    st.subheader("Perguntas rapidas")
    with st.expander("Como devo nomear as colunas?", expanded=False):
        st.write("Use nomes comuns. Se voce usar nomes diferentes, o app tenta reconhecer automaticamente.")
    with st.expander("E se meu arquivo tiver apenas Realizado?", expanded=False):
        st.write("O app aceita arquivos com apenas valores realizados. O dashboard trabalha com o que estiver disponivel.")
    with st.expander("Como corrijo erros de importacao?", expanded=False):
        st.write("Revise formato de datas e compare com o template. Em CSV, teste separador virgula/ponto-e-virgula.")

    st.info("Depois do guia, acesse Upload para importar dados e depois o Dashboard para ver os resultados.")


def main() -> None:
    initialize()

    if st.session_state.user is None:
        show_login()
        return

    if st.session_state.show_welcome:
        show_welcome_screen()
        return

    handle_checkout_return()
    page = show_sidebar()
    if st.session_state.get("page_target"):
        page = st.session_state.page_target
        st.session_state.page_target = None

    message = st.session_state.get("message")
    if message:
        st.success(message)
        st.session_state.message = None

    if page == "Upload":
        show_upload()
    elif page == "Dashboard":
        show_dashboard()
    elif page == "Planos":
        show_upgrade_page()
    elif page == "Guia rapido":
        show_getting_started()
    else:
        show_my_account()


if __name__ == "__main__":
    main()
