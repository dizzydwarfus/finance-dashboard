# syntax=docker/dockerfile:1
FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci && npm cache clean --force
COPY index.html tsconfig.json vite.config.ts ./
COPY src ./src
RUN npm run build
FROM nginxinc/nginx-unprivileged:stable-alpine
COPY nginx-main.conf /etc/nginx/nginx.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
USER 101:101
HEALTHCHECK --interval=30s --timeout=3s CMD wget -q --spider http://127.0.0.1:8080/healthz || exit 1
CMD ["nginx", "-e", "stderr", "-g", "daemon off;"]
