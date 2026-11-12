"""Parse the actual Windows entry point with Windows PowerShell's file decoder."""
import os
from pathlib import Path
import shutil
import subprocess
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'start.ps1'


class PowerShellTests(unittest.TestCase):
    def assert_parses(self, executable):
        command = (
            "$tokens=$null; $errors=$null; "
            "[System.Management.Automation.Language.Parser]::ParseFile("
            "$env:CITY_TILE_SCRIPT_TEST,[ref]$tokens,[ref]$errors) | Out-Null; "
            "if ($errors.Count) { $errors | ForEach-Object { "
            "Write-Output ($_.ErrorId + ':' + $_.Extent.StartLineNumber) }; exit 1 }"
        )
        result = subprocess.run([executable, '-NoProfile', '-NonInteractive', '-Command', command],
                                env={**os.environ, 'CITY_TILE_SCRIPT_TEST': str(SCRIPT)},
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(os.name == 'nt', 'Windows entry point')
    def test_windows_powershell_51_parses_real_script(self):
        executable = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        self.assert_parses(str(executable))

    @unittest.skipUnless(shutil.which('pwsh'), 'PowerShell 7 is not installed')
    def test_powershell_7_parses_real_script(self):
        self.assert_parses(shutil.which('pwsh'))


if __name__ == '__main__':
    unittest.main()
