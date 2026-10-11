"""FinFlow: upload a CSV file and get descriptive statistics and histograms back.

Built for small financial tables (e.g. daily revenue/expense/profit), but it
works on any CSV with numeric columns.
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

app = FastAPI(
    title="FinFlow",
    description="Upload a CSV, get descriptive statistics and histograms.",
    version="1.1",
)


@app.middleware("http")
async def reject_large_bodies(request: Request, call_next):
    # Refuse oversized requests before the multipart body is parsed and spooled.
    # ponytail: trusts Content-Length; chunked uploads are still caught by the read limit in /upload.
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


@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only .csv files are accepted")
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"File larger than {MAX_UPLOAD_BYTES} bytes")
    if not data.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File is empty")
    df = parse_csv(data)
    return {"summary": summarize(df), "plot_base64": histogram_png(df)}


@app.get("/health")
def health():
    return {"status": "ok"}
