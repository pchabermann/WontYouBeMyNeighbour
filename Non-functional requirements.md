# ASI Platform - Non-Functional Requirements & Scale Analysis

## 1. Development Environment (Reference Baseline)

All measurements in this document were taken on the following home workstation running the full ASI platform inside a kind (Kubernetes in Docker) cluster:

| Component | Specification |
|---|---|
| CPU | Intel Core i7-10700KF @ 3.80 GHz (8 cores / 16 threads) |
| RAM | 12 GB DDR4 (11.68 GiB available to Docker) |
| Storage | 1 TB SSD (676 GB free) |
| GPU | NVIDIA GeForce RTX 5060 Ti (16 GB VRAM) -- unused by ASI |
| OS | WSL2 on Windows (kernel 6.6.87.2-microsoft-standard-WSL2) |
| Container runtime | Docker Desktop (overlay2) |
| Kubernetes | kind v1.x, single-node cluster |

This is a consumer desktop, not a server. The entire 3-agent ASI demo runs comfortably within its constraints, using 17.3% of available memory and minimal CPU.

---

## 2. Current Demo Footprint (3-Agent GRE Topology)

### Pod-Level Resource Consumption (Measured)

| Component | Memory (RSS) | Disk (/app) | CPU (steady-state) | Docker Image |
|---|---|---|---|---|
| asi-wizard | 99 MB | 2.2 MB | ~30m | 322 MB |
| asi-monitor | 81 MB | 84 KB | ~20m | 322 MB |
| asi-topology3d | 84 MB | 192 KB | ~10m | 322 MB |
| core-router (agent) | 230 MB | 16 MB | ~50m | 865 MB |
| edge-router (agent) | 230 MB | 16 MB | ~50m | 865 MB |
| internal-router (agent) | 230 MB | 16 MB | ~50m | 865 MB |
| **Total (6 pods)** | **~954 MB** | **~50 MB** | **~210m** | -- |

On this i7-10700KF workstation, the 6-pod cluster consumes:
- **Memory**: 2.03 GB of 11.68 GB (17.3%) -- leaves 9.6 GB for other work
- **CPU**: Negligible steady-state; OSPF hello timers fire every 10s
- **Disk**: ~50 MB pod storage + ~2.4 GB for Docker images
- **Network**: ~8.7 KB TX/RX per Multus interface over 120 OSPF packets (18 min). Negligible.

### What This Means

A developer can run the full ASI platform -- wizard, monitor, 3D visualization, and 3 OSPF agents with GRE tunnels, DiffServ QoS, and NetFlow -- on a laptop or budget desktop. No cloud required for development.

---

## 3. Token Usage Per Action

All estimates use Claude Sonnet 4 pricing ($0.003/1K input, $0.015/1K output).

### Token Breakdown: Single Chat Query

| Component | Tokens | Notes |
|---|---|---|
| System prompt | 2,500 | Fixed per conversation |
| Conversation overhead | 500 | Per turn |
| Interfaces (5x) | 300 | 60 tokens/interface |
| OSPF neighbors (2x) | 160 | 80 tokens/neighbor |
| OSPF LSAs (3x) | 105 | 35 tokens/LSA |
| **Total input** | **3,565** | Current demo agent |
| Response | ~350 | Average |
| **Cost** | **$0.016** | Per query |

### Per-Action Cost Estimates

| Action | Input Tokens | Output Tokens | Cost | Typical Frequency |
|---|---|---|---|---|
| Simple query ("How many interfaces?") | 3,565 | 350 | $0.016 | Ad hoc |
| OSPF troubleshooting ("Why is neighbor down?") | 4,200 | 500 | $0.020 | During incidents |
| Run test suite + interpret results | 4,565 | 500 | $0.021 | Post-change |
| Autonomous multi-turn analysis | 7,130 | 800 | $0.033 | Alert-triggered |
| Configuration review | 5,000 | 600 | $0.024 | Maintenance windows |

### Context Growth by Network State Size

| Agent Profile | Routes | Neighbors | Interfaces | Context Tokens | Cost/Query |
|---|---|---|---|---|---|
| Current demo | 3 | 2 | 5 | 3,565 | $0.016 |
| Small branch | 50 | 3 | 5 | 8,019 | $0.029 |
| Campus core | 200 | 5 | 8 | 17,590 | $0.058 |
| Regional hub | 500 | 10 | 12 | 36,679 | $0.115 |
| Enterprise core | 1,000 | 15 | 20 | 68,242 | $0.210 |
| Service provider PE | 10,000 | 50 | 100 | 625,252 | RAG required |
| Full IPv4 DFZ | 950,000 | 200 | 50 | 94,098,730 | RAG required |

---

## 4. Realistic Query Model

Queries scale with **humans, not agents**. A team of 5-10 network engineers operates the network. Most agents sit quietly on any given day with no one talking to them.

### Query Sources

| Source | Description | Volume |
|---|---|---|
| **Human interactive** | NOC engineer troubleshooting, config review, "show me" queries | 5-10 engineers x 10-20 agent interactions/day x 5-10 queries each |
| **Automated health checks** | Periodic status polling (cacheable, sampled at scale) | 0.005-1.0 per agent/day depending on fleet size |
| **Alert-triggered analysis** | Autonomous investigation when a threshold trips | ~0.1 per agent/day (most agents are healthy) |

### Query Volume by Scale

| Fleet Size | NOC Staff | Human Queries/Day | Auto Queries/Day | Total Queries/Day |
|---|---|---|---|---|
| 10 agents | 5 | 350 | 10 | **360** |
| 100 agents | 5 | 525 | 50 | **575** |
| 1,000 agents | 8 | 840 | 200 | **1,040** |
| 10,000 agents | 8 | 1,120 | 500 | **1,620** |
| 100,000 agents | 10 | 1,400 | 1,000 | **2,400** |
| 1,000,000 agents | 10 | 1,400 | 5,000 | **6,400** |

A human physically cannot interact with more than ~20 agents/day in a meaningful way. At 100K+ agents, automated queries use aggressive caching and statistical sampling (check 1% of fleet, extrapolate).

---

## 5. Scale Analysis: 10 to 1,000,000 Agents

### LLM Cost (Human-Scale Query Model)

Assumes a normal enterprise routing table (~200-1,000 routes/agent) and Claude Sonnet 4 full-context.

| Agents | Context Tokens | Queries/Day | Cost/Query | Monthly LLM Cost | Per Agent/Month |
|---|---|---|---|---|---|
| 10 | 8,019 | 360 | $0.029 | **$317** | $31.70 |
| 100 | 17,590 | 575 | $0.058 | **$1,001** | $10.01 |
| 1,000 | 36,679 | 1,040 | $0.115 | **$3,597** | $3.60 |
| 10,000 | 68,242 | 1,620 | $0.210 | **$10,205** | $1.02 |
| 100,000 | 68,242 | 2,400 | $0.210 | **$15,118** | $0.15 |
| 1,000,000 | 68,242 | 6,400 | $0.210 | **$40,315** | $0.04 |

Monthly LLM cost plateaus around $10K-$40K because query volume is bounded by human operators, not agent count.

### Infrastructure Requirements (Measured: 230 MB / 50m CPU per agent pod)

| Agents | CPU Cores | Memory | Pod Storage | Nodes Needed |
|---|---|---|---|---|
| 10 | 0.6 | 2.6 GB | 0.2 GB | 1 |
| 100 | 5.1 | 23 GB | 1.6 GB | 1 |
| 1,000 | 50 | 230 GB | 16 GB | 5 |
| 10,000 | 500 | 2.3 TB | 160 GB | 42 |
| 100,000 | 5,000 | 23 TB | 1.6 TB | 411 |
| 1,000,000 | 50,000 | 230 TB | 16 TB | 4,108 |

---

## 6. Infrastructure Costing (Real Hardware)

### Reference: Development Machine (What Runs the Demo Today)

| | Spec | Can Run | Approx. Cost |
|---|---|---|---|
| **Your workstation** | i7-10700KF, 12 GB RAM, 1 TB SSD | 3 agents comfortably, ~10 max | Already owned |
| **Upgraded to 64 GB RAM** | Same CPU, 64 GB DDR4 | ~50 agents | ~$80-$120 for RAM upgrade |

### Bare Metal Servers (Monthly Rental)

| Server | Specs | Agents It Can Run | Monthly Cost | Source |
|---|---|---|---|---|
| **Hetzner EX44** | i5-13500 (14c/20t), 64 GB DDR4, 2x512 GB NVMe | ~50-80 agents | **$51/mo** | [hetzner.com/dedicated-rootserver/ex44](https://www.hetzner.com/dedicated-rootserver/ex44/) |
| **Hetzner AX102** | Ryzen 9 7950X3D (16c/32t), 128 GB DDR5, 2x1.9 TB NVMe | ~150-250 agents | **$116/mo** | [hetzner.com/dedicated-rootserver/ax102](https://www.hetzner.com/dedicated-rootserver/ax102/) |
| **Used Dell R630** | 2x Xeon E5-2620v4 (16c/32t), 64 GB ECC, 1U rack | ~50-80 agents | **$120-$200 one-time** | Refurb market |

### Cloud (AWS EC2 On-Demand, us-east-1)

| Instance | Specs | Agents It Can Run | Hourly / Monthly Cost |
|---|---|---|---|
| **m7i.4xlarge** | 16 vCPU, 64 GB | ~50-80 agents | ~$0.81/hr / **$583/mo** |
| **m7i.16xlarge** | 64 vCPU, 256 GB | ~400-600 agents | ~$3.23/hr / **$2,325/mo** |
| **r7i.16xlarge** | 64 vCPU, 512 GB | ~800-1,200 agents | ~$4.23/hr / **$3,046/mo** |

Source: [AWS EC2 On-Demand Pricing](https://aws.amazon.com/ec2/pricing/on-demand/), [Vantage m7i.16xlarge](https://instances.vantage.sh/aws/ec2/m7i.16xlarge), [Vantage r7i.16xlarge](https://instances.vantage.sh/aws/ec2/r7i.16xlarge)

### Total Cost of Ownership by Scale

| Scale | Infrastructure Option | Infra Cost/Month | LLM Cost/Month | **Total/Month** |
|---|---|---|---|---|
| **3 agents (demo)** | Your i7-10700KF workstation | $0 (owned) | $74 | **$74** |
| **50 agents** | 1x Hetzner EX44 | $51 | $500 | **$551** |
| **250 agents** | 1x Hetzner AX102 | $116 | $1,500 | **$1,616** |
| **1,000 agents** | 5x Hetzner AX102 | $580 | $3,597 | **$4,177** |
| **1,000 agents** | 2x AWS m7i.16xlarge | $4,650 | $3,597 | **$8,247** |
| **10,000 agents** | 42x Hetzner AX102 | $4,872 | $10,205 | **$15,077** |
| **10,000 agents** | 8x AWS r7i.16xlarge | $24,368 | $10,205 | **$34,573** |
| **100,000 agents** | 411 nodes (bare metal cluster) | ~$47,676 | $15,118 | **$62,794** |
| **1,000,000 agents** | 4,108 nodes | ~$476,528 | $40,315 | **$516,843** |

At small scale (< 1,000 agents), **LLM cost dominates**. At large scale (> 10,000 agents), **infrastructure dominates** because agent pods cost memory/CPU but humans are the bottleneck for queries.

---

## 7. Context Window Limits & RAG Architecture

### Thresholds

| Threshold | Routes/Agent | Impact | Mitigation |
|---|---|---|---|
| Comfortable | < 500 | Full context fits, 96% accuracy | None needed |
| Degradation onset | 500-5,000 | 88-93% accuracy, 35-170K tokens | RAG recommended |
| Context overflow | > 5,000 | Exceeds 200K Sonnet window | RAG mandatory |
| RAG overflow | > 50,000 | Even RAG 88% reduction overflows | Semantic RAG (retrieve relevant subset per query) |

### RAG Impact (at 1,000 routes/agent, enterprise core)

| Architecture | Effective Tokens | Cost/Query | Accuracy | Latency |
|---|---|---|---|---|
| Full context | 68,242 | $0.210 | 91.2% | 1,823 ms |
| RAG | 8,189 | $0.030 | 93.1% | 1,061 ms |

RAG provides **7x cost reduction**, **better accuracy** (smaller context = less noise), and **40% lower latency**. For agents with > 500 routes, RAG is strictly better.

### Full IPv4 DFZ (950K Routes)

Full context: 94.1M tokens (470x the context window). Impossible.

Practical approach: **Semantic RAG** retrieves only the ~100 routes relevant to each query. Context stays at ~7,500 tokens ($0.028/query) regardless of total table size. A 1M-route agent costs the same per query as a 50-route branch agent.

### Model Comparison (1,000 routes/agent, full context)

| Model | Cost/Query | Accuracy | Monthly (10K agents, 1,620 q/day) |
|---|---|---|---|
| Claude Sonnet 4 | $0.210 | 91.2% | $10,205 |
| GPT-4o | $0.174 | 88.8% | $8,459 |
| Gemini 1.5 Pro | $0.087 | 87.2% | $4,230 |
| Claude Sonnet 4 + RAG | $0.030 | 93.1% | **$1,447** |

---

## 8. Cost Optimization Levers

| Lever | Savings | Trade-off |
|---|---|---|
| RAG architecture | 7x | Adds retrieval latency (~200ms), requires vector store |
| Response caching | 2-5x | Stale answers; invalidate on state change |
| Cheaper model for routine queries | 2-3x | Lower accuracy on complex troubleshooting |
| Event-driven (not polling) | 5-10x on auto queries | Requires alerting pipeline |
| Semantic RAG for large tables | Constant cost/query regardless of table size | Requires embedding pipeline |
| Bare metal over cloud | 3-5x on infrastructure | Self-managed; no elastic scaling |

### Recommended Architecture by Scale

| Fleet Size | Architecture | LLM Strategy | Est. Monthly Total |
|---|---|---|---|
| 1-50 agents | Full context, single server | Claude Sonnet, direct | $100-$600 |
| 50-500 agents | Full context + caching | Claude Sonnet, cache common queries | $600-$2,500 |
| 500-5,000 agents | RAG, small cluster | Sonnet + vector store | $2,000-$5,000 |
| 5,000-100,000 agents | RAG + tiered models | Sonnet for incidents, Haiku for health checks | $10,000-$60,000 |
| 100,000+ agents | Semantic RAG + tiered + caching | Full optimization stack | $60,000-$500,000 |

---

## 9. Summary

| Metric | Demo (3 agents) on i7-10700KF | 10K Enterprise | 1M Fleet |
|---|---|---|---|
| Memory used | 954 MB of 12 GB | 2.3 TB | 230 TB |
| CPU used | 0.21 of 16 cores | 500 cores | 50,000 cores |
| Infrastructure | Your desktop | 42 nodes | 4,108 nodes |
| Monthly infra cost | $0 (owned) | $4,872-$24,368 | $476K+ |
| Monthly LLM cost | $74 | $10,205 | $40,315 |
| **Total monthly** | **$74** | **$15K-$35K** | **$517K** |
| Per-agent/month LLM | $24.73 | $1.02 | $0.04 |
| Queries/day | ~50 (1-2 devs) | 1,620 (8 NOC staff) | 6,400 (10 NOC staff) |
| Accuracy | 96% | 91% full / 93% RAG | 91% full / 93% RAG |

**Key takeaway**: LLM cost is modest and predictable because humans -- not agents -- drive query volume. The real scaling constraint is infrastructure compute. A $51/month Hetzner box can run 50+ agents. Your existing i7-10700KF workstation runs 3 agents at 17% memory utilization with room for ~10 total.

---

*Measured on Intel i7-10700KF (8c/16t, 12 GB RAM, WSL2). Token estimates from `wontyoubemyneighbor/agentic/metrics/scale_predictor.py`. Accuracy model uses sigmoid degradation (context rot hypothesis). LLM costs based on February 2026 Anthropic API pricing. Cloud pricing from AWS EC2 On-Demand (us-east-1, February 2026). Bare metal pricing from Hetzner (Germany, incl. VAT).*
