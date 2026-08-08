FROM node:24-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --fetch-retries=5 --fetch-retry-mintimeout=10000 --fetch-retry-maxtimeout=60000

COPY index.html tsconfig.json tsconfig.app.json tsconfig.node.json vite.config.ts ./
COPY public ./public
COPY scripts/build-real.mjs scripts/audit-real-build.mjs ./scripts/
COPY src ./src

ARG VITE_API_MODE=real
ARG VITE_API_BASE_URL=/
ARG VITE_API_TIMEOUT_MS=15000
ENV VITE_API_MODE=${VITE_API_MODE}
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
ENV VITE_API_TIMEOUT_MS=${VITE_API_TIMEOUT_MS}

RUN test "${VITE_API_MODE}" = "real" \
    && npm run build \
    && npm run audit:real \
    && rm /app/dist-real/.vite/manifest.json

FROM nginxinc/nginx-unprivileged:1.27-alpine AS runtime

ARG VCS_REF=unknown
LABEL org.opencontainers.image.source="https://github.com/xianxuan-a/local-rag-chat" \
      org.opencontainers.image.revision="${VCS_REF}"

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist-real/ /usr/share/nginx/html/

EXPOSE 8080
