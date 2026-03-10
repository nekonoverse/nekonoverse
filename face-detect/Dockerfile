FROM nvidia/cuda:12.6.0-runtime-ubuntu24.04

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN python3 -m venv /venv && \
    /venv/bin/pip install --no-cache-dir -r requirements.txt

COPY main.py .

# Pre-download anime face model at build time
RUN /venv/bin/python3 -c "from huggingface_hub import hf_hub_download; \
    hf_hub_download('deepghs/anime_face_detection', 'face_detect_v0_n/model.onnx'); \
    hf_hub_download('deepghs/anime_face_detection', 'face_detect_v0_n/threshold.json')"

ENV DETECTION_MODE=auto

EXPOSE 8001
CMD ["/venv/bin/uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
