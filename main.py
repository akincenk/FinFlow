# FinFlow - Financial Data Analyzer API

"""
A FastAPI-based financial data analysis and visualization tool.
Users can upload CSV/Excel files to receive summary statistics, basic analysis, and graphical outputs via an API.
"""

from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse
import pandas as pd
import io
import matplotlib.pyplot as plt
import base64

app = FastAPI(title="FinFlow API", description="Upload financial data, get insights and plots.", version="1.0")

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        df = pd.read_csv(io.BytesIO(contents))

        summary = {
            "columns": df.columns.tolist(),
            "shape": df.shape,
            "describe": df.describe().to_dict(),
        }

        # Example histogram plot
        plt.figure(figsize=(8,4))
        df.select_dtypes(include='number').hist(bins=20)
        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format="png")
        buf.seek(0)
        img_base64 = base64.b64encode(buf.read()).decode("utf-8")
        buf.close()

        return JSONResponse(content={
            "summary": summary,
            "plot_base64": img_base64
        })

    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})

@app.get("/")
def root():
    return {"message": "Welcome to FinFlow API. Use /upload to analyze your financial data."}
