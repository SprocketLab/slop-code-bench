#!/usr/bin/env python3
"""
Network monitoring and analysis toolkit.
Provides utilities for monitoring network traffic, analyzing protocols,
and generating network statistics and reports.
"""

import json
import logging
import threading
import time
from collections import defaultdict
from collections import deque
from dataclasses import asdict
from dataclasses import dataclass
from typing import Any

import psutil

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class NetworkPacket:
    """Represents a network packet with basic metadata."""

    timestamp: float
    source_ip: str
    dest_ip: str
    source_port: int
    dest_port: int
    protocol: str
    size: int
    flags: list[str]


@dataclass
class ConnectionInfo:
    """Information about a network connection."""

    local_address: str
    local_port: int
    remote_address: str
    remote_port: int
    status: str
    pid: int
    process_name: str


class NetworkMonitor:
    """Main class for monitoring network activity."""

    def __init__(self, interface: str = "eth0", buffer_size: int = 10000):
        """
        Initialize the network monitor.

        Args:
            interface: Network interface to monitor
            buffer_size: Size of packet buffer
        """
        self.interface = interface
        self.buffer_size = buffer_size
        self.packet_buffer = deque(maxlen=buffer_size)
        self.is_monitoring = False
        self.monitor_thread = None
        self.stats = defaultdict(int)
        self.connections = {}

    def start_monitoring(self) -> None:
        """Start monitoring network traffic."""
        if self.is_monitoring:
            logger.warning("Monitoring already started")
            return

        self.is_monitoring = True
        self.monitor_thread = threading.Thread(
            target=self._monitor_loop, daemon=True
        )
        self.monitor_thread.start()
        logger.info(f"Started monitoring on interface {self.interface}")

    def stop_monitoring(self) -> None:
        """Stop monitoring network traffic."""
        if not self.is_monitoring:
            logger.warning("Monitoring not active")
            return

        self.is_monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        logger.info("Stopped network monitoring")

    def _monitor_loop(self) -> None:
        """Main monitoring loop (simulated)."""
        while self.is_monitoring:
            try:
                # Simulate packet capture
                packet = self._simulate_packet()
                if packet:
                    self.packet_buffer.append(packet)
                    self._update_stats(packet)
                time.sleep(0.01)  # Simulate packet arrival rate
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")

    def _simulate_packet(self) -> NetworkPacket | None:
        """Simulate network packet generation for testing."""
        import random

        # Simulate different types of traffic
        protocols = ["TCP", "UDP", "ICMP"]
        source_ips = ["192.168.1.100", "10.0.0.50", "172.16.0.10", "8.8.8.8"]
        dest_ips = ["192.168.1.1", "10.0.0.1", "172.16.0.1", "1.1.1.1"]

        if random.random() < 0.8:  # 80% chance to generate a packet
            return NetworkPacket(
                timestamp=time.time(),
                source_ip=random.choice(source_ips),
                dest_ip=random.choice(dest_ips),
                source_port=random.randint(1024, 65535),
                dest_port=random.choice([80, 443, 22, 53, 25, 110, 143]),
                protocol=random.choice(protocols),
                size=random.randint(64, 1500),
                flags=random.sample(
                    ["SYN", "ACK", "FIN", "RST", "PSH", "URG"],
                    k=random.randint(0, 3),
                ),
            )
        return None

    def _update_stats(self, packet: NetworkPacket) -> None:
        """Update network statistics based on packet."""
        self.stats[f"packets_{packet.protocol.lower()}"] += 1
        self.stats["total_packets"] += 1
        self.stats["total_bytes"] += packet.size

        # Update per-protocol byte counts
        self.stats[f"bytes_{packet.protocol.lower()}"] += packet.size

    def get_active_connections(self) -> list[ConnectionInfo]:
        """Get list of active network connections."""
        connections = []

        try:
            for conn in psutil.net_connections():
                if conn.status == "ESTABLISHED":
                    try:
                        pid = conn.pid or 0
                        process_name = "Unknown"
                        if pid > 0:
                            process = psutil.Process(pid)
                            process_name = process.name()

                        connection = ConnectionInfo(
                            local_address=conn.laddr.ip
                            if conn.laddr
                            else "N/A",
                            local_port=conn.laddr.port if conn.laddr else 0,
                            remote_address=conn.raddr.ip
                            if conn.raddr
                            else "N/A",
                            remote_port=conn.raddr.port if conn.raddr else 0,
                            status=conn.status,
                            pid=pid,
                            process_name=process_name,
                        )
                        connections.append(connection)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
        except Exception as e:
            logger.error(f"Error getting connections: {e}")

        return connections

    def get_network_interfaces(self) -> dict[str, dict[str, Any]]:
        """Get information about network interfaces."""
        interfaces = {}

        try:
            net_if_addrs = psutil.net_if_addrs()
            net_if_stats = psutil.net_if_stats()

            for interface_name, addresses in net_if_addrs.items():
                interface_info = {
                    "addresses": [],
                    "is_up": False,
                    "speed": 0,
                    "mtu": 0,
                }

                for addr in addresses:
                    interface_info["addresses"].append(
                        {
                            "family": str(addr.family),
                            "address": addr.address,
                            "netmask": addr.netmask,
                            "broadcast": addr.broadcast,
                        }
                    )

                if interface_name in net_if_stats:
                    stats = net_if_stats[interface_name]
                    interface_info.update(
                        {
                            "is_up": stats.isup,
                            "speed": stats.speed,
                            "mtu": stats.mtu,
                        }
                    )

                interfaces[interface_name] = interface_info
        except Exception as e:
            logger.error(f"Error getting interfaces: {e}")

        return interfaces

    def get_bandwidth_usage(self) -> dict[str, Any]:
        """Get current bandwidth usage statistics."""
        try:
            net_io = psutil.net_io_counters()
            return {
                "bytes_sent": net_io.bytes_sent,
                "bytes_recv": net_io.bytes_recv,
                "packets_sent": net_io.packets_sent,
                "packets_recv": net_io.packets_recv,
                "errin": net_io.errin,
                "errout": net_io.errout,
                "dropin": net_io.dropin,
                "dropout": net_io.dropout,
            }
        except Exception as e:
            logger.error(f"Error getting bandwidth usage: {e}")
            return {}

    def analyze_traffic_patterns(
        self, time_window: float = 60.0
    ) -> dict[str, Any]:
        """
        Analyze traffic patterns over a time window.

        Args:
            time_window: Time window in seconds to analyze

        Returns:
            Dictionary containing traffic analysis
        """
        current_time = time.time()
        recent_packets = [
            p
            for p in self.packet_buffer
            if current_time - p.timestamp <= time_window
        ]

        if not recent_packets:
            return {"error": "No recent packets to analyze"}

        # Protocol distribution
        protocol_counts = defaultdict(int)
        port_counts = defaultdict(int)
        ip_counts = defaultdict(int)

        for packet in recent_packets:
            protocol_counts[packet.protocol] += 1
            port_counts[packet.dest_port] += 1
            ip_counts[packet.dest_ip] += 1

        # Calculate statistics
        total_packets = len(recent_packets)
        avg_packet_size = sum(p.size for p in recent_packets) / total_packets

        return {
            "time_window": time_window,
            "total_packets": total_packets,
            "avg_packet_size": round(avg_packet_size, 2),
            "protocol_distribution": dict(protocol_counts),
            "top_destination_ports": dict(
                sorted(port_counts.items(), key=lambda x: x[1], reverse=True)[
                    :10
                ]
            ),
            "top_destination_ips": dict(
                sorted(ip_counts.items(), key=lambda x: x[1], reverse=True)[:10]
            ),
            "packets_per_second": round(total_packets / time_window, 2),
        }

    def export_data(self, filename: str, format_type: str = "json") -> None:
        """
        Export monitoring data to file.

        Args:
            filename: Output filename
            format_type: Export format (json, csv)
        """
        data = {
            "timestamp": time.time(),
            "interface": self.interface,
            "statistics": dict(self.stats),
            "connections": [
                asdict(conn) for conn in self.get_active_connections()
            ],
            "interfaces": self.get_network_interfaces(),
            "bandwidth": self.get_bandwidth_usage(),
            "traffic_analysis": self.analyze_traffic_patterns(),
        }

        if format_type.lower() == "json":
            with open(filename, "w") as f:
                json.dump(data, f, indent=2, default=str)
        elif format_type.lower() == "csv":
            import csv

            with open(filename, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["Metric", "Value"])
                for key, value in data["statistics"].items():
                    writer.writerow([key, value])

        logger.info(f"Data exported to {filename}")


def main():
    """Example usage of the NetworkMonitor class."""
    monitor = NetworkMonitor()

    try:
        print("Starting network monitor...")
        monitor.start_monitoring()

        # Let it run for a bit
        time.sleep(5)

        # Get some statistics
        print(f"Total packets captured: {monitor.stats['total_packets']}")
        print(f"Total bytes: {monitor.stats['total_bytes']}")

        # Get active connections
        connections = monitor.get_active_connections()
        print(f"Active connections: {len(connections)}")

        # Analyze traffic patterns
        analysis = monitor.analyze_traffic_patterns()
        if "error" not in analysis:
            print(f"Packets per second: {analysis['packets_per_second']}")

        # Export data
        monitor.export_data("network_data.json")

    except KeyboardInterrupt:
        print("\nStopping monitor...")
    finally:
        monitor.stop_monitoring()


if __name__ == "__main__":
    main()
