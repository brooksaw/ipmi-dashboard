FROM python:3.12-slim

# OCI standard labels — surface in Unraid's Version column + Docker Hub / GHCR UI
ARG VERSION=dev
ARG REVISION=unknown
LABEL org.opencontainers.image.title="IPMI Dashboard" \
      org.opencontainers.image.description="Multi-server Supermicro BMC dashboard with Settings UI (browser-based: configure servers, thresholds, webhooks without restart), fan control, alerts, power control, SEL log, Unraid disk health, webhook notifications." \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.source="https://github.com/brooksaw/ipmi-dashboard" \
      org.opencontainers.image.url="https://github.com/brooksaw/ipmi-dashboard" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.vendor="brooksaw"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_VERSION=${VERSION} \
    APP_REVISION=${REVISION}

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ipmitool openssh-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY templates ./templates
COPY static ./static
COPY run.py ./
COPY docker-entrypoint.sh ./
RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 8080

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["python3", "run.py"]
