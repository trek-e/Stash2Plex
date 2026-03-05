FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Copy shared_lib first (changes less frequently → better layer caching)
COPY shared_lib/ /app/shared_lib/

# Install provider dependencies before copying code (deps change less often than code)
COPY provider/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Install curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Create non-root user matching typical Stash container UID
RUN groupadd -g 1000 stash && useradd -u 1000 -g stash -s /bin/sh stash

# Copy provider application code
COPY provider/ /app/provider/

# Ensure stash user owns the app and config mount point
RUN chown -R stash:stash /app && mkdir -p /config && chown stash:stash /config

USER stash

EXPOSE 9090

# Exec form CMD — required for SIGTERM to reach uvicorn (graceful shutdown + lifespan teardown)
CMD ["uvicorn", "provider.main:app", "--host", "0.0.0.0", "--port", "9090"]
