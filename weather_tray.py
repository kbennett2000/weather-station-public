#!/usr/bin/env python3

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('AppIndicator3', '0.1')
from gi.repository import Gtk, AppIndicator3, GLib
import requests
import threading
import time
from datetime import datetime
import math
import pytz
from astral import LocationInfo
from astral.sun import sun
from astral import moon

class WeatherTray:
    def __init__(self):
        self.indicator = AppIndicator3.Indicator.new(
            "home-weather",
            "",
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS
        )
        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        self.indicator.set_label("🌡️ -- °F", "home-weather-label")

        self.menu = Gtk.Menu()
        self.details_item = Gtk.MenuItem(label="Loading sensor data...")
        self.menu.append(self.details_item)

        separator = Gtk.SeparatorMenuItem()
        self.menu.append(separator)

        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", lambda x: Gtk.main_quit())
        self.menu.append(quit_item)

        self.menu.show_all()
        self.indicator.set_menu(self.menu)

        self.url = "http://192.168.1.60/data"
        self.data = {}

        GLib.timeout_add_seconds(30, self.update)
        self.update()

    def fetch_data(self):
        try:
            r = requests.get(self.url, timeout=8)
            r.raise_for_status()
            self.data = r.json()
            return True
        except:
            self.data = {}
            return False

    def update(self):
        threading.Thread(target=self._fetch_and_update, daemon=True).start()
        return True

    def _fetch_and_update(self):
        success = self.fetch_data()
        GLib.idle_add(self._update_ui, success)

    def _update_ui(self, success):
        if not success or not self.data:
            self.indicator.set_label("🌡️ -- °F", "home-weather-label")
            self.details_item.set_label("❌ Sensor offline")
            return False

        tf = self.data.get("temperatureF", 0)
        tc = self.data.get("temperatureC", 0)
        humidity = self.data.get("humidity", 0)

        self.indicator.set_label(f"🌡️ {tf:.1f}°F", "home-weather-label")

        # Altitude
        altitude_m = self.data.get("altitude", 0)
        altitude_ft = altitude_m * 3.28084

        # Absolute Humidity (g/m³)
        abs_humidity = self.calculate_absolute_humidity(tc, humidity)

        # Sun / Moon
        lat = self.data.get("latitude", 39.433235)
        lon = self.data.get("longitude", -104.518867)
        tz = pytz.timezone("America/Denver")
        now = datetime.now(tz)

        loc = LocationInfo("Home", "US", "America/Denver", lat, lon)
        sun_data = sun(loc.observer, date=now.date(), tzinfo=tz)

        sunrise = sun_data["sunrise"].strftime("%I:%M %p")
        sunset = sun_data["sunset"].strftime("%I:%M %p")
        dawn = sun_data["dawn"].strftime("%I:%M %p")
        dusk = sun_data["dusk"].strftime("%I:%M %p")
        solar_noon = sun_data["noon"].strftime("%I:%M %p")

        # Moon
        moon_phase_val = moon.phase(now)
        illumination = (1 - math.cos(moon_phase_val * 2 * math.pi)) / 2 * 100

        details = (
            f"🌡️ {tf:.1f}°F / {tc:.1f}°C\n"
            f"Humidity: {humidity:.1f}%\n"
            f"Absolute Humidity: {abs_humidity:.1f} g/m³\n"
            f"Pressure: {self.data.get('pressure')} hPa\n"
            f"Light: {self.data.get('lux'):.2f} lux\n"
            f"WiFi: {self.data.get('rssi')} dBm\n"
            f"Altitude: {altitude_m:.1f} m / {altitude_ft:.1f} ft\n"
            f"GPS: {lat:.5f}, {lon:.5f}\n\n"
            f"🌅 Sunrise: {sunrise}\n"
            f"🌄 Dawn: {dawn}\n"
            f"☀️ Solar Noon: {solar_noon}\n"
            f"🌇 Sunset: {sunset}\n"
            f"🌆 Dusk: {dusk}\n\n"
            f"🌕 Moon Phase: {moon_phase_val:.2f}\n"
            f"☾ Illumination: {illumination:.1f}%\n"
            f"✅ Updated: {now.strftime('%I:%M:%S %p')}"
        )
        self.details_item.set_label(details)
        return False

    def calculate_absolute_humidity(self, temp_c, rh):
        """Calculate absolute humidity in g/m³"""
        if temp_c is None or rh is None:
            return 0.0
        # Magnus formula approximation
        svp = 6.112 * math.exp((17.67 * temp_c) / (temp_c + 243.5))
        abs_humidity = (svp * rh * 2.1674) / (273.15 + temp_c)
        return abs_humidity

if __name__ == "__main__":
    WeatherTray()
    Gtk.main()
