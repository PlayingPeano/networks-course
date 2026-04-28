import random
import struct
from dataclasses import dataclass


TYPE_DATA = 0
TYPE_ACK = 1
TYPE_END = 2
TYPE_REQUEST = 3

HEADER_STRUCT = struct.Struct("!BBHH")
CHECKSUM_MOD = 0xFFFF


@dataclass
class Frame:
    frame_type: int
    seq: int
    payload: bytes


def compute_checksum(data: bytes) -> int:
    if len(data) % 2 == 1:
        data += b"\x00"

    total = 0
    for i in range(0, len(data), 2):
        word = (data[i] << 8) + data[i + 1]
        total += word
        total = (total & CHECKSUM_MOD) + (total >> 16)
    return (~total) & CHECKSUM_MOD


def verify_checksum(data: bytes, checksum: int) -> bool:
    return compute_checksum(data) == checksum


def encode_frame(frame_type: int, seq: int, payload: bytes = b"") -> bytes:
    if frame_type not in (TYPE_DATA, TYPE_ACK, TYPE_END, TYPE_REQUEST):
        raise ValueError(f"Unknown frame type: {frame_type}")
    if seq not in (0, 1):
        raise ValueError(f"Sequence number must be 0 or 1, got: {seq}")
    if payload is None:
        payload = b""
    if len(payload) > 65535:
        raise ValueError("Payload is too large for one frame")
    header_wo_checksum = HEADER_STRUCT.pack(frame_type, seq, len(payload), 0)
    checksum = compute_checksum(header_wo_checksum + payload)
    return HEADER_STRUCT.pack(frame_type, seq, len(payload), checksum) + payload


def decode_frame(raw: bytes) -> Frame:
    if len(raw) < HEADER_STRUCT.size:
        raise ValueError("Frame is too short")
    frame_type, seq, payload_len, checksum = HEADER_STRUCT.unpack(raw[: HEADER_STRUCT.size])
    payload = raw[HEADER_STRUCT.size :]
    if payload_len != len(payload):
        raise ValueError("Broken frame: payload length mismatch")
    header_wo_checksum = HEADER_STRUCT.pack(frame_type, seq, payload_len, 0)
    if not verify_checksum(header_wo_checksum + payload, checksum):
        raise ValueError("Broken frame: checksum mismatch")
    return Frame(frame_type=frame_type, seq=seq, payload=payload)


def should_drop(loss_rate: float) -> bool:
    if loss_rate <= 0:
        return False
    if loss_rate >= 1:
        return True
    return random.random() < loss_rate
