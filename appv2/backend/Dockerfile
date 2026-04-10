FROM python:3.11-slim

WORKDIR /app

# Copy requirements first (layer caching)
COPY appv2/backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project root (for brokers/ library)
COPY brokers /brokers

# Copy appv2 backend
COPY appv2/ .

# Create data/logs directories
RUN mkdir -p /app/data /app/logs

EXPOSE 8001

CMD ["uvicorn", "appv2.main:app", "--host", "0.0.0.0", "--port", "8001"]
