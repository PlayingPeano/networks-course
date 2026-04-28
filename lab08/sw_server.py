import argparse
import socket
from pathlib import Path

from stop_and_wait_protocol import TYPE_ACK, TYPE_DATA, TYPE_END, TYPE_REQUEST, decode_frame, encode_frame, should_drop


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stop-and-Wait UDP server")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", type=int, default=9000, help="Bind port")
    parser.add_argument(
        "--output",
        default="received.bin",
        help="Path to output file that will be reconstructed from received packets",
    )
    parser.add_argument(
        "--loss-rate",
        type=float,
        default=0.3,
        help="Packet loss probability [0.0..1.0] applied to both incoming packets and outgoing ACKs",
    )
    parser.add_argument(
        "--serve-file",
        default="",
        help="Optional file path for server->client transfer when REQUEST is received",
    )
    parser.add_argument("--chunk-size", type=int, default=512, help="Payload size in bytes per DATA packet")
    parser.add_argument(
        "--timeout",
        type=float,
        default=0.5,
        help="Timeout in seconds to wait for ACK during server->client transfer",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=50,
        help="Maximum retransmissions per packet during server->client transfer",
    )
    return parser.parse_args()


def send_ack(sock: socket.socket, seq: int, addr, loss_rate: float) -> bool:
    ack = encode_frame(TYPE_ACK, seq)
    if should_drop(loss_rate):
        print(f"[server] ACK {seq} dropped (simulated)")
        return False
    sock.sendto(ack, addr)
    print(f"[server] ACK {seq} sent")
    return True


def wait_for_ack(sock: socket.socket, expected_seq: int, loss_rate: float) -> bool:
    while True:
        try:
            raw, _ = sock.recvfrom(65535)
        except socket.timeout:
            return False
        except OSError as exc:
            print(f"[server] Socket error while waiting ACK: {exc}")
            return False

        if should_drop(loss_rate):
            print("[server] ACK dropped on receive (simulated)")
            continue

        try:
            frame = decode_frame(raw)
        except ValueError as exc:
            print(f"[server] Broken frame ignored while waiting ACK: {exc}")
            continue

        if frame.frame_type != TYPE_ACK:
            print(f"[server] Non-ACK frame received (type={frame.frame_type}), ignored")
            continue
        if frame.seq != expected_seq:
            print(f"[server] ACK seq={frame.seq} does not match expected={expected_seq}, ignored")
            continue
        print(f"[server] ACK {frame.seq} received")
        return True


def send_with_retries(
    sock: socket.socket,
    client_addr: tuple[str, int],
    frame_type: int,
    seq: int,
    payload: bytes,
    timeout: float,
    loss_rate: float,
    max_retries: int,
) -> None:
    frame_name = {
        TYPE_DATA: "DATA",
        TYPE_END: "END",
    }.get(frame_type, f"TYPE_{frame_type}")
    packet = encode_frame(frame_type, seq, payload)

    for attempt in range(1, max_retries + 1):
        if should_drop(loss_rate):
            print(
                f"[server] {frame_name} seq={seq} dropped on send (simulated), "
                f"attempt={attempt}/{max_retries}"
            )
        else:
            sock.sendto(packet, client_addr)
            suffix = f", size={len(payload)}" if frame_type == TYPE_DATA else ""
            print(f"[server] {frame_name} seq={seq} sent{suffix}, attempt={attempt}/{max_retries}")

        sock.settimeout(timeout)
        if wait_for_ack(sock, seq, loss_rate):
            return
        print(f"[server] Timeout waiting ACK for seq={seq}, retransmit")

    raise RuntimeError(f"Failed to deliver seq={seq}: retries exhausted ({max_retries})")


def send_file_to_client(sock: socket.socket, client_addr: tuple[str, int], source_path: Path, args: argparse.Namespace) -> None:
    data = source_path.read_bytes()
    chunks = [data[i : i + args.chunk_size] for i in range(0, len(data), args.chunk_size)]
    if not chunks:
        chunks = [b""]

    seq = 0
    total_sent = 0

    print(f"[server] Sending file to client: {source_path.resolve()}")
    print(f"[server] File size: {len(data)} bytes, chunks: {len(chunks)}, chunk_size: {args.chunk_size}")

    for chunk in chunks:
        send_with_retries(
            sock=sock,
            client_addr=client_addr,
            frame_type=TYPE_DATA,
            seq=seq,
            payload=chunk,
            timeout=args.timeout,
            loss_rate=args.loss_rate,
            max_retries=args.max_retries,
        )
        total_sent += len(chunk)
        seq = 1 - seq

    send_with_retries(
        sock=sock,
        client_addr=client_addr,
        frame_type=TYPE_END,
        seq=seq,
        payload=b"",
        timeout=args.timeout,
        loss_rate=args.loss_rate,
        max_retries=args.max_retries,
    )
    print(f"[server] Server->client transfer complete, bytes acknowledged: {total_sent}")


def main() -> None:
    args = parse_args()
    if not (0 <= args.loss_rate <= 1):
        raise ValueError("--loss-rate must be in range [0.0, 1.0]")
    if args.chunk_size <= 0:
        raise ValueError("--chunk-size must be positive")
    if args.timeout <= 0:
        raise ValueError("--timeout must be positive")
    if args.max_retries <= 0:
        raise ValueError("--max-retries must be positive")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    serve_path = Path(args.serve_file) if args.serve_file else None
    if serve_path is not None and (not serve_path.exists() or not serve_path.is_file()):
        raise FileNotFoundError(f"Serve file does not exist: {serve_path}")

    expected_seq = 0
    client_addr = None
    received_bytes = 0

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock, output_path.open("wb") as fout:
        sock.bind((args.host, args.port))
        print(f"[server] Listening on {args.host}:{args.port}")
        print(f"[server] Output file: {output_path.resolve()}")
        print(f"[server] Simulated loss rate: {args.loss_rate * 100:.0f}%")
        if serve_path is not None:
            print(f"[server] Serve file for downloads: {serve_path.resolve()}")

        while True:
            try:
                raw, addr = sock.recvfrom(65535)
                client_addr = addr
            except OSError as exc:
                print(f"[server] Socket error: {exc}")
                continue

            if should_drop(args.loss_rate):
                print("[server] Incoming frame dropped (simulated)")
                continue

            try:
                frame = decode_frame(raw)
            except ValueError as exc:
                print(f"[server] Broken frame ignored: {exc}")
                continue

            if frame.frame_type == TYPE_DATA:
                if frame.seq == expected_seq:
                    fout.write(frame.payload)
                    received_bytes += len(frame.payload)
                    print(
                        f"[server] DATA seq={frame.seq} accepted, size={len(frame.payload)}, "
                        f"total_received={received_bytes}"
                    )
                    send_ack(sock, frame.seq, addr, args.loss_rate)
                    expected_seq = 1 - expected_seq
                else:
                    print(f"[server] Duplicate DATA seq={frame.seq}, resending ACK")
                    send_ack(sock, frame.seq, addr, args.loss_rate)
            elif frame.frame_type == TYPE_END:
                print(f"[server] END seq={frame.seq} received")
                if send_ack(sock, frame.seq, addr, args.loss_rate):
                    break
                print("[server] END ACK dropped, waiting for retransmitted END")
            elif frame.frame_type == TYPE_ACK:
                print("[server] Unexpected ACK frame from client, ignored")
            elif frame.frame_type == TYPE_REQUEST:
                request_name = frame.payload.decode("utf-8", errors="ignore").strip()
                print(
                    f"[server] REQUEST received from {addr[0]}:{addr[1]}, "
                    f"name={request_name if request_name else '<default>'}"
                )
                if serve_path is None:
                    print("[server] No --serve-file configured, request ignored")
                    continue
                send_file_to_client(sock, addr, serve_path, args)
                break
            else:
                print(f"[server] Unknown frame type={frame.frame_type}, ignored")

    print("[server] Transfer complete")
    if client_addr is not None:
        print(f"[server] Last client address: {client_addr[0]}:{client_addr[1]}")
    print(f"[server] Final file size: {received_bytes} bytes")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[server] Fatal error: {exc}")
