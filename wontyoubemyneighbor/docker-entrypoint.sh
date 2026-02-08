#!/bin/bash
# Docker entrypoint script for ASI Agent containers
# Starts LLDP daemon for Layer 2 neighbor discovery, then runs the agent

# Start LLDP daemon in the background
# -d: daemonize, -c: configure mode, -e: enable receiving
if command -v lldpd &> /dev/null; then
    echo "Starting LLDP daemon..."
    # Start lldpd with agent name as system name
    SYSTEM_NAME="${AGENT_NAME:-asi-agent}"
    SYSTEM_DESC="ASI Agent - Won't You Be My Neighbor"

    # Start lldpd daemon
    lldpd -c -e

    # Configure system info via lldpcli
    sleep 1
    lldpcli configure system hostname "$SYSTEM_NAME" 2>/dev/null || true
    lldpcli configure system description "$SYSTEM_DESC" 2>/dev/null || true

    echo "LLDP daemon started"
else
    echo "Warning: lldpd not installed, LLDP discovery disabled"
fi

# Setup GRE tunnels if configured via environment variables
# Format: GRE_TUNNEL_<N>="name:local_ip:remote_ip:tunnel_ip:key:ttl:mtu"
echo "========== GRE DEBUG: Checking for GRE_TUNNEL environment variables =========="
env | grep "^GRE" || echo "No GRE environment variables found"
echo "==========================================================================="

for var in $(env | grep "^GRE_TUNNEL_" | cut -d= -f1); do
    tunnel_config="${!var}"
    IFS=':' read -r tunnel_name local_ip remote_ip tunnel_ip key ttl mtu <<< "$tunnel_config"

    # Special handling: gre0 is a default Linux interface that can't be deleted/recreated
    # Automatically rename gre0 to gre1 for user-defined tunnels
    if [ "$tunnel_name" = "gre0" ]; then
        echo "Note: Renaming tunnel from gre0 to gre1 (gre0 is a special Linux interface)"
        tunnel_name="gre1"
    fi

    echo "Setting up GRE tunnel: $tunnel_name ($local_ip -> $remote_ip)"

    # Wait for local IP to be configured (external network connection)
    # Try for up to 10 seconds
    for i in {1..20}; do
        if ip addr show | grep -q "$local_ip"; then
            echo "Local IP $local_ip is configured"
            break
        fi
        echo "Waiting for local IP $local_ip... ($i/20)"
        sleep 0.5
    done

    # Verify local IP exists
    if ! ip addr show | grep -q "$local_ip"; then
        echo "ERROR: Local IP $local_ip not found. Skipping tunnel $tunnel_name"
        continue
    fi

    echo "Creating GRE tunnel: $tunnel_name"

    # Check if tunnel already exists (gre0 is a default interface)
    if ip tunnel show | grep -q "^$tunnel_name:"; then
        echo "Tunnel $tunnel_name exists, deleting and recreating..."
        ip tunnel del $tunnel_name 2>/dev/null || true
        sleep 0.5
    fi

    # Build tunnel command
    tunnel_cmd="ip tunnel add $tunnel_name mode gre local $local_ip remote $remote_ip ttl $ttl"
    if [ -n "$key" ] && [ "$key" != "none" ]; then
        tunnel_cmd="$tunnel_cmd key $key"
    fi
    tunnel_cmd="$tunnel_cmd pmtudisc"

    # Create tunnel
    eval $tunnel_cmd || echo "Warning: Failed to create tunnel $tunnel_name"

    # Assign IP
    ip addr add $tunnel_ip dev $tunnel_name || echo "Warning: Failed to assign IP to $tunnel_name"

    # Set MTU
    ip link set $tunnel_name mtu $mtu || echo "Warning: Failed to set MTU on $tunnel_name"

    # Bring up
    ip link set $tunnel_name up || echo "Warning: Failed to bring up $tunnel_name"

    echo "GRE tunnel $tunnel_name is up"

    # Disable default gre0 if we created a custom tunnel
    if [ "$tunnel_name" != "gre0" ]; then
        ip link set gre0 down 2>/dev/null || true
    fi
done

# Configure interface IPs from ASI_AGENT_CONFIG
if [ -n "$ASI_AGENT_CONFIG" ]; then
    echo "========== Configuring interface IPs from ASI_AGENT_CONFIG =========="

    # Extract interface configs using Python
    python3 << 'PYTHON_SCRIPT'
import json
import os
import subprocess

config = json.loads(os.environ['ASI_AGENT_CONFIG'])
interfaces = config.get('ifs', [])

for iface in interfaces:
    iface_name = iface.get('n') or iface.get('id')
    addresses = iface.get('a', [])
    iface_type = iface.get('t', 'eth')

    # Skip loopback interfaces (handled separately)
    if iface_type == 'lo':
        continue

    # Check if interface exists
    try:
        subprocess.run(['ip', 'link', 'show', iface_name],
                      check=True, capture_output=True)
        target_iface = iface_name
    except subprocess.CalledProcessError:
        # Interface doesn't exist - add IPs to eth0 instead (logical interface)
        print(f"  Interface {iface_name} does not exist, adding IPs to eth0 instead (logical interface)")
        target_iface = 'eth0'

    # Add each IP address to the interface
    for addr in addresses:
        if not addr:
            continue

        # Check if IP is already configured on target interface
        result = subprocess.run(['ip', 'addr', 'show', target_iface],
                              capture_output=True, text=True)
        if addr in result.stdout:
            print(f"  ✓ {target_iface} already has {addr} (logical: {iface_name})")
            continue

        # Add the IP address to target interface
        try:
            subprocess.run(['ip', 'addr', 'add', addr, 'dev', target_iface],
                          check=True, capture_output=True)
            print(f"  ✓ Added {addr} to {target_iface} (logical: {iface_name})")
        except subprocess.CalledProcessError as e:
            print(f"  ✗ Failed to add {addr} to {target_iface} (logical: {iface_name}): {e}")

print("Interface IP configuration complete")
PYTHON_SCRIPT

    echo "===================================================================="
fi

# Execute the main command (passed as arguments)
exec "$@"
