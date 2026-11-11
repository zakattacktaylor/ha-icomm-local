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
import xml.etree.ElementTree as ET

from aiohttp import web
from ans import decode_datagram, encode_datagram, verify_registration
from protocol import telemetry, setpoint_frame, mode_frame

READ_RESOURCES=('property.json?name=superBlockDyn1','/property.json?name=superBlockDyn1','properties.json?name=superBlockDyn1','/properties.json?name=superBlockDyn1')


class Notifications(asyncio.DatagramProtocol):
    def __init__(self, service, port):
        self.service, self.port = service, port
        self.transport = None
        self.last_error_reply={}

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, packet, peer):
        service = self.service
        if peer[0] not in service.allowed_peers:return
        try:
            if packet[0] == 0:
                # Bind registration to the single provisioned device as well as its key.
                dsn = packet[3:3+packet[2]].rstrip(b'\0').decode('ascii')
                if dsn != service.dsn:return
                message = decode_datagram(packet)
                if message['operation']!='register':return
                if not verify_registration(packet, service.key):
                    self.error_echo(packet,peer,2)
                    return
                service.registration_id = secrets.token_bytes(4)
                service.peer = peer
                self.reply(2, message['sequence'], struct.pack('>HB',30,0),peer)
                service.schedule_probe(self,peer,min(message['interval_seconds'],300),message['sequence'])
                service.events.append(('registered', time.time()))
                return
            try:message = decode_datagram(packet, service.key)
            except ValueError:
                if service.registration_id is None and packet[0]==4 and len(packet)>=40 and (len(packet)-24)%16==0:
                    self.error_echo(packet,peer,3)
                    if not service.key_refresh_sent:
                        service.key_refresh_sent=True
                        registration_id=packet[4:8]
                        async def refresh_key():
                            await asyncio.sleep(2)
                            if service.active and service.registration_id is None:
                                message=encode_datagram(9,0,int(time.monotonic()*1000)&0xffffffff,registration_id,service.key)
                                self.transport.sendto(message,peer)
                                service.events.append(('local_key_refresh_notification',time.time()))
                        task=asyncio.create_task(refresh_key());service.tasks.add(task);task.add_done_callback(service.tasks.discard)
                raise
            if service.registration_id is None:
                if message['operation'] not in ('keepalive','request_probe'):return
                service.registration_id=packet[4:8]
                service.events.append(('session_resumed',time.time()))
            elif packet[4:8] != service.registration_id:
                self.error_echo(packet,peer,3)
                return
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

    def error_echo(self, packet, peer, format_code):
        # The agent authenticates an echoed opaque request with its own key.
        # Preserve the signed/encrypted bytes; change ONLY the outer format.
        stamp=time.monotonic();marker=(peer,format_code)
        if stamp-self.last_error_reply.get(marker,-10)<2:return
        if len(self.last_error_reply)>16:self.last_error_reply.clear()
        self.last_error_reply[marker]=stamp
        self.transport.sendto(bytes((format_code,))+packet[1:],peer)
        self.service.events.append(('registration_refresh_requested',time.time()))

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
        self.invalid_datagrams=0;self.expires=0;self.started_at=0;self.key_refresh_sent=False
        self.uploads={};self.rejected_uploads=0
        self.read_queued=True;self.read_id=secrets.randbelow(1<<30);self.awaiting_read=None;self.last_read_sent=0;self.last_read_status=None;self.read_resource_index=0;self.lan_setup_pending=False;self.lan_setup_id=None;self.lan_setup_status=None

    def status(self):
        return {'active':self.active,'expires_unix':self.expires,
            'registered':self.peer is not None,'reading':self.reading,
            'reading_age_seconds':time.time()-self.reading_at if self.reading_at else None,
            'pending':self.pending is not None,'invalid_datagrams':self.invalid_datagrams,
            'uploads':self.uploads,'rejected_uploads':self.rejected_uploads,'last_read_status':self.last_read_status,'read_resource_index':self.read_resource_index,
            'lan_setup_status':getattr(self,'lan_setup_status',None),
            'events':self.events[-30:]}

    def load_profile(self):
        profile=json.loads((self.root/'profile.json').read_text())
        identity=ET.fromstring(profile['identity_xml'])
        key=base64.b64decode(identity.findtext('ans-cipher-key'),validate=True)[:16]
        if len(key)!=16:raise ValueError('Invalid notification key')
        self.dsn=profile['dsn'];self.device_id=str(profile['device_id']);self.key=key
        mask=profile.get('reporting_mask')
        if mask is not None and (not isinstance(mask,str) or len(mask)>1024 or not re.fullmatch(r'[01]+(?:,[01]+){3}',mask)):
            raise ValueError('Invalid reporting mask')
        rate=profile.get('reporting_rate')
        if rate is not None and (not isinstance(rate,int) or rate!=21601):raise ValueError('Unvalidated reporting rate')
        lanip=profile.get('lanip')
        if lanip is not None:
            key=lanip.get('lanip_key','')
            if not isinstance(key,str) or not key.isascii() or not 16<=len(key)<=32:raise ValueError('Invalid LAN key')
            if lanip.get('status')!='enable' or not isinstance(lanip.get('lanip_key_id'),int) or not 1<=lanip['lanip_key_id']<=65535:raise ValueError('Invalid LAN key ID')
            if lanip.get('keep_alive')!=30:raise ValueError('Invalid LAN heartbeat')
        self.profile=profile
        self.lan_setup_pending=lanip is not None
        self.lan_setup_id=None;self.lan_setup_status=None

    def schedule_probe(self, channel, peer, seconds, sequence):
        async def later():
            await asyncio.sleep(seconds)
            if self.active:channel.reply(5,sequence,b'',peer)
        task=asyncio.create_task(later());self.tasks.add(task);task.add_done_callback(self.tasks.discard)

    async def start(self, seconds, tls_context):
        if self.active:raise ValueError('Emulator already active')
        if not isinstance(seconds,int) or not 10<=seconds<=300:raise ValueError('Lifetime must be 10–300 seconds')
        self.load_profile();self.registration_id=None;self.peer=None;self.pending=None
        self.reading=None;self.reading_at=0;self.events=[];self.invalid_datagrams=0;self.key_refresh_sent=False
        self.uploads={};self.rejected_uploads=0
        self.read_queued=True;self.read_id=secrets.randbelow(1<<30);self.awaiting_read=None;self.last_read_sent=0;self.last_read_status=None;self.read_resource_index=0;self.lan_setup_pending=self.profile.get('lanip') is not None;self.lan_setup_id=None;self.lan_setup_status=None
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
            async def poll_readings():
                while self.active:
                    await asyncio.sleep(3)
                    interval=3 if self.pending else 30
                    if self.peer and not self.profile.get('lanip') and self.read_resource_index<len(READ_RESOURCES) and time.time()-self.last_read_sent>=interval:
                        self.read_queued=True
                        self.notify()
            polling=asyncio.create_task(poll_readings());self.tasks.add(polling);polling.add_done_callback(self.tasks.discard)
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
        self.read_queued=True
        self.notify()
        return self.status()

    def accept_telemetry(self, value):
        reading=asdict(telemetry(value));self.reading=reading;self.reading_at=time.time()
        self.events.append(('telemetry',self.reading_at))
        pending=self.pending
        if pending and pending['sent_at'] and self.reading_at>pending['sent_at']:
            actual=reading['target_f'] if pending['kind']=='target' else reading['mode']
            expected=pending['value']
            if actual==expected or isinstance(actual,(float,int)) and isinstance(expected,(float,int)) and abs(actual-expected)<.02:
                self.events.append(('command_confirmed',time.time()));self.pending=None

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
        if isinstance(element,bytes):body=element
        else:
            ET.indent(element,space='  ')
            body=b'<?xml version="1.0" encoding="UTF-8"?>\n'+ET.tostring(element,encoding='utf-8',short_empty_elements=False)
        response=web.Response(body=body,content_type='application/xml',charset='utf-8',headers=headers)
        response.enable_chunked_encoding()
        return response

    async def http(self, request):
        if request.remote not in self.allowed_peers:raise web.HTTPForbidden()
        path=request.path
        if request.method=='GET' and path==f'/dsns/{self.dsn}.xml':
            # Preserve the legacy agent's exact XML declaration/empty-tag style.
            identity=self.profile['identity_xml']
            for name,value in (('unix-time',str(int(time.time()))),):
                identity=re.sub(r'(<'+name+r'(?:\s[^>]*)?>)[^<]*(</'+name+r'>)',
                    lambda match:match[1]+escape(value)+match[2],identity)
            if self.profile.get('lanip'):
                for name in ('lan-enabled','local-access-enabled'):
                    identity=re.sub(r'(<'+name+r'>)[^<]*(</'+name+r'>)',lambda match:match[1]+'true'+match[2],identity)
            phase='initial' if 'x-ayla-client-auth' in request.headers else 'key'
            self.events.append(('identity_'+phase,time.time()))
            return self.xml_response(identity.encode())
        prefix=f'/devices/{self.device_id}'
        if request.method=='GET' and path==prefix+'/lan.json' and self.profile.get('lanip'):
            self.events.append(('lan_key_requested',time.time()))
            return web.json_response({'lanip':self.profile['lanip']})
        if request.method=='PUT' and path==prefix+'/local_lan_setup.json':
            try:
                if int(request.query.get('cmd_id','-1'))!=self.lan_setup_id:raise ValueError()
                self.lan_setup_status=int(request.query.get('status','0'))
            except ValueError:raise web.HTTPBadRequest()
            self.events.append(('lan_setup_result_'+str(self.lan_setup_status),time.time()))
            return web.Response(status=200)
        if request.method=='PUT' and path==prefix+'.xml':
            try:
                info=ET.fromstring(await request.read())
                if info.tag!='device':raise ValueError()
            except (ET.ParseError,ValueError):raise web.HTTPBadRequest()
            # This is the device reporting its own metadata, not a device command.
            self.events.append(('device_info_put',time.time()))
            return web.Response(status=200)
        if request.method=='GET' and path==prefix+'/commands.xml':
            root=ET.Element('commands');properties=ET.SubElement(root,'properties')
            # Only the verified report-selection request is used during bootstrap.
            # No captured operating mode, firmware or schedules are replayed.
            if self.profile.get('reporting_mask') and not self.profile.get('lanip') and not self.reading_at:
                item=ET.SubElement(properties,'property')
                for name,value in (('base-type','string'),('mime-type',''),('name','periodicParameterSetting'),('value',self.profile['reporting_mask'])):
                    ET.SubElement(item,name).text=value
                if self.profile.get('reporting_rate') is not None:
                    item=ET.SubElement(properties,'property')
                    for name,value in (('base-type','integer'),('mime-type',''),('name','superBlockDynDataUpdateRate'),('value',str(self.profile['reporting_rate']))):
                        ET.SubElement(item,name).text=value
                self.events.append(('reporting_requested',time.time()))
            if self.pending:
                if time.time()>self.pending['expires']:
                    self.events.append(('command_expired',time.time()));self.pending=None
                elif self.pending['sent_at'] is None:
                    item=ET.SubElement(properties,'property')
                    for name,value in (('base-type','string'),('mime-type',''),('name','setBlockParameter'),('value',self.pending['frame'])):
                        ET.SubElement(item,name).text=value
                    self.pending['sent_at']=time.time()
            ET.SubElement(root,'schedules');cmds=ET.SubElement(root,'cmds')
            if self.read_queued and not self.profile.get('lanip') and self.read_resource_index<len(READ_RESOURCES):
                self.read_id+=1;self.awaiting_read=self.read_id
                command=ET.SubElement(cmds,'cmd')
                # The agent prefixes resource with '/', but strips '/' from uri.
                for name,value in (('id',str(self.read_id)),('method','GET'),('resource',READ_RESOURCES[self.read_resource_index]),('uri','/local_read.json'),('data','')):
                    ET.SubElement(command,name).text=value
                self.read_queued=False;self.last_read_sent=time.time()
                self.events.append(('telemetry_read_requested',self.last_read_sent))
            if self.lan_setup_pending:
                self.read_id+=1;self.lan_setup_id=self.read_id
                command=ET.SubElement(cmds,'cmd')
                for name,value in (('id',str(self.lan_setup_id)),('method','PUT'),('resource','lanip.json'),('uri','/local_lan_setup.json'),('data',json.dumps({'lanip':self.profile['lanip']},separators=(',',':')))):
                    ET.SubElement(command,name).text=value
                self.lan_setup_pending=False
            self.events.append(('commands_get',time.time()))
            return self.xml_response(root)
        if request.method=='PUT' and path==prefix+'/local_read.json':
            try:
                if int(request.query.get('cmd_id','-1'))!=self.awaiting_read:raise ValueError('Stale read response')
                status=int(request.query.get('status','0'));self.last_read_status=status
                if status==200:
                    value=json.loads((await request.read()).rstrip(b'\0 \r\n'))
                    candidates=[]
                    def collect(item):
                        if isinstance(item,list):
                            for member in item:collect(member)
                        elif isinstance(item,dict):
                            if item.get('name')=='superBlockDyn1' and isinstance(item.get('value'),str):candidates.append(item['value'])
                            for name in ('property','properties'):
                                if name in item:collect(item[name])
                    collect(value)
                    if len(candidates)!=1:raise ValueError('Unexpected property response')
                    self.accept_telemetry(candidates[0])
                else:
                    self.events.append(('telemetry_read_failed_'+str(status),time.time()))
                    if status==404:
                        self.read_resource_index+=1;self.last_read_sent=0;self.read_queued=True
                self.awaiting_read=None
            except (ValueError,TypeError,KeyError):raise web.HTTPBadRequest()
            return web.Response(status=200)
        if request.method=='POST' and path.startswith(prefix+'/properties/') and path.endswith('/datapoints.xml'):
            name=path[len(prefix+'/properties/'):-len('/datapoints.xml')]
            if len(self.uploads)<32 or name in self.uploads:self.uploads[name]=self.uploads.get(name,0)+1
            try:
                body=ET.fromstring(await request.read());value=body.findtext('value')
                if value is None:value=body.findtext('.//value')
                if value is None:raise ValueError('Missing value')
                if name=='superBlockDyn1':self.accept_telemetry(value)
            except (ET.ParseError,ValueError,TypeError):
                self.rejected_uploads+=1
                raise web.HTTPBadRequest()
            return web.Response(status=200)
        # Firmware, registration/ownership and arbitrary cloud APIs are unsupported.
        label=(request.method+' '+path.replace(self.dsn,'DSN').replace(self.device_id,'ID'))[:160]
        self.events.append(('unsupported '+label,time.time()))
        raise web.HTTPNotFound()
