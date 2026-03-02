FROM node:22-alpine

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install

COPY . .

EXPOSE 3000
CMD ["npx", "vite", "dev", "--host", "0.0.0.0", "--port", "3000"]
