"""
ASI Monitor Service

Standalone dashboard for monitoring deployed ASI network topologies.
Queries the Kubernetes API directly to discover topology namespaces and agent pods.
"""

from fastapi import FastAPI, APIRouter, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import logging
import os

from k8s_client import ASIKubernetesClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ASIMonitor")

app = FastAPI(
    title="ASI Monitor Service",
    description="Network topology monitoring dashboard",
    version="1.0.0",
)

api = APIRouter(prefix="/api/wizard", tags=["monitor"])

# Initialize K8s client
try:
    k8s = ASIKubernetesClient()
    logger.info("K8s client initialized")
except Exception as e:
    logger.warning(f"K8s client unavailable: {e}")
    k8s = None


@api.get("/health")
async def health():
    return {"status": "healthy", "service": "asi-monitor", "platform": "kubernetes"}


@api.get("/networks")
async def list_networks():
    """List all deployed topology networks."""
    if not k8s:
        raise HTTPException(status_code=503, detail="K8s client unavailable")
    return k8s.list_topology_namespaces()


@api.get("/networks/{network_id}/status")
async def network_status(network_id: str):
    """Get detailed status for a topology network."""
    if not k8s:
        raise HTTPException(status_code=503, detail="K8s client unavailable")
    return k8s.get_network_status(network_id)


@api.get("/networks/{network_id}/health")
async def network_health(network_id: str):
    """Run health check on a topology network."""
    if not k8s:
        raise HTTPException(status_code=503, detail="K8s client unavailable")
    return k8s.get_network_health(network_id)


@api.get("/networks/{network_id}/agents/{agent_id}/logs")
async def agent_logs(
    network_id: str, agent_id: str, tail: int = Query(default=200)
):
    """Get pod logs for a specific agent."""
    if not k8s:
        raise HTTPException(status_code=503, detail="K8s client unavailable")
    return k8s.get_agent_logs(network_id, agent_id, tail)


@api.post("/networks/{network_id}/stop")
async def stop_network(network_id: str, save_state: bool = Query(default=False)):
    """Stop (delete) a topology network."""
    if not k8s:
        raise HTTPException(status_code=503, detail="K8s client unavailable")
    return k8s.stop_network(network_id)


# Compat endpoint for saved networks (not implemented in K8s, returns empty)
@api.get("/libraries/networks")
async def list_saved_networks():
    return []


app.include_router(api)

# Serve static files
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
@app.get("/monitor")
async def index():
    """Serve monitor dashboard."""
    return FileResponse("static/monitor.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)
