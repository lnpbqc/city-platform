import asyncio
import json
from datetime import datetime, timezone
from time import monotonic
from urllib.parse import urlencode
from urllib.request import urlopen

from app.errors import ApiProblem
from app.schemas.weather import WeatherReading

_CACHE_SECONDS = 600
_cache: dict[tuple[float, float], tuple[float, WeatherReading]] = {}
_in_flight: dict[tuple[float, float], asyncio.Task[WeatherReading]] = {}


def _fetch_current(latitude: float, longitude: float) -> WeatherReading:
    query = urlencode({"latitude": latitude, "longitude": longitude, "current": "weather_code,is_day",
                       "timeformat": "unixtime", "cell_selection": "nearest"})
    with urlopen(f"https://api.open-meteo.com/v1/forecast?{query}", timeout=5) as response:
        current = json.loads(response.read(65536))["current"]
    if type(current["time"]) is not int or current["is_day"] not in (0, 1):
        raise ValueError("Invalid current weather")
    return WeatherReading(latitude=latitude, longitude=longitude, code=current["weather_code"],
                          is_day=bool(current["is_day"]), valid_at=datetime.fromtimestamp(current["time"], timezone.utc))


async def _load(key: tuple[float, float]) -> WeatherReading:
    try:
        result = await asyncio.to_thread(_fetch_current, *key)
        _cache[key] = (monotonic() + _CACHE_SECONDS, result)
        return result
    finally:
        _in_flight.pop(key, None)


async def current_weather(latitude: float, longitude: float) -> WeatherReading:
    key = (round(latitude, 2) or 0.0, round(longitude, 2) or 0.0)
    now = monotonic()
    if cached := _cache.get(key):
        if cached[0] > now:
            return cached[1]
    for expired in [cell for cell, (until, _) in _cache.items() if until <= now]:
        del _cache[expired]
    if (task := _in_flight.get(key)) is None:
        task = _in_flight[key] = asyncio.create_task(_load(key))
    try:
        return await asyncio.shield(task)
    except (OSError, ValueError, TypeError, KeyError, OverflowError) as cause:
        raise ApiProblem(503, "WEATHER_UNAVAILABLE", "当前天气暂不可用") from cause
