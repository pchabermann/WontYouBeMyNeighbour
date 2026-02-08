# ASI Controller

**Agentic Software Infrastructure (ASI) Kubernetes Operator**

The ASI Controller is a Kubernetes operator that orchestrates cloud-native network agent topologies with LLM integration. It provides a declarative API for deploying, managing, and monitoring autonomous network agents running routing protocols (OSPF, BGP, IS-IS) with Claude AI integration.

## Overview

Won't You Be My Neighbor is evolving from Docker-based deployments to a full cloud-native Kubernetes architecture. The ASI Controller is the core component that:

- **Manages Network Topologies**: Declaratively define multi-agent network topologies using Kubernetes Custom Resources
- **Orchestrates Agent Pods**: Automatically provisions StatefulSets, Services, ConfigMaps, and PersistentVolumes
- **Enables True Network Isolation**: Uses Multus CNI for true multi-interface networking (no more Docker bridge issues!)
- **Integrates with CNCF Stack**: Works seamlessly with Istio, Rook-Ceph, Prometheus, Grafana
- **Provides Namespace Isolation**: Each topology gets its own namespace for security and resource isolation

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        ASI Platform                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │    Wizard    │  │Control Center│  │   Topology   │          │
│  │     Pod      │  │     Pod      │  │  Viewer Pod  │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              ASI Controller (This Project)              │   │
│  │  Watches AgentTopology CRs → Creates Resources          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │        Namespace: topology-gre-external-peering         │   │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐        │   │
│  │  │Edge Router │  │Core Router │  │ Internal   │        │   │
│  │  │   Pod      │  │   Pod      │  │  Router Pod│        │   │
│  │  │ (StatefulSet)  (StatefulSet)  (StatefulSet) │        │   │
│  │  │  - OSPF    │  │  - OSPF    │  │  - OSPF    │        │   │
│  │  │  - Claude  │  │  - BGP     │  │  - Claude  │        │   │
│  │  │  - Dashboard│  │  - Claude  │  │  - Dashboard│        │   │
│  │  └────────────┘  └────────────┘  └────────────┘        │   │
│  │           ↕             ↕             ↕                  │   │
│  │      [NetworkAttachmentDefinition (Multus CNI)]        │   │
│  │      fd00:0:1::/64   fd00:0:2::/64                     │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │         Observability Stack (Separate Namespace)        │   │
│  │   Prometheus | Grafana | Loki | Jaeger | Kiali         │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## Key Features

### 1. Declarative Topology Management
Define your entire network topology in YAML:

```yaml
apiVersion: asi.asi.anthropic.com/v1alpha1
kind: AgentTopology
metadata:
  name: my-network
spec:
  agents:
  - name: edge-router
    protocols:
    - type: ospf
      config:
        area: "0.0.0.0"
        routerId: "10.255.255.1"
    interfaces:
    - name: eth0
      type: ethernet
      addresses: [10.0.1.1/30]
    llm:
      model: claude-sonnet-4
      profile: "Senior network engineer"
  links:
  - name: edge-core
    endpoints:
    - agent: edge-router
      interface: eth0
    - agent: core-router
      interface: eth0
    subnet: fd00:0:1::/64
```

### 2. Namespace-Per-Topology Isolation
Each topology is deployed in its own namespace (e.g., `topology-my-network`), providing:
- Resource isolation and quotas
- Network policy enforcement
- Independent lifecycle management
- Easy cleanup (delete namespace = delete topology)

### 3. True Network Interface Isolation
Uses Multus CNI to create true point-to-point links:
- No more Docker bridge multicast leakage
- Each link gets its own L2 domain
- OSPF, BGP, and IS-IS work exactly like on real routers

### 4. Cloud-Native Storage
Integrates with Rook-Ceph for persistent storage:
- Agent state (LSDB, RIB, FIB)
- Test results and logs
- Configuration history

### 5. Service Mesh Integration
Istio service mesh on the agent overlay network (fd00::/64):
- Automatic mTLS between agents
- Distributed tracing with Jaeger
- Traffic management and observability
- **Note**: Istio is NOT used on the underlay K8s infrastructure

## Getting Started

### Prerequisites

- Go 1.23+
- Kubernetes 1.35+ cluster
- kubectl configured
- Docker for building images
- (Optional) Multus CNI for multi-interface networking
- (Optional) Rook-Ceph for persistent storage
- (Optional) Istio for service mesh

### Installation

1. **Install CRDs**:
```bash
make install
```

2. **Deploy the controller**:
```bash
make deploy IMG=localhost:5000/asi-controller:latest
```

3. **Verify deployment**:
```bash
kubectl get pods -n asi-system
kubectl get crd agenttopologies.asi.asi.anthropic.com
```

### Quick Start: Deploy a Sample Topology

1. **Apply the sample**:
```bash
kubectl apply -f config/samples/asi_v1alpha1_agenttopology.yaml
```

2. **Watch the topology being created**:
```bash
kubectl get agenttopology gre-external-peering -w
kubectl get pods -n topology-gre-external-peering
```

3. **Check agent status**:
```bash
kubectl describe agenttopology gre-external-peering
```

4. **Access an agent dashboard**:
```bash
kubectl port-forward -n topology-gre-external-peering svc/edge-router 8080:8080
# Open http://localhost:8080 in browser
```

5. **View logs**:
```bash
kubectl logs -n topology-gre-external-peering edge-router-0 -f
```

## API Reference

### AgentTopology

The primary custom resource for defining network topologies.

**Spec Fields**:
- `agents` ([]AgentSpec): List of network agents
- `links` ([]LinkSpec): Point-to-point links between agents

**Status Fields**:
- `namespace` (string): Kubernetes namespace created for this topology
- `phase` (string): Overall topology phase (Creating, Running, Failed)
- `agentStatuses` ([]AgentStatus): Per-agent status information
- `conditions` ([]Condition): Standard Kubernetes conditions

### AgentSpec

Defines a single network agent.

**Fields**:
- `name` (string): Agent identifier
- `protocols` ([]ProtocolConfig): Routing protocols (OSPF, BGP, IS-IS)
- `interfaces` ([]InterfaceConfig): Network interfaces
- `llm` (LLMConfig): LLM model and configuration
- `mcpServers` ([]string): MCP servers to connect to
- `image` (string): Container image (defaults to `localhost:5000/asi-agent:latest`)
- `resources` (ResourceRequirements): CPU/memory requests and limits

### ProtocolConfig

**Fields**:
- `type` (string): Protocol type (ospf, bgp, isis)
- `config` (map[string]string): Protocol-specific configuration
  - OSPF: area, routerId, helloInterval, deadInterval
  - BGP: asn, routerId, neighbors
  - IS-IS: level, areaAddress

### InterfaceConfig

**Fields**:
- `name` (string): Interface name (eth0, eth1, lo)
- `type` (string): Interface type (ethernet, loopback)
- `addresses` ([]string): IP addresses (CIDR notation)
- `mtu` (int32): MTU (576-9216)

### LinkSpec

**Fields**:
- `name` (string): Link identifier
- `endpoints` ([]LinkEndpoint): Two agent interfaces
- `subnet` (string): IPv6 subnet for SLAAC
- `mtu` (int32): Link MTU

## Development

### Build and Run Locally

```bash
# Generate manifests and deepcopy code
make generate manifests

# Build the controller binary
make build

# Run controller locally (connects to kubectl context)
make run
```

### Testing

```bash
# Run unit tests
make test

# Run integration tests (requires K8s cluster)
make test-integration
```

### Building Docker Image

```bash
make docker-build IMG=localhost:5000/asi-controller:latest
make docker-push IMG=localhost:5000/asi-controller:latest
```

## Roadmap

- [x] Core CRD and reconciler
- [x] Namespace-per-topology isolation
- [x] StatefulSet and Service creation
- [x] ConfigMap-based agent configuration
- [x] PersistentVolumeClaim integration
- [ ] NetworkAttachmentDefinition (Multus CNI) integration
- [ ] Istio service mesh automatic enrollment
- [ ] Prometheus ServiceMonitor generation
- [ ] Webhook validation for topology configs
- [ ] Topology graph visualization API
- [ ] Multi-cluster federation

## Comparison: Docker vs Kubernetes

| Feature | Docker (Old) | Kubernetes (New) |
|---------|-------------|------------------|
| **Network Isolation** | Shared bridge, multicast leakage | Multus CNI, true L2 isolation |
| **Interface Binding** | INADDR_ANY conflicts | Per-pod network namespaces |
| **Storage** | Host volumes | Rook-Ceph PVCs |
| **Scaling** | Manual docker-compose | Declarative StatefulSets |
| **Discovery** | Custom logic | Kubernetes DNS |
| **Observability** | Ad-hoc logs | Prometheus, Grafana, Jaeger |
| **Security** | Root containers | RBAC, NetworkPolicies, mTLS |
| **Multi-Tenancy** | Single namespace | Namespace-per-topology |

## Architecture Decisions

### Why Go for the Controller?
- Kubebuilder generates boilerplate
- Native Kubernetes client libraries
- Performance and concurrency
- Python agent code remains unchanged

### Why Namespace-Per-Topology?
- Security isolation
- Resource quotas
- Network policies
- Easy cleanup

### Why Multus CNI?
- True multi-interface pods
- Point-to-point link isolation
- Prevents multicast leakage
- Real router behavior

### Why Rook-Ceph?
- Cloud-native storage
- Dynamic PV provisioning
- High availability
- Integrates with K8s

### Why Istio (Overlay Only)?
- mTLS between agents
- Distributed tracing
- Traffic telemetry
- NOT used on K8s underlay (avoid complexity)

## Troubleshooting

### Topology stuck in "Creating"
```bash
kubectl describe agenttopology <name>
kubectl logs -n asi-system deployment/asi-controller-manager
```

### Agent pod not starting
```bash
kubectl describe pod -n topology-<name> <agent>-0
kubectl logs -n topology-<name> <agent>-0
```

### No OSPF adjacencies forming
- Check if Multus CNI is installed
- Verify NetworkAttachmentDefinitions are created
- Inspect pod network interfaces: `kubectl exec -n topology-<name> <agent>-0 -- ip addr`

## Contributing

This project is part of the Won't You Be My Neighbor ASI platform. Contributions are welcome!

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## License

Copyright 2026.

Licensed under the Apache License, Version 2.0.

---

**Built with [Kubebuilder](https://book.kubebuilder.io/)**
