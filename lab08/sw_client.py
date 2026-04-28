import argparse
import socket
from pathlib import Path

from stop_and_wait_protocol import TYPE_ACK, TYPE_DATA, TYPE_END, TYPE_REQUEST, decode_frame, encode_frame, should_drop


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stop-and-Wait UDP client")
    parser.add_argument("--host", default="127.0.0.1", help="Server host")
    parser.add_argument("--port", type=int, default=9000, help="Server port")
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument("--file", help="File to upload to server (client -> server mode)")
    mode_group.add_argument(
        "--download-output",
        help="Path for received file (server -> client mode)",
    )
    parser.add_argument(
        "--request-name",
        default="",
        help="Optional file name to request from server in download mode",
    )
    parser.add_argument("--chunk-size", type=int, default=512, help="Payload size in bytes per DATA packet")
    parser.add_argument(
        "--timeout",
        type=float,
        default=0.5,
        help="Timeout in seconds to wait for ACK before retransmission",
    )
    parser.add_argument(
        "--loss-rate",
        type=float,
        default=0.3,
        help="Packet loss probability [0.0..1.0] applied to both outgoing DATA and incoming ACKs",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=50,
        help="Maximum retransmissions per packet before giving up",
    )
    return parser.parse_args()


def wait_for_ack(sock: socket.socket, expected_seq: int, loss_rate: float) -> bool:
    while True:
        try:
            raw, _ = sock.recvfrom(65535)
        except socket.timeout:
            return False
        except OSError as exc:
            print(f"[client] Socket error while waiting ACK: {exc}")
            return False

        if should_drop(loss_rate):
            print("[client] ACK dropped on receive (simulated)")
            continue

        try:
            frame = decode_frame(raw)
        except ValueError as exc:
            print(f"[client] Broken frame ignored while waiting ACK: {exc}")
            continue

        if frame.frame_type != TYPE_ACK:
            print(f"[client] Non-ACK frame received (type={frame.frame_type}), ignored")
            continue
        if frame.seq != expected_seq:
            print(f"[client] ACK seq={frame.seq} does not match expected={expected_seq}, ignored")
            continue
        print(f"[client] ACK {frame.seq} received")
        return True


def send_ack(sock: socket.socket, seq: int, addr, loss_rate: float) -> bool:
    ack = encode_frame(TYPE_ACK, seq)
    if should_drop(loss_rate):
        print(f"[client] ACK {seq} dropped on send (simulated)")
        return False
    sock.sendto(ack, addr)
    print(f"[client] ACK {seq} sent")
    return True


def send_with_retries(
    sock: socket.socket,
    server_addr: tuple[str, int],
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
        TYPE_REQUEST: "REQUEST",
    }.get(frame_type, f"TYPE_{frame_type}")
    packet = encode_frame(frame_type, seq, payload)

    for attempt in range(1, max_retries + 1):
        if should_drop(loss_rate):
            print(
                f"[client] {frame_name} seq={seq} dropped on send (simulated), "
                f"attempt={attempt}/{max_retries}"
            )
        else:
            sock.sendto(packet, server_addr)
            suffix = f", size={len(payload)}" if frame_type == TYPE_DATA else ""
            print(f"[client] {frame_name} seq={seq} sent{suffix}, attempt={attempt}/{max_retries}")

        sock.settimeout(timeout)
        if wait_for_ack(sock, seq, loss_rate):
            return
        print(f"[client] Timeout waiting ACK for seq={seq}, retransmit")

    raise RuntimeError(f"Failed to deliver seq={seq}: retries exhausted ({max_retries})")


def upload_file(sock: socket.socket, server_addr: tuple[str, int], source_path: Path, args: argparse.Namespace) -> None:
    data = source_path.read_bytes()
    chunks = [data[i : i + args.chunk_size] for i in range(0, len(data), args.chunk_size)]
    if not chunks:
        chunks = [b""]

    seq = 0
    total_sent = 0

    print(f"[client] Upload mode: {source_path.resolve()}")
    print(f"[client] File size: {len(data)} bytes, chunks: {len(chunks)}, chunk_size: {args.chunk_size}")

    for chunk in chunks:
        send_with_retries(
            sock=sock,
            server_addr=server_addr,
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
        server_addr=server_addr,
        frame_type=TYPE_END,
        seq=seq,
        payload=b"",
        timeout=args.timeout,
        loss_rate=args.loss_rate,
        max_retries=args.max_retries,
    )
    print(f"[client] Upload complete, bytes acknowledged: {total_sent}")


def download_file(
    sock: socket.socket,
    server_addr: tuple[str, int],
    output_path: Path,
    request_name: str,
    args: argparse.Namespace,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    request_payload = request_name.encode("utf-8")
    request_frame = encode_frame(TYPE_REQUEST, 0, request_payload)

    expected_seq = 0
    total_received = 0
    request_attempts = 0
    consecutive_timeouts = 0
    transfer_started = False

    print(f"[client] Download mode: output -> {output_path.resolve()}")
    print(f"[client] Requested name: {request_name if request_name else '<default>'}")

    with output_path.open("wb") as fout:
        while True:
            if not transfer_started and request_attempts < args.max_retries:
                request_attempts += 1
                if should_drop(args.loss_rate):
                    print(
                        f"[client] REQUEST dropped on send (simulated), "
                        f"attempt={request_attempts}/{args.max_retries}"
                    )
                else:
                    sock.sendto(request_frame, server_addr)
                    print(
                        f"[client] REQUEST sent, attempt={request_attempts}/{args.max_retries}"
                    )

            sock.settimeout(args.timeout)
            try:
                raw, addr = sock.recvfrom(65535)
            except socket.timeout:
                consecutive_timeouts += 1
                if not transfer_started and request_attempts >= args.max_retries:
                    raise RuntimeError("Server did not respond to download request")
                if transfer_started and consecutive_timeouts >= args.max_retries:
                    raise RuntimeError("Download timed out: too many consecutive receive timeouts")
                continue
            except OSError as exc:
                raise RuntimeError(f"Socket error while downloading: {exc}") from exc

            consecutive_timeouts = 0
            if should_drop(args.loss_rate):
                print("[client] Incoming frame dropped (simulated)")
                continue

            try:
                frame = decode_frame(raw)
            except ValueError as exc:
                print(f"[client] Broken frame ignored while downloading: {exc}")
                continue

            if frame.frame_type == TYPE_DATA:
                transfer_started = True
                if frame.seq == expected_seq:
                    fout.write(frame.payload)
                    total_received += len(frame.payload)
                    print(
                        f"[client] DATA seq={frame.seq} accepted, size={len(frame.payload)}, "
                        f"total_received={total_received}"
                    )
                    send_ack(sock, frame.seq, addr, args.loss_rate)
                    expected_seq = 1 - expected_seq
                else:
                    print(f"[client] Duplicate DATA seq={frame.seq}, resending ACK")
                    send_ack(sock, frame.seq, addr, args.loss_rate)
            elif frame.frame_type == TYPE_END:
                transfer_started = True
                print(f"[client] END seq={frame.seq} received")
                if send_ack(sock, frame.seq, addr, args.loss_rate):
                    break
                print("[client] END ACK dropped, waiting for retransmitted END")
            elif frame.frame_type == TYPE_ACK:
                print("[client] Unexpected ACK while downloading, ignored")
            elif frame.frame_type == TYPE_REQUEST:
                print("[client] Unexpected REQUEST while downloading, ignored")
            else:
                print(f"[client] Unknown frame type={frame.frame_type}, ignored")

    print(f"[client] Download complete, bytes received: {total_received}")


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

    server_addr = (args.host, args.port)
    print(f"[client] Server address: {args.host}:{args.port}")
    print(f"[client] Timeout: {args.timeout}s, simulated loss: {args.loss_rate * 100:.0f}%")

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        if args.file:
            source_path = Path(args.file)
            if not source_path.exists() or not source_path.is_file():
                raise FileNotFoundError(f"Input file does not exist: {source_path}")
            upload_file(sock, server_addr, source_path, args)
        else:
            download_output = Path(args.download_output)
            download_file(sock, server_addr, download_output, args.request_name, args)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[client] Fatal error: {exc}")
