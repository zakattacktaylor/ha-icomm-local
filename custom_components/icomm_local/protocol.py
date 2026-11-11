"""iCOMM block framing and authenticated Ayla LAN session codec.

Wire formats informed by ericboehs/aosmith-water-heater and deiger/AirCon.
Implementation is independent; no cloud credentials are used.
"""
import base64
import hmac
import json
import math
import secrets
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MODES = {'electric': 1, 'vacation': 2, 'hybrid': 4, 'heat_pump': 5}


def crc8(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ (0x5E if crc & 0x80 else 0)) & 255
    return crc


def frame(offset: int, payload: bytes) -> str:
    body = bytes((0xBD, 0x40, 6 + len(payload), 0x0B, offset)) + payload
    return (body + bytes((crc8(body),))).hex(' ').upper()


def setpoint_frame(fahrenheit: float, maximum: int = 130) -> str:
    if not math.isfinite(fahrenheit) or fahrenheit != int(fahrenheit) or not 95 <= fahrenheit <= maximum:
        raise ValueError(f'Target must be an integer between 95 and {maximum} Fahrenheit')
    return frame(6, round((fahrenheit - 32) / 1.8 * 256).to_bytes(2, 'big'))


def mode_frame(mode: str, days: int = 1) -> str:
    if mode not in MODES or not isinstance(days, int) or not 1 <= days <= 100:
        raise ValueError('Unsupported mode or duration')
    return frame(15, bytes((days if mode in ('electric', 'vacation') else 0, MODES[mode])))


@dataclass(frozen=True)
class Telemetry:
    target_f: float
    mode: str
    duration_days: int
    top_f: float
    middle_f: float
    bottom_f: float


def telemetry(value: str) -> Telemetry:
    blocks = [bytes.fromhex(part) for part in value.split(',')]
    if [len(b) for b in blocks] != [8, 148, 230, 52, 52]:
        raise ValueError('Unsupported superBlockDyn1 layout')
    def temp(block, offset):
        return round(int.from_bytes(blocks[block][offset:offset + 2], 'big') / 256 * 1.8 + 32, 2)
    target = temp(3, 0)
    if target != temp(3, 12) or not 32 <= target <= 160:
        raise ValueError('Invalid or inconsistent target')
    mode = next((name for name, code in MODES.items() if code == blocks[3][31]), 'unknown')
    return Telemetry(target, mode, blocks[3][30], temp(1, 0), temp(1, 2), temp(1, 4))


class Direction:
    """Ayla uses zero-padded AES-CBC plus HMAC-SHA256, with chained IVs."""
    def __init__(self, lan_key: bytes, material: bytes):
        def derive(suffix):
            msg = material + suffix
            return hmac.digest(lan_key, hmac.digest(lan_key, msg, 'sha256') + msg, 'sha256')
        self.sign_key = derive(b'0')
        self.key = derive(b'1')
        self.iv = derive(b'2')[:16]

    def encrypt(self, value: dict) -> dict:
        text = json.dumps(value, separators=(',', ':')).encode()
        padded = text + b'\0' * (-len(text) % 16)
        encryptor = Cipher(algorithms.AES(self.key), modes.CBC(self.iv)).encryptor()
        ciphertext = encryptor.update(padded) + encryptor.finalize()
        self.iv = ciphertext[-16:]
        return {'enc': base64.b64encode(ciphertext).decode(),
                'sign': base64.b64encode(hmac.digest(self.sign_key, text, 'sha256')).decode()}

    def decrypt(self, envelope: dict) -> dict:
        ciphertext = base64.b64decode(envelope['enc'], validate=True)
        signature = base64.b64decode(envelope['sign'], validate=True)
        if not ciphertext or len(ciphertext) % 16:
            raise ValueError('Invalid ciphertext length')
        decryptor = Cipher(algorithms.AES(self.key), modes.CBC(self.iv)).decryptor()
        text = (decryptor.update(ciphertext) + decryptor.finalize()).rstrip(b'\0')
        if not hmac.compare_digest(signature, hmac.digest(self.sign_key, text, 'sha256')):
            raise ValueError('Invalid LAN message signature')
        result = json.loads(text)
        self.iv = ciphertext[-16:]
        return result


class Session:
    def __init__(self, key: str, key_id: int):
        self.key = key.encode()
        self.key_id = key_id
        self.tx = self.rx = None
        self.tx_seq = 0
        self.rx_seq = -1

    def exchange(self, request: dict) -> dict:
        if request.get('key_id') != self.key_id or request.get('ver') != 1 or request.get('proto') != 1 or request.get('sec'):
            raise ValueError('Unsupported key exchange')
        r1, t1 = request['random_1'], request['time_1']
        if not isinstance(r1, str) or not 1 <= len(r1) <= 128 or not isinstance(t1, int):
            raise ValueError('Invalid key exchange')
        r2 = secrets.token_hex(8)
        t2 = secrets.randbelow(2**40)
        self.tx = Direction(self.key, f'{r1}{r2}{t1}{t2}'.encode())
        self.rx = Direction(self.key, f'{r2}{r1}{t2}{t1}'.encode())
        self.tx_seq = 0
        self.rx_seq = -1
        return {'random_2': r2, 'time_2': t2}

    def encrypt(self, data: dict) -> dict:
        if self.tx is None:
            raise ValueError('No LAN session')
        value = self.tx.encrypt({'seq_no': self.tx_seq, 'data': data})
        self.tx_seq += 1
        return value

    def decrypt(self, envelope: dict) -> dict:
        if self.rx is None:
            raise ValueError('No LAN session')
        value = self.rx.decrypt(envelope)
        seq = value.get('seq_no')
        if not isinstance(seq, int) or seq <= self.rx_seq:
            raise ValueError('Replayed or invalid sequence')
        self.rx_seq = seq
        return value
