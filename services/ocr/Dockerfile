FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY services/ocr/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/ocr/app/ ./app/
COPY shared/ ./shared/

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
