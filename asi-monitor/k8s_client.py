"""
Shared Kubernetes API client for ASI observability services.

Translates Docker-era /api/wizard/networks endpoints into K8s API calls,
querying topology-* namespaces and agent pods directly.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from kubernetes import client, config
from kubernetes.client.rest import ApiException

logger = logging.getLogger("ASIKubernetesClient")

TOPOLOGY_LABEL = "asi.anthropic.com/topology"
AGENT_LABEL = "asi.anthropic.com/agent"
LINK_LABEL = "asi.anthropic.com/link"
MULTUS_ANNOTATION = "k8s.v1.cni.cncf.io/networks"


class ASIKubernetesClient:
    """K8s API client that provides Docker-compatible network/agent endpoints."""

    def __init__(self):
        try:
            config.load_incluster_config()
            logger.info("Loaded in-cluster Kubernetes configuration")
        except Exception:
            try:
                config.load_kube_config()
                logger.info("Loaded kubeconfig configuration")
            except Exception as e:
                logger.warning(f"No Kubernetes cluster available: {e}")
                raise
        self.core = client.CoreV1Api()
        self.apps = client.AppsV1Api()
        self.custom = client.CustomObjectsApi()

    def list_topology_namespaces(self) -> List[Dict[str, Any]]:
        """
        List all topology-* namespaces as 'networks'.
        Maps to: GET /api/wizard/networks
        Returns the same shape the existing monitor.js expects.
        """
        namespaces = self.core.list_namespace(
            label_selector=TOPOLOGY_LABEL
        )
        results = []
        for ns in namespaces.items:
            topo_name = ns.metadata.labels.get(TOPOLOGY_LABEL, "")
            ns_name = ns.metadata.name
            network_id = ns_name.replace("topology-", "", 1)

            try:
                pods = self.core.list_namespaced_pod(namespace=ns_name)
                pod_count = len(pods.items)
                running_count = sum(
                    1 for p in pods.items if p.status.phase == "Running"
                )
            except ApiException:
                pod_count = 0
                running_count = 0

            results.append({
                "network_id": network_id,
                "name": topo_name,
                "status": "running" if running_count > 0 else "stopped",
                "agent_count": pod_count,
                "docker_network": ns_name,  # Compat field for monitor.js
                "started_at": ns.metadata.creation_timestamp.isoformat()
                if ns.metadata.creation_timestamp else "",
            })
        return results

    def get_network_status(self, network_id: str) -> Dict[str, Any]:
        """
        Get pod-level status for a topology namespace.
        Maps to: GET /api/wizard/networks/{id}/status
        """
        ns = f"topology-{network_id}"
        try:
            pods = self.core.list_namespaced_pod(
                namespace=ns,
                label_selector=TOPOLOGY_LABEL
            )
        except ApiException as e:
            if e.status == 404:
                return {"network_id": network_id, "agents": {}, "error": "Namespace not found"}
            raise

        agents = {}
        for pod in pods.items:
            agent_name = pod.metadata.labels.get(AGENT_LABEL, pod.metadata.name)
            phase = pod.status.phase or "Unknown"
            ready = all(
                cs.ready for cs in (pod.status.container_statuses or [])
            )
            config_data = self._get_agent_config(ns, agent_name)

            # Parse protocols from ConfigMap
            protocols = self._parse_protocols(config_data)

            agents[agent_name] = {
                "status": "running" if phase == "Running" and ready else phase.lower(),
                "ip_address": pod.status.pod_ip or "N/A",
                "docker_ip": pod.status.pod_ip or "N/A",
                "webui_port": None,  # K8s uses services, not localhost ports
                "config": self._build_frontend_config(config_data),
                "protocols": protocols,
                "ospf_neighbors": 0,
                "bgp_peers": 0,
                "namespace": ns,
                "node": pod.spec.node_name,
            }

        return {
            "network_id": network_id,
            "name": network_id,
            "status": "running" if any(
                a["status"] == "running" for a in agents.values()
            ) else "stopped",
            "agent_count": len(agents),
            "agents": agents,
        }

    def get_network_health(self, network_id: str) -> Dict[str, Any]:
        """
        Check pod readiness for all agents in a topology.
        Maps to: GET /api/wizard/networks/{id}/health
        """
        ns = f"topology-{network_id}"
        try:
            pods = self.core.list_namespaced_pod(namespace=ns)
        except ApiException:
            return {"healthy": False, "agents": {}, "error": "Namespace not found"}

        agents = {}
        all_healthy = True
        for pod in pods.items:
            agent_name = pod.metadata.labels.get(AGENT_LABEL, pod.metadata.name)
            ready = all(
                cs.ready for cs in (pod.status.container_statuses or [])
            )
            healthy = pod.status.phase == "Running" and ready
            if not healthy:
                all_healthy = False
            agents[agent_name] = {
                "healthy": healthy,
                "status": pod.status.phase,
            }
        return {"healthy": all_healthy, "agents": agents}

    def get_agent_logs(
        self, network_id: str, agent_id: str, tail: int = 200
    ) -> Dict[str, Any]:
        """
        Get pod logs for a specific agent.
        Maps to: GET /api/wizard/networks/{id}/agents/{agentId}/logs
        """
        ns = f"topology-{network_id}"
        try:
            pods = self.core.list_namespaced_pod(
                namespace=ns,
                label_selector=f"{AGENT_LABEL}={agent_id}"
            )
        except ApiException:
            return {"logs": f"Namespace {ns} not found"}

        if not pods.items:
            return {"logs": f"No pod found for agent {agent_id}"}

        pod_name = pods.items[0].metadata.name
        try:
            logs = self.core.read_namespaced_pod_log(
                name=pod_name, namespace=ns, tail_lines=tail
            )
            return {"logs": logs or "(no logs yet)"}
        except ApiException as e:
            return {"logs": f"Error reading logs: {e.reason}"}

    def stop_network(self, network_id: str) -> Dict[str, Any]:
        """
        Delete the topology namespace (cascading delete of all resources).
        Maps to: POST /api/wizard/networks/{id}/stop
        """
        ns = f"topology-{network_id}"
        try:
            self.core.delete_namespace(name=ns)
            return {"status": "deleted", "network_id": network_id}
        except ApiException as e:
            if e.status == 404:
                return {"status": "not_found", "network_id": network_id}
            return {"status": "error", "error": str(e)}

    def get_topology_graph(self, network_id: str) -> Dict[str, Any]:
        """
        Build node/link graph data for 3D visualization.
        Reads pods, ConfigMaps, and NADs to construct nodes + links.
        """
        ns = f"topology-{network_id}"
        try:
            pods = self.core.list_namespaced_pod(
                namespace=ns, label_selector=TOPOLOGY_LABEL
            )
        except ApiException:
            return {"nodes": [], "links": []}

        nads = self._list_nads(ns)

        nodes = []
        for pod in pods.items:
            agent_name = pod.metadata.labels.get(AGENT_LABEL, pod.metadata.name)
            config_data = self._get_agent_config(ns, agent_name)
            protocols = self._parse_protocols(config_data)
            phase = pod.status.phase or "Unknown"
            ready = all(
                cs.ready for cs in (pod.status.container_statuses or [])
            )

            nodes.append({
                "id": agent_name,
                "name": config_data.get("agent.name", agent_name),
                "status": "running" if phase == "Running" and ready else phase.lower(),
                "protocols": protocols,
                "neighbors": 0,
                "routes": 0,
                "docker_ip": pod.status.pod_ip or "N/A",
                "port": None,
                "network": network_id,
            })

        links = self._build_links_from_nads(nads, pods)

        return {"nodes": nodes, "links": links}

    def _get_agent_config(self, ns: str, agent_name: str) -> Dict[str, str]:
        """Read agent ConfigMap to extract protocol/interface config."""
        try:
            cm = self.core.read_namespaced_config_map(
                name=f"{agent_name}-config", namespace=ns
            )
            return cm.data or {}
        except ApiException:
            return {}

    def _parse_protocols(self, config_data: Dict[str, str]) -> List[str]:
        """Extract protocol names from ConfigMap flat keys."""
        protocols = []
        i = 0
        while True:
            proto_type = config_data.get(f"protocol.{i}.type")
            if proto_type is None:
                break
            protocols.append(proto_type.upper())
            i += 1
        return protocols

    def _build_frontend_config(self, config_data: Dict[str, str]) -> Dict[str, Any]:
        """
        Convert flat ConfigMap keys to the nested format frontend JS expects.
        JS reads: config.n (name), config.protos ([{p: "ospf", ...}])
        """
        result: Dict[str, Any] = {
            "n": config_data.get("agent.name", ""),
        }
        protos = []
        i = 0
        while True:
            proto_type = config_data.get(f"protocol.{i}.type")
            if proto_type is None:
                break
            proto = {"p": proto_type.lower()}
            area = config_data.get(f"protocol.{i}.area")
            if area:
                proto["area"] = area
            rid = config_data.get(f"protocol.{i}.routerId")
            if rid:
                proto["rid"] = rid
            protos.append(proto)
            i += 1
        result["protos"] = protos
        return result

    def _list_nads(self, ns: str) -> List[Dict[str, Any]]:
        """List NetworkAttachmentDefinitions in a namespace."""
        try:
            nads = self.custom.list_namespaced_custom_object(
                group="k8s.cni.cncf.io",
                version="v1",
                namespace=ns,
                plural="network-attachment-definitions",
            )
            return nads.get("items", [])
        except ApiException:
            return []

    def _build_links_from_nads(
        self, nads: List[Dict[str, Any]], pods
    ) -> List[Dict[str, Any]]:
        """
        Build link list from NADs + pod Multus annotations.
        Each NAD represents a link. Pod annotations tell us which agents
        are connected to which NAD.
        """
        # Map NAD name -> link metadata
        nad_names = set()
        for nad in nads:
            nad_name = nad["metadata"]["name"]
            nad_names.add(nad_name)

        # Map: NAD name -> list of agent names attached to it
        nad_to_agents: Dict[str, List[str]] = {n: [] for n in nad_names}

        for pod in pods.items:
            agent_name = pod.metadata.labels.get(AGENT_LABEL, pod.metadata.name)
            annotations = pod.metadata.annotations or {}
            multus_nets = annotations.get(MULTUS_ANNOTATION, "")
            if not multus_nets:
                # Check template annotations from deployment
                continue
            for net_ref in multus_nets.split(","):
                net_ref = net_ref.strip()
                # Format: "namespace/nad-name" or just "nad-name"
                nad_name = net_ref.split("/")[-1] if "/" in net_ref else net_ref
                if nad_name in nad_to_agents:
                    nad_to_agents[nad_name].append(agent_name)

        # Build links from NADs with exactly 2 agents
        links = []
        for nad_name, agents in nad_to_agents.items():
            if len(agents) >= 2:
                links.append({
                    "source": agents[0],
                    "target": agents[1],
                    "protocol": "Underlay",
                    "layer": "underlay",
                    "name": nad_name,
                })
        return links
