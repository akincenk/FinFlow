# FinFlow

[![CI](https://github.com/akincenk/FinFlow/actions/workflows/ci.yml/badge.svg)](https://github.com/akincenk/FinFlow/actions/workflows/ci.yml)

A small FastAPI service: upload a CSV and get descriptive statistics and histograms back as JSON, plus a cash-flow analysis (totals, monthly income/expense/net, top expense categories, running balance) when the file is a transaction ledger.

## What it does

`POST /upload` accepts one `.csv` file and returns:

- `summary.columns`, `summary.rows`, `summary.numeric_columns`
- `summary.missing_values`: empty cells per column
- `summary.describe`: count, mean, std, min, quartiles and max for each numeric column (`null` where a statistic is undefined, e.g. std of one row)
- `plot_base64`: a PNG with one histogram per numeric column (first 12 columns)
- `finance`: `null` unless the CSV has `date` and `amount` columns (header match is case-insensitive). Then it treats each row as a transaction, positive amounts as income and negative amounts as expenses, and returns:
  - `transactions`, `period.start`, `period.end`
  - `totals`: `income`, `expense` (as a positive number) and `net`
  - `monthly`: one entry per calendar month with `income`, `expense`, `net`
  - `running_balance`: cumulative net per day that has transactions, starting from 0
  - `top_expense_categories`: the five categories with the largest spend, if there is a `category` column (blank categories count as `uncategorized`); otherwise `null`

  Every row needs a parseable date and a numeric amount, otherwise `400` says how many rows are invalid. Amounts are rounded to cents in the output.

Upload rules:

- The filename must end in `.csv` (otherwise `415`).
- Files over `MAX_UPLOAD_BYTES` (default 1 MiB) are rejected with `413`, checked against `Content-Length` before the body is parsed and again while reading.
- The content must be UTF-8 (a BOM is fine), parse as CSV, have at least one data row and at least one numeric column (otherwise `400`, with a short message and no stack trace).

## Stack

Python 3.11+, FastAPI, pandas, matplotlib (object-oriented `Figure` API, no global pyplot state). All code is in `main.py`. Sample inputs: `example_data.csv` (generic numeric table) and `example_transactions.csv` (ledger).

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
curl -F 'file=@example_data.csv' localhost:8000/upload
curl -F 'file=@example_transactions.csv' localhost:8000/upload
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

Example for `example_data.csv` (truncated; it has no `amount` column, so `finance` is `null`):

```json
{
  "summary": {
    "columns": ["Date", "Revenue", "Expense", "Profit"],
    "rows": 5,
    "numeric_columns": ["Revenue", "Expense", "Profit"],
    "missing_values": {"Date": 0, "Revenue": 0, "Expense": 0, "Profit": 0},
    "describe": {"Revenue": {"count": 5.0, "mean": 14200.0, "std": 3193.74, "min": 10000.0, "...": "..."}}
  },
  "finance": null,
  "plot_base64": "iVBORw0KGgo..."
}
```

`finance` for `example_transactions.csv` (truncated):

```json
{
  "transactions": 12,
  "period": {"start": "2024-01-02", "end": "2024-02-27"},
  "totals": {"income": 9150.0, "expense": 3633.05, "net": 5516.95},
  "monthly": [
    {"month": "2024-01", "income": 4200.0, "expense": 1867.85, "net": 2332.15},
    {"month": "2024-02", "income": 4950.0, "expense": 1765.2, "net": 3184.8}
  ],
  "running_balance": [{"date": "2024-01-02", "balance": 4200.0}, "..."],
  "top_expense_categories": [{"category": "housing", "expense": 3000.0}, {"category": "food", "expense": 392.95}, "..."]
}
```

## Tests

```bash
pip install -r requirements-dev.txt
ruff check . && pytest
```

Tests cover the statistics on the sample file, PNG output, NaN handling, BOM input, the ledger analysis (totals, monthly figures, categories, running balance, unsorted input, invalid rows), and rejection of wrong extensions, empty, header-only, non-numeric, non-UTF-8, malformed and oversized files. CI runs them on Python 3.11 and 3.12, runs `pip-audit` on the pinned requirements and builds the Docker image.

## Design decisions

- **Stateless, one endpoint.** Nothing is stored; each upload is analyzed and discarded, so there is no database or user data to protect.
- **Ledger detection by column names.** A file with `date` + `amount` gets the cash-flow section; anything else still gets generic statistics, so the endpoint stays useful for arbitrary numeric CSVs.
- **Sign convention for income/expense.** One signed `amount` column is the most common bank-export format; separate debit/credit columns are not supported.
- **Strict ledger validation.** A bad date or amount fails the request rather than being silently dropped, because dropped rows would make the totals wrong.
- **Synchronous handler.** pandas and matplotlib are CPU-bound, so `/upload` is a plain `def` and runs in FastAPI's threadpool instead of blocking the event loop.

## Security

- Uploads are limited by extension (`.csv`) and size (`MAX_UPLOAD_BYTES`, enforced via `Content-Length` and again while reading).
- Errors return short messages, never stack traces.
- The Docker image runs as a non-root user; runtime dependencies are pinned and separate from dev dependencies.
- There is no authentication: the service stores nothing and spends no money, but run it on a private network or behind an authenticating proxy if exposed.

## Limitations / next steps

- The ledger analysis needs one signed `amount` column and a single currency; no debit/credit columns, budgets, forecasts or multi-currency handling. Monthly buckets use calendar months of the dates as written (no timezone handling).
- CSV only; Excel is not supported.
- The whole file is parsed in memory, which is why uploads are capped. No authentication or rate limiting.

## License

MIT, see [LICENSE](LICENSE).
