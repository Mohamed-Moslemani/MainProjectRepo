FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

COPY services/gateway/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/gateway/app/ ./app/
COPY services/gateway/alembic.ini ./alembic.ini
COPY services/gateway/alembic/ ./alembic/
COPY shared/ ./shared/
# Sweeper entry points used by the gateway_cron sidecar (mukhtar SLA
# escalation + email outbox delivery). They import app.* so the cwd
# must be /app at runtime — both already are because of WORKDIR above.
COPY scripts/sweep_mukhtar_sla.py scripts/sweep_email_outbox.py ./scripts/

RUN mkdir -p /app/uploads

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
