# 7D-BIM Lifecycle Tool - online copy (e.g. Render). Locally use start.bat / start.sh instead.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BIM7D_DATA=/app/projects \
    PORT=8000

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY web ./web

# Build the Kifisia demo project once, at image build time, so the first visit is fast.
RUN python -c "from app import store; store.ROOT.mkdir(parents=True, exist_ok=True); store.ensure_demo()"

EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
