# Weather Station

> A DIY networked weather station built on ESP32 sensors, a Raspberry Pi (or any Linux box), and a custom web dashboard with built-in forecasting.

<!-- Add a screenshot of the dashboard here, e.g.:
![Dashboard](docs/images/dashboard.png)
-->

## What is this?

One or more weather sensors built around an ESP32 running FreeRTOS and a few cheap off-the-shelf sensors. Readings are collected by a light computing device (Raspberry Pi Zero 2 W or Linux PC), stored in a MySQL database, and displayed on the local network through a dashboard with live readings, historical charts, and a custom forecasting algorithm.

If you want to know what the weather is doing at your house **right now**, what it's been doing for the past week, and roughly what it'll do later today — all on your own hardware, with no cloud service in the loop — this is for you.

## Features

- **Live local-network dashboard** with separate indoor and outdoor readings
- **Historical charts** for temperature, humidity, pressure, dewpoint, and light over windows from 1 hour to 1 week
- **Custom forecast engine** that predicts the next 12 hours using time-of-day weighted historical readings, with tunable analysis span and recency weight
- **Sun and moon data**: sunrise, sunset, solar noon, dawn, dusk, moon phase, illumination, moonrise, moonset
- **GPS-aware** outdoor sensors with live coordinates, altitude, and satellite count
- **Linux system tray widget** that shows current temperature in the taskbar and a rich popup with dew point, absolute humidity, sun/moon sky positions, day length, GPS in DMS, and Maidenhead grid square
- **On-device OLED display** that cycles through weather, light, GPS, and system status pages
- **Multi-sensor capable** — supports indoor, outdoor, and additional indoor (e.g. basement) sensors out of the box
- **Resilient** — FreeRTOS task scheduling, WiFi auto-reconnect, retry logic with exponential backoff on the logger side

## Architecture

```
                           ┌─────────────────┐
                           │  ESP32 Outdoor  │  ← BME280, TSL2591, NEO-6M, OLED
                           │   (FreeRTOS)    │
                           │  192.168.1.60   │
                           └────────┬────────┘
                                    │ HTTP /data (JSON)
                                    ▼
┌─────────────────┐         ┌─────────────────┐         ┌─────────────────┐
│  ESP32 Indoor   │────────▶│ weatherLogger_  │────────▶│     MySQL       │
│   (FreeRTOS)    │  HTTP   │   *.py          │  INSERT │ weather_station │
└─────────────────┘         └─────────────────┘         └────────┬────────┘
                                                                 │
                                                                 │ SELECT
                                                                 ▼
                            ┌─────────────────┐         ┌─────────────────┐
                            │   Web Browser   │◀────────│ weatherProxy.py │
                            │   (dashboard)   │  HTTP   │                 │
                            └─────────────────┘         └─────────────────┘

      ┌─────────────────┐
      │   Linux Tray    │ ── reads directly from the ESP32
      │ weather_tray.py │    (bypasses the database)
      └─────────────────┘
```

## What's in this repo

| File / Folder | Purpose |
|---|---|
| `sketches/` | ESP32 Arduino sketches (one per sensor type) |
| `weatherLogger_Outdoor.py` | Polls the outdoor ESP32 and writes readings to MySQL |
| `weatherLogger_Indoor.py` | Polls the indoor ESP32 and writes readings to MySQL |
| `weatherProxy.py` | HTTP server that serves the dashboard and exposes MySQL data as CSV |
| `dashboard.html` | The main web dashboard (Chart.js + React) |
| `weatherAnalysis.js` | React component for the "Forecast & Analysis" tab |
| `weather_tray.py` | Linux system tray widget with rich weather popup |
| `installScriptUbuntu.sh` | Bootstrap script for Ubuntu installs |
| `js/` | Bundled JS libraries (Chart.js, React, SunCalc, etc.) |
| `docs/` | Setup guides for Raspberry Pi and Ubuntu Server |

## Quick start

**You'll need:**

- One or more ESP32 boards + sensors (see [parts list](#parts-list))
- A Raspberry Pi Zero 2 W or any Linux machine (Ubuntu Server recommended) to act as the collector / web server
- A WiFi network the sensors can join
- Basic comfort with breadboards, the Arduino IDE, and a Linux command line

**Rough flow:**

1. Wire up the sensors to your ESP32(s) per the [pin connections](#pin-connections) below.
2. Open the appropriate sketch in the Arduino IDE, set your WiFi credentials, and flash it. Note the assigned IP address.
3. Set up your collector machine using one of the setup guides:
   - [Raspberry Pi setup](docs/rpiSetup.md)
   - [Ubuntu Server setup](docs/ubuntuServerSetup.md)
4. Point your browser at the collector machine and the dashboard will load.
5. Optional: install `weather_tray.py` on any Linux desktop for an always-visible widget.

## Configuration

Before flashing the sketches, change the `NetworkName` and `NetworkPassword` placeholders in [the indoor sketch](sketches/jonesBigAssWeatherStation_FreeRTOS_indoor_main.ino) and [the outdoor sketch](sketches/jonesBigAssWeatherStation_FreeRTOS_outdoor.ino) to match your WiFi network.

The default outdoor sensor IP is `192.168.1.60`. If you use a different address, update it in the sketch and in the logger scripts.

## Parts list

- Raspberry Pi Zero 2 W or PC running Linux (recommend Ubuntu Server)
- ESP-32 control boards (one per sensor location)
- BME280 temp / humidity / pressure sensors
- TSL2591 light sensor (outdoor only)
- NEO-6M GPS sensor (outdoor only)
- 0.96" OLED display (optional)
- Project boxes or containers for sensors as desired

## Pin connections

Most sensor boards share the I²C bus on GPIO21 (SDA) and GPIO22 (SCL). The GPS uses Serial2.

### BME280

- VIN → ESP32 3.3V
- GND → ESP32 GND
- SCL → ESP32 GPIO22
- SDA → ESP32 GPIO21
- CSB → unconnected
- SDO → ESP32 GND

### TSL2591 (outdoor only)

- VIN → ESP32 3.3V
- GND → ESP32 GND
- SCL → ESP32 GPIO22 (shared with BME280)
- SDA → ESP32 GPIO21 (shared with BME280)
- INT → unconnected

### NEO-6M GPS (outdoor only)

- VCC → ESP32 3.3V
- GND → ESP32 GND
- TX → ESP32 GPIO16 (RX2)
- RX → ESP32 GPIO17 (TX2)

### OLED display

- VCC → ESP32 3.3V
- GND → ESP32 GND
- SCL → ESP32 GPIO22 (shared with others)
- SDA → ESP32 GPIO21 (shared with others)

## License

Released under the [MIT License](LICENSE). Use it, fork it, hack it, build a business on it — whatever you want. The only formal requirement is keeping the copyright notice in copies.
