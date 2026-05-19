import argparse
import os
import socket
import struct
import time
from typing import Optional


ICMP_ECHO_REQUEST = 8
ICMP_ECHO_REPLY = 0
ICMP_TIME_EXCEEDED = 11
ICMP_DEST_UNREACHABLE = 3


def checksum(data: bytes) -> int:
    if len(data) % 2:
        data += b"\x00"
    total = 0
    for i in range(0, len(data), 2):
        total += (data[i] << 8) + data[i + 1]
    total = (total >> 16) + (total & 0xFFFF)
    total += total >> 16
    return (~total) & 0xFFFF


def build_echo_request(ident: int, seq: int) -> bytes:
    payload = struct.pack("!d", time.time())
    header = struct.pack("!BBHHH", ICMP_ECHO_REQUEST, 0, 0, ident, seq)
    chksum = checksum(header + payload)
    header = struct.pack("!BBHHH", ICMP_ECHO_REQUEST, 0, chksum, ident, seq)
    return header + payload


def resolve_name(ip: str) -> Optional[str]:
    try:
        name, _, _ = socket.gethostbyaddr(ip)
        return name
    except socket.herror:
        return None
    except OSError:
        return None


def parse_icmp_reply(packet: bytes, expected_id: int, expected_seq: int) -> Optional[tuple[int, str]]:
    if len(packet) < 20:
        return None
    ip_header_len = (packet[0] & 0x0F) * 4
    if len(packet) < ip_header_len + 8:
        return None

    icmp_offset = ip_header_len
    icmp_type, _, _, recv_id, recv_seq = struct.unpack(
        "!BBHHH", packet[icmp_offset : icmp_offset + 8]
    )

    if icmp_type == ICMP_ECHO_REPLY:
        if recv_id == expected_id and recv_seq == expected_seq:
            return icmp_type, "matched"
        return None

    if icmp_type in (ICMP_TIME_EXCEEDED, ICMP_DEST_UNREACHABLE):
        inner_ip_offset = icmp_offset + 8
        if len(packet) < inner_ip_offset + 20:
            return None
        inner_ip_len = (packet[inner_ip_offset] & 0x0F) * 4
        inner_icmp_offset = inner_ip_offset + inner_ip_len
        if len(packet) < inner_icmp_offset + 8:
            return None
        inner_type, _, _, inner_id, inner_seq = struct.unpack(
            "!BBHHH", packet[inner_icmp_offset : inner_icmp_offset + 8]
        )
        if inner_type == ICMP_ECHO_REQUEST and inner_id == expected_id and inner_seq == expected_seq:
            return icmp_type, "matched"

    return None


def traceroute(
    destination: str,
    max_hops: int,
    probes_per_hop: int,
    timeout: float,
    resolve_hostnames: bool,
) -> None:
    try:
        destination_ip = socket.gethostbyname(destination)
    except socket.gaierror as exc:
        raise RuntimeError(f"Could not resolve destination '{destination}': {exc}") from exc

    ident = os.getpid() & 0xFFFF

    print(f"Traceroute to {destination} ({destination_ip}), max hops: {max_hops}, probes per hop: {probes_per_hop}")

    with socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP) as sock:
        sock.settimeout(timeout)
        reached_destination = False

        for ttl in range(1, max_hops + 1):
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_TTL, ttl)
            hop_times: list[Optional[float]] = []
            hop_ips: list[Optional[str]] = []
            hop_reached_destination = False

            for probe in range(probes_per_hop):
                seq = ttl * probes_per_hop + probe
                packet = build_echo_request(ident, seq)
                send_time = time.perf_counter()
                try:
                    sock.sendto(packet, (destination_ip, 0))
                except OSError as exc:
                    hop_times.append(None)
                    hop_ips.append(None)
                    print(f"{ttl:2d}  send failed: {exc}")
                    continue

                probe_ip: Optional[str] = None
                probe_rtt_ms: Optional[float] = None
                probe_final = False
                deadline = send_time + timeout

                while time.perf_counter() < deadline:
                    remaining = deadline - time.perf_counter()
                    if remaining <= 0:
                        break
                    sock.settimeout(remaining)
                    try:
                        reply, addr = sock.recvfrom(65535)
                    except socket.timeout:
                        break
                    except OSError:
                        break

                    parsed = parse_icmp_reply(reply, ident, seq)
                    if not parsed:
                        continue

                    icmp_type, _ = parsed
                    probe_ip = addr[0]
                    probe_rtt_ms = (time.perf_counter() - send_time) * 1000
                    if icmp_type == ICMP_ECHO_REPLY:
                        probe_final = True
                    break

                hop_ips.append(probe_ip)
                hop_times.append(probe_rtt_ms)
                if probe_final:
                    hop_reached_destination = True

            unique_hop_ips = [ip for ip in dict.fromkeys(ip for ip in hop_ips if ip is not None)]
            if not unique_hop_ips:
                host_label = "*"
            elif len(unique_hop_ips) == 1:
                ip = unique_hop_ips[0]
                if resolve_hostnames:
                    name = resolve_name(ip)
                    host_label = f"{name} ({ip})" if name else ip
                else:
                    host_label = ip
            else:
                labeled_ips = []
                for ip in unique_hop_ips:
                    if resolve_hostnames:
                        name = resolve_name(ip)
                        labeled_ips.append(f"{name} ({ip})" if name else ip)
                    else:
                        labeled_ips.append(ip)
                host_label = ", ".join(labeled_ips)

            rtt_label_parts = [f"{rtt:.2f} ms" if rtt is not None else "*" for rtt in hop_times]
            print(f"{ttl:2d}  {host_label:45s}  {'  '.join(rtt_label_parts)}")

            if hop_reached_destination:
                reached_destination = True
                break

        if not reached_destination:
            print("Destination not reached within max hops.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ICMP traceroute built on raw sockets")
    parser.add_argument("destination", help="Destination hostname or IPv4 address")
    parser.add_argument(
        "--max-hops",
        type=int,
        default=30,
        help="Maximum TTL (default: 30)",
    )
    parser.add_argument(
        "--probes",
        type=int,
        default=3,
        help="Number of probes per hop (default: 3)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=1.0,
        help="Timeout per probe in seconds (default: 1.0)",
    )
    parser.add_argument(
        "--no-dns",
        action="store_true",
        help="Do not resolve intermediate hop hostnames",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.max_hops <= 0:
        raise ValueError("--max-hops must be positive")
    if args.probes <= 0:
        raise ValueError("--probes must be positive")
    if args.timeout <= 0:
        raise ValueError("--timeout must be positive")

    traceroute(
        destination=args.destination,
        max_hops=args.max_hops,
        probes_per_hop=args.probes,
        timeout=args.timeout,
        resolve_hostnames=not args.no_dns,
    )


if __name__ == "__main__":
    try:
        main()
    except PermissionError:
        print("Permission denied: raw ICMP sockets require elevated privileges.")
        print("Run with sudo, for example: sudo python3 lab11/icmp_traceroute.py google.com")
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
    except Exception as exc:
        print(f"Error: {exc}")
