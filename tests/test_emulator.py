import asyncio
import base64
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET
from aiohttp.test_utils import TestClient,TestServer
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'addons/icomm_emulator'))
from aiohttp import web
from emulator import LocalService,Notifications
from ans import decode_datagram,encode_datagram


class Transport:
    def __init__(self):self.sent=[]
    def sendto(self,packet,peer):self.sent.append((packet,peer))


class EmulatorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory=tempfile.TemporaryDirectory();self.root=Path(self.directory.name)
        key=base64.b64encode(bytes(range(64))).decode()
        profile={'dsn':'SYNTHETIC','device_id':'123','local_ans_host':'192.0.2.3',
            'identity_xml':f'<device><ans-cipher-key>{key}</ans-cipher-key><ans-server>cloud.invalid</ans-server></device>'}
        (self.root/'profile.json').write_text(json.dumps(profile))
        self.service=LocalService(self.root,['127.0.0.1']);self.service.load_profile()
        self.service.active=True
        self.channel=Notifications(self.service,55055);self.channel.connection_made(Transport())
        self.service.udp=[self.channel]
        app=web.Application();app.router.add_route('*','/{path:.*}',self.service.http)
        self.client=TestClient(TestServer(app));await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        for task in list(self.service.tasks):task.cancel()
        await asyncio.gather(*self.service.tasks,return_exceptions=True)
        self.directory.cleanup()

    def register(self):
        dsn=b'SYNTHETIC\0';data=bytes((0,0,len(dsn)))+dsn+struct.pack('>BBHIH',1,1,9,100,30)
        packet=data+hashlib.sha1(data+self.service.key).digest()
        self.channel.datagram_received(packet,('127.0.0.1',49000))
        response,peer=self.channel.transport.sent[-1]
        self.assertEqual(decode_datagram(response,self.service.key)['operation'],'register_response')

    async def test_register_keepalive_and_reject_forged_packets(self):
        self.register();reg=self.service.registration_id
        packet=encode_datagram(7,10,101,reg,self.service.key,struct.pack('>H',30))
        self.channel.datagram_received(packet,('127.0.0.1',49000))
        reply,_=self.channel.transport.sent[-1]
        self.assertEqual(decode_datagram(reply,self.service.key)['operation'],'keepalive_response')
        count=len(self.channel.transport.sent)
        self.channel.datagram_received(packet,('127.0.0.2',49000))
        self.channel.datagram_received(packet[:-1]+bytes((packet[-1]^1,)),('127.0.0.1',49000))
        self.assertEqual(len(self.channel.transport.sent),count)

    async def test_identity_has_local_ans_and_no_bootstrap_writes(self):
        response=await self.client.get('/dsns/SYNTHETIC.xml');root=ET.fromstring(await response.read())
        self.assertEqual(root.findtext('ans-server'),'192.0.2.3')
        response=await self.client.get('/devices/123/commands.xml');root=ET.fromstring(await response.read())
        self.assertEqual(len(root.find('properties')),0)
        response=await self.client.get('/firmware.bin');self.assertEqual(response.status,404)

    async def test_command_is_one_shot_and_expires_without_replay(self):
        self.register();self.service.reading_at=time.time()
        self.service.queue('target',129)
        packet,_=self.channel.transport.sent[-1]
        self.assertEqual(decode_datagram(packet,self.service.key)['operation'],'notify')
        response=await self.client.get('/devices/123/commands.xml');root=ET.fromstring(await response.read())
        self.assertEqual(root.findtext('.//value'),'BD 40 08 0B 06 35 E4 38')
        response=await self.client.get('/devices/123/commands.xml');root=ET.fromstring(await response.read())
        self.assertEqual(len(root.find('properties')),0)
        with self.assertRaises(ValueError):self.service.queue('target',130)
        self.service.pending['expires']=time.time()-1
        response=await self.client.get('/devices/123/commands.xml');await response.read()
        self.assertIsNone(self.service.pending)
        self.service.reading_at=0
        with self.assertRaises(ValueError):self.service.queue('target',130)

    async def test_only_fresh_telemetry_confirms_command(self):
        self.register();self.service.reading_at=time.time();self.service.queue('target',129)
        blocks=[bytearray(n) for n in (8,148,230,52,52)]
        for offset in (0,12):blocks[3][offset:offset+2]=round((129-32)/1.8*256).to_bytes(2,'big')
        blocks[3][31]=4
        value=','.join(b.hex() for b in blocks)
        body=f'<datapoint><value>{value}</value></datapoint>'
        response=await self.client.post('/devices/123/properties/superBlockDyn1/datapoints.xml',data=body)
        self.assertEqual(response.status,200);self.assertIsNotNone(self.service.pending)
        response=await self.client.get('/devices/123/commands.xml');await response.read()
        response=await self.client.post('/devices/123/properties/superBlockDyn1/datapoints.xml',data=body)
        self.assertEqual(response.status,200);self.assertIsNone(self.service.pending)

    def test_generated_codecs_match_source(self):
        root=Path(__file__).resolve().parents[1]
        for name in ('ans.py','protocol.py'):
            generated=(root/'addons/icomm_emulator'/name).read_text().split('\n',1)[1]
            self.assertEqual(generated,(root/'custom_components/icomm_local'/name).read_text())
