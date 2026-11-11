import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/'tools/router-capture-window.sh'

class RouterWindowTests(unittest.TestCase):
    def test_partial_install_failure_runs_scoped_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'iptables').write_text('''#!/bin/sh
printf '%s\\n' "$*" >> "$TEST_LOG"
case "$*" in *"-S PREROUTING"*) exit 0;; esac
case "$*" in *"-I PREROUTING"*"-p udp"*) exit 1;; esac
''')
            for name in ('sleep','conntrack'):(root/name).write_text('#!/bin/sh\nexit 0\n')
            for path in root.iterdir():path.chmod(0o700)
            env=dict(os.environ,PATH=directory+':'+os.environ['PATH'],TEST_LOG=str(root/'calls'),
                HEATER='192.0.2.2',HTTPS_UPSTREAM='198.51.100.1',UDP_UPSTREAM='198.51.100.2',
                TARGET='192.0.2.3',GATEWAY='192.0.2.1',RUN_ID='synthetic',WINDOW_SECONDS='20',ENABLE_UDP_FORWARD='1')
            result=subprocess.run(['sh',str(SCRIPT),'start'],env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,1)
            calls=(root/'calls').read_text()
            self.assertEqual(calls.count('-D PREROUTING'),2)
            self.assertEqual(calls.count('-D POSTROUTING'),2)
            self.assertNotIn(' -F',calls)
            self.assertIn('--comment icomm-capture-synthetic',calls)
            self.assertIn('ROLLBACK COMPLETE',result.stdout)

    def test_stale_cleanup_does_not_expire_sessions_after_rules_are_gone(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'iptables').write_text('#!/bin/sh\nexit 1\n')
            (root/'conntrack').write_text('#!/bin/sh\nprintf called > "$TEST_LOG"\n')
            for path in root.iterdir():path.chmod(0o700)
            env=dict(os.environ,PATH=directory+':'+os.environ['PATH'],TEST_LOG=str(root/'calls'),
                HEATER='192.0.2.2',HTTPS_UPSTREAM='198.51.100.1',UDP_UPSTREAM='198.51.100.2',
                TARGET='192.0.2.3',GATEWAY='192.0.2.1',RUN_ID='stale')
            result=subprocess.run(['sh',str(SCRIPT),'cleanup'],env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0)
            self.assertFalse((root/'calls').exists())
