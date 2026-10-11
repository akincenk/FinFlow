"""FinFlow: upload a CSV file and get statistics, histograms and, for transaction
files, a cash-flow analysis back.

Any CSV with numeric columns gets descriptive statistics. A CSV with `date` and
`amount` columns (case-insensitive; optional `category`) is also treated as a
transaction ledger: positive amounts are income, negative amounts are expenses.
"""

import base64
import io
import math
import os

import pandas as pd
from fastapi import FastAPI, File, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse
from matplotlib.figure import Figure

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(1024 * 1024)))  # 1 MiB
MAX_PLOTTED_COLUMNS = 12
TOP_CATEGORIES = 5

app = FastAPI(
    title="FinFlow",
    description="Upload a CSV, get descriptive statistics, histograms and a cash-flow analysis.",
    version="1.2",
)


@app.middleware("http")
async def reject_large_bodies(request: Request, call_next):
    # Refuse oversized requests before the multipart body is parsed and spooled.
    # This only sees Content-Length; chunked uploads are caught by the read limit in /upload.
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_UPLOAD_BYTES + 64 * 1024:  # allow multipart overhead
        return JSONResponse(status_code=413, content={"detail": f"File larger than {MAX_UPLOAD_BYTES} bytes"})
    return await call_next(request)


def _clean(value):
    """Make a pandas value JSON-safe (NaN/inf -> None)."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def parse_csv(data: bytes) -> pd.DataFrame:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File must be UTF-8 encoded text") from None
    try:
        df = pd.read_csv(io.StringIO(text))
    except (pd.errors.EmptyDataError, pd.errors.ParserError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Could not parse file as CSV") from None
    if df.empty:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "CSV has a header but no data rows")
    return df


def summarize(df: pd.DataFrame) -> dict:
    numeric = df.select_dtypes(include="number")
    if numeric.empty:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "CSV has no numeric columns to analyze")
    describe = {
        col: {stat: _clean(float(v)) for stat, v in stats.items()}
        for col, stats in numeric.describe().to_dict().items()
    }
    return {
        "columns": df.columns.tolist(),
        "rows": len(df),
        "numeric_columns": numeric.columns.tolist(),
        "missing_values": {col: int(n) for col, n in df.isna().sum().items()},
        "describe": describe,
    }


def _money(value: float) -> float:
    return round(float(value), 2)


def _find_column(df: pd.DataFrame, name: str) -> str | None:
    return next((c for c in df.columns if str(c).strip().lower() == name), None)


def analyze_transactions(df: pd.DataFrame) -> dict | None:
    """Cash-flow analysis for ledgers with date + amount columns, else None."""
    date_col, amount_col = _find_column(df, "date"), _find_column(df, "amount")
    if date_col is None or amount_col is None:
        return None
    category_col = _find_column(df, "category")

    dates = pd.to_datetime(df[date_col], errors="coerce", format="mixed")
    amounts = pd.to_numeric(df[amount_col], errors="coerce")
    bad = int((dates.isna() | amounts.isna()).sum())
    if bad:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{bad} row(s) have a missing or invalid date or amount")

    tx = pd.DataFrame({"date": dates, "amount": amounts}).sort_values("date", kind="stable")
    income = tx["amount"].clip(lower=0)
    expense = -tx["amount"].clip(upper=0)

    by_month = (
        pd.DataFrame({"month": tx["date"].dt.strftime("%Y-%m"), "income": income, "expense": expense})
        .groupby("month", sort=True)
        .sum()
    )
    monthly = [
        {"month": m, "income": _money(r.income), "expense": _money(r.expense), "net": _money(r.income - r.expense)}
        for m, r in by_month.iterrows()
    ]

    daily = tx.groupby(tx["date"].dt.date, sort=True)["amount"].sum().cumsum()
    running_balance = [{"date": d.isoformat(), "balance": _money(b)} for d, b in daily.items()]

    result = {
        "transactions": len(tx),
        "period": {"start": tx["date"].min().date().isoformat(), "end": tx["date"].max().date().isoformat()},
        "totals": {
            "income": _money(income.sum()),
            "expense": _money(expense.sum()),
            "net": _money(tx["amount"].sum()),
        },
        "monthly": monthly,
        "running_balance": running_balance,
        "top_expense_categories": None,
    }
    if category_col is not None:
        categories = df.loc[tx.index, category_col].fillna("uncategorized").astype(str)
        spent = expense.groupby(categories).sum()
        spent = spent[spent > 0].sort_values(ascending=False, kind="stable").head(TOP_CATEGORIES)
        result["top_expense_categories"] = [{"category": c, "expense": _money(v)} for c, v in spent.items()]
    return result


def histogram_png(df: pd.DataFrame) -> str:
    """Render one histogram per numeric column; return a base64 PNG."""
    numeric = df.select_dtypes(include="number").iloc[:, :MAX_PLOTTED_COLUMNS]
    n = numeric.shape[1]
    cols = min(n, 3)
    rows = math.ceil(n / cols)
    # Figure (not pyplot) is thread-safe and is freed when it goes out of scope.
    fig = Figure(figsize=(4 * cols, 3 * rows))
    axes = fig.subplots(rows, cols, squeeze=False).flatten()
    for ax, col in zip(axes, numeric.columns, strict=False):
        ax.hist(numeric[col].dropna(), bins=20)
        ax.set_title(str(col))
    for ax in axes[n:]:
        ax.set_visible(False)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    return base64.b64encode(buf.getvalue()).decode("ascii")


# Plain `def`: pandas and matplotlib are CPU-bound, so FastAPI runs this in its threadpool
# instead of blocking the event loop.
@app.post("/upload")
def upload_file(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only .csv files are accepted")
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"File larger than {MAX_UPLOAD_BYTES} bytes")
    if not data.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File is empty")
    df = parse_csv(data)
    summary = summarize(df)
    return {"summary": summary, "finance": analyze_transactions(df), "plot_base64": histogram_png(df)}


@app.get("/health")
def health():
    return {"status": "ok"}
