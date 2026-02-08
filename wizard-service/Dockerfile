FROM python:3.11-slim

LABEL org.opencontainers.image.title="ASI Wizard Service"
LABEL org.opencontainers.image.description="Network topology builder for ASI platform"
LABEL org.opencontainers.image.version="2.0.0"

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app.py .
COPY netbox_mcp.py .
COPY smtp_mcp.py .
COPY mcp_definitions.json .
COPY static/ ./static/
COPY templates/ ./templates/

# Non-root user for security
RUN useradd -m -u 1000 wizard && chown -R wizard:wizard /app
USER wizard

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:8000/api/wizard/health')" || exit 1

# Run the application
CMD ["python", "app.py"]
