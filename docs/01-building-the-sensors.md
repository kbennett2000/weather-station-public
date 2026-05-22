# 01 · Building the sensors

This is the hands-on hardware guide: parts, wiring, flashing. If you've never built an ESP32 project before, you should be able to work through this in an afternoon. If you've never soldered, you probably won't need to — the parts list below favours pre-soldered breakouts that work with jumper wires.

When you're done, you'll have one to three ESP32 sensors on your home WiFi serving a `/data` JSON endpoint on the LAN. The next doc, [`02-install-and-configure.md`](02-install-and-configure.md), turns those endpoints into a live dashboard.

---

## What you're building

Three roles. Each is a small ESP32 board with a temperature/humidity/pressure sensor; the outdoor one adds a light sensor and a GPS module.

| Role | Sensors | Used by the dashboard for |
|---|---|---|
| **outdoor** | BME280 (T/H/P) + TSL2591 (light) + NEO-6M (GPS) | Hero panel, historical charts, polar sky plot, day arc, light panel, location panel |
| **indoor** | BME280 only | Live indoor panel |
| **basement** | BME280 only | Live basement panel (or any secondary indoor location) |

The outdoor sensor is the "main" device — it's the only one whose history is logged to SQLite, and its GPS is what the server uses to resolve your timezone, sun position, and moon phase. You can absolutely run a setup with only an outdoor sensor; indoor and basement are optional.

All three sketches use FreeRTOS for task scheduling. You don't need to know what that means — it just keeps the WiFi, sensor reads, and HTTP server from blocking each other.

---

## Parts list

Prices are rough; all are widely available on Amazon, AliExpress, Adafruit, SparkFun, and Mouser. Generic search-friendly names are used — no affiliate links.

### Outdoor sensor (one set)

| Part | Quantity | Approx price | Notes |
|---|---|---|---|
| ESP32 dev board (ESP32-WROOM-32, DEVKIT V1 style) | 1 | $8–15 | Any board with breakout headers. Look for "ESP32 38-pin." |
| BME280 breakout module | 1 | $5–10 | I²C version. Pre-soldered headers preferred. |
| TSL2591 high-dynamic-range light sensor breakout | 1 | $7–15 | Adafruit's is well-supported. |
| NEO-6M GPS module with antenna | 1 | $8–12 | The cheap blue "GY-NEO6MV2" board is fine. |
| 0.96" SSD1306 OLED display (128×64, I²C, 4-pin) | 1 (optional) | $3–8 | Status display on the sensor itself. Skip if you don't want it. |
| Jumper wires (female-female, 20 cm) | ~20 | $5 | Pre-crimped, no soldering needed. |
| Micro-USB cable | 1 | — | For power + flashing. |
| 5 V 1 A USB power supply | 1 | $5 | A phone charger works. |
| Project enclosure (weather-resistant, vented) | 1 | $10–25 | Or a sealed plastic box with a downward-facing vent. |
| Optional: solar radiation shield | 1 | $15–40 | The "Stevenson screen" thing. Prevents the sun from artificially heating your temp sensor. Cheap 3D-printed versions exist on Thingiverse. |

**Why a radiation shield matters:** direct sunlight on a BME280 will read 20-30°F higher than ambient air temperature. If your outdoor sensor will see any sun at all, you need either a shield or a deeply shaded mounting location.

### Indoor / basement sensor (one set per location)

| Part | Quantity | Approx price |
|---|---|---|
| ESP32 dev board | 1 | $8–15 |
| BME280 breakout | 1 | $5–10 |
| Jumper wires | ~8 | $2 |
| Micro-USB cable + power supply | 1 each | — |
| Small enclosure | 1 | $5–15 |

Way simpler. No GPS, no light sensor, no shield — these stay indoors.

---

## Wiring

The ESP32's pin assignments are hard-coded in the sketches at [`sketches/outdoor.ino`](../sketches/outdoor.ino), [`sketches/indoor.ino`](../sketches/indoor.ino), and [`sketches/basement.ino`](../sketches/basement.ino). The wiring below matches those constants — change one and you have to change the other.

All I²C devices (BME280, TSL2591, OLED) share a single bus on GPIO 21 (SDA) and GPIO 22 (SCL). You can — and should — daisy-chain them. The GPS uses Serial2 (UART) on GPIO 16 (ESP32's RX) and GPIO 17 (ESP32's TX).

### Outdoor wiring table

```
                              ┌──────── ESP32 ────────┐
  BME280                      │                       │
    VIN ───── 3V3 ───────────┤ 3V3                   │
    GND ───── GND ───────────┤ GND                   │
    SCL ───── GPIO22 ────────┤ GPIO22 (I²C SCL)      │
    SDA ───── GPIO21 ────────┤ GPIO21 (I²C SDA)      │
    CSB ───── (leave unconn.) │                       │
    SDO ───── GND             │                       │
                              │                       │
  TSL2591                     │                       │
    VIN ───── 3V3 ───────────┤ 3V3                   │
    GND ───── GND ───────────┤ GND                   │
    SCL ───── GPIO22 ────────┤ (shared with BME280)  │
    SDA ───── GPIO21 ────────┤ (shared with BME280)  │
    INT ───── (leave unconn.) │                       │
                              │                       │
  NEO-6M GPS                  │                       │
    VCC ───── 3V3 ───────────┤ 3V3                   │
    GND ───── GND ───────────┤ GND                   │
    TX  ───── GPIO16 ────────┤ GPIO16 (Serial2 RX)   │
    RX  ───── GPIO17 ────────┤ GPIO17 (Serial2 TX)   │
                              │                       │
  OLED (optional)             │                       │
    VCC ───── 3V3 ───────────┤ 3V3                   │
    GND ───── GND ───────────┤ GND                   │
    SCL ───── GPIO22 ────────┤ (shared with BME280)  │
    SDA ───── GPIO21 ────────┤ (shared with BME280)  │
                              │                       │
    USB ───── for power + flashing                    │
                              └───────────────────────┘
```

Note the GPS wiring: the **module's** TX goes to the **ESP32's** RX (GPIO16), and the **module's** RX goes to the **ESP32's** TX (GPIO17). This always trips people up the first time.

The ESP32 only has so many 3V3 pins on the headers — most boards have one or two. You'll probably need to break each one out to a small splitter (or solder a few wires to a single pin) so all four devices can share. Same for GND.

### Indoor / basement wiring

Just the BME280:

```
  BME280                ESP32
    VIN ── 3V3 ──────── 3V3
    GND ── GND ──────── GND
    SCL ── GPIO22 ───── GPIO22 (I²C SCL)
    SDA ── GPIO21 ───── GPIO21 (I²C SDA)
    CSB ── (unconn.)
    SDO ── GND
```

That's it. Four wires plus power.

> *Photo of an assembled outdoor sensor goes here. [TODO: capture and add to `docs/images/`]*

> *Photo of an assembled indoor sensor goes here. [TODO: capture and add to `docs/images/`]*

---

## Flashing the sketches

### Set up the Arduino IDE

If you don't have the Arduino IDE yet, install the latest version from [arduino.cc/en/software](https://www.arduino.cc/en/software). Then teach it about ESP32 boards:

1. **File → Preferences → Additional Board Manager URLs** — add:
   ```
   https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
   ```
2. **Tools → Board → Boards Manager** — search "esp32" and install **esp32 by Espressif Systems** (version 2.0.x or 3.x; 3.x is what these sketches were tested against).
3. Install the libraries used by the sketches. **Tools → Manage Libraries** and install each by name:
   - **Adafruit BME280 Library** (and its dependency, Adafruit Unified Sensor)
   - **Adafruit TSL2591 Library** (outdoor only)
   - **TinyGPS** (outdoor only — the older "TinyGPS", not "TinyGPSPlus")
   - **Adafruit SSD1306** (if you're using the OLED)

### Configure WiFi credentials

Each sketch has a block near the top with the WiFi network name, password, and the device's static IP. Open the right sketch:

- Outdoor → [`sketches/outdoor.ino`](../sketches/outdoor.ino) (IP 192.168.1.60)
- Indoor → [`sketches/indoor.ino`](../sketches/indoor.ino) (IP 192.168.1.61)
- Basement → [`sketches/basement.ino`](../sketches/basement.ino) (IP 192.168.1.63)

Find the constants. They look something like:

```cpp
const char* ssid     = "YOUR_WIFI_NAME";
const char* password = "YOUR_WIFI_PASSWORD";
IPAddress ip(192, 168, 1, 60);   // change to a free address on your LAN
IPAddress gateway(192, 168, 1, 1);
IPAddress subnet(255, 255, 255, 0);
IPAddress dns(8, 8, 8, 8);
```

Edit `ssid` and `password` to match your network. If `192.168.1.x` isn't your subnet, change the `ip`, `gateway`, and `subnet` accordingly. The IP must be outside your router's DHCP range or your router will hand it out to someone else and you'll get conflicts.

> **Why static IPs?** The server polls each sensor by IP, and a sensor that wanders around the DHCP pool would break the dashboard every few hours. CLAUDE.md treats hardcoded IPs as a design choice — config provisioning is out of scope.

### Upload

1. Plug the ESP32 into your computer with the USB cable.
2. **Tools → Board → ESP32 Arduino → ESP32 Dev Module** (or your specific board variant).
3. **Tools → Port** — pick the new serial port (looks like `/dev/ttyUSB0` on Linux, `COM3+` on Windows, `/dev/cu.SLAB_USBtoUART` on macOS).
4. **Tools → Upload Speed** — 921600 is fine. If uploading fails, drop to 115200.
5. Click the **Upload** button (right arrow).

The compile takes a minute or so the first time. You'll see "Connecting...." in the bottom panel. If your board doesn't have an auto-reset circuit, you may need to hold the **BOOT** button while it says "Connecting" and release it once "Writing" starts.

### Verify

Open the serial monitor at 115200 baud. You should see something like:

```
Connecting to YOUR_WIFI_NAME....
WiFi Connected!
IP Address: 192.168.1.60
RSSI: -58 dBm
HTTP server started
Sensor Task - Free heap: 178432 bytes
```

From any computer on your LAN:

```bash
curl http://192.168.1.60/data
```

…should return JSON with the current readings. If it does, you're done with this sensor. Repeat for the other two.

---

## Mounting (outdoor)

The biggest single thing affecting outdoor temperature accuracy is shielding from direct sun. Other factors that matter, in roughly descending order:

- **Direct sun on the sensor.** A 5-minute morning sun-spot pushes temperature readings 15–25°F high. Either deeply shade the enclosure or use a radiation shield.
- **Proximity to AC compressor exhaust, dryer vents, or sun-warmed walls.** Mount at least 3–4 ft from any of these.
- **Height above ground.** Standard weather-station guidance is 4–6 ft above grass (not concrete or asphalt). Closer to the ground gets noisier; closer to roof level reads warmer.
- **GPS sky view.** The NEO-6M needs a clear view of the sky for a fix. A solid metal roof above it will keep it from ever locking. A few inches of plastic enclosure is fine.

If you only have a roof eave or covered porch available, that's fine — it solves the sun problem and usually still leaves the GPS happy.

---

## Troubleshooting

**"Connecting..........." forever during upload.** Hold BOOT while it's connecting; release when it starts writing. Some boards need this every time, some never need it.

**Serial monitor shows garbled characters.** Wrong baud rate. The sketches use 115200.

**"WiFi reconnection failed" on boot.** Wrong SSID or password, or your network is on 5 GHz (the ESP32 is 2.4 GHz only). Confirm your router exposes a 2.4 GHz SSID.

**`curl http://<ip>/data` times out.** Either the sensor isn't on WiFi yet (check serial monitor), or the static IP collides with something else on your LAN. Try `ping <ip>` first — if that fails, the device isn't reachable.

**`/data` returns `{"error":"No valid sensor data"}`.** The BME280 isn't being detected on I²C. Check the wiring; the most common mistake is swapping SDA and SCL. The serial monitor will print specific reading errors.

**`lux` is consistently `null` in the response.** TSL2591 wiring or I²C address conflict. Check that the TSL2591 LED isn't lit (which would mean an I²C bus issue) and that VIN goes to 3V3, not 5V.

**GPS `satellites` stays at 0 and `latitude` / `longitude` are `null`.** First fix can take 5–15 minutes outside under open sky. Indoors with a window-view: 30+ minutes, sometimes never. The dashboard works without GPS — it falls back to the `fallback_lat`/`fallback_lon` in `weather.toml` — but a real fix is more accurate for sun-position math.

**Sensor was working, then stopped after a few hours.** Almost always WiFi-related. The sketches include a watchdog task that reconnects every 30 s when WiFi drops. If it's still hanging after that, the BME280 may need a power cycle; try cutting power for 10 s.

---

## Next

You have one or more sensors serving JSON on your LAN. Time to set up the collector machine that polls them, logs history, and serves the dashboard:

→ [`02-install-and-configure.md`](02-install-and-configure.md)
