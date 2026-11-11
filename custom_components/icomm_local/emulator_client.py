"""Authenticated local add-on client. No vendor APIs or NUC dependency."""
import asyncio
import time
import aiohttp
from .protocol import Telemetry


class EmulatorHeater:
    def __init__(self, session, host, token, on_update, port=8787):
        self.session,self.base,self.token=session,f'http://{host}:{port}',token
        self.on_update=on_update;self.state=None;self.last_update=0;self.last_error=None
        self.active=False;self.task=None;self.control_lock=asyncio.Lock()

    @property
    def available(self):
        return self.active and self.state is not None and time.time()-self.last_update<120

    async def request(self, path, data=None):
        try:
            async with asyncio.timeout(8):
                async with self.session.request('GET' if data is None else 'POST',self.base+path,
                    json=data,headers={'Authorization':'Bearer '+self.token}) as response:
                    if response.status!=200:raise ConnectionError(f'Local emulator returned HTTP {response.status}')
                    return await response.json()
        except aiohttp.ClientError as error:
            raise ConnectionError('Local emulator connection failed') from error

    async def refresh(self):
        status=await self.request('/emulator/status')
        self.active=status['active']
        if status.get('reading') is not None:
            self.state=Telemetry(**status['reading'])
            self.last_update=time.time()-status['reading_age_seconds']
        self.last_error=None
        self.on_update()
        return status

    async def start(self):
        async def poll():
            while True:
                try:await self.refresh()
                except (ConnectionError,TimeoutError,OSError,ValueError,KeyError) as error:
                    self.active=False;self.last_error=str(error);self.on_update()
                await asyncio.sleep(5)
        self.task=asyncio.create_task(poll())

    async def stop(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task,return_exceptions=True)
            self.task=None

    async def set_target(self, value):await self.control('target',value)
    async def set_mode(self, value):await self.control('mode',value)

    async def control(self,kind,value):
        async with self.control_lock:
            if not self.available:raise ConnectionError('Fresh local telemetry is required')
            started=time.time()
            await self.request('/emulator/control',{'kind':kind,'value':value})
            deadline=time.monotonic()+35
            while time.monotonic()<deadline:
                await asyncio.sleep(1)
                status=await self.refresh()
                actual=self.state.target_f if kind=='target' else self.state.mode
                matches=actual==value or isinstance(actual,(float,int)) and isinstance(value,(float,int)) and abs(actual-value)<.02
                if self.last_update>started and matches and not status['pending']:return
            raise TimeoutError('No fresh telemetry confirmed the command; check the physical controller')
