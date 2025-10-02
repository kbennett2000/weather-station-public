#!/bin/bash

# Installation Script for Weather Reporting System on Ubuntu Server 24.04 LTS
# Run as sudo ./install-weather-station.sh

# Exit on error
set -e

# Function to prompt for input
prompt() {
    read -p "$1: " input
    echo "$input"
}

# Step 1: Update the System and Install Dependencies
echo "Updating system and installing dependencies..."
apt update
apt upgrade -y
apt install python3 python3-venv mariadb-server iptables-persistent git -y

# Step 2: Set a Static IP
echo "Configuring static IP with NetworkManager..."
apt install network-manager -y  # Install if not present
systemctl start NetworkManager
systemctl enable NetworkManager

# Prompt for connection name and details
echo "Run 'nmcli con show' to find your connection name (e.g., 'Wired connection 1')."
connection_name=$(prompt "Enter connection name")
ip_address=$(prompt "Enter static IP (e.g., 192.168.1.62/24)")
gateway=$(prompt "Enter gateway (e.g., 192.168.1.1)")
dns=$(prompt "Enter DNS servers (e.g., '192.168.1.1 8.8.8.8')")

nmcli con mod "$connection_name" ipv4.method manual ipv4.addresses "$ip_address" ipv4.gateway "$gateway" ipv4.dns "$dns"
nmcli con up "$connection_name"

echo "Static IP configured. Verify with 'ip addr show'."

# Step 3: Clone the Repository
cd ~
git clone https://github.com/kbennett2000/weather-station-public.git
cd weather-station

# Step 4: Set Up MariaDB Database
echo "Securing MariaDB..."
mysql_secure_installation  # This is interactive; follow prompts

db_password=$(prompt "Enter a secure password for 'weatheruser' (used for database)")

mysql -u root -p <<EOF
CREATE DATABASE weather_station;
CREATE USER 'weatheruser'@'localhost' IDENTIFIED BY '$db_password';
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
EOF

systemctl start mariadb
systemctl enable mariadb

echo "Database set up. Password: $db_password (save this securely)."

# Step 5: Set Up Virtual Environment and Dependencies
python3 -m venv ~/weather-station/venv
source ~/weather-station/venv/bin/activate
pip install mysql-connector-python requests
deactivate

# Step 6: Configure Scripts
echo "Configuring scripts with database password..."
sed -i "s/'password': 'password'/'password': '$db_password'/g" ~/weather-station/weatherProxy.py
sed -i "s/'password': 'password'/'password': '$db_password'/g" ~/weather-station/weatherLogger_Indoor.py
sed -i "s/'password': 'password'/'password': '$db_password'/g" ~/weather-station/weatherLogger_Outdoor.py

# Ensure port 8000 in weatherProxy.py (add check or force set)
sed -i "s/HTTPServer(('0.0.0.0', 80), ProxyHandler)/HTTPServer(('0.0.0.0', 8000), ProxyHandler)/g" ~/weather-station/weatherProxy.py

# Step 7: Test Scripts Manually (script will guide, but manual test required)
echo "Manual test: Activate venv with 'source ~/weather-station/venv/bin/activate', then run 'python ~/weather-station/weatherProxy.py' and browse to http://<server-ip>:8000. Ctrl+C to stop. Deactivate with 'deactivate'."
echo "Repeat for loggers: python ~/weather-station/weatherLogger_Indoor.py, etc. Press Enter when done testing."
read -p ""

# Step 8: Set Up Port Forwarding (80 to 8000)
interface=$(prompt "Enter your network interface (e.g., eth0 from 'ip link show')")
iptables -t nat -A PREROUTING -i "$interface" -p tcp --dport 80 -j REDIRECT --to-port 8000
mkdir -p /etc/iptables
iptables-save | tee /etc/iptables/rules.v4

cat <<EOF > /etc/systemd/system/iptables-restore.service
[Unit]
Description=Restore iptables rules
After=network.target

[Service]
ExecStart=/usr/sbin/iptables-restore /etc/iptables/rules.v4
Type=oneshot
RemainAfterExit=true

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable iptables-restore.service
systemctl start iptables-restore.service

# Step 9: Set Up Systemd Services
cat <<EOF > /etc/systemd/system/weather-dashboard.service
[Unit]
Description=Weather Dashboard Server
After=network.target mariadb.service

[Service]
ExecStart=/home/$(whoami)/weather-station/venv/bin/python /home/$(whoami)/weather-station/weatherProxy.py
WorkingDirectory=/home/$(whoami)/weather-station
Restart=always
User=$(whoami)

[Install]
WantedBy=multi-user.target
EOF

cat <<EOF > /etc/systemd/system/indoor-weather.service
[Unit]
Description=Indoor Weather Data Logger
After=network.target mariadb.service

[Service]
ExecStart=/home/$(whoami)/weather-station/venv/bin/python /home/$(whoami)/weather-station/weatherLogger_Indoor.py
WorkingDirectory=/home/$(whoami)/weather-station
Restart=always
User=$(whoami)

[Install]
WantedBy=multi-user.target
EOF

cat <<EOF > /etc/systemd/system/outdoor-weather.service
[Unit]
Description=Outdoor Weather Data Logger
After=network.target mariadb.service

[Service]
ExecStart=/home/$(whoami)/weather-station/venv/bin/python /home/$(whoami)/weather-station/weatherLogger_Outdoor.py
WorkingDirectory=/home/$(whoami)/weather-station
Restart=always
User=$(whoami)

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable weather-dashboard.service indoor-weather.service outdoor-weather.service
systemctl start weather-dashboard.service indoor-weather.service outdoor-weather.service

# Step 10: Firewall Configuration (Optional)
echo "Enabling UFW (firewall). This will allow SSH, 80, and 8000."
ufw allow ssh
ufw allow 80
ufw allow 8000
ufw --force enable
ufw reload

# Step 11: Verification
echo "Installation complete! Rebooting in 10 seconds (Ctrl+C to cancel)."
sleep 10
reboot

# After reboot, verify with:
# sudo systemctl status weather-dashboard.service
# sudo iptables -t nat -L -v -n
# Browse to http://<server-ip>
