"""Bounded byte-preserving capture service. No generated heater commands.

Private captures contain device secrets. Management API requires a separate
installation token. Listener lifetime is independently bounded on the Green.
"""
import asyncio
from collections import deque
from contextlib import suppress
from datetime import datetime, timezone
import hmac
import io
import ipaddress
import json
import os
from pathlib import Path
import signal
import ssl
import subprocess
import tarfile
import time

from aiohttp import web

MAX_CAPTURE_BYTES = 24_000_000


class Recording:
    def __init__(self, root):
        self.root = root
        self.size = 0
        self.exhausted = False

    def write(self, name, data):
        if self.size + len(data) > MAX_CAPTURE_BYTES:
            self.exhausted = True
            return
        self.size += len(data)
        with (self.root / name).open('ab') as output:
            output.write(data)

    def datagram(self, direction, local_port, peer, data):
        row = {'time': time.time(), 'direction': direction, 'local_port': local_port,
               'peer': list(peer), 'payload_hex': data.hex()}
        self.write('udp.jsonl', (json.dumps(row)+'\n').encode())


class RemoteUDP(asyncio.DatagramProtocol):
    def __init__(self, owner, peer):
        self.owner, self.peer = owner, peer

    def datagram_received(self, data, address):
        self.owner.recording.datagram('cloud_to_heater', self.owner.local_port, address, data)
        self.owner.responses += 1
        self.owner.transport.sendto(data, self.peer)

    def error_received(self, error):
        self.owner.errors += 1


class UDPForwarder(asyncio.DatagramProtocol):
    def __init__(self, local_port, upstream, allowed_peers, recording):
        self.local_port, self.upstream = local_port, upstream
        self.allowed_peers, self.recording = set(allowed_peers), recording
        self.transport = None
        self.channels = {}
        self.creating = set()
        self.pending = {}
        self.tasks = set()
        self.requests = self.responses = self.errors = self.dropped = 0

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, peer):
        if peer[0] not in self.allowed_peers or len(self.channels) + len(self.creating) >= 8 and peer not in self.channels and peer not in self.creating:
            self.dropped += 1
            return
        self.recording.datagram('heater_to_cloud', self.local_port, peer, data)
        self.requests += 1
        if peer in self.channels:
            self.channels[peer].sendto(data)
        else:
            queue = self.pending.setdefault(peer, deque(maxlen=16))
            queue.append(data)
            if peer not in self.creating:
                self.creating.add(peer)
                task = asyncio.create_task(self._open(peer))
                self.tasks.add(task)
                task.add_done_callback(self.tasks.discard)

    async def _open(self, peer):
        try:
            transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(
                lambda: RemoteUDP(self, peer), remote_addr=(self.upstream, self.local_port))
            self.channels[peer] = transport
            for data in self.pending.pop(peer, ()):
                transport.sendto(data)
        except (OSError, ValueError):
            self.errors += 1
            self.pending.pop(peer, None)
        finally:
            self.creating.discard(peer)

    async def close(self):
        for task in list(self.tasks):task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        for channel in self.channels.values():channel.close()
        if self.transport:self.transport.close()
        self.channels.clear()

    def status(self):
        return {'port': self.local_port, 'requests': self.requests, 'responses': self.responses,
                'errors': self.errors, 'dropped': self.dropped}


class HTTPSForwarder:
    def __init__(self, recording, upstream_address, upstream_hostname, upstream_context, allowed_peers, upstream_port=443):
        self.recording = recording
        self.upstream_address, self.upstream_hostname = upstream_address, upstream_hostname
        self.upstream_port = upstream_port
        self.upstream_context, self.allowed_peers = upstream_context, set(allowed_peers)
        self.tasks = set()
        self.count = self.failures = 0

    async def copy(self, reader, writer, filename):
        while data := await reader.read(65536):
            self.recording.write(filename, data)
            writer.write(data)
            await writer.drain()

    async def handle(self, reader, writer):
        if writer.get_extra_info('peername')[0] not in self.allowed_peers:
            writer.close()
            return
        task = asyncio.current_task()
        self.tasks.add(task)
        self.count += 1
        number = self.count
        remote_writer = None
        try:
            remote_reader, remote_writer = await asyncio.wait_for(asyncio.open_connection(
                self.upstream_address, self.upstream_port, ssl=self.upstream_context,
                server_hostname=self.upstream_hostname), 15)
            metadata = {'time': time.time(), 'session': number,
                'cipher': writer.get_extra_info('cipher'), 'upstream_verified': True}
            self.recording.write('https-sessions.jsonl', (json.dumps(metadata)+'\n').encode())
            copies = [asyncio.create_task(self.copy(reader, remote_writer, f'https-{number:03}-heater.bin')),
                      asyncio.create_task(self.copy(remote_reader, writer, f'https-{number:03}-cloud.bin'))]
            try:
                done, _ = await asyncio.wait(copies, return_when=asyncio.FIRST_COMPLETED)
                for item in done:item.result()
            finally:
                for item in copies:item.cancel()
                await asyncio.gather(*copies, return_exceptions=True)
        except (OSError, TimeoutError, ssl.SSLError):
            self.failures += 1
        finally:
            writer.close()
            if remote_writer:remote_writer.close()
            await asyncio.gather(writer.wait_closed(), *([remote_writer.wait_closed()] if remote_writer else []), return_exceptions=True)
            self.tasks.discard(task)

    async def close(self):
        for task in list(self.tasks):task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)


class Harness:
    def __init__(self, root, allowed_peers):
        self.root, self.allowed_peers = root, allowed_peers
        self.capture_id = None
        self.expires = 0
        self.tls_server = self.https = self.recording = None
        self.udp = []
        self.timer = None
        self.lock = asyncio.Lock()
        self.last_status = None

    def status(self):
        if not self.capture_id:
            return {'active': False, 'last': self.last_status}
        return {'active': True, 'capture_id': self.capture_id, 'expires_unix': self.expires,
            'bytes_saved': self.recording.size, 'recording_limit_reached': self.recording.exhausted,
            'https_sessions': self.https.count, 'https_failures': self.https.failures,
            'udp': [item.status() for item in self.udp]}

    def tls_context(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_2
        context.set_ciphers('DHE-RSA-AES256-SHA:AES128-SHA:AES256-SHA:@SECLEVEL=0')
        context.load_cert_chain(self.root/'cert.pem', self.root/'key.pem')
        context.load_dh_params(self.root/'dh.pem')
        return context

    async def start(self, config):
        async with self.lock:
            if self.capture_id:raise ValueError('A capture is already active')
            seconds = int(config.get('seconds', 300))
            if not 10 <= seconds <= 300:raise ValueError('Capture lifetime must be 10–300 seconds')
            tls_address = str(ipaddress.IPv4Address(config['upstream_tls_ip']))
            udp_address = str(ipaddress.IPv4Address(config['upstream_udp_ip']))
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+str(time.time_ns()%1_000_000)
            directory = self.root/'captures'/stamp
            directory.mkdir(parents=True)
            self.recording = Recording(directory)
            self.capture_id, self.expires = stamp, time.time()+seconds
            upstream_context = ssl.create_default_context(cafile=str(Path(__file__).with_name('entrust-root-g2.crt')))
            self.https = HTTPSForwarder(self.recording,tls_address,
                'proxy-ingress-usfield.aylanetworks.com',upstream_context,self.allowed_peers)
            try:
                downstream_context = await asyncio.to_thread(self.tls_context)
                self.tls_server = await asyncio.start_server(self.https.handle,'0.0.0.0',8444,
                    ssl=downstream_context,ssl_handshake_timeout=35)
                for port in (55055,55056):
                    item=UDPForwarder(port,udp_address,self.allowed_peers,self.recording)
                    await asyncio.get_running_loop().create_datagram_endpoint(lambda item=item:item,
                        local_addr=('0.0.0.0',port))
                    self.udp.append(item)
            except BaseException:
                await self._stop()
                raise
            self.timer=asyncio.create_task(self._expiry(stamp,seconds))
            return self.status()

    async def _expiry(self, capture_id, seconds):
        await asyncio.sleep(seconds)
        await self.stop(capture_id)

    async def stop(self, expected_id=None):
        async with self.lock:
            if expected_id and self.capture_id != expected_id:
                raise ValueError('Capture ID does not match')
            await self._stop()
            return self.status()

    async def _stop(self):
        if not self.capture_id:return
        self.last_status = self.status()
        self.last_status['stopped_unix'] = time.time()
        if self.timer and self.timer is not asyncio.current_task():
            self.timer.cancel()
        self.timer = None
        if self.tls_server:
            self.tls_server.close()
            await self.tls_server.wait_closed()
        if self.https:await self.https.close()
        await asyncio.gather(*(item.close() for item in self.udp))
        (self.recording.root/'summary.json').write_text(json.dumps(self.last_status,indent=2))
        self.tls_server=None;self.udp=[];self.capture_id=None


def archive(directory):
    buffer=io.BytesIO()
    with tarfile.open(fileobj=buffer,mode='w:gz') as output:
        for file in directory.iterdir():
            if file.is_file():output.add(file,arcname=file.name)
    return buffer.getvalue()


def create_app(harness, token):
    @web.middleware
    async def authentication(request, handler):
        supplied=request.headers.get('Authorization','')
        if not hmac.compare_digest(supplied,'Bearer '+token):raise web.HTTPUnauthorized()
        return await handler(request)
    app=web.Application(middlewares=[authentication],client_max_size=8192)
    async def status(request):return web.json_response(harness.status())
    async def start(request):
        try:return web.json_response(await harness.start(await request.json()))
        except (ValueError,KeyError) as error:raise web.HTTPBadRequest(text=str(error)) from None
    async def stop(request):
        try:return web.json_response(await harness.stop((await request.json()).get('capture_id')))
        except ValueError as error:raise web.HTTPConflict(text=str(error)) from None
    async def download(request):
        name=request.match_info['capture_id']
        if '/' in name or '..' in name or not name.replace('-','').isalnum():raise web.HTTPBadRequest()
        directory=harness.root/'captures'/name
        if not directory.is_dir():raise web.HTTPNotFound()
        if harness.capture_id==name:raise web.HTTPConflict(text='Stop the capture before exporting')
        return web.Response(body=await asyncio.to_thread(archive,directory),content_type='application/gzip')
    app.router.add_get('/status',status)
    app.router.add_post('/capture/start',start)
    app.router.add_post('/capture/stop',stop)
    app.router.add_get('/captures/{capture_id}/archive',download)
    return app


def prepare_tls(root):
    if not (root/'key.pem').exists() or not (root/'cert.pem').exists():
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-sha256','-nodes',
            '-keyout',str(root/'key.pem'),'-out',str(root/'cert.pem'),'-days','365',
            '-subj','/CN=proxy-ingress-usfield.aylanetworks.com'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    if not (root/'dh.pem').exists():
        subprocess.run(['openssl','genpkey','-genparam','-algorithm','DH','-pkeyopt','group:ffdhe2048',
            '-out',str(root/'dh.pem')],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)


async def main():
    os.umask(0o077)
    root=Path('/data')
    options=json.loads((root/'options.json').read_text())
    token=options['api_token']
    peers=options['allowed_peers']
    if len(token)<24 or not peers:raise ValueError('Configure a management token and allowed peers first')
    for peer in peers:ipaddress.IPv4Address(peer)
    await asyncio.to_thread(prepare_tls,root)
    harness=Harness(root,peers)
    runner=web.AppRunner(create_app(harness,token),access_log=None)
    await runner.setup()
    await web.TCPSite(runner,'0.0.0.0',8787).start()
    stopped=asyncio.Event()
    loop=asyncio.get_running_loop()
    for sig in (signal.SIGTERM,signal.SIGINT):loop.add_signal_handler(sig,stopped.set)
    print('iCOMM harness ready; recording listeners disabled until a bounded capture starts',flush=True)
    try:await stopped.wait()
    finally:await harness.stop();await runner.cleanup()


if __name__=='__main__':asyncio.run(main())
