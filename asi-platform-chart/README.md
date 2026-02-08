# ASI Platform Helm Chart

This Helm chart deploys the complete Agentic Software Infrastructure (ASI) platform to Kubernetes, including:

- **ASI Controller**: Kubernetes operator that manages AgentTopology custom resources
- **Wizard Service**: Web UI for building network topologies
- **Agent Image**: Network agents with OSPF/BGP/IS-IS and Claude AI integration
- **Observability Stack** (optional): Prometheus, Grafana, Loki, Jaeger

## Prerequisites

- Kubernetes 1.25+
- Helm 3.8+
- (Optional) Multus CNI for multi-interface networking
- (Optional) Rook-Ceph for persistent storage
- (Optional) Istio service mesh

## Installation

### Quick Start

```bash
# Add the ASI Helm repository (when published)
# helm repo add asi https://charts.asi.anthropic.com
# helm repo update

# Install with default values
helm install asi-platform asi/asi-platform \
  --create-namespace \
  --namespace asi-system

# Check deployment
kubectl get pods -n asi-system
kubectl get crd agenttopologies.asi.asi.anthropic.com
```

### Install from Local Chart

```bash
# From the project root
cd asi-platform-chart

# Install
helm install asi-platform . \
  --create-namespace \
  --namespace asi-system

# Upgrade
helm upgrade asi-platform . -n asi-system

# Uninstall
helm uninstall asi-platform -n asi-system
```

## Configuration

### Values File

The chart is highly configurable via `values.yaml`. Key sections:

#### Global Settings

```yaml
global:
  imageRegistry: localhost:5000  # Your container registry
  imagePullPolicy: Always
```

#### ASI Controller

```yaml
controller:
  enabled: true
  replicaCount: 1
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
```

#### Wizard Service

```yaml
wizard:
  enabled: true
  service:
    type: LoadBalancer  # Or NodePort, ClusterIP
    port: 80
  ingress:
    enabled: true
    hosts:
      - host: wizard.asi.example.com
```

#### Agent Defaults

```yaml
agent:
  image:
    repository: asi-agent
    tag: latest
  defaultResources:
    requests:
      cpu: 500m
      memory: 512Mi
```

### Custom Values

Create a custom values file:

```yaml
# my-values.yaml
global:
  imageRegistry: gcr.io/my-project

wizard:
  service:
    type: LoadBalancer
  ingress:
    enabled: true
    hosts:
      - host: wizard.asi.mycompany.com

networking:
  multus:
    enabled: true
  istio:
    enabled: true

observability:
  prometheus:
    enabled: true
  grafana:
    enabled: true
```

Install with custom values:

```bash
helm install asi-platform . -f my-values.yaml -n asi-system
```

## Usage

### Access the Wizard

After installation, get the wizard URL:

```bash
# If using LoadBalancer
kubectl get svc asi-platform-wizard -n asi-system
# Access via EXTERNAL-IP

# If using port-forward
kubectl port-forward -n asi-system svc/asi-platform-wizard 8000:80
# Open http://localhost:8000
```

### Create a Topology

1. Open the wizard UI
2. Follow the multi-step wizard to configure agents, links, and LLM settings
3. Launch the topology
4. Verify deployment:

```bash
# List topologies
kubectl get agenttopology

# Check topology status
kubectl describe agenttopology my-topology

# View agent pods
kubectl get pods -n topology-my-topology

# Access agent dashboard
kubectl port-forward -n topology-my-topology my-agent-0 8080:8080
```

### Delete a Topology

```bash
# Via wizard UI (recommended)
# OR via kubectl
kubectl delete agenttopology my-topology

# The controller will automatically clean up the namespace and all resources
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Helm Chart: asi-platform                 │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  Namespace: asi-system                                       │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  ASI Controller (Deployment)                         │  │
│  │  - Watches AgentTopology CRs                         │  │
│  │  - Creates namespaces, StatefulSets, Services        │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Wizard Service (Deployment + Service/Ingress)      │  │
│  │  - Web UI for building topologies                    │  │
│  │  - Creates AgentTopology CRs via K8s API            │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                               │
│  Namespace: topology-* (created by controller)              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Agent Pods (StatefulSets)                           │  │
│  │  - OSPF/BGP/IS-IS protocols                          │  │
│  │  - Claude AI integration                              │  │
│  │  - Individual dashboards                              │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## Advanced Configuration

### Enable Multus CNI

```yaml
networking:
  multus:
    enabled: true
```

Requires Multus CNI to be installed in the cluster.

### Enable Istio Service Mesh

```yaml
networking:
  istio:
    enabled: true
```

Istio is enabled ONLY on agent overlay networks (fd00::/64), NOT on Kubernetes infrastructure.

### Enable Observability Stack

```yaml
observability:
  prometheus:
    enabled: true
  grafana:
    enabled: true
    adminPassword: "my-secure-password"
  jaeger:
    enabled: true
```

### Enable Rook-Ceph Storage

```yaml
storage:
  rook:
    enabled: true
```

Requires Rook-Ceph to be installed in the cluster.

## Upgrading

```bash
# Upgrade to new chart version
helm upgrade asi-platform . -n asi-system

# Upgrade with new values
helm upgrade asi-platform . -f my-values.yaml -n asi-system

# View upgrade history
helm history asi-platform -n asi-system

# Rollback
helm rollback asi-platform <revision> -n asi-system
```

## Uninstallation

```bash
# Uninstall the chart
helm uninstall asi-platform -n asi-system

# CRDs are kept by default (to preserve data)
# To remove CRDs:
kubectl delete crd agenttopologies.asi.asi.anthropic.com

# Remove all topology namespaces
kubectl delete ns -l asi.anthropic.com/topology
```

## Troubleshooting

### Controller not starting

```bash
kubectl describe pod -n asi-system -l app=asi-controller
kubectl logs -n asi-system -l app=asi-controller
```

Common issues:
- CRD not installed: `helm install` with `crds.install: true`
- RBAC permissions: Check ClusterRole bindings
- Image pull errors: Verify `global.imageRegistry`

### Wizard cannot create topologies

```bash
kubectl logs -n asi-system -l app=asi-wizard
```

Common issues:
- No permissions: Check wizard ServiceAccount RBAC
- CRD not found: Install CRDs
- Kubernetes API unreachable: Check service account token

### Agent pods not starting

```bash
# Get topology status
kubectl describe agenttopology <name>

# Check agent pod
kubectl describe pod -n topology-<name> <agent>-0
kubectl logs -n topology-<name> <agent>-0
```

Common issues:
- Image pull errors: Check agent image configuration
- Resource limits: Increase `agent.defaultResources`
- Storage issues: Check PVC status, verify storage class exists

## Development

### Template Testing

```bash
# Render templates locally
helm template asi-platform . -f values.yaml

# Dry run
helm install asi-platform . --dry-run --debug -n asi-system

# Lint chart
helm lint .
```

### Package Chart

```bash
helm package .
# Creates asi-platform-2.0.0.tgz
```

## Support

- GitHub Issues: https://github.com/anthropics/wontyoubemyneighbor/issues
- Documentation: https://github.com/anthropics/wontyoubemyneighbor/tree/main/docs

## License

Copyright 2026. Licensed under Apache License 2.0.
