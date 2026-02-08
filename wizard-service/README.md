# ASI Wizard Service

**Kubernetes-Native Network Topology Builder**

The ASI Wizard Service is a standalone web application that provides a graphical interface for building and deploying network agent topologies to Kubernetes. It replaces the Docker-based wizard with a cloud-native implementation that creates `AgentTopology` custom resources.

## Overview

This service:
- Provides a multi-step wizard UI for building network topologies
- Translates user inputs into Kubernetes `AgentTopology` CRs
- Manages topology lifecycle (create, list, delete)
- Works seamlessly with the ASI Controller

## Features

### 1. Multi-Step Wizard
- **Step 1**: Topology name and basic settings
- **Step 2**: MCP server selection (Prometheus, filesystem, etc.)
- **Step 3**: Agent builder (name, protocols, interfaces, LLM profile)
- **Step 4**: Topology and links (point-to-point connections)
- **Step 5**: LLM configuration (model, API keys)

### 2. Kubernetes Integration
- Uses Kubernetes Python client to create AgentTopology CRs
- Supports both in-cluster (ServiceAccount) and out-of-cluster (kubeconfig) auth
- Real-time topology status tracking
- YAML export of generated CRs

### 3. Topology Management
- List all deployed topologies
- View topology status and agent health
- Delete topologies
- Download AgentTopology YAML

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     User's Browser                          │
│                  (Wizard UI - React/JS)                     │
└─────────────────────┬───────────────────────────────────────┘
                      │ HTTP/JSON
                      ↓
┌─────────────────────────────────────────────────────────────┐
│               Wizard Service (This Service)                 │
│  ┌────────────────────────────────────────────────────┐    │
│  │  FastAPI Application                                │    │
│  │  - Session management                               │    │
│  │  - Wizard step validation                           │    │
│  │  - AgentTopology CR builder                         │    │
│  └────────────────────────────────────────────────────┘    │
│                      │                                       │
│                      │ Kubernetes Python Client             │
│                      ↓                                       │
│  ┌────────────────────────────────────────────────────┐    │
│  │  Create AgentTopology Custom Resource              │    │
│  │  apiVersion: asi.asi.anthropic.com/v1alpha1        │    │
│  │  kind: AgentTopology                                │    │
│  │  spec: { agents: [...], links: [...] }            │    │
│  └────────────────────────────────────────────────────┘    │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ↓ POST to Kubernetes API
┌─────────────────────────────────────────────────────────────┐
│                  Kubernetes API Server                      │
│         (Stores AgentTopology in etcd)                      │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ↓ Watches for AgentTopology CRs
┌─────────────────────────────────────────────────────────────┐
│                    ASI Controller                           │
│  Creates: Namespaces, StatefulSets, Services, etc.         │
└─────────────────────────────────────────────────────────────┘
```

## Installation

### Prerequisites

- Kubernetes cluster with ASI Controller installed
- `AgentTopology` CRD deployed (`kubectl apply -f config/crd/bases/`)
- Docker for building images

### Build and Deploy

1. **Build the image**:
```bash
docker build -t localhost:5000/asi-wizard:latest .
docker push localhost:5000/asi-wizard:latest
```

2. **Create Kubernetes resources**:

```yaml
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: asi-wizard
  namespace: asi-system

---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: asi-wizard
rules:
- apiGroups: ["asi.asi.anthropic.com"]
  resources: ["agenttopologies"]
  verbs: ["create", "get", "list", "watch", "delete"]
- apiGroups: [""]
  resources: ["namespaces"]
  verbs: ["list"]

---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: asi-wizard
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: asi-wizard
subjects:
- kind: ServiceAccount
  name: asi-wizard
  namespace: asi-system

---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: asi-wizard
  namespace: asi-system
spec:
  replicas: 1
  selector:
    matchLabels:
      app: asi-wizard
  template:
    metadata:
      labels:
        app: asi-wizard
    spec:
      serviceAccountName: asi-wizard
      containers:
      - name: wizard
        image: localhost:5000/asi-wizard:latest
        ports:
        - containerPort: 8000
        livenessProbe:
          httpGet:
            path: /api/wizard/health
            port: 8000
          initialDelaySeconds: 10
        readinessProbe:
          httpGet:
            path: /api/wizard/health
            port: 8000
          initialDelaySeconds: 5

---
apiVersion: v1
kind: Service
metadata:
  name: asi-wizard
  namespace: asi-system
spec:
  selector:
    app: asi-wizard
  ports:
  - port: 80
    targetPort: 8000
  type: LoadBalancer
```

3. **Apply the resources**:
```bash
kubectl apply -f wizard-deployment.yaml
```

4. **Access the wizard**:
```bash
kubectl port-forward -n asi-system svc/asi-wizard 8000:80
# Open http://localhost:8000
```

## API Reference

### Session Management

**Initialize Session**
```http
POST /api/wizard/session/{session_id}/init
```

**Get Session State**
```http
GET /api/wizard/session/{session_id}
```

**Update Wizard Step**
```http
POST /api/wizard/session/{session_id}/step/{step}
Content-Type: application/json

{
  "topology_name": "my-network",
  "agents": [...],
  "links": [...]
}
```

### Topology Management

**Launch Topology**
```http
POST /api/wizard/session/{session_id}/launch
Content-Type: application/json

{
  "topology_name": "my-network",
  "api_keys": {
    "claude": "sk-ant-..."
  }
}
```

**List Topologies**
```http
GET /api/wizard/topologies
```

**Get Topology Status**
```http
GET /api/wizard/topologies/{topology_name}
```

**Delete Topology**
```http
DELETE /api/wizard/topologies/{topology_name}
```

**Export Topology YAML**
```http
GET /api/wizard/topologies/{topology_name}/yaml
```

### Health Check

```http
GET /api/wizard/health
GET /api/wizard/check-k8s
```

## Configuration Translation

### Wizard Input → AgentTopology CR

The wizard translates user inputs into Kubernetes-native AgentTopology CRs:

**Wizard Input**:
```json
{
  "agents": [
    {
      "id": "edge-router",
      "name": "Edge Router",
      "router_id": "10.255.255.1",
      "protocol": "ospf",
      "interfaces": [
        {"name": "eth0", "type": "ethernet", "addresses": ["10.0.1.1/30"]}
      ]
    }
  ],
  "links": [
    {
      "id": "edge-core",
      "agent1_id": "edge-router",
      "interface1": "eth0",
      "agent2_id": "core-router",
      "interface2": "eth0"
    }
  ]
}
```

**Generated AgentTopology CR**:
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
        routerId: "10.255.255.1"
    interfaces:
    - name: eth0
      type: ethernet
      addresses:
      - 10.0.1.1/30
    llm:
      model: claude-sonnet-4
      profile: "Network agent: Edge Router"
  links:
  - name: edge-core
    endpoints:
    - agent: edge-router
      interface: eth0
    - agent: core-router
      interface: eth0
    subnet: fd00:0:1::/64
```

## Development

### Run Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Run the service (will use kubeconfig)
python app.py
```

### Run in Kubernetes

```bash
# Build and push
docker build -t localhost:5000/asi-wizard:latest .
docker push localhost:5000/asi-wizard:latest

# Deploy
kubectl apply -f wizard-deployment.yaml
```

## Comparison: Old vs New

| Feature | Docker Wizard (Old) | Kubernetes Wizard (New) |
|---------|---------------------|-------------------------|
| **Deployment** | docker-compose up | kubectl apply |
| **Orchestration** | DockerManager | Kubernetes API |
| **Output** | Docker containers | AgentTopology CRs |
| **State** | In-memory + files | Kubernetes etcd |
| **Scaling** | Single instance | K8s Deployment (replicas) |
| **Auth** | N/A | ServiceAccount + RBAC |
| **Discovery** | Docker API | Kubernetes API |

## Troubleshooting

### "Kubernetes API error"
- Check that ASI Controller and CRDs are installed: `kubectl get crd agenttopologies.asi.asi.anthropic.com`
- Verify wizard has correct RBAC permissions: `kubectl get clusterrolebinding asi-wizard`

### "Topology already exists"
- List existing topologies: `kubectl get agenttopology`
- Delete conflicting topology: `kubectl delete agenttopology <name>`

### "Session not found"
- Sessions are stored in memory and cleared after launch
- Each browser tab should use a unique session ID (generated by UI)

## Security

- **Non-root container**: Runs as user `wizard` (UID 1000)
- **RBAC restricted**: Can only create/manage AgentTopology CRs, not other resources
- **No elevated privileges**: No NET_ADMIN or host access required
- **API key handling**: LLM API keys passed to agents via Kubernetes Secrets (TODO)

## Roadmap

- [ ] Copy static files from original webui/
- [ ] Integrate with LLM for natural language topology creation
- [ ] Topology templates library
- [ ] Topology validation (prevent invalid link configs)
- [ ] Multi-topology comparison view
- [ ] Integration with Control Center service

## License

Copyright 2026. Licensed under Apache License 2.0.
