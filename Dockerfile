FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.13-slim
ENV UV_LINK_MODE=copy PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir uv==0.5.31
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY server/ server/
COPY data/book/ data/book/
COPY data/images/ data/images/
COPY --from=web /web/dist/ web/dist/
EXPOSE 8000
CMD ["sh", "-c", "exec .venv/bin/uvicorn server.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
