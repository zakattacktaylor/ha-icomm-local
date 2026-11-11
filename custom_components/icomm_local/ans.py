"""Offline decoder for Ayla notification datagrams; no networking or cloud calls.

Protocol fields described by the Ayla device agent's notify_proto.h. This is an
independent implementation of that format, not copied device-agent source.
"""
import struct
import hashlib
import hmac
import os
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

OPERATIONS = {1:'register',2:'register_response',3:'request_probe',4:'request_probe_response',
    5:'probe',6:'probe_response',7:'keepalive',8:'keepalive_response',9:'notify',
    10:'notify_response',11:'unregister',12:'unregister_response'}


def crc8(data):
    crc = 0xFF
    for value in data:
        crc ^= value
        for _ in range(8):
            crc = ((crc << 1) ^ (7 if crc & 0x80 else 0)) & 255
    return crc


def decode_datagram(packet, key=None):
    if not packet:
        raise ValueError('Empty datagram')
    result = {'format':packet[0], 'length':len(packet)}
    if packet[0] in (3,4):
        if len(packet)<40 or (len(packet)-24)%16:
            raise ValueError('Invalid encrypted datagram size')
        result['encrypted'] = True
        if key is None:
            return result
        if len(key) != 16:
            raise ValueError('Expected a 16-byte ANS key')
        decoder=Cipher(algorithms.AES(key),modes.CBC(packet[8:24])).decryptor()
        plain=decoder.update(packet[24:])+decoder.finalize()
        if crc8(plain):
            raise ValueError('ANS checksum mismatch')
        result['crc_valid'] = True
    elif packet[0] in (0,2):
        if len(packet)<3 or len(packet)<3+packet[2]+8:
            raise ValueError('Invalid registration datagram')
        # DSN is deliberately omitted from the decoded result.
        plain=packet[3+packet[2]:]
        result['encrypted'] = False
    elif packet[0] == 1:
        if len(packet)<32:raise ValueError('Invalid legacy datagram')
        plain=packet[24:]
        result['encrypted'] = False
    else:
        raise ValueError('Unknown ANS encapsulation')
    version,operation,sequence,timestamp=struct.unpack('>BBHI',plain[:8])
    if version not in (0,1) or operation not in OPERATIONS:
        raise ValueError('Unrecognized ANS header')
    result.update(version=version,operation=OPERATIONS[operation],sequence=sequence,
                  device_time_ms=timestamp)
    if operation in (1,2,3,7) and len(plain)>=10:
        result['interval_seconds']=int.from_bytes(plain[8:10],'big')
    if operation in (4,6,8,10,12) and len(plain)>=9:
        result['error']=plain[8]
    if operation==2 and len(plain)>=11:result['error']=plain[10]
    return result


def verify_registration(packet, key):
    """Verify format-0 registration using the wire-confirmed SHA1(message+key).

    The HTTPS key is longer; this protocol uses its first 16 decoded bytes.
    No identifier or key is returned.
    """
    if len(key) != 16:
        raise ValueError('Expected a 16-byte ANS key')
    if not packet or packet[0] != 0 or len(packet) < 33:
        return False
    try:
        decoded = decode_datagram(packet)
    except ValueError:
        return False
    if decoded.get('operation') != 'register':
        return False
    return hmac.compare_digest(packet[-20:], hashlib.sha1(packet[:-20]+key).digest())


def encode_datagram(operation, sequence, timestamp, registration_id, key, payload=b'', iv=None):
    """Build an encrypted format-4 packet offline; performs no network I/O."""
    if operation not in OPERATIONS or operation == 1:
        raise ValueError('Expected a non-registration operation')
    if len(key) != 16 or len(registration_id) != 4:
        raise ValueError('Expected a 16-byte key and 4-byte registration ID')
    iv = os.urandom(16) if iv is None else iv
    if len(iv) != 16:
        raise ValueError('Expected a 16-byte IV')
    plain = struct.pack('>BBHI', 1, operation, sequence, timestamp)+payload
    plain += bytes((-len(plain)-1) % 16)
    plain += bytes((crc8(plain),))
    encoder = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return bytes((4,0,0,0))+registration_id+iv+encoder.update(plain)+encoder.finalize()
