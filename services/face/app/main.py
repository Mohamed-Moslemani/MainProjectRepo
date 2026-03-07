import logging
from fastapi import FastAPI
from .routers import face

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="DocFlow - Face Verification Service", version="0.1.0")
app.include_router(face.router)


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "face"}
