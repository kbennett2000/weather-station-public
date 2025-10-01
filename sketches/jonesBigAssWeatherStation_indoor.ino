#include <Wire.h>
#include <Adafruit_BME280.h>
#include <WiFi.h>
#include <WebServer.h>
#include <Adafruit_SSD1306.h>
#include "time.h"

#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
#define OLED_RESET -1
#define SCREEN_ADDRESS 0x3C

IPAddress ip(192, 168, 1, 61);      // Static IP
IPAddress gateway(192, 168, 1, 1);  // Router IP
IPAddress subnet(255, 255, 255, 0); // Subnet mask
IPAddress dns(8, 8, 8, 8);          // DNS (Google)

const char *ssid = "NetworkName";
const char *password = "NetworkPassword";
const char *ntpServer = "pool.ntp.org";
const long gmtOffset_sec = -25200;   // GMT-7 for Mountain Time
const int daylightOffset_sec = 3600; // 1 hour DST

const float TEMP_OFFSET = -5.5; // Temperature correction in Celsius

Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);
Adafruit_BME280 bme;
WebServer server(80);

struct Reading
{
  float tempC;
  float tempF;
  float humidity;
  float pressure;
  unsigned long timestamp;
  time_t realtime;
};

const unsigned long READING_INTERVAL = 60000; // 1 minute

float celsiusToFahrenheit(float celsius)
{
  return celsius * 9.0 / 5.0 + 32.0;
}

void handleRoot()
{
  String html = R"html(
<!DOCTYPE html>
<html>
<head>
    <title>Jones Big Ass Indoor Weather Station</title>
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
        .historical {
            font-size: 16px;
            color: #666;
            margin-top: 10px;
            padding: 5px 0;
            border-top: 1px solid #eee;
        }
        .timestamp {
            font-size: 14px;
            color: #999;
            text-align: right;
            margin-top: 10px;
        }
    </style>
    <script>
        function updateData() {
            fetch('/data')
                .then(response => response.json())
                .then(data => {
                    document.getElementById('tempC').textContent = data.temperatureC.toFixed(1) + '°C';
                    document.getElementById('tempF').textContent = data.temperatureF.toFixed(1) + '°F';
                    document.getElementById('humidity').textContent = data.humidity.toFixed(1) + '%';
                    document.getElementById('pressure').textContent = data.pressure.toFixed(1) + ' hPa';

                    document.getElementById('timestamp').textContent = new Date().toLocaleString();
                });
        }
        
        setInterval(updateData, 5000);
        updateData();
    </script>
</head>
<body>
    <h1>Jones Big Ass Indoor Weather Station</h1>
    
    <div class="card">
        <div class="label">Temperature</div>
        <div class="value" id="tempC">--°C</div>
        <div class="value" id="tempF">--°F</div>
        <div class="timestamp">Last updated: <span id="timestamp">--</span></div>
    </div>
    
    <div class="card">
        <div class="label">Humidity</div>
        <div class="value" id="humidity">--%</div>
    </div>
    
    <div class="card">
        <div class="label">Pressure</div>
        <div class="value" id="pressure">-- hPa</div>
    </div>

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

  String json = "{";
  json += "\"temperatureC\":" + String(temperatureC) + ",";
  json += "\"temperatureF\":" + String(temperatureF) + ",";
  json += "\"humidity\":" + String(humidity) + ",";
  json += "\"pressure\":" + String(pressure); // Removed trailing comma
  json += "}";

  server.send(200, "application/json", json);
}

void displayMessage(String message)
{
  display.clearDisplay();
  display.setTextSize(2);
  display.setCursor(0, 0);
  display.println(message);
  display.display();
}

void setup()
{
  Serial.begin(115200);
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

  displayMessage("Connecting\nto WiFi...");

  WiFi.begin(ssid, password);
  WiFi.config(ip, gateway, subnet, dns);

  while (WiFi.status() != WL_CONNECTED)
  {
    delay(500);
    Serial.print(".");
  }

  // Set timezone and sync NTP
  configTime(gmtOffset_sec, daylightOffset_sec, ntpServer);

  // Wait for time sync
  struct tm timeinfo;
  if (!getLocalTime(&timeinfo))
  {
    Serial.println("Failed to obtain time");
    return;
  }

  Serial.print("Current time: ");
  Serial.println(&timeinfo, "%Y-%m-%d %H:%M:%S");

  Serial.println("\nWiFi Connected!");
  Serial.print("IP Address: ");
  Serial.println(WiFi.localIP());

  display.clearDisplay();
  display.setCursor(0, 0);
  display.println("Connected!");
  display.println("IP Address:");
  display.println(WiFi.localIP().toString());
  display.display();

  server.on("/", handleRoot);
  server.on("/data", handleData);
  // server.on("/raw", handleRawData);
  // server.on("/rawjson", handleRawJson);
  // server.on("/csv", handleCSV);
  server.begin();

  float tempC = bme.readTemperature();
  float tempF = celsiusToFahrenheit(tempC);
  float humidity = bme.readHumidity();
  float pressure = bme.readPressure() / 100.0F;

  Serial.println("HTTP server started");
}

void loop()
{
  server.handleClient();

  static unsigned long lastPrint = 0;
  if (millis() - lastPrint >= 10000)
  {
    float temperatureC = bme.readTemperature() + TEMP_OFFSET;
    float temperatureF = celsiusToFahrenheit(temperatureC);
    float humidity = bme.readHumidity();
    float pressure = bme.readPressure() / 100.0F;

    Serial.println("\nCurrent Readings:");
    Serial.print("Temperature: ");
    Serial.print(temperatureC);
    Serial.print(" °C / ");
    Serial.print(temperatureF);
    Serial.println(" °F");
    Serial.print("Humidity: ");
    Serial.print(humidity);
    Serial.println(" %");
    Serial.print("Pressure: ");
    Serial.print(pressure);
    Serial.println(" hPa");

    lastPrint = millis();

    // Update display with current readings
    display.clearDisplay();
    display.setTextSize(1);
    display.setCursor(0, 0);
    display.print("Temp: ");
    display.print(temperatureC, 1);
    display.println("C");
    display.print("Hum:  ");
    display.print(humidity, 1);
    display.println("%");
    display.print("Press:");
    display.print(pressure, 1);
    display.println("hPa");
    display.display();
  }
}