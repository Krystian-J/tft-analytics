# Base image — official Python 3.12 on slim Debian (smaller than full image)
FROM python:3.12-slim

# Set working directory inside the container
WORKDIR /app

# Prevents Python from writing .pyc files
ENV PYTHONDONTWRITEBYTECODE=1

# Prevents Python from buffering stdout/stderr so logs appear immediately
ENV PYTHONUNBUFFERED=1

# Install system dependencies needed by psycopg2
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy shared folder first (crawler depends on it)
COPY shared/ ./shared/

# Copy crawler requirements and install dependencies
COPY crawler/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy crawler source code
COPY crawler/ ./crawler/

# Default command — starts Celery worker
# Queues are explicitly listed so this worker only processes crawler tasks
CMD ["celery", "-A", "crawler.main", "worker", "--loglevel=info", "-Q", "league,match_list,match_detail,save"]
