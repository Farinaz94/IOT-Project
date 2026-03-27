FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Ensure common modules can be imported
ENV PYTHONPATH "${PYTHONPATH}:/app"
