FROM alpine:3.19

LABEL maintainer="UPZZ Lab"
LABEL description="Supermicro IPMI Health Dashboard — one-shot, watch-mode, or web UI"
LABEL version="1.1.0"

# Install ipmitool, bash, python3
RUN apk add --no-cache ipmitool bash python3

# Copy scripts
COPY ipmi-dashboard.sh /usr/local/bin/ipmi-dashboard
COPY web-dashboard.py /usr/local/bin/web-dashboard
RUN chmod +x /usr/local/bin/ipmi-dashboard /usr/local/bin/web-dashboard

# Default: web UI on port 8080
EXPOSE 8080
ENTRYPOINT ["web-dashboard"]
