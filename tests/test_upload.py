import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)
EXAMPLE = (Path(__file__).parent.parent / "example_data.csv").read_bytes()


def upload(content: bytes, filename: str = "data.csv"):
    return client.post("/upload", files={"file": (filename, content, "text/csv")})


def test_example_file_summary():
    r = upload(EXAMPLE)
    assert r.status_code == 200
    s = r.json()["summary"]
    assert s["columns"] == ["Date", "Revenue", "Expense", "Profit"]
    assert s["rows"] == 5
    assert s["numeric_columns"] == ["Revenue", "Expense", "Profit"]
    assert s["describe"]["Revenue"]["mean"] == pytest.approx(14200)
    assert s["describe"]["Profit"]["max"] == 7000
    assert s["missing_values"]["Revenue"] == 0


def test_plot_is_png():
    png = base64.b64decode(upload(EXAMPLE).json()["plot_base64"])
    assert png.startswith(b"\x89PNG\r\n\x1a\n")


def test_missing_values_reported_and_json_safe():
    r = upload(b"a,b\n1,\n2,\n3,\n")  # column b is all NaN -> stats would be NaN
    assert r.status_code == 200
    s = r.json()["summary"]
    assert s["missing_values"] == {"a": 0, "b": 3}
    assert s["describe"]["b"]["mean"] is None


def test_single_row_std_is_null():
    r = upload(b"x\n5\n")
    assert r.status_code == 200
    assert r.json()["summary"]["describe"]["x"]["std"] is None


def test_utf8_bom_header():
    r = upload("﻿Amount\n1\n2\n".encode())
    assert r.json()["summary"]["columns"] == ["Amount"]


@pytest.mark.parametrize(
    ("content", "filename", "code"),
    [
        (EXAMPLE, "data.xlsx", 415),
        (EXAMPLE, "data.csv.exe", 415),
        (b"", "data.csv", 400),
        (b"a,b\n", "data.csv", 400),  # header only
        (b"name,city\nann,paris\n", "data.csv", 400),  # no numeric columns
        (b"\xff\xfe\x00\x01binary", "data.csv", 400),  # not UTF-8
        (b'a,b\n1,"unterminated\n', "data.csv", 400),  # malformed
    ],
)
def test_rejects_bad_files(content, filename, code):
    r = upload(content, filename)
    assert r.status_code == code
    assert "detail" in r.json()


def test_rejects_oversized_file(monkeypatch):
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 100)
    r = upload(b"x\n" + b"1\n" * 100)
    assert r.status_code == 413


def test_middleware_rejects_large_content_length(monkeypatch):
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 100)
    r = upload(b"x\n" + b"1\n" * 40_000)
    assert r.status_code == 413


def test_many_columns_plotted_without_error():
    header = ",".join(f"c{i}" for i in range(20))
    row = ",".join(str(i) for i in range(20))
    r = upload(f"{header}\n{row}\n{row}\n".encode())
    assert r.status_code == 200
    assert len(r.json()["summary"]["numeric_columns"]) == 20


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


TRANSACTIONS = (Path(__file__).parent.parent / "example_transactions.csv").read_bytes()


def test_generic_csv_has_no_finance_section():
    assert upload(EXAMPLE).json()["finance"] is None  # has Date but no amount column


def test_transaction_ledger_analysis():
    r = upload(TRANSACTIONS)
    assert r.status_code == 200
    f = r.json()["finance"]
    assert f["transactions"] == 12
    assert f["period"] == {"start": "2024-01-02", "end": "2024-02-27"}
    assert f["totals"] == {"income": 9150.0, "expense": 3633.05, "net": 5516.95}
    assert f["monthly"] == [
        {"month": "2024-01", "income": 4200.0, "expense": 1867.85, "net": 2332.15},
        {"month": "2024-02", "income": 4950.0, "expense": 1765.2, "net": 3184.8},
    ]
    assert f["top_expense_categories"] == [
        {"category": "housing", "expense": 3000.0},
        {"category": "food", "expense": 392.95},
        {"category": "utilities", "expense": 145.1},
        {"category": "transport", "expense": 95.0},
    ]
    assert f["running_balance"][0] == {"date": "2024-01-02", "balance": 4200.0}
    assert f["running_balance"][-1] == {"date": "2024-02-27", "balance": 5516.95}
    assert len(f["running_balance"]) == 12


def test_ledger_is_sorted_and_same_day_rows_combined():
    csv = b"Amount,DATE\n-50,2024-03-02\n100,2024-03-01\n-20,2024-03-02\n"  # unsorted, any column case
    f = upload(csv).json()["finance"]
    assert f["running_balance"] == [
        {"date": "2024-03-01", "balance": 100.0},
        {"date": "2024-03-02", "balance": 30.0},
    ]
    assert f["top_expense_categories"] is None  # no category column
    assert f["totals"] == {"income": 100.0, "expense": 70.0, "net": 30.0}


def test_missing_category_counted_as_uncategorized():
    csv = b"date,amount,category\n2024-01-01,-10,\n2024-01-02,-30,rent\n"
    cats = upload(csv).json()["finance"]["top_expense_categories"]
    assert cats == [{"category": "rent", "expense": 30.0}, {"category": "uncategorized", "expense": 10.0}]


@pytest.mark.parametrize(
    "csv",
    [
        b"date,amount\n2024-01-01,10\nnot-a-date,5\n",
        b"date,amount\n2024-01-01,10\n2024-01-02,\n",
    ],
)
def test_ledger_with_invalid_rows_rejected(csv):
    r = upload(csv)
    assert r.status_code == 400
    assert "1 row(s)" in r.json()["detail"]
