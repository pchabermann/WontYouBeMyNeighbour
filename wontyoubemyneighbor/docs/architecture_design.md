# OSPF Agent Architecture Design

## Document Purpose
Define the architecture, components, and interactions for the wontyoubemyneighbor OSPF agent.

---

## 1. System Overview

### 1.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    OSPFAgent (Main)                         │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              Event Loop (asyncio)                     │  │
│  └──────────────────────────────────────────────────────┘  │
│                           │                                  │
│     ┌─────────────────────┼─────────────────────┐          │
│     │                     │                     │          │
│     ▼                     ▼                     ▼          │
│  ┌──────┐           ┌──────────┐          ┌────────┐      │
│  │Hello │           │  Receive │          │ Aging  │      │
│  │ Loop │           │   Loop   │          │  Loop  │      │
│  └──────┘           └──────────┘          └────────┘      │
│     │                     │                     │          │
│     │                     │                     │          │
│     ▼                     ▼                     ▼          │
├─────────────────────────────────────────────────────────────┤
│                   Component Layer                           │
├─────────────────────────────────────────────────────────────┤
│ ┌─────────────┐ ┌──────────────┐ ┌────────────────────┐   │
│ │   Hello     │ │  Adjacency   │ │      Flooding      │   │
│ │  Handler    │ │   Manager    │ │      Manager       │   │
│ └─────────────┘ └──────────────┘ └────────────────────┘   │
│                                                             │
│ ┌─────────────┐ ┌──────────────┐ ┌────────────────────┐   │
│ │   Neighbor  │ │     LSDB     │ │        SPF         │   │
│ │   Manager   │ │   Manager    │ │    Calculator      │   │
│ └─────────────┘ └──────────────┘ └────────────────────┘   │
├─────────────────────────────────────────────────────────────┤
│                    Protocol Layer                           │
├─────────────────────────────────────────────────────────────┤
│ ┌─────────────────────────────────────────────────────────┐│
│ │           Packet Handler (packets.py)                   ││
│ │  - OSPFHeader    - HelloPacket    - DBDPacket          ││
│ │  - LSRPacket     - LSUPacket      - LSAckPacket        ││
│ │  - LSA classes (Router, Network, Summary, External)    ││
│ └─────────────────────────────────────────────────────────┘│
├─────────────────────────────────────────────────────────────┤
│                    Network Layer                            │
├─────────────────────────────────────────────────────────────┤
│ ┌──────────────────┐        ┌─────────────────────────┐   │
│ │  Socket Handler  │        │  Interface Manager      │   │
│ │  - Raw Socket    │        │  - IP Address           │   │
│ │  - Multicast     │        │  - Network Mask         │   │
│ │  - Send/Receive  │        │  - MTU                  │   │
│ └──────────────────┘        └─────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                             │
                             ▼
                    ┌────────────────┐
                    │  Network (eth0)│
                    │  224.0.0.5     │
                    └────────────────┘
```

### 1.2 Design Principles

1. **Separation of Concerns**: Each component has single responsibility
2. **Event-Driven**: Asyncio for concurrent operations
3. **Stateful**: Explicit state machines for neighbors
4. **Testable**: Components can be tested in isolation
5. **RFC Compliant**: Strict adherence to RFC 2328
6. **Observable**: Extensive logging for debugging

---

## 2. Core Components

### 2.1 OSPFAgent (wontyoubemyneighbor.py)

**Role**: Main orchestrator and entry point

**Responsibilities**:
- Initialize all components
- Manage asyncio event loop
- Coordinate between components
- Handle configuration
- Provide CLI interface

**Key Methods**:
```python
async def start()                    # Start agent
async def stop()                     # Stop agent gracefully
async def _hello_loop()              # Send periodic Hellos
async def _receive_loop()            # Receive and route packets
async def _aging_loop()              # Age LSAs
async def _spf_loop()                # Periodic SPF calculation
async def _process_packet(data)      # Route packet to handler
```

**State**:
- Router configuration (ID, area, interface)
- Component instances
- Neighbor dictionary
- Running flag

---

### 2.2 HelloHandler (ospf/hello.py)

**Role**: Manage Hello protocol

**Responsibilities**:
- Build Hello packets
- Process received Hellos
- Maintain neighbor discovery
- Validate Hello parameters
- Detect dead neighbors

**Key Methods**:
```python
def __init__(router_id, area_id, interface, network_mask)
def build_hello_packet() -> bytes
def process_hello(packet: bytes) -> Optional[str]
async def monitor_neighbors()
```

**State**:
- Hello interval
- Dead interval
- Router priority
- Designated Router
- Backup Designated Router
- Neighbor list (router_id -> last_seen_time)

**Events Generated**:
- `neighbor_discovered(router_id, ip_address)`
- `neighbor_dead(router_id)`

---

### 2.3 OSPFNeighbor (ospf/neighbor.py)

**Role**: Represent single OSPF neighbor with state machine

**Responsibilities**:
- Track neighbor state (Down → Full)
- Maintain neighbor-specific data structures
- Handle state transitions
- Store DBD exchange state
- Manage LSA request/retransmission lists

**State Machine**:
```
Down → Init → 2-Way → ExStart → Exchange → Loading → Full
```

**Key Attributes**:
```python
router_id: str                    # Neighbor's router ID
ip_address: str                   # Neighbor's IP
priority: int                     # Router priority
state: int                        # Current FSM state
last_hello: float                 # Timestamp of last Hello
dd_sequence_number: int           # DBD sequence number
is_master: bool                   # Master/slave for DBD
ls_request_list: List[LSAHeader]  # LSAs we need
ls_retransmission_list: List[LSA] # Unacked LSAs
db_summary_list: List[LSAHeader]  # LSAs to send in DBD
```

**Key Methods**:
```python
def handle_hello(hello_packet)
def trigger_event(event_name)
def should_form_adjacency() -> bool
def is_full() -> bool
```

---

### 2.4 AdjacencyManager (ospf/adjacency.py)

**Role**: Manage adjacency formation through DBD exchange

**Responsibilities**:
- Determine master/slave
- Conduct DBD exchange (ExStart, Exchange states)
- Build and process DBD packets
- Identify LSAs needed from neighbor
- Transition to Loading state

**Key Methods**:
```python
async def start_exchange(neighbor, lsdb)
async def continue_exchange(neighbor, lsdb)
def process_dbd(neighbor, dbd_packet) -> List[LSAHeader]
def _build_dbd_packet(flags, sequence, lsa_headers) -> bytes
def _compare_lsa(lsa_header) -> bool  # Do we need this LSA?
```

**State**:
- Master/slave determination
- DD sequence number
- DBD exchange progress per neighbor

---

### 2.5 LinkStateDatabase (ospf/lsdb.py)

**Role**: Store and manage Link State Advertisements

**Responsibilities**:
- Store LSAs indexed by (type, id, adv_router)
- Add/update LSAs with sequence number comparison
- Age LSAs (increment age each second)
- Remove MaxAge LSAs
- Generate Router LSA for this router
- Provide LSA lookup and iteration

**Data Structure**:
```python
database: Dict[Tuple[int, str, str], LSA]
# Key: (ls_type, link_state_id, advertising_router)
# Value: LSA object
```

**Key Methods**:
```python
def add_lsa(lsa) -> bool              # Returns True if newer
def get_lsa(ls_type, ls_id, adv_router) -> Optional[LSA]
def get_all_lsas() -> List[LSA]
def get_lsa_headers() -> List[LSAHeader]
def age_lsas() -> int                 # Returns count aged out
def create_router_lsa(router_id, links) -> RouterLSA
def _is_newer(lsa1, lsa2) -> bool     # RFC 2328 Section 13.1
```

**LSA Comparison Logic** (RFC 2328 Section 13.1):
1. Higher sequence number = newer
2. If seq equal, higher checksum = newer
3. If both equal, age comparison

---

### 2.6 LSAFloodingManager (ospf/flooding.py)

**Role**: Handle LSA flooding protocol (LSR, LSU, LSAck)

**Responsibilities**:
- Send Link State Requests for needed LSAs
- Process LSR and respond with LSU
- Process LSU and update LSDB
- Generate LSAck for received LSAs
- Flood new LSAs to all neighbors except sender
- Manage retransmission lists
- Handle acknowledgments

**Key Methods**:
```python
async def send_ls_request(neighbor)
def process_ls_request(neighbor, lsr_packet) -> LSUPacket
def process_ls_update(neighbor, lsu_packet) -> LSAckPacket
def process_ls_ack(neighbor, ack_packet)
def _flood_lsa(lsa, exclude_neighbor)
```

**Flooding Algorithm**:
1. Receive LSU
2. For each LSA in LSU:
   - Validate checksum
   - Compare with LSDB copy
   - If newer: install, flood to other neighbors
   - If equal: ignore
   - If older: send back our newer copy
3. Send LSAck
4. Remove from request list

---

### 2.7 SPFCalculator (ospf/spf.py)

**Role**: Calculate shortest path tree and routing table

**Responsibilities**:
- Build graph from LSDB
- Run Dijkstra's algorithm
- Generate routing table
- Handle topology changes
- Provide route lookups

**Algorithm**:
1. Build directed graph from Router LSAs and Network LSAs
2. Set root = this router
3. Run Dijkstra to find shortest paths to all nodes
4. Build routing table with (destination, cost, next_hop)

**Key Methods**:
```python
def calculate() -> Dict[str, RouteEntry]
def _build_graph() -> nx.Graph
def _process_router_lsa(graph, lsa)
def _process_network_lsa(graph, lsa)
def get_route(destination) -> Optional[RouteEntry]
def print_routing_table()
```

**Data Structures**:
```python
class RouteEntry:
    destination: str      # Destination network/router
    cost: int            # Total path cost
    next_hop: str        # Next hop router ID or IP
    path: List[str]      # Full path for debugging
```

**Library**: Use NetworkX for Dijkstra implementation

---

### 2.8 Packet Handler (ospf/packets.py)

**Role**: Define OSPF packet structures using Scapy

**Responsibilities**:
- Define all packet types with Scapy
- Serialize packets to bytes
- Parse bytes to packet objects
- Calculate checksums
- Handle authentication fields

**Packet Classes**:
```python
class OSPFHeader(Packet)           # 24 bytes, all packets
class OSPFHello(Packet)            # Hello-specific fields
class OSPFDBDescription(Packet)    # DBD-specific fields
class OSPFLSReq(Packet)            # LSR-specific fields
class OSPFLSUpdate(Packet)         # LSU-specific fields
class OSPFLSAck(Packet)            # LSAck-specific fields

class LSAHeader(Packet)            # 20 bytes, all LSAs
class RouterLSA(Packet)            # Type 1
class NetworkLSA(Packet)           # Type 2
class SummaryLSA(Packet)           # Type 3/4
class ASExternalLSA(Packet)        # Type 5
```

**Key Functions**:
```python
def parse_ospf_packet(data: bytes) -> Packet
def build_ospf_packet(packet: Packet) -> bytes
def calculate_checksum(data: bytes) -> int
def validate_checksum(packet: Packet) -> bool
```

---

### 2.9 OSPFSocket (lib/socket_handler.py)

**Role**: Handle raw sockets for OSPF communication

**Responsibilities**:
- Create raw socket for IP protocol 89
- Join/leave multicast groups
- Send OSPF packets to unicast or multicast
- Receive OSPF packets with timeout
- Handle socket options (TTL, multicast TTL, etc.)

**Key Methods**:
```python
def __init__(interface, router_id)
def open()                           # Create and configure socket
def close()                          # Clean up
def send(packet: bytes, dest: str)   # Send to IP
def receive(timeout: float) -> Optional[bytes]
def join_multicast(group: str)
def leave_multicast(group: str)
```

**Socket Configuration**:
- `AF_INET`, `SOCK_RAW`, protocol 89
- `IP_HDRINCL` to build IP header
- `IP_ADD_MEMBERSHIP` for multicast
- `SO_BINDTODEVICE` to bind to interface
- Multicast TTL = 1 (link-local)

---

### 2.10 InterfaceManager (lib/interface.py)

**Role**: Network interface information

**Responsibilities**:
- Get interface IP address
- Get interface network mask
- Get interface MAC address
- Validate interface exists and is up
- Get MTU

**Key Methods**:
```python
def get_ip_address(interface: str) -> str
def get_netmask(interface: str) -> str
def get_mac_address(interface: str) -> str
def get_mtu(interface: str) -> int
def is_interface_up(interface: str) -> bool
```

---

### 2.11 StateMachine (lib/state_machine.py)

**Role**: Generic finite state machine

**Responsibilities**:
- Define states and transitions
- Trigger events to transition
- Execute enter/exit callbacks
- Validate transitions
- Provide state query

**Key Methods**:
```python
def __init__(initial_state)
def add_transition(from_state, event, to_state)
def add_on_enter(state, callback)
def add_on_exit(state, callback)
def trigger(event, **kwargs) -> bool
def get_state() -> Any
```

**Usage**:
```python
fsm = StateMachine(STATE_DOWN)
fsm.add_transition(STATE_DOWN, "HelloReceived", STATE_INIT)
fsm.add_transition(STATE_INIT, "2-WayReceived", STATE_2WAY)
fsm.add_on_enter(STATE_2WAY, lambda: print("2-Way established"))
fsm.trigger("HelloReceived")
```

---

## 3. Data Flow

### 3.1 Hello Exchange Flow

```
┌─────────────┐                              ┌─────────────┐
│   OSPFAgent │                              │   Neighbor  │
└──────┬──────┘                              └──────┬──────┘
       │                                            │
       │ 1. Hello Loop Timer                       │
       ├──────────────────────────────────────────►│
       │    HelloHandler.build_hello_packet()      │
       │    OSPFSocket.send(AllSPFRouters)         │
       │                                            │
       │ 2. Receive Hello                          │
       │◄──────────────────────────────────────────┤
       │                                            │
       │ 3. Parse & Process                        │
       │    HelloHandler.process_hello()           │
       │    Extract neighbor_id                    │
       │                                            │
       │ 4. Update Neighbor                        │
       │    neighbor.handle_hello()                │
       │    FSM: Down → Init                       │
       │                                            │
       │ 5. Next Hello includes neighbor_id        │
       ├──────────────────────────────────────────►│
       │                                            │
       │ 6. Receive Hello with our ID              │
       │◄──────────────────────────────────────────┤
       │    FSM: Init → 2-Way                      │
       │                                            │
       │ 7. Decision: Form Adjacency?              │
       │    neighbor.should_form_adjacency()       │
       │    Yes: FSM: 2-Way → ExStart              │
       │                                            │
```

### 3.2 Adjacency Formation Flow

```
┌─────────────┐                              ┌─────────────┐
│  Master     │                              │   Slave     │
└──────┬──────┘                              └──────┬──────┘
       │                                            │
       │ 1. ExStart State                          │
       │    Compare router IDs                     │
       │    Higher ID = Master                     │
       │                                            │
       │ 2. Send DBD (I=1, M=1, MS=1)              │
       ├──────────────────────────────────────────►│
       │    Sequence = X                           │
       │                                            │
       │ 3. Receive DBD (I=1, M=1, MS=0)           │
       │◄──────────────────────────────────────────┤
       │    Sequence = X (slave uses master's seq) │
       │    FSM: ExStart → Exchange                │
       │                                            │
       │ 4. Exchange State                         │
       │    Send DBD with LSA headers              │
       ├──────────────────────────────────────────►│
       │    M=1 if more headers to send            │
       │                                            │
       │ 5. Receive DBD with LSA headers           │
       │◄──────────────────────────────────────────┤
       │    Build request list                     │
       │                                            │
       │ 6. Final DBD (M=0)                        │
       ├──────────────────────────────────────────►│
       │    No more headers                        │
       │                                            │
       │ 7. Final DBD (M=0)                        │
       │◄──────────────────────────────────────────┤
       │    FSM: Exchange → Loading                │
       │                                            │
       │ 8. Loading State                          │
       │    Send LSR for needed LSAs               │
       ├──────────────────────────────────────────►│
       │                                            │
       │ 9. Receive LSU with requested LSAs        │
       │◄──────────────────────────────────────────┤
       │    Add LSAs to LSDB                       │
       │    Send LSAck                             │
       ├──────────────────────────────────────────►│
       │                                            │
       │ 10. All requests satisfied                │
       │     FSM: Loading → Full                   │
       │     Adjacency Complete!                   │
       │                                            │
```

### 3.3 LSA Flooding Flow

```
┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│  Router A   │   │  Router B   │   │  Router C   │
└──────┬──────┘   └──────┬──────┘   └──────┬──────┘
       │                 │                 │
       │ 1. New LSA      │                 │
       │    (topology    │                 │
       │     change)     │                 │
       │                 │                 │
       │ 2. Flood LSU    │                 │
       ├────────────────►│                 │
       │                 │ 3. Process LSU  │
       │                 │    Add to LSDB  │
       │                 │                 │
       │ 4. Receive Ack  │                 │
       │◄────────────────┤                 │
       │                 │                 │
       │                 │ 5. Flood to C   │
       │                 ├────────────────►│
       │                 │                 │
       │                 │ 6. Receive Ack  │
       │                 │◄────────────────┤
       │                 │                 │
       │ (If no ack)     │                 │
       │ 7. Retransmit   │                 │
       │    after 5s     │                 │
       │                 │                 │
```

---

## 4. Async Task Architecture

### 4.1 Main Event Loop

```python
async def main():
    agent = OSPFAgent(...)

    # Start all concurrent tasks
    await asyncio.gather(
        agent._hello_loop(),       # Send Hellos every 10s
        agent._receive_loop(),     # Receive packets continuously
        agent._aging_loop(),       # Age LSAs every 1s
        agent._spf_loop(),         # Run SPF periodically
        agent._monitor_neighbors() # Check for dead neighbors
    )
```

### 4.2 Task Responsibilities

**hello_loop**:
- Timer: Every HelloInterval (10s)
- Action: Build and send Hello packet
- Error handling: Log and continue

**receive_loop**:
- Blocking: socket.receive() with timeout
- Action: Parse packet, route to handler
- Error handling: Log malformed packets, continue

**aging_loop**:
- Timer: Every 1 second
- Action: Increment LSA ages, remove MaxAge
- Trigger: SPF calculation if LSAs aged out

**spf_loop**:
- Timer: Every 30 seconds (configurable)
- Action: Recalculate SPF and routing table
- Optimization: Only run if topology changed

**monitor_neighbors**:
- Timer: Every 1 second
- Action: Check last_hello timestamp
- If > DeadInterval: Declare neighbor dead

---

## 5. Configuration

### 5.1 Required Parameters

```python
router_id: str          # Unique router identifier (e.g., "10.255.255.99")
area_id: str            # OSPF area (e.g., "0.0.0.0")
interface: str          # Network interface (e.g., "eth0")
network: str            # Network address (e.g., "192.168.1.0")
netmask: str            # Network mask (e.g., "255.255.255.0")
```

### 5.2 Optional Parameters

```python
hello_interval: int = 10         # Hello packet interval
dead_interval: int = 40          # Neighbor dead interval
priority: int = 1                # Router priority (DR election)
auth_type: int = 0               # Authentication type
auth_key: str = ""               # Authentication key
log_level: str = "INFO"          # Logging level
```

---

## 6. Error Handling

### 6.1 Network Errors
- **Socket creation failure**: Log error, exit
- **Send failure**: Log warning, continue
- **Receive timeout**: Normal, continue
- **Malformed packet**: Log warning, discard

### 6.2 Protocol Errors
- **Mismatched Hello parameters**: Reject neighbor, log
- **Invalid sequence number**: Discard DBD, log
- **Checksum failure**: Discard packet, log
- **Unknown LSA type**: Accept header only, log

### 6.3 State Errors
- **Invalid state transition**: Log error, stay in current state
- **Neighbor timeout**: Trigger KillNbr event, tear down adjacency
- **DBD exchange deadlock**: Restart exchange

---

## 7. Logging Strategy

### 7.1 Log Levels

**DEBUG**: Detailed packet traces, timer events
```
DEBUG: Sent Hello packet to 224.0.0.5
DEBUG: Received DBD from 10.1.1.1, seq=12345
```

**INFO**: State changes, adjacencies, SPF runs
```
INFO: Neighbor 10.1.1.1: Init → 2-Way
INFO: Adjacency FULL with 10.1.1.1
INFO: SPF calculation complete (5 routes)
```

**WARNING**: Protocol violations, retransmissions
```
WARNING: Hello parameter mismatch from 10.1.1.2
WARNING: Retransmitting LSA (seq=0x80000005)
```

**ERROR**: Serious issues, resource failures
```
ERROR: Failed to open socket: Permission denied
ERROR: Invalid checksum in LSA from 10.1.1.3
```

### 7.2 Structured Logging

Include context in all log messages:
- Timestamp
- Component name
- Neighbor ID (if applicable)
- Packet type (if applicable)

---

## 8. Testing Architecture

### 8.1 Unit Test Structure

```
tests/
├── test_packets.py          # Packet parsing/generation
├── test_neighbor_fsm.py     # State machine transitions
├── test_lsdb.py             # LSDB operations
├── test_spf.py              # SPF algorithm
├── test_flooding.py         # LSA flooding logic
└── integration/
    └── test_real_router.py  # End-to-end with real router
```

### 8.2 Mocking Strategy

**Mock Sockets**: Use fake socket for unit tests
**Mock Timers**: Use asyncio test utilities
**Mock Packets**: Craft packets programmatically
**Real Integration**: Test with actual OSPF router

---

## 9. Performance Considerations

### 9.1 Optimization Points

**SPF Calculation**:
- Only run when topology changes
- Use incremental SPF for small changes
- Throttle calculation frequency

**Packet Processing**:
- Validate checksum early
- Discard duplicates quickly
- Batch LSA processing

**Memory Management**:
- Limit LSDB size
- Prune old LSAs aggressively
- Use efficient data structures

### 9.2 Scalability Limits

**Target Scale**:
- 10-20 neighbors
- 100-200 LSAs in LSDB
- Single area only

**Beyond Scope**:
- Large networks (hundreds of routers)
- Multiple areas
- Advanced optimizations

---

## 10. Future Extensions

### 10.1 Phase 2 Features
- DR/BDR election for broadcast networks
- Network LSA generation
- Multiple interface support

### 10.2 Phase 3 Features
- Multi-area support (ABR functionality)
- MD5 authentication
- Graceful restart
- Virtual links

### 10.3 Phase 4 Features
- Web UI for visualization
- REST API for control
- LLM integration for topology analysis
- BGP integration

---

## 11. Success Criteria

### 11.1 Minimum Viable Product
✓ Form adjacency with real OSPF router
✓ Exchange LSAs
✓ Maintain synchronized LSDB
✓ Calculate routing table
✓ Advertise /32 route
✓ Real router learns our route

### 11.2 Full Implementation
✓ All packet types implemented
✓ All neighbor states working
✓ LSA flooding complete
✓ SPF calculation correct
✓ Comprehensive tests passing
✓ Documented and maintainable

---

## Summary

This architecture provides:
1. **Modularity**: Clear component boundaries
2. **Testability**: Each component testable in isolation
3. **Maintainability**: Well-documented, standard patterns
4. **Scalability**: Room for future enhancements
5. **Correctness**: RFC 2328 compliance by design

The asyncio-based design naturally fits OSPF's event-driven nature, making the implementation clean and efficient.
