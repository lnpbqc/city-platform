from typing import Annotated

from fastapi import APIRouter, Query

from app.schemas.weather import WeatherReading
from app.services.weather import current_weather

router = APIRouter()


@router.get("/api/weather/current", response_model=WeatherReading)
async def weather_now(lat: Annotated[float, Query(ge=-90, le=90)],
                      lon: Annotated[float, Query(ge=-180, le=180)]):
    return await current_weather(lat, lon)
