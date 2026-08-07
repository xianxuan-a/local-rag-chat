FROM node:24-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --fetch-retries=5 --fetch-retry-mintimeout=10000 --fetch-retry-maxtimeout=60000

COPY . .

ARG VITE_API_MODE=real
ARG VITE_API_BASE_URL=/
ARG VITE_API_TIMEOUT_MS=15000
ENV VITE_API_MODE=${VITE_API_MODE}
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
ENV VITE_API_TIMEOUT_MS=${VITE_API_TIMEOUT_MS}

RUN test "${VITE_API_MODE}" = "real" \
    && npm run build:real \
    && npm run audit:real \
    && rm /app/dist-real/.vite/manifest.json

FROM nginxinc/nginx-unprivileged:1.27-alpine AS runtime

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist-real/ /usr/share/nginx/html/

EXPOSE 8080
