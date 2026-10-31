# Production Dockerfile for TalibAI (Student Study Companion)
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy dependencies first for Docker layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV PORT=8000
ENV HOST=0.0.0.0
ENV TALIB_DB_PATH=/var/lib/talib-ai/talib_ai.db
ENV TALIB_GENERATED_DIR=/var/lib/talib-ai/generated_files

RUN mkdir -p /var/lib/talib-ai/generated_files
VOLUME ["/var/lib/talib-ai"]

EXPOSE 8000

# Start production server
CMD ["python", "run.py"]
