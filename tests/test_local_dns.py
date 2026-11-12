import asyncio
import ipaddress
from pathlib import Path
import struct
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'addons/icomm_emulator'))
from local_dns import LocalDNS,response


def query(name='heater.example',kind=1):
    wire=b''.join(bytes((len(label),))+label.encode() for label in name.split('.'))+b'\0'
    return struct.pack('!6H',321,0x100,1,0,0,0)+wire+struct.pack('!HH',kind,1)


class CodecTests(unittest.TestCase):
    def test_only_configured_names_resolve_and_aaaa_cannot_escape_locally(self):
        hosts={'heater.example':'192.0.2.1'}
        wire,name,rcode=response(query('HeAtEr.Example'),hosts)
        self.assertEqual((name,rcode),('heater.example',0))
        self.assertEqual(struct.unpack('!6H',wire[:12]),(321,0x8500,1,1,0,0))
        self.assertEqual(wire[-4:],ipaddress.IPv4Address('192.0.2.1').packed)
        self.assertEqual(struct.unpack('!I',wire[-10:-6])[0],300)
        for kind in (28,16):
            wire,_,rcode=response(query(kind=kind),hosts)
            self.assertEqual(rcode,0);self.assertEqual(struct.unpack('!H',wire[6:8])[0],0)
        wire,_,rcode=response(query('unrelated.example'),hosts)
        self.assertEqual(rcode,3);self.assertEqual(struct.unpack('!H',wire[6:8])[0],0)

    def test_malformed_queries_and_non_allowlisted_peers_are_dropped(self):
        service=LocalDNS({'heater.example':'192.0.2.1'},['127.0.0.1'])
        self.assertIsNone(service.reply(query(),('127.0.0.2',123)))
        malformed=[b'',query()[:15],query()[:12]+b'\xc0\x0c'+query()[-4:],query()+b'x'*4096]
        for packet in malformed:self.assertIsNone(service.reply(packet,('127.0.0.1',123)))
        self.assertEqual(service.denied,1);self.assertEqual(service.invalid,len(malformed));self.assertEqual(service.queries,0)


class NetworkTests(unittest.IsolatedAsyncioTestCase):
    async def test_tcp_and_udp_answer_and_shutdown(self):
        service=LocalDNS({'heater.example':'192.0.2.1'},['127.0.0.1'])
        await service.start('127.0.0.1',0)
        try:
            port=service.server.sockets[0].getsockname()[1]
            reader,writer=await asyncio.open_connection('127.0.0.1',port)
            packet=query();writer.write(struct.pack('!H',len(packet))+packet);await writer.drain()
            size=struct.unpack('!H',await reader.readexactly(2))[0]
            answer=await reader.readexactly(size);self.assertEqual(answer[-4:],ipaddress.IPv4Address('192.0.2.1').packed)
            writer.close();await writer.wait_closed()
            future=asyncio.get_running_loop().create_future()
            class Receiver(asyncio.DatagramProtocol):
                def datagram_received(self,data,peer):
                    if not future.done():future.set_result(data)
            transport,_=await asyncio.get_running_loop().create_datagram_endpoint(Receiver,remote_addr=service.transport.get_extra_info('sockname'))
            try:
                transport.sendto(packet);answer=await asyncio.wait_for(future,1)
                self.assertEqual(answer[-4:],ipaddress.IPv4Address('192.0.2.1').packed)
            finally:transport.close()
            self.assertEqual(service.queries,2)
        finally:await service.stop()
        with self.assertRaises(OSError):await asyncio.open_connection('127.0.0.1',port)
