# --- build ---------------------------------------------------------------
FROM node:22-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Vite bakes these in at build time. Railway injects service variables into
# the build, so set VITE_API_BASE_URL / VITE_WS_BASE_URL on the frontend
# service; --build-arg also works for local `docker build`.
ARG VITE_API_BASE_URL
ARG VITE_WS_BASE_URL
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV VITE_WS_BASE_URL=$VITE_WS_BASE_URL
RUN npm run build

# --- serve --------------------------------------------------------------
FROM node:22-alpine

ENV PORT=3000
RUN npm i -g serve@14
WORKDIR /app
COPY --from=build /app/dist ./dist

EXPOSE 3000
# -s: single-page-app fallback to index.html for client-side routing.
CMD ["sh", "-c", "serve -s dist -l ${PORT:-3000}"]
