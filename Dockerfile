FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py gunicorn.conf.py ./
COPY access/ access/
COPY purchase/ purchase/
COPY payment/ payment/
COPY shared/ shared/

EXPOSE 8000

# 4 threads share app.db: never open a transaction on it; use a separate connection.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--threads", "4", "app:app"]
