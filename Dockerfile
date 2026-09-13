FROM python:3.11-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package*.json ./
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm && npm install
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml requirements.txt ./
COPY backend ./backend
RUN pip install --no-cache-dir .
COPY config ./config
COPY --from=frontend /src/frontend/dist ./frontend/dist
RUN mkdir -p /app/data/images /app/data/faiss
EXPOSE 8000
CMD ["python", "-m", "backend.app.main"]

