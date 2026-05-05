#!/usr/bin/env python3
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('AppIndicator3', '0.1')
from gi.repository import Gtk, AppIndicator3, GLib
import requests
import threading
from datetime import datetime, timedelta, timezone
import math
import pytz
import webbrowser                     # ← NEW: for opening the browser
from timezonefinder import TimezoneFinder
from astral import LocationInfo
from astral.sun import sun

tf = TimezoneFinder()

# ====================== FULL SUNCALC PORT (exact translation of your original JS) ======================
PI = math.pi
sin = math.sin
cos = math.cos
tan = math.tan
asin = math.asin
atan = math.atan2
acos = math.acos
rad = PI / 180

DAY_MS = 86400
J1970 = 2440588
J2000 = 2451545

def to_julian(date):
    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)
    delta = date - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return delta.total_seconds() / DAY_MS - 0.5 + J1970

def from_julian(j):
    seconds = (j + 0.5 - J1970) * DAY_MS
    return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=seconds)

def to_days(date):
    return to_julian(date) - J2000

e = rad * 23.4397

def right_ascension(l, b):
    return atan(sin(l) * cos(e) - tan(b) * sin(e), cos(l))

def declination(l, b):
    return asin(sin(b) * cos(e) + cos(b) * sin(e) * sin(l))

def azimuth(H, phi, dec):
    return atan(sin(H), cos(H) * sin(phi) - tan(dec) * cos(phi))

def altitude(H, phi, dec):
    return asin(sin(phi) * sin(dec) + cos(phi) * cos(dec) * cos(H))

def sidereal_time(d, lw):
    return rad * (280.16 + 360.9856235 * d) - lw

def astro_refraction(h):
    if h < 0:
        h = 0
    return 0.0002967 / math.tan(h + 0.00312536 / (h + 0.08901179))

def solar_mean_anomaly(d):
    return rad * (357.5291 + 0.98560028 * d)

def ecliptic_longitude(M):
    C = rad * (1.9148 * sin(M) + 0.02 * sin(2 * M) + 0.0003 * sin(3 * M))
    P = rad * 102.9372
    return M + C + P + PI

def sun_coords(d):
    M = solar_mean_anomaly(d)
    L = ecliptic_longitude(M)
    return {"dec": declination(L, 0), "ra": right_ascension(L, 0)}

class SunCalc:
    times = [
        [-0.833, "sunrise", "sunset"],
        [-0.3, "sunriseEnd", "sunsetStart"],
        [-6, "dawn", "dusk"],
        [-12, "nauticalDawn", "nauticalDusk"],
        [-18, "nightEnd", "night"],
        [6, "goldenHourEnd", "goldenHour"],
    ]

    J0 = 0.0009

    @staticmethod
    def add_time(angle, rise_name, set_name):
        SunCalc.times.append([angle, rise_name, set_name])

    @staticmethod
    def get_position(date, lat, lng):
        lw = rad * -lng
        phi = rad * lat
        d = to_days(date)
        c = sun_coords(d)
        H = sidereal_time(d, lw) - c["ra"]
        return {
            "azimuth": azimuth(H, phi, c["dec"]),
            "altitude": altitude(H, phi, c["dec"]),
        }

    @staticmethod
    def julian_cycle(d, lw):
        return round(d - SunCalc.J0 - lw / (2 * PI))

    @staticmethod
    def approx_transit(Ht, lw, n):
        return SunCalc.J0 + (Ht + lw) / (2 * PI) + n

    @staticmethod
    def solar_transit_j(ds, M, L):
        return J2000 + ds + 0.0053 * sin(M) - 0.0069 * sin(2 * L)

    @staticmethod
    def hour_angle(h, phi, d):
        return acos((sin(h) - sin(phi) * sin(d)) / (cos(phi) * cos(d)))

    @staticmethod
    def observer_angle(height):
        return (-2.076 * math.sqrt(height)) / 60

    @staticmethod
    def get_set_j(h, lw, phi, dec, n, M, L):
        w = SunCalc.hour_angle(h, phi, dec)
        a = SunCalc.approx_transit(w, lw, n)
        return SunCalc.solar_transit_j(a, M, L)

    @staticmethod
    def get_times(date, lat, lng, height=0):
        lw = rad * -lng
        phi = rad * lat
        dh = SunCalc.observer_angle(height)
        d = to_days(date)
        n = SunCalc.julian_cycle(d, lw)
        ds = SunCalc.approx_transit(0, lw, n)
        M = solar_mean_anomaly(ds)
        L = ecliptic_longitude(M)
        dec = declination(L, 0)
        Jnoon = SunCalc.solar_transit_j(ds, M, L)

        result = {
            "solarNoon": from_julian(Jnoon),
            "nadir": from_julian(Jnoon - 0.5),
        }

        for time_def in SunCalc.times:
            h0 = (time_def[0] + dh) * rad
            Jset = SunCalc.get_set_j(h0, lw, phi, dec, n, M, L)
            Jrise = Jnoon - (Jset - Jnoon)
            result[time_def[1]] = from_julian(Jrise)
            result[time_def[2]] = from_julian(Jset)

        return result

    @staticmethod
    def moon_coords(d):
        L = rad * (218.316 + 13.176396 * d)
        M = rad * (134.963 + 13.064993 * d)
        F = rad * (93.272 + 13.22935 * d)
        l = L + rad * 6.289 * sin(M)
        b = rad * 5.128 * sin(F)
        dt = 385001 - 20905 * cos(M)
        return {
            "ra": right_ascension(l, b),
            "dec": declination(l, b),
            "dist": dt,
        }

    @staticmethod
    def get_moon_position(date, lat, lng):
        lw = rad * -lng
        phi = rad * lat
        d = to_days(date)
        c = SunCalc.moon_coords(d)
        H = sidereal_time(d, lw) - c["ra"]
        h = altitude(H, phi, c["dec"])
        pa = atan(sin(H), tan(phi) * cos(c["dec"]) - sin(c["dec"]) * cos(H))
        h = h + astro_refraction(h)
        return {
            "azimuth": azimuth(H, phi, c["dec"]),
            "altitude": h,
            "distance": c["dist"],
            "parallacticAngle": pa,
        }

    @staticmethod
    def get_moon_illumination(date=None):
        if date is None:
            date = datetime.now(timezone.utc)
        d = to_days(date)
        s = sun_coords(d)
        m = SunCalc.moon_coords(d)
        sdist = 149598000
        phi = acos(sin(s['dec']) * sin(m['dec']) + cos(s['dec']) * cos(m['dec']) * cos(s['ra'] - m['ra']))
        inc = atan(sdist * sin(phi), m['dist'] - sdist * cos(phi))
        angle = atan(cos(s['dec']) * sin(s['ra'] - m['ra']),
                     sin(s['dec']) * cos(m['dec']) - cos(s['dec']) * sin(m['dec']) * cos(s['ra'] - m['ra']))
        return {
            'fraction': (1 + cos(inc)) / 2,
            'phase': 0.5 + (0.5 * inc * (-1 if angle < 0 else 1)) / PI,
            'angle': angle
        }

    @staticmethod
    def hours_later(date, h):
        return date + timedelta(hours=h)

    @staticmethod
    def get_moon_times(date, lat, lng, in_utc=False):
        t = date.replace(hour=0, minute=0, second=0, microsecond=0)
        if in_utc and t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)

        hc = 0.133 * rad
        pos = SunCalc.get_moon_position(t, lat, lng)
        h0 = pos["altitude"] - hc
        rise = None
        sett = None
        ye = 0.0

        for i in range(1, 25, 2):
            h1 = SunCalc.get_moon_position(SunCalc.hours_later(t, i), lat, lng)["altitude"] - hc
            h2 = SunCalc.get_moon_position(SunCalc.hours_later(t, i + 1), lat, lng)["altitude"] - hc

            a = (h0 + h2) / 2 - h1
            b = (h2 - h0) / 2
            xe = -b / (2 * a) if a != 0 else 0
            ye = (a * xe + b) * xe + h1
            d = b * b - 4 * a * h1
            roots = 0
            x1 = x2 = 0.0

            if d >= 0:
                dx = math.sqrt(d) / (abs(a) * 2)
                x1 = xe - dx
                x2 = xe + dx
                if abs(x1) <= 1: roots += 1
                if abs(x2) <= 1: roots += 1
                if x1 < -1: x1 = x2

            if roots == 1:
                if h0 < 0:
                    rise = i + x1
                else:
                    sett = i + x1
            elif roots == 2:
                rise = i + (x2 if ye < 0 else x1)
                sett = i + (x1 if ye < 0 else x2)

            if rise is not None and sett is not None:
                break
            h0 = h2

        result = {}
        if rise is not None:
            result["rise"] = SunCalc.hours_later(t, rise)
        if sett is not None:
            result["set"] = SunCalc.hours_later(t, sett)

        if rise is None and sett is None:
            result["alwaysUp" if ye > 0 else "alwaysDown"] = True

        return result


# ====================== MOON ICON & PHASE NAME HELPERS ======================
def get_moon_icon(phase):
    if phase < 0.0625 or phase > 0.9375: return "🌑"
    elif phase < 0.1875: return "🌒"
    elif phase < 0.3125: return "🌓"
    elif phase < 0.4375: return "🌔"
    elif phase < 0.5625: return "🌕"
    elif phase < 0.6875: return "🌖"
    elif phase < 0.8125: return "🌗"
    else: return "🌘"

def get_moon_phasename(phase):
    if phase < 0.0625 or phase > 0.9375: return "New Moon"
    elif phase < 0.1875: return "Waxing Crescent"
    elif phase < 0.3125: return "First Quarter"
    elif phase < 0.4375: return "Waxing Gibbous"
    elif phase < 0.5625: return "Full Moon"
    elif phase < 0.6875: return "Waning Gibbous"
    elif phase < 0.8125: return "Last Quarter"
    else: return "Waning Crescent"


# ====================== MAIN WIDGET (now with clickable details) ======================
class WeatherTray:
    def __init__(self):
        self.indicator = AppIndicator3.Indicator.new(
            "home-weather", "", AppIndicator3.IndicatorCategory.APPLICATION_STATUS
        )
        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        self.indicator.set_label("🌡️ -- °F", "home-weather-label")
        self.menu = Gtk.Menu()
        self.details_label = Gtk.Label()
        self.details_item = Gtk.MenuItem()
        self.details_item.add(self.details_label)
        
        # ←←← NEW: Make the entire details section clickable
        self.details_item.connect("activate", self.on_details_clicked)
        
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

        tf_temp = self.data.get("temperatureF", 0)
        tc = self.data.get("temperatureC", 0)
        humidity = self.data.get("humidity", 0)
        pressure_hpa = self.data.get("pressure", 0)

        dewpoint_c = self.calculate_dew_point(tc, humidity)
        dew_str = f"🌧️ Dew Point: {dewpoint_c*9/5+32:.1f}°F / {dewpoint_c:.1f}°C\n" if dewpoint_c is not None else ""

        self.indicator.set_label(f"🌡️ {tf_temp:.1f}°F", "home-weather-label")

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

        moon_data = SunCalc.get_moon_illumination(now)
        moon_phase_val = moon_data['phase']
        illumination = moon_data['fraction'] * 100
        moon_icon = get_moon_icon(moon_phase_val)
        moon_phasename = get_moon_phasename(moon_phase_val)

        moon_times = SunCalc.get_moon_times(now, lat or 39.433235, lon or -104.518867)
        mr = moon_times.get("rise")
        ms = moon_times.get("set")

        moon_rise_str = mr.astimezone(tz).strftime('%I:%M %p') if mr else "—"
        moon_set_str = ms.astimezone(tz).strftime('%I:%M %p') if ms else "—"

        if "alwaysUp" in moon_times:
            moon_rise_str = "↑ Always up"
            moon_set_str = "↑ Always up"
        if "alwaysDown" in moon_times:
            moon_rise_str = "↓ Never rises"
            moon_set_str = "↓ Never sets"

        details = (
            f"\n🌡️ Temp: {tf_temp:.1f}°F / {tc:.1f}°C\n"
            f"{dew_str}"
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
            f"🌙 Moonrise: {moon_rise_str}    Moonset: {moon_set_str}\n"
            f"{moon_icon} {moon_phasename}: {illumination:.1f}%\n\n"
            f"<span foreground='#aaaaaa' size='small'>Click anywhere here to open dashboard</span>\n"
            f"✅ Updated: {now.strftime('%I:%M:%S %p')}"
        )

        self.details_label.set_markup(
            '<span size="large" weight="bold">👨🏾📣Jones Big Ass Weather Widget🌦️</span>\n' + details
        )
        return False

    # ←←← NEW: Click handler for the details section
    def on_details_clicked(self, menuitem):
        """Open the sensor web dashboard when the details menu item is clicked"""
        webbrowser.open("http://192.168.1.62")

    def calculate_absolute_humidity(self, temp_c, rh):
        if temp_c is None or rh is None:
            return 0.0
        svp = 6.112 * math.exp((17.67 * temp_c) / (temp_c + 243.5))
        return (svp * rh * 2.1674) / (273.15 + temp_c)

    def calculate_dew_point(self, temp_c, rh):
        if temp_c is None or rh is None or rh <= 0 or rh > 100:
            return None
        try:
            alpha = math.log(rh / 100.0) + (17.67 * temp_c) / (temp_c + 243.5)
            return (243.5 * alpha) / (17.67 - alpha)
        except:
            return None


if __name__ == "__main__":
    WeatherTray()
    Gtk.main()
