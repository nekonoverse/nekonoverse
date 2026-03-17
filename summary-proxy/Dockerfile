FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2 libxslt1.1 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

EXPOSE 8003
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8003"]
