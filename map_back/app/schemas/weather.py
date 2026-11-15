from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class WeatherReading(BaseModel):
    model_config = ConfigDict(extra="forbid")
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    code: int = Field(ge=0, le=99)
    is_day: bool
    valid_at: AwareDatetime


class AutomaticWeather(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["open-meteo"]
    effect: Literal["none", "clear", "rain", "snow"]
    reading: WeatherReading


class ManualWeather(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["manual"]
    effect: Literal["clear", "rain", "snow"]


class NoWeather(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["none"]
    effect: Literal["none"]


WeatherSnapshot = Annotated[AutomaticWeather | ManualWeather | NoWeather, Field(discriminator="source")]
