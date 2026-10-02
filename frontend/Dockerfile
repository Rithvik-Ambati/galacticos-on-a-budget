# Production image for the frontend: build the static bundle, serve it with nginx.
# Authored, never built/run in this project (user instruction: "don't deploy yet").

FROM node:20-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
