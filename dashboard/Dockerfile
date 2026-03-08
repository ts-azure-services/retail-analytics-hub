# ── Stage 1: Build ────────────────────────────────────────────────
FROM node:22-alpine AS build
WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
ENV VITE_API_URL=""
RUN npm run build

# ── Stage 2: Runtime ──────────────────────────────────────────────
FROM node:22-alpine
WORKDIR /app

COPY --from=build /app/package*.json ./
RUN npm ci --omit=dev

COPY --from=build /app/dist ./dist

ENV NODE_ENV=production
EXPOSE 3001

CMD ["node", "dist/proxy.js"]
