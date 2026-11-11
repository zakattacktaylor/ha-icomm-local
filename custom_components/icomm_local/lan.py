"""Standalone local callback server and heater registration client."""
import asyncio
import json
from collections import deque
import time

from aiohttp import ClientSession, ClientTimeout, web

from .protocol import Session, mode_frame, setpoint_frame, telemetry



class LocalHeater:
    def __init__(self, host, callback_host, key, key_id=1, port=8888, maximum=130, on_update=None):
        self.host, self.callback_host = host, callback_host
        self.key_id, self.port, self.maximum = key_id, port, maximum
        self.session = Session(key, key_id)
        self.on_update = on_update or (lambda: None)
        self.state = None
        self.last_update = 0.0
        self.last_contact = 0.0
        self.last_error = None
        self.queue = deque()
        self.events = deque(maxlen=100)
        self.properties = {}
        self._wake = asyncio.Event()
        self._task = None
        self._runner = None
        self._registered = False
        self._command_id = 0
        self._request_lock = asyncio.Lock()
        self._control_lock = asyncio.Lock()
        self._changed = asyncio.Event()

    def event(self, kind, **fields):
        self.events.append({'time': time.time(), 'kind': kind, **fields})

    @property
    def available(self):
        return self.state is not None and time.time() - self.last_update < 120

    async def start(self):
        app = web.Application(client_max_size=65536)
        app.router.add_route('*', '/local_lan/{tail:.*}', self._handle)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        try:
            await web.TCPSite(self._runner, '0.0.0.0', self.port).start()
        except BaseException:
            await self._runner.cleanup()
            raise
        self._task = asyncio.create_task(self._heartbeat())

    async def stop(self):
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        if self._runner:
            await self._runner.cleanup()

    def refresh(self):
        # Never allow an offline heater to accumulate unbounded stale requests.
        if any('cmds' in item for item in self.queue):
            return
        self._command_id += 1
        self.queue.append({'cmds': [{'cmd': {'method': 'GET',
            'resource': 'property.json?name=superBlockDyn1',
            'uri': '/local_lan/property/datapoint.json', 'data': '', 'cmd_id': self._command_id}}]})
        self._wake.set()

    async def set_target(self, target):
        return await self._write(setpoint_frame(target, self.maximum),
            lambda s: abs(s.target_f - target) < .1, 'target', target)

    async def set_mode(self, mode, days=1):
        return await self._write(mode_frame(mode, days),
            lambda s: s.mode == mode and (mode not in ('electric','vacation') or s.duration_days == days), 'mode', mode)

    async def _write(self, frame, confirmed, field, value):
        async with self._control_lock:
            if not self.available:
                raise ConnectionError('No recent local telemetry')
            if len(self.queue) > 4:
                raise ConnectionError('Local command queue is busy')
            item = {'properties': [{'property': {'base_type': 'string', 'name': 'setBlockParameter',
                'value': frame, 'id': str(time.time_ns())}}]}
            self.queue.appendleft(item)
            self._wake.set()
            started = time.time()
            self.event('write_queued', field=field, value=value)
            try:
                async with asyncio.timeout(45):
                    while True:
                        self._changed.clear()
                        if self.last_update > started and confirmed(self.state):
                            self.event('write_confirmed', field=field, value=value)
                            return
                        await self._changed.wait()
            finally:
                # An undelivered command must not take effect long after a timeout.
                try:self.queue.remove(item)
                except ValueError:pass

    async def _heartbeat(self):
        async with ClientSession(timeout=ClientTimeout(total=5)) as client:
            last_refresh = 0.0
            while True:
                try:
                    if time.time() - last_refresh >= 30:
                        self.refresh(); last_refresh = time.time()
                    payload = {'local_reg': {'ip': self.callback_host, 'port': self.port,
                        'uri': '/local_lan', 'notify': int(bool(self.queue))}}
                    self._wake.clear()
                    method = 'PUT' if self._registered else 'POST'
                    async with client.request(method, f'http://{self.host}/local_reg.json', json=payload) as response:
                        if response.status != 202:
                            raise ConnectionError(f'Local registration returned HTTP {response.status}')
                        await response.read()
                    self._registered = True
                    if self.last_error:
                        self.last_error = None; self.on_update()
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    self._registered = False
                    text = f'{type(error).__name__}: {error}'
                    if text != self.last_error:
                        self.last_error = text
                        self.event('registration_failed', error=text)
                        self.on_update()
                try:
                    await asyncio.wait_for(self._wake.wait(), 10 if self.last_error else (2 if self.queue else 10))
                except TimeoutError:
                    pass
                self.on_update()  # Expire stale availability even without new packets.

    async def _handle(self, request):
        if request.remote != self.host:
            raise web.HTTPForbidden()
        async with self._request_lock:
            try:
                path = request.match_info['tail']
                self.last_contact = time.time()
                if path == 'key_exchange.json' and request.method == 'POST':
                    result = self.session.exchange((await request.json())['key_exchange'])
                    self.event('key_exchange')
                    return web.json_response(result)
                if path == 'commands.json' and request.method == 'GET':
                    item = self.queue.popleft() if self.queue else {}
                    if 'properties' in item:
                        # Request fresh readback after the write was delivered.
                        self.refresh()
                    self.event('poll', delivered=next(iter(item), 'empty'))
                    return web.json_response(self.session.encrypt(item))
                if path in ('property/datapoint.json', 'property/datapoint/ack.json') and request.method in ('POST','PUT'):
                    body = await request.read()
                    if body:
                        decoded = self.session.decrypt(json.loads(body))
                        data = decoded.get('data', {})
                        # Normal update or reverse-REST property response.
                        prop = data.get('property', data)
                        if isinstance(prop, dict) and 'name' in prop:
                            name, value = prop['name'], prop.get('value')
                            self.properties[name] = value
                            if name == 'superBlockDyn1' and isinstance(value, str):
                                self.state = telemetry(value)
                                self.last_update = time.time()
                                self.event('telemetry', target=self.state.target_f, mode=self.state.mode)
                                self._changed.set(); self.on_update()
                        self.event('update', name=prop.get('name') if isinstance(prop,dict) else None,
                            status=data.get('ack_status') if isinstance(data,dict) else None)
                    return web.Response()
                raise web.HTTPNotFound()
            except (ValueError, KeyError, TypeError) as error:
                self.event('invalid_message', error=type(error).__name__)
                raise web.HTTPBadRequest() from None
