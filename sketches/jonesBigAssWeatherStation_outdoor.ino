#include <Wire.h>
#include <Adafruit_BME280.h>
#include <Adafruit_TSL2591.h>
#include <TinyGPS.h>
#include <WiFi.h>
#include <WebServer.h>
#include <Adafruit_SSD1306.h>
#include "time.h"

#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
#define OLED_RESET -1
#define SCREEN_ADDRESS 0x3C

#define GPS_RX 16
#define GPS_TX 17

IPAddress ip(192, 168, 1, 60);
IPAddress gateway(192, 168, 1, 1);
IPAddress subnet(255, 255, 255, 0);
IPAddress dns(8, 8, 8, 8);

const char *ssid = "NetworkName";
const char *password = "NetworkPassword";
const char *ntpServer = "pool.ntp.org";
const long gmtOffset_sec = -25200;
const int daylightOffset_sec = 3600;

float TEMP_OFFSET = 0;

Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);
Adafruit_BME280 bme;
Adafruit_TSL2591 tsl = Adafruit_TSL2591(2591);
TinyGPS gps;

WebServer server(80);

void handleSetOffset()
{
  if (server.hasArg("value"))
  {
    TEMP_OFFSET = server.arg("value").toFloat();
    server.send(200, "text/plain", "OK");
  }
  else
  {
    server.send(400, "text/plain", "Missing value");
  }
}

void displayMessage(String message)
{
  display.clearDisplay();
  display.setTextSize(2);
  display.setCursor(0, 0);
  display.println(message);
  display.display();
}

float celsiusToFahrenheit(float celsius)
{
  return celsius * 9.0 / 5.0 + 32.0;
}

void configureTSL2591()
{
  tsl.setGain(TSL2591_GAIN_LOW);
  tsl.setTiming(TSL2591_INTEGRATIONTIME_100MS);
}

void handleRoot()
{
  String html = R"html(
<!DOCTYPE html>
<html>
<head>
    <title>Jones Big Ass Outdoor Weather Station</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta charset="UTF-8">
    <style>
        body { 
            font-family: Arial, sans-serif; 
            margin: 20px;
            background-color: #f0f0f0;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
        }
        h1 {
            color: #333;
            text-align: center;
            margin-bottom: 30px;
        }
        .card {
            background-color: white;
            border-radius: 8px;
            padding: 20px;
            margin: 20px 0;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .value {
            font-size: 28px;
            font-weight: bold;
            color: #2196F3;
            margin: 10px 0;
        }
        .label {
            color: #666;
            font-size: 18px;
            margin-bottom: 10px;
            font-weight: 500;
        }
        .timestamp {
            font-size: 14px;
            color: #999;
            text-align: right;
            margin-top: 10px;
        }
    </style>
    <script>
        function setOffset() {
            const value = document.getElementById('tempOffset').value;
            fetch('/setOffset?value=' + value)
                .then(response => {
                    if(response.ok) {
                        alert('Offset updated');
                        updateData();
                    }
                });
        }
        function updateData() {
            fetch('/data')
                .then(response => response.json())
                .then(data => {
                    document.getElementById('tempC').textContent = data.temperatureC.toFixed(1) + '°C';
                    document.getElementById('tempF').textContent = data.temperatureF.toFixed(1) + '°F';
                    document.getElementById('humidity').textContent = data.humidity.toFixed(1) + '%';
                    document.getElementById('pressure').textContent = data.pressure.toFixed(1) + ' hPa';
                    document.getElementById('lux').textContent = data.lux.toFixed(1) + ' lux';
                    document.getElementById('ir').textContent = data.ir + ' IR';
                    document.getElementById('visible').textContent = data.visible + ' Visible';
                    document.getElementById('lat').textContent = data.latitude.toFixed(6) + '°';
                    document.getElementById('lon').textContent = data.longitude.toFixed(6) + '°';
                    document.getElementById('alt').textContent = data.altitude.toFixed(1) + ' m';
                    document.getElementById('spd').textContent = data.speed.toFixed(1) + ' km/h';
                    document.getElementById('satellites').textContent = data.satellites;                    
                    document.getElementById('timestamp').textContent = new Date().toLocaleString();
                    document.getElementById('tempOffset').value = data.tempOffset;
                });
        }
        
        setInterval(updateData, 5000);
        updateData();
    </script>
</head>
<body>
    <h1>Jones Big Ass Outdoor Weather Station</h1>
    
    <div class="card">
        <div class="label">Temperature</div>
        <div class="value" id="tempC">--°C</div>
        <div class="value" id="tempF">--°F</div>
    </div>
    
    <div class="card">
        <div class="label">Humidity</div>
        <div class="value" id="humidity">--%</div>
    </div>
    
    <div class="card">
        <div class="label">Pressure</div>
        <div class="value" id="pressure">-- hPa</div>
    </div>

    <div class="card">
        <div class="label">Light</div>
        <div class="value" id="lux">-- lux</div>
        <div class="value" id="ir">-- IR</div>
        <div class="value" id="visible">-- Visible</div>
    </div>

    <div class="card">
        <div class="label">Location</div>
        <div class="value" id="lat">--°</div>
        <div class="value" id="lon">--°</div>
        <div class="value" id="alt">-- m</div>
        <div class="value" id="spd">-- km/h</div>
        <div class="value">Satellites: <span id="satellites">--</span></div>
    </div>

    <div class="card">
      <div class="label">Temperature Offset</div>
      <div class="value">
          <input type="number" id="tempOffset" step="0.1" style="width: 100px;">
          <button onclick="setOffset()">Update</button>
      </div>
    </div>

    <div class="timestamp">Last updated: <span id="timestamp">--</span></div>
</body>
</html>
)html";
  server.send(200, "text/html", html);
}

void handleData()
{
  float temperatureC = bme.readTemperature() + TEMP_OFFSET;
  float temperatureF = celsiusToFahrenheit(temperatureC);
  float humidity = bme.readHumidity();
  float pressure = bme.readPressure() / 100.0F;

  // Get light sensor readings
  uint32_t lum = tsl.getFullLuminosity();
  uint16_t ir = lum >> 16;
  uint16_t full = lum & 0xFFFF;
  uint16_t visible = full - ir;
  float lux = tsl.calculateLux(full, ir);

  // GPS variables
  float flat, flon;
  unsigned long age;
  gps.f_get_position(&flat, &flon, &age);

  String json = "{";
  json += "\"temperatureC\":" + String(temperatureC) + ",";
  json += "\"temperatureF\":" + String(temperatureF) + ",";
  json += "\"humidity\":" + String(humidity) + ",";
  json += "\"pressure\":" + String(pressure) + ",";
  json += "\"lux\":" + (isnan(lux) ? "0" : String(lux)) + ",";
  json += "\"ir\":" + String(ir) + ",";
  json += "\"visible\":" + String(visible) + ",";
  json += "\"full\":" + String(full) + ",";
  json += "\"latitude\":" + String(flat, 6) + ",";
  json += "\"longitude\":" + String(flon, 6) + ",";
  json += "\"altitude\":" + String(gps.altitude() / 100.0) + ",";
  json += "\"speed\":" + String(gps.speed() * 0.0185) + ",";
  json += "\"course\":" + String(gps.course() / 100.0) + ",";
  json += "\"satellites\":" + String(gps.satellites()) + ",";
  json += "\"tempOffset\":" + String(TEMP_OFFSET);
  json += "}";

  server.send(200, "application/json", json);
}

void setup()
{
  Serial.begin(115200);
  Serial2.begin(9600, SERIAL_8N1, GPS_RX, GPS_TX);
  delay(1000);

  Serial.println("\n\nStarting Weather Station...");

  Wire.begin(21, 22);
  Serial.println("I2C Initialized");

  if (!display.begin(SSD1306_SWITCHCAPVCC, SCREEN_ADDRESS))
  {
    Serial.println("SSD1306 allocation failed");
    while (1)
      delay(10);
  }
  Serial.println("Display Initialized");

  display.clearDisplay();
  display.setTextColor(WHITE);
  display.setTextSize(1);

  if (!bme.begin(0x76))
  {
    Serial.println("Could not find BME280 sensor!");
    displayMessage("BME280\nError!");
    while (1)
      delay(10);
  }
  Serial.println("BME280 Initialized");

  if (!tsl.begin())
  {
    Serial.println("Could not find TSL2591 sensor!");
    displayMessage("TSL2591\nError!");
    while (1)
      delay(10);
  }
  Serial.println("TSL2591 Initialized");
  configureTSL2591();

  displayMessage("Connecting\nto WiFi...");

  WiFi.begin(ssid, password);
  WiFi.config(ip, gateway, subnet, dns);

  while (WiFi.status() != WL_CONNECTED)
  {
    delay(500);
    Serial.print(".");
  }

  Serial.println("\nWiFi Connected!");
  Serial.print("IP Address: ");
  Serial.println(WiFi.localIP());

  server.on("/", handleRoot);
  server.on("/data", handleData);
  server.on("/setOffset", handleSetOffset);
  server.begin();

  Serial.println("HTTP server started");
}

void loop()
{
  server.handleClient();

  while (Serial2.available())
  {
    char c = Serial2.read();
    gps.encode(c);
  }

  static unsigned long lastPrint = 0;
  if (millis() - lastPrint >= 10000)
  {
    float temperatureC = bme.readTemperature() + TEMP_OFFSET;
    float temperatureF = celsiusToFahrenheit(temperatureC);
    float humidity = bme.readHumidity();
    float pressure = bme.readPressure() / 100.0F;

    uint32_t lum = tsl.getFullLuminosity();
    uint16_t ir = lum >> 16;
    uint16_t full = lum & 0xFFFF;
    float lux = tsl.calculateLux(full, ir);

    float flat, flon;
    unsigned long age;
    gps.f_get_position(&flat, &flon, &age);

    display.clearDisplay();
    display.setTextSize(1);
    display.setCursor(0, 0);

    static uint8_t displayPage = 0;
    switch (displayPage)
    {
    case 0:
      display.println("Weather:");
      display.printf("Temp: %.1fC\n", temperatureC);
      display.printf("Hum:  %.1f%%\n", humidity);
      display.printf("Press:%.1fhPa\n", pressure);
      break;
    case 1:
      display.println("Light:");
      display.printf("Lux: %.1f\n", lux);
      display.printf("IR:  %d\n", ir);
      display.printf("Vis: %d\n", full - ir);
      break;
    case 2:
      display.println("Location:");
      if (age < 5000)
      {
        display.printf("Lat: %.6f\n", flat);
        display.printf("Lon: %.6f\n", flon);
        display.printf("Alt: %.1fm\n", gps.altitude() / 100.0);
      }
      else
      {
        display.println("No GPS Fix");
      }
      break;
    }
    display.display();

    displayPage = (displayPage + 1) % 3;
    lastPrint = millis();
  }
}