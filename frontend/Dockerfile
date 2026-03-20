FROM node:22-alpine AS base

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY packages/ui /packages/ui
COPY frontend/ .

# --- Development stage ---
FROM base AS dev
EXPOSE 3000
CMD ["npx", "vite", "dev", "--host", "0.0.0.0", "--port", "3000"]

# --- Production stage ---
FROM base AS production
ARG GIT_HASH=""
ARG GIT_BRANCH=""
ENV VITE_GIT_HASH=${GIT_HASH}
ENV VITE_GIT_BRANCH=${GIT_BRANCH}
RUN npx vite build
EXPOSE 3000
CMD ["npx", "vite", "preview", "--host", "0.0.0.0", "--port", "3000"]
