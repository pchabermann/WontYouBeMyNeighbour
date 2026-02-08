"""
ASI Topology3D Service

Standalone 3D network topology visualization.
Queries the Kubernetes API directly to discover topology namespaces,
agent pods, and network links. Supports WebSocket for real-time updates.
"""

from fastapi import FastAPI, APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import asyncio
import json
import logging
import os
from typing import List

from k8s_client import ASIKubernetesClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ASITopology3D")

app = FastAPI(
    title="ASI Topology3D Service",
    description="3D network topology visualization",
    version="1.0.0",
)

api = APIRouter(prefix="/api/wizard", tags=["topology3d"])

# Initialize K8s client
try:
    k8s = ASIKubernetesClient()
    logger.info("K8s client initialized")
except Exception as e:
    logger.warning(f"K8s client unavailable: {e}")
    k8s = None

# Connected WebSocket clients
connected_clients: List[WebSocket] = []


@api.get("/health")
async def health():
    return {"status": "healthy", "service": "asi-topology3d", "platform": "kubernetes"}


@api.get("/networks")
async def list_networks():
    """List all deployed topology networks."""
    if not k8s:
        raise HTTPException(status_code=503, detail="K8s client unavailable")
    return k8s.list_topology_namespaces()


@api.get("/networks/discover")
async def discover_networks():
    """Auto-discover topology networks (same as list for K8s)."""
    if not k8s:
        raise HTTPException(status_code=503, detail="K8s client unavailable")
    return k8s.list_topology_namespaces()


@api.get("/networks/{network_id}/status")
async def network_status(network_id: str):
    """Get detailed status for a topology network."""
    if not k8s:
        raise HTTPException(status_code=503, detail="K8s client unavailable")
    return k8s.get_network_status(network_id)


@api.get("/networks/discover/{network_id}/status")
async def discover_network_status(network_id: str):
    """Get status for auto-discovered network (same as regular status)."""
    if not k8s:
        raise HTTPException(status_code=503, detail="K8s client unavailable")
    return k8s.get_network_status(network_id)


@api.get("/networks/{network_id}/graph")
async def topology_graph(network_id: str):
    """Return nodes + links for 3D rendering."""
    if not k8s:
        raise HTTPException(status_code=503, detail="K8s client unavailable")
    return k8s.get_topology_graph(network_id)


app.include_router(api)


# WebSocket for real-time topology updates
@app.websocket("/ws/monitor")
async def ws_monitor(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    logger.info(f"WebSocket client connected ({len(connected_clients)} total)")
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "get_metrics":
                metrics = await _build_metrics()
                await websocket.send_json({"type": "metrics", "data": metrics})

            elif msg_type == "get_topology":
                topo = await _build_full_topology()
                await websocket.send_json({"type": "topology", "data": topo})

            elif msg_type == "get_agent_details":
                agent_id = data.get("agent_id", "")
                # Return basic info from pod status
                networks = k8s.list_topology_namespaces() if k8s else []
                for net in networks:
                    status = k8s.get_network_status(net["network_id"])
                    if agent_id in status.get("agents", {}):
                        await websocket.send_json({
                            "type": "agent_details",
                            "data": status["agents"][agent_id],
                        })
                        break

            elif msg_type == "subscribe":
                # Acknowledge subscription
                await websocket.send_json({
                    "type": "subscribed",
                    "topics": data.get("topics", []),
                })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        if websocket in connected_clients:
            connected_clients.remove(websocket)
        logger.info(f"WebSocket client disconnected ({len(connected_clients)} total)")


async def _build_metrics():
    """Aggregate metrics from all topology namespaces."""
    if not k8s:
        return {}
    networks = k8s.list_topology_namespaces()
    total_agents = sum(n["agent_count"] for n in networks)
    running = sum(1 for n in networks if n["status"] == "running")
    return {
        "runningNetworks": running,
        "totalAgents": total_agents,
        "totalNeighbors": 0,
        "totalRoutes": 0,
    }


async def _build_full_topology():
    """Build combined topology from all namespaces."""
    if not k8s:
        return {"nodes": [], "links": []}
    networks = k8s.list_topology_namespaces()
    all_nodes, all_links = [], []
    for net in networks:
        graph = k8s.get_topology_graph(net["network_id"])
        all_nodes.extend(graph.get("nodes", []))
        all_links.extend(graph.get("links", []))
    return {"nodes": all_nodes, "links": all_links}


async def _periodic_push():
    """Push metrics and topology to connected WebSocket clients every 10s."""
    while True:
        await asyncio.sleep(10)
        if not connected_clients or not k8s:
            continue
        try:
            metrics = await _build_metrics()
            topo = await _build_full_topology()
            for ws in list(connected_clients):
                try:
                    await ws.send_json({"type": "metrics", "data": metrics})
                    await ws.send_json({"type": "topology_update", "data": topo})
                except Exception:
                    if ws in connected_clients:
                        connected_clients.remove(ws)
        except Exception as e:
            logger.error(f"Periodic push error: {e}")


@app.on_event("startup")
async def start_background_tasks():
    asyncio.create_task(_periodic_push())


# Serve static files
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
@app.get("/topology3d")
async def index():
    """Serve 3D topology visualization."""
    return FileResponse("static/topology3d.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8002)
