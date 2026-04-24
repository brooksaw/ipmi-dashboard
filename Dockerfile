FROM alpine:3.19

LABEL maintainer="UPZZ Lab"
LABEL description="Supermicro IPMI Health Dashboard — one-shot or watch-mode monitoring"
LABEL version="1.0.0"

# Install ipmitool and bash
RUN apk add --no-cache ipmitool bash

# Copy the dashboard script
COPY ipmi-dashboard.sh /usr/local/bin/ipmi-dashboard
RUN chmod +x /usr/local/bin/ipmi-dashboard

# Default entrypoint
ENTRYPOINT ["ipmi-dashboard"]
