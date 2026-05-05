#!/usr/bin/env python3
# This shebang line specifies that the script should be executed using the Python 3 interpreter (whichever 'python3' is in the user's PATH).

# =============================
# JONES BIG ASS WEATHER WIDGET 
# =============================
# FOR INSTALLATION INSTRUCTIONS PLEASE SEE [howToUseWeatherTray_Ubuntu.md](./docs/howToUseWeatherTray_Ubuntu.md) IN THE DOCS FOLDER OF THIS REPO!
#
# WHAT THIS SCRIPT DOES:
# This is a complete Linux system tray (AppIndicator) weather widget built with GTK3 and AppIndicator3.
# It displays live weather data from a custom home weather station/sensor device running on your local network.
#
# HOW IT WORKS (high-level overview):
# 1. It creates a system tray icon that shows the current temperature (e.g., "🌡️ 72.3°F / 22.4°C").
# 2. Every 30 seconds it fetches fresh JSON data from the sensor at http://192.168.1.60/data using a background thread (so the UI never freezes).
# 3. When you left-click the tray icon, a popup menu appears with rich details:
#    - Temperature, dew point, humidity (with absolute humidity in g/m³), pressure, altitude
#    - Precise sunrise/sunset/dawn/dusk times (calculated with the astral library)
#    - Full moon phase, illumination %, moonrise/moonset (using a complete port of the popular SunCalc JavaScript library)
#    - Light level (lux), WiFi signal strength (RSSI), GPS coordinates, number of satellites, timezone, device uptime
# 4. Clicking the "details" menu item opens the sensor's web dashboard in your default browser.
# 5. All times are automatically adjusted to the sensor's local timezone (detected via latitude/longitude using timezonefinder).
# 6. The code includes a full, self-contained astronomy library (SunCalc port) for sun and moon calculations - no external API calls needed.
# 7. If the sensor goes offline, the widget gracefully shows an error message in the menu.
#
# WHY THIS IS USEFUL FOR FUTURE DEVELOPERS:
# - Every single line is commented so you can understand exactly what each statement does.
# - The SunCalc class is a faithful port of the popular JS library (https://github.com/mourner/suncalc) - you can extend it easily.
# - Threading + GLib.idle_add pattern is the correct way to keep GTK responsive.
# - Modular helper functions (dew point, absolute humidity, ms_to_dhms, moon icons) are clearly explained.
# - You can easily change the sensor URL, add more sensors, or customize the menu.
#
# REQUIREMENTS:
# - Python 3
# - gir1.2-gtk-3.0, gir1.2-appindicator3-0.1 (system packages)
# - pip packages: requests, pytz, timezonefinder, astral
#
# HOW TO RUN:
#   ./weather_widget.py   (or python3 weather_widget.py)
#   It will appear in your system tray immediately and update forever until you quit.
#
# =============================================================================

import gi
# Imports the 'gi' (GObject Introspection) module, which lets Python talk to C libraries like GTK and AppIndicator3.

gi.require_version('Gtk', '3.0')
# Tells gi which version of the GTK library we want to use (version 3.0). This must be called BEFORE importing Gtk.

gi.require_version('AppIndicator3', '0.1')
# Tells gi which version of the AppIndicator3 library we want to use (the system tray indicator API).

from gi.repository import Gtk, AppIndicator3, GLib
# Imports the actual GTK, AppIndicator3, and GLib classes and functions we will use for the GUI and main loop.

import requests
# Imports the requests library so we can make HTTP GET requests to fetch JSON data from the weather sensor.

import threading
# Imports the threading module so we can run the network request in a background thread (prevents the GUI from freezing).

from datetime import datetime, timedelta, timezone
# Imports datetime classes needed for handling dates, times, timezones, and time deltas (used heavily in astronomy calculations).

import math
# Imports the math module because we need sin(), cos(), tan(), asin(), etc. for the SunCalc astronomy formulas.

import pytz
# Imports pytz, a timezone library that lets us work with real-world timezones (e.g., converting UTC to local sensor time).

import webbrowser
# Imports the webbrowser module so we can open the sensor's web dashboard in the user's default browser when they click the menu.

from timezonefinder import TimezoneFinder
# Imports TimezoneFinder - a fast library that can determine the timezone name from any latitude/longitude on Earth.

from astral import LocationInfo
# Imports LocationInfo from the astral library (used to create a location object for sunrise/sunset calculations).

from astral.sun import sun
# Imports the 'sun' function from astral, which calculates sunrise, sunset, dawn, and dusk times for a given location and date.

def ms_to_dhms(milliseconds: int) -> str:
    # Defines a helper function that converts a millisecond uptime value into a human-readable string like "3d 05hrs 12min 34sec".
    # Convert to timedelta
    td = timedelta(milliseconds=milliseconds)
    # Creates a timedelta object from the raw milliseconds (timedelta understands milliseconds).

    # Get total days and the remaining time
    days = td.days
    # Extracts the whole number of days from the timedelta.

    # Get hours, minutes, seconds from the time part
    seconds = td.seconds
    # Extracts the remaining seconds (after whole days) from the timedelta.

    hours = seconds // 3600
    # Integer division: total remaining seconds divided by 3600 gives whole hours.

    minutes = (seconds % 3600) // 60
    # Modulo 3600 gives leftover seconds in the hour, then divide by 60 for whole minutes.

    secs = seconds % 60
    # Modulo 60 gives the leftover seconds after minutes.

    return f"{days}d {hours:02d}hrs {minutes:02d}min {secs:02d}sec"
    # Returns a nicely formatted string with zero-padded hours, minutes, and seconds.

tf = TimezoneFinder()
# Creates a single global TimezoneFinder instance (reused for every timezone lookup - more efficient than creating a new one each time).

# ====================== FULL SUNCALC PORT (from original JS) ======================
# This entire section is a complete, line-by-line Python port of the popular SunCalc JavaScript library.
# It calculates sun position, sunrise/sunset times, and moon position/phase/illumination with high accuracy.
# No external APIs are used - everything is pure math based on astronomical formulas.

PI = math.pi
# Defines PI as a constant for convenience in all the trigonometric calculations that follow.

sin = math.sin
# Creates a short alias 'sin' so we can write sin(x) instead of math.sin(x) everywhere (makes the ported formulas cleaner).

cos = math.cos
# Creates a short alias 'cos' for the cosine function.

tan = math.tan
# Creates a short alias 'tan' for the tangent function.

asin = math.asin
# Creates a short alias 'asin' for the arcsine function.

atan = math.atan2
# Creates a short alias 'atan' that actually points to atan2 (the two-argument arctangent - more accurate for angles).

acos = math.acos
# Creates a short alias 'acos' for the arccosine function.

rad = PI / 180
# Defines a conversion constant: degrees to radians (used everywhere because trig functions expect radians).

DAY_MS = 86400
# Number of milliseconds in one day (24*60*60*1000) - used in Julian date calculations.

J1970 = 2440588
# Julian day number for the Unix epoch (1970-01-01) - base for converting dates to Julian days.

J2000 = 2451545
# Julian day number for the J2000 epoch (used in many astronomical formulas as a reference point).

def to_julian(date):
    # Helper function that converts a Python datetime object into a Julian day number.
    if date.tzinfo is None:
        # If the date has no timezone info, assume it is UTC.
        date = date.replace(tzinfo=timezone.utc)
    delta = date - datetime(1970, 1, 1, tzinfo=timezone.utc)
    # Calculates the time difference between the given date and the Unix epoch (1970-01-01 UTC).
    return delta.total_seconds() / DAY_MS - 0.5 + J1970
    # Converts the timedelta to days (including fractional day) and adjusts to the Julian day scale.

def from_julian(j):
    # Helper function that converts a Julian day number back into a Python datetime object (in UTC).
    seconds = (j + 0.5 - J1970) * DAY_MS
    # Reverses the Julian day formula to get total seconds since 1970-01-01.
    return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=seconds)
    # Adds the calculated seconds to the epoch date and returns a datetime.

def to_days(date):
    # Simple helper that returns the number of days since J2000 epoch (used in sun/moon coordinate math).
    return to_julian(date) - J2000
    # Reuses to_julian and subtracts the J2000 constant.

e = rad * 23.4397
# Obliquity of the ecliptic (Earth's axial tilt) in radians - a fundamental constant for sun position calculations.

def right_ascension(l, b):
    # Calculates right ascension from ecliptic longitude (l) and latitude (b).
    return atan(sin(l) * cos(e) - tan(b) * sin(e), cos(l))
    # Standard astronomical formula for converting ecliptic coordinates to equatorial right ascension.

def declination(l, b):
    # Calculates declination from ecliptic longitude (l) and latitude (b).
    return asin(sin(b) * cos(e) + cos(b) * sin(e) * sin(l))
    # Standard astronomical formula for declination.

def azimuth(H, phi, dec):
    # Calculates the azimuth (compass direction) of a celestial object.
    return atan(sin(H), cos(H) * sin(phi) - tan(dec) * cos(phi))
    # Formula that uses hour angle H, observer latitude phi, and declination.

def altitude(H, phi, dec):
    # Calculates the altitude (angle above horizon) of a celestial object.
    return asin(sin(phi) * sin(dec) + cos(phi) * cos(dec) * cos(H))
    # Standard altitude formula.

def sidereal_time(d, lw):
    # Calculates local sidereal time (star time) for a given day and longitude.
    return rad * (280.16 + 360.9856235 * d) - lw
    # Formula based on Earth's rotation rate.

def astro_refraction(h):
    # Calculates atmospheric refraction correction for low altitudes (makes the sun appear higher when near horizon).
    if h < 0:
        # If the object is below the horizon, treat it as exactly on the horizon for the formula.
        h = 0
    return 0.0002967 / math.tan(h + 0.00312536 / (h + 0.08901179))
    # Empirical refraction formula (very accurate for visual astronomy).

def solar_mean_anomaly(d):
    # Calculates the sun's mean anomaly for a given day (used in ecliptic longitude).
    return rad * (357.5291 + 0.98560028 * d)
    # Mean anomaly formula (how far the Earth has moved in its orbit).

def ecliptic_longitude(M):
    # Calculates the sun's ecliptic longitude from its mean anomaly.
    C = rad * (1.9148 * sin(M) + 0.02 * sin(2 * M) + 0.0003 * sin(3 * M))
    # Equation of the center (correction for elliptical orbit).
    P = rad * 102.9372
    # Perihelion longitude constant.
    return M + C + P + PI
    # Full ecliptic longitude formula.

def sun_coords(d):
    # Returns the sun's declination and right ascension for a given day.
    M = solar_mean_anomaly(d)
    # Compute mean anomaly.
    L = ecliptic_longitude(M)
    # Compute ecliptic longitude.
    return {"dec": declination(L, 0), "ra": right_ascension(L, 0)}
    # Return dictionary with declination and right ascension (latitude b=0 for the sun).

class SunCalc:
    # This class contains the complete SunCalc astronomy engine (ported from JavaScript).
    # All methods are static because they are pure math functions that don't need instance state.

    times = [
        [-0.833, "sunrise", "sunset"],
        [-0.3, "sunriseEnd", "sunsetStart"],
        [-6, "dawn", "dusk"],
        [-12, "nauticalDawn", "nauticalDusk"],
        [-18, "nightEnd", "night"],
        [6, "goldenHourEnd", "goldenHour"],
    ]
    # List of standard solar event definitions (angle in degrees, rise name, set name).

    J0 = 0.0009
    # Small constant used in Julian cycle calculations for sunrise/set.

    @staticmethod
    def add_time(angle, rise_name, set_name):
        # Allows users to add custom solar events (e.g., civil twilight) at runtime.
        SunCalc.times.append([angle, rise_name, set_name])
        # Appends a new time definition to the class list.

    @staticmethod
    def get_position(date, lat, lng):
        # Returns the sun's azimuth and altitude at a specific date, latitude, and longitude.
        lw = rad * -lng
        # Longitude converted to radians (negative because of coordinate convention).
        phi = rad * lat
        # Latitude converted to radians.
        d = to_days(date)
        # Days since J2000.
        c = sun_coords(d)
        # Get sun's declination and right ascension.
        H = sidereal_time(d, lw) - c["ra"]
        # Compute hour angle.
        return {
            "azimuth": azimuth(H, phi, c["dec"]),
            "altitude": altitude(H, phi, c["dec"]),
        }
        # Return azimuth and altitude in a dictionary.

    @staticmethod
    def julian_cycle(d, lw):
        # Calculates the Julian cycle number for sunrise/set approximation.
        return round(d - SunCalc.J0 - lw / (2 * PI))
        # Standard formula to find nearest solar transit cycle.

    @staticmethod
    def approx_transit(Ht, lw, n):
        # Approximates the time of solar transit.
        return SunCalc.J0 + (Ht + lw) / (2 * PI) + n
        # Formula used in the iterative sunrise/set solver.

    @staticmethod
    def solar_transit_j(ds, M, L):
        # Calculates the exact Julian day of solar noon/transit.
        return J2000 + ds + 0.0053 * sin(M) - 0.0069 * sin(2 * L)
        # High-precision solar transit formula.

    @staticmethod
    def hour_angle(h, phi, d):
        # Calculates the hour angle for a given altitude h (used in rise/set).
        return acos((sin(h) - sin(phi) * sin(d)) / (cos(phi) * cos(d)))
        # Standard hour-angle formula for sunrise/set.

    @staticmethod
    def observer_angle(height):
        # Calculates the angular correction for observer height above sea level (in arcminutes).
        return (-2.076 * math.sqrt(height)) / 60
        # Empirical formula for dip of the horizon due to height.

    @staticmethod
    def get_set_j(h, lw, phi, dec, n, M, L):
        # Helper that computes the Julian day of sunrise or sunset for a specific altitude.
        w = SunCalc.hour_angle(h, phi, dec)
        # Hour angle at the desired altitude.
        a = SunCalc.approx_transit(w, lw, n)
        # Approximate transit time.
        return SunCalc.solar_transit_j(a, M, L)
        # Convert to exact Julian day.

    @staticmethod
    def get_times(date, lat, lng, height=0):
        # Main public method: returns a dictionary of ALL sun times (sunrise, sunset, dawn, golden hour, etc.).
        lw = rad * -lng
        # Longitude in radians.
        phi = rad * lat
        # Latitude in radians.
        dh = SunCalc.observer_angle(height)
        # Height correction in radians.
        d = to_days(date)
        # Days since J2000.
        n = SunCalc.julian_cycle(d, lw)
        # Current Julian cycle.
        ds = SunCalc.approx_transit(0, lw, n)
        # Approximate transit time.
        M = solar_mean_anomaly(ds)
        # Mean anomaly.
        L = ecliptic_longitude(M)
        # Ecliptic longitude.
        dec = declination(L, 0)
        # Sun declination.
        Jnoon = SunCalc.solar_transit_j(ds, M, L)
        # Exact solar noon Julian day.

        result = {
            "solarNoon": from_julian(Jnoon),
            "nadir": from_julian(Jnoon - 0.5),
        }
        # Start the result dictionary with solar noon and nadir (midnight).

        for time_def in SunCalc.times:
            # Loop through every solar event definition (dawn, sunrise, etc.).
            h0 = (time_def[0] + dh) * rad
            # Convert the angle (plus height correction) to radians.
            Jset = SunCalc.get_set_j(h0, lw, phi, dec, n, M, L)
            # Calculate set time.
            Jrise = Jnoon - (Jset - Jnoon)
            # Sunrise is symmetric around noon.
            result[time_def[1]] = from_julian(Jrise)
            # Store the rise time as a datetime object.
            result[time_def[2]] = from_julian(Jset)
            # Store the set time as a datetime object.

        return result
        # Return the complete dictionary of sun times.

    @staticmethod
    def moon_coords(d):
        # Calculates the moon's equatorial coordinates and distance for a given day.
        L = rad * (218.316 + 13.176396 * d)
        # Moon's mean longitude.
        M = rad * (134.963 + 13.064993 * d)
        # Mean anomaly.
        F = rad * (93.272 + 13.22935 * d)
        # Mean distance.
        l = L + rad * 6.289 * sin(M)
        # Corrected longitude.
        b = rad * 5.128 * sin(F)
        # Latitude.
        dt = 385001 - 20905 * cos(M)
        # Distance from Earth in km.
        return {
            "ra": right_ascension(l, b),
            "dec": declination(l, b),
            "dist": dt,
        }
        # Return right ascension, declination, and distance.

    @staticmethod
    def get_moon_position(date, lat, lng):
        # Returns the moon's azimuth, altitude, distance, and parallactic angle.
        lw = rad * -lng
        # Longitude in radians.
        phi = rad * lat
        # Latitude in radians.
        d = to_days(date)
        # Days since J2000.
        c = SunCalc.moon_coords(d)
        # Get moon coordinates.
        H = sidereal_time(d, lw) - c["ra"]
        # Hour angle.
        h = altitude(H, phi, c["dec"])
        # Altitude before refraction.
        pa = atan(sin(H), tan(phi) * cos(c["dec"]) - sin(c["dec"]) * cos(H))
        # Parallactic angle.
        h = h + astro_refraction(h)
        # Apply atmospheric refraction.
        return {
            "azimuth": azimuth(H, phi, c["dec"]),
            "altitude": h,
            "distance": c["dist"],
            "parallacticAngle": pa,
        }
        # Return full moon position dictionary.

    @staticmethod
    def get_moon_illumination(date=None):
        # Calculates the moon's illuminated fraction, phase, and angle (phase of the moon).
        if date is None:
            # Default to current UTC time if no date is supplied.
            date = datetime.now(timezone.utc)
        d = to_days(date)
        # Days since J2000.
        s = sun_coords(d)
        # Sun position.
        m = SunCalc.moon_coords(d)
        # Moon position.
        sdist = 149598000
        # Average Earth-Sun distance in km.
        phi = acos(sin(s['dec']) * sin(m['dec']) + cos(s['dec']) * cos(m['dec']) * cos(s['ra'] - m['ra']))
        # Phase angle between sun and moon.
        inc = atan(sdist * sin(phi), m['dist'] - sdist * cos(phi))
        # Illuminated fraction angle.
        angle = atan(cos(s['dec']) * sin(s['ra'] - m['ra']),
                     sin(s['dec']) * cos(m['dec']) - cos(s['dec']) * sin(m['dec']) * cos(s['ra'] - m['ra']))
        # Position angle of the moon's bright limb.
        return {
            'fraction': (1 + cos(inc)) / 2,
            # Illuminated fraction (0.0 to 1.0).
            'phase': 0.5 + (0.5 * inc * (-1 if angle < 0 else 1)) / PI,
            # Phase value used for icon selection (0.0 = new moon, 0.5 = full moon).
            'angle': angle
            # Angle of the illuminated edge.
        }
        # Return illumination data dictionary.

    @staticmethod
    def hours_later(date, h):
        # Simple helper that adds a number of hours to a datetime (used in moon rise/set search).
        return date + timedelta(hours=h)
        # Returns a new datetime object shifted by h hours.

    @staticmethod
    def get_moon_times(date, lat, lng, in_utc=False):
        # Calculates the moonrise and moonset times for a given date (very accurate iterative method).
        t = date.replace(hour=0, minute=0, second=0, microsecond=0)
        # Start at midnight of the given date (local time).
        if in_utc and t.tzinfo is None:
            # If requested, force UTC timezone.
            t = t.replace(tzinfo=timezone.utc)

        hc = 0.133 * rad
        # Altitude threshold for "rise" (moon is considered risen when it reaches this altitude).
        pos = SunCalc.get_moon_position(t, lat, lng)
        # Get moon position at midnight.
        h0 = pos["altitude"] - hc
        # Starting altitude offset.
        rise = None
        # Will hold the rise time (in fractional hours).
        sett = None
        # Will hold the set time.
        ye = 0.0
        # Used in quadratic solving.

        for i in range(1, 25, 2):
            # Loop through 24 hours in 2-hour steps (efficient search).
            h1 = SunCalc.get_moon_position(SunCalc.hours_later(t, i), lat, lng)["altitude"] - hc
            # Altitude 2 hours later.
            h2 = SunCalc.get_moon_position(SunCalc.hours_later(t, i + 1), lat, lng)["altitude"] - hc
            # Altitude 4 hours later.

            a = (h0 + h2) / 2 - h1
            # Quadratic coefficient a.
            b = (h2 - h0) / 2
            # Quadratic coefficient b.
            xe = -b / (2 * a) if a != 0 else 0
            # Root of the derivative.
            ye = (a * xe + b) * xe + h1
            # Evaluated quadratic at xe.
            d = b * b - 4 * a * h1
            # Discriminant for quadratic equation.
            roots = 0
            x1 = x2 = 0.0
            # Roots of the quadratic.

            if d >= 0:
                # If real roots exist...
                dx = math.sqrt(d) / (abs(a) * 2)
                # Distance to roots.
                x1 = xe - dx
                x2 = xe + dx
                if abs(x1) <= 1: roots += 1
                # Count valid roots (must be between -1 and 1).
                if abs(x2) <= 1: roots += 1
                if x1 < -1: x1 = x2
                # Adjust for edge cases.

            if roots == 1:
                # Only one valid crossing.
                if h0 < 0:
                    rise = i + x1
                else:
                    sett = i + x1
            elif roots == 2:
                # Two crossings - decide which is rise and which is set.
                rise = i + (x2 if ye < 0 else x1)
                sett = i + (x1 if ye < 0 else x2)

            if rise is not None and sett is not None:
                # Once we have both rise and set, we can stop searching.
                break
            h0 = h2
            # Move to next interval.

        result = {}
        # Build the final result dictionary.
        if rise is not None:
            result["rise"] = SunCalc.hours_later(t, rise)
            # Store rise time.
        if sett is not None:
            result["set"] = SunCalc.hours_later(t, sett)
            # Store set time.

        if rise is None and sett is None:
            # Special case when the moon never rises or never sets on this day.
            result["alwaysUp" if ye > 0 else "alwaysDown"] = True

        return result
        # Return moon rise/set data.

# ====================== MOON ICON & PHASE NAME HELPERS ======================
def get_moon_icon(phase):
    # Returns a Unicode emoji representing the current moon phase (0.0 to 1.0).
    if phase < 0.0625 or phase > 0.9375: return "🌑"
    # New Moon.
    elif phase < 0.1875: return "🌒"
    # Waxing Crescent.
    elif phase < 0.3125: return "🌓"
    # First Quarter.
    elif phase < 0.4375: return "🌔"
    # Waxing Gibbous.
    elif phase < 0.5625: return "🌕"
    # Full Moon.
    elif phase < 0.6875: return "🌖"
    # Waning Gibbous.
    elif phase < 0.8125: return "🌗"
    # Last Quarter.
    else: return "🌘"
    # Waning Crescent.

def get_moon_phasename(phase):
    # Returns the English name of the current moon phase (used in the menu).
    if phase < 0.0625 or phase > 0.9375: return "New Moon"
    # New Moon.
    elif phase < 0.1875: return "Waxing Crescent"
    # Waxing Crescent.
    elif phase < 0.3125: return "First Quarter"
    # First Quarter.
    elif phase < 0.4375: return "Waxing Gibbous"
    # Waxing Gibbous.
    elif phase < 0.5625: return "Full Moon"
    # Full Moon.
    elif phase < 0.6875: return "Waning Gibbous"
    # Waning Gibbous.
    elif phase < 0.8125: return "Last Quarter"
    # Last Quarter.
    else: return "Waning Crescent"
    # Waning Crescent.

# ====================== MAIN WIDGET CLASS ======================
class WeatherTray:
    # This is the main class that creates and manages the entire system tray weather widget.
    def __init__(self):
        # Constructor - runs once when the widget starts.
        self.indicator = AppIndicator3.Indicator.new(
            "home-weather", "", AppIndicator3.IndicatorCategory.APPLICATION_STATUS
        )
        # Creates a new AppIndicator3 indicator (the tray icon) with a unique ID.

        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        # Makes the indicator visible in the system tray.

        self.indicator.set_label("🌡️ -- °F", "home-weather-label")
        # Sets the initial label shown next to the icon (temperature placeholder).

        self.menu = Gtk.Menu()
        # Creates a new GTK menu that will pop up when the tray icon is clicked.

        self.details_label = Gtk.Label()
        # Creates a GTK Label widget that will hold all the rich weather text (supports markup).

        self.details_item = Gtk.MenuItem()
        # Creates a menu item that will contain the label.

        self.details_item.add(self.details_label)
        # Adds the label widget inside the menu item.

        self.details_item.connect("activate", self.on_details_clicked)
        # Connects the menu item's "activate" signal to our click handler method.

        self.menu.append(self.details_item)
        # Adds the details menu item to the popup menu.

        separator = Gtk.SeparatorMenuItem()
        # Creates a visual separator line in the menu.

        self.menu.append(separator)
        # Adds the separator after the details item.

        quit_item = Gtk.MenuItem(label="Quit")
        # Creates a simple "Quit" menu item.

        quit_item.connect("activate", lambda x: Gtk.main_quit())
        # Connects the Quit item so it calls Gtk.main_quit() when clicked (exits the program cleanly).

        self.menu.append(quit_item)
        # Adds the Quit item at the bottom of the menu.

        self.menu.show_all()
        # Makes the entire menu (and all its children) visible.

        self.indicator.set_menu(self.menu)
        # Attaches the completed menu to the system tray indicator.

        self.url = "http://192.168.1.60/data"
        # Stores the URL of our local weather sensor's JSON endpoint (change this if your sensor is on a different IP).

        self.data = {}
        # Empty dictionary that will hold the latest sensor JSON data.

        GLib.timeout_add_seconds(30, self.update)
        # Schedules the self.update() method to run every 30 seconds (GLib is the main loop).

        self.update()
        # Immediately performs the first update so the widget shows data right away when it starts.

    def fetch_data(self):
        # Fetches fresh JSON data from the sensor over HTTP.
        try:
            r = requests.get(self.url, timeout=8)
            # Makes an HTTP GET request with an 8-second timeout.
            r.raise_for_status()
            # Raises an exception if the server returned an error status code.
            self.data = r.json()
            # Parses the response as JSON and stores it in self.data.
            return True
            # Success!
        except:
            # If any error occurs (network issue, bad JSON, timeout, etc.).
            self.data = {}
            # Clear the data so we know the sensor is offline.
            return False
            # Failure.

    def get_timezone(self, lat, lon):
        # Returns a pytz timezone object for the sensor's GPS coordinates.
        if not lat or not lon:
            # If we have no valid coordinates, fall back to UTC.
            return pytz.timezone("UTC")
        try:
            tz_name = tf.timezone_at(lat=lat, lng=lon)
            # Ask TimezoneFinder for the IANA timezone name at this lat/lon.
            if tz_name:
                return pytz.timezone(tz_name)
                # Return the actual pytz timezone object.
        except:
            # If anything goes wrong (rare), fall back to UTC.
            pass
        return pytz.timezone("UTC")
        # Default fallback.

    def update(self):
        # This method is called by GLib every 30 seconds.
        # It starts a background thread so network I/O doesn't block the GTK main loop.
        threading.Thread(target=self._fetch_and_update, daemon=True).start()
        # daemon=True means the thread will die when the main program exits.
        return True
        # Returning True tells GLib to keep repeating this timeout.

    def _fetch_and_update(self):
        # This runs in the background thread.
        success = self.fetch_data()
        # Fetch the latest sensor data.
        GLib.idle_add(self._update_ui, success)
        # Schedule the UI update to happen on the main GTK thread (safe).

    def _update_ui(self, success):
        # This runs on the main GTK thread and actually refreshes the tray icon and menu.
        if not success or not self.data:
            # If the fetch failed or we have no data...
            self.indicator.set_label("🌡️ -- °F", "home-weather-label")
            # Show placeholder temperature.
            self.details_label.set_markup('<span size="large" weight="bold">👨🏾📢Jones Big Ass Weather Widget🌦️⛱️</span>\n\n❌ ❌ ❌ DEVICE OFFLINE ❌ ❌ ❌')
            # Show big offline warning in the menu.
            return False
            # Done.

        tf_temp = self.data.get("temperatureF", 0)
        # Get temperature in Fahrenheit (default 0 if missing).
        tc = self.data.get("temperatureC", 0)
        # Get temperature in Celsius.
        humidity = self.data.get("humidity", 0)
        # Get relative humidity percentage.
        pressure_hpa = self.data.get("pressure", 0)
        # Get barometric pressure in hPa.

        dewpoint_c = self.calculate_dew_point(tc, humidity)
        # Calculate dew point using our helper method.
        dew_str = f"🌧️ Dew Point: {dewpoint_c*9/5+32:.1f}°F / {dewpoint_c:.1f}°C\n" if dewpoint_c is not None else ""
        # Build a nice dew-point string (or empty if calculation failed).

        self.indicator.set_label(f"🌡️ {tf_temp:.1f}°F / {tc:.1f}°C", "home-weather-label")
        # Update the tray icon label with the current temperature (this is what the user sees all the time).

        altitude_m = self.data.get("altitude", 0)
        # Get altitude in meters.
        altitude_ft = altitude_m * 3.28084
        # Convert meters to feet.
        abs_humidity = self.calculate_absolute_humidity(tc, humidity)
        # Calculate absolute humidity in g/m³.
        pressure_inhg = pressure_hpa * 0.029529983071
        # Convert hPa to inches of mercury.
        lat = self.data.get("latitude")
        # Get GPS latitude.
        lon = self.data.get("longitude")
        # Get GPS longitude.
        sats = self.data.get("satellites")
        # Get number of GPS satellites in view.
        uptime = self.data.get("uptime")
        # Get device uptime in milliseconds.
        tz = self.get_timezone(lat, lon)
        # Determine the correct local timezone for the sensor.
        now = datetime.now(tz)
        # Get the current time in the sensor's local timezone.

        loc = LocationInfo("Home", "US", tz.zone, lat or 0, lon or 0)
        # Create an astral LocationInfo object for sunrise/sunset calculations.
        sun_data = sun(loc.observer, date=now.date(), tzinfo=tz)
        # Calculate all sun times for today using the astral library.

        moon_data = SunCalc.get_moon_illumination(now)
        # Get current moon illumination data using our SunCalc class.
        moon_phase_val = moon_data['phase']
        # Extract the phase value (0-1).
        illumination = moon_data['fraction'] * 100
        # Convert fraction to percentage.
        moon_icon = get_moon_icon(moon_phase_val)
        # Get the correct moon emoji.
        moon_phasename = get_moon_phasename(moon_phase_val)
        # Get the English phase name.

        moon_times = SunCalc.get_moon_times(now, lat or 0, lon or 0)
        # Get moonrise and moonset times.
        mr = moon_times.get("rise")
        # Extract moonrise (may be None).
        ms = moon_times.get("set")
        # Extract moonset (may be None).

        moon_rise_str = mr.astimezone(tz).strftime('%H:%M') if mr else "—"
        # Format moonrise time in local 24-hour clock or show dash if unknown.
        moon_set_str = ms.astimezone(tz).strftime('%H:%M') if ms else "—"
        # Format moonset time the same way.

        if "alwaysUp" in moon_times:
            # Special case: moon never sets today.
            moon_rise_str = "↑ Always up"
            moon_set_str = "↑ Always up"
        if "alwaysDown" in moon_times:
            # Special case: moon never rises today.
            moon_rise_str = "↓ Never rises"
            moon_set_str = "↓ Never sets"

        details = (
            f"\n🌡️ Temp: {tf_temp:.1f}°F / {tc:.1f}°C\n"
            # Temperature line.
            f"{dew_str}"
            # Dew point line (may be empty).
            f"💧 Humidity: {humidity:.1f}% ({abs_humidity:.1f} g/m³)\n"
            # Humidity with absolute value.
            f"🌀 Pressure: {pressure_hpa} hPa ({pressure_inhg:.2f} inHg)\n"
            # Pressure in both units.
            f"🏔️ Altitude: {altitude_ft:.1f} ft / {altitude_m:.1f} m\n\n"
            # Altitude.
            f"🌅 Sunrise (Dawn): {sun_data['sunrise'].strftime('%H:%M')} ({sun_data['dawn'].strftime('%H:%M')})\n"
            # Sunrise and dawn.
            f"☀️ Solar Noon: {sun_data['noon'].strftime('%H:%M')}\n"
            # Solar noon.
            f"🌇 Sunset (Dusk): {sun_data['sunset'].strftime('%H:%M')} ({sun_data['dusk'].strftime('%H:%M')})\n"
            # Sunset and dusk.
            f"🌝 Moonrise: {moon_rise_str}\n"
            # Moonrise.
            f"🌚 Moonset: {moon_set_str}\n"
            # Moonset.
            f"{moon_icon} {moon_phasename}: {illumination:.1f}%\n\n"
            # Moon phase with emoji and percentage.
            f"💡 Light: {self.data.get('lux'):.2f} lux\n"
            # Light level in lux.
            f"📶 WiFi: {self.data.get('rssi')} dBm\n"
            # WiFi signal strength.
            f"🌏 GPS: {lat:.5f}, {lon:.5f}\n"
            # GPS coordinates.
            f"📡 Satellites: {sats} \n"
            # Number of satellites.
            f"🕓 Timezone: {tz.zone} ({now.strftime('%Z')})\n"
            # Timezone info.
            f"🤖 Uptime: {ms_to_dhms(uptime)}\n"
            # Device uptime.
            f"✅ Updated: {now.strftime('%H:%M:%S')}"
            # Time this data was last refreshed.
        )

        self.details_label.set_markup(
            '<span size="large" weight="bold">👨🏾📢Jones Big Ass Weather Widget🌦️⛱️</span>\n' + details
        )
        # Update the menu label with all the beautiful formatted weather information using Pango markup.
        return False
        # We are done updating the UI.

    def on_details_clicked(self, menuitem):
        # Called when the user clicks the details menu item.
        """Open the sensor web dashboard when the details menu item is clicked"""
        webbrowser.open("http://192.168.1.62")
        # Opens the sensor's web interface in the default browser (note: different IP from the data endpoint).

    def calculate_absolute_humidity(self, temp_c, rh):
        # Calculates absolute humidity in grams per cubic meter using the Magnus formula.
        if temp_c is None or rh is None:
            # Guard against bad data.
            return 0.0
        svp = 6.112 * math.exp((17.67 * temp_c) / (temp_c + 243.5))
        # Saturation vapor pressure.
        return (svp * rh * 2.1674) / (273.15 + temp_c)
        # Final absolute humidity formula.

    def calculate_dew_point(self, temp_c, rh):
        # Calculates dew point temperature in Celsius using the Magnus approximation.
        if temp_c is None or rh is None or rh <= 0 or rh > 100:
            # Guard against invalid inputs.
            return None
        try:
            alpha = math.log(rh / 100.0) + (17.67 * temp_c) / (temp_c + 243.5)
            # Intermediate alpha value.
            return (243.5 * alpha) / (17.67 - alpha)
            # Final dew point formula.
        except:
            # In case of any math error (e.g., division by zero).
            return None

if __name__ == "__main__":
    # This block runs only when the script is executed directly (not imported).
    WeatherTray()
    # Create and start the weather widget.
    Gtk.main()
    # Start the GTK main event loop (keeps the tray icon alive forever).
