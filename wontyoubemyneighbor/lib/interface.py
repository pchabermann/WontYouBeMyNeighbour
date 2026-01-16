"""
Network Interface Management
Get interface information (IP, netmask, MAC, MTU)
"""

import socket
import struct
import logging
from typing import Optional
import platform

logger = logging.getLogger(__name__)


def get_ip_address(interface: str) -> Optional[str]:
    """
    Get IP address of network interface

    Args:
        interface: Interface name (e.g., 'eth0')

    Returns:
        IP address as string or None if not found
    """
    try:
        import netifaces
        addrs = netifaces.ifaddresses(interface)
        if netifaces.AF_INET in addrs:
            return addrs[netifaces.AF_INET][0]['addr']
        return None
    except ImportError:
        # Fallback without netifaces
        try:
            import fcntl
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            ip = socket.inet_ntoa(fcntl.ioctl(
                s.fileno(),
                0x8915,  # SIOCGIFADDR
                struct.pack('256s', interface[:15].encode())
            )[20:24])
            s.close()
            return ip
        except Exception as e:
            logger.error(f"Failed to get IP address for {interface}: {e}")
            return None


def get_all_ip_addresses(interface: str) -> list:
    """
    Get all IP addresses of network interface

    Args:
        interface: Interface name (e.g., 'eth0')

    Returns:
        List of IP addresses as strings
    """
    try:
        import netifaces
        addrs = netifaces.ifaddresses(interface)
        if netifaces.AF_INET in addrs:
            return [addr['addr'] for addr in addrs[netifaces.AF_INET]]
        return []
    except ImportError:
        # Fallback - can only get one address
        ip = get_ip_address(interface)
        return [ip] if ip else []
    except Exception as e:
        logger.error(f"Failed to get IP addresses for {interface}: {e}")
        return []


def verify_ip_on_interface(interface: str, ip_address: str) -> bool:
    """
    Verify that a specific IP address exists on an interface

    Args:
        interface: Interface name
        ip_address: IP address to verify

    Returns:
        True if IP exists on interface
    """
    all_ips = get_all_ip_addresses(interface)
    return ip_address in all_ips


def get_netmask(interface: str, ip_address: Optional[str] = None) -> Optional[str]:
    """
    Get netmask of network interface for a specific IP or the first one

    Args:
        interface: Interface name
        ip_address: Optional specific IP to get netmask for

    Returns:
        Netmask as string or None if not found
    """
    try:
        import netifaces
        addrs = netifaces.ifaddresses(interface)
        if netifaces.AF_INET in addrs:
            if ip_address:
                # Find netmask for specific IP
                for addr_info in addrs[netifaces.AF_INET]:
                    if addr_info['addr'] == ip_address:
                        return addr_info['netmask']
                logger.warning(f"IP {ip_address} not found on {interface}")
                return None
            else:
                # Return first netmask
                return addrs[netifaces.AF_INET][0]['netmask']
        return None
    except ImportError:
        # Fallback without netifaces
        try:
            import fcntl
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            netmask = socket.inet_ntoa(fcntl.ioctl(
                s.fileno(),
                0x891b,  # SIOCGIFNETMASK
                struct.pack('256s', interface[:15].encode())
            )[20:24])
            s.close()
            return netmask
        except Exception as e:
            logger.error(f"Failed to get netmask for {interface}: {e}")
            return None


def get_mac_address(interface: str) -> Optional[str]:
    """
    Get MAC address of network interface

    Args:
        interface: Interface name

    Returns:
        MAC address as string (format: XX:XX:XX:XX:XX:XX) or None
    """
    try:
        import netifaces
        addrs = netifaces.ifaddresses(interface)
        if netifaces.AF_LINK in addrs:
            return addrs[netifaces.AF_LINK][0]['addr']
        return None
    except ImportError:
        # Fallback without netifaces
        try:
            import fcntl
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            info = fcntl.ioctl(
                s.fileno(),
                0x8927,  # SIOCGIFHWADDR
                struct.pack('256s', interface[:15].encode())
            )
            s.close()
            mac = ':'.join(['%02x' % b for b in info[18:24]])
            return mac
        except Exception as e:
            logger.error(f"Failed to get MAC address for {interface}: {e}")
            return None


def get_mtu(interface: str) -> int:
    """
    Get MTU of network interface

    Args:
        interface: Interface name

    Returns:
        MTU in bytes (default 1500 if unavailable)
    """
    try:
        import netifaces
        # Note: netifaces doesn't directly provide MTU, so we use fallback
        raise ImportError
    except ImportError:
        # Fallback
        try:
            import fcntl
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            mtu = struct.unpack('I', fcntl.ioctl(
                s.fileno(),
                0x8921,  # SIOCGIFMTU
                struct.pack('256s', interface[:15].encode())
            )[16:20])[0]
            s.close()
            return mtu
        except Exception as e:
            logger.warning(f"Failed to get MTU for {interface}, using default 1500: {e}")
            return 1500


def is_interface_up(interface: str) -> bool:
    """
    Check if interface is up

    Args:
        interface: Interface name

    Returns:
        True if interface is up
    """
    try:
        import netifaces
        return interface in netifaces.interfaces()
    except ImportError:
        # Fallback - try to get IP address
        return get_ip_address(interface) is not None


def list_interfaces() -> list:
    """
    List all network interfaces

    Returns:
        List of interface names
    """
    try:
        import netifaces
        return netifaces.interfaces()
    except ImportError:
        # Fallback - parse /proc/net/dev on Linux
        try:
            with open('/proc/net/dev', 'r') as f:
                lines = f.readlines()[2:]  # Skip header
                interfaces = []
                for line in lines:
                    interface = line.split(':')[0].strip()
                    interfaces.append(interface)
                return interfaces
        except Exception:
            logger.warning("Failed to list interfaces")
            return []


class InterfaceInfo:
    """
    Container for network interface information
    """

    def __init__(self, interface: str, source_ip: Optional[str] = None):
        """
        Initialize and gather interface information

        Args:
            interface: Interface name
            source_ip: Optional specific IP to use (if interface has multiple IPs)
        """
        self.interface = interface

        # If source_ip specified, verify it exists on interface
        if source_ip:
            if not verify_ip_on_interface(interface, source_ip):
                all_ips = get_all_ip_addresses(interface)
                raise ValueError(
                    f"IP {source_ip} not found on {interface}. "
                    f"Available IPs: {', '.join(all_ips) if all_ips else 'none'}"
                )
            self.ip_address = source_ip
            self.netmask = get_netmask(interface, source_ip)
        else:
            # Auto-detect first IP
            self.ip_address = get_ip_address(interface)
            self.netmask = get_netmask(interface)

        self.mac_address = get_mac_address(interface)
        self.mtu = get_mtu(interface)
        self.is_up = is_interface_up(interface)

    def validate(self) -> bool:
        """
        Validate that interface has minimum required information

        Returns:
            True if interface is usable for OSPF
        """
        if not self.is_up:
            logger.error(f"Interface {self.interface} is not up")
            return False

        if not self.ip_address:
            logger.error(f"Interface {self.interface} has no IP address")
            return False

        if not self.netmask:
            logger.error(f"Interface {self.interface} has no netmask")
            return False

        return True

    def __repr__(self) -> str:
        return (f"InterfaceInfo(interface={self.interface}, "
                f"ip={self.ip_address}, "
                f"netmask={self.netmask}, "
                f"mac={self.mac_address}, "
                f"mtu={self.mtu}, "
                f"up={self.is_up})")


def get_interface_info(interface: str, source_ip: Optional[str] = None) -> Optional[InterfaceInfo]:
    """
    Get complete interface information

    Args:
        interface: Interface name
        source_ip: Optional specific IP to use (if interface has multiple IPs)

    Returns:
        InterfaceInfo object or None if interface invalid
    """
    try:
        info = InterfaceInfo(interface, source_ip)

        if not info.validate():
            return None

        return info
    except ValueError as e:
        logger.error(str(e))
        return None
