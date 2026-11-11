import base64
import importlib
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from custom_components.icomm_local.protocol import Direction, Session, mode_frame, setpoint_frame, telemetry


class ProtocolTests(unittest.TestCase):
    def test_commands_match_captured_cloud_frames(self):
        self.assertEqual(setpoint_frame(129), 'BD 40 08 0B 06 35 E4 38')
        self.assertEqual(setpoint_frame(130), 'BD 40 08 0B 06 36 72 34')
        for mode, expected in [('hybrid','00 04 14'),('heat_pump','00 05 4A'),
                               ('electric','01 01 FE'),('vacation','01 02 1C')]:
            self.assertEqual(mode_frame(mode), 'BD 40 08 0B 0F '+expected)
        for bad in (94, 131, 129.5, float('nan')):
            with self.assertRaises(ValueError):setpoint_frame(bad)

    def test_crypto_chaining_and_tampered_packet_do_not_poison_next_packet(self):
        sender, receiver = Direction(b'example secret', b'example material'), Direction(b'example secret', b'example material')
        for value in ({'seq_no':0,'data':{}},{'seq_no':1,'data':{'value':'hello'}}):
            envelope = sender.encrypt(value)
            tampered = dict(envelope, sign=base64.b64encode(b'x'*32).decode())
            with self.assertRaises(ValueError):receiver.decrypt(tampered)
            self.assertEqual(receiver.decrypt(envelope),value)

    def test_sequence_and_session_reset(self):
        s=Session('example-key',1)
        request={'key_id':1,'ver':1,'proto':1,'random_1':'hello','time_1':123}
        reply=s.exchange(request)
        peer=Direction(b'example-key', f"{reply['random_2']}hello{reply['time_2']}123".encode())
        self.assertEqual(s.decrypt(peer.encrypt({'seq_no':0,'data':{}}))['seq_no'],0)
        with self.assertRaises(ValueError):s.decrypt(peer.encrypt({'seq_no':0,'data':{}}))
        s.exchange(request)
        self.assertEqual(s.rx_seq,-1)

    def test_telemetry_rejects_unknown_layout_and_inconsistent_target(self):
        with self.assertRaises(ValueError):telemetry('0000')
        blocks=[bytearray(n) for n in (8,148,230,52,52)]
        blocks[3][:2]=blocks[3][12:14]=bytes.fromhex('3672');blocks[3][31]=4
        result=telemetry(','.join(b.hex() for b in blocks))
        self.assertEqual((result.target_f,result.mode),(130.0,'hybrid'))
        blocks[3][12]=0
        with self.assertRaises(ValueError):telemetry(','.join(b.hex() for b in blocks))
