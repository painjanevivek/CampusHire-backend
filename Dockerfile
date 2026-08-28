FROM docker:29-cli@sha256:000bb62ff495f986c9f5578eb67cc2cb98b91138eda81d7762d5371eb8a497fe AS docker-cli

FROM python:3.13-slim@sha256:ffb752e139c0a19692a43af8d8523b274222dd68eebad5d583b45c2201c6e30a AS application

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
RUN addgroup --system campushire && adduser --system --ingroup campushire campushire
COPY pyproject.toml README.md ./
COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations
RUN pip install --no-cache-dir .

USER campushire
EXPOSE 8000

FROM application AS worker
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
CMD ["python", "-m", "app.worker"]

FROM application AS api
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import os, urllib.request; request=urllib.request.Request('http://127.0.0.1:8000/api/v1/health/live', headers={'Host': os.getenv('HEALTHCHECK_HOST', 'localhost')}); urllib.request.urlopen(request, timeout=3)"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*", "--no-access-log"]
