FROM node:20-slim
WORKDIR /tests
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
CMD ["npx", "vitest", "run", "--reporter=verbose"]
