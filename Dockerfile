FROM python:3.11.15-slim-bookworm AS dependencies

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

COPY requirements.txt requirements.lock ./
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN python -m pip install \
        --no-cache-dir \
        --index-url "$PIP_INDEX_URL" \
        --prefix=/install \
        -r requirements.lock \
    && PYTHONPATH=/install/lib/python3.11/site-packages \
        python -m pip check

FROM python:3.11.15-slim-bookworm AS runtime

ARG VCS_REF=unknown
LABEL org.opencontainers.image.source="https://github.com/xianxuan-a/local-rag-chat" \
      org.opencontainers.image.revision="${VCS_REF}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY --from=dependencies /install/ /usr/local/

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

COPY --chown=app:app alembic.ini run.py ./
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app app ./app
COPY --chown=app:app scripts/*.py ./scripts/
COPY --chown=app:app ui ./ui

USER app

EXPOSE 8000 8501

CMD ["python", "run.py"]
