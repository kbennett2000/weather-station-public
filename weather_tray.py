#!/usr/bin/env python3

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('AppIndicator3', '0.1')
from gi.repository import Gtk, AppIndicator3, GLib
import requests
import threading
import time

class WeatherTray:
    def __init__(self):
        # APPLICATION_STATUS + empty icon = much less clutter
        self.indicator = AppIndicator3.Indicator.new(
            "home-weather",
            "",                                      # no gear icon
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS
        )
        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        
        # This is what puts the live temperature right in the top bar
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
        self.update()  # first update right now

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

        # Live temp in top bar
        self.indicator.set_label(f"🌡️ {tf:.1f}°F", "home-weather-label")

        # Dropdown details
        details = (
            f"🌡️ {tf:.1f}°F / {tc:.1f}°C\n"
            f"Humidity: {self.data.get('humidity'):.1f}%\n"
            f"Pressure: {self.data.get('pressure')} hPa\n"
            f"Light: {self.data.get('lux'):.2f} lux\n"
            f"WiFi: {self.data.get('rssi')} dBm\n"
            f"Altitude: {self.data.get('altitude'):.1f} m\n"
            f"GPS: {self.data.get('latitude')}, {self.data.get('longitude')}\n"
            f"Updated: {time.strftime('%I:%M:%S %p')}"
        )
        self.details_item.set_label(details)
        return False

if __name__ == "__main__":
    WeatherTray()
    Gtk.main()
