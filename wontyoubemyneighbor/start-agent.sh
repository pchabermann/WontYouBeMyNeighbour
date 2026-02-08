#!/bin/bash
# ASI Agent Startup Script for Kubernetes with Multus CNI
# Configures real multiple interfaces and starts routing protocols

set -e

CONFIG_DIR="/etc/asi"
AGENT_NAME=$(cat ${CONFIG_DIR}/agent.name 2>/dev/null || echo "${AGENT_NAME:-local}")

# Export ASI_AGENT_NAME so the webui dashboard displays the correct name
export ASI_AGENT_NAME="${AGENT_NAME}"

echo "🚀 Starting ASI Agent: ${AGENT_NAME}"
echo "=================================="

# Function to read config value
get_config() {
    local key="$1"
    local file="${CONFIG_DIR}/${key}"
    if [ -f "$file" ]; then
        cat "$file"
    fi
}

# First pass: find and configure the loopback interface
echo "📍 Configuring loopback interface..."
for i in 0 1 2 3 4 5; do
    IF_NAME=$(get_config "interface.${i}.name")
    IF_TYPE=$(get_config "interface.${i}.type")
    IF_ADDR=$(get_config "interface.${i}.address.0")

    if [ -z "$IF_NAME" ]; then
        continue
    fi

    # Match loopback by type OR name
    if [ "$IF_TYPE" = "loopback" ] || [ "$IF_TYPE" = "lo" ] || [[ "$IF_NAME" == lo* ]]; then
        if [ -n "$IF_ADDR" ]; then
            ip addr add ${IF_ADDR} dev lo 2>/dev/null || true
            echo "  ✓ Loopback (${IF_NAME}): ${IF_ADDR}"
        fi
    fi
done

# Second pass: configure Multus link interfaces (net1, net2, ...)
# The ConfigMap contains link.0.interface_index, link.1.interface_index, etc.
# which tell us exactly which interfaces map to Multus net1, net2, ...
echo "📡 Configuring network interfaces..."
echo "  Available interfaces:"
ip link show | grep -E "^[0-9]+:" | awk '{print "    " $2}' | tr -d ':'

LINK_COUNT=$(get_config "link.count")
OSPF_INTERFACES=()

if [ -n "$LINK_COUNT" ] && [ "$LINK_COUNT" -gt 0 ] 2>/dev/null; then
    # Use explicit link-to-interface mapping from wizard
    echo "  Using link mapping (${LINK_COUNT} links)..."
    for link_idx in $(seq 0 $((LINK_COUNT - 1))); do
        IFACE_INDEX=$(get_config "link.${link_idx}.interface_index")
        IFACE_NAME=$(get_config "link.${link_idx}.interface_name")
        IF_ADDR=$(get_config "interface.${IFACE_INDEX}.address.0")
        IF_TYPE=$(get_config "interface.${IFACE_INDEX}.type")

        REAL_IF="net$((link_idx + 1))"

        if ip link show ${REAL_IF} > /dev/null 2>&1; then
            echo "  → Link ${link_idx}: ${IFACE_NAME} (interface.${IFACE_INDEX}) → ${REAL_IF}"

            if [ -n "$IF_ADDR" ]; then
                ip addr flush dev ${REAL_IF} scope global
                ip addr add ${IF_ADDR} dev ${REAL_IF}
                ip link set ${REAL_IF} up
                echo "    ✓ ${REAL_IF}: ${IF_ADDR}"
            fi

            OSPF_INTERFACES+=("${REAL_IF}")
        else
            echo "  ⚠ Warning: ${REAL_IF} not found (expected for link ${link_idx})"
        fi
    done
else
    # Fallback: map non-loopback/non-gre interfaces in order
    echo "  Using interface order fallback..."
    NET_INDEX=1
    for i in 0 1 2 3 4 5; do
        IF_NAME=$(get_config "interface.${i}.name")
        IF_TYPE=$(get_config "interface.${i}.type")
        IF_ADDR=$(get_config "interface.${i}.address.0")

        if [ -z "$IF_NAME" ]; then
            continue
        fi

        # Skip loopback and tunnel interfaces
        if [ "$IF_TYPE" = "loopback" ] || [ "$IF_TYPE" = "lo" ] || [[ "$IF_NAME" == lo* ]]; then
            continue
        fi
        if [ "$IF_TYPE" = "gre" ] || [ "$IF_TYPE" = "vxlan" ] || [ "$IF_TYPE" = "tunnel" ]; then
            continue
        fi

        REAL_IF="net${NET_INDEX}"
        if ip link show ${REAL_IF} > /dev/null 2>&1; then
            echo "  → Configuring ${IF_NAME} on ${REAL_IF} (${IF_TYPE})"
            if [ -n "$IF_ADDR" ]; then
                ip addr flush dev ${REAL_IF} scope global
                ip addr add ${IF_ADDR} dev ${REAL_IF}
                ip link set ${REAL_IF} up
                echo "    ✓ ${REAL_IF}: ${IF_ADDR}"
            fi
            OSPF_INTERFACES+=("${REAL_IF}")
            NET_INDEX=$((NET_INDEX + 1))
        else
            echo "  ⚠ Warning: ${REAL_IF} not found (expected for ${IF_NAME})"
        fi
    done
fi

# Add GRE tunnel interfaces to OSPF (created at runtime by the agent, not Multus)
for i in 0 1 2 3 4 5; do
    IF_NAME=$(get_config "interface.${i}.name")
    IF_TYPE=$(get_config "interface.${i}.type")
    if [ -z "$IF_NAME" ]; then continue; fi
    if [ "$IF_TYPE" = "gre" ]; then
        echo "  → GRE tunnel ${IF_NAME} will be added to OSPF (created at runtime)"
        OSPF_INTERFACES+=("${IF_NAME}")
    fi
done

# Build command-line arguments for wontyoubemyneighbor.py
echo "🔧 Building routing protocol configuration..."

PROTO0_TYPE=$(get_config "protocol.0.type")
PROTO0_ROUTERID=$(get_config "protocol.0.routerId")
PROTO0_AREA=$(get_config "protocol.0.area")
PROTO0_HELLO=$(get_config "protocol.0.helloInterval")
PROTO0_DEAD=$(get_config "protocol.0.deadInterval")
PROTO0_NETWORK_TYPE=$(get_config "protocol.0.network_type")

PROTO1_TYPE=$(get_config "protocol.1.type")
PROTO1_ASN=$(get_config "protocol.1.asn")
PROTO1_ROUTERID=$(get_config "protocol.1.routerId")

ARGS=""

# OSPF configuration
if [ "$PROTO0_TYPE" = "ospf" ]; then
    echo "  ✓ OSPF: router-id ${PROTO0_ROUTERID}, area ${PROTO0_AREA}"
    ARGS="${ARGS} --router-id ${PROTO0_ROUTERID}"
    ARGS="${ARGS} --area ${PROTO0_AREA}"

    # Pass network type (point-to-point is critical for /30 and /31 links)
    if [ -n "$PROTO0_NETWORK_TYPE" ]; then
        ARGS="${ARGS} --network-type ${PROTO0_NETWORK_TYPE}"
        echo "  ✓ Network type: ${PROTO0_NETWORK_TYPE}"
    fi

    # Add all tracked interfaces to OSPF
    for iface in "${OSPF_INTERFACES[@]}"; do
        ARGS="${ARGS} --interface ${iface}"
        echo "    → OSPF on ${iface}"
    done

    # OSPF options
    if [ -n "$PROTO0_HELLO" ]; then
        ARGS="${ARGS} --hello-interval ${PROTO0_HELLO}"
    fi
    if [ -n "$PROTO0_DEAD" ]; then
        ARGS="${ARGS} --dead-interval ${PROTO0_DEAD}"
    fi
fi

# BGP configuration
if [ "$PROTO1_TYPE" = "bgp" ]; then
    echo "  ✓ BGP: AS ${PROTO1_ASN}"
    ARGS="${ARGS} --bgp-local-as ${PROTO1_ASN}"
fi

# Build ASI_AGENT_CONFIG JSON from ConfigMap keys
echo "📋 Building agent config JSON from ConfigMap..."
AGENT_CONFIG_JSON=$(python3 -c "
import os, json

config_dir = '${CONFIG_DIR}'
agent_name = '${AGENT_NAME}'

# Build interfaces array from ConfigMap keys
interfaces = []
i = 0
while True:
    name_file = os.path.join(config_dir, f'interface.{i}.name')
    if not os.path.exists(name_file):
        break
    iface = {}
    for key in ['name', 'type', 'address.0']:
        fpath = os.path.join(config_dir, f'interface.{i}.{key}')
        if os.path.exists(fpath):
            val = open(fpath).read().strip()
            if key == 'name':
                iface['n'] = val
                iface['id'] = val
            elif key == 'type':
                iface['t'] = val
            elif key == 'address.0' and val:
                iface['a'] = [val]
    # Read MTU if present, default 1400 for GRE, 1500 otherwise
    mtu_path = os.path.join(config_dir, f'interface.{i}.mtu')
    if os.path.exists(mtu_path):
        iface['mtu'] = int(open(mtu_path).read().strip())
    elif iface.get('t') == 'gre':
        iface['mtu'] = 1400
    # Read GRE/tunnel config if present
    tun_path = os.path.join(config_dir, f'interface.{i}.tun')
    if os.path.exists(tun_path):
        tun_json = open(tun_path).read().strip()
        if tun_json:
            iface['tun'] = json.loads(tun_json)
    iface['s'] = 'up'
    interfaces.append(iface)
    i += 1

# Build protocols array
protos = []
j = 0
while True:
    type_file = os.path.join(config_dir, f'protocol.{j}.type')
    if not os.path.exists(type_file):
        break
    proto = {'p': open(type_file).read().strip()}
    for key in ['area', 'routerId', 'asn']:
        fpath = os.path.join(config_dir, f'protocol.{j}.{key}')
        if os.path.exists(fpath):
            proto[key[:3] if key == 'routerId' else key] = open(fpath).read().strip()
    protos.append(proto)
    j += 1

config = {
    'n': agent_name,
    'ifs': interfaces,
    'protos': protos,
}
print(json.dumps(config))
")

export ASI_AGENT_CONFIG="${AGENT_CONFIG_JSON}"
echo "  ✓ ASI_AGENT_CONFIG set (${#AGENT_CONFIG_JSON} bytes)"

echo ""
echo "🎯 Starting routing agent..."
echo "Command: python wontyoubemyneighbor.py ${ARGS}"
echo ""

# Start the agent
cd /app
exec python wontyoubemyneighbor.py ${ARGS}
