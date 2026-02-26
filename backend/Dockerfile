FROM python:3.12-slim

WORKDIR /app

COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend /app/backend
COPY shared /app/shared

# Ensure package structure is recognised
RUN touch /app/backend/__init__.py \
    && touch /app/backend/db/__init__.py \
    && touch /app/backend/routers/__init__.py \
    && touch /app/backend/services/__init__.py

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
