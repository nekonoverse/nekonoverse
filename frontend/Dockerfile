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
RUN npx vite build
EXPOSE 3000
CMD ["npx", "vite", "preview", "--host", "0.0.0.0", "--port", "3000"]
