#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import mimetypes
import os
import secrets
import socket
import ssl
import sys


def read_smtp_line(sock: socket.socket, buf: bytearray) -> bytes:
    while True:
        if b"\r\n" in buf:
            i = buf.index(b"\r\n")
            line = bytes(buf[:i])
            del buf[: i + 2]
            return line
        chunk = sock.recv(8192)
        if not chunk:
            raise ConnectionError("connection closed by server")
        buf.extend(chunk)


def recv_reply(sock: socket.socket, buf: bytearray, verbose: bool) -> tuple[int, list[bytes]]:
    lines: list[bytes] = []
    while True:
        line = read_smtp_line(sock, buf)
        lines.append(line)
        if verbose:
            print(f"< {line!r}", file=sys.stderr)
        if len(line) >= 4 and line[3] == 0x2D:
            continue
        break
    try:
        code = int(line[:3])
    except ValueError as e:
        raise RuntimeError(f"invalid SMTP reply: {lines!r}") from e
    return code, lines


def send_cmd(sock: socket.socket, cmd: str, verbose: bool) -> None:
    if verbose:
        print(f"> {cmd!r}", file=sys.stderr)
    sock.sendall(cmd.encode("ascii", errors="strict") + b"\r\n")


def expect(sock: socket.socket, buf: bytearray, ok: set[int], ctx: str, verbose: bool) -> None:
    code, lines = recv_reply(sock, buf, verbose)
    if code not in ok:
        sys.exit(f"{ctx}: {code} {lines}")


def ehlo_supports(lines: list[bytes], cap: bytes) -> bool:
    blob = b"\n".join(lines).upper()
    return cap.upper() in blob


def dot_stuff_terminate(inner: bytes) -> bytes:
    """SMTP DATA transparency: lines starting with '.' get an extra '.', then end with .\\r\\n."""
    out = bytearray()
    for line in inner.split(b"\r\n"):
        if line.startswith(b"."):
            line = b"." + line
        out.extend(line + b"\r\n")
    out.extend(b".\r\n")
    return bytes(out)


def build_plain(mail_from: str, rcpt_to: str, subject: str, body: str) -> bytes:
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    hdr = (
        f"From: {mail_from}\r\n"
        f"To: {rcpt_to}\r\n"
        f"Subject: {subject}\r\n"
        f"MIME-Version: 1.0\r\n"
        f"Content-Type: text/plain; charset=utf-8\r\n"
        f"\r\n"
    )
    inner = hdr.encode("utf-8") + body.encode("utf-8")
    return dot_stuff_terminate(inner)


def wrap_base64(data: bytes, width: int = 76) -> str:
    s = base64.b64encode(data).decode("ascii")
    return "\r\n".join(s[i : i + width] for i in range(0, len(s), width))


def build_mixed_with_image(
    mail_from: str, rcpt_to: str, subject: str, body: str, image_path: str
) -> bytes:
    with open(image_path, "rb") as f:
        raw_img = f.read()
    boundary = "bnd_" + secrets.token_hex(16)
    fn = os.path.basename(image_path).replace('"', "").replace("\r", "").replace("\n", "")
    ctype, _ = mimetypes.guess_type(image_path)
    if not ctype or not ctype.startswith("image/"):
        ctype = "application/octet-stream"
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    b64 = wrap_base64(raw_img)
    text = (
        f"From: {mail_from}\r\n"
        f"To: {rcpt_to}\r\n"
        f"Subject: {subject}\r\n"
        f"MIME-Version: 1.0\r\n"
        f'Content-Type: multipart/mixed; boundary="{boundary}"\r\n'
        f"\r\n"
        f"--{boundary}\r\n"
        f"Content-Type: text/plain; charset=utf-8\r\n"
        f"Content-Transfer-Encoding: 8bit\r\n"
        f"\r\n"
        f"{body}\r\n"
        f"--{boundary}\r\n"
        f"Content-Type: {ctype}\r\n"
        f"Content-Transfer-Encoding: base64\r\n"
        f'Content-Disposition: attachment; filename="{fn}"\r\n'
        f"\r\n"
        f"{b64}\r\n"
        f"--{boundary}--\r\n"
    )
    return dot_stuff_terminate(text.encode("utf-8"))


def main() -> None:
    p = argparse.ArgumentParser(description="SMTP client using sockets only (no smtplib).")
    p.add_argument("--host", default="mail.spbu.ru", help="SMTP server hostname")
    p.add_argument("--port", type=int, default=25, help="port (25 plain, 587 STARTTLS)")
    p.add_argument("--ehlo", default="localhost", help="client name in EHLO")
    p.add_argument("--mail-from", required=True, help="envelope sender (MAIL FROM)")
    p.add_argument("--to", required=True, dest="rcpt_to", help="recipient address")
    p.add_argument("--subject", default="Lab 5 A.2 — SMTP over socket")
    p.add_argument("--body-file", default="", help="message body from UTF-8 file")
    p.add_argument(
        "--starttls",
        action="store_true",
        help="issue STARTTLS after EHLO (e.g. port 587)",
    )
    p.add_argument("--auth-user", default="", help="AUTH PLAIN username (after TLS)")
    p.add_argument("--auth-password", default="", help="AUTH PLAIN password")
    p.add_argument("-v", "--verbose", action="store_true", help="print SMTP dialogue")
    p.add_argument(
        "--attach-image",
        default="",
        metavar="PATH",
        help="attach binary image (multipart/mixed, base64); e.g. .png .jpg",
    )
    args = p.parse_args()

    if bool(args.auth_user) != bool(args.auth_password):
        sys.exit("set both --auth-user and --auth-password, or neither")

    if args.body_file:
        with open(args.body_file, encoding="utf-8") as f:
            body = f.read()
    elif not sys.stdin.isatty():
        body = sys.stdin.read()
    else:
        body = "Test message (lab 5, SMTP socket client).\n"
        if args.attach_image:
            body += "See attached image.\n"

    if args.attach_image and not os.path.isfile(args.attach_image):
        sys.exit(f"attach-image not found: {args.attach_image}")

    raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    raw.settimeout(60)
    try:
        raw.connect((args.host, args.port))
    except OSError as e:
        sys.exit(f"connect: {e}")

    sock: socket.socket = raw
    buf = bytearray()
    try:
        expect(sock, buf, {220}, "greeting", args.verbose)

        send_cmd(sock, f"EHLO {args.ehlo}", args.verbose)
        code, ehlo_lines = recv_reply(sock, buf, args.verbose)
        if code != 250:
            send_cmd(sock, f"HELO {args.ehlo}", args.verbose)
            expect(sock, buf, {250}, "HELO", args.verbose)
            ehlo_lines = []

        if args.starttls:
            if not ehlo_supports(ehlo_lines, b"STARTTLS"):
                sys.exit("server did not advertise STARTTLS in EHLO")
            send_cmd(sock, "STARTTLS", args.verbose)
            expect(sock, buf, {220}, "STARTTLS", args.verbose)
            ctx = ssl.create_default_context()
            sock = ctx.wrap_socket(sock, server_hostname=args.host)
            buf.clear()

            send_cmd(sock, f"EHLO {args.ehlo}", args.verbose)
            expect(sock, buf, {250}, "EHLO after TLS", args.verbose)

        if args.auth_user:
            raw_auth = b"\0" + args.auth_user.encode("utf-8") + b"\0" + args.auth_password.encode("utf-8")
            token = base64.b64encode(raw_auth).decode("ascii")
            send_cmd(sock, f"AUTH PLAIN {token}", args.verbose)
            expect(sock, buf, {235}, "AUTH PLAIN", args.verbose)

        mf = args.mail_from
        if "<" not in mf:
            mf = f"<{mf}>"
        send_cmd(sock, f"MAIL FROM:{mf}", args.verbose)
        expect(sock, buf, {250}, "MAIL FROM", args.verbose)

        rt = args.rcpt_to
        if "<" not in rt:
            rt = f"<{rt}>"
        send_cmd(sock, f"RCPT TO:{rt}", args.verbose)
        expect(sock, buf, {250, 251}, "RCPT TO", args.verbose)

        send_cmd(sock, "DATA", args.verbose)
        expect(sock, buf, {354}, "DATA", args.verbose)

        if args.attach_image:
            payload = build_mixed_with_image(
                args.mail_from, args.rcpt_to, args.subject, body, args.attach_image
            )
        else:
            payload = build_plain(args.mail_from, args.rcpt_to, args.subject, body)
        if args.verbose:
            print("> ... message ...", file=sys.stderr)
        sock.sendall(payload)
        expect(sock, buf, {250}, "after DATA", args.verbose)

        send_cmd(sock, "QUIT", args.verbose)
        expect(sock, buf, {221}, "QUIT", args.verbose)
    finally:
        try:
            sock.close()
        except OSError:
            pass

    print("message sent", file=sys.stderr)


if __name__ == "__main__":
    main()
