# FinFlow

[![CI](https://github.com/akincenk/FinFlow/actions/workflows/ci.yml/badge.svg)](https://github.com/akincenk/FinFlow/actions/workflows/ci.yml)

A small FastAPI service: upload a CSV (for example daily revenue/expense/profit) and get descriptive statistics and histograms back as JSON.

## What it does

`POST /upload` accepts one `.csv` file and returns:

- `summary.columns`, `summary.rows`, `summary.numeric_columns`
- `summary.missing_values`: empty cells per column
- `summary.describe`: count, mean, std, min, quartiles and max for each numeric column (`null` where a statistic is undefined, e.g. std of one row)
- `plot_base64`: a PNG with one histogram per numeric column (first 12 columns)

Upload rules:

- The filename must end in `.csv` (otherwise `415`).
- Files over `MAX_UPLOAD_BYTES` (default 1 MiB) are rejected with `413`, checked against `Content-Length` before the body is parsed and again while reading.
- The content must be UTF-8 (a BOM is fine), parse as CSV, have at least one data row and at least one numeric column (otherwise `400`, with a short message and no stack trace).

## Stack

Python 3.11+, FastAPI, pandas, matplotlib (object-oriented `Figure` API, no global pyplot state). All code is in `main.py`; `example_data.csv` is a sample input.

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
curl -F 'file=@example_data.csv' localhost:8000/upload
```

Interactive docs: http://127.0.0.1:8000/docs.

### Docker

```bash
docker build -t finflow .
docker run --rm -p 8000:8000 finflow
```

The container runs as a non-root user.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `MAX_UPLOAD_BYTES` | `1048576` | Maximum upload size |

## API

| Method | Path | Description |
| --- | --- | --- |
| POST | `/upload` | Multipart form field `file`: a CSV file |
| GET | `/health` | Liveness check |

Example (truncated):

```json
{
  "summary": {
    "columns": ["Date", "Revenue", "Expense", "Profit"],
    "rows": 5,
    "numeric_columns": ["Revenue", "Expense", "Profit"],
    "missing_values": {"Date": 0, "Revenue": 0, "Expense": 0, "Profit": 0},
    "describe": {"Revenue": {"count": 5.0, "mean": 14200.0, "std": 3193.74, "min": 10000.0, "...": "..."}}
  },
  "plot_base64": "iVBORw0KGgo..."
}
```

## Tests

```bash
pip install -r requirements-dev.txt
ruff check . && pytest
```

Tests cover the statistics on the sample file, PNG output, NaN handling, BOM input, and rejection of wrong extensions, empty, header-only, non-numeric, non-UTF-8, malformed and oversized files. CI runs them on Python 3.11 and 3.12.

## Limitations / next steps

- Generic statistics only: no finance-specific analysis (trends, margins, period aggregation), and dates are treated as text.
- CSV only; Excel is not supported.
- The whole file is parsed in memory, which is why uploads are capped. No authentication or rate limiting.

## License

MIT, see [LICENSE](LICENSE).
