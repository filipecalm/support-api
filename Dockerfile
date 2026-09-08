FROM python:3.14-slim
WORKDIR /app
COPY requirements.txt .
RUN python -m pip install --no-cache-dir --require-hashes -r requirements.txt \
    && groupadd --system support && useradd --system --gid support support
COPY app ./app
USER support
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-proxy-headers", "--limit-concurrency", "100", "--timeout-keep-alive", "5"]
