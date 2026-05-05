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
from timezonefinder import TimezoneFinder
from astral import LocationInfo
from astral.sun import sun

tf = TimezoneFinder()

# ==================== Exact suncalc.js Moon Illumination ====================
def to_days(date):
    # Matches suncalc.js exactly
    return (date.timestamp() / 86400) - 0.5 + 2440588 - 2451545

def right_ascension(l, b):
    return math.atan2(math.sin(l) * math.cos(e), math.cos(l))

def declination(l, b):
    return math.asin(math.sin(b) * math.cos(e) + math.cos(b) * math.sin(e) * math.sin(l))

def solar_mean_anomaly(d):
    return math.radians(357.5291 + 0.98560028 * d)

def ecliptic_longitude(M):
    C = math.radians(1.9148 * math.sin(M) + 0.02 * math.sin(2 * M) + 0.0003 * math.sin(3 * M))
    P = math.radians(102.9372)
    return M + C + P + math.pi

def sun_coords(d):
    M = solar_mean_anomaly(d)
    L = ecliptic_longitude(M)
    return {
        'dec': declination(L, 0),
        'ra': right_ascension(L, 0)
    }

def moon_coords(d):
    L = math.radians(218.316 + 13.176396 * d)
    M = math.radians(134.963 + 13.064993 * d)
    F = math.radians(93.272 + 13.22935 * d)
    l = L + math.radians(6.289 * math.sin(M))
    b = math.radians(5.128 * math.sin(F))
    dt = 385001 - 20905 * math.cos(M)
    return {
        'ra': right_ascension(l, b),
        'dec': declination(l, b),
        'dist': dt
    }

def get_moon_illumination(date):
    d = to_days(date)
    s = sun_coords(d)
    m = moon_coords(d)
    sdist = 149598000
    phi = math.acos(math.sin(s['dec']) * math.sin(m['dec']) +
                    math.cos(s['dec']) * math.cos(m['dec']) * math.cos(s['ra'] - m['ra']))
    inc = math.atan2(sdist * math.sin(phi), m['dist'] - sdist * math.cos(phi))
    angle = math.atan2(math.cos(s['dec']) * math.sin(s['ra'] - m['ra']),
                       math.sin(s['dec']) * math.cos(m['dec']) -
                       math.cos(s['dec']) * math.sin(m['dec']) * math.cos(s['ra'] - m['ra']))

    return {
        'fraction': (1 + math.cos(inc)) / 2,
        'phase': 0.5 + (0.5 * inc * (-1 if angle < 0 else 1)) / math.pi,
        'angle': angle
    }

e = math.radians(23.4397)   # obliquity of Earth

# Moon icon helper
def get_moon_icon(phase):
    if phase < 0.0625 or phase > 0.9375: return "🌑"
    elif phase < 0.1875: return "🌒"
    elif phase < 0.3125: return "🌓"
    elif phase < 0.4375: return "🌔"
    elif phase < 0.5625: return "🌕"
    elif phase < 0.6875: return "🌖"
    elif phase < 0.8125: return "🌗"
    else: return "🌘"


# Moon phasename helper
def get_moon_phasename(phase):
    if phase < 0.0625 or phase > 0.9375: return "New Moon"
    elif phase < 0.1875: return "Waxing Crescent"
    elif phase < 0.3125: return "First Quarter"
    elif phase < 0.4375: return "Waxing Gibbous"
    elif phase < 0.5625: return "Full Moon"
    elif phase < 0.6875: return "Waning Gibbous"
    elif phase < 0.8125: return "Last Quarter"
    else: return "Waning Crescent"


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

        self.details_label = Gtk.Label()
        self.details_item = Gtk.MenuItem()
        self.details_item.add(self.details_label)
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

    def get_timezone(self, lat, lon):
        if not lat or not lon:
            return pytz.timezone("UTC")
        try:
            tz_name = tf.timezone_at(lat=lat, lng=lon)
            if tz_name:
                return pytz.timezone(tz_name)
        except:
            pass
        return pytz.timezone("UTC")

    def update(self):
        threading.Thread(target=self._fetch_and_update, daemon=True).start()
        return True

    def _fetch_and_update(self):
        success = self.fetch_data()
        GLib.idle_add(self._update_ui, success)

    def _update_ui(self, success):
        if not success or not self.data:
            self.indicator.set_label("🌡️ -- °F", "home-weather-label")
            self.details_label.set_markup('<span size="large" weight="bold">JONES BIG ASS WEATHER WIDGET</span>\n❌ Sensor offline')
            return False

        tf = self.data.get("temperatureF", 0)
        tc = self.data.get("temperatureC", 0)
        humidity = self.data.get("humidity", 0)
        pressure_hpa = self.data.get("pressure", 0)

        self.indicator.set_label(f"🌡️ {tf:.1f}°F", "home-weather-label")

        altitude_m = self.data.get("altitude", 0)
        altitude_ft = altitude_m * 3.28084
        abs_humidity = self.calculate_absolute_humidity(tc, humidity)
        pressure_inhg = pressure_hpa * 0.029529983071

        lat = self.data.get("latitude")
        lon = self.data.get("longitude")
        tz = self.get_timezone(lat, lon)
        now = datetime.now(tz)

        loc = LocationInfo("Home", "US", tz.zone, lat or 39.433235, lon or -104.518867)
        sun_data = sun(loc.observer, date=now.date(), tzinfo=tz)

        # Exact suncalc.js moon calculation
        moon_data = get_moon_illumination(now)
        moon_phase_val = moon_data['phase']
        illumination = moon_data['fraction'] * 100
        moon_icon = get_moon_icon(moon_phase_val)
        moon_phasename = get_moon_phasename(moon_phase_val)

        details = (
            f"🌡️ Temp: {tf:.1f}°F / {tc:.1f}°C\n"
            f"💧 Humidity: {humidity:.1f}% ({abs_humidity:.1f} g/m³)\n"
            f"🌀 Pressure: {pressure_hpa} hPa ({pressure_inhg:.2f} inHg)\n"
            f"💡 Light: {self.data.get('lux'):.2f} lux\n"
            f"📶 WiFi: {self.data.get('rssi')} dBm\n"
            f"🏔️ Altitude: {altitude_m:.1f} m / {altitude_ft:.1f} ft\n"
            f"📍 GPS: {lat:.5f}, {lon:.5f}\n"
            f"🌐 Timezone: {tz.zone} ({now.strftime('%Z')})\n\n"
            f"🌅 Sunrise (Dawn): {sun_data['sunrise'].strftime('%I:%M %p')} ({sun_data['dawn'].strftime('%I:%M %p')})\n"
            f"☀️ Solar Noon: {sun_data['noon'].strftime('%I:%M %p')}\n"
            f"🌇 Sunset (Dusk): {sun_data['sunset'].strftime('%I:%M %p')} ({sun_data['dusk'].strftime('%I:%M %p')})\n\n"
            #f"{moon_icon} Moon Phase (Illum): {moon_phasename} - {moon_phase_val:.2f} ({illumination:.1f}%)\n"
            f"{moon_icon} {moon_phasename}: {illumination:.1f}%\n"
            f"✅ Updated: {now.strftime('%I:%M:%S %p')}"
        )

        self.details_label.set_markup(
            '<span size="large" weight="bold">👨🏾📣JONES BIG ASS WEATHER WIDGET🌎</span>\n' + details
        )
        return False

    def calculate_absolute_humidity(self, temp_c, rh):
        if temp_c is None or rh is None:
            return 0.0
        svp = 6.112 * math.exp((17.67 * temp_c) / (temp_c + 243.5))
        abs_humidity = (svp * rh * 2.1674) / (273.15 + temp_c)
        return abs_humidity

if __name__ == "__main__":
    WeatherTray()
    Gtk.main()
EOF
