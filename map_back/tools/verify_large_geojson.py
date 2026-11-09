"""Exercise real TCP upload, streaming import, bounded map reads and restart."""
import argparse
import ctypes
import json
import math
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter, sleep

import httpx

ROOT = Path(__file__).resolve().parents[2]


def memory_bytes(pid):
    if os.name != 'nt':
        return int(Path(f'/proc/{pid}/status').read_text().split('VmRSS:')[1].split()[0]) * 1024
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('faults', wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in ('peak', 'working', 'pool_peak', 'pool', 'nonpage_peak', 'nonpage', 'page', 'page_peak')]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x410, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        psapi = ctypes.WinDLL('psapi')
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return counters.peak
    finally:
        kernel.CloseHandle(handle)


def stop(process):
    # Windows venv python.exe is a redirector: terminate the actual interpreter,
    # otherwise its child keeps the HTTP socket and SQLite files open.
    if os.name == 'nt' and getattr(process, 'actual_pid', process.pid) != process.pid:
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(1, False, process.actual_pid)
        if handle:
            kernel.TerminateProcess(handle, 0)
            kernel.CloseHandle(handle)
    elif process.poll() is None:
        process.terminate()
    process.wait(timeout=30)


def generate(path, size):
    count = 0
    kinds = {'Point': 0, 'LineString': 0, 'Polygon': 0}
    with path.open('wb') as stream:
        stream.write(b'{"type":"FeatureCollection","features":[')
        while True:
            x, y = 113 + (count % 200) / 10000, 23 + (count // 200 % 200) / 10000
            positions = [[round(x + .0001 * math.cos(i * 2 * math.pi / 256), 8),
                          round(y + .0001 * math.sin(i * 2 * math.pi / 256), 8)] for i in range(256)]
            kind = ('Point', 'LineString', 'Polygon')[count % 3]
            coordinates = [x, y] if kind == 'Point' else positions if kind == 'LineString' else [positions + [positions[0]]]
            feature = {'type': 'Feature', 'properties': {'name': f'混合几何-{count}', 'source': 'large-file-verification',
                        'category': kind, 'importance': count % 10}, 'geometry': {'type': kind, 'coordinates': coordinates}}
            encoded = (b',' if count else b'') + json.dumps(feature, ensure_ascii=False, separators=(',', ':')).encode()
            if stream.tell() + len(encoded) + 2 > size:
                break
            stream.write(encoded)
            kinds[kind] += 1
            count += 1
        stream.write(b']}')
        stream.write(b' ' * (size - stream.tell()))
    assert path.stat().st_size == size
    return count, kinds


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mib', type=int, default=1024)
    args = parser.parse_args()
    verification = ROOT / '.verification'
    verification.mkdir(exist_ok=True)
    report = {'size_bytes': args.mib * 1024 * 1024}
    with tempfile.TemporaryDirectory(prefix='large-geojson-', dir=verification) as temporary:
        folder = Path(temporary)
        source = folder / 'mixed.geojson'
        print('Generating mixed geometries...', flush=True)
        report['features'], report['geometry_counts'] = generate(source, report['size_bytes'])
        environment = {**os.environ, 'MAP_STORAGE_DIR': str(folder / 'storage'),
                       'MAP_DATABASE_URL': 'sqlite:///' + (folder / 'storage/catalog.db').as_posix(), 'PYTHONIOENCODING': 'utf-8'}
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], cwd=ROOT / 'map_back', env=environment,
                       check=True, capture_output=True, creationflags=flags)
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
        address = f'http://127.0.0.1:{port}'
        log = (folder / 'server.log').open('w', encoding='utf-8')
        pid_file = folder / 'server.pid'
        server = None
        def start():
            pid_file.unlink(missing_ok=True)
            script = 'import os;from pathlib import Path;import uvicorn;Path(os.environ["VERIFICATION_PID"]).write_text(str(os.getpid()));uvicorn.run("app.main:app",host="127.0.0.1",port=int(os.environ["VERIFICATION_PORT"]),log_level="warning",access_log=False)'
            process = subprocess.Popen([sys.executable, '-c', script], cwd=ROOT / 'map_back',
                                       env={**environment, 'VERIFICATION_PID': str(pid_file), 'VERIFICATION_PORT': str(port)},
                                       stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
            deadline = perf_counter() + 300
            while perf_counter() < deadline:
                try:
                    if httpx.get(address + '/api/health', timeout=1, trust_env=False).status_code == 200:
                        process.actual_pid = int(pid_file.read_text())
                        return process
                except httpx.TransportError:
                    pass
                if process.poll() is not None:
                    raise RuntimeError((folder / 'server.log').read_text(encoding='utf-8'))
                sleep(.1)
            if pid_file.exists():
                process.actual_pid = int(pid_file.read_text())
            stop(process)
            raise RuntimeError('Benchmark server startup timed out')
        try:
            server = start()
            with httpx.Client(base_url=address, timeout=3600, trust_env=False) as client:
                tiny = {'type': 'FeatureCollection', 'features': [{'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [113, 23]}, 'properties': {'name': 'existing-poi'}}]}
                result = client.post('/api/layers/upload', data={'name': '已有POI', 'type': 'geojson', 'category': 'POI'}, files={'file': ('poi.geojson', json.dumps(tiny))})
                assert result.status_code == 201, result.text
                old = result.json()
                old_view = {'layer_id': old['id'], 'asset_id': old['asset_id'], 'version': old['asset_version'], 'bbox': [112.9, 22.9, 113.1, 23.1], 'width': 800, 'height': 600, 'meters_per_pixel': .5}
                def upload():
                    with source.open('rb') as stream:
                        return client.post('/api/layers/upload', data={'name': 'GiB混合几何', 'type': 'geojson', 'category': '大文件验证'}, files={'file': ('mixed.geojson', stream, 'application/geo+json')})
                print(f'Uploading {report["features"]} features / {args.mib} MiB...', flush=True)
                started = perf_counter()
                peak = memory_bytes(server.actual_pid)
                latencies = []
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(upload)
                    with httpx.Client(base_url=address, timeout=30, trust_env=False) as reader:
                        while not future.done():
                            peak = max(peak, memory_bytes(server.actual_pid))
                            tick = perf_counter()
                            response = reader.post('/api/map/viewport', json=old_view)
                            assert response.status_code == 200 and response.json()['features'], response.text
                            latencies.append(perf_counter() - tick)
                            sleep(.5)
                    response = future.result()
                report['upload_import_seconds'] = perf_counter() - started
                report['server_peak_rss_bytes'] = max(peak, memory_bytes(server.actual_pid))
                report['concurrent_read_count'] = len(latencies)
                report['concurrent_read_max_seconds'] = max(latencies, default=0)
                assert response.status_code == 201, response.text
                layer = response.json()
                view = {**old_view, 'layer_id': layer['id'], 'asset_id': layer['asset_id'], 'version': layer['asset_version']}
                for label, bbox in [('regional', [113, 23, 113.001, 23.001]), ('whole', [-180, -90, 180, 90])]:
                    tick = perf_counter()
                    response = client.post('/api/map/viewport', json={**view, 'bbox': bbox})
                    assert response.status_code == 200, response.text
                    data = response.json()
                    assert len(data['features']) <= 2000 and len(response.content) <= 10 * 1024 * 1024
                    report[label] = {'seconds': perf_counter() - tick, 'features': len(data['features']), 'bytes': len(response.content), 'truncated': data['truncated']}
                identity = data['features'][0]['id']
                assert client.get('/api/map/objects/' + identity).status_code == 200
                report['database_bytes'] = sum(path.stat().st_size for path in (folder / 'storage').glob('catalog.db*'))
                (verification / f'large-geojson-{args.mib}MiB.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
                print(json.dumps(report, ensure_ascii=False), flush=True)
                stop(server)
                restarted = perf_counter()
                server = start()
                assert client.post('/api/map/viewport', json=view).status_code == 200
                report['restart_verified'] = True
                report['restart_seconds'] = perf_counter() - restarted
        finally:
            if server and server.poll() is None:
                stop(server)
            log.close()
    (verification / f'large-geojson-{args.mib}MiB.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
