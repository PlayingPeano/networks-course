from stop_and_wait_protocol import compute_checksum, verify_checksum


def run_test(name: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}")


def main() -> None:
    payload_ok = b"Stop-and-Wait checksum test payload"
    checksum_ok = compute_checksum(payload_ok)
    run_test("valid payload passes verification", verify_checksum(payload_ok, checksum_ok))

    corrupted_payload = bytearray(payload_ok)
    corrupted_payload[3] ^= 0b00010000
    run_test(
        "bit error in payload is detected",
        not verify_checksum(bytes(corrupted_payload), checksum_ok),
    )

    another_payload = b"\x00\x01\x02\x03\x04\x05\x06"
    wrong_checksum = (compute_checksum(another_payload) ^ 0x00FF) & 0xFFFF
    run_test(
        "wrong checksum value is rejected",
        not verify_checksum(another_payload, wrong_checksum),
    )


if __name__ == "__main__":
    main()
