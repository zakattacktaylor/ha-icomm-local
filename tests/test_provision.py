import importlib.util
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET
spec=importlib.util.spec_from_file_location('provision',Path(__file__).resolve().parents[1]/'tools/provision_proxy.py')
provision=importlib.util.module_from_spec(spec);spec.loader.exec_module(provision)

class ProvisionTests(unittest.TestCase):
    def test_adds_only_lan_key_command_and_preserves_existing_property(self):
        body=b'<commands><properties><property><name>example</name><value>keep</value></property></properties><cmds/><schedules/></commands>'
        result,added=provision.add_lan_command(body,{'key':'synthetic-key-123456','key_id':1})
        root=ET.fromstring(result)
        self.assertTrue(added)
        self.assertEqual(root.findtext('properties/property/value'),'keep')
        self.assertEqual(root.findtext('cmds/cmd/resource'),'lanip.json')
        self.assertEqual(root.findtext('cmds/cmd/method'),'PUT')
        self.assertIsNone(root.find('properties/property[name="setBlockParameter"]'))

    def test_does_not_displace_existing_reverse_rest_command(self):
        original=b'<commands><properties/><cmds><cmd><id>1</id></cmd></cmds></commands>'
        result,added=provision.add_lan_command(original,{'key':'synthetic-key-123456','key_id':1})
        self.assertFalse(added);self.assertEqual(result,original)

    def test_preserves_oem_authority_and_disables_automatic_compression(self):
        headers=provision.forward_request_headers({'host':'example-device.aylanetworks.com',
            'X-Ayla-Auth-Key':'synthetic-token','Transfer-Encoding':'chunked','Content-Length':'10',
            'Accept-Encoding':'gzip'})
        self.assertEqual(headers['host'],'example-device.aylanetworks.com')
        self.assertEqual(headers['X-Ayla-Auth-Key'],'synthetic-token')
        self.assertEqual(headers['Accept-Encoding'],'identity')
        self.assertNotIn('Transfer-Encoding',headers)
        self.assertNotIn('Content-Length',headers)
        with self.assertRaises(ValueError):provision.forward_request_headers({'Host':'example.invalid'})
