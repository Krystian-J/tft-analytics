# Base image — official Python 3.12 on slim Debian (smaller than full image)
FROM python:3.12-slim

# Set working directory inside the container
WORKDIR /app

# Prevents Python from writing .pyc files
ENV PYTHONDONTWRITEBYTECODE=1

# Prevents Python from buffering stdout/stderr so logs appear immediately
ENV PYTHONUNBUFFERED=1

# Copy shared folder first (backend depends on it)
COPY shared/ ./shared/

# Copy backend requirements and install dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source code
COPY backend/ ./backend/

# Expose the port FastAPI will run on
EXPOSE 8000

# Default command — starts FastAPI via uvicorn
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
