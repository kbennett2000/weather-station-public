# weather-station

## Description:
This project consists of one to many weather sensors based on an ESP32 control board and several cheap off-the-shelf sensors. Readings from the weather sensors are collected by a light computing device (Raspberry Pi Zero 2 W or Linux PC) and displayed on the local network as well as recorded in a MySQL database to be used for forecasting functions.

## Instructions:
- Pin connections for the ESP32 based sensors can be found below.
- Detailed setup instructions for Raspberry Pi [can be found here](docs/rpiSetup.md)
- Detailed setup instructions for Linux PC [can be found here](docs/ubuntuServerSetup.md)
- Be sure to change the `NetworkName` and `NetworkPassword` palceholders in [the Indoor sketch](sketches/jonesBigAssWeatherStation_FreeRTOS_indoor_main.ino) and [the Outdoor sketch](sketches/jonesBigAssWeatherStation_FreeRTOS_outdoor.ino) to match your network.

## ESP32 / Pi Zero W weather station parts list:
- Raspberry Pi Zero 2 W or PC running Linux (recommend Ubuntu Server)
- ESP-32 
- BME280 temp / humidity / pressure sensor
- TSL2591 light sensor (outdoor only)
- NEO-6M GPS sensor (outdoor only)
- Optional 0.96 OLED display

## ESP32 Pin Connections:
### BME280:
- VIN → ESP32 3.3V
- GND → ESP32 GND
- SCL → ESP32 GPIO22
- SDA → ESP32 GPIO21
- CSB → unconnected
- SDO → ESP32 GND

### TSL2591 (outdoor only):
- VIN → ESP32 3.3V
- GND → ESP32 GND
- SCL → ESP32 GPIO22 (shared with BME280)
- SDA → ESP32 GPIO21 (shared with BME280)
- INT → unconnected

### NEO-6M GPS (outdoor only):
- VCC → ESP32 3.3V
- GND → ESP32 GND
- TX → ESP32 GPIO16 (RX2)
- RX → ESP32 GPIO17 (TX2)

### OLED Display:
- VCC → ESP32 3.3V
- GND → ESP32 GND
- SCL → ESP32 GPIO22 (shared with others)
- SDA → ESP32 GPIO21 (shared with others)



