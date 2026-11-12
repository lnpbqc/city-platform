import json
import os
from pathlib import Path
import signal
import tempfile
import unittest
from unittest.mock import patch

from tile_service import launcher


class LauncherTests(unittest.TestCase):
    def test_configuration_loads_shared_file_and_keeps_explicit_environment(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / 'config.json'
            config.write_text(json.dumps({'token': 'a' * 64, 'url': 'http://127.0.0.1:18744', 'backend': 'http://127.0.0.1:8000'}))
            with patch.dict(os.environ, {'CITY_TILE_CONFIG': str(config)}, clear=True):
                self.assertEqual(launcher.load_configuration(), str(config.resolve()))
                self.assertEqual(os.environ['CITY_TILE_TOKEN'], 'a' * 64)
                self.assertEqual(os.environ['CITY_TILE_PORT'], '18744')
                self.assertEqual(os.environ['CITY_TILE_HOST'], '127.0.0.1')
                self.assertEqual(os.environ['CITY_TILE_BACKEND_ORIGIN'], 'http://127.0.0.1:8000')
                os.environ['CITY_TILE_PORT'] = '19000'
                launcher.load_configuration()
                self.assertEqual(os.environ['CITY_TILE_PORT'], '19000')

    def test_stop_refuses_reused_pid_wrong_command_and_other_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            pidfile = Path(temporary) / 'service.pid.json'
            record = {'pid': 123, 'start': '100', 'executable': '/python', 'config': '/config'}
            pidfile.write_text(json.dumps(record))
            valid = {'start': '100', 'executable': '/python', 'command': ['/python', '-m', 'uvicorn', 'tile_service.service:create_app']}
            with patch.object(launcher.os, 'kill') as kill:
                for change in ({'start': '101'}, {'command': ['/python', 'other-service']}, {'executable': '/other-python'}):
                    with patch.object(launcher, 'process_identity', return_value={**valid, **change}):
                        with self.assertRaises(RuntimeError):
                            launcher.stop(pidfile, '/config')
                with self.assertRaises(RuntimeError):
                    launcher.stop(pidfile, '/different-config')
                kill.assert_not_called()
                self.assertTrue(pidfile.exists())

    def test_stop_sends_only_sigterm_to_verified_service_and_cleans_record(self):
        with tempfile.TemporaryDirectory() as temporary:
            pidfile = Path(temporary) / 'service.pid.json'
            pidfile.write_text(json.dumps({'pid': 123, 'start': '100', 'executable': '/python', 'config': '/config'}))
            identity = {'start': '100', 'executable': '/python', 'command': ['/python', '-m', 'uvicorn', 'tile_service.service:create_app']}
            with patch.object(launcher, 'process_identity', side_effect=[identity, None]), patch.object(launcher.os, 'kill') as kill:
                launcher.stop(pidfile, '/config')
                kill.assert_called_once_with(123, signal.SIGTERM)
                self.assertFalse(pidfile.exists())


if __name__ == '__main__':
    unittest.main()
