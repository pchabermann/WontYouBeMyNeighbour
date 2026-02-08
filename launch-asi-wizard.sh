#!/bin/bash
#===============================================================================
# ASI Network Wizard Launcher
#
# This script sets up the complete ASI platform and launches the wizard
# to build and deploy network topologies with GRE external peering!
#
# Usage: ./launch-asi-wizard.sh [options]
#   --cluster-name <name> : Kubernetes cluster name (default: asi-test)
#   --template <name>     : Deploy a pre-built template (e.g., gre-external-peering)
#   --wizard-only         : Just launch wizard, skip setup
#   --help                : Show this help message
#===============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Default Configuration
CLUSTER_NAME=""
WIZARD_PORT=8080

# Banner
echo -e "${BLUE}"
cat << "EOF"
╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║       ASI Network Wizard - Agentic Simulation Infrastructure  ║
║                                                               ║
║   Build and deploy intelligent network topologies            ║
║   with OSPF, BGP, GRE tunnels, and external connectivity     ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
EOF
echo -e "${NC}"

# Parse arguments
TEMPLATE_NAME=""
WIZARD_ONLY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --cluster-name)
            CLUSTER_NAME="$2"
            shift 2
            ;;
        --template)
            TEMPLATE_NAME="$2"
            shift 2
            ;;
        --wizard-only)
            WIZARD_ONLY=true
            shift
            ;;
        --help)
            echo "Usage: $0 [options]"
            echo ""
            echo "Options:"
            echo "  --cluster-name <name>  Kubernetes cluster name (default: asi-test)"
            echo "  --template <name>      Deploy a template (gre-external-peering, basic-ospf, etc.)"
            echo "  --wizard-only          Skip setup, just launch wizard"
            echo "  --help                 Show this help message"
            echo ""
            echo "Examples:"
            echo "  # Full setup with wizard UI (will prompt for cluster name)"
            echo "  $0"
            echo ""
            echo "  # Specify cluster name on command line"
            echo "  $0 --cluster-name my-asi-cluster"
            echo ""
            echo "  # Quick deploy with GRE template"
            echo "  $0 --template gre-external-peering"
            echo ""
            echo "  # Just launch wizard (if already set up)"
            echo "  $0 --wizard-only"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

#===============================================================================
# Cluster Name Prompt
#===============================================================================

# If wizard-only mode, try to detect current cluster
if [ "$WIZARD_ONLY" = true ]; then
    CURRENT_CONTEXT=$(kubectl config current-context 2>/dev/null || echo "")
    if [[ "$CURRENT_CONTEXT" == kind-* ]]; then
        CLUSTER_NAME="${CURRENT_CONTEXT#kind-}"
        echo -e "${GREEN}Using current cluster: ${CLUSTER_NAME}${NC}"
        echo ""
    fi
fi

# Prompt for cluster name if not set
if [ -z "$CLUSTER_NAME" ]; then
    echo -e "${CYAN}════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}  Kubernetes Cluster Configuration${NC}"
    echo -e "${CYAN}════════════════════════════════════════════════════════${NC}"
    echo ""

    # Show existing kind clusters if any
    EXISTING_CLUSTERS=$(kind get clusters 2>/dev/null || echo "")
    if [ -n "$EXISTING_CLUSTERS" ]; then
        echo -e "${YELLOW}📋 Existing kind clusters:${NC}"
        echo "$EXISTING_CLUSTERS" | sed 's/^/  - /'
        echo ""
    fi

    # Prompt for cluster name
    echo -e "${YELLOW}Enter Kubernetes cluster name (default: asi-test):${NC}"
    read -r -p "> " USER_CLUSTER_NAME

    # Use default if empty
    if [ -z "$USER_CLUSTER_NAME" ]; then
        CLUSTER_NAME="asi-test"
        echo -e "${BLUE}Using default: ${CLUSTER_NAME}${NC}"
    else
        CLUSTER_NAME="$USER_CLUSTER_NAME"
        echo -e "${GREEN}Using cluster: ${CLUSTER_NAME}${NC}"
    fi
    echo ""
fi

#===============================================================================
# Setup Phase (skip if --wizard-only)
#===============================================================================

if [ "$WIZARD_ONLY" = false ]; then
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}  Phase 1: Environment Setup${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
    echo ""

    # Check prerequisites
    echo -e "${YELLOW}🔍 Checking prerequisites...${NC}"

    if ! command -v kubectl &> /dev/null; then
        echo -e "${RED}❌ kubectl not found. Please install kubectl first.${NC}"
        exit 1
    fi
    echo -e "${GREEN}✓ kubectl${NC}"

    if ! command -v docker &> /dev/null; then
        echo -e "${RED}❌ docker not found. Please install Docker first.${NC}"
        exit 1
    fi
    echo -e "${GREEN}✓ docker${NC}"

    if ! command -v kind &> /dev/null; then
        echo -e "${RED}❌ kind not found. Please install kind first.${NC}"
        exit 1
    fi
    echo -e "${GREEN}✓ kind${NC}"

    if ! command -v python3 &> /dev/null; then
        echo -e "${RED}❌ python3 not found. Please install Python 3.${NC}"
        exit 1
    fi
    echo -e "${GREEN}✓ python3${NC}"

    echo ""

    # Create kind cluster
    echo -e "${YELLOW}🚀 Setting up Kubernetes cluster...${NC}"
    if kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
        echo -e "${BLUE}Cluster '${CLUSTER_NAME}' already exists${NC}"
    else
        echo -e "${BLUE}Creating kind cluster '${CLUSTER_NAME}'...${NC}"

        # Check if kind config exists
        if [ -f "wontyoubemyneighbor/templates/kind-config.yaml" ]; then
            kind create cluster --name ${CLUSTER_NAME} --config wontyoubemyneighbor/templates/kind-config.yaml
        else
            kind create cluster --name ${CLUSTER_NAME}
        fi

        echo -e "${GREEN}✓ Cluster created${NC}"
    fi

    # Deploy ASI CRDs
    echo ""
    echo -e "${YELLOW}🎮 Deploying ASI CRDs...${NC}"

    # Create asi-system namespace
    kubectl create namespace asi-system --dry-run=client -o yaml | kubectl apply -f - > /dev/null 2>&1

    # Create LLM API key secret (from local environment if available)
    echo ""
    echo -e "${YELLOW}🔑 Configuring LLM API keys...${NC}"
    SECRET_ARGS=""
    if [ -n "$ANTHROPIC_API_KEY" ]; then
        SECRET_ARGS="${SECRET_ARGS} --from-literal=ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}"
        echo -e "${GREEN}  ✓ ANTHROPIC_API_KEY found${NC}"
    fi
    if [ -n "$OPENAI_API_KEY" ]; then
        SECRET_ARGS="${SECRET_ARGS} --from-literal=OPENAI_API_KEY=${OPENAI_API_KEY}"
        echo -e "${GREEN}  ✓ OPENAI_API_KEY found${NC}"
    fi
    if [ -n "$GOOGLE_API_KEY" ]; then
        SECRET_ARGS="${SECRET_ARGS} --from-literal=GOOGLE_API_KEY=${GOOGLE_API_KEY}"
        echo -e "${GREEN}  ✓ GOOGLE_API_KEY found${NC}"
    fi
    if [ -n "$SECRET_ARGS" ]; then
        kubectl create secret generic llm-api-keys -n asi-system ${SECRET_ARGS} --dry-run=client -o yaml | kubectl apply -f - > /dev/null 2>&1
        echo -e "${GREEN}  ✓ LLM API keys stored in K8s secret${NC}"
    else
        echo -e "${BLUE}  ℹ LLM API keys will be configured in the wizard (Step 4).${NC}"
        echo -e "${BLUE}    Or pre-set ANTHROPIC_API_KEY, OPENAI_API_KEY, or GOOGLE_API_KEY in your shell.${NC}"
    fi

    # Deploy CRDs directly (skip controller build due to Go version issues)
    if kubectl get crd agenttopologies.asi.asi.anthropic.com &> /dev/null; then
        echo -e "${BLUE}ASI CRDs already deployed${NC}"
    else
        echo -e "${BLUE}Installing AgentTopology CRD...${NC}"
        kubectl apply -f asi-controller/config/crd/bases/asi.asi.anthropic.com_agenttopologies.yaml
        echo -e "${GREEN}✓ CRDs deployed${NC}"
    fi

    # Install Multus CNI (required for multi-interface agent networking)
    echo ""
    echo -e "${YELLOW}🔌 Installing Multus CNI...${NC}"
    if kubectl get daemonset -n kube-system kube-multus-ds &> /dev/null; then
        echo -e "${BLUE}Multus CNI already installed${NC}"
    else
        echo -e "${BLUE}Deploying Multus thick daemonset...${NC}"
        kubectl apply -f https://raw.githubusercontent.com/k8snetworkplumbingwg/multus-cni/master/deployments/multus-daemonset-thick.yml > /dev/null 2>&1
        echo -e "${GREEN}✓ Multus CNI deployed${NC}"
    fi

    # Wait for Multus to be ready
    echo -e "${YELLOW}Waiting for Multus CNI to be ready...${NC}"
    kubectl rollout status daemonset/kube-multus-ds -n kube-system --timeout=120s 2>/dev/null || true
    echo -e "${GREEN}✓ Multus CNI ready${NC}"

    # Install CNI bridge plugin into kind node (not included by default)
    echo ""
    echo -e "${YELLOW}🌉 Installing CNI bridge plugin...${NC}"
    CONTROL_PLANE_NODE="${CLUSTER_NAME}-control-plane"
    if docker exec ${CONTROL_PLANE_NODE} test -f /opt/cni/bin/bridge 2>/dev/null; then
        echo -e "${BLUE}CNI bridge plugin already installed${NC}"
    else
        echo -e "${BLUE}Downloading CNI plugins v1.6.2 into kind node...${NC}"
        docker exec ${CONTROL_PLANE_NODE} sh -c \
            'curl -sL https://github.com/containernetworking/plugins/releases/download/v1.6.2/cni-plugins-linux-amd64-v1.6.2.tgz | tar xzf - -C /opt/cni/bin/'
        echo -e "${GREEN}✓ CNI bridge plugin installed${NC}"
    fi

    # Disable bridge-nf-call-iptables so Multus bridge traffic isn't filtered by K8s iptables rules
    echo ""
    echo -e "${YELLOW}🔧 Configuring bridge networking for Multus...${NC}"
    CONTROL_PLANE_NODE="${CLUSTER_NAME}-control-plane"
    docker exec ${CONTROL_PLANE_NODE} sysctl -w net.bridge.bridge-nf-call-iptables=0 > /dev/null 2>&1 && \
        echo -e "${GREEN}✓ bridge-nf-call-iptables disabled (required for Multus L3 connectivity)${NC}" || \
        echo -e "${YELLOW}⚠ Could not disable bridge-nf-call-iptables (may affect Multus connectivity)${NC}"

    echo ""
    echo -e "${GREEN}✅ Environment setup complete!${NC}"
    echo ""
fi

#===============================================================================
# Template Deployment (if --template specified)
#===============================================================================

if [ -n "$TEMPLATE_NAME" ]; then
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}  Phase 2: Deploying Template: ${TEMPLATE_NAME}${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
    echo ""

    TEMPLATE_DIR="wontyoubemyneighbor/templates/topology_templates/${TEMPLATE_NAME}"

    if [ ! -d "$TEMPLATE_DIR" ]; then
        echo -e "${RED}❌ Template not found: ${TEMPLATE_DIR}${NC}"
        echo ""
        echo -e "${YELLOW}Available templates:${NC}"
        ls -1 wontyoubemyneighbor/templates/topology_templates/ | grep -v "\.md$"
        exit 1
    fi

    echo -e "${BLUE}📋 Using template: ${TEMPLATE_NAME}${NC}"
    echo -e "${BLUE}Building agent image...${NC}"

    cd wontyoubemyneighbor
    docker build -t asi-agent:latest . > /dev/null 2>&1
    cd ..

    echo -e "${GREEN}✓ Agent image built${NC}"

    echo -e "${BLUE}Loading agent image into cluster...${NC}"
    kind load docker-image asi-agent:latest --name ${CLUSTER_NAME} > /dev/null 2>&1
    echo -e "${GREEN}✓ Agent image loaded${NC}"

    # Deploy using Python script
    echo -e "${BLUE}Deploying topology...${NC}"
    cd wontyoubemyneighbor
    python3 << EOF
import json
import yaml
from kubernetes import client, config

# Load kubeconfig
config.load_kube_config()
k8s_custom = client.CustomObjectsApi()

# Read template
with open('templates/topology_templates/${TEMPLATE_NAME}/agents.json') as f:
    agents = json.load(f)

with open('templates/topology_templates/${TEMPLATE_NAME}/links.json') as f:
    links = json.load(f)

# Create AgentTopology CR
topology = {
    'apiVersion': 'asi.asi.anthropic.com/v1alpha1',
    'kind': 'AgentTopology',
    'metadata': {
        'name': '${TEMPLATE_NAME}',
        'namespace': 'default'
    },
    'spec': {
        'agents': agents,
        'links': links
    }
}

print("Creating AgentTopology resource...")
try:
    k8s_custom.create_namespaced_custom_object(
        group='asi.asi.anthropic.com',
        version='v1alpha1',
        namespace='default',
        plural='agenttopologies',
        body=topology
    )
    print("✓ Topology created successfully!")
except Exception as e:
    print(f"Error: {e}")
EOF
    cd ..

    echo ""
    echo -e "${GREEN}✅ Template deployed!${NC}"
    echo ""
    echo -e "${YELLOW}📊 Check status with:${NC}"
    echo -e "  kubectl get pods -n topology-${TEMPLATE_NAME}"
    echo ""
    exit 0
fi

#===============================================================================
# Wizard UI Launch
#===============================================================================

echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}  Phase 3: Launching Wizard UI${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo ""

echo -e "${BLUE}🧙 Starting ASI Wizard Service...${NC}"

# Build and load agent image (needed for topology pod deployment)
echo -e "${YELLOW}Building agent image...${NC}"
if [ -f "wontyoubemyneighbor/Dockerfile" ]; then
    docker build -t asi-agent:latest wontyoubemyneighbor/ > /dev/null 2>&1
    echo -e "${GREEN}✓ Agent image built${NC}"

    echo -e "${YELLOW}Loading agent image into cluster...${NC}"
    kind load docker-image asi-agent:latest --name ${CLUSTER_NAME} > /dev/null 2>&1
    echo -e "${GREEN}✓ Agent image loaded into cluster${NC}"
else
    echo -e "${YELLOW}⚠ wontyoubemyneighbor/Dockerfile not found, skipping agent image build${NC}"
fi

# Deploy wizard service
cd wizard-service

# Build and load wizard image
echo -e "${YELLOW}Building wizard image...${NC}"
docker build -t asi-wizard:latest . > /dev/null 2>&1
echo -e "${GREEN}✓ Wizard image built${NC}"

echo -e "${YELLOW}Loading wizard image into cluster...${NC}"
kind load docker-image asi-wizard:latest --name ${CLUSTER_NAME} > /dev/null 2>&1
echo -e "${GREEN}✓ Image loaded into cluster${NC}"

# Deploy to Kubernetes
echo -e "${YELLOW}Deploying wizard service...${NC}"
kubectl apply -f k8s-deployment.yaml > /dev/null 2>&1

# Update deployment to use local image
kubectl set image deployment/asi-wizard wizard=asi-wizard:latest -n asi-system > /dev/null 2>&1
kubectl patch deployment asi-wizard -n asi-system -p '{"spec":{"template":{"spec":{"containers":[{"name":"wizard","imagePullPolicy":"Never"}]}}}}' > /dev/null 2>&1
echo -e "${GREEN}✓ Wizard service deployed${NC}"

# Wait for wizard to be ready
echo -e "${YELLOW}Waiting for wizard to be ready...${NC}"
kubectl wait --for=condition=available --timeout=120s deployment/asi-wizard -n asi-system
echo -e "${GREEN}✓ Wizard service ready${NC}"

cd ..

#===============================================================================
# Build and Deploy Observability Services (Monitor + Topology3D)
#===============================================================================

echo ""
echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}  Phase 4: Deploying Observability Services${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo ""

MONITOR_PORT=8081
TOPO3D_PORT=8082

# --- Build and deploy asi-monitor ---
if [ -d "asi-monitor" ]; then
    echo -e "${YELLOW}Building asi-monitor image...${NC}"
    docker build -t asi-monitor:latest asi-monitor/ > /dev/null 2>&1
    echo -e "${GREEN}✓ Monitor image built${NC}"

    echo -e "${YELLOW}Loading asi-monitor into cluster...${NC}"
    kind load docker-image asi-monitor:latest --name ${CLUSTER_NAME} > /dev/null 2>&1
    echo -e "${GREEN}✓ Monitor image loaded${NC}"

    echo -e "${YELLOW}Deploying monitor service...${NC}"
    kubectl apply -f asi-monitor/k8s-deployment.yaml > /dev/null 2>&1
    echo -e "${GREEN}✓ Monitor service deployed${NC}"
else
    echo -e "${YELLOW}⚠ asi-monitor/ not found, skipping monitor deployment${NC}"
fi

# --- Build and deploy asi-topology3d ---
if [ -d "asi-topology3d" ]; then
    echo -e "${YELLOW}Building asi-topology3d image...${NC}"
    docker build -t asi-topology3d:latest asi-topology3d/ > /dev/null 2>&1
    echo -e "${GREEN}✓ Topology3D image built${NC}"

    echo -e "${YELLOW}Loading asi-topology3d into cluster...${NC}"
    kind load docker-image asi-topology3d:latest --name ${CLUSTER_NAME} > /dev/null 2>&1
    echo -e "${GREEN}✓ Topology3D image loaded${NC}"

    echo -e "${YELLOW}Deploying topology3d service...${NC}"
    kubectl apply -f asi-topology3d/k8s-deployment.yaml > /dev/null 2>&1
    echo -e "${GREEN}✓ Topology3D service deployed${NC}"
else
    echo -e "${YELLOW}⚠ asi-topology3d/ not found, skipping topology3d deployment${NC}"
fi

# Wait for observability services
echo ""
echo -e "${YELLOW}Waiting for observability services to be ready...${NC}"
kubectl wait --for=condition=available --timeout=120s deployment/asi-monitor -n asi-system 2>/dev/null && \
    echo -e "${GREEN}✓ Monitor service ready${NC}" || \
    echo -e "${YELLOW}⚠ Monitor service not ready${NC}"
kubectl wait --for=condition=available --timeout=120s deployment/asi-topology3d -n asi-system 2>/dev/null && \
    echo -e "${GREEN}✓ Topology3D service ready${NC}" || \
    echo -e "${YELLOW}⚠ Topology3D service not ready${NC}"

#===============================================================================
# Port-Forward All Services
#===============================================================================

echo ""
echo -e "${YELLOW}Setting up port-forwards...${NC}"

kubectl port-forward -n asi-system svc/asi-wizard ${WIZARD_PORT}:80 &>/dev/null &
PF_WIZARD=$!

kubectl port-forward -n asi-system svc/asi-monitor ${MONITOR_PORT}:80 &>/dev/null &
PF_MONITOR=$!

kubectl port-forward -n asi-system svc/asi-topology3d ${TOPO3D_PORT}:80 &>/dev/null &
PF_TOPO3D=$!

sleep 3

echo ""
echo -e "${GREEN}✅ All services running!${NC}"
echo ""
echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  🧙 Wizard:      ${CYAN}http://localhost:${WIZARD_PORT}/static/wizard.html${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${BLUE}  After deploying a topology via the wizard:${NC}"
echo -e "${BLUE}  📊 Monitor:     ${NC}http://localhost:${MONITOR_PORT}/"
echo -e "${BLUE}  🌐 Topology3D:  ${NC}http://localhost:${TOPO3D_PORT}/"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop all services${NC}"
echo ""

# Keep all port-forwards running
wait $PF_WIZARD $PF_MONITOR $PF_TOPO3D
