import asyncio
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from io import BytesIO
from threading import Event
from urllib.parse import parse_qs, urlsplit
from urllib.error import HTTPError

from app.services import weather


def reading(latitude, longitude):
    return weather.WeatherReading(latitude=latitude, longitude=longitude, code=71,
                                  is_day=True, valid_at=datetime(2026, 1, 1, tzinfo=timezone.utc))


def test_current_weather_rounds_coordinates_and_expires_cache(client, monkeypatch):
    calls = []
    now = 1000
    monkeypatch.setattr(weather, "_cache", {})
    monkeypatch.setattr(weather, "monotonic", lambda: now)
    monkeypatch.setattr(weather, "_fetch_current", lambda lat, lon: (calls.append((lat, lon)), reading(lat, lon))[1])
    assert client.get("/api/weather/current?lat=91&lon=113").status_code == 422
    first = client.get("/api/weather/current?lat=23.031&lon=113.362")
    assert first.status_code == 200
    assert first.json() == {"latitude": 23.03, "longitude": 113.36, "code": 71,
                            "is_day": True, "valid_at": "2026-01-01T00:00:00Z"}
    assert client.get("/api/weather/current?lat=23.034&lon=113.363").json() == first.json()
    assert calls == [(23.03, 113.36)]
    now += 600
    assert client.get("/api/weather/current?lat=23.031&lon=113.362").status_code == 200
    assert len(calls) == 2


def test_same_cell_concurrent_requests_share_upstream(monkeypatch):
    started, release = Event(), Event()
    calls = []

    def fetch(lat, lon):
        calls.append((lat, lon))
        started.set()
        assert release.wait(3)
        return reading(lat, lon)

    monkeypatch.setattr(weather, "_cache", {})
    monkeypatch.setattr(weather, "_fetch_current", fetch)

    async def run():
        first = asyncio.create_task(weather.current_weather(23.031, 113.362))
        assert await asyncio.to_thread(started.wait, 3)
        second = asyncio.create_task(weather.current_weather(23.032, 113.364))
        await asyncio.sleep(0)
        release.set()
        assert await first == await second

    asyncio.run(run())
    assert calls == [(23.03, 113.36)]


def test_weather_failure_is_local_and_can_recover(client, monkeypatch):
    monkeypatch.setattr(weather, "_cache", {})
    now = 10_000
    monkeypatch.setattr(weather, "monotonic", lambda: now)

    def offline(*_):
        raise TimeoutError

    monkeypatch.setattr(weather, "_fetch_current", offline)
    url = "/api/weather/current?lat=23&lon=113"
    failed = client.get(url)
    assert failed.status_code == 503
    assert failed.json()["code"] == "WEATHER_UNAVAILABLE"
    assert failed.headers["retry-after"] == "60"
    assert client.get("/api/health").status_code == 200
    monkeypatch.setattr(weather, "_fetch_current", reading)
    assert client.get(url).status_code == 503
    now += 60
    assert client.get(url).status_code == 200


def test_weather_rate_limit_pauses_other_points_and_reports_trace(client, monkeypatch, caplog):
    monkeypatch.setattr(weather, "_cache", {})
    now = 20_000
    monkeypatch.setattr(weather, "monotonic", lambda: now)
    calls = []

    def fetch(lat, lon):
        calls.append((lat, lon))
        if len(calls) == 1:
            raise HTTPError("https://api.open-meteo.com", 429, "Too Many Requests", {"Retry-After": "121"}, None)
        return reading(lat, lon)

    monkeypatch.setattr(weather, "_fetch_current", fetch)
    first = client.get("/api/weather/current?lat=26&lon=110")
    assert first.status_code == 429
    assert first.json()["code"] == "WEATHER_RATE_LIMITED"
    assert first.headers["retry-after"] == "121"
    assert first.headers["x-trace-id"] in caplog.text
    assert "upstream_status=429" in caplog.text
    now += 120
    second_url = "/api/weather/current?lat=27&lon=110"
    assert client.get(second_url).headers["retry-after"] == "1"
    assert calls == [(26, 110)]
    now += 1
    assert client.get(second_url).status_code == 200


def test_upstream_retry_after_date_and_missing_header():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert weather._retry_after(format_datetime(now + timedelta(seconds=90), usegmt=True), now) == 90
    assert weather._retry_after(None, now) == 600


def test_open_meteo_response_is_normalized_with_the_requested_sample(monkeypatch):
    def upstream(url, timeout):
        parsed = urlsplit(url)
        assert parsed.netloc == "api.open-meteo.com" and parsed.path == "/v1/forecast"
        assert parse_qs(parsed.query) == {
            "latitude": ["23.03"], "longitude": ["113.36"], "current": ["weather_code,is_day"],
            "timeformat": ["unixtime"], "cell_selection": ["nearest"],
        }
        assert timeout == 5
        return BytesIO(b'{"latitude":23.0,"longitude":113.4,"current":{"weather_code":71,"is_day":1,"time":1767225600}}')

    monkeypatch.setattr(weather, "urlopen", upstream)
    assert weather._fetch_current(23.03, 113.36) == reading(23.03, 113.36)
