#!/usr/bin/env python3
"""One-time, bounded iCOMM LAN-key provisioning proxy.

Operator must separately arrange scoped routing with an independent rollback.
This tool never installs network rules or sends temperature/mode commands.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import ssl
import xml.etree.ElementTree as ET

from aiohttp import ClientSession, ClientTimeout, TCPConnector, web


def forward_request_headers(headers):
    result = {k:v for k,v in headers.items() if k.lower() not in
        ('content-length','transfer-encoding','connection','accept-encoding')}
    authority = next((v for k,v in result.items() if k.lower() == 'host'), '')
    if not authority.lower().endswith('.aylanetworks.com'):
        raise ValueError('Unexpected device service authority')
    result['Accept-Encoding'] = 'identity'
    return result


def add_lan_command(body, config):
    root = ET.fromstring(body)
    if root.tag != 'commands':
        raise ValueError('Unexpected response document')
    commands = root.find('cmds')
    if commands is None or list(commands):
        return body, False
    command = ET.SubElement(commands, 'cmd')
    data = {'lanip': {'status': 'enable', 'lanip_key_id': config['key_id'],
        'lanip_key': config['key'], 'keep_alive': 30, 'auto_sync': 1}}
    # The device-agent XML protocol prepends / to resource and strips it from uri.
    for name, value in [('id','900001'), ('method','PUT'), ('resource','lanip.json'),
                        ('data',json.dumps(data)), ('uri','/local-lan-provision')]:
        ET.SubElement(command, name).text = value
    return ET.tostring(root), True


async def serve(args):
    config = json.loads(args.lan_config.read_text())
    if not 16 <= len(config['key']) <= 32 or not 1 <= config['key_id'] <= 65535:
        raise ValueError('Invalid LAN configuration')
    downstream = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    downstream.minimum_version = downstream.maximum_version = ssl.TLSVersion.TLSv1_2
    downstream.set_ciphers('DHE-RSA-AES256-SHA:AES128-SHA:AES256-SHA:@SECLEVEL=0')
    downstream.load_dh_params(args.dh_params)
    downstream.load_cert_chain(args.cert, args.key)
    upstream = ssl.create_default_context(cafile=args.upstream_ca)
    injected = False
    async with ClientSession(connector=TCPConnector(ssl=upstream),
            timeout=ClientTimeout(total=45), auto_decompress=False, skip_auto_headers={'Accept-Encoding'}) as client:
        async def handle(request):
            nonlocal injected
            if request.remote != args.allowed_peer:
                raise web.HTTPForbidden()
            print(request.method, request.path, flush=True)
            if request.path.endswith('/local-lan-provision'):
                print('LAN configuration reply status:', request.query.get('status'), flush=True)
                return web.Response()
            if request.path.endswith('/lan.json'):
                return web.json_response({'lanip': {'status': 'enable',
                    'lanip_key_id':config['key_id'], 'lanip_key':config['key'],
                    'keep_alive':30, 'auto_sync':1}})
            # Preserve Host: Ayla routes requests by OEM service authority.
            try:
                headers = forward_request_headers(request.headers)
            except ValueError:
                raise web.HTTPBadRequest() from None
            async with client.request(request.method,
                    'https://proxy-ingress-usfield.aylanetworks.com'+request.path_qs,
                    data=await request.read(), headers=headers) as response:
                body = await response.read()
                output_headers = {k:v for k,v in response.headers.items()
                    if k.lower() in ('content-type','content-encoding','x-ayla-auth-key')}
                print('Upstream HTTP',response.status,flush=True)
                if request.path.endswith('/commands.xml') and response.status == 200 and not injected:
                    body, injected = add_lan_command(body, config)
                    if injected:print('LAN key configuration delivered',flush=True)
                if request.path.startswith('/dsns/') and response.status == 200 and body.lstrip().startswith(b'<'):
                    root = ET.fromstring(body)
                    for name in ('lan-enabled','local-access-enabled'):
                        element = root.find(name)
                        if element is not None:element.text = 'true'
                    body = ET.tostring(root)
                return web.Response(body=body,status=response.status,headers=output_headers)
        app = web.Application(client_max_size=1048576)
        app.router.add_route('*','/{path:.*}',handle)
        runner = web.AppRunner(app,access_log=None)
        await runner.setup()
        try:
            await web.TCPSite(runner,args.bind,args.port,ssl_context=downstream).start()
            print('READY bounded LAN provisioning proxy',flush=True)
            await asyncio.sleep(args.seconds)
        finally:await runner.cleanup()


if __name__ == '__main__':
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lan-config',required=True,type=Path)
    parser.add_argument('--bind',required=True)
    parser.add_argument('--allowed-peer',required=True)
    parser.add_argument('--port',type=int,default=8444)
    parser.add_argument('--seconds',type=int,default=300)
    parser.add_argument('--cert',required=True)
    parser.add_argument('--key',required=True)
    parser.add_argument('--dh-params',required=True)
    parser.add_argument('--upstream-ca')
    args = parser.parse_args()
    if not 1 <= args.seconds <= 600:parser.error('Lifetime must be 1–600 seconds')
    asyncio.run(serve(args))
