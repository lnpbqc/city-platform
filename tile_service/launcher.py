"""Load server-only configuration and manage this launcher's exact Linux process."""
import json
import os
from pathlib import Path
import signal
import sys
import time
from urllib.parse import urlsplit


def load_configuration():
    config_path = os.environ.get('CITY_TILE_CONFIG')
    if config_path:
        config = json.loads(Path(config_path).read_text(encoding='utf-8-sig'))
        target = urlsplit(config['url'])
        if target.scheme != 'http' or not target.hostname or target.username or target.password:
            raise ValueError('Invalid tile service URL')
        os.environ.setdefault('CITY_TILE_TOKEN', config['token'])
        os.environ.setdefault('CITY_TILE_BACKEND_ORIGIN', config['backend'])
        os.environ.setdefault('CITY_TILE_PORT', str(target.port or 80))
        os.environ.setdefault('CITY_TILE_HOST', target.hostname)
    if len(os.environ.get('CITY_TILE_TOKEN', '')) < 24:
        raise ValueError('Tile service token must contain at least 24 characters')
    return str(Path(config_path).resolve()) if config_path else None


def process_identity(pid):
    try:
        # comm can contain spaces and parentheses; the fields after its final ')' are fixed.
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        command = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
        return {'start': fields[19], 'executable': str(Path(f'/proc/{pid}/exe').resolve()),
                'command': [part.decode() for part in command if part]}
    except (FileNotFoundError, ProcessLookupError):
        return None


def stop(pidfile, config):
    if not pidfile.exists():
        print('No managed tile service PID file')
        return
    record = json.loads(pidfile.read_text())
    if record['config'] != config:
        raise RuntimeError('PID file belongs to another configuration')
    identity = process_identity(record['pid'])
    if identity is not None:
        if (identity['start'] != record['start'] or identity['executable'] != record['executable']
                or 'tile_service.service:create_app' not in identity['command']
                or 'uvicorn' not in identity['command']):
            raise RuntimeError('PID identity changed; refusing to stop another process')
        os.kill(record['pid'], signal.SIGTERM)
        for _ in range(450):
            current = process_identity(record['pid'])
            if current is None or current['start'] != record['start']:
                break
            time.sleep(.1)
        else:
            raise RuntimeError('Tile service has not stopped gracefully; PID file retained')
    pidfile.unlink(missing_ok=True)
    print('Managed tile service stopped')


def main():
    config = load_configuration()
    data = Path(os.environ.get('CITY_TILE_DATA', str(Path.home() / '.local/share/city-tile')))
    pidfile = data / 'service.pid.json'
    if sys.argv[1:] == ['--stop']:
        stop(pidfile, config)
        return
    if sys.argv[1:]:
        raise ValueError('Only --stop is supported')
    import fcntl
    data.mkdir(parents=True, exist_ok=True)
    lock = (data / 'service.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError('A managed tile service is already running') from None
    os.set_inheritable(lock.fileno(), True)
    identity = process_identity(os.getpid())
    pidfile.write_text(json.dumps({'pid': os.getpid(), 'start': identity['start'],
        'executable': identity['executable'], 'config': config}))
    os.execv(sys.executable, [sys.executable, '-m', 'uvicorn', 'tile_service.service:create_app',
        '--factory', '--host', os.environ.get('CITY_TILE_HOST', '127.0.0.1'),
        '--port', os.environ.get('CITY_TILE_PORT', '18744'), '--workers', '1'])


if __name__ == '__main__':
    main()
