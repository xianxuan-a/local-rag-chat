FROM python:3.11.15-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN pip install --no-cache-dir --index-url "$PIP_INDEX_URL" -r requirements.txt

COPY . ./

RUN mkdir -p \
        /app/data/logs \
        /app/data/uploads \
        /app/data/chroma \
        /app/data/metadata \
        /app/data/chat_history \
        /app/data/backups \
        /app/data/evaluations \
        /app/logs \
    && addgroup --system app \
    && adduser --system --ingroup app app \
    && chown -R app:app /app

USER app

EXPOSE 8000 8501

CMD ["python", "run.py"]
