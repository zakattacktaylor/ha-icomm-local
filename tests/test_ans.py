import struct
import sys
import unittest
from pathlib import Path
from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from custom_components.icomm_local.ans import crc8,decode_datagram

class AnsDecoderTests(unittest.TestCase):
    def test_encrypted_keepalive_and_wrong_key(self):
        key=bytes(range(16));iv=bytes(reversed(range(16)))
        plain=struct.pack('>BBHIH',1,7,123,456789,80)+bytes(5)
        plain+=bytes((crc8(plain),))
        self.assertEqual(crc8(plain),0)
        encoder=Cipher(algorithms.AES(key),modes.CBC(iv)).encryptor()
        packet=bytes.fromhex('0400000001020304')+iv+encoder.update(plain)+encoder.finalize()
        result=decode_datagram(packet,key)
        self.assertEqual(result['operation'],'keepalive')
        self.assertEqual(result['sequence'],123)
        self.assertEqual(result['interval_seconds'],80)
        self.assertTrue(result['crc_valid'])
        self.assertNotIn('operation',decode_datagram(packet))
        with self.assertRaises(ValueError):decode_datagram(packet,bytes(16))

    def test_registration_does_not_reveal_identifier(self):
        dsn=b'SYNTHETIC-ONLY\0'
        packet=bytes((0,0,len(dsn)))+dsn+struct.pack('>BBHIH',1,1,1,1000,30)+bytes(20)
        result=decode_datagram(packet)
        self.assertEqual(result['operation'],'register')
        self.assertFalse(result['encrypted'])
        self.assertNotIn('SYNTHETIC',str(result))

    def test_truncated_encrypted_datagram_is_rejected(self):
        with self.assertRaises(ValueError):decode_datagram(b'\x04'+bytes(23),bytes(16))
