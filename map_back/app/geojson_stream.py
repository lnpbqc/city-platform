"""Bounded-memory FeatureCollection reader; validates the complete JSON stream."""
from pathlib import Path
from collections.abc import Callable
from contextvars import ContextVar
import ijson
from ijson.common import ObjectBuilder


cancellation = ContextVar("geojson_cancellation", default=None)


def check_cancel(cancel: Callable[[], None] | None):
    callback = cancel or cancellation.get()
    if callback:
        callback()


def members(path: Path, cancel=None, *, require_collection=True, allow_crs=False):
    with path.open('rb') as source:
        if source.read(3) != b'\xef\xbb\xbf':
            source.seek(0)
        class Reader:
            def read(self, size):
                return b'' if size == 0 else source.read(size)
        events = iter(ijson.basic_parse(Reader(), use_float=True))
        try:
            if next(events) != ('start_map', None):
                raise ValueError('GeoJSON 必须为 FeatureCollection')
            seen, kind = set(), None
            def value(first):
                builder = ObjectBuilder()
                event, item = first
                builder.event(event, item)
                depth = int(event in ('start_map', 'start_array'))
                while depth:
                    event, item = next(events)
                    builder.event(event, item)
                    depth += int(event in ('start_map', 'start_array')) - int(event in ('end_map', 'end_array'))
                    check_cancel(cancel)
                return builder.value
            while True:
                check_cancel(cancel)
                event, key = next(events)
                if event == 'end_map':
                    break
                if event != 'map_key' or key in seen:
                    raise ValueError('GeoJSON 顶层属性无效或重复')
                seen.add(key)
                first = next(events)
                if key == 'features':
                    if first != ('start_array', None):
                        raise ValueError('GeoJSON features 必须为数组')
                    while True:
                        first = next(events)
                        if first == ('end_array', None):
                            break
                        feature = value(first)
                        if not isinstance(feature, dict) or feature.get('type') != 'Feature':
                            raise ValueError('features 内必须是 Feature')
                        yield None, feature
                else:
                    item = value(first)
                    if key == 'crs' and not allow_crs:
                        raise ValueError('请移除旧式 crs 声明，并先转换为 WGS84 经纬度')
                    if key == 'type':
                        kind = item
                    yield key, item
            if require_collection and (kind != 'FeatureCollection' or 'features' not in seen):
                raise ValueError('GeoJSON 必须为 FeatureCollection')
            try:
                next(events)
                raise ValueError('JSON 尾部存在额外内容')
            except StopIteration:
                pass
        except (ijson.JSONError, UnicodeError, StopIteration, OverflowError) as error:
            raise ValueError(f'{path.name} 不是有效的 UTF-8 JSON') from error


def features(path: Path, cancel=None):
    for key, value in members(path, cancel):
        if key is None:
            yield value
