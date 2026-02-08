# Dashboard & Chat Testing Guide

User-friendly guide for testing GRE/OSPF using the web dashboard and natural language chat.

---

## 🖥️ Access the Dashboards

After deployment, agent dashboards are available at:
- **Core Router**: `http://localhost:8888` (or port shown in deployment output)
- **Edge Router**: Check deployment output for port
- **Internal Router**: Check deployment output for port

---

## 💬 Natural Language Prompts for Agent Chat

### Testing Connectivity

```
Ping the external FRR router at 10.255.255.100
```

```
Ping the FRR router through the GRE tunnel at 10.255.0.2
```

```
Ping all my OSPF neighbors and tell me which ones respond
```

```
Test connectivity to 10.100.0.1 (FRR's external network)
```

```
Traceroute to 10.255.255.100 and explain the path
```

### Checking OSPF

```
Show me all OSPF neighbors and their states
```

```
Which OSPF neighbors are in Full state?
```

```
What routes did we learn via OSPF?
```

```
Explain my OSPF topology
```

```
Why is my OSPF neighbor stuck in ExStart?
```

```
Show me the OSPF link state database
```

### Checking GRE Tunnel

```
Show me the GRE tunnel configuration
```

```
Is the GRE tunnel up?
```

```
What's the MTU on the GRE tunnel?
```

```
Explain how the GRE tunnel works
```

```
Test the GRE tunnel to the FRR router
```

### Checking Routes

```
Show me the routing table
```

```
What routes go through the GRE tunnel?
```

```
Can I reach 10.100.0.0/24?
```

```
Show me all routes learned from OSPF
```

```
Explain how to reach 10.255.255.100
```

### Interface Information

```
Show me all network interfaces
```

```
What IP addresses are configured?
```

```
Show interface statistics for gre0
```

```
Which interfaces are running OSPF?
```

---

## 📊 What to Look For on Dashboards

### ✅ Interfaces Panel (Should Show)

| Interface | Type | IP Address | MTU | Status | Description |
|-----------|------|------------|-----|--------|-------------|
| eth0 | Ethernet | 172.24.0.99/16 | 1500 | up | Main network interface |
| eth1 | Ethernet | 192.168.100.10/24 | 1500 | up | GRE underlay to external FRR |
| gre0 | gre | 10.255.0.1/30 | 1400 | up | GRE tunnel to external FRR router |
| lo0 | Loopback | 10.255.255.99/32 | 1500 | up | Loopback |

**✓ All should be "up"**
**✓ Total Interfaces: 4**

---

### ✅ OSPF Neighbors Panel (Should Show)

| Neighbor ID | IP Address | State | Interface | DR/BDR |
|-------------|------------|-------|-----------|--------|
| 10.255.255.1 | 172.24.0.2 | **Full** | eth0 | - |
| 10.255.255.2 | 172.24.0.4 | **Full** | eth0 | - |
| 10.255.255.100 | 10.255.0.2 | **Full** | gre0 | - |

**✓ Total Neighbors: 3**
**✓ Full Adjacencies: 3**
**✓ All states should be "Full" (NOT ExStart!)**

**⚠️ If stuck in ExStart:**
- Neighbors can hear each other but can't exchange databases
- Usually indicates MTU mismatch or network type mismatch
- Ask agent: "Why is my OSPF neighbor stuck in ExStart?"

---

### ✅ OSPF Routes Panel (Should Show)

| Prefix | Next Hop | Interface | Cost | Type |
|--------|----------|-----------|------|------|
| 10.100.0.0/24 | 10.255.0.2 | gre0 | 20 | O |
| 10.255.255.1/32 | 172.24.0.2 | eth0 | 10 | O |
| 10.255.255.2/32 | 172.24.0.4 | eth0 | 10 | O |
| 10.255.255.100/32 | 10.255.0.2 | gre0 | 10 | O |

**✓ Should see routes to:**
- Edge Router loopback (10.255.255.1)
- Internal Router loopback (10.255.255.2)
- FRR Router loopback (10.255.255.100)
- FRR's external network (10.100.0.0/24)

**⚠️ If "No routes":**
- OSPF neighbors aren't reaching Full state
- Routes aren't being advertised
- Ask agent: "Why am I not learning OSPF routes?"

---

### ✅ GRE Tunnels Panel (Should Show)

| Tunnel | Local IP | Remote IP | Tunnel IP | Key | MTU | State |
|--------|----------|-----------|-----------|-----|-----|-------|
| gre0 | 192.168.100.10 | 192.168.100.20 | 10.255.0.1/30 | 100 | 1400 | UP |

**✓ Local IP: 192.168.100.10** (NOT N/A)
**✓ Remote IP: 192.168.100.20** (NOT N/A)
**✓ Tunnel IP: 10.255.0.1/30**
**✓ Key: 100** (NOT "none")
**✓ State: UP**

**⚠️ If showing N/A or "none":**
- GRE tunnel metadata not being parsed correctly
- Tunnel may still work, but dashboard display needs fixing
- Ask agent: "Show me the GRE tunnel configuration in detail"

---

### ✅ Routes/Routing Table Panel

You should see routes like:

```
10.100.0.0/24 via 10.255.0.2 dev gre0 proto ospf
10.255.0.0/30 dev gre0 proto kernel scope link
10.255.255.1 via 172.24.0.2 dev eth0 proto ospf
10.255.255.2 via 172.24.0.4 dev eth0 proto ospf
10.255.255.100 via 10.255.0.2 dev gre0 proto ospf
172.24.0.0/16 dev eth0 proto kernel scope link
192.168.100.0/24 dev eth1 proto kernel scope link
```

**✓ Routes via gre0** = Routes through the GRE tunnel
**✓ Routes with "proto ospf"** = Routes learned via OSPF

---

## 🔧 Standard FRR Commands

### Connect to FRR Router

```bash
# Enter FRR CLI
docker exec -it external-frr vtysh
```

### Inside vtysh (FRR CLI)

```
# Show OSPF neighbors
show ip ospf neighbor

# Show OSPF interfaces
show ip ospf interface

# Show OSPF routes
show ip route ospf

# Show all routes
show ip route

# Show OSPF database
show ip ospf database

# Show running configuration
show running-config

# Ping from FRR
ping 10.255.0.1

# Traceroute from FRR
traceroute 10.255.255.99

# Exit vtysh
exit
```

### Expected FRR Output

#### `show ip ospf neighbor` (Should Show):
```
Neighbor ID     Pri State           Up Time         Dead Time Address         Interface                        RXmtL RqstL DBsmL
10.255.255.99   1   Full/-          00:05:23        00:00:38  10.255.0.1      gre1:192.168.100.10              0     0     0
```

**✓ State should be "Full/-"**
**✓ Interface should be "gre1"**

#### `show ip route ospf` (Should Show):
```
O   10.255.255.1/32 [110/20] via 10.255.0.1, gre1, weight 1, 00:05:15
O   10.255.255.2/32 [110/20] via 10.255.0.1, gre1, weight 1, 00:05:15
O   10.255.255.99/32 [110/10] via 10.255.0.1, gre1, weight 1, 00:05:23
O   172.24.0.0/16 [110/20] via 10.255.0.1, gre1, weight 1, 00:05:15
```

**✓ Should see routes to Agentic network (172.24.0.0/16)**
**✓ Should see routes to all Agentic router loopbacks**

---

## 🧪 Quick Validation Checklist

### From Core Router Dashboard:

1. ✅ **Interfaces**: 4 interfaces, all "up"
2. ✅ **OSPF Neighbors**: 3 neighbors, all "Full"
3. ✅ **OSPF Routes**: At least 4 routes learned
4. ✅ **GRE Tunnel**: Shows Local IP, Remote IP, Key (not N/A)

### Ask Agent in Chat:

1. ✅ "Ping 10.255.255.100" → Should succeed
2. ✅ "Ping 10.100.0.1" → Should succeed (FRR's external network)
3. ✅ "Show OSPF neighbors" → All should be Full
4. ✅ "What routes did we learn via OSPF?" → Should list 4+ routes

### From FRR CLI:

1. ✅ `show ip ospf neighbor` → Should show 10.255.255.99 in Full state
2. ✅ `show ip route ospf` → Should show routes to 172.24.0.0/16
3. ✅ `ping 10.255.255.99` → Should succeed
4. ✅ `ping 10.255.255.1` → Should succeed (through Core to Edge)

---

## 🔴 Current Issues I See

Based on your dashboard screenshot:

### Issue 1: OSPF Neighbors Stuck in ExStart ⚠️

**Problem**: Neighbors 10.255.255.1 and 10.255.255.2 are in "ExStart" state, not "Full"

**What to Try**:
- Wait 30-60 seconds (can take time to negotiate)
- Ask agent: "Why is my OSPF neighbor stuck in ExStart?"
- Ask agent: "Show me the OSPF database exchange status"
- Check logs: `docker logs springfield-core-router--ospf---gre | grep -i exstart`

**Possible Causes**:
- Database exchange in progress (normal, wait a bit)
- MTU mismatch between neighbors
- Packet loss during database exchange

### Issue 2: GRE Tunnel Showing N/A ⚠️

**Problem**: GRE dashboard shows:
- Local IP: N/A (should be 192.168.100.10)
- Remote IP: N/A (should be 192.168.100.20)
- Key: none (should be 100)

**What to Try**:
- Ask agent: "Show me the GRE tunnel configuration in detail"
- Ask agent: "Run: ip tunnel show gre0"
- The tunnel might still work, just dashboard display issue

### Issue 3: No OSPF Routes ⚠️

**Problem**: "No routes" in OSPF Routes panel

**Explanation**: This is normal if neighbors are stuck in ExStart. Routes are only installed after reaching Full state.

**What to Try**:
- Wait for neighbors to reach Full
- Once Full, routes should appear automatically
- Ask agent: "Show me the routing table"

---

## 🎯 Success Indicators

You'll know everything is working when:

1. ✅ All 3 OSPF neighbors show **"Full"** state
2. ✅ OSPF Routes panel shows **4+ routes**
3. ✅ GRE Tunnel panel shows correct **Local/Remote IPs and Key**
4. ✅ Agent can ping **10.255.255.100** (FRR router)
5. ✅ Agent can ping **10.100.0.1** (FRR's external network)
6. ✅ FRR can ping **10.255.255.1** and **10.255.255.2** (through Core)

---

## 💡 Pro Tips

### Instead of Docker Commands:

❌ Don't use: `docker exec ... ip addr show`
✅ Use chat: "Show me all network interfaces"

❌ Don't use: `docker logs ... | grep OSPF`
✅ Use chat: "Show me OSPF neighbor states"

❌ Don't use: `docker exec ... ping 10.255.255.100`
✅ Use chat: "Ping the FRR router at 10.255.255.100"

### The agent understands you and can:
- Execute commands for you
- Explain the output
- Troubleshoot problems
- Suggest fixes

Just ask naturally! 🤖
