FROM node:22-slim AS build

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .

# The API base is baked in at build time (it reaches the browser, so it cannot
# be an env var read at runtime). Cloud Build passes the deployed API URL.
ARG NEXT_PUBLIC_API_BASE
ENV NEXT_PUBLIC_API_BASE=${NEXT_PUBLIC_API_BASE}
RUN npm run build


FROM node:22-slim

WORKDIR /app
ENV NODE_ENV=production \
    PORT=8080

# `output: "standalone"` traces only the files the server actually imports,
# so node_modules does not come along whole.
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static

CMD ["node", "server.js"]
