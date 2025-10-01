# weather-station
## ESP32 / Pi Zero W weather station
- Raspberry Pi Zero 2 W
- ESP-32 
- BME280 temp / humidity / pressure sensor
- TSL2591 light sensor (outdoor only)
- NEO-6M GPS sensor (outdoor only)
- Optional 0.96 OLED display

### ESP32 Pin Connections:
#### BME280:
- VIN → ESP32 3.3V
- GND → ESP32 GND
- SCL → ESP32 GPIO22
- SDA → ESP32 GPIO21
- CSB → unconnected
- SDO → ESP32 GND

#### TSL2591 (outdoor only):
- VIN → ESP32 3.3V
- GND → ESP32 GND
- SCL → ESP32 GPIO22 (shared with BME280)
- SDA → ESP32 GPIO21 (shared with BME280)
- INT → unconnected

#### NEO-6M GPS (outdoor only):
- VCC → ESP32 3.3V
- GND → ESP32 GND
- TX → ESP32 GPIO16 (RX2)
- RX → ESP32 GPIO17 (TX2)

#### OLED Display:
- VCC → ESP32 3.3V
- GND → ESP32 GND
- SCL → ESP32 GPIO22 (shared with others)
- SDA → ESP32 GPIO21 (shared with others)
