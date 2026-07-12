FROM python:3.11-slim

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Prefer install without emergentintegrations if unavailable
RUN pip install --no-cache-dir -r requirements.txt || \
    pip install --no-cache-dir $(grep -v emergentintegrations requirements.txt | tr '\n' ' ')

RUN playwright install --with-deps chromium || true

COPY . .
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
