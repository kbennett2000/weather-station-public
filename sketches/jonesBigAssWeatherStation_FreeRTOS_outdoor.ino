#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <freertos/semphr.h>
#include "esp_task_wdt.h"
#include "esp_system.h"
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
#define WDT_TIMEOUT 30 // timeout in seconds

#define GPS_RX 16
#define GPS_TX 17

// Store boot count in RTC memory (survives reset)
RTC_DATA_ATTR int bootCount = 0;

IPAddress ip(192, 168, 1, 60);
IPAddress gateway(192, 168, 1, 1);
IPAddress subnet(255, 255, 255, 0);
IPAddress dns(8, 8, 8, 8);

const char *ssid = "NetworkName";
const char *password = "NetworkPassword";
const char *ntpServer = "pool.ntp.org";
const long gmtOffset_sec = -25200;
const int daylightOffset_sec = 3600;

// Shared variable protection
SemaphoreHandle_t i2cMutex;
SemaphoreHandle_t tempOffsetMutex;
SemaphoreHandle_t dataMutex;

// Task handles
TaskHandle_t sensorTaskHandle = NULL;
TaskHandle_t gpsTaskHandle = NULL;
TaskHandle_t displayTaskHandle = NULL;
TaskHandle_t webServerTaskHandle = NULL;
TaskHandle_t wifiWatchdogTaskHandle = NULL;

float TEMP_OFFSET = 0;

Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);
Adafruit_BME280 bme;
Adafruit_TSL2591 tsl = Adafruit_TSL2591(2591);
TinyGPS gps;
WebServer server(80);

// Structure to hold sensor data
struct SensorData
{
    float temperatureC;
    float temperatureF;
    float humidity;
    float pressure;
    uint32_t lum;
    uint16_t ir;
    uint16_t full;
    uint16_t visible;
    float lux;
    float latitude;
    float longitude;
    float altitude;
    float speed;
    float course;
    unsigned int satellites;
    unsigned long age;
    bool validData;
    long lastUpdateTime;
} sensorData;

float celsiusToFahrenheit(float celsius)
{
    return celsius * 9.0 / 5.0 + 32.0;
}

void configureTSL2591()
{
    tsl.setGain(TSL2591_GAIN_LOW);
    tsl.setTiming(TSL2591_INTEGRATIONTIME_100MS);
}

void checkWiFiConnection()
{
    if (WiFi.status() != WL_CONNECTED)
    {
        Serial.println("WiFi disconnected. Reconnecting...");
        WiFi.disconnect();
        WiFi.begin(ssid, password);
        WiFi.config(ip, gateway, subnet, dns);

        int attempts = 0;
        while (WiFi.status() != WL_CONNECTED && attempts < 20)
        {
            delay(500);
            Serial.print(".");
            attempts++;
        }

        if (WiFi.status() == WL_CONNECTED)
        {
            Serial.println("\nWiFi reconnected");
            Serial.printf("RSSI: %d dBm\n", WiFi.RSSI());
        }
        else
        {
            Serial.println("\nWiFi reconnection failed");
        }
    }
}

void handleSetOffset()
{
    if (xSemaphoreTake(tempOffsetMutex, pdMS_TO_TICKS(5000)) != pdTRUE)
    {
        server.send(503, "text/plain", "Server busy");
        return;
    }

    if (server.hasArg("value"))
    {
        TEMP_OFFSET = server.arg("value").toFloat();
        server.send(200, "text/plain", "OK");
    }
    else
    {
        server.send(400, "text/plain", "Missing value");
    }
    xSemaphoreGive(tempOffsetMutex);
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
        .status {
            font-size: 14px;
            color: #666;
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
                    if(data.error) {
                        document.getElementById('error').textContent = data.error;
                        return;
                    }
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
                    document.getElementById('rssi').textContent = data.rssi + ' dBm';
                    document.getElementById('uptime').textContent = Math.floor(data.uptime / 1000) + ' seconds';
                    document.getElementById('heap').textContent = data.freeHeap + ' bytes';                    
                    document.getElementById('timestamp').textContent = new Date().toLocaleString();
                    document.getElementById('tempOffset').value = data.tempOffset;
                    document.getElementById('error').textContent = '';
                });
        }
        
        setInterval(updateData, 5000);
        updateData();
    </script>
</head>
<body>
    <h1>Jones Big Ass Outdoor Weather Station</h1>
    
    <div id="error" style="color: red; text-align: center;"></div>
    
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

    <div class="card">
        <div class="label">System Status</div>
        <div class="status">WiFi Signal: <span id="rssi">--</span></div>
        <div class="status">Uptime: <span id="uptime">--</span></div>
        <div class="status">Free Memory: <span id="heap">--</span></div>
    </div>

    <div class="timestamp">Last updated: <span id="timestamp">--</span></div>
</body>
</html>
)html";
    server.send(200, "text/html", html);
}

void handleData()
{
    if (xSemaphoreTake(dataMutex, pdMS_TO_TICKS(5000)) != pdTRUE)
    {
        server.send(503, "text/plain", "Server busy");
        return;
    }

    String json = "{";
    if (sensorData.validData)
    {
        json += "\"temperatureC\":" + String(sensorData.temperatureC) + ",";
        json += "\"temperatureF\":" + String(sensorData.temperatureF) + ",";
        json += "\"humidity\":" + String(sensorData.humidity) + ",";
        json += "\"pressure\":" + String(sensorData.pressure) + ",";
        json += "\"lux\":" + String(sensorData.lux) + ",";
        json += "\"ir\":" + String(sensorData.ir) + ",";
        json += "\"visible\":" + String(sensorData.visible) + ",";
        json += "\"latitude\":" + String(sensorData.latitude, 6) + ",";
        json += "\"longitude\":" + String(sensorData.longitude, 6) + ",";
        json += "\"altitude\":" + String(sensorData.altitude) + ",";
        json += "\"speed\":" + String(sensorData.speed) + ",";
        json += "\"course\":" + String(sensorData.course) + ",";
        json += "\"satellites\":" + String(sensorData.satellites) + ",";
        json += "\"tempOffset\":" + String(TEMP_OFFSET) + ",";
        json += "\"rssi\":" + String(WiFi.RSSI()) + ",";
        json += "\"uptime\":" + String(millis()) + ",";
        json += "\"freeHeap\":" + String(ESP.getFreeHeap());
    }
    else
    {
        json += "\"error\":\"No valid sensor data\"";
    }
    json += "}";
    xSemaphoreGive(dataMutex);

    server.send(200, "application/json", json);
}

void sensorTask(void *parameter)
{
    TickType_t xLastWakeTime = xTaskGetTickCount();

    while (1)
    {
        // Log debug info
        Serial.printf("Sensor Task - Free heap: %d bytes\n", ESP.getFreeHeap());
        Serial.printf("WiFi RSSI: %d dBm\n", WiFi.RSSI());

        // Always acquire mutexes in the same order to prevent deadlocks
        if (xSemaphoreTake(dataMutex, pdMS_TO_TICKS(5000)) != pdTRUE)
        {
            Serial.println("Failed to acquire dataMutex");
            continue;
        }

        if (xSemaphoreTake(i2cMutex, pdMS_TO_TICKS(5000)) != pdTRUE)
        {
            xSemaphoreGive(dataMutex);
            Serial.println("Failed to acquire i2cMutex");
            continue;
        }

        if (xSemaphoreTake(tempOffsetMutex, pdMS_TO_TICKS(5000)) != pdTRUE)
        {
            xSemaphoreGive(i2cMutex);
            xSemaphoreGive(dataMutex);
            Serial.println("Failed to acquire tempOffsetMutex");
            continue;
        }

        bool success = true;

        // Read BME280
        float temp = bme.readTemperature();
        float humidity = bme.readHumidity();
        float pressure = bme.readPressure();

        if (isnan(temp) || temp < -40 || temp > 85)
        {
            Serial.println("Invalid temperature reading");
            success = false;
        }

        if (isnan(humidity) || humidity < 0 || humidity > 100)
        {
            Serial.println("Invalid humidity reading");
            success = false;
        }

        if (isnan(pressure) || pressure < 30000 || pressure > 110000)
        {
            Serial.println("Invalid pressure reading");
            success = false;
        }

        if (success)
        {
            sensorData.temperatureC = temp + TEMP_OFFSET;
            sensorData.temperatureF = celsiusToFahrenheit(sensorData.temperatureC);
            sensorData.humidity = humidity;
            sensorData.pressure = pressure / 100.0F;
        }

        // Read TSL2591
        uint32_t lum = tsl.getFullLuminosity();
        if (lum == 0xFFFFFFFF)
        {
            Serial.println("Failed to read TSL2591");
            success = false;
        }
        else
        {
            sensorData.lum = lum;
            sensorData.ir = lum >> 16;
            sensorData.full = lum & 0xFFFF;
            sensorData.visible = sensorData.full - sensorData.ir;
            sensorData.lux = tsl.calculateLux(sensorData.full, sensorData.ir);
        }

        sensorData.validData = success;
        sensorData.lastUpdateTime = millis();

        if (!success)
        {
            Serial.println("Attempting to reinitialize sensors...");
            if (!bme.begin(0x76))
            {
                Serial.println("Failed to reinitialize BME280");
            }
            if (!tsl.begin())
            {
                Serial.println("Failed to reinitialize TSL2591");
            }
            else
            {
                configureTSL2591();
            }
        }

        xSemaphoreGive(tempOffsetMutex);
        xSemaphoreGive(i2cMutex);
        xSemaphoreGive(dataMutex);

        vTaskDelayUntil(&xLastWakeTime, pdMS_TO_TICKS(5000));
    }
}

void gpsTask(void *parameter)
{
    while (1)
    {
        while (Serial2.available())
        {
            char c = Serial2.read();
            gps.encode(c);
        }

        if (xSemaphoreTake(dataMutex, pdMS_TO_TICKS(1000)) == pdTRUE)
        {
            gps.f_get_position(&sensorData.latitude, &sensorData.longitude, &sensorData.age);
            sensorData.altitude = gps.altitude() / 100.0;
            sensorData.speed = gps.speed() * 0.0185;
            sensorData.course = gps.course() / 100.0;
            sensorData.satellites = gps.satellites();
            xSemaphoreGive(dataMutex);
        }

        vTaskDelay(pdMS_TO_TICKS(100));
    }
}

void displayTask(void *parameter)
{
    uint8_t displayPage = 0;
    TickType_t xLastWakeTime = xTaskGetTickCount();

    while (1)
    {
        if (xSemaphoreTake(dataMutex, pdMS_TO_TICKS(1000)) != pdTRUE)
        {
            continue;
        }

        if (xSemaphoreTake(i2cMutex, pdMS_TO_TICKS(1000)) != pdTRUE)
        {
            xSemaphoreGive(dataMutex);
            continue;
        }

        display.clearDisplay();
        display.setTextSize(1);
        display.setCursor(0, 0);

        if (sensorData.validData)
        {
            switch (displayPage)
            {
            case 0:
                display.println("Weather:");
                display.printf("Temp: %.1fC\n", sensorData.temperatureC);
                display.printf("Hum:  %.1f%%\n", sensorData.humidity);
                display.printf("Press:%.1fhPa\n", sensorData.pressure);
                break;
            case 1:
                display.println("Light:");
                display.printf("Lux: %.1f\n", sensorData.lux);
                display.printf("IR:  %d\n", sensorData.ir);
                display.printf("Vis: %d\n", sensorData.visible);
                break;
            case 2:
                display.println("Location:");
                if (sensorData.age < 5000)
                {
                    display.printf("Lat: %.6f\n", sensorData.latitude);
                    display.printf("Lon: %.6f\n", sensorData.longitude);
                    display.printf("Alt: %.1fm\n", sensorData.altitude);
                }
                else
                {
                    display.println("No GPS Fix");
                }
                break;
            case 3:
                display.println("System:");
                display.printf("RSSI: %d dBm\n", WiFi.RSSI());
                display.printf("Heap: %d KB\n", ESP.getFreeHeap() / 1024);
                display.printf("Up: %d min\n", millis() / 60000);
                break;
            }
        }
        else
        {
            display.println("Sensor Error");
            display.println("Check Serial");
            display.println("Monitor");
            display.printf("Heap: %d KB\n", ESP.getFreeHeap() / 1024);
        }

        display.display();
        displayPage = (displayPage + 1) % 4; // Now 4 pages instead of 3

        xSemaphoreGive(i2cMutex);
        xSemaphoreGive(dataMutex);

        vTaskDelayUntil(&xLastWakeTime, pdMS_TO_TICKS(10000));
    }
}

void wifiWatchdogTask(void *parameter)
{
    while (1)
    {
        checkWiFiConnection();

        // Log system status every minute
        static unsigned long lastLog = 0;
        if (millis() - lastLog >= 60000)
        {
            Serial.printf("System Status:\n");
            Serial.printf("Uptime: %lu minutes\n", millis() / 60000);
            Serial.printf("Free Heap: %u bytes\n", ESP.getFreeHeap());
            Serial.printf("WiFi RSSI: %d dBm\n", WiFi.RSSI());
            Serial.printf("Last sensor update: %lu ms ago\n", millis() - sensorData.lastUpdateTime);
            Serial.printf("Boot count: %d\n", bootCount);
            lastLog = millis();
        }

        vTaskDelay(pdMS_TO_TICKS(10000)); // Check every 10 seconds
    }
}

void webServerTask(void *parameter)
{
    while (1)
    {
        server.handleClient();
        vTaskDelay(pdMS_TO_TICKS(10));
    }
}

void setup()
{
    Serial.begin(115200);
    Serial2.begin(9600, SERIAL_8N1, GPS_RX, GPS_TX);
    delay(1000);

    bootCount++;
    Serial.printf("\n\nStarting Weather Station... (Boot Count: %d)\n", bootCount);
    Serial.printf("Reset Reason: %d\n", esp_reset_reason());

    // Create mutexes
    i2cMutex = xSemaphoreCreateMutex();
    tempOffsetMutex = xSemaphoreCreateMutex();
    dataMutex = xSemaphoreCreateMutex();

    if (!i2cMutex || !tempOffsetMutex || !dataMutex)
    {
        Serial.println("Failed to create mutexes!");
        while (1)
            delay(1000);
    }

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

    // Initialize BME280
    int bmeRetries = 3;
    while (!bme.begin(0x76) && bmeRetries > 0)
    {
        Serial.println("Retrying BME280 initialization...");
        delay(1000);
        bmeRetries--;
    }
    if (bmeRetries == 0)
    {
        Serial.println("Could not find BME280 sensor!");
        display.clearDisplay();
        display.println("BME280\nError!");
        display.display();
        while (1)
            delay(10);
    }
    Serial.println("BME280 Initialized");

    // Initialize TSL2591
    int tslRetries = 3;
    while (!tsl.begin() && tslRetries > 0)
    {
        Serial.println("Retrying TSL2591 initialization...");
        delay(1000);
        tslRetries--;
    }
    if (tslRetries == 0)
    {
        Serial.println("Could not find TSL2591 sensor!");
        display.clearDisplay();
        display.println("TSL2591\nError!");
        display.display();
        while (1)
            delay(10);
    }
    Serial.println("TSL2591 Initialized");
    configureTSL2591();

    display.clearDisplay();
    display.println("Connecting\nto WiFi...");
    display.display();

    WiFi.begin(ssid, password);
    WiFi.config(ip, gateway, subnet, dns);

    int wifiRetries = 30;
    while (WiFi.status() != WL_CONNECTED && wifiRetries > 0)
    {
        delay(500);
        Serial.print(".");
        wifiRetries--;
    }

    if (WiFi.status() != WL_CONNECTED)
    {
        Serial.println("\nWiFi connection failed!");
        ESP.restart();
    }

    Serial.println("\nWiFi Connected!");
    Serial.printf("IP Address: %s\n", WiFi.localIP().toString().c_str());
    Serial.printf("RSSI: %d dBm\n", WiFi.RSSI());

    server.on("/", handleRoot);
    server.on("/data", handleData);
    server.on("/setOffset", handleSetOffset);
    server.begin();

    Serial.println("HTTP server started");

    // Initialize sensorData
    sensorData.validData = false;
    sensorData.lastUpdateTime = millis();

    // Create tasks with adjusted priorities and stack sizes
    xTaskCreate(sensorTask, "SensorTask", 4096, NULL, 3, &sensorTaskHandle);
    xTaskCreate(webServerTask, "WebServerTask", 4096, NULL, 2, &webServerTaskHandle);
    xTaskCreate(gpsTask, "GPSTask", 4096, NULL, 2, &gpsTaskHandle);
    xTaskCreate(displayTask, "DisplayTask", 4096, NULL, 1, &displayTaskHandle);
    xTaskCreate(wifiWatchdogTask, "WiFiWatchdog", 4096, NULL, 1, &wifiWatchdogTaskHandle);

    // Configure watchdog
    esp_task_wdt_config_t wdtConfig = {
        .timeout_ms = WDT_TIMEOUT * 1000,
        .idle_core_mask = (1 << portNUM_PROCESSORS) - 1,
        .trigger_panic = true};
    esp_task_wdt_init(&wdtConfig);
}

void loop()
{
    vTaskDelete(NULL); // Delete setup and loop task
}
