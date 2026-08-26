FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    ffmpeg \
    espeak-ng \
    && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml /app/backend/pyproject.toml
COPY backend/app /app/backend/app
COPY backend/alembic /app/backend/alembic
COPY backend/alembic.ini /app/backend/alembic.ini
COPY config /app/config

WORKDIR /app/backend
RUN pip install --no-cache-dir -e ".[dev,speech]"
# Pre-download/cache the model at build time so first request isn't slow.
# Must match WHISPER_MODEL_SIZE below / in .env — "small" is the practical
# floor for usable Hindi/Kannada recognition ("tiny" is English-only in
# practice despite being nominally multilingual).
ARG WHISPER_MODEL_SIZE=small
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('${WHISPER_MODEL_SIZE}', device='cpu', compute_type='int8')"

# Piper neural TTS (English + Hindi). Kannada has no official Piper voice —
# LocalTTSProvider falls back to eSpeak NG for kn and any missing model.
ARG PIPER_RELEASE=2023.11.14-2
ARG TTS_VOICES_DIR=/app/models/tts
RUN python - <<'PY'
import tarfile, urllib.request
from pathlib import Path

piper_url = "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_x86_64.tar.gz"
tarball = Path("/tmp/piper.tar.gz")
urllib.request.urlretrieve(piper_url, tarball)
with tarfile.open(tarball) as tar:
    tar.extractall("/opt")
tarball.unlink()
piper_bin = Path("/opt/piper/piper")
piper_bin.chmod(0o755)

voices = Path("/app/models/tts")
voices.mkdir(parents=True, exist_ok=True)
base = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0"
files = {
    "en_US-lessac-medium.onnx": f"{base}/en/en_US/lessac/medium/en_US-lessac-medium.onnx",
    "en_US-lessac-medium.onnx.json": f"{base}/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json",
    "hi_IN-priyamvada-medium.onnx": f"{base}/hi/hi_IN/priyamvada/medium/hi_IN-priyamvada-medium.onnx",
    "hi_IN-priyamvada-medium.onnx.json": f"{base}/hi/hi_IN/priyamvada/medium/hi_IN-priyamvada-medium.onnx.json",
}
for name, url in files.items():
    dest = voices / name
    print("downloading", name)
    urllib.request.urlretrieve(url, dest)
print("piper voices ready")
PY

ENV PYTHONUNBUFFERED=1 \
    BOUNDARY_POLICY_PATH=/app/config/boundary/policies.yaml \
    DOCUMENT_STORAGE_PATH=/app/data/documents \
    WHISPER_MODEL_SIZE=${WHISPER_MODEL_SIZE} \
    PIPER_BIN=/opt/piper/piper \
    TTS_VOICES_DIR=/app/models/tts \
    PIPER_EN_VOICE=en_US-lessac-medium.onnx \
    PIPER_HI_VOICE=hi_IN-priyamvada-medium.onnx

RUN mkdir -p /app/data/documents

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
