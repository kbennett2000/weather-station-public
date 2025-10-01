# Setup Instructions for Raspberry Pi Zero W

## Step 1: Flash the SD Card

### 1. Download Raspberry Pi OS Lite:

- Get the latest 32-bit Lite version from raspberrypi.com/software/operating-systems/.

### 2. Install Raspberry Pi Imager:

- Download and install from raspberrypi.com/software/.

### 3. Flash the Image:

- Insert the SD card into your computer.
- Open Raspberry Pi Imager:
  - Choose “Raspberry Pi OS Lite (32-bit)”.
  - Select your SD card.
  - Click “Next”, then “Edit Settings”:
    - Hostname: weatherproxy.
    - Enable SSH: Check “Enable SSH”, set username pi, and a password.
    - Configure Wi-Fi: Enter your SSID and password.
  - Write the image to the SD card.

## Step 2: Initial Boot and Update

### 1. Boot the Pi:

- Insert the SD card into the Pi Zero W and power it on.

### 2. SSH In:

From your computer:

```bash
ssh pi@weatherproxy.local
```

### 3. Update the System:

```bash
sudo apt update
```

```bash
sudo apt upgrade -y
```

## Step 3: Set Static IP with NetworkManager

- Your fresh install uses `NetworkManager` for networking (not `dhcpcd`).

### 1. List Connections:

```bash
nmcli con show
```

Output example:

```
NAME           UUID                                  TYPE      DEVICE
preconfigured  38e909dd-478d-4c80-8782-7c9fab72f5d5  wifi      wlan0
lo             68c8f2ec-03d5-4886-8291-bab3638810a3  loopback  lo
```

Note the NAME (e.g., `preconfigured`).

### 2. Set Static IP:

```bash
sudo nmcli con mod preconfigured ipv4.method manual ipv4.addresses 192.168.1.62/24 ipv4.gateway 192.168.1.1 ipv4.dns "192.168.1.1 8.8.8.8"
```

```bash
sudo nmcli con up preconfigured
```

(SSH may disconnect—reconnect to `pi@192.168.1.62`)

### 3. Verify:

```bash
ip addr show wlan0
```

Look for `inet 192.168.1.62/24`.

```bash
ping 192.168.1.1
```

```bash
ping 8.8.8.8
```

Ensure both respond.

### 4. Test Persistence:

```bash
sudo reboot
```

SSH back in (`ssh pi@192.168.1.62`) and recheck:

```bash
ip addr show wlan0
```

## Step 4: Install Weather Station Application

### Prepare the Environment

#### 1. Install Dependencies:

```bash
sudo apt update
```

```bash
sudo apt install python3-pip mariadb-server -y
```

```bash
pip3 install requests mysql-connector-python --break-system-packages
```

#### 2. Create Directory:

```bash
mkdir ~/weather_station
```

```bash
cd ~/weather_station
```

### Set Up MySQL Database

#### 1. Secure MySQL Installation:

```bash
sudo mysql_secure_installation
```

- Follow the prompts (set a root password, answer 'Y' to all security questions).

#### 2. Create Database and User:

```bash
sudo mysql
```

In the MySQL prompt:

```sql
CREATE DATABASE weather_station;
CREATE USER 'weatheruser'@'localhost' IDENTIFIED BY 'your_secure_password';
GRANT ALL PRIVILEGES ON weather_station.* TO 'weatheruser'@'localhost';
FLUSH PRIVILEGES;

USE weather_station;

CREATE TABLE indoor_weather (
    id INT AUTO_INCREMENT PRIMARY KEY,
    timestamp DATETIME,
    temperatureC FLOAT,
    temperatureF FLOAT,
    humidity FLOAT,
    pressure FLOAT,
    INDEX idx_timestamp (timestamp)
);

CREATE TABLE outdoor_weather (
    id INT AUTO_INCREMENT PRIMARY KEY,
    timestamp DATETIME,
    temperatureC FLOAT,
    temperatureF FLOAT,
    humidity FLOAT,
    pressure FLOAT,
    lux FLOAT,
    ir FLOAT,
    visible FLOAT,
    full FLOAT,
    latitude FLOAT,
    longitude FLOAT,
    altitude FLOAT,
    speed FLOAT,
    course FLOAT,
    satellites INT,
    tempOffset FLOAT,
    rssi INT,
    uptime BIGINT,
    freeHeap INT,
    INDEX idx_timestamp (timestamp)
);

EXIT;
```

### Transfer Files

#### 1. From your computer, copy the scripts and dashboard files:

```bash
scp *.py dashboard.html *.js pi@192.168.1.62:~/weather_station/
```

### Indoor Data Logger (indoor.py)

Logs data from http://192.168.1.61/data to weather_data_indoor.csv.

#### 1. Test:

```bash
python3 weatherLogger_Indoor.py
```

Ctrl+C to stop.

```bash
mysql -u weatheruser -p'password' -e "SELECT * FROM weather_station.indoor_weather LIMIT 5"
```

#### 2. Create Service:

```bash
sudo nano /etc/systemd/system/indoor-weather.service
```

Add:

```
[Unit]
Description=Indoor Weather Data Logger
After=network.target

[Service]
ExecStart=/usr/bin/python3 /home/pi/weather_station/indoor.py
WorkingDirectory=/home/pi/weather_station
Restart=always
User=pi

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl enable indoor-weather.service
```

```bash
sudo systemctl start indoor-weather.service
```

### Outdoor Data Logger (outdoor.py)

Logs data from http://192.168.1.60/data to weather_data_outdoor.csv.

#### 1. Test:

```bash
python3 outdoor.py
```

Ctrl+C to stop.

```bash
cat weather_data_outdoor.csv
```

```bash
cat weather_logger.log
```

#### 2. Create Service:

```bash
sudo nano /etc/systemd/system/outdoor-weather.service
```

Add:

```
[Unit]
Description=Outdoor Weather Data Logger
After=network.target

[Service]
ExecStart=/usr/bin/python3 /home/pi/weather_station/outdoor.py
WorkingDirectory=/home/pi/weather_station
Restart=always
User=pi

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl enable outdoor-weather.service
```

```bash
sudo systemctl start outdoor-weather.service
```

### Dashboard Server (proxy.py)

Serves `dashboard.html` and proxies requests.

#### 1. Stop Existing Service (if running on port 8000):

```bash
sudo systemctl stop weather-dashboard.service
```

#### 2. Modify to Use Port 80:

```bash
nano ~/weather_station/proxy.py
```

Change:

```python
server = HTTPServer(('0.0.0.0', 8000), ProxyHandler)
```

to:

```python
server = HTTPServer(('0.0.0.0', 80), ProxyHandler)
```

#### 3. Create/Update Service:

```bash
sudo nano /etc/systemd/system/weather-dashboard.service
```

Add:

```
[Unit]
Description=Weather Dashboard Server
After=network.target

[Service]
ExecStart=/usr/bin/python3 /home/pi/weather_station/proxy.py
WorkingDirectory=/home/pi/weather_station
Restart=always

[Install]
WantedBy=multi-user.target
```

(No `User=pi` — port 80 requires root.)

Enable and start:

```bash
sudo systemctl daemon-reload
```

```bash
sudo systemctl enable weather-dashboard.service
```

```bash
sudo systemctl start weather-dashboard.service
```

#### 4. Verify:

```bash
sudo systemctl status weather-dashboard.service
```

Browse `http://192.168.1.62` from another device—should show the dashboard.

## Step 5: Map `http://weather` on Windows 10

### 1. Edit Hosts File:

- Open Notepad as Administrator (Win + S, “Notepad”, right-click, “Run as administrator”).
- File > Open > `C:\Windows\System32\drivers\etc\hosts`
- Change “Text Documents” to “All Files”.
- Add at the bottom:

```
192.168.1.62    weather
```

- Save and close.

### 2. Test:

- In a browser: `http://weather`
- Command Prompt:

```cmd
ping weather
```

- Should resolve to 192.168.1.62.

## Step 6: Final Verification

- Services:

```bash
sudo systemctl status indoor-weather.service
sudo systemctl status outdoor-weather.service
sudo systemctl status weather-dashboard.service
```

- Data:

```bash
ls -l ~/weather_station/
```

- Check database growth.

```bash
mysql -u weatheruser -p'password' -e "SELECT COUNT(*) FROM weather_station.indoor_weather"
```

```bash
mysql -u weatheruser -p'password' -e "SELECT COUNT(*) FROM weather_station.outdoor_weather"
```

Dashboard: `http://weather` loads the dashboard.

## Troubleshooting

- NetworkManager Fails: Re-run `nmcli` commands or check `systemctl status NetworkManager`
- Port 80 Conflict: `sudo netstat -tulnp | grep :80` — stop any conflicting service (e.g., `sudo systemctl stop apache2`).
- Scripts Fail: Check logs (`weather_logger.log`) or CSV files for clues.
