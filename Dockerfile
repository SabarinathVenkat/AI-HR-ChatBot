# HR Chat Agent. Build:  docker build -t hr-chat-agent .
# Run:    docker run --env-file .env -p 8000:8000 -v hr_data:/data hr-chat-agent
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first, so this layer is cached until requirements.txt changes.
COPY requirements.txt .
RUN pip install -r requirements.txt

# Run as an unprivileged user.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data /app/models_cache \
    && chown -R appuser:appuser /data /app

COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser data ./data

USER appuser

# Bake the embedding model into the image so the first start needs no download.
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='models_cache')"

# Everything that must survive a restart lives on the /data volume: the database, the uploaded resumes and
# templates, and the issue log.
ENV DB_PATH=/data/hr_chat.db \
    RESUME_STORE_DIR=/data/resume_files \
    RESUME_LOG_FILE=/data/logs/resume_builder.log \
    LOG_LEVEL=INFO

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8000"]
