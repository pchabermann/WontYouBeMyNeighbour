FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    iproute2 \
    iputils-ping \
    tcpdump \
    net-tools \
    procps \
    iptables \
    curl && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN cp webui/server-agent-only.py webui/server.py

# Make startup script executable
RUN chmod +x /app/start-agent.sh

# Create non-root user
RUN useradd -m -u 1000 asi && chown -R asi:asi /app

EXPOSE 8080 9090

HEALTHCHECK CMD curl -f http://localhost:8000/api/health || exit 1

# Use startup script as entrypoint
ENTRYPOINT ["/app/start-agent.sh"]
