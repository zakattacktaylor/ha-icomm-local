import asyncio
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from aiohttp import ClientSession,web

spec=importlib.util.spec_from_file_location('icomm_capture',Path(__file__).resolve().parents[1]/'addons/icomm_emulator/capture.py')
capture=importlib.util.module_from_spec(spec);spec.loader.exec_module(capture)


class QueueUDP(asyncio.DatagramProtocol):
    def __init__(self,queue,echo=False):self.queue=queue;self.echo=echo
    def connection_made(self,transport):self.transport=transport
    def datagram_received(self,data,peer):
        self.queue.put_nowait((data,peer))
        if self.echo:self.transport.sendto(b'reply:'+data,peer)


class UDPTests(unittest.IsolatedAsyncioTestCase):
    async def test_roundtrip_is_byte_identical_and_client_channels_are_separate(self):
        loop=asyncio.get_running_loop();server_queue=asyncio.Queue()
        server,_=await loop.create_datagram_endpoint(lambda:QueueUDP(server_queue,True),local_addr=('127.0.0.2',0))
        port=server.get_extra_info('sockname')[1]
        with tempfile.TemporaryDirectory() as directory:
            recording=capture.Recording(Path(directory));forward=capture.UDPForwarder(port,'127.0.0.2',['127.0.0.1'],recording)
            listener,_=await loop.create_datagram_endpoint(lambda:forward,local_addr=('127.0.0.1',port))
            clients=[]
            try:
                peers=[]
                for suffix in (b'one',b'two'):
                    replies=asyncio.Queue();client,_=await loop.create_datagram_endpoint(lambda:QueueUDP(replies),local_addr=('127.0.0.1',0))
                    clients.append(client);payload=bytes(range(256))+suffix
                    client.sendto(payload,('127.0.0.1',port))
                    sent,peer=await asyncio.wait_for(server_queue.get(),1);peers.append(peer)
                    self.assertEqual(sent,payload)
                    received,_=await asyncio.wait_for(replies.get(),1);self.assertEqual(received,b'reply:'+payload)
                self.assertNotEqual(peers[0],peers[1])
                rows=[json.loads(x) for x in (Path(directory)/'udp.jsonl').read_text().splitlines()]
                self.assertEqual([x['direction'] for x in rows],['heater_to_cloud','cloud_to_heater']*2)
                self.assertEqual(forward.status()['responses'],2)
                denied_queue=asyncio.Queue();denied,_=await loop.create_datagram_endpoint(lambda:QueueUDP(denied_queue),local_addr=('127.0.0.3',0));clients.append(denied)
                denied.sendto(b'blocked',('127.0.0.1',port));await asyncio.sleep(.02)
                self.assertEqual(forward.dropped,1)
                self.assertTrue(server_queue.empty())
            finally:
                for client in clients:client.close()
                await forward.close();server.close()


class ManagementTests(unittest.IsolatedAsyncioTestCase):
    async def test_api_requires_token_and_bad_lifetime_does_not_arm_listeners(self):
        with tempfile.TemporaryDirectory() as directory:
            harness=capture.Harness(Path(directory),['127.0.0.1'])
            runner=web.AppRunner(capture.create_app(harness,'synthetic-management-token'))
            await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
            base='http://127.0.0.1:'+str(site._server.sockets[0].getsockname()[1])
            try:
                async with ClientSession() as session:
                    async with session.get(base+'/status') as response:self.assertEqual(response.status,401)
                    headers={'Authorization':'Bearer synthetic-management-token'}
                    async with session.get(base+'/status',headers=headers) as response:
                        self.assertEqual(response.status,200);self.assertFalse((await response.json())['active'])
                    async with session.post(base+'/capture/start',headers=headers,json={'seconds':1000}) as response:self.assertEqual(response.status,400)
                    self.assertFalse(harness.status()['active'])
                    async with session.post(base+'/capture/stop',headers=headers,json={'capture_id':'stale-id'}) as response:self.assertEqual(response.status,409)
            finally:await runner.cleanup()


class RecordingTests(unittest.TestCase):
    def test_storage_limit_does_not_raise_or_corrupt_existing_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            recording=capture.Recording(Path(directory));recording.write('stream',b'first')
            recording.size=capture.MAX_CAPTURE_BYTES
            recording.write('stream',b'overflow')
            self.assertTrue(recording.exhausted);self.assertEqual((Path(directory)/'stream').read_bytes(),b'first')

class HTTPSForwardingTests(unittest.IsolatedAsyncioTestCase):
    async def test_upstream_tls_verification_and_raw_http_preservation(self):
        import ssl
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);await asyncio.to_thread(capture.prepare_tls,root)
            request=b'GET /commands.xml HTTP/1.1\r\nHost: original-oem.example\r\nX-Ayla-Auth-Key: synthetic\r\n\r\n'
            response=b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n5\r\nhello\r\n0\r\n\r\n'
            context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(root/'cert.pem',root/'key.pem')
            seen=asyncio.Future()
            async def origin(reader,writer):
                try:
                    data=await reader.readexactly(len(request));seen.set_result(data)
                    writer.write(response);await writer.drain()
                finally:writer.close();await writer.wait_closed()
            upstream=await asyncio.start_server(origin,'127.0.0.1',0,ssl=context)
            trust=ssl.create_default_context(cafile=str(root/'cert.pem'))
            relay=capture.HTTPSForwarder(capture.Recording(root),'127.0.0.1',
                'proxy-ingress-usfield.aylanetworks.com',trust,['127.0.0.1'],
                upstream_port=upstream.sockets[0].getsockname()[1])
            listener=await asyncio.start_server(relay.handle,'127.0.0.1',0)
            try:
                reader,writer=await asyncio.open_connection('127.0.0.1',listener.sockets[0].getsockname()[1])
                writer.write(request);await writer.drain()
                self.assertEqual(await asyncio.wait_for(reader.readexactly(len(response)),3),response)
                self.assertEqual(await seen,request)
                await reader.read();writer.close();await writer.wait_closed()
                self.assertEqual((root/'https-001-heater.bin').read_bytes(),request)
                self.assertEqual((root/'https-001-cloud.bin').read_bytes(),response)
                self.assertEqual(relay.failures,0)
            finally:
                listener.close();upstream.close();await listener.wait_closed();await upstream.wait_closed();await relay.close()
