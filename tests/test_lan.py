import asyncio
import json
import sys
import time
import unittest
from pathlib import Path
from aiohttp import ClientSession
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from custom_components.icomm_local.lan import LocalHeater
from custom_components.icomm_local.protocol import Direction,telemetry


def sample(target=130):
    blocks=[bytearray(n) for n in (8,148,230,52,52)]
    value=round((target-32)/1.8*256).to_bytes(2,'big')
    blocks[3][:2]=blocks[3][12:14]=value;blocks[3][31]=4
    return ','.join(b.hex() for b in blocks)


class LocalCallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_authenticated_write_readback_and_invalid_signature(self):
        heater=LocalHeater('127.0.0.1','127.0.0.1','synthetic-test-key',port=0)
        await heater.start()
        heater._task.cancel();await asyncio.gather(heater._task,return_exceptions=True)
        heater.queue.clear();heater._registered=True;heater.last_error=None
        port=next(iter(heater._runner.sites))._server.sockets[0].getsockname()[1]
        base=f'http://127.0.0.1:{port}/local_lan/'
        try:
            async with ClientSession() as client:
                async with client.post(base+'key_exchange.json',json={'key_exchange':{
                    'key_id':1,'ver':1,'proto':1,'random_1':'simulator','time_1':123}}) as response:
                    self.assertEqual(response.status,200);reply=await response.json()
                incoming=Direction(b'synthetic-test-key',f"simulator{reply['random_2']}123{reply['time_2']}".encode())
                outgoing=Direction(b'synthetic-test-key',f"{reply['random_2']}simulator{reply['time_2']}123".encode())
                self.assertFalse(heater.available)
                initial=outgoing.encrypt({'seq_no':0,'data':{'name':'superBlockDyn1','value':sample(130)}})
                async with client.post(base+'property/datapoint.json',json=initial) as response:self.assertEqual(response.status,200)
                self.assertTrue(heater.available)
                action=asyncio.create_task(heater.set_target(129));await asyncio.sleep(0)
                async with client.get(base+'commands.json') as response:
                    data=incoming.decrypt(await response.json())
                self.assertEqual(data['data']['properties'][0]['property']['value'],'BD 40 08 0B 06 35 E4 38')
                envelope=outgoing.encrypt({'seq_no':1,'data':{'name':'superBlockDyn1','value':sample(129)}})
                bad=dict(envelope,sign='AAAA')
                async with client.post(base+'property/datapoint.json',json=bad) as response:self.assertEqual(response.status,400)
                self.assertFalse(action.done())
                async with client.post(base+'property/datapoint.json',json=envelope) as response:self.assertEqual(response.status,200)
                await asyncio.wait_for(action,1)
                self.assertEqual(heater.state.target_f,129.0)
                self.assertTrue(any(e['kind']=='write_confirmed' for e in heater.events))
        finally:await heater.stop()

    async def test_lost_registration_blocks_control_even_with_cached_reading(self):
        heater=LocalHeater('127.0.0.1','127.0.0.1','synthetic-test-key')
        heater.state=telemetry(sample());heater.last_update=time.time()
        heater._registered=True;self.assertTrue(heater.available)
        heater.last_error='Local registration returned HTTP 404';heater._registered=False
        self.assertFalse(heater.available)
        with self.assertRaises(ConnectionError):await heater.set_target(129)
        self.assertEqual(len(heater.queue),0)
