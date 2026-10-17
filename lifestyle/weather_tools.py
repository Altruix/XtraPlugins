# Copyright (C) 2021-present by Altruix@Github, < https://github.com/Altruix >.
#
# This file is part of < https://github.com/Altruix/Altruix > project,
# and is released under the "GNU v3.0 License Agreement".
# Please see < https://github.com/Altriux/Altruix/blob/main/LICENSE >
#
# All rights reserved.

import urllib.parse
from Main import Altruix
from Main.core.types.client import AltruixTelegramClient as Client
from Main.core.types.message import Message

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

WEATHER_ICONS = {
    "sunny": "☀️",
    "clear": "🌙",
    "partly cloudy": "⛅",
    "cloudy": "☁️",
    "overcast": "🌥",
    "mist": "🌫",
    "fog": "🌁",
    "patchy rain possible": "🌦",
    "light rain": "🌧",
    "heavy rain": "⛈",
    "thundery outbreaks possible": "🌩",
    "snow": "❄️",
    "sleet": "🌨",
}


def _get_icon(desc: str) -> str:
    desc_l = desc.lower()
    for k, v in WEATHER_ICONS.items():
        if k in desc_l:
            return v
    return "🌤"


@Altruix.register_on_cmd(
    ["weather", "wttr"],
    cmd_help={
        "help": "Get current weather conditions and forecast for any city or location.",
        "example": "weather Tokyo",
    },
    requires_input=True,
)
async def weather_report(c: Client, m: Message):
    if not HAS_HTTPX:
        return await m.handle_message("❌ <code>httpx</code> is required for weather lookup.")

    query = m.user_input.strip()
    msg = await m.handle_message(f"🌤 Fetching weather for <b>{query}</b>...")

    encoded_city = urllib.parse.quote_plus(query)
    url = f"https://wttr.in/{encoded_city}?format=j1"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.get(url, headers={"User-Agent": "AltruixUserbot/1.0"})

        if res.status_code != 200:
            return await msg.edit_msg(f"❌ Failed to fetch weather for <code>{query}</code> (HTTP {res.status_code}).")

        data = res.json()
        current = data.get("current_condition", [{}])[0]
        nearest_area = data.get("nearest_area", [{}])[0]

        city_name = nearest_area.get("areaName", [{}])[0].get("value", query.title())
        region = nearest_area.get("region", [{}])[0].get("value", "")
        country = nearest_area.get("country", [{}])[0].get("value", "")

        temp_c = current.get("temp_C", "N/A")
        temp_f = current.get("temp_F", "N/A")
        feels_c = current.get("FeelsLikeC", "N/A")
        feels_f = current.get("FeelsLikeF", "N/A")
        desc = current.get("weatherDesc", [{}])[0].get("value", "Clear")
        humidity = current.get("humidity", "N/A")
        wind_kmph = current.get("windspeedKmph", "N/A")
        wind_dir = current.get("winddir16Point", "")
        uv = current.get("uvIndex", "N/A")
        visibility = current.get("visibility", "N/A")

        icon = _get_icon(desc)

        location_display = f"{city_name}"
        if region and region != city_name:
            location_display += f", {region}"
        if country:
            location_display += f", {country}"

        # Forecast summary for next 2 days
        weather_days = data.get("weather", [])
        forecast_lines = []
        for day in weather_days[:2]:
            date_str = day.get("date", "")
            max_c = day.get("maxtempC", "")
            min_c = day.get("mintempC", "")
            day_desc = day.get("hourly", [{}])[4].get("weatherDesc", [{}])[0].get("value", "")
            day_icon = _get_icon(day_desc)
            forecast_lines.append(f"• <b>{date_str}:</b> {day_icon} {min_c}°C – {max_c}°C ({day_desc})")

        forecast_block = ("\n\n<b>📅 Forecast:</b>\n" + "\n".join(forecast_lines)) if forecast_lines else ""

        report = (
            f"<b>{icon} Weather in {location_display}</b>\n\n"
            f"<b>• Condition:</b> {desc}\n"
            f"<b>• Temperature:</b> {temp_c}°C ({temp_f}°F)\n"
            f"<b>• Feels Like:</b> {feels_c}°C ({feels_f}°F)\n"
            f"<b>• Humidity:</b> {humidity}%\n"
            f"<b>• Wind:</b> {wind_kmph} km/h {wind_dir}\n"
            f"<b>• UV Index:</b> {uv}\n"
            f"<b>• Visibility:</b> {visibility} km"
            f"{forecast_block}"
        )
        await msg.edit_msg(report)
    except Exception as e:
        await msg.edit_msg(f"❌ Weather lookup error: <code>{e}</code>")
