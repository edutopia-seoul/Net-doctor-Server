FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json vite.config.js index.html ./
COPY src ./src
RUN npm ci && npm run build
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
