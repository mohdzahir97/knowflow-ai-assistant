# Build the static bundle, then serve it with nginx.
#
# VITE_API_BASE_URL is baked in at BUILD time, not read at runtime: Vite
# substitutes import.meta.env into the bundle. So it must be passed as a build
# arg, and it must be an address the BROWSER can reach - never a Compose
# service name like http://backend:8001, which resolves only inside the
# Docker network. This is the one real difference from the Streamlit client,
# which calls the API server-side and so does use the service name.
FROM node:24-alpine AS builder

WORKDIR /app

# Copied first so a dependency layer is reused when only source changes.
COPY package.json package-lock.json ./
RUN npm ci

COPY tsconfig.json vite.config.ts index.html ./
COPY src ./src

ARG VITE_API_BASE_URL=http://localhost:8001
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM nginx:1.27-alpine

# History fallback: client-side routes such as /reset-password must serve
# index.html rather than 404, or an emailed link breaks on a page reload.
RUN printf '%s\n' \
    'server {' \
    '  listen 80;' \
    '  root /usr/share/nginx/html;' \
    '  index index.html;' \
    '  location / {' \
    '    try_files $uri $uri/ /index.html;' \
    '  }' \
    '}' > /etc/nginx/conf.d/default.conf

COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -q --spider http://localhost/ || exit 1
