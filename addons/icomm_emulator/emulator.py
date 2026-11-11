"""Bounded, single-device local Ayla service; no upstream networking.

The private profile supplies the captured identity and current ANS key. No cloud
commands, firmware responses or schedules are replayed from that profile.
"""
import asyncio
import base64
from dataclasses import asdict
import json
from pathlib import Path
import secrets
import struct
import time
import re
from xml.sax.saxutils import escape
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

from aiohttp import web
from ans import decode_datagram, encode_datagram, verify_registration
from protocol import telemetry, setpoint_frame, mode_frame


class Notifications(asyncio.DatagramProtocol):
    def __init__(self, service, port):
        self.service, self.port = service, port
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, packet, peer):
        service = self.service
        if peer[0] not in service.allowed_peers:return
        try:
            if packet[0] == 0:
                if not verify_registration(packet, service.key):return
                # Bind registration to the single provisioned device as well as its key.
                dsn = packet[3:3+packet[2]].rstrip(b'\0').decode('ascii')
                if dsn != service.dsn:return
                message = decode_datagram(packet)
                service.registration_id = secrets.token_bytes(4)
                service.peer = peer
                self.reply(2, message['sequence'], struct.pack('>HB',30,0),peer)
                service.schedule_probe(self,peer,min(message['interval_seconds'],300),message['sequence'])
                service.events.append(('registered', time.time()))
                return
            if packet[4:8] != service.registration_id:return
            message = decode_datagram(packet, service.key)
            operation = message['operation']
            if operation == 'keepalive':self.reply(8,message['sequence'],b'\0',peer)
            elif operation == 'request_probe':
                self.reply(4,message['sequence'],b'\0',peer)
                service.schedule_probe(self,peer,min(message['interval_seconds'],300),message['sequence'])
            elif operation == 'probe':self.reply(6,message['sequence'],b'\0',peer)
            elif operation == 'notify_response':
                if message['sequence']==service.notify_sequence:
                    service.events.append(('notify_ack',time.time()))
            if self.port==55055 and operation in ('keepalive','request_probe'):service.peer=peer
        except (ValueError,KeyError,IndexError,UnicodeError):
            service.invalid_datagrams += 1

    def reply(self, operation, sequence, payload, peer):
        packet=encode_datagram(operation,sequence,int(time.monotonic()*1000)&0xffffffff,
            self.service.registration_id,self.service.key,payload)
        self.transport.sendto(packet,peer)


class LocalService:
    def __init__(self, root, allowed_peers):
        self.root, self.allowed_peers = Path(root), set(allowed_peers)
        self.active=False;self.runner=None;self.udp=[];self.tasks=set();self.timer=None
        self.profile=None;self.key=None;self.dsn=None;self.device_id=None
        self.registration_id=None;self.peer=None;self.notify_sequence=0
        self.pending=None;self.reading=None;self.reading_at=0;self.events=[]
        self.invalid_datagrams=0;self.expires=0;self.started_at=0

    def status(self):
        return {'active':self.active,'expires_unix':self.expires,
            'registered':self.peer is not None,'reading':self.reading,
            'reading_age_seconds':time.time()-self.reading_at if self.reading_at else None,
            'pending':self.pending is not None,'invalid_datagrams':self.invalid_datagrams,
            'events':self.events[-30:]}

    def load_profile(self):
        profile=json.loads((self.root/'profile.json').read_text())
        identity=ET.fromstring(profile['identity_xml'])
        key=base64.b64decode(identity.findtext('ans-cipher-key'),validate=True)[:16]
        if len(key)!=16:raise ValueError('Invalid notification key')
        self.dsn=profile['dsn'];self.device_id=str(profile['device_id']);self.key=key
        self.profile=profile

    def schedule_probe(self, channel, peer, seconds, sequence):
        async def later():
            await asyncio.sleep(seconds)
            if self.active:channel.reply(5,sequence,b'',peer)
        task=asyncio.create_task(later());self.tasks.add(task);task.add_done_callback(self.tasks.discard)

    async def start(self, seconds, tls_context):
        if self.active:raise ValueError('Emulator already active')
        if not isinstance(seconds,int) or not 10<=seconds<=300:raise ValueError('Lifetime must be 10–300 seconds')
        self.load_profile();self.registration_id=None;self.peer=None;self.pending=None
        self.reading=None;self.reading_at=0;self.events=[];self.invalid_datagrams=0
        seed=self.profile.get('resume_registration_id')
        if seed is not None:
            self.registration_id=bytes.fromhex(seed)
            if len(self.registration_id)!=4:raise ValueError('Invalid resume registration ID')
        self.active=True;self.started_at=time.time();self.expires=time.time()+seconds
        try:
            app=web.Application(client_max_size=65536)
            app.router.add_route('*','/{path:.*}',self.http)
            self.runner=web.AppRunner(app,access_log=None);await self.runner.setup()
            await web.TCPSite(self.runner,'0.0.0.0',8444,ssl_context=tls_context).start()
            for port in (55055,55056):
                channel=Notifications(self,port)
                transport,_=await asyncio.get_running_loop().create_datagram_endpoint(lambda c=channel:c,local_addr=('0.0.0.0',port))
                self.udp.append(channel)
            async def expire():
                await asyncio.sleep(seconds);await self.stop()
            self.timer=asyncio.create_task(expire())
        except BaseException:
            await self.stop();raise
        return self.status()

    async def stop(self):
        self.active=False;self.pending=None
        if self.timer and self.timer is not asyncio.current_task():self.timer.cancel()
        self.timer=None
        for task in list(self.tasks):task.cancel()
        await asyncio.gather(*self.tasks,return_exceptions=True);self.tasks.clear()
        for channel in self.udp:channel.transport.close()
        self.udp=[]
        if self.runner:await self.runner.cleanup()
        self.runner=None;self.peer=None
        return self.status()

    def queue(self, kind, value):
        if not self.active or not self.peer:raise ValueError('Heater has not registered locally')
        if self.pending:raise ValueError('Wait for pending command confirmation')
        if not self.reading_at or time.time()-self.reading_at>120:raise ValueError('Fresh telemetry required')
        if kind=='target':frame=setpoint_frame(value)
        elif kind=='mode':frame=mode_frame(value)
        else:raise ValueError('Unsupported control')
        self.pending={'kind':kind,'value':value,'frame':frame,'expires':time.time()+30,'sent_at':None}
        self.notify()
        return self.status()

    def notify(self):
        if not self.active or not self.peer:raise ValueError('Heater has not registered locally')
        self.notify_sequence=(self.notify_sequence+1)&65535
        self.udp[0].reply(9,self.notify_sequence,b'',self.peer)
        self.events.append(('notify_sent',time.time()))
        return self.status()

    def xml_response(self, element):
        headers={}
        # Local auth is independent of the vendor; never reuse captured cloud tokens.
        if not hasattr(self,'auth_token'):self.auth_token=secrets.token_hex(18)
        headers['x-ayla-auth-key']=self.auth_token
        body=element if isinstance(element,bytes) else ET.tostring(element,encoding='utf-8')
        response=web.Response(body=body,content_type='application/xml',charset='utf-8',headers=headers)
        response.enable_chunked_encoding()
        return response

    async def http(self, request):
        if request.remote not in self.allowed_peers:raise web.HTTPForbidden()
        path=request.path
        if request.method=='GET' and path==f'/dsns/{self.dsn}.xml':
            # Preserve the legacy agent's exact XML declaration/empty-tag style.
            identity=self.profile['identity_xml']
            for name,value in (('ans-server',self.profile['local_ans_host']),('unix-time',str(int(time.time())))):
                identity=re.sub(r'(<'+name+r'(?:\s[^>]*)?>)[^<]*(</'+name+r'>)',
                    lambda match:match[1]+escape(value)+match[2],identity)
            phase='initial' if 'x-ayla-client-auth' in request.headers else 'key'
            self.events.append(('identity_'+phase,time.time()))
            return self.xml_response(identity.encode())
        prefix=f'/devices/{self.device_id}'
        if request.method=='GET' and path==prefix+'/commands.xml':
            root=ET.Element('commands');properties=ET.SubElement(root,'properties')
            # No captured mode, firmware, schedules, or settings are replayed.
            if self.pending:
                if time.time()>self.pending['expires']:
                    self.events.append(('command_expired',time.time()));self.pending=None
                elif self.pending['sent_at'] is None:
                    item=ET.SubElement(properties,'property')
                    for name,value in (('base-type','string'),('name','setBlockParameter'),('value',self.pending['frame'])):
                        ET.SubElement(item,name).text=value
                    self.pending['sent_at']=time.time()
            ET.SubElement(root,'schedules');ET.SubElement(root,'cmds')
            self.events.append(('commands_get',time.time()))
            return self.xml_response(root)
        if request.method=='POST' and path.startswith(prefix+'/properties/') and path.endswith('/datapoints.xml'):
            name=path[len(prefix+'/properties/'):-len('/datapoints.xml')]
            try:
                body=ET.fromstring(await request.read());value=body.findtext('value')
                if value is None:value=body.findtext('.//value')
                if value is None:raise ValueError('Missing value')
                if name=='superBlockDyn1':
                    reading=asdict(telemetry(value));self.reading=reading;self.reading_at=time.time()
                    self.events.append(('telemetry',self.reading_at))
                    # Only post-delivery telemetry can confirm a command. Echoes cannot.
                    pending=self.pending
                    if pending and pending['sent_at'] and self.reading_at>pending['sent_at']:
                        actual=reading['target_f'] if pending['kind']=='target' else reading['mode']
                        expected=pending['value']
                        if actual==expected or isinstance(actual,(float,int)) and isinstance(expected,(float,int)) and abs(actual-expected)<.02:
                            self.events.append(('command_confirmed',time.time()));self.pending=None
            except (ET.ParseError,ValueError,TypeError):raise web.HTTPBadRequest()
            return web.Response(status=200)
        # Firmware, registration/ownership and arbitrary cloud APIs are unsupported.
        raise web.HTTPNotFound()
