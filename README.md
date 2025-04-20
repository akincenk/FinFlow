# FinFlow

FinFlow is a simple yet powerful API that allows users to upload financial data in CSV format and get instant insights, including descriptive statistics and histograms. Built with FastAPI and Pandas.

## Features

- Upload CSV data
- Get column info, shape, descriptive stats
- Auto-generated histogram plots (base64 encoded)

## Tech Stack

- Python, FastAPI, Pandas, Matplotlib

## Getting Started

### Install dependencies

```bash
pip install -r requirements.txt
```

### Run the API

```bash
uvicorn main:app --reload
```

### Test with Swagger

Visit: `http://localhost:8000/docs`

### Upload Endpoint

- POST `/upload`
- Body: `file` (CSV)

### Example cURL

```bash
curl -X 'POST' \
  'http://localhost:8000/upload' \
  -F 'file=@your_file.csv'
```

---

© 2025 Cenk
