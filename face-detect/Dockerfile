FROM nvidia/cuda:12.6.0-runtime-ubuntu24.04

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv libgl1 libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN python3 -m venv /venv && \
    /venv/bin/pip install --no-cache-dir -r requirements.txt

COPY main.py lbpcascade_animeface.xml ./

EXPOSE 8001
CMD ["/venv/bin/uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
