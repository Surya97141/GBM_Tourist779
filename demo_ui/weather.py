"""Current-weather lookup for a destination, by its stored coordinates -
never GPS, never browser location, nothing about where this demo happens
to be running physically. Display-only: nothing in here feeds into
ranking, scoring, or any decision logic anywhere in the pipeline.
"""

import os
import time

import requests

OPENWEATHER_ENDPOINT = "https://api.openweathermap.org/data/2.5/weather"
REQUEST_TIMEOUT_SECONDS = 5
CACHE_TTL_SECONDS = 300  # a few minutes - enough to survive re-selecting the same destination during one demo without re-hitting the free tier

# destination coordinates don't change during a run, so keying by (lat, lng)
# is exactly as unique as keying by destination_id would be here - this
# process-local cache never persists between runs
_cache = {}


def get_weather(lat: float, lng: float) -> dict:
    cache_key = (round(lat, 4), round(lng, 4))
    cached = _cache.get(cache_key)
    if cached is not None:
        fetched_at, result = cached
        if time.time() - fetched_at < CACHE_TTL_SECONDS:
            return result

    result = _fetch_weather(lat, lng)
    _cache[cache_key] = (time.time(), result)
    return result


def _fetch_weather(lat: float, lng: float) -> dict:
    api_key = os.environ.get("OPENWEATHER_API_KEY")
    if not api_key:
        return {"available": False, "reason": "OPENWEATHER_API_KEY not set"}

    try:
        response = requests.get(
            OPENWEATHER_ENDPOINT,
            params={"lat": lat, "lon": lng, "appid": api_key, "units": "metric"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.exceptions.RequestException as e:
        return {"available": False, "reason": str(e)}

    if response.status_code != 200:
        return {"available": False, "reason": f"OpenWeatherMap returned status {response.status_code}"}

    try:
        data = response.json()
        return {
            "available": True,
            "temperature": data["main"]["temp"],
            "description": data["weather"][0]["description"],
            "humidity": data["main"]["humidity"],
        }
    except (ValueError, KeyError, IndexError):
        return {"available": False, "reason": "unexpected response shape from OpenWeatherMap"}
