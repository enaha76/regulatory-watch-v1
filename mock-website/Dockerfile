FROM node:20-slim
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY server.ts tsconfig.json ./
CMD ["npx", "tsx", "server.ts"]
