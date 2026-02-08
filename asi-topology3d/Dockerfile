FROM python:3.11-slim

LABEL org.opencontainers.image.title="ASI Topology3D Service"
LABEL org.opencontainers.image.description="3D network topology visualization"
LABEL org.opencontainers.image.version="1.0.0"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY k8s_client.py .
COPY static/ ./static/

RUN useradd -m -u 1000 topo3d && chown -R topo3d:topo3d /app
USER topo3d

EXPOSE 8002

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8002/api/wizard/health')" || exit 1

CMD ["python", "app.py"]
