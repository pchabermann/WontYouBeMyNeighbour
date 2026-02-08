"""
ASI Wizard Service - Kubernetes Edition

Standalone service for building and deploying ASI network topologies
to Kubernetes using AgentTopology custom resources.

This replaces the Docker-based orchestration with cloud-native K8s deployment.
"""

from fastapi import FastAPI, APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, Response
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime
import logging
import asyncio
import os
import re
import yaml
import json
import httpx
import websockets

# Kubernetes client
from kubernetes import client, config
from kubernetes.client.rest import ApiException

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("WizardService")

# Initialize FastAPI app
app = FastAPI(
    title="ASI Wizard Service",
    description="Network topology builder for ASI platform",
    version="2.0.0-kubernetes"
)

# API router
api_router = APIRouter(prefix="/api/wizard", tags=["wizard"])

# Initialize Kubernetes client (optional - wizard can run standalone for config)
k8s_core = None
k8s_custom = None
try:
    # Try in-cluster config first (when running in K8s pod)
    config.load_incluster_config()
    logger.info("Loaded in-cluster Kubernetes configuration")
    k8s_core = client.CoreV1Api()
    k8s_custom = client.CustomObjectsApi()
except:
    try:
        # Fall back to kubeconfig (when running locally)
        config.load_kube_config()
        logger.info("Loaded kubeconfig configuration")
        k8s_core = client.CoreV1Api()
        k8s_custom = client.CustomObjectsApi()
    except Exception as e:
        logger.warning(f"No Kubernetes cluster available: {e}")
        logger.warning("Wizard running in standalone mode - configure topologies but cannot deploy")

# Kubernetes API constants
ASI_GROUP = "asi.asi.anthropic.com"
ASI_VERSION = "v1alpha1"
ASI_PLURAL = "agenttopologies"
ASI_NAMESPACE = "default"  # Where to create AgentTopology CRs

# Load MCP definitions from external JSON file
MCP_DEFINITIONS = []
try:
    mcp_file_path = os.path.join(os.path.dirname(__file__), "mcp_definitions.json")
    with open(mcp_file_path, "r") as f:
        MCP_DEFINITIONS = json.load(f)
    logger.info(f"Loaded {len(MCP_DEFINITIONS)} MCP definitions from {mcp_file_path}")
except FileNotFoundError:
    logger.warning(f"MCP definitions file not found at {mcp_file_path}, using empty list")
except json.JSONDecodeError as e:
    logger.error(f"Failed to parse MCP definitions JSON: {e}")
except Exception as e:
    logger.error(f"Failed to load MCP definitions: {e}")


# ============================================================================
# Pydantic Models (same as original wizard)
# ============================================================================

class MCPSelection(BaseModel):
    """MCP server selection"""
    selected: List[str] = Field(default_factory=list)
    custom: List[Dict[str, Any]] = Field(default_factory=list)


class AgentConfig(BaseModel):
    """Agent configuration"""
    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    router_id: str
    protocol: str = Field(..., pattern=r"^(ospf|ospfv3|ibgp|ebgp|isis)$")
    protocols: List[Dict[str, Any]] = Field(default_factory=list)
    interfaces: List[Dict[str, Any]] = Field(default_factory=list)
    protocol_config: Dict[str, Any] = Field(default_factory=dict)
    from_template: Optional[str] = None


class LinkConfig(BaseModel):
    """Link configuration"""
    id: str
    agent1_id: str
    interface1: str
    agent2_id: str
    interface2: str
    link_type: str = "ethernet"
    cost: int = 10


class TopologyConfig(BaseModel):
    """Topology configuration"""
    links: List[LinkConfig] = Field(default_factory=list)
    auto_generate: bool = False


class LLMConfig(BaseModel):
    """LLM provider configuration"""
    provider: str = Field("claude", pattern=r"^(claude|openai|gemini)$")
    model: str = "claude-sonnet-4"
    api_key: Optional[str] = None


class WizardState(BaseModel):
    """Complete wizard state"""
    step: int = 1
    topology_name: str = Field(default="my-topology")
    mcp_selection: Optional[MCPSelection] = None
    agents: List[AgentConfig] = Field(default_factory=list)
    topology: Optional[TopologyConfig] = None
    llm_config: Optional[LLMConfig] = None
    api_keys: Dict[str, str] = Field(default_factory=dict)


class LaunchRequest(BaseModel):
    """Network launch request"""
    topology_name: str
    api_keys: Dict[str, str] = Field(default_factory=dict)


# In-memory wizard sessions
_wizard_sessions: Dict[str, WizardState] = {}
_wizard_sessions_lock = asyncio.Lock()


# ============================================================================
# Kubernetes AgentTopology Builder
# ============================================================================

def build_agenttopology_cr(session: WizardState) -> Dict[str, Any]:
    """
    Translate wizard session state to AgentTopology custom resource.

    This is the key function that converts the wizard UI state into the
    Kubernetes-native declarative format.
    """

    # Build agents list
    agents = []
    for agent_cfg in session.agents:
        agent_spec = {
            "name": agent_cfg.id,
            "interfaces": [],
            "protocols": []
        }

        # Add interfaces (handle both short and long field names from frontend)
        # CRD only supports types: "ethernet", "loopback"
        # GRE/VXLAN tunnels are mapped to "ethernet" with tunnel config in annotations
        tunnel_configs = {}
        for iface in agent_cfg.interfaces:
            iface_name = iface.get("n") or iface.get("name") or iface.get("id", "eth0")
            iface_type_raw = iface.get("t") or iface.get("type", "ethernet")

            # Map to CRD-supported types
            if iface_type_raw in ("eth", "ethernet"):
                iface_type = "ethernet"
            elif iface_type_raw in ("lo", "loopback"):
                iface_type = "loopback"
            else:
                # GRE, VXLAN, etc. -> store as ethernet, save tunnel config in annotations
                iface_type = "ethernet"

            # Clean interface name to match CRD pattern: ^[a-z0-9]+$
            clean_name = re.sub(r'[^a-z0-9]', '', iface_name.lower())
            if not clean_name:
                clean_name = "eth0"

            iface_spec = {
                "name": clean_name,
                "type": iface_type,
            }

            # Add addresses if present (short: "a", long: "addresses")
            addresses = iface.get("a") or iface.get("addresses", [])
            if addresses:
                iface_spec["addresses"] = addresses

            # Add MTU if present and valid
            mtu = iface.get("mtu")
            if mtu and isinstance(mtu, int) and 576 <= mtu <= 9216:
                iface_spec["mtu"] = mtu

            # Store tunnel config in annotations (not in interface spec)
            tun = iface.get("tun")
            if tun:
                tunnel_configs[clean_name] = tun

            agent_spec["interfaces"].append(iface_spec)

        # Store tunnel configs as annotation on the agent
        if tunnel_configs:
            agent_spec["_tunnel_configs"] = tunnel_configs

        # Ensure at least one interface (K8s CRD requires minimum 1)
        if not agent_spec["interfaces"]:
            agent_spec["interfaces"] = [
                {"name": "eth0", "type": "ethernet"},
                {"name": "lo0", "type": "loopback", "addresses": [f"{agent_cfg.router_id}/32"]}
            ]

        # Add protocols (handle both short and long field names)
        for proto in agent_cfg.protocols:
            proto_type = proto.get("p") or proto.get("type", agent_cfg.protocol)
            proto_spec = {
                "type": proto_type,
                "config": {}
            }

            # Add router ID
            router_id = proto.get("r") or proto.get("router_id") or agent_cfg.router_id
            if router_id:
                proto_spec["config"]["routerId"] = router_id

            # Add OSPF area
            area = proto.get("a") or proto.get("area")
            if area:
                proto_spec["config"]["area"] = str(area)

            # Add networks
            nets = proto.get("nets") or proto.get("networks")
            if nets:
                proto_spec["config"]["networks"] = ",".join(nets) if isinstance(nets, list) else str(nets)

            # Add OSPF interfaces
            ifaces = proto.get("interfaces")
            if ifaces:
                proto_spec["config"]["interfaces"] = ",".join(ifaces) if isinstance(ifaces, list) else str(ifaces)

            # Add protocol options
            opts = proto.get("opts")
            if opts and isinstance(opts, dict):
                for key, value in opts.items():
                    proto_spec["config"][key] = str(value)

            # Add loopback IP
            loopback_ip = proto.get("loopback_ip")
            if loopback_ip:
                proto_spec["config"]["loopbackIp"] = loopback_ip

            # Extract any explicit config dict
            if proto.get("config") and isinstance(proto["config"], dict):
                for key, value in proto["config"].items():
                    proto_spec["config"][key] = str(value)

            agent_spec["protocols"].append(proto_spec)

        # Add LLM configuration
        if session.llm_config:
            agent_spec["llm"] = {
                "model": session.llm_config.model,
                "profile": f"Network agent: {agent_cfg.name}",
            }
            if session.llm_config.model == "claude-sonnet-4":
                agent_spec["llm"]["temperature"] = "0.7"

        # Add MCP servers
        if session.mcp_selection:
            agent_spec["mcpServers"] = session.mcp_selection.selected

        agents.append(agent_spec)

    # Build links list
    links = []
    if session.topology:
        for idx, link_cfg in enumerate(session.topology.links):
            link_spec = {
                "name": link_cfg.id or f"link-{idx}",
                "endpoints": [
                    {
                        "agent": link_cfg.agent1_id,
                        "interface": link_cfg.interface1
                    },
                    {
                        "agent": link_cfg.agent2_id,
                        "interface": link_cfg.interface2
                    }
                ],
                "subnet": f"fd00:0:{idx+1}::/64",  # Auto-generate IPv6 subnets
                "mtu": 1500
            }
            links.append(link_spec)

    # Collect tunnel configs from agents and store in annotations
    all_tunnel_configs = {}
    for agent_spec in agents:
        tunnel_configs = agent_spec.pop("_tunnel_configs", None)
        if tunnel_configs:
            for iface_name, tun_cfg in tunnel_configs.items():
                key = f"{agent_spec['name']}.{iface_name}"
                all_tunnel_configs[key] = tun_cfg

    # Build annotations
    annotations = {}
    if all_tunnel_configs:
        annotations["asi.anthropic.com/tunnel-configs"] = json.dumps(all_tunnel_configs)
    if session.api_keys:
        # Store API key provider (not the key itself for security)
        annotations["asi.anthropic.com/llm-providers"] = ",".join(session.api_keys.keys())

    # Build complete AgentTopology CR
    topology_cr = {
        "apiVersion": f"{ASI_GROUP}/{ASI_VERSION}",
        "kind": "AgentTopology",
        "metadata": {
            "name": session.topology_name,
            "namespace": ASI_NAMESPACE,
            "labels": {
                "asi.anthropic.com/created-by": "wizard",
                "asi.anthropic.com/created-at": datetime.utcnow().strftime("%Y%m%dT%H%M%S")
            },
            "annotations": annotations
        },
        "spec": {
            "agents": agents,
            "links": links
        }
    }

    return topology_cr


def build_agent_links(session: WizardState) -> List[Dict[str, Any]]:
    """
    Build link definitions from the topology config.
    If no explicit links defined, auto-generate links between agents
    based on matching interface addresses (same subnet).
    """
    links = []

    # Use explicit links from topology step if available
    if session.topology and session.topology.links:
        for idx, link_cfg in enumerate(session.topology.links):
            links.append({
                "name": f"link-{idx}",
                "agent1": link_cfg.agent1_id,
                "iface1": link_cfg.interface1,
                "agent2": link_cfg.agent2_id,
                "iface2": link_cfg.interface2,
            })
        return links

    # Auto-generate links: find ethernet interfaces with matching /30 or /31 subnets
    # This is a heuristic - agents on the same subnet are assumed to be linked
    agent_ifaces = []
    for agent_cfg in session.agents:
        for iface in agent_cfg.interfaces:
            iface_type = iface.get("t") or iface.get("type", "ethernet")
            if iface_type in ("loopback", "lo"):
                continue
            iface_name = iface.get("n") or iface.get("name", "eth0")
            addresses = iface.get("a") or iface.get("addresses", [])
            for addr in addresses:
                agent_ifaces.append({
                    "agent": agent_cfg.id,
                    "iface": iface_name,
                    "addr": addr,
                })

    # Match interfaces by subnet (simple /30 or /31 matching)
    matched = set()
    for i, a in enumerate(agent_ifaces):
        if i in matched:
            continue
        for j, b in enumerate(agent_ifaces):
            if j <= i or j in matched:
                continue
            if a["agent"] == b["agent"]:
                continue
            # Check if addresses are on the same /30 subnet
            try:
                ip_a = a["addr"].split("/")[0]
                ip_b = b["addr"].split("/")[0]
                parts_a = [int(x) for x in ip_a.split(".")]
                parts_b = [int(x) for x in ip_b.split(".")]
                # Same /30: first 30 bits match
                if parts_a[:3] == parts_b[:3] and abs(parts_a[3] - parts_b[3]) <= 2:
                    links.append({
                        "name": f"link-{len(links)}",
                        "agent1": a["agent"],
                        "iface1": a["iface"],
                        "agent2": b["agent"],
                        "iface2": b["iface"],
                    })
                    matched.add(i)
                    matched.add(j)
            except (ValueError, IndexError):
                continue

    return links


async def create_network_attachments(topology_ns: str, links: List[Dict[str, Any]], topology_name: str):
    """
    Create Multus NetworkAttachmentDefinitions (bridge-based) for each link.
    Each link gets its own Linux bridge on the kind node, providing a real
    L2 segment between the two agent pods.
    """
    for idx, link in enumerate(links):
        nad_name = link["name"]
        bridge_name = f"asi-br-{idx}"
        subnet = f"169.254.{idx}.0/24"

        nad_config = json.dumps({
            "cniVersion": "0.3.1",
            "type": "bridge",
            "bridge": bridge_name,
            "isGateway": False,
            "ipMasq": False,
            "ipam": {
                "type": "host-local",
                "subnet": subnet
            }
        })

        nad_body = {
            "apiVersion": "k8s.cni.cncf.io/v1",
            "kind": "NetworkAttachmentDefinition",
            "metadata": {
                "name": nad_name,
                "namespace": topology_ns,
                "labels": {
                    "asi.anthropic.com/topology": topology_name,
                    "asi.anthropic.com/link": nad_name,
                },
            },
            "spec": {
                "config": nad_config,
            },
        }

        try:
            k8s_custom.create_namespaced_custom_object(
                group="k8s.cni.cncf.io",
                version="v1",
                namespace=topology_ns,
                plural="network-attachment-definitions",
                body=nad_body,
            )
            logger.info(f"Created NAD: {nad_name} (bridge={bridge_name}) in {topology_ns}")
        except ApiException as e:
            if e.status == 409:
                logger.info(f"NAD {nad_name} already exists in {topology_ns}")
            else:
                raise


def build_multus_annotations(links: List[Dict[str, Any]], agent_name: str, topology_ns: str) -> Dict[str, str]:
    """
    Build Multus network annotations for an agent pod.
    Each link where this agent participates adds a network attachment,
    which Multus will create as net1, net2, net3... interfaces.
    """
    networks = []
    for link in links:
        if link["agent1"] == agent_name or link["agent2"] == agent_name:
            nad_ref = f"{topology_ns}/{link['name']}"
            networks.append(nad_ref)

    annotations = {}
    if networks:
        annotations["k8s.v1.cni.cncf.io/networks"] = ", ".join(networks)
    return annotations


def _build_api_key_env(session: WizardState) -> List:
    """Build env vars for LLM API keys from user-entered keys in the wizard session."""
    # Map wizard key names to env var names
    key_map = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "google": "GOOGLE_API_KEY",
    }
    env_vars = []
    # First: use keys from the wizard session (user-entered during step 5)
    for wizard_key, env_name in key_map.items():
        value = session.api_keys.get(wizard_key)
        if value:
            env_vars.append(client.V1EnvVar(name=env_name, value=value))
            logger.info(f"Passing {env_name} to agent pods (from wizard session)")
    # Fallback: use keys from the wizard pod's own environment
    if not env_vars:
        for env_name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"):
            if os.environ.get(env_name):
                env_vars.append(client.V1EnvVar(name=env_name, value=os.environ[env_name]))
    return env_vars


async def deploy_agent_pods(session: WizardState, topology_ns: str) -> List[Dict[str, Any]]:
    """
    Create K8s resources (Namespace, NADs, ConfigMaps, Deployments, Services)
    for each agent. Uses Multus CNI for real virtual interfaces between agents,
    enabling actual OSPF/BGP adjacencies.
    """
    agent_statuses = []
    agent_image = "asi-agent:latest"

    # 1. Create the topology namespace
    ns_body = client.V1Namespace(
        metadata=client.V1ObjectMeta(
            name=topology_ns,
            labels={
                "asi.anthropic.com/topology": session.topology_name,
            }
        )
    )
    try:
        k8s_core.create_namespace(body=ns_body)
        logger.info(f"Created namespace: {topology_ns}")
    except ApiException as e:
        if e.status == 409:
            logger.info(f"Namespace {topology_ns} already exists")
        else:
            raise

    # 2. Build links and create NetworkAttachmentDefinitions
    links = build_agent_links(session)
    logger.info(f"Topology has {len(links)} links: {[l['name'] for l in links]}")

    if links:
        await create_network_attachments(topology_ns, links, session.topology_name)

    # 3. Deploy each agent
    apps_api = client.AppsV1Api()

    for agent_cfg in session.agents:
        agent_name = agent_cfg.id
        try:
            # Build ConfigMap data (same format the start-agent.sh expects)
            config_data = {"agent.name": agent_name}

            # Interface config
            for i, iface in enumerate(agent_cfg.interfaces):
                iface_name = iface.get("n") or iface.get("name", f"eth{i}")
                iface_type = iface.get("t") or iface.get("type", "ethernet")
                config_data[f"interface.{i}.name"] = iface_name
                config_data[f"interface.{i}.type"] = iface_type
                addresses = iface.get("a") or iface.get("addresses", [])
                for j, addr in enumerate(addresses):
                    config_data[f"interface.{i}.address.{j}"] = addr
                # MTU
                mtu = iface.get("mtu")
                if mtu:
                    config_data[f"interface.{i}.mtu"] = str(mtu)
                # GRE/tunnel config: serialize tun block as JSON
                tun = iface.get("tun")
                if tun:
                    config_data[f"interface.{i}.tun"] = json.dumps(tun)

            # Protocol config
            for i, proto in enumerate(agent_cfg.protocols):
                proto_type = proto.get("p") or proto.get("type", agent_cfg.protocol)
                config_data[f"protocol.{i}.type"] = proto_type
                router_id = proto.get("r") or proto.get("router_id", agent_cfg.router_id)
                if router_id:
                    config_data[f"protocol.{i}.routerId"] = router_id
                area = proto.get("a") or proto.get("area")
                if area:
                    config_data[f"protocol.{i}.area"] = str(area)
                # Pass through any extra config keys
                opts = proto.get("opts")
                if opts and isinstance(opts, dict):
                    for key, value in opts.items():
                        config_data[f"protocol.{i}.{key}"] = str(value)
                if proto.get("config") and isinstance(proto["config"], dict):
                    for key, value in proto["config"].items():
                        config_data[f"protocol.{i}.{key}"] = str(value)

            # Link-to-interface mapping for start-agent.sh
            # Tells the startup script which ConfigMap interfaces map to Multus net1, net2...
            link_iface_index = 0
            for link in links:
                if link["agent1"] == agent_name:
                    iface_name = link["iface1"]
                elif link["agent2"] == agent_name:
                    iface_name = link["iface2"]
                else:
                    continue
                # Find the ConfigMap interface index for this interface name
                for i, iface in enumerate(agent_cfg.interfaces):
                    cfg_iface_name = iface.get("n") or iface.get("name", "")
                    if cfg_iface_name == iface_name:
                        config_data[f"link.{link_iface_index}.interface_index"] = str(i)
                        config_data[f"link.{link_iface_index}.interface_name"] = cfg_iface_name
                        link_iface_index += 1
                        break
            config_data["link.count"] = str(link_iface_index)

            # LLM config
            if session.llm_config:
                config_data["llm.model"] = session.llm_config.model
                config_data["llm.profile"] = f"Network agent: {agent_cfg.name}"

            # Create ConfigMap
            cm = client.V1ConfigMap(
                metadata=client.V1ObjectMeta(
                    name=f"{agent_name}-config",
                    namespace=topology_ns,
                    labels={
                        "asi.anthropic.com/agent": agent_name,
                        "asi.anthropic.com/topology": session.topology_name,
                    }
                ),
                data=config_data
            )
            try:
                k8s_core.create_namespaced_config_map(namespace=topology_ns, body=cm)
            except ApiException as e:
                if e.status == 409:
                    k8s_core.replace_namespaced_config_map(
                        name=f"{agent_name}-config", namespace=topology_ns, body=cm
                    )
                else:
                    raise

            # Build Multus network annotations for this agent
            multus_annotations = build_multus_annotations(links, agent_name, topology_ns)

            # Create Deployment with Multus annotations for real interfaces
            deployment = client.V1Deployment(
                metadata=client.V1ObjectMeta(
                    name=agent_name,
                    namespace=topology_ns,
                    labels={
                        "asi.anthropic.com/agent": agent_name,
                        "asi.anthropic.com/topology": session.topology_name,
                    }
                ),
                spec=client.V1DeploymentSpec(
                    replicas=1,
                    selector=client.V1LabelSelector(
                        match_labels={"asi.anthropic.com/agent": agent_name}
                    ),
                    template=client.V1PodTemplateSpec(
                        metadata=client.V1ObjectMeta(
                            labels={
                                "asi.anthropic.com/agent": agent_name,
                                "asi.anthropic.com/topology": session.topology_name,
                            },
                            annotations=multus_annotations,
                        ),
                        spec=client.V1PodSpec(
                            containers=[
                                client.V1Container(
                                    name="agent",
                                    image=agent_image,
                                    image_pull_policy="Never",
                                    ports=[
                                        client.V1ContainerPort(
                                            name="dashboard",
                                            container_port=8000,
                                            protocol="TCP"
                                        ),
                                        client.V1ContainerPort(
                                            name="metrics",
                                            container_port=9090,
                                            protocol="TCP"
                                        ),
                                    ],
                                    env=[
                                        client.V1EnvVar(name="AGENT_NAME", value=agent_name),
                                        client.V1EnvVar(name="TOPOLOGY_NAME", value=session.topology_name),
                                    ] + _build_api_key_env(session),
                                    volume_mounts=[
                                        client.V1VolumeMount(
                                            name="config",
                                            mount_path="/etc/asi"
                                        ),
                                    ],
                                    security_context=client.V1SecurityContext(
                                        capabilities=client.V1Capabilities(
                                            add=["NET_ADMIN", "NET_RAW"]
                                        )
                                    ),
                                )
                            ],
                            volumes=[
                                client.V1Volume(
                                    name="config",
                                    config_map=client.V1ConfigMapVolumeSource(
                                        name=f"{agent_name}-config"
                                    )
                                ),
                            ],
                        ),
                    ),
                ),
            )
            try:
                apps_api.create_namespaced_deployment(namespace=topology_ns, body=deployment)
            except ApiException as e:
                if e.status == 409:
                    apps_api.replace_namespaced_deployment(
                        name=agent_name, namespace=topology_ns, body=deployment
                    )
                else:
                    raise

            # Create Service
            svc = client.V1Service(
                metadata=client.V1ObjectMeta(
                    name=agent_name,
                    namespace=topology_ns,
                    labels={
                        "asi.anthropic.com/agent": agent_name,
                        "asi.anthropic.com/topology": session.topology_name,
                    }
                ),
                spec=client.V1ServiceSpec(
                    type="ClusterIP",
                    selector={"asi.anthropic.com/agent": agent_name},
                    ports=[
                        client.V1ServicePort(
                            name="dashboard", port=8080, target_port=8000, protocol="TCP"
                        ),
                        client.V1ServicePort(
                            name="metrics", port=9090, target_port=9090, protocol="TCP"
                        ),
                    ],
                ),
            )
            try:
                k8s_core.create_namespaced_service(namespace=topology_ns, body=svc)
            except ApiException as e:
                if e.status == 409:
                    pass  # Service already exists

            # Count how many links this agent participates in
            link_count = sum(1 for l in links if l["agent1"] == agent_name or l["agent2"] == agent_name)
            logger.info(f"Deployed agent: {agent_name} in {topology_ns} ({link_count} links, Multus interfaces: net1..net{link_count})")
            agent_statuses.append({
                "name": agent_name,
                "phase": "Deploying",
                "pod_name": f"{agent_name}-*",
                "dashboard_url": f"http://{agent_name}.{topology_ns}.svc.cluster.local:8080",
                "links": link_count,
            })

        except Exception as e:
            logger.error(f"Failed to deploy agent {agent_name}: {e}")
            agent_statuses.append({
                "name": agent_name,
                "phase": "Failed",
                "message": str(e),
            })

    return agent_statuses


async def create_topology(session: WizardState) -> Dict[str, Any]:
    """Create AgentTopology CR in Kubernetes and deploy agent pods"""

    # Build the CR
    topology_cr = build_agenttopology_cr(session)
    topology_ns = f"topology-{session.topology_name}"

    try:
        # Create the AgentTopology custom resource
        response = k8s_custom.create_namespaced_custom_object(
            group=ASI_GROUP,
            version=ASI_VERSION,
            namespace=ASI_NAMESPACE,
            plural=ASI_PLURAL,
            body=topology_cr
        )

        logger.info(f"Created AgentTopology: {session.topology_name}")

    except ApiException as e:
        if e.status == 409:
            logger.info(f"AgentTopology '{session.topology_name}' already exists, continuing with deployment")
        else:
            logger.error(f"Failed to create AgentTopology: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # Deploy actual agent pods (direct deployment without controller)
    try:
        agent_statuses = await deploy_agent_pods(session, topology_ns)
        deployed_count = sum(1 for a in agent_statuses if a["phase"] != "Failed")
        logger.info(f"Deployed {deployed_count}/{len(agent_statuses)} agents in {topology_ns}")

        # Build agents dict in the format frontend expects:
        # { "agent-id": { "webui_port": ..., "ip_address": ..., "status": ... } }
        agents_dict = {}
        for i, agent_status in enumerate(agent_statuses):
            agent_name = agent_status["name"]
            agents_dict[agent_name] = {
                "webui_port": None,  # K8s uses services, not localhost ports
                "ip_address": f"{agent_name}.{topology_ns}.svc.cluster.local",
                "status": "deploying" if agent_status["phase"] != "Failed" else "failed",
                "dashboard_url": agent_status.get("dashboard_url", ""),
                "namespace": topology_ns,
                "links": agent_status.get("links", 0),
            }

        return {
            "status": "created",
            "topology_name": session.topology_name,
            "namespace": topology_ns,
            "agent_count": deployed_count,
            "agents": agents_dict,
        }

    except Exception as e:
        logger.error(f"Failed to deploy agents: {e}")
        raise HTTPException(status_code=500, detail=f"Agent deployment failed: {str(e)}")


async def get_topology_status(topology_name: str) -> Dict[str, Any]:
    """Get status of a deployed topology"""

    try:
        response = k8s_custom.get_namespaced_custom_object(
            group=ASI_GROUP,
            version=ASI_VERSION,
            namespace=ASI_NAMESPACE,
            plural=ASI_PLURAL,
            name=topology_name
        )

        status = response.get("status", {})

        return {
            "name": topology_name,
            "phase": status.get("phase", "Unknown"),
            "namespace": status.get("namespace"),
            "agents": status.get("agentStatuses", []),
            "conditions": status.get("conditions", [])
        }

    except ApiException as e:
        if e.status == 404:
            raise HTTPException(status_code=404, detail="Topology not found")
        raise HTTPException(status_code=500, detail=str(e))


async def delete_topology(topology_name: str):
    """Delete an AgentTopology CR"""

    try:
        k8s_custom.delete_namespaced_custom_object(
            group=ASI_GROUP,
            version=ASI_VERSION,
            namespace=ASI_NAMESPACE,
            plural=ASI_PLURAL,
            name=topology_name
        )

        logger.info(f"Deleted AgentTopology: {topology_name}")

    except ApiException as e:
        if e.status == 404:
            raise HTTPException(status_code=404, detail="Topology not found")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# API Endpoints
# ============================================================================

@api_router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "platform": "kubernetes"}


@api_router.get("/mcps/default")
async def get_default_mcps():
    """Get default MCP configurations for wizard - loaded from mcp_definitions.json"""
    return MCP_DEFINITIONS


@api_router.get("/libraries/agents")
async def get_agent_templates():
    """Get agent template library (empty for now - agents built via wizard)"""
    return []


@api_router.get("/check-k8s")
async def check_kubernetes():
    """Check if Kubernetes API is accessible"""
    if not k8s_core or not k8s_custom:
        return {
            "available": False,
            "message": "No Kubernetes cluster configured. Start a kind cluster first."
        }
    try:
        # Try to list namespaces
        k8s_core.list_namespace(limit=1)

        # Try to list AgentTopology CRDs
        k8s_custom.list_namespaced_custom_object(
            group=ASI_GROUP,
            version=ASI_VERSION,
            namespace=ASI_NAMESPACE,
            plural=ASI_PLURAL,
            limit=1
        )

        return {
            "available": True,
            "message": "Kubernetes API is accessible and AgentTopology CRD is installed"
        }
    except Exception as e:
        return {
            "available": False,
            "message": f"Kubernetes API error: {str(e)}"
        }


@api_router.post("/session/{session_id}/init")
async def init_session(session_id: str):
    """Initialize a new wizard session"""
    async with _wizard_sessions_lock:
        if session_id in _wizard_sessions:
            return {"status": "exists", "step": _wizard_sessions[session_id].step}

        _wizard_sessions[session_id] = WizardState()
        return {"status": "created", "step": 1}


@api_router.get("/session/{session_id}")
async def get_session(session_id: str):
    """Get current wizard session state"""
    if session_id not in _wizard_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    return _wizard_sessions[session_id].dict()


@api_router.post("/session/{session_id}/step/{step}")
async def update_step(session_id: str, step: int, data: Dict[str, Any]):
    """Update wizard step data"""
    if session_id not in _wizard_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = _wizard_sessions[session_id]
    session.step = step

    # Update step-specific data
    if step == 1:  # Topology name
        session.topology_name = data.get("topology_name", "my-topology")
    elif step == 2:  # MCP selection
        session.mcp_selection = MCPSelection(**data)
    elif step == 3:  # Agents
        session.agents = [AgentConfig(**agent) for agent in data.get("agents", [])]
    elif step == 4:  # Topology/Links
        session.topology = TopologyConfig(**data)
    elif step == 5:  # LLM configuration
        session.llm_config = LLMConfig(**data)

    return {"status": "ok", "step": step}


@api_router.post("/session/{session_id}/step3/agent")
async def add_agent(session_id: str, agent: Dict[str, Any]):
    """Add a single agent to step 3"""
    if session_id not in _wizard_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = _wizard_sessions[session_id]

    # Initialize agents list if needed
    if not session.agents:
        session.agents = []

    # Add the agent (will be validated by AgentConfig)
    try:
        agent_config = AgentConfig(**agent)
        session.agents.append(agent_config)
        return {"status": "ok", "agent_id": agent_config.id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid agent configuration: {str(e)}")


@api_router.post("/session/{session_id}/step3/complete")
async def complete_step3(session_id: str):
    """Mark step 3 (agents) as complete"""
    if session_id not in _wizard_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = _wizard_sessions[session_id]
    session.step = 3
    return {"status": "ok", "agent_count": len(session.agents) if session.agents else 0}


@api_router.get("/session/{session_id}/preview")
async def get_preview(session_id: str):
    """Get session preview/summary for the final review step"""
    if session_id not in _wizard_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = _wizard_sessions[session_id]
    agents = session.agents or []
    links = session.topology.links if session.topology else []

    return {
        "topology_name": session.topology_name or "my-network",
        "agent_count": len(agents),
        "link_count": len(links),
        "mcp_count": len(session.mcp_selection.selected) if session.mcp_selection else 0,
        "agents": [{"id": a.id, "name": a.name, "router_id": a.router_id, "protocol": a.protocol} for a in agents],
        "mcps": session.mcp_selection.selected if session.mcp_selection else [],
    }


@api_router.post("/session/{session_id}/validate-api-key")
async def validate_api_key(session_id: str, data: Dict[str, Any]):
    """Basic API key format validation"""
    if session_id not in _wizard_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    provider = data.get("provider", "")
    api_key = data.get("api_key", "")

    if not api_key:
        return {"valid": False, "message": "API key is required"}

    # Basic format validation per provider
    if provider == "claude" and not api_key.startswith("sk-ant-"):
        return {"valid": False, "message": "Anthropic API keys typically start with 'sk-ant-'"}
    elif provider == "openai" and not api_key.startswith("sk-"):
        return {"valid": False, "message": "OpenAI API keys typically start with 'sk-'"}

    return {"valid": True, "message": "API key format looks valid"}


# ============================================================================
# NetBox MCP Endpoints (ported from Docker-based wizard)
# ============================================================================

class NetBoxCheckDuplicatesRequest(BaseModel):
    netbox_url: str = Field(..., min_length=1)
    api_token: str = Field(..., min_length=1)
    device_names: List[str] = Field(...)


class NetBoxRegisterFromWizardRequest(BaseModel):
    netbox_url: str = Field(..., min_length=1)
    api_token: str = Field(..., min_length=1)
    site_name: str = Field(..., min_length=1)
    agent_name: str = Field(...)
    agent_config: Dict[str, Any] = Field(...)


class NetBoxCablesRequest(BaseModel):
    netbox_url: str = Field(..., min_length=1)
    api_token: str = Field(..., min_length=1)
    site_name: str = Field(..., min_length=1)
    links: List[Dict[str, Any]] = Field(...)


@api_router.post("/mcps/netbox/check-duplicates")
async def check_netbox_duplicates(request: NetBoxCheckDuplicatesRequest):
    """Check if devices already exist in NetBox before registration."""
    try:
        import httpx

        if not request.netbox_url.startswith(('http://', 'https://')):
            return {"status": "error", "error": "Invalid NetBox URL: must start with http:// or https://"}

        base_url = request.netbox_url.rstrip('/')
        headers = {
            "Authorization": f"Token {request.api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        duplicates = []
        async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
            for device_name in request.device_names:
                try:
                    response = await client.get(
                        f"{base_url}/api/dcim/devices/",
                        headers=headers,
                        params={"name": device_name}
                    )
                    if response.status_code == 200:
                        data = response.json()
                        results = data.get("results", [])
                        if results:
                            device = results[0]
                            duplicates.append({
                                "name": device_name,
                                "exists": True,
                                "device_id": device.get("id"),
                                "device_url": f"{base_url}/dcim/devices/{device.get('id')}/",
                                "site": device.get("site", {}).get("name", "Unknown"),
                                "status": device.get("status", {}).get("value", "unknown")
                            })
                except Exception as e:
                    logger.warning(f"Error checking device {device_name}: {e}")

        return {
            "status": "ok",
            "total_checked": len(request.device_names),
            "duplicates_found": len(duplicates),
            "duplicates": duplicates
        }
    except ImportError:
        return {"status": "error", "error": "httpx not installed"}
    except Exception as e:
        logger.error(f"Error checking NetBox duplicates: {e}")
        return {"status": "error", "error": str(e)}


@api_router.post("/session/{session_id}/agents/{agent_id}/mcps/netbox/register")
async def register_wizard_agent_in_netbox(session_id: str, agent_id: str, request: NetBoxRegisterFromWizardRequest):
    """Register an agent from the wizard session in NetBox."""
    if not request.netbox_url.startswith(('http://', 'https://')):
        return {
            "status": "error", "success": False, "agent_id": agent_id,
            "agent_name": request.agent_name,
            "errors": [f"Invalid NetBox URL: '{request.netbox_url}' - must start with http:// or https://"]
        }

    try:
        from netbox_mcp import NetBoxConfig, configure_netbox, auto_register_agent, get_netbox_client

        config = NetBoxConfig(
            url=request.netbox_url,
            api_token=request.api_token,
            site_name=request.site_name,
            auto_register=True
        )
        configure_netbox(config)

        agent_cfg = request.agent_config
        netbox_agent_config = {
            "router_id": agent_cfg.get("router_id", ""),
            "interfaces": [],
            "protocols": []
        }

        # Convert interfaces (wizard uses n=name, t=type, a=addresses array)
        interfaces = agent_cfg.get("interfaces", agent_cfg.get("ifs", []))
        for iface in interfaces:
            if isinstance(iface, dict):
                ip_addr = ""
                addresses = iface.get("a", [])
                if addresses and len(addresses) > 0:
                    ip_addr = addresses[0]
                elif iface.get("ip"):
                    ip_addr = iface.get("ip")

                netbox_agent_config["interfaces"].append({
                    "name": iface.get("n") or iface.get("name", ""),
                    "type": iface.get("t") or iface.get("type", "ethernet"),
                    "ip": ip_addr,
                    "enabled": iface.get("e", True) if "e" in iface else iface.get("enabled", True),
                    "mac": iface.get("mac"),
                })

        # Convert protocols (wizard uses p=type, a=area, asn=AS number)
        protocols = agent_cfg.get("protos", agent_cfg.get("protocols", []))
        for proto in protocols:
            if isinstance(proto, dict):
                proto_type = proto.get("p") or proto.get("t") or proto.get("type", "")
                proto_dict = {"type": proto_type}
                if "a" in proto:
                    proto_dict["area"] = proto["a"]
                if "area" in proto:
                    proto_dict["area"] = proto["area"]
                if "asn" in proto:
                    proto_dict["local_as"] = proto["asn"]
                if "local_as" in proto:
                    proto_dict["local_as"] = proto["local_as"]
                if "peers" in proto:
                    proto_dict["peers"] = proto["peers"]
                netbox_agent_config["protocols"].append(proto_dict)

        logger.info(f"Registering wizard agent {agent_id} ({request.agent_name}) in NetBox site {request.site_name}")
        result = await auto_register_agent(request.agent_name, netbox_agent_config)

        client = get_netbox_client()
        if client:
            await client.close()

        is_success = result.get("success", False)
        return {
            "status": "ok" if is_success else "error",
            "success": is_success,
            "agent_id": agent_id,
            "agent_name": request.agent_name,
            "device_name": result.get("device_name", request.agent_name),
            "device_url": result.get("device_url"),
            "interfaces": result.get("interfaces", []),
            "ip_addresses": result.get("ip_addresses", []),
            "services": result.get("services", []),
            "errors": result.get("errors", [])
        }
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"NetBox MCP not available: {e}. Install httpx: pip install httpx")
    except Exception as e:
        logger.error(f"NetBox registration failed for {agent_id}: {e}")
        return {
            "status": "error", "success": False, "agent_id": agent_id,
            "agent_name": request.agent_name, "errors": [str(e)]
        }


@api_router.post("/mcps/netbox/register-cables")
async def register_netbox_cables(request: NetBoxCablesRequest):
    """Register cables/links in NetBox to capture network topology."""
    if not request.netbox_url.startswith(('http://', 'https://')):
        return {"status": "error", "success": False, "error": "Invalid NetBox URL: must start with http:// or https://"}

    try:
        from netbox_mcp import NetBoxConfig, NetBoxClient as NBClient

        config = NetBoxConfig(
            url=request.netbox_url,
            api_token=request.api_token,
            site_name=request.site_name
        )
        nb_client = NBClient(config)
        result = await nb_client.register_topology_cables(request.links)
        await nb_client.close()

        logger.info(f"[NetBox Cables] Complete: {result['created']} created, {result['existing']} existing, {result['failed']} failed")
        return {
            "status": "ok" if result["failed"] == 0 else "partial",
            "success": result["failed"] == 0,
            "total": result["total"],
            "created": result["created"],
            "existing": result["existing"],
            "failed": result["failed"],
            "cables": result["cables"],
            "errors": result["errors"],
            "message": f"Registered {result['created']} cables ({result['existing']} already existed, {result['failed']} failed)"
        }
    except ImportError as e:
        return {"status": "error", "success": False, "error": f"NetBox MCP not available: {e}"}
    except Exception as e:
        logger.error(f"Error registering NetBox cables: {e}")
        return {"status": "error", "success": False, "error": str(e)}


@api_router.post("/session/{session_id}/launch")
async def launch_topology(session_id: str, request: LaunchRequest):
    """Launch the configured topology to Kubernetes"""
    if not k8s_custom:
        raise HTTPException(status_code=503, detail="No Kubernetes cluster available. Please start a kind cluster first.")

    if session_id not in _wizard_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = _wizard_sessions[session_id]
    session.topology_name = request.topology_name

    # Store API keys in session for topology CR
    session.api_keys = request.api_keys

    # Validate session
    if not session.agents:
        raise HTTPException(status_code=400, detail="No agents configured")

    # Create the topology
    result = await create_topology(session)

    # Clean up session
    async with _wizard_sessions_lock:
        if session_id in _wizard_sessions:
            del _wizard_sessions[session_id]

    return result


@api_router.get("/topologies")
async def list_topologies():
    """List all deployed topologies"""
    try:
        response = k8s_custom.list_namespaced_custom_object(
            group=ASI_GROUP,
            version=ASI_VERSION,
            namespace=ASI_NAMESPACE,
            plural=ASI_PLURAL
        )

        topologies = []
        for item in response.get("items", []):
            metadata = item["metadata"]
            status = item.get("status", {})

            topologies.append({
                "name": metadata["name"],
                "created": metadata["creationTimestamp"],
                "phase": status.get("phase", "Unknown"),
                "namespace": status.get("namespace"),
                "agent_count": len(item["spec"].get("agents", []))
            })

        return {"topologies": topologies}

    except ApiException as e:
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/topologies/{topology_name}")
async def get_topology(topology_name: str):
    """Get topology details and status"""
    return await get_topology_status(topology_name)


@api_router.get("/topologies/{topology_name}/pods")
async def get_topology_pods(topology_name: str):
    """Get live pod status for a topology"""
    if not k8s_core:
        raise HTTPException(status_code=503, detail="No Kubernetes cluster available")

    topology_ns = f"topology-{topology_name}"
    try:
        pods = k8s_core.list_namespaced_pod(
            namespace=topology_ns,
            label_selector=f"asi.anthropic.com/topology={topology_name}"
        )
        agents = {}
        for pod in pods.items:
            agent_name = pod.metadata.labels.get("asi.anthropic.com/agent", pod.metadata.name)
            phase = pod.status.phase  # Running, Pending, Failed, etc.
            ready = all(
                cs.ready for cs in (pod.status.container_statuses or [])
            )
            agents[agent_name] = {
                "pod_name": pod.metadata.name,
                "status": "running" if phase == "Running" and ready else phase.lower(),
                "ip_address": pod.status.pod_ip or "N/A",
                "namespace": topology_ns,
                "node": pod.spec.node_name,
            }
        return {
            "topology_name": topology_name,
            "namespace": topology_ns,
            "agent_count": len(agents),
            "agents": agents,
        }
    except ApiException as e:
        if e.status == 404:
            raise HTTPException(status_code=404, detail=f"Namespace {topology_ns} not found")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.delete("/topologies/{topology_name}")
async def remove_topology(topology_name: str):
    """Delete a topology"""
    await delete_topology(topology_name)
    return {"status": "deleted", "topology_name": topology_name}


@api_router.get("/topologies/{topology_name}/yaml")
async def get_topology_yaml(topology_name: str):
    """Get the AgentTopology CR as YAML"""
    try:
        response = k8s_custom.get_namespaced_custom_object(
            group=ASI_GROUP,
            version=ASI_VERSION,
            namespace=ASI_NAMESPACE,
            plural=ASI_PLURAL,
            name=topology_name
        )

        # Convert to YAML
        yaml_content = yaml.dump(response, default_flow_style=False)

        return {"yaml": yaml_content}

    except ApiException as e:
        if e.status == 404:
            raise HTTPException(status_code=404, detail="Topology not found")
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================================================
# SMTP Email API Endpoints
# ==========================================================================

class SMTPConfigRequest(BaseModel):
    """SMTP configuration request"""
    server: str = Field(default="localhost")
    port: int = Field(default=587)
    username: str = Field(default="")
    password: str = Field(default="")
    use_tls: bool = Field(default=True)
    use_ssl: bool = Field(default=False)
    from_address: str = Field(default="agent@network.local")
    from_name: str = Field(default="Network Agent")

class SMTPSendRequest(BaseModel):
    """Email send request"""
    to: str = Field(..., min_length=1)
    subject: str = Field(..., min_length=1)
    body: str = Field(..., min_length=1)
    html_body: Optional[str] = None
    priority: str = Field(default="normal")

class SMTPTestRequest(BaseModel):
    """Test email request"""
    recipient: str = Field(..., min_length=1)

class SMTPAlertRuleRequest(BaseModel):
    """Alert rule request"""
    name: str = Field(..., min_length=1)
    alert_type: str = Field(..., min_length=1)
    recipients: str = Field(..., min_length=1)
    priority: str = Field(default="normal")
    cooldown: int = Field(default=300)


@api_router.get("/smtp/config")
async def get_smtp_config(agent_id: Optional[str] = None):
    """Get SMTP configuration and statistics"""
    try:
        from smtp_mcp import get_smtp_client
        smtp_client = get_smtp_client(agent_id or "local")
        return {"config": smtp_client.config.to_dict(), "statistics": smtp_client.get_statistics()}
    except ImportError as e:
        return {"config": {}, "error": f"SMTP module not available: {e}"}
    except Exception as e:
        logger.error(f"SMTP config error: {e}")
        return {"config": {}, "error": str(e)}


@api_router.post("/smtp/config")
async def set_smtp_config(request: SMTPConfigRequest):
    """Configure SMTP settings"""
    try:
        from smtp_mcp import get_smtp_client, SMTPConfig
        smtp_client = get_smtp_client()

        smtp_config = SMTPConfig(
            server=request.server,
            port=request.port,
            username=request.username,
            password=request.password,
            use_tls=request.use_tls,
            use_ssl=request.use_ssl,
            from_address=request.from_address,
            from_name=request.from_name
        )
        smtp_client.configure(smtp_config)
        return {"success": True, "config": smtp_config.to_dict()}
    except ImportError as e:
        return {"success": False, "error": f"SMTP module not available: {e}"}
    except Exception as e:
        logger.error(f"SMTP config set error: {e}")
        return {"success": False, "error": str(e)}


@api_router.get("/smtp/history")
async def get_email_history(limit: int = 50, status: Optional[str] = None):
    """Get email history"""
    try:
        from smtp_mcp import get_smtp_client, EmailStatus
        smtp_client = get_smtp_client()

        email_status = None
        if status:
            email_status = EmailStatus(status)

        emails = smtp_client.get_email_history(limit, email_status)
        return {"emails": emails, "count": len(emails)}
    except ImportError as e:
        return {"emails": [], "error": f"SMTP module not available: {e}"}
    except Exception as e:
        logger.error(f"Email history error: {e}")
        return {"emails": [], "error": str(e)}


@api_router.get("/smtp/statistics")
async def get_smtp_statistics():
    """Get SMTP statistics"""
    try:
        from smtp_mcp import get_smtp_statistics as _get_stats
        return {"statistics": _get_stats()}
    except ImportError as e:
        return {"statistics": {}, "error": f"SMTP module not available: {e}"}
    except Exception as e:
        logger.error(f"SMTP statistics error: {e}")
        return {"statistics": {}, "error": str(e)}


@api_router.post("/smtp/test")
async def send_test_email(request: SMTPTestRequest):
    """Send a test email to verify configuration"""
    try:
        from smtp_mcp import get_smtp_client
        smtp_client = get_smtp_client()
        success = await smtp_client.send_test_email(request.recipient)
        return {"success": success}
    except ImportError as e:
        return {"success": False, "error": f"SMTP module not available: {e}"}
    except Exception as e:
        logger.error(f"Test email error: {e}")
        return {"success": False, "error": str(e)}


@api_router.post("/smtp/send")
async def send_email(request: SMTPSendRequest):
    """Send an email"""
    try:
        from smtp_mcp import get_smtp_client, Email, EmailPriority
        smtp_client = get_smtp_client()

        recipients = [r.strip() for r in request.to.split(",")]
        email_priority = EmailPriority(request.priority)

        email = Email(
            to=recipients,
            subject=request.subject,
            body=request.body,
            html_body=request.html_body,
            priority=email_priority
        )

        success = await smtp_client.send_immediate(email)
        return {"success": success, "email": email.to_dict()}
    except ImportError as e:
        return {"success": False, "error": f"SMTP module not available: {e}"}
    except Exception as e:
        logger.error(f"Send email error: {e}")
        return {"success": False, "error": str(e)}


@api_router.get("/smtp/alerts")
async def get_alert_rules():
    """Get all email alert rules"""
    try:
        from smtp_mcp import get_smtp_client
        smtp_client = get_smtp_client()
        rules = smtp_client.get_alert_rules()
        return {"rules": [r.to_dict() for r in rules], "count": len(rules)}
    except ImportError as e:
        return {"rules": [], "error": f"SMTP module not available: {e}"}
    except Exception as e:
        logger.error(f"Alert rules error: {e}")
        return {"rules": [], "error": str(e)}


@api_router.post("/smtp/alerts")
async def add_alert_rule(request: SMTPAlertRuleRequest):
    """Add an email alert rule"""
    try:
        from smtp_mcp import get_smtp_client, AlertRule, AlertType, EmailPriority
        smtp_client = get_smtp_client()

        rule = AlertRule(
            name=request.name,
            alert_type=AlertType(request.alert_type),
            recipients=[r.strip() for r in request.recipients.split(",")],
            priority=EmailPriority(request.priority),
            cooldown_seconds=request.cooldown
        )
        smtp_client.add_alert_rule(rule)
        return {"success": True, "rule": rule.to_dict()}
    except ImportError as e:
        return {"success": False, "error": f"SMTP module not available: {e}"}
    except Exception as e:
        logger.error(f"Add alert rule error: {e}")
        return {"success": False, "error": str(e)}


@api_router.delete("/smtp/alerts/{rule_name}")
async def delete_alert_rule(rule_name: str):
    """Delete an alert rule"""
    try:
        from smtp_mcp import get_smtp_client
        smtp_client = get_smtp_client()
        success = smtp_client.remove_alert_rule(rule_name)
        return {"success": success}
    except ImportError as e:
        return {"success": False, "error": f"SMTP module not available: {e}"}
    except Exception as e:
        logger.error(f"Delete alert rule error: {e}")
        return {"success": False, "error": str(e)}


# ============================================================================
# Agent Dashboard Reverse Proxy
# ============================================================================
# Proxies requests from the wizard (accessible via port-forward on localhost:8080)
# to agent ClusterIP services inside the K8s cluster, eliminating the need for
# per-agent port-forwards.
#
# URL pattern: /agent-proxy/{namespace}/{agent-name}/{path}
# Example:     /agent-proxy/topology-gre-test/core-router/dashboard
# Proxies to:  http://core-router.topology-gre-test.svc.cluster.local:8080/dashboard

_proxy_client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0), follow_redirects=True)


@app.api_route("/agent-proxy/{namespace}/{agent_name}/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def agent_proxy(namespace: str, agent_name: str, path: str, request: Request):
    """Reverse proxy to agent dashboard services inside the cluster."""
    # Validate namespace format
    if not namespace.startswith("topology-"):
        raise HTTPException(status_code=400, detail="Invalid namespace")

    # Build internal service URL
    target_url = f"http://{agent_name}.{namespace}.svc.cluster.local:8080/{path}"

    # Forward query string
    if request.url.query:
        target_url += f"?{request.url.query}"

    proxy_base = f"/agent-proxy/{namespace}/{agent_name}"

    try:
        # Forward the request
        body = await request.body()
        headers = {
            k: v for k, v in request.headers.items()
            if k.lower() not in ("host", "transfer-encoding")
        }

        resp = await _proxy_client.request(
            method=request.method,
            url=target_url,
            headers=headers,
            content=body if body else None,
        )

        content = resp.content
        content_type = resp.headers.get("content-type", "")

        # For HTML responses, inject a script that rewrites fetch/XHR to route
        # through the proxy. The agent dashboard uses absolute paths like
        # /api/interfaces and /static/agent-dashboard.js which would otherwise
        # hit the wizard service instead of the agent.
        if "text/html" in content_type:
            html = content.decode("utf-8", errors="replace")
            rewrite_script = f"""<script>
(function() {{
    var B = "{proxy_base}";
    // Rewrite fetch() calls
    var _fetch = window.fetch;
    window.fetch = function(url, opts) {{
        if (typeof url === "string" && url.startsWith("/") && !url.startsWith(B))
            url = B + url;
        return _fetch.call(this, url, opts);
    }};
    // Rewrite XMLHttpRequest.open()
    var _open = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function(method, url) {{
        if (typeof url === "string" && url.startsWith("/") && !url.startsWith(B))
            url = B + url;
        return _open.apply(this, arguments);
    }};
    // Rewrite WebSocket to route through proxy
    var _WS = window.WebSocket;
    window.WebSocket = function(url, protocols) {{
        if (typeof url === "string" && url.indexOf("/ws") !== -1) {{
            var proto = location.protocol === "https:" ? "wss:" : "ws:";
            url = proto + "//" + location.host + B + "/ws";
        }}
        return protocols ? new _WS(url, protocols) : new _WS(url);
    }};
    window.WebSocket.prototype = _WS.prototype;
    window.WebSocket.CONNECTING = _WS.CONNECTING;
    window.WebSocket.OPEN = _WS.OPEN;
    window.WebSocket.CLOSING = _WS.CLOSING;
    window.WebSocket.CLOSED = _WS.CLOSED;
}})();
</script>"""
            # Also rewrite src= and href= absolute paths in the HTML itself
            # so <script src="/static/..."> and <link href="/static/..."> load correctly
            html = html.replace('src="/static/', f'src="{proxy_base}/static/')
            html = html.replace("src='/static/", f"src='{proxy_base}/static/")
            html = html.replace('href="/static/', f'href="{proxy_base}/static/')
            html = html.replace("href='/static/", f"href='{proxy_base}/static/")
            # Inject the rewrite script right after <head>
            html = html.replace("<head>", f"<head>{rewrite_script}", 1)
            content = html.encode("utf-8")

        # Return proxied response with original content type
        return Response(
            content=content,
            status_code=resp.status_code,
            headers={
                k: v for k, v in resp.headers.items()
                if k.lower() not in ("transfer-encoding", "content-encoding", "content-length")
            },
        )

    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail=f"Agent {agent_name} is not reachable in {namespace}. Pod may still be starting.")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail=f"Agent {agent_name} timed out")
    except Exception as e:
        logger.error(f"Proxy error for {agent_name} in {namespace}: {e}")
        raise HTTPException(status_code=502, detail=str(e))


@app.websocket("/agent-proxy/{namespace}/{agent_name}/ws")
async def agent_ws_proxy(ws: WebSocket, namespace: str, agent_name: str):
    """WebSocket proxy to agent pods."""
    if not namespace.startswith("topology-"):
        await ws.close(code=1008)
        return

    await ws.accept()
    target_url = f"ws://{agent_name}.{namespace}.svc.cluster.local:8080/ws"

    try:
        async with websockets.connect(target_url) as upstream:
            async def client_to_upstream():
                try:
                    while True:
                        data = await ws.receive_text()
                        await upstream.send(data)
                except WebSocketDisconnect:
                    pass

            async def upstream_to_client():
                try:
                    async for msg in upstream:
                        await ws.send_text(msg)
                except Exception:
                    pass

            await asyncio.gather(client_to_upstream(), upstream_to_client())
    except Exception as e:
        logger.error(f"WebSocket proxy error for {agent_name}: {e}")
    finally:
        try:
            await ws.close()
        except Exception:
            pass


# Middleware to disable browser caching for JS/HTML (prevents stale wizard UI)
from starlette.middleware.base import BaseHTTPMiddleware

class NoCacheStaticMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static/") and any(request.url.path.endswith(ext) for ext in (".js", ".html", ".css")):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

app.add_middleware(NoCacheStaticMiddleware)

# Mount API router
app.include_router(api_router)

# Serve static files (wizard UI)
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# Serve index page
@app.get("/")
async def index():
    """Serve wizard UI"""
    if os.path.exists("static/wizard.html"):
        return FileResponse("static/wizard.html")
    elif os.path.exists("templates/index.html"):
        return FileResponse("templates/index.html")
    return HTMLResponse("""
    <html>
        <head><title>ASI Wizard</title></head>
        <body>
            <h1>ASI Network Topology Wizard</h1>
            <p>Kubernetes Edition - AgentTopology CRD Builder</p>
            <p>API available at <a href="/docs">/docs</a></p>
        </body>
    </html>
    """)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
