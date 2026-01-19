# Quick Start: Ralph Agentic Network Router

Complete implementation of the agentic LLM interface for wontyoubemyneighbor is now merged to main!

## ✅ What's Complete

- **Multi-provider LLM Support**: OpenAI GPT-4, Anthropic Claude Sonnet 4, Google Gemini Pro
- **Natural Language Interface**: Ask questions about your network in plain English
- **Decision Engine**: Explainable AI with route selection, anomaly detection, recommendations
- **Safe Actions**: Human-in-the-loop approval workflow for network changes
- **Multi-Agent Coordination**: Gossip protocol + distributed consensus voting
- **Protocol Integration**: Native OSPF and BGP connectors
- **REST API**: 20+ endpoints with auto-generated OpenAPI docs
- **Chat Client**: Interactive `mrrogers.py` client
- **Tests**: 42 passing tests covering all major components
- **Docker Support**: Full containerized deployment

## 🚀 How to Launch

### 1. Launch the Agent with LLM Interface

Start wontyoubemyneighbor.py with your routing protocol AND the agentic interface:

```bash
# Example: OSPF + BGP + OpenAI interface
python3 wontyoubemyneighbor.py \
  --router-id 10.0.1.1 \
  --area 0.0.0.0 \
  --interface eth0 \
  --bgp-local-as 65001 \
  --bgp-peer 192.0.2.2 \
  --bgp-peer-as 65002 \
  --agentic-api \
  --openai-key sk-YOUR-KEY-HERE

# Example: Just BGP + Claude interface
python3 wontyoubemyneighbor.py \
  --router-id 10.0.1.1 \
  --bgp-local-as 65001 \
  --bgp-peer 192.0.2.2 \
  --bgp-peer-as 65001 \
  --bgp-passive 192.0.2.2 \
  --agentic-api \
  --claude-key sk-ant-YOUR-KEY-HERE

# Example: OSPF + Multiple LLM providers (with fallback)
python3 wontyoubemyneighbor.py \
  --router-id 10.255.255.99 \
  --area 0.0.0.0 \
  --interface eth0 \
  --agentic-api \
  --openai-key sk-YOUR-KEY-HERE \
  --claude-key sk-ant-YOUR-KEY-HERE \
  --gemini-key YOUR-GEMINI-KEY
```

The agent will start with:
- Your routing protocols (OSPF/BGP) running natively
- REST API server at http://localhost:8080
- API documentation at http://localhost:8080/docs

### 2. Chat with the Agent using Mr. Rogers

After the agent is running, launch the chat client in a separate terminal:

```bash
# Interactive mode
python3 mrrogers.py

# Connect to specific host/port
python3 mrrogers.py --host 192.168.1.100 --port 8080

# Batch mode for demos
python3 mrrogers.py --batch "show ospf neighbors" "what is my network status"
```

## 💬 Example Queries

Once connected via `mrrogers.py`, you can ask natural language questions:

```
You: Show me my OSPF neighbors
Ralph: OSPF Neighbors:
  • Neighbor 2.2.2.2
    State: Full
    Address: 192.168.1.2
```

```
You: Why is traffic to 10.0.0.0/24 going through R2?
Ralph: Selected route via R2 (192.168.1.3)

Decision factors:
- AS Path length: 2 (vs R1: 3)
- MED: 0 (vs R1: 50)
- Local Preference: 120 (vs R1: 100)
```

```
You: Are there any network issues?
Ralph: Detected 1 anomaly:

1. [HIGH] neighbor_flapping
   Neighbor 3.3.3.3 has flapped 12 times
   Recommendation: Check interface stability and MTU settings
```

## 🔧 Available Flags

### Agentic Interface Flags

```bash
--agentic-api                # Enable agentic LLM interface API server
--agentic-api-host HOST      # API host (default: 0.0.0.0)
--agentic-api-port PORT      # API port (default: 8080)
--openai-key KEY             # OpenAI API key for GPT-4
--claude-key KEY             # Anthropic Claude API key
--gemini-key KEY             # Google Gemini API key
--autonomous-mode            # Enable autonomous actions (dangerous!)
--ralph-id ID                # Ralph instance ID (default: based on router-id)
```

### Example Launch Commands

```bash
# OSPF with OpenAI
python3 wontyoubemyneighbor.py \
  --router-id 10.0.1.1 \
  --area 0.0.0.0 \
  --interface eth0 \
  --agentic-api \
  --openai-key $OPENAI_API_KEY

# BGP with Claude
python3 wontyoubemyneighbor.py \
  --router-id 192.0.2.1 \
  --bgp-local-as 65001 \
  --bgp-peer 192.0.2.2 \
  --bgp-peer-as 65002 \
  --agentic-api \
  --claude-key $ANTHROPIC_API_KEY

# OSPF + BGP + Multiple LLMs
python3 wontyoubemyneighbor.py \
  --router-id 10.0.1.1 \
  --area 0.0.0.0 \
  --interface eth0 \
  --bgp-local-as 65001 \
  --bgp-peer 192.0.2.2 \
  --bgp-peer-as 65002 \
  --agentic-api \
  --openai-key $OPENAI_API_KEY \
  --claude-key $ANTHROPIC_API_KEY \
  --autonomous-mode
```

## 📚 Documentation

- **Full README**: `wontyoubemyneighbor/agentic/README.md`
- **Deployment Guide**: `DEPLOYMENT.md`
- **Mission Status**: `MISSION_STATUS.md` (shows 100% spec compliance)
- **API Documentation**: http://localhost:8080/docs (when running)

## 🧪 Run Tests

```bash
cd wontyoubemyneighbor/agentic/tests
./run_tests.sh
```

All 42 tests should pass.

## 🐳 Docker Deployment

```bash
# Build and run API server
docker-compose -f docker-compose.agentic.yml up ralph-api

# Run demo
docker-compose -f docker-compose.agentic.yml --profile demo up ralph-demo
```

## 🎯 Key Features

### 1. Natural Language Understanding
Ask questions in plain English and get structured responses:
- "Show me my OSPF neighbors"
- "What is the route to 10.0.0.0/24?"
- "Are there any network issues?"

### 2. Explainable Decisions
Every routing decision comes with rationale:
- Why a specific route was selected
- What alternatives were considered
- Confidence scores for recommendations

### 3. Safe Actions
Network changes require approval by default:
- Human-in-the-loop workflow
- Configurable safety constraints
- Audit logging of all actions

### 4. Multi-Agent Coordination
Multiple Ralph instances can coordinate:
- Gossip protocol for state sharing
- Distributed consensus voting for critical actions
- No single point of failure

### 5. Protocol-Native Integration
Ralph participates in routing protocols:
- Receives OSPF LSAs in real-time
- Maintains BGP sessions
- Can execute routing changes when approved

## 📝 Example Workflow

1. **Start the router with agentic interface:**
```bash
python3 wontyoubemyneighbor.py \
  --router-id 10.0.1.1 \
  --bgp-local-as 65001 \
  --bgp-peer 192.0.2.2 \
  --bgp-peer-as 65001 \
  --agentic-api \
  --claude-key $ANTHROPIC_API_KEY
```

2. **Chat with the agent:**
```bash
python3 mrrogers.py
```

3. **Ask questions:**
```
You: Show me my BGP peers
Ralph: BGP Peers:
  • Peer 192.0.2.2 (AS 65001)
    State: Established
    Uptime: 00:15:23
    Routes Received: 15
```

4. **Get explanations:**
```
You: Why is traffic to 10.0.0.0/24 using peer 192.0.2.2?
Ralph: [Detailed explanation with AS path, MED, local preference, etc.]
```

5. **Take actions (with approval):**
```
You: Increase the local preference for routes from 192.0.2.2 to 150
Ralph: Action requires approval. Details: [...]
  Approve? (yes/no)
```

## 🎉 Success

You now have a fully functional agentic network router that:
- Runs OSPF and/or BGP natively
- Understands natural language queries
- Explains routing decisions
- Can take safe actions with your approval
- Coordinates with other Ralph instances

**Ralph is ready to be your network's neighbor!** 🏘️🤖

---

For more details, see:
- `wontyoubemyneighbor/agentic/README.md`
- `DEPLOYMENT.md`
- `MISSION_STATUS.md`
