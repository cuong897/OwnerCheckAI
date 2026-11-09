# --- Build stage ---
FROM node:20-alpine AS builder

WORKDIR /build

COPY frontend/package.json ./
RUN npm install --no-audit --no-fund

COPY frontend/. ./
RUN npm run build

# --- Runtime stage: serve static với nginx ---
FROM nginx:1.26-alpine AS runtime

COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /build/dist /usr/share/nginx/html

EXPOSE 80
