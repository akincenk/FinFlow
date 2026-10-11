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
