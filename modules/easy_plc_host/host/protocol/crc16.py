"""Modbus RTU CRC16 (poly 0xA001, init 0xFFFF)."""


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def append_crc(frame: bytes) -> bytes:
    c = crc16(frame)
    return frame + bytes((c & 0xFF, (c >> 8) & 0xFF))


def verify_crc(frame: bytes) -> bool:
    if len(frame) < 4:
        return False
    body, got = frame[:-2], frame[-2:]
    expect = crc16(body)
    return got[0] == (expect & 0xFF) and got[1] == ((expect >> 8) & 0xFF)
