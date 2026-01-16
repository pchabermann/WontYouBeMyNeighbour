# OSPF Packet Format Specification

## Document Purpose
Complete specification of OSPF packet formats for implementation using Scapy.

---

## 1. OSPF Header (All Packets)

### 1.1 Format

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|   Version #   |     Type      |         Packet length         |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                          Router ID                            |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                           Area ID                             |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|           Checksum            |             AuType            |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                       Authentication                          |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                       Authentication                          |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

### 1.2 Field Descriptions

| Field | Size | Description |
|-------|------|-------------|
| Version | 1 byte | OSPF version (always 2) |
| Type | 1 byte | Packet type (1-5) |
| Packet Length | 2 bytes | Total packet length including header |
| Router ID | 4 bytes | Originating router's ID |
| Area ID | 4 bytes | OSPF area identifier |
| Checksum | 2 bytes | Standard IP checksum (RFC 905) |
| AuType | 2 bytes | Authentication type (0=None, 1=Simple, 2=MD5) |
| Authentication | 8 bytes | Authentication data |

### 1.3 Scapy Implementation

```python
class OSPFHeader(Packet):
    name = "OSPF Header"
    fields_desc = [
        ByteField("version", 2),
        ByteEnumField("type", 1, {
            1: "Hello",
            2: "Database Description",
            3: "Link State Request",
            4: "Link State Update",
            5: "Link State Acknowledgment"
        }),
        ShortField("len", None),  # Auto-calculated
        IPField("router_id", "0.0.0.0"),
        IPField("area_id", "0.0.0.0"),
        XShortField("chksum", None),  # Auto-calculated
        ShortEnumField("auth_type", 0, {
            0: "Null",
            1: "Simple Password",
            2: "Cryptographic"
        }),
        XLongField("auth_data", 0)
    ]

    def post_build(self, p, pay):
        # Auto-calculate length
        if self.len is None:
            l = len(p) + len(pay)
            p = p[:2] + struct.pack("!H", l) + p[4:]

        # Auto-calculate checksum
        if self.chksum is None:
            ck = checksum(p + pay)
            p = p[:12] + struct.pack("!H", ck) + p[14:]

        return p + pay
```

---

## 2. Hello Packet (Type 1)

### 2.1 Format

```
OSPF Header (24 bytes)
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                        Network Mask                           |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|         HelloInterval         |    Options    |    Rtr Pri    |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                     RouterDeadInterval                        |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                      Designated Router                        |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                   Backup Designated Router                    |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                          Neighbor                             |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                           ...                                 |
```

### 2.2 Field Descriptions

| Field | Size | Description |
|-------|------|-------------|
| Network Mask | 4 bytes | Subnet mask of sending interface |
| HelloInterval | 2 bytes | Seconds between Hellos |
| Options | 1 byte | OSPF optional capabilities |
| Rtr Pri | 1 byte | Router priority (DR election) |
| RouterDeadInterval | 4 bytes | Seconds before neighbor declared dead |
| Designated Router | 4 bytes | IP of current DR |
| Backup Designated Router | 4 bytes | IP of current BDR |
| Neighbor | 4 bytes | Router IDs of neighbors (repeated) |

### 2.3 Options Field

```
 0 1 2 3 4 5 6 7
+-+-+-+-+-+-+-+-+
|*|*|DC|EA|N/P|MC|E|*|
+-+-+-+-+-+-+-+-+
```

| Bit | Name | Description |
|-----|------|-------------|
| E (0x02) | External | External routing capability |
| MC (0x04) | Multicast | Multicast capable |
| N/P (0x08) | NSSA | NSSA area support |
| EA (0x10) | External Attr | External attributes LSA |
| DC (0x20) | Demand Circuit | Demand circuit support |

### 2.4 Scapy Implementation

```python
class OSPFHello(Packet):
    name = "OSPF Hello"
    fields_desc = [
        IPField("network_mask", "255.255.255.0"),
        ShortField("hello_interval", 10),
        ByteField("options", 0x02),  # E-bit set
        ByteField("router_priority", 1),
        IntField("router_dead_interval", 40),
        IPField("designated_router", "0.0.0.0"),
        IPField("backup_designated_router", "0.0.0.0"),
        FieldListField("neighbors", [], IPField("", "0.0.0.0"))
    ]

# Bind to OSPF Header
bind_layers(OSPFHeader, OSPFHello, type=1)
```

---

## 3. Database Description Packet (Type 2)

### 3.1 Format

```
OSPF Header (24 bytes)
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|         Interface MTU         |    Options    |0|0|0|0|0|I|M|MS
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                     DD sequence number                        |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                                                               |
+-                                                             -+
|                                                               |
+-                      An LSA Header                          -+
|                                                               |
+-                                                             -+
|                                                               |
+-                                                             -+
|                                                               |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                              ...                              |
```

### 3.2 Field Descriptions

| Field | Size | Description |
|-------|------|-------------|
| Interface MTU | 2 bytes | MTU of outgoing interface |
| Options | 1 byte | OSPF optional capabilities |
| I-bit | 1 bit | Init bit (first packet) |
| M-bit | 1 bit | More bit (more packets follow) |
| MS-bit | 1 bit | Master/Slave bit (1=Master) |
| DD Sequence | 4 bytes | Sequence number for ordering |
| LSA Headers | 20 bytes each | LSA headers from database |

### 3.3 Scapy Implementation

```python
class OSPFDBD(Packet):
    name = "OSPF Database Description"
    fields_desc = [
        ShortField("interface_mtu", 1500),
        ByteField("options", 0x02),
        ByteField("flags", 0x00),  # I, M, MS bits
        IntField("dd_sequence", 0),
        PacketListField("lsa_headers", [], LSAHeader)
    ]

    def get_i_bit(self):
        return (self.flags & 0x04) >> 2

    def get_m_bit(self):
        return (self.flags & 0x02) >> 1

    def get_ms_bit(self):
        return self.flags & 0x01

    def set_flags(self, i=0, m=0, ms=0):
        self.flags = (i << 2) | (m << 1) | ms

bind_layers(OSPFHeader, OSPFDBD, type=2)
```

---

## 4. Link State Request Packet (Type 3)

### 4.1 Format

```
OSPF Header (24 bytes)
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                          LS type                              |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                       Link State ID                           |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                     Advertising Router                        |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                              ...                              |
```

### 4.2 Field Descriptions

| Field | Size | Description |
|-------|------|-------------|
| LS Type | 4 bytes | LSA type being requested |
| Link State ID | 4 bytes | Identifies the LSA |
| Advertising Router | 4 bytes | Router that originated the LSA |

Note: These three fields repeat for each LSA being requested.

### 4.3 Scapy Implementation

```python
class LSRequest(Packet):
    name = "LS Request"
    fields_desc = [
        IntEnumField("ls_type", 1, {
            1: "Router LSA",
            2: "Network LSA",
            3: "Summary LSA (IP network)",
            4: "Summary LSA (ASBR)",
            5: "AS External LSA"
        }),
        IPField("link_state_id", "0.0.0.0"),
        IPField("advertising_router", "0.0.0.0")
    ]

class OSPFLSR(Packet):
    name = "OSPF Link State Request"
    fields_desc = [
        PacketListField("requests", [], LSRequest)
    ]

bind_layers(OSPFHeader, OSPFLSR, type=3)
```

---

## 5. Link State Update Packet (Type 4)

### 5.1 Format

```
OSPF Header (24 bytes)
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                            # LSAs                             |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                                                               |
+-                                                            +-+
|                             LSAs                              |
+-                                                            +-+
|                              ...                              |
```

### 5.2 Field Descriptions

| Field | Size | Description |
|-------|------|-------------|
| # LSAs | 4 bytes | Number of LSAs in this update |
| LSAs | Variable | Full LSAs (header + body) |

### 5.3 Scapy Implementation

```python
class OSPFLSU(Packet):
    name = "OSPF Link State Update"
    fields_desc = [
        IntField("num_lsas", None),  # Auto-calculated
        PacketListField("lsas", [], LSA,
                       count_from=lambda pkt: pkt.num_lsas)
    ]

    def post_build(self, p, pay):
        if self.num_lsas is None:
            num = len(self.lsas)
            p = struct.pack("!I", num) + p[4:]
        return p + pay

bind_layers(OSPFHeader, OSPFLSU, type=4)
```

---

## 6. Link State Acknowledgment Packet (Type 5)

### 6.1 Format

```
OSPF Header (24 bytes)
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                                                               |
+-                                                             -+
|                         LSA Header                            |
+-                                                             -+
|                                                               |
+-                                                             -+
|                                                               |
+-                                                             -+
|                                                               |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                              ...                              |
```

### 6.2 Scapy Implementation

```python
class OSPFLSAck(Packet):
    name = "OSPF Link State Acknowledgment"
    fields_desc = [
        PacketListField("lsa_headers", [], LSAHeader)
    ]

bind_layers(OSPFHeader, OSPFLSAck, type=5)
```

---

## 7. LSA Header (Common to All LSAs)

### 7.1 Format

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|            LS age             |    Options    |    LS type    |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                        Link State ID                          |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                     Advertising Router                        |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                     LS sequence number                        |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|         LS checksum           |             length            |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

### 7.2 Field Descriptions

| Field | Size | Description |
|-------|------|-------------|
| LS Age | 2 bytes | Time in seconds since LSA originated |
| Options | 1 byte | OSPF optional capabilities |
| LS Type | 1 byte | LSA type (1-5) |
| Link State ID | 4 bytes | Identifies the LSA (type-dependent) |
| Advertising Router | 4 bytes | Router that originated the LSA |
| LS Sequence | 4 bytes | Sequence number for freshness |
| LS Checksum | 2 bytes | Checksum of LSA contents |
| Length | 2 bytes | Length including header |

### 7.3 LS Sequence Number

- **Initial**: 0x80000001
- **Range**: 0x80000001 to 0x7FFFFFFF
- **Increment**: +1 for each new instance
- **Wrap**: At max, generate with InitialSequenceNumber

### 7.4 Scapy Implementation

```python
class LSAHeader(Packet):
    name = "LSA Header"
    fields_desc = [
        ShortField("ls_age", 0),
        ByteField("options", 0x02),
        ByteEnumField("ls_type", 1, {
            1: "Router LSA",
            2: "Network LSA",
            3: "Summary LSA (IP network)",
            4: "Summary LSA (ASBR)",
            5: "AS External LSA"
        }),
        IPField("link_state_id", "0.0.0.0"),
        IPField("advertising_router", "0.0.0.0"),
        IntField("ls_sequence_number", 0x80000001),
        XShortField("ls_checksum", None),  # Auto-calculated
        ShortField("length", None)  # Auto-calculated
    ]

    def post_build(self, p, pay):
        # Auto-calculate length
        if self.length is None:
            l = len(p) + len(pay)
            p = p[:18] + struct.pack("!H", l) + p[20:]

        # Auto-calculate checksum
        if self.ls_checksum is None:
            # Fletcher checksum (RFC 905)
            ck = fletcher_checksum(p[2:] + pay)
            p = p[:16] + struct.pack("!H", ck) + p[18:]

        return p + pay
```

---

## 8. Router LSA (Type 1)

### 8.1 Format

```
LSA Header (20 bytes)
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|    0    |V|E|B|        0      |            # links            |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                          Link ID                              |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                         Link Data                             |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|     Type      |     # TOS     |            metric             |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                              ...                              |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|      TOS      |        0      |          TOS  metric          |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                          Link ID                              |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                         Link Data                             |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                              ...                              |
```

### 8.2 Field Descriptions

| Field | Size | Description |
|-------|------|-------------|
| V-bit | 1 bit | Virtual link endpoint |
| E-bit | 1 bit | AS boundary router |
| B-bit | 1 bit | Area border router |
| # links | 2 bytes | Number of router links |
| Link ID | 4 bytes | Identifies other end (type-dependent) |
| Link Data | 4 bytes | Additional data (type-dependent) |
| Type | 1 byte | Link type (1-4) |
| # TOS | 1 byte | Number of TOS metrics |
| Metric | 2 bytes | Cost of using this link |

### 8.3 Link Types

| Type | Description | Link ID | Link Data |
|------|-------------|---------|-----------|
| 1 | Point-to-point | Neighbor Router ID | Interface IP |
| 2 | Transit network | DR IP address | Interface IP |
| 3 | Stub network | Network IP | Network mask |
| 4 | Virtual link | Neighbor Router ID | Interface IP |

### 8.4 Scapy Implementation

```python
class RouterLink(Packet):
    name = "Router Link"
    fields_desc = [
        IPField("link_id", "0.0.0.0"),
        IPField("link_data", "0.0.0.0"),
        ByteEnumField("link_type", 3, {
            1: "Point-to-point",
            2: "Transit network",
            3: "Stub network",
            4: "Virtual link"
        }),
        ByteField("num_tos", 0),
        ShortField("metric", 1)
    ]

class RouterLSA(Packet):
    name = "Router LSA"
    fields_desc = [
        BitField("reserved1", 0, 5),
        BitField("v_bit", 0, 1),  # Virtual endpoint
        BitField("e_bit", 0, 1),  # AS boundary
        BitField("b_bit", 0, 1),  # Area border
        ByteField("reserved2", 0),
        ShortField("num_links", None),  # Auto-calculated
        PacketListField("links", [], RouterLink,
                       count_from=lambda pkt: pkt.num_links)
    ]

    def post_build(self, p, pay):
        if self.num_links is None:
            num = len(self.links)
            p = p[:2] + struct.pack("!H", num) + p[4:]
        return p + pay

bind_layers(LSAHeader, RouterLSA, ls_type=1)
```

---

## 9. Network LSA (Type 2)

### 9.1 Format

```
LSA Header (20 bytes)
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                         Network Mask                          |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                        Attached Router                        |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                              ...                              |
```

### 9.2 Field Descriptions

| Field | Size | Description |
|-------|------|-------------|
| Network Mask | 4 bytes | Subnet mask of the network |
| Attached Router | 4 bytes | Router IDs attached (repeated) |

### 9.3 Scapy Implementation

```python
class NetworkLSA(Packet):
    name = "Network LSA"
    fields_desc = [
        IPField("network_mask", "255.255.255.0"),
        FieldListField("attached_routers", [], IPField("", "0.0.0.0"))
    ]

bind_layers(LSAHeader, NetworkLSA, ls_type=2)
```

---

## 10. Summary LSA (Type 3/4)

### 10.1 Format

```
LSA Header (20 bytes)
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                         Network Mask                          |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|      0        |                  metric                       |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|     TOS       |                TOS  metric                    |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                              ...                              |
```

### 10.2 Scapy Implementation

```python
class SummaryLSA(Packet):
    name = "Summary LSA"
    fields_desc = [
        IPField("network_mask", "255.255.255.0"),
        ByteField("reserved", 0),
        X3BytesField("metric", 1)
    ]

bind_layers(LSAHeader, SummaryLSA, ls_type=3)
bind_layers(LSAHeader, SummaryLSA, ls_type=4)
```

---

## 11. AS External LSA (Type 5)

### 11.1 Format

```
LSA Header (20 bytes)
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                         Network Mask                          |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|E|     0       |                  metric                       |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                      Forwarding address                       |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                      External Route Tag                       |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|E|    TOS      |                TOS  metric                    |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                      Forwarding address                       |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                      External Route Tag                       |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                              ...                              |
```

### 11.2 Field Descriptions

| Field | Size | Description |
|-------|------|-------------|
| E-bit | 1 bit | External metric type (0=Type 1, 1=Type 2) |
| Metric | 3 bytes | Cost to reach destination |
| Forwarding Address | 4 bytes | Forward packets to this address |
| External Route Tag | 4 bytes | Additional info (not used by OSPF) |

### 11.3 Scapy Implementation

```python
class ASExternalLSA(Packet):
    name = "AS External LSA"
    fields_desc = [
        IPField("network_mask", "255.255.255.0"),
        BitField("e_bit", 0, 1),
        BitField("reserved", 0, 7),
        X3BytesField("metric", 1),
        IPField("forwarding_address", "0.0.0.0"),
        IntField("external_route_tag", 0)
    ]

bind_layers(LSAHeader, ASExternalLSA, ls_type=5)
```

---

## 12. Checksum Calculation

### 12.1 OSPF Header Checksum (RFC 905)

Standard IP checksum over entire packet except authentication field.

```python
def ospf_checksum(data: bytes) -> int:
    """Calculate OSPF checksum (standard IP checksum)"""
    # Exclude authentication field (last 8 bytes of header)
    checksum_data = data[:16] + b'\x00\x00' + data[18:]

    # Standard IP checksum
    if len(checksum_data) % 2:
        checksum_data += b'\x00'

    s = sum(struct.unpack('!%dH' % (len(checksum_data) // 2), checksum_data))
    s = (s >> 16) + (s & 0xffff)
    s += s >> 16

    return ~s & 0xffff
```

### 12.2 LSA Checksum (Fletcher)

Fletcher checksum over LSA contents (age field set to 0).

```python
def fletcher_checksum(data: bytes) -> int:
    """Calculate Fletcher checksum for LSA (RFC 905 Appendix B)"""
    c0 = c1 = 0

    # Set age field to 0
    data = b'\x00\x00' + data[2:]

    for i in range(2, len(data)):  # Skip checksum field
        if i == 16 or i == 17:  # Skip checksum field
            continue
        c0 = (c0 + data[i]) % 255
        c1 = (c1 + c0) % 255

    x = ((len(data) - 17) * c0 - c1) % 255
    if x <= 0:
        x += 255
    y = 510 - c0 - x
    if y > 255:
        y -= 255

    return (x << 8) | y
```

---

## 13. Complete Example: Hello Packet

### 13.1 Building a Hello Packet

```python
from scapy.all import *

# Build OSPF Header
header = OSPFHeader(
    version=2,
    type=1,  # Hello
    router_id="10.255.255.99",
    area_id="0.0.0.0",
    auth_type=0  # No authentication
)

# Build Hello payload
hello = OSPFHello(
    network_mask="255.255.255.0",
    hello_interval=10,
    options=0x02,  # E-bit
    router_priority=1,
    router_dead_interval=40,
    designated_router="0.0.0.0",
    backup_designated_router="0.0.0.0",
    neighbors=["10.1.1.1", "10.2.2.2"]
)

# Combine
packet = header / hello

# Serialize to bytes
packet_bytes = bytes(packet)

# Send via raw socket
sock.sendto(packet_bytes, ("224.0.0.5", 0))
```

### 13.2 Parsing a Hello Packet

```python
# Receive from socket
data, addr = sock.recvfrom(65535)

# Parse OSPF packet
packet = OSPFHeader(data)

# Check type
if packet.type == 1:
    hello = packet[OSPFHello]
    print(f"Hello from {packet.router_id}")
    print(f"Neighbors: {hello.neighbors}")
```

---

## 14. Testing Packet Formats

### 14.1 Unit Test Structure

```python
def test_hello_packet():
    """Test Hello packet creation and parsing"""
    # Create
    pkt = OSPFHeader() / OSPFHello(neighbors=["10.1.1.1"])

    # Serialize
    data = bytes(pkt)

    # Parse
    parsed = OSPFHeader(data)

    # Validate
    assert parsed.type == 1
    assert parsed[OSPFHello].neighbors == ["10.1.1.1"]

def test_checksum():
    """Test checksum calculation"""
    pkt = OSPFHeader() / OSPFHello()
    data = bytes(pkt)

    # Extract checksum
    chksum = struct.unpack("!H", data[12:14])[0]

    # Verify
    assert chksum != 0
    assert validate_checksum(data)
```

---

## 15. Wire Format Validation

### 15.1 Wireshark Dissection

Verify packet format with Wireshark:

```bash
# Capture OSPF packets
sudo tcpdump -i eth0 -nn proto 89 -w ospf.pcap

# Open in Wireshark
wireshark ospf.pcap

# Check:
# - All fields present and correct
# - Checksums valid
# - Packet lengths correct
# - Multicast destination (224.0.0.5)
```

### 15.2 Reference Implementation

Compare with real router packets:
1. Capture Hello from real router
2. Capture Hello from our agent
3. Compare field-by-field
4. Validate identical structure

---

## Summary

This specification provides complete packet format definitions for:
- OSPF Header (all packets)
- Hello Packet
- Database Description Packet
- Link State Request Packet
- Link State Update Packet
- Link State Acknowledgment Packet
- LSA Header (all LSAs)
- Router LSA
- Network LSA
- Summary LSA
- AS External LSA

All formats include:
- Bit-level field layout
- Scapy implementation
- Helper methods
- Checksum calculation
- Examples and tests

Implementation priority: Hello → DBD → LSR/LSU/LSAck → LSAs
