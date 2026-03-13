# ── Stage 1: Build ────────────────────────────────────────────────
FROM node:22-slim AS build
WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .

# Build frontend (Vite)
ENV VITE_API_URL=""
RUN npm run build

# Bundle server (TypeScript → JavaScript)
RUN npx esbuild server/index.ts --bundle --platform=node --format=esm \
      --packages=external --outfile=dist/server.js

# ── Stage 2: Runtime ──────────────────────────────────────────────
FROM node:22-slim
WORKDIR /app

COPY --from=build /app/package*.json ./
RUN npm ci --omit=dev

# Frontend static assets (built by Vite)
COPY --from=build /app/dist/assets ./dist/assets
COPY --from=build /app/dist/index.html ./dist/index.html

# Compiled server
COPY --from=build /app/dist/server.js ./dist/server.js

# In local dev, event_hubs.duckdb is volume-mounted.
# In cloud, customer reviews are queried via KQL (Fabric Real-Time Intelligence).

ENV NODE_ENV=production
EXPOSE 3001

CMD ["node", "dist/server.js"]
