import os
import re
import smtplib
import unicodedata
from email.message import EmailMessage
from io import BytesIO

import pandas as pd
from datetime import datetime
from sqlalchemy import select
from mvp.database import SessionLocal
from mvp.models import Upload, FinancialRecord, User


def slugify(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(text))
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower().strip()
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
    return normalized.strip("_")


def _find_column(columns, names):
    for name in names:
        slug = slugify(name)
        if slug in columns:
            return columns[slug]
    return None


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    columns = {slugify(col): col for col in df.columns}
    mapping = {
        "date": _find_column(columns, [
            "date",
            "data",
            "dia",
            "data_lancamento",
            "data do documento",
            "competencia",
            "periodo",
            "periodo_contabil",
            "mes_ano",
        ]),
        "category": _find_column(columns, [
            "categoria",
            "category",
            "tipo",
            "natureza",
            "tipo_despesa",
            "conta",
            "centro_custo",
            "descricao",
            "classificacao_dre",
        ]),
        "budgeted": _find_column(columns, [
            "orcado",
            "oracado",
            "oracado_original",
            "orcamento",
            "orcamento_planejado",
            "planned",
            "previsao",
            "previsto",
            "orcamento_disponivel",
        ]),
        "actual": _find_column(columns, [
            "real",
            "realizado",
            "valor",
            "valor_real",
            "gasto",
            "actual",
            "spent",
            "realizado_sap",
            "valor_em_moeda_da_empresa",
        ]),
        "record_type": _find_column(columns, [
            "tipo",
            "type",
            "natureza",
            "tipo_despesa",
            "classificacao",
            "classificacao_dre",
        ]),
    }

    if not mapping["date"] or not mapping["category"]:
        raise ValueError(
            "O arquivo precisa conter pelo menos as colunas de data e categoria. "
            "Use nomes como Data, Categoria, Orçado e Real."
        )

    if not mapping["budgeted"] and not mapping["actual"]:
        raise ValueError(
            "O arquivo precisa conter pelo menos uma coluna de valores: Orçado ou Realizado. "
            "Use nomes como Orçado, Realizado, Valor ou Gasto."
        )

    df = df.rename(
        columns={
            mapping["date"]: "date",
            mapping["category"]: "category",
            mapping["budgeted"]: "budgeted",
            mapping["actual"]: "actual",
            mapping["record_type"]: "record_type",
        }
    )

    df = df[[col for col in ["date", "category", "budgeted", "actual", "record_type"] if col in df.columns]]

    return df


def _parse_date_series(series: pd.Series) -> pd.Series:
    values = series.astype(str).str.strip()
    parsed = pd.to_datetime(values, format="%Y-%m-%d", errors="coerce")
    parsed = parsed.combine_first(pd.to_datetime(values, dayfirst=True, errors="coerce"))

    for fmt in ["%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%m/%d/%Y", "%d.%m.%Y"]:
        missing = parsed.isna()
        if not missing.any():
            break
        parsed.loc[missing] = pd.to_datetime(values[missing], format=fmt, errors="coerce")

    return parsed


def _get_record_type_series(df: pd.DataFrame) -> pd.Series:
    if "record_type" in df.columns:
        return df["record_type"].astype(str).str.lower()
    if "type" in df.columns:
        return df["type"].astype(str).str.lower()
    return pd.Series(["expense"] * len(df), index=df.index)


def validate_uploaded_df(df: pd.DataFrame) -> pd.DataFrame:
    if "date" not in df.columns or "category" not in df.columns:
        raise ValueError(
            "O arquivo precisa conter, no mínimo, as colunas Data e Categoria. "
            "Use nomes como Data, Categoria, Orçado e Real."
        )

    df = df.copy()
    df["date"] = _parse_date_series(df["date"])
    if df["date"].isna().any():
        raise ValueError("Algumas datas não puderam ser interpretadas. Verifique o formato do arquivo.")

    df["category"] = df["category"].astype(str).fillna("Sem categoria")

    if "budgeted" in df.columns:
        df["budgeted"] = pd.to_numeric(df["budgeted"], errors="coerce")
    else:
        df["budgeted"] = None

    if "actual" in df.columns:
        df["actual"] = pd.to_numeric(df["actual"], errors="coerce")
    else:
        df["actual"] = None

    if "record_type" in df.columns:
        df["record_type"] = df["record_type"].astype(str).str.lower().fillna("expense")
        df["record_type"] = df["record_type"].apply(
            lambda value: "revenue" if "receita" in value or "rev" in value else "expense"
        )
    else:
        df["record_type"] = df["actual"].apply(
            lambda value: "revenue" if pd.notna(value) and value >= 0 else "expense"
        )

    df["month_year"] = df["date"].dt.strftime("%Y-%m")
    return df


def format_currency(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "R$ 0,00"
    formatted = f"R$ {value:,.2f}"
    return formatted.replace(",", "X").replace(".", ",").replace("X", ".")


def build_unplanned_report(df: pd.DataFrame) -> pd.DataFrame:
    if "budgeted" not in df.columns or "actual" not in df.columns:
        return pd.DataFrame()

    type_column = None
    if "record_type" in df.columns:
        type_column = "record_type"
    elif "type" in df.columns:
        type_column = "type"

    if type_column is not None:
        mask_type = df[type_column].astype(str).str.lower() == "expense"
    else:
        mask_type = df["actual"].apply(lambda value: pd.notna(value) and value < 0)

    mask = (
        mask_type
        & (
            df["budgeted"].isna()
            | (df["actual"] > df["budgeted"])
        )
    )
    return df.loc[mask].copy()


def compute_summary_metrics(df: pd.DataFrame) -> dict:
    result = {
        "total_budgeted": 0.0,
        "total_actual": 0.0,
        "total_difference": 0.0,
        "months": 0,
        "categories": 0,
        "unplanned_count": 0,
        "unplanned_amount": 0.0,
        "missing_budgeted": 0,
        "missing_actual": 0,
        "missing_category": 0,
    }

    df = df.copy()
    if df.empty:
        return result

    df["budgeted"] = pd.to_numeric(df["budgeted"], errors="coerce")
    df["actual"] = pd.to_numeric(df["actual"], errors="coerce")
    df["difference"] = df["actual"] - df["budgeted"]

    result["total_budgeted"] = float(df["budgeted"].sum(skipna=True))
    result["total_actual"] = float(df["actual"].sum(skipna=True))
    result["total_difference"] = float(result["total_actual"] - result["total_budgeted"])
    result["months"] = int(df["month_year"].nunique()) if "month_year" in df.columns else 0
    result["categories"] = int(df["category"].nunique()) if "category" in df.columns else 0
    result["missing_budgeted"] = int(df["budgeted"].isna().sum())
    result["missing_actual"] = int(df["actual"].isna().sum())
    result["missing_category"] = int(df["category"].isna().sum())

    unplanned = build_unplanned_report(df)
    result["unplanned_count"] = int(len(unplanned))
    result["unplanned_amount"] = float(unplanned["actual"].sum(skipna=True))

    return result


def compute_monthly_evolution(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["budgeted"] = pd.to_numeric(df["budgeted"], errors="coerce")
    df["actual"] = pd.to_numeric(df["actual"], errors="coerce")
    df["difference"] = df["actual"] - df["budgeted"]

    return (
        df.groupby("month_year", as_index=False)
        .agg(budgeted=("budgeted", "sum"), actual=("actual", "sum"), difference=("difference", "sum"))
        .sort_values("month_year")
    )


def compute_category_risks(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["difference"] = pd.to_numeric(df["actual"], errors="coerce") - pd.to_numeric(df["budgeted"], errors="coerce")
    result = (
        df.groupby("category", as_index=False)
        .agg(actual=("actual", "sum"), difference=("difference", "sum"))
        .sort_values("difference", ascending=False)
    )
    return result


def compute_budget_utilization(df: pd.DataFrame) -> float:
    df = df.copy()
    df["budgeted"] = pd.to_numeric(df["budgeted"], errors="coerce")
    df["actual"] = pd.to_numeric(df["actual"], errors="coerce")
    total_budgeted = df["budgeted"].sum(skipna=True)
    total_actual = df["actual"].sum(skipna=True)
    if total_budgeted <= 0:
        return 0.0
    return float((total_actual / total_budgeted) * 100)


def compute_revenue_expense_counts(df: pd.DataFrame) -> dict:
    df = df.copy()
    types = _get_record_type_series(df)
    return {
        "revenues": int((types == "revenue").sum()),
        "expenses": int((types == "expense").sum()),
    }


def compute_type_breakdown(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["record_type"] = _get_record_type_series(df)
    df["budgeted"] = pd.to_numeric(df["budgeted"], errors="coerce")
    df["actual"] = pd.to_numeric(df["actual"], errors="coerce")
    result = (
        df.groupby("record_type", as_index=False)
        .agg(
            budgeted=("budgeted", "sum"),
            actual=("actual", "sum"),
        )
        .assign(
            difference=lambda x: x["actual"] - x["budgeted"],
            execution=lambda x: x.apply(
                lambda row: float(row["actual"] / row["budgeted"] * 100)
                if row["budgeted"] > 0
                else 0.0,
                axis=1,
            ),
        )
    )
    return result


def compute_monthly_evolution_by_type(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["record_type"] = _get_record_type_series(df)
    df["budgeted"] = pd.to_numeric(df["budgeted"], errors="coerce")
    df["actual"] = pd.to_numeric(df["actual"], errors="coerce")
    return (
        df.groupby(["month_year", "record_type"], as_index=False)
        .agg(budgeted=("budgeted", "sum"), actual=("actual", "sum"))
        .sort_values(["month_year", "record_type"])
    )


def compute_top_variance_categories(df: pd.DataFrame, top_n: int = 5) -> pd.DataFrame:
    df = df.copy()
    df["budgeted"] = pd.to_numeric(df["budgeted"], errors="coerce")
    df["actual"] = pd.to_numeric(df["actual"], errors="coerce")
    df["difference"] = df["actual"] - df["budgeted"]
    result = (
        df.groupby("category", as_index=False)
        .agg(
            budgeted=("budgeted", "sum"),
            actual=("actual", "sum"),
            difference=("difference", "sum"),
        )
        .assign(percent_diff=lambda x: x.apply(
            lambda row: float(row["difference"] / row["budgeted"] * 100)
            if row["budgeted"] not in (0, None) and pd.notna(row["budgeted"])
            else 0.0,
            axis=1,
        ))
        .sort_values("difference", ascending=False)
    )
    return result.head(top_n)


def _safe_divide(value: float, divisor: float, default: float = 0.0) -> float:
    if divisor is None or divisor == 0 or pd.isna(divisor):
        return default
    return float(value / divisor)


def compute_category_deviation(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["budgeted"] = pd.to_numeric(df["budgeted"], errors="coerce")
    df["actual"] = pd.to_numeric(df["actual"], errors="coerce")
    categories = (
        df.groupby("category", as_index=False)
        .agg(budgeted=("budgeted", "sum"), actual=("actual", "sum"))
    )
    categories["difference"] = categories["actual"] - categories["budgeted"]
    categories["pct_deviation"] = categories.apply(
        lambda row: (row["actual"] / row["budgeted"] - 1) * 100
        if row["budgeted"] not in (0, None) and pd.notna(row["budgeted"])
        else 0.0,
        axis=1,
    )
    categories["abs_impact"] = categories["difference"].abs()
    return categories.sort_values("abs_impact", ascending=False)


def compute_moving_average_trends(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["record_type"] = _get_record_type_series(df)
    df["actual"] = pd.to_numeric(df["actual"], errors="coerce")
    df["month_year"] = df["date"].dt.strftime("%Y-%m")

    monthly = (
        df.groupby(["month_year", "record_type"], as_index=False)["actual"]
        .sum()
    )
    monthly["period"] = pd.to_datetime(monthly["month_year"] + "-01", errors="coerce")
    monthly = monthly.sort_values(["record_type", "period"])
    monthly["ma_3m"] = monthly.groupby("record_type")["actual"].transform(
        lambda s: s.rolling(3, min_periods=1).mean()
    )
    monthly["ma_6m"] = monthly.groupby("record_type")["actual"].transform(
        lambda s: s.rolling(6, min_periods=1).mean()
    )
    return monthly


def compute_top_category_concentration(df: pd.DataFrame, top_n: int = 5) -> dict:
    df = df.copy()
    df["record_type"] = _get_record_type_series(df)
    df["actual"] = pd.to_numeric(df["actual"], errors="coerce")
    expenses = df[df["record_type"] == "expense"].copy()
    expenses["actual_abs"] = expenses["actual"].abs()
    total_expense = expenses["actual_abs"].sum()
    categories = (
        expenses.groupby("category", as_index=False)["actual_abs"].sum()
        .rename(columns={"actual_abs": "expense_amount"})
        .sort_values("expense_amount", ascending=False)
    )
    top5 = categories.head(top_n).copy()
    share = _safe_divide(top5["expense_amount"].sum(), total_expense) * 100
    return {
        "top_categories": top5,
        "total_expense": total_expense,
        "top_share": share,
        "top_n": top_n,
    }


def compute_smart_alerts(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["actual"] = pd.to_numeric(df["actual"], errors="coerce")
    df["record_type"] = _get_record_type_series(df)
    df["month_year"] = df["date"].dt.strftime("%Y-%m")

    monthly = (
        df.groupby(["category", "month_year", "record_type"], as_index=False)["actual"]
        .sum()
    )
    monthly["period"] = pd.to_datetime(monthly["month_year"] + "-01", errors="coerce")
    monthly = monthly.sort_values(["category", "period"])
    monthly["avg_prev_3m"] = monthly.groupby("category")["actual"].transform(
        lambda s: s.shift(1).rolling(3, min_periods=2).mean()
    )
    monthly["std_prev_3m"] = monthly.groupby("category")["actual"].transform(
        lambda s: s.shift(1).rolling(3, min_periods=2).std()
    )

    latest = monthly.groupby("category", as_index=False).tail(1)
    alerts = []
    for _, row in latest.iterrows():
        if pd.notna(row["avg_prev_3m"]) and row["avg_prev_3m"] > 0:
            if row["actual"] > row["avg_prev_3m"] * 1.25:
                alerts.append(
                    {
                        "category": row["category"],
                        "alert": "Categoria acelerando",
                        "detail": (
                            f"{format_currency(row['actual'])} no último mês vs média 3M de "
                            f"{format_currency(row['avg_prev_3m'])}"
                        ),
                        "record_type": row["record_type"],
                    }
                )
        if pd.notna(row["std_prev_3m"]) and row["std_prev_3m"] > 0 and pd.notna(row["avg_prev_3m"]):
            zscore = abs(row["actual"] - row["avg_prev_3m"]) / row["std_prev_3m"]
            if zscore >= 2.0:
                alerts.append(
                    {
                        "category": row["category"],
                        "alert": "Categoria fora da curva",
                        "detail": (
                            f"z={zscore:.1f}: {format_currency(row['actual'])} vs média "
                            f"{format_currency(row['avg_prev_3m'])}"
                        ),
                        "record_type": row["record_type"],
                    }
                )
    if not alerts:
        return pd.DataFrame(columns=["category", "alert", "detail", "record_type"])
    return pd.DataFrame(alerts)


def compute_recurrence_and_expense_type(df: pd.DataFrame) -> dict:
    df = df.copy()
    df["record_type"] = _get_record_type_series(df)
    df["month_year"] = df["date"].dt.strftime("%Y-%m")
    df["actual"] = pd.to_numeric(df["actual"], errors="coerce").abs()

    category_months = df.groupby("category")["month_year"].nunique()
    recurring = category_months[category_months >= 3].index.tolist()
    occasional = category_months[category_months < 3].index.tolist()
    total_categories = len(category_months)
    recurrence_pct = _safe_divide(len(recurring), total_categories) * 100

    expense = df[df["record_type"] == "expense"].copy()
    expense["is_fixed"] = expense["category"].isin(recurring)
    fixed_expense = expense.loc[expense["is_fixed"], "actual"].sum()
    variable_expense = expense.loc[~expense["is_fixed"], "actual"].sum()
    total_expense = fixed_expense + variable_expense
    fixed_pct = _safe_divide(fixed_expense, total_expense) * 100
    variable_pct = _safe_divide(variable_expense, total_expense) * 100

    return {
        "recurring_categories": recurring,
        "occasional_categories": occasional,
        "recurrence_pct": recurrence_pct,
        "fixed_expense_pct": fixed_pct,
        "variable_expense_pct": variable_pct,
        "fixed_expense_amount": fixed_expense,
        "variable_expense_amount": variable_expense,
    }


def compute_remaining_budget_and_runway(df: pd.DataFrame) -> dict:
    df = df.copy()
    df["record_type"] = _get_record_type_series(df)
    df["actual"] = pd.to_numeric(df["actual"], errors="coerce")
    df["budgeted"] = pd.to_numeric(df["budgeted"], errors="coerce")
    df["month_year"] = df["date"].dt.strftime("%Y-%m")

    expenses = df[df["record_type"] == "expense"].copy()
    expenses["actual_abs"] = expenses["actual"].abs()
    total_budgeted = expenses["budgeted"].sum()
    total_actual = expenses["actual_abs"].sum()
    remaining = total_budgeted - total_actual

    monthly_spend = (
        expenses.groupby("month_year", as_index=False)["actual_abs"]
        .sum()
        .sort_values("month_year")
        .tail(3)
        ["actual_abs"]
        .mean()
    )
    if monthly_spend <= 0:
        days_until_runout = None
    else:
        days_until_runout = int(_safe_divide(remaining, monthly_spend / 30, default=0.0))
        if remaining <= 0:
            days_until_runout = 0

    return {
        "total_budgeted_expense": total_budgeted,
        "total_actual_expense": total_actual,
        "budget_remaining": remaining,
        "monthly_spend": monthly_spend,
        "days_until_runout": days_until_runout,
    }


def compute_forecast_12m(df: pd.DataFrame) -> dict:
    df = df.copy()
    df["record_type"] = _get_record_type_series(df)
    df["actual"] = pd.to_numeric(df["actual"], errors="coerce")
    df["budgeted"] = pd.to_numeric(df["budgeted"], errors="coerce")
    df["month_year"] = df["date"].dt.strftime("%Y-%m")

    monthly_actual = (
        df.groupby(["month_year", "record_type"], as_index=False)["actual"]
        .sum()
    )
    monthly_actual["period"] = pd.to_datetime(monthly_actual["month_year"] + "-01", errors="coerce")
    monthly_actual = monthly_actual.sort_values(["record_type", "period"])

    last_6 = monthly_actual.groupby("record_type").tail(6)
    average_actual = last_6.groupby("record_type")["actual"].mean().to_dict()
    if "expense" in average_actual:
        average_actual["expense"] = abs(average_actual["expense"])

    monthly_budget = (
        df[df["record_type"] == "expense"]
        .groupby("month_year", as_index=False)["budgeted"]
        .sum()
    )
    average_budget = monthly_budget["budgeted"].mean() if not monthly_budget.empty else 0.0

    base_expense = average_actual.get("expense", 0.0) * 12
    optimistic_expense = base_expense * 0.9
    pessimistic_expense = base_expense * 1.1

    probability = 50
    if average_budget > 0:
        ratio = _safe_divide(average_actual.get("expense", 0.0), average_budget)
        probability = int(max(0, min(100, (ratio - 1) * 50 + 50)))

    return {
        "base_expense": base_expense,
        "optimistic_expense": optimistic_expense,
        "pessimistic_expense": pessimistic_expense,
        "overrun_probability": probability,
        "average_budget_monthly": average_budget,
    }


def compute_data_quality_metrics(df: pd.DataFrame) -> dict:
    df = df.copy()
    total = len(df)
    if total == 0:
        return {
            "missing_budgeted_pct": 0.0,
            "missing_actual_pct": 0.0,
            "invalid_dates": 0,
            "invalid_dates_pct": 0.0,
            "generic_category_pct": 0.0,
            "quality_score": 100.0,
        }

    generic_values = {
        "outros", "diversos", "sem categoria", "nao informado", "não informado",
        "geral", "varios", "vários", "indefinido", "sem especificacao",
    }
    missing_budgeted = int(df["budgeted"].isna().sum())
    missing_actual = int(df["actual"].isna().sum())
    invalid_dates = int(df["date"].isna().sum())
    generic_categories = int(
        df["category"].astype(str).str.strip().str.lower().isin(generic_values).sum()
    )

    missing_budgeted_pct = _safe_divide(missing_budgeted, total) * 100
    missing_actual_pct = _safe_divide(missing_actual, total) * 100
    invalid_dates_pct = _safe_divide(invalid_dates, total) * 100
    generic_category_pct = _safe_divide(generic_categories, total) * 100

    quality_score = 100.0 - (
        missing_budgeted_pct * 0.25
        + missing_actual_pct * 0.25
        + invalid_dates_pct * 0.25
        + generic_category_pct * 0.25
    )
    quality_score = max(0.0, min(100.0, quality_score))

    return {
        "missing_budgeted_pct": missing_budgeted_pct,
        "missing_actual_pct": missing_actual_pct,
        "invalid_dates": invalid_dates,
        "invalid_dates_pct": invalid_dates_pct,
        "generic_category_pct": generic_category_pct,
        "quality_score": quality_score,
    }


def localize_export_columns(df: pd.DataFrame) -> pd.DataFrame:
    mapping = {
        "date": "Data",
        "category": "Categoria",
        "budgeted": "Orçado",
        "actual": "Realizado",
        "record_type": "Tipo",
        "month_year": "Mês/Ano",
        "difference": "Diferença",
        "pct_deviation": "% Desvio",
        "abs_impact": "Impacto R$",
    }
    df = df.copy()
    rename_map = {source: target for source, target in mapping.items() if source in df.columns}
    return df.rename(columns=rename_map)


def build_alert_notification_text(alerts: list[str], ctx: dict, budget_utilization: float, forecast_metrics: dict, runway: dict) -> str:
    lines = [
        f"Relatório automático de alertas - {ctx.get('period_caption', 'Recorte atual')}",
        "",
        "Alertas detectados:",
    ]
    lines.extend([f"- {alert}" for alert in alerts])
    lines.extend(
        [
            "",
            "Resumo de risco:",
            f" - Execução do orçamento: {budget_utilization:.1f}%",
            f" - Probabilidade de estouro: {forecast_metrics.get('overrun_probability', 0)}%",
            f" - Orçamento restante: {format_currency(runway.get('budget_remaining'))}",
            f" - Dias até estouro: {runway.get('days_until_runout', '-')}",
        ]
    )
    return "\n".join(lines)


def send_email_alert(
    recipient_email: str,
    subject: str,
    body: str,
    smtp_server: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    sender_email: str,
) -> bool:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender_email
    message["To"] = recipient_email
    message.set_content(body)

    try:
        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=15) as smtp:
                smtp.login(smtp_user, smtp_password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(smtp_server, smtp_port, timeout=15) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
                smtp.login(smtp_user, smtp_password)
                smtp.send_message(message)
    except smtplib.SMTPAuthenticationError as exc:
        raise RuntimeError(
            "Autenticação SMTP falhou. Verifique usuário/senha e, se usar Gmail com 2FA, use uma senha de app. "
            f"Detalhe: {exc}"
        ) from exc
    except Exception as exc:
        raise RuntimeError(f"Falha ao enviar e-mail via SMTP: {exc}") from exc

    return True


def get_system_smtp_config() -> dict[str, object]:
    smtp_server = os.getenv("SMTP_SERVER", "")
    smtp_port = int(os.getenv("SMTP_PORT", "587")) if os.getenv("SMTP_PORT") else 587
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_password = os.getenv("SMTP_PASSWORD", "")
    smtp_sender = os.getenv("SMTP_FROM", "")
    return {
        "smtp_server": smtp_server,
        "smtp_port": smtp_port,
        "smtp_user": smtp_user,
        "smtp_password": smtp_password,
        "smtp_sender": smtp_sender,
        "email_ready": bool(smtp_server and smtp_user and smtp_password and smtp_sender),
    }


def send_system_email_alert(recipient_email: str, subject: str, body: str) -> bool:
    config = get_system_smtp_config()
    if not config["email_ready"]:
        raise RuntimeError(
            "O serviço de e-mail não está configurado no servidor. Defina SMTP_SERVER, SMTP_PORT, SMTP_USER, SMTP_PASSWORD e SMTP_FROM."
        )
    return send_email_alert(
        recipient_email=recipient_email,
        subject=subject,
        body=body,
        smtp_server=config["smtp_server"],
        smtp_port=int(config["smtp_port"]),
        smtp_user=config["smtp_user"],
        smtp_password=config["smtp_password"],
        sender_email=config["smtp_sender"],
    )




def dataframe_to_excel_bytes(df: pd.DataFrame, sheet_name: str = "Dados") -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name[:31])
    output.seek(0)
    return output.read()


def _pdf_clean_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(text))
    cleaned = normalized.encode("ascii", "ignore").decode("ascii")
    return cleaned.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def generate_report_pdf_bytes(lines: list[str], title: str = "Relatório") -> bytes:
    output = BytesIO()
    output.write(b"%PDF-1.4\n")

    objects = []
    offsets = []

    text_lines = []
    content_y = 820
    if title:
        text_lines.append(f"BT /F1 14 Tf 50 {content_y} Td ({_pdf_clean_text(title)}) Tj ET\n")
        content_y -= 24
        text_lines.append(f"BT /F1 10 Tf 50 {content_y} Td ({_pdf_clean_text(' ')}) Tj ET\n")
        content_y -= 18

    for line in lines:
        safe_line = _pdf_clean_text(line)
        if len(safe_line) > 120:
            safe_line = safe_line[:120] + "..."
        text_lines.append(f"BT /F1 10 Tf 50 {content_y} Td ({safe_line}) Tj ET\n")
        content_y -= 14
        if content_y < 60:
            break

    content = "".join(text_lines).encode("latin-1")

    offsets.append(output.tell())
    output.write(b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")

    offsets.append(output.tell())
    output.write(b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n")

    offsets.append(output.tell())
    output.write(
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>\nendobj\n"
    )

    offsets.append(output.tell())
    output.write(b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n")

    stream = b"stream\n" + content + b"endstream\n"
    offsets.append(output.tell())
    output.write(b"5 0 obj\n<< /Length %d >>\n" % len(stream))
    output.write(stream)
    output.write(b"endobj\n")

    xref_start = output.tell()
    output.write(b"xref\n0 6\n0000000000 65535 f \n")
    for offset in offsets:
        output.write(f"{offset:010d} 00000 n \n".encode("latin-1"))

    output.write(b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n")
    output.write(str(xref_start).encode("latin-1"))
    output.write(b"\n%%EOF")

    return output.getvalue()


def _read_csv_file(file) -> pd.DataFrame:
    encodings = ["utf-8-sig", "utf-8", "latin1", "cp1252"]
    separators = [None, ";", ","]

    for encoding in encodings:
        for sep in separators:
            try:
                file.seek(0)
                return pd.read_csv(
                    file,
                    sep=sep,
                    engine="python",
                    encoding=encoding,
                    dtype=str,
                    keep_default_na=False,
                    na_values=[""],
                    skipinitialspace=True,
                )
            except Exception:
                continue

    file.seek(0)
    raise ValueError(
        "Não foi possível ler o CSV. Verifique o delimitador (vírgula ou ponto e vírgula) e a codificação do arquivo."
    )


def parse_file(file) -> pd.DataFrame:
    """Lê um arquivo Excel/CSV e normaliza as colunas para um import genérico."""
    if file.name.lower().endswith((".xls", ".xlsx")):
        df = pd.read_excel(file)
    else:
        df = _read_csv_file(file)

    df = _normalize_columns(df)
    df["date"] = _parse_date_series(df["date"])

    if df["date"].isna().any():
        bad_values = df.loc[df["date"].isna(), "date"].astype(str).head(5).tolist()
        raise ValueError(
            "Algumas datas não puderam ser interpretadas. "
            f"Valores problemáticos: {bad_values}. Use formato DD/MM/AAAA ou AAAA-MM-DD."
        )

    df["category"] = df["category"].astype(str).fillna("Sem categoria")
    if "budgeted" in df.columns:
        df["budgeted"] = pd.to_numeric(df["budgeted"], errors="coerce")
    else:
        df["budgeted"] = None

    if "actual" in df.columns:
        df["actual"] = pd.to_numeric(df["actual"], errors="coerce")
    else:
        df["actual"] = None

    if "record_type" in df.columns:
        df["record_type"] = df["record_type"].astype(str).str.lower().fillna("expense")
        df["record_type"] = df["record_type"].apply(
            lambda value: "revenue" if "receita" in value or "rev" in value else "expense"
        )
    else:
        df["record_type"] = df["actual"].apply(
            lambda value: "revenue" if pd.notna(value) and value >= 0 else "expense"
        )

    df["month_year"] = df["date"].dt.strftime("%Y-%m")
    return df


def store_upload(tenant_id: int, user_id: int, filename: str, df: pd.DataFrame) -> int:
    with SessionLocal() as db:
        upload = Upload(tenant_id=tenant_id, user_id=user_id, filename=filename, status="completed")
        db.add(upload)
        db.flush()

        records = []
        for _, row in df.iterrows():
            records.append(
                FinancialRecord(
                    tenant_id=tenant_id,
                    upload_id=upload.id,
                    user_id=user_id,
                    date=row["date"].to_pydatetime() if hasattr(row["date"], "to_pydatetime") else row["date"],
                    category=row["category"],
                    budgeted=float(row["budgeted"]) if pd.notna(row["budgeted"]) else None,
                    actual=float(row["actual"]) if pd.notna(row["actual"]) else None,
                    record_type=row["record_type"],
                    month_year=row["month_year"],
                )
            )

        db.add_all(records)
        db.commit()
        return len(records)


def get_tenant_records(tenant_id: int) -> pd.DataFrame:
    with SessionLocal() as db:
        statement = select(FinancialRecord).where(FinancialRecord.tenant_id == tenant_id)
        rows = db.scalars(statement).all()

    if not rows:
        return pd.DataFrame()

    data = [
        {
            "date": row.date,
            "category": row.category,
            "budgeted": row.budgeted,
            "actual": row.actual,
            "record_type": row.record_type,
            "type": row.record_type,
            "month_year": row.month_year,
        }
        for row in rows
    ]
    return pd.DataFrame(data)


def get_tenant_uploads(tenant_id: int) -> pd.DataFrame:
    with SessionLocal() as db:
        statement = (
            select(Upload, User.email)
            .join(User, User.id == Upload.user_id)
            .where(Upload.tenant_id == int(tenant_id))
            .order_by(Upload.created_at.desc())
        )
        rows = db.execute(statement).all()

    if not rows:
        return pd.DataFrame(columns=["id", "filename", "created_at", "status", "uploaded_by"])

    data = [
        {
            "id": upload.id,
            "filename": upload.filename,
            "created_at": upload.created_at,
            "status": upload.status,
            "uploaded_by": email,
        }
        for (upload, email) in rows
    ]
    return pd.DataFrame(data)


def get_user_records(user_id: int) -> pd.DataFrame:
    """Compat: mantida para chamadas antigas; prefira get_tenant_records()."""
    with SessionLocal() as db:
        statement = select(FinancialRecord).where(FinancialRecord.user_id == user_id)
        rows = db.scalars(statement).all()

    if not rows:
        return pd.DataFrame()

    data = [
        {
            "date": row.date,
            "category": row.category,
            "budgeted": row.budgeted,
            "actual": row.actual,
            "record_type": row.record_type,
            "type": row.record_type,
            "month_year": row.month_year,
        }
        for row in rows
    ]
    return pd.DataFrame(data)
