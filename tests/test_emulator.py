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
        self.service.profile['debug_property_reads']=True
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
        self.assertEqual(root.findtext('ans-server'),'cloud.invalid')
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

    async def test_raw_ping_handles_legacy_blank_line_and_rejects_other_routes(self):
        server=await asyncio.start_server(self.service.raw_ping,'127.0.0.1',0,limit=4096)
        port=server.sockets[0].getsockname()[1]
        try:
            for request,expected in (
                (b'GET /ping?time=1 HTTP/1.1\r\nHost: synthetic.invalid\r\n\r\nContent-Length: 0\r\n\r\n',b'200 OK'),
                (b'GET /ping HTTP/1.1\r\nHost: synthetic.invalid\r\nContent-Length: 0\r\n\r\n',b'200 OK'),
                (b'POST /emulator/control HTTP/1.1\r\nHost: synthetic.invalid\r\n\r\n',b'404 Not Found')):
                reader,writer=await asyncio.open_connection('127.0.0.1',port)
                writer.write(request);await writer.drain();response=await reader.read()
                self.assertIn(expected,response);self.assertTrue(response.endswith(b'\r\n\r\n'))
                writer.close();await writer.wait_closed()
            self.service.allowed_peers=set()
            reader,writer=await asyncio.open_connection('127.0.0.1',port)
            self.assertIn(b'403 Forbidden',await reader.read());writer.close();await writer.wait_closed()
        finally:server.close();await server.wait_closed()

    async def test_identity_fixed_length_experiment_preserves_xml_and_hides_query_values(self):
        self.service.profile['response_framing']='length'
        response=await self.client.get('/dsns/SYNTHETIC.xml?ans=synthetic-private-value')
        body=await response.read()
        self.assertEqual(response.status,200)
        self.assertEqual(int(response.headers['Content-Length']),len(body))
        self.assertNotIn('Transfer-Encoding',response.headers)
        self.assertEqual(ET.fromstring(body).tag,'device')
        event=self.service.events[-1]
        self.assertEqual(event[2],{'query_keys':['ans']})
        self.assertNotIn('synthetic-private-value',str(event))

    def test_profile_validates_reporting_interval_before_startup(self):
        profile=json.loads((self.root/'profile.json').read_text())
        for rate in (60,21601):
            profile['reporting_rate']=rate
            self.service.load_profile(profile)
            self.assertEqual(self.service.profile['reporting_rate'],rate)
        for rate in (0,30,60.5,'60'):
            profile['reporting_rate']=rate
            with self.assertRaises(ValueError):self.service.load_profile(profile)

    async def test_reporting_configuration_is_sent_even_if_early_telemetry_arrives(self):
        self.service.profile['reporting_mask']='01,01,01,01'
        self.service.profile['reporting_rate']=60
        self.service.reading_at=time.time()
        response=await self.client.get('/devices/123/commands.xml');root=ET.fromstring(await response.read())
        values={p.findtext('name'):p.findtext('value') for p in root.findall('.//property')}
        self.assertEqual(values['superBlockDynDataUpdateRate'],'60')
        response=await self.client.get('/devices/123/commands.xml');root=ET.fromstring(await response.read())
        self.assertEqual(len(root.find('properties')),0)

    async def test_normal_cloud_profile_does_not_issue_lan_property_queries(self):
        self.service.profile.pop('debug_property_reads',None)
        response=await self.client.get('/devices/123/commands.xml')
        root=ET.fromstring(await response.read())
        self.assertIsNone(root.find('.//cmd'))

    def test_diagnostics_event_history_is_bounded(self):
        for n in range(500):self.service.events.append(('synthetic',n))
        self.assertLessEqual(len(self.service.events),200)
        self.assertEqual(len(self.service.status()['events']),30)

    async def test_https_ping_returns_server_time_for_recovery(self):
        response=await self.client.get('/ping?time=1')
        self.assertEqual(response.status,200);self.assertEqual(await response.read(),b'')
        self.assertGreater(int(response.headers['x-ayla-server-time']),0)
        self.assertEqual(self.service.events[-1][0],'https_ping')

    async def test_metadata_report_is_acknowledged_and_unknown_routes_are_visible(self):
        response=await self.client.put('/devices/123.xml',data='<device><model>synthetic</model></device>')
        self.assertEqual(response.status,200)
        self.assertEqual(self.service.events[-1][0],'device_info_put')
        response=await self.client.get('/devices/123/unknown.xml')
        self.assertEqual(response.status,404)
        self.assertIn('GET /devices/ID/unknown.xml',self.service.events[-1][0])

    async def test_existing_session_resumes_only_after_key_validation(self):
        reg=bytes.fromhex('abcdef01')
        self.service.registration_id=None
        wrong=encode_datagram(7,10,101,reg,bytes(16),struct.pack('>H',30))
        self.channel.datagram_received(wrong,('127.0.0.1',49000))
        self.assertIsNone(self.service.registration_id)
        packet=encode_datagram(7,10,101,reg,self.service.key,struct.pack('>H',30))
        self.channel.datagram_received(packet,('127.0.0.1',49000))
        self.assertEqual(self.service.registration_id,reg)
        self.assertEqual(self.service.peer,('127.0.0.1',49000))
        alternate=Notifications(self.service,55056);alternate.connection_made(Transport())
        alternate.datagram_received(packet,('127.0.0.1',49001))
        self.assertEqual(self.service.peer,('127.0.0.1',49000))

    async def test_unknown_key_recovery_echo_preserves_authenticated_bytes(self):
        unknown_key=bytes(reversed(range(16)));reg=bytes.fromhex('abcdef01')
        self.service.registration_id=None
        packet=encode_datagram(7,10,101,reg,unknown_key,struct.pack('>H',30))
        self.channel.datagram_received(packet,('127.0.0.1',49000))
        echoed,peer=self.channel.transport.sent[-1]
        self.assertEqual(echoed,bytes((3,))+packet[1:])
        self.assertEqual(decode_datagram(echoed,unknown_key)['operation'],'keepalive')
        count=len(self.channel.transport.sent)
        self.channel.datagram_received(packet,('127.0.0.1',49000))
        self.assertEqual(len(self.channel.transport.sent),count)
        dsn=b'SYNTHETIC\0';data=bytes((0,0,len(dsn)))+dsn+struct.pack('>BBHIH',1,1,11,102,30)
        registration=data+hashlib.sha1(data+unknown_key).digest()
        self.channel.datagram_received(registration,('127.0.0.1',49000))
        echoed,peer=self.channel.transport.sent[-1]
        self.assertEqual(echoed,bytes((2,))+registration[1:])
        self.assertIsNone(self.service.registration_id)

    async def test_bootstrap_requests_only_reporting_not_captured_controls(self):
        self.service.profile['reporting_mask']='01,01,01,01'
        response=await self.client.get('/devices/123/commands.xml')
        root=ET.fromstring(await response.read())
        self.assertEqual([x.findtext('name') for x in root.findall('.//property')],['periodicParameterSetting'])
        self.service.reading_at=time.time()
        response=await self.client.get('/devices/123/commands.xml')
        root=ET.fromstring(await response.read())
        self.assertEqual(len(root.find('properties')),0)

    async def test_explicit_property_query_is_get_and_response_is_correlated(self):
        response=await self.client.get('/devices/123/commands.xml')
        root=ET.fromstring(await response.read());cmd=root.find('.//cmd')
        self.assertEqual(cmd.findtext('method'),'GET')
        self.assertEqual(cmd.findtext('resource'),'property.json?name=superBlockDyn1')
        self.assertEqual(cmd.findtext('uri'),'/local_read.json')
        identifier=int(cmd.findtext('id'))
        blocks=[bytearray(n) for n in (8,148,230,52,52)]
        for offset in (0,12):blocks[3][offset:offset+2]=round((130-32)/1.8*256).to_bytes(2,'big')
        blocks[3][31]=4
        value=','.join(b.hex() for b in blocks)
        response=await self.client.put(f'/devices/123/local_read.json?cmd_id={identifier+1}&status=200',json={'name':'superBlockDyn1','value':value})
        self.assertEqual(response.status,400);self.assertIsNone(self.service.reading)
        response=await self.client.put(f'/devices/123/local_read.json?cmd_id={identifier}&status=200',json={'name':'superBlockDyn1','value':value})
        self.assertEqual(response.status,200);self.assertEqual(self.service.reading['target_f'],130)
        self.assertIsNone(self.service.awaiting_read)

    async def test_property_query_variants_stop_after_bounded_404s(self):
        resources=[]
        for index in range(4):
            self.service.read_queued=True
            response=await self.client.get('/devices/123/commands.xml')
            root=ET.fromstring(await response.read());cmd=root.find('.//cmd')
            resources.append(cmd.findtext('resource'))
            identifier=int(cmd.findtext('id'))
            response=await self.client.put(f'/devices/123/local_read.json?cmd_id={identifier}&status=404',data='')
            self.assertEqual(response.status,200)
        self.assertEqual(len(set(resources)),4)
        self.assertEqual(self.service.read_resource_index,4)
        response=await self.client.get('/devices/123/commands.xml')
        root=ET.fromstring(await response.read())
        self.assertIsNone(root.find('.//cmd'))
        self.assertIsNone(self.service.reading)

    async def test_reporting_wire_preserves_legacy_empty_tags_and_declaration(self):
        self.service.profile['reporting_mask']='01,01,01,01'
        response=await self.client.get('/devices/123/commands.xml');body=await response.read()
        self.assertTrue(body.startswith(b'<?xml version="1.0" encoding="UTF-8"?>'))
        self.assertIn(b'<mime-type></mime-type>',body)

    async def test_local_lan_provisioning_uses_private_key_without_status_leak(self):
        profile=json.loads((self.root/'profile.json').read_text())
        profile['identity_xml']=profile['identity_xml'].replace('</device>','<lan-enabled>false</lan-enabled><local-access-enabled>false</local-access-enabled></device>')
        profile['lanip']={'status':'enable','lanip_key':'SYNTHETIC_KEY_ONLY','lanip_key_id':1,'keep_alive':30,'auto_sync':1}
        (self.root/'profile.json').write_text(json.dumps(profile));self.service.load_profile()
        response=await self.client.get('/dsns/SYNTHETIC.xml');root=ET.fromstring(await response.read())
        self.assertEqual(root.findtext('lan-enabled'),'true')
        response=await self.client.get('/devices/123/lan.json');data=await response.json()
        self.assertEqual(data['lanip']['lanip_key'],'SYNTHETIC_KEY_ONLY')
        response=await self.client.get('/devices/123/commands.xml');root=ET.fromstring(await response.read())
        cmd=root.find('.//cmd');self.assertEqual(cmd.findtext('method'),'PUT')
        self.assertEqual(cmd.findtext('resource'),'lanip.json')
        self.assertEqual(json.loads(cmd.findtext('data'))['lanip']['status'],'enable')
        identifier=int(cmd.findtext('id'))
        response=await self.client.put(f'/devices/123/local_lan_setup.json?cmd_id={identifier}&status=200',data='')
        self.assertEqual(response.status,200)
        self.assertEqual(self.service.status()['lan_setup_status'],200)
        self.assertNotIn('SYNTHETIC_KEY_ONLY',str(self.service.status()))

    async def test_local_key_refresh_notification_is_bounded_and_well_formed(self):
        self.service.registration_id=None
        foreign=bytes(reversed(range(16)));reg=bytes.fromhex('abcdef01')
        packet=encode_datagram(7,10,101,reg,foreign,struct.pack('>H',30))
        self.channel.datagram_received(packet,('127.0.0.1',49000))
        await asyncio.sleep(2.05)
        notification,peer=self.channel.transport.sent[-1]
        self.assertEqual(notification[0],4)
        self.assertEqual(notification[4:8],reg)
        self.assertEqual(decode_datagram(notification,self.service.key)['operation'],'notify')
        with self.assertRaises(ValueError):decode_datagram(notification,foreign)
        self.assertEqual(sum(e[0]=='local_key_refresh_notification' for e in self.service.events),1)

    async def test_authenticated_probe_recovers_existing_notification_session(self):
        self.service.registration_id=None
        reg=bytes.fromhex('abcdef01')
        packet=encode_datagram(5,17,202,reg,self.service.key)
        self.channel.datagram_received(packet,('127.0.0.1',49000))
        reply,peer=self.channel.transport.sent[-1]
        decoded=decode_datagram(reply,self.service.key)
        self.assertEqual(decoded['operation'],'probe_response')
        self.assertEqual(decoded['sequence'],17)
        self.assertEqual(self.service.peer,('127.0.0.1',49000))

    async def test_commissioning_lifetime_stays_bounded(self):
        self.service.active=False
        with self.assertRaises(ValueError):await self.service.start(901,None)
