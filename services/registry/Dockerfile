FROM python:3.13-slim

WORKDIR /app

COPY services/registry/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/registry/app/ ./app/
COPY services/registry/alembic.ini ./alembic.ini
COPY services/registry/alembic/ ./alembic/
COPY services/registry/seed/ ./seed/
COPY shared/ ./shared/

EXPOSE 8003

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003"]
