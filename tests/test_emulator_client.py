import time
import unittest
from aiohttp import web
from aiohttp.test_utils import TestClient,TestServer
from custom_components.icomm_local.emulator_client import EmulatorHeater


class EmulatorClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_freshness_and_offline_state(self):
        state={'active':True,'registered':True,'reading_age_seconds':2,'pending':False,'reading':{
            'target_f':130,'mode':'hybrid','duration_days':0,'top_f':125,'middle_f':124,'bottom_f':123}}
        seen=[]
        async def handler(request):
            seen.append(request.headers.get('Authorization'))
            return web.json_response(state)
        app=web.Application();app.router.add_get('/emulator/status',handler)
        client=TestClient(TestServer(app));await client.start_server()
        updates=[]
        heater=EmulatorHeater(client.session,'127.0.0.1','synthetic-only-token',lambda:updates.append(True),client.port)
        try:
            await heater.refresh();self.assertTrue(heater.available)
            self.assertEqual(heater.state.target_f,130)
            self.assertEqual(seen,['Bearer synthetic-only-token'])
            state['reading_age_seconds']=150
            await heater.refresh();self.assertTrue(heater.available)
            state['reading_age_seconds']=181
            await heater.refresh();self.assertFalse(heater.available)
            state['reading_age_seconds']=1;state['reading']=None
            await heater.refresh();self.assertFalse(heater.available);self.assertIsNone(heater.state)
            state['active']=False
            await heater.refresh();self.assertFalse(heater.available)
            with self.assertRaises(ConnectionError):await heater.set_target(129)
        finally:await client.close()
