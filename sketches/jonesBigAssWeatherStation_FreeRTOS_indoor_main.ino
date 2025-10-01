// ***** FreeRTOS
// You'll need to install the FreeRTOS library first. In the Arduino IDE:
//   Go to Tools > Manage Libraries
//   Search for "FreeRTOS"
//   Install "FreeRTOS by Richard Barry"

#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <freertos/semphr.h>
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

IPAddress ip(192, 168, 1, 61);
IPAddress gateway(192, 168, 1, 1);
IPAddress subnet(255, 255, 255, 0);
IPAddress dns(8, 8, 8, 8);

const char *ssid = "NetworkName";
const char *password = "NetworkPassword";
const char *ntpServer = "pool.ntp.org";
const long gmtOffset_sec = -25200;
const int daylightOffset_sec = 3600;

const float TEMP_OFFSET = -5.5;

// Task handles
TaskHandle_t sensorTaskHandle = NULL;
TaskHandle_t displayTaskHandle = NULL;
TaskHandle_t webServerTaskHandle = NULL;

// Mutex for shared resources
SemaphoreHandle_t i2cMutex;
SemaphoreHandle_t dataMutex;

Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);
Adafruit_BME280 bme;
WebServer server(80);

// Structure to hold sensor data
struct SensorData
{
    float temperatureC;
    float temperatureF;
    float humidity;
    float pressure;
    time_t timestamp;
} sensorData;

float celsiusToFahrenheit(float celsius)
{
    return celsius * 9.0 / 5.0 + 32.0;
}

void displayMessage(String message)
{
    xSemaphoreTake(i2cMutex, portMAX_DELAY);
    display.clearDisplay();
    display.setTextSize(2);
    display.setCursor(0, 0);
    display.println(message);
    display.display();
    xSemaphoreGive(i2cMutex);
}

void handleRoot()
{
    String html = R"html(
<!DOCTYPE html>
<html>
<head>
    <title>Jones Big Ass Master Indoor Weather Station</title>
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
    <h1>Jones Big Ass Master Indoor Weather Station</h1>
    
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
    xSemaphoreTake(dataMutex, portMAX_DELAY);
    String json = "{";
    json += "\"temperatureC\":" + String(sensorData.temperatureC) + ",";
    json += "\"temperatureF\":" + String(sensorData.temperatureF) + ",";
    json += "\"humidity\":" + String(sensorData.humidity) + ",";
    json += "\"pressure\":" + String(sensorData.pressure);
    json += "}";
    xSemaphoreGive(dataMutex);

    server.send(200, "application/json", json);
}

// Task to read sensors
void sensorTask(void *parameter)
{
    // ***** FreeRTOS
    // This line is used for precise task timing in FreeRTOS:
    //   - TickType_t is the data type for system ticks
    //   - xTaskGetTickCount() gets the current tick count when the line executes
    //   - xLastWakeTime stores this value and is used by vTaskDelayUntil() to ensure precise periodic timing
    // Example usage:
    //   TickType_t xLastWakeTime = xTaskGetTickCount();
    //   while(1) {
    //       // Task runs exactly every 10 seconds
    //       vTaskDelayUntil(&xLastWakeTime, pdMS_TO_TICKS(10000));
    //   }
    TickType_t xLastWakeTime = xTaskGetTickCount();

    // ***** FreeRTOS
    // The while(1) or infinite loop is fundamental to how RTOS tasks work. Here's why:
    //   Task Lifetime:
    //     - RTOS tasks are meant to run forever (until explicitly deleted or the system restarts)
    //     - Without the infinite loop, the task would run once and terminate
    //     - Tasks are like mini programs that need to keep running and doing their job
    //   Task Management:
    //     - The RTOS scheduler knows tasks are continuous
    //     - vTaskDelay() and vTaskDelayUntil() inside the loop let other tasks run
    //     - Without these delays, a task would hog the CPU
    while (1)
    {
        // ***** FreeRTOS
        // portMAX_DELAY is a FreeRTOS constant that means "wait indefinitely" when used with semaphores.
        // When used in xSemaphoreTake(mutex, portMAX_DELAY), the task will wait forever until it can get the mutex,
        //   rather than timing out after a specified period.
        // You can also specify a maximum wait time in ticks instead, like:
        //   xSemaphoreTake(mutex, pdMS_TO_TICKS(1000));  // Wait up to 1 second
        xSemaphoreTake(i2cMutex, portMAX_DELAY);
        xSemaphoreTake(dataMutex, portMAX_DELAY);

        // Read BME280
        sensorData.temperatureC = bme.readTemperature() + TEMP_OFFSET;
        sensorData.temperatureF = celsiusToFahrenheit(sensorData.temperatureC);
        sensorData.humidity = bme.readHumidity();
        sensorData.pressure = bme.readPressure() / 100.0F;
        time(&sensorData.timestamp);

        // Debug output
        Serial.println("\nCurrent Readings:");
        Serial.printf("Temperature: %.1f°C / %.1f°F\n",
                      sensorData.temperatureC, sensorData.temperatureF);
        Serial.printf("Humidity: %.1f%%\n", sensorData.humidity);
        Serial.printf("Pressure: %.1f hPa\n", sensorData.pressure);

        xSemaphoreGive(dataMutex);
        xSemaphoreGive(i2cMutex);

        vTaskDelayUntil(&xLastWakeTime, pdMS_TO_TICKS(5000));
    }
}

// Task to update display
void displayTask(void *parameter)
{
    TickType_t xLastWakeTime = xTaskGetTickCount();

    while (1)
    {
        xSemaphoreTake(i2cMutex, portMAX_DELAY);
        xSemaphoreTake(dataMutex, portMAX_DELAY);

        display.clearDisplay();
        display.setTextSize(1);
        display.setCursor(0, 0);
        display.print("Temp: ");
        display.print(sensorData.temperatureC, 1);
        display.println("C");
        display.print("Hum:  ");
        display.print(sensorData.humidity, 1);
        display.println("%");
        display.print("Press:");
        display.print(sensorData.pressure, 1);
        display.println("hPa");
        display.display();

        xSemaphoreGive(dataMutex);
        xSemaphoreGive(i2cMutex);

        vTaskDelayUntil(&xLastWakeTime, pdMS_TO_TICKS(10000));
    }
}

// Task to handle web server
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
    delay(1000);

    Serial.println("\n\nStarting Weather Station...");

    // ***** FreeRTOS
    // Create mutexes
    i2cMutex = xSemaphoreCreateMutex();
    dataMutex = xSemaphoreCreateMutex();

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
    server.begin();

    Serial.println("HTTP server started");

    // ***** FreeRTOS
    // Create RTOS tasks
    // NOTES:
    //    By default, ESP32 Arduino framework creates the setup() and loop()
    //    tasks on Core 1, while Core 0 handles WiFi/BT.
    //
    //    sensorTaskHandle is a pointer (TaskHandle_t type) that stores a reference to the sensor task after it's created. It's useful for:
    //      - Task management (suspend/resume/delete)
    //      - Changing priorities
    //      - Checking task status
    //      - Memory monitoring
    // EXAMPLE:
    //    xTaskCreate(
    //        sensorTask,        // Task function
    //        "SensorTask",      // Name for debugging
    //        4096,              // Stack size (bytes)
    //        NULL,              // Parameter to pass
    //        2,                 // Priority (higher number = higher priority)
    //        &sensorTaskHandle, // Task handle
    //        1                  // Optional: Core ID (0 or 1).
    //    );
    xTaskCreate(sensorTask, "SensorTask", 4096, NULL, 2, &sensorTaskHandle);
    xTaskCreate(displayTask, "DisplayTask", 2048, NULL, 1, &displayTaskHandle);
    xTaskCreate(webServerTask, "WebServerTask", 4096, NULL, 3, &webServerTaskHandle);
}

void loop()
{
    // ***** FreeRTOS
    // Empty - tasks handle everything
    // vTaskDelete(NULL); in the loop() function deletes the currently running task.
    //   Since NULL is passed, it deletes itself.
    //   We use this because loop() is no longer needed after RTOS tasks are created,
    //     everything is handled by the tasks we created.
    //   Without this, the loop() task would unnecessarily consume resources.
    vTaskDelete(NULL);
}