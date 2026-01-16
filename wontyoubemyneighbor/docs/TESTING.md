# Testing Guide

## Setup

Install dependencies:
```bash
pip install -r requirements.txt
```

## Running Tests

### All Tests
```bash
cd wontyoubemyneighbor
python3 -m pytest tests/ -v
```

### Specific Test File
```bash
python3 -m pytest tests/test_packets.py -v
```

### Test Coverage
```bash
python3 -m pytest tests/ --cov=ospf --cov-report=html
```

## Test Structure

```
tests/
├── test_packets.py          # Packet parsing/generation tests
├── test_neighbor_fsm.py     # Neighbor state machine tests (TBD)
├── test_lsdb.py             # LSDB operations tests (TBD)
├── test_spf.py              # SPF algorithm tests (TBD)
├── test_flooding.py         # LSA flooding tests (TBD)
└── integration/
    └── test_real_router.py  # Integration tests with real router (TBD)
```

## Test Status

### Iteration 3 - Packet Tests (test_packets.py)

**Completed Test Classes:**
- TestOSPFHeader: OSPF header creation, serialization, parsing
- TestOSPFHello: Hello packet complete workflow
- TestOSPFDBDescription: DBD packet and flags
- TestLSAHeader: LSA header creation and serialization
- TestRouterLSA: Router LSA with links
- TestNetworkLSA: Network LSA creation
- TestChecksums: OSPF and LSA checksum validation
- TestPacketParsing: Packet parsing utilities
- TestPacketIntegration: Complete roundtrip tests

**Total Tests:** 25+ test cases

**To Run:**
```bash
pip install -r requirements.txt
cd wontyoubemyneighbor
python3 -m pytest tests/test_packets.py -v
```

## Notes

Tests are designed to validate:
1. Packet structure compliance with RFC 2328
2. Serialization to bytes (wire format)
3. Deserialization from bytes
4. Checksum calculation and validation
5. Complete roundtrip workflows
6. Utility function correctness

Tests will be run during integration testing phase once all dependencies are properly installed.
