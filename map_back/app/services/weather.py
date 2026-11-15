import asyncio
import json
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from math import ceil
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from app.errors import ApiProblem, logger
from app.schemas.weather import WeatherReading

_CACHE_SECONDS = 600
_FAILURE_SECONDS = 60
_cache: dict[tuple[float, float], tuple[float, WeatherReading]] = {}
_in_flight: dict[tuple[float, float], asyncio.Task[WeatherReading]] = {}
_retry_until: dict[tuple[float, float], float] = {}
_rate_limit_until = 0.0


def _fetch_current(latitude: float, longitude: float) -> WeatherReading:
    query = urlencode({"latitude": latitude, "longitude": longitude, "current": "weather_code,is_day",
                       "timeformat": "unixtime", "cell_selection": "nearest"})
    with urlopen(f"https://api.open-meteo.com/v1/forecast?{query}", timeout=5) as response:
        current = json.loads(response.read(65536))["current"]
    if type(current["time"]) is not int or current["is_day"] not in (0, 1):
        raise ValueError("Invalid current weather")
    return WeatherReading(latitude=latitude, longitude=longitude, code=current["weather_code"],
                          is_day=bool(current["is_day"]), valid_at=datetime.fromtimestamp(current["time"], timezone.utc))


def _retry_after(header: str | None, now: datetime) -> int:
    if header is not None:
        try:
            if header.isascii() and header.isdecimal():
                return int(header)
            return max(0, ceil((parsedate_to_datetime(header) - now).total_seconds()))
        except (ValueError, TypeError, OverflowError):
            pass
    return _CACHE_SECONDS


def _weather_error(seconds: int, limited: bool = False) -> ApiProblem:
    if limited:
        error = ApiProblem(429, "WEATHER_RATE_LIMITED", "天气服务限流")
    else:
        error = ApiProblem(503, "WEATHER_UNAVAILABLE", "当前天气暂不可用")
    error.headers = {"Retry-After": str(seconds)}
    return error


async def _load(key: tuple[float, float], trace_id: str) -> WeatherReading:
    global _rate_limit_until
    try:
        result = await asyncio.to_thread(_fetch_current, *key)
        _cache[key] = (monotonic() + _CACHE_SECONDS, result)
        return result
    except (OSError, ValueError, TypeError, KeyError, OverflowError) as cause:
        upstream_status = cause.code if isinstance(cause, HTTPError) else None
        reason = cause.reason if isinstance(cause, URLError) else cause
        logger.warning("trace_id=%s weather_upstream_failure upstream_status=%s reason=%s detail=%s",
                       trace_id, upstream_status, type(cause).__name__, type(reason).__name__)
        now = monotonic()
        if isinstance(cause, HTTPError) and cause.code == 429:
            retry = _retry_after(cause.headers.get("Retry-After") if cause.headers else None,
                                 datetime.now(timezone.utc))
            _rate_limit_until = max(_rate_limit_until, now + retry)
            raise _weather_error(ceil(_rate_limit_until - now), limited=True) from cause
        _retry_until[key] = now + _FAILURE_SECONDS
        raise _weather_error(_FAILURE_SECONDS) from cause
    finally:
        _in_flight.pop(key, None)


async def current_weather(latitude: float, longitude: float, trace_id: str = "-") -> WeatherReading:
    key = (round(latitude, 2) or 0.0, round(longitude, 2) or 0.0)
    now = monotonic()
    if cached := _cache.get(key):
        if cached[0] > now:
            return cached[1]
    for expired in [cell for cell, (until, _) in _cache.items() if until <= now]:
        del _cache[expired]
    if _rate_limit_until > now:
        raise _weather_error(ceil(_rate_limit_until - now), limited=True)
    for expired in [cell for cell, until in _retry_until.items() if until <= now]:
        del _retry_until[expired]
    if key in _retry_until:
        raise _weather_error(ceil(_retry_until[key] - now))
    if (task := _in_flight.get(key)) is None:
        task = _in_flight[key] = asyncio.create_task(_load(key, trace_id))
    return await asyncio.shield(task)
