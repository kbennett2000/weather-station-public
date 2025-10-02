sudo apt update
sudo apt upgrade -y
sudo apt install python3 python3-venv mariadb-server iptables-persistent -y
sudo apt update
sudo apt install network-manager -y
sudo tee /etc/netplan/01-network-manager-all.yaml <<EOF
network:
  version: 2
  renderer: NetworkManager
EOF
sudo netplan generate
sudo netplan apply
sudo systemctl restart NetworkManager
sudo systemctl enable NetworkManager
nmcli con show
sudo nmcli con mod "Wired connection 1" ipv4.method manual ipv4.addresses 192.168.1.62/24 ipv4.gateway 192.168.1.1 ipv4.dns "192.168.1.1 8.8.8.8"
sudo nmcli con up "Wired connection 1"
ip addr show
cd ~
git clone https://github.com/kbennett2000/weather-station-public.git
cd weather-station-public
sudo mysql_secure_installation
sudo mysql -e "CREATE DATABASE weather_station; CREATE USER 'weatheruser'@'localhost' IDENTIFIED BY 'password'; GRANT ALL PRIVILEGES ON weather_station.* TO 'weatheruser'@'localhost'; FLUSH PRIVILEGES; USE weather_station; CREATE TABLE indoor_weather (id INT AUTO_INCREMENT PRIMARY KEY, timestamp DATETIME, temperatureC FLOAT, temperatureF FLOAT, humidity FLOAT, pressure FLOAT, INDEX idx_timestamp (timestamp)); CREATE TABLE outdoor_weather (id INT AUTO_INCREMENT PRIMARY KEY, timestamp DATETIME, temperatureC FLOAT, temperatureF FLOAT, humidity FLOAT, pressure FLOAT, lux FLOAT, ir FLOAT, visible FLOAT, full FLOAT, latitude FLOAT, longitude FLOAT, altitude FLOAT, speed FLOAT, course FLOAT, satellites INT, tempOffset FLOAT, rssi INT, uptime BIGINT, freeHeap INT, INDEX idx_timestamp (timestamp));"
sudo systemctl start mariadb
sudo systemctl enable mariadb
python3 -m venv ~/weather-station-public/venv



echo "********** IT MIGHT BREAK HERE **********"
pause
source ~/weather-station-public/venv/bin/activate
pip install mysql-connector-python requests
deactivate
echo "********** DID IT BREAK? **********"
pause



sudo iptables -t nat -A PREROUTING -i eth0 -p tcp --dport 80 -j REDIRECT --to-port 8000
sudo mkdir -p /etc/iptables
sudo iptables-save | sudo tee /etc/iptables/rules.v4
sudo tee /etc/systemd/system/iptables-restore.service <<EOF
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
sudo systemctl daemon-reload
sudo systemctl enable iptables-restore.service
sudo systemctl start iptables-restore.service
sudo iptables -t nat -L -v -n
sudo tee /etc/systemd/system/weather-dashboard.service <<EOF
[Unit]
Description=Weather Dashboard Server
After=network.target mariadb.service

[Service]
ExecStart=/home/kb/weather-station-public/venv/bin/python /home/kb/weather-station-public/weatherProxy.py
WorkingDirectory=/home/kb/weather-station-public
Restart=always
User=kb

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable weather-dashboard.service
sudo systemctl start weather-dashboard.service
sudo tee /etc/systemd/system/indoor-weather.service <<EOF
[Unit]
Description=Indoor Weather Service
After=network.target mariadb.service

[Service]
ExecStart=/home/kb/weather-station-public/venv/bin/python /home/kb/weather-station-public/weatherLogger_Indoor.py
WorkingDirectory=/home/kb/weather-station-public
Restart=always
User=kb

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable indoor-weather.service
sudo systemctl start indoor-weather.service
sudo tee /etc/systemd/system/outdoor-weather.service <<EOF
[Unit]
Description=Outdoor Weather Service
After=network.target mariadb.service

[Service]
ExecStart=/home/kb/weather-station-public/venv/bin/python /home/kb/weather-station-public/weatherLogger_Outdoor.py
WorkingDirectory=/home/kb/weather-station-public
Restart=always
User=kb

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable outdoor-weather.service
sudo systemctl start outdoor-weather.service
sudo apt install ufw -y
sudo ufw allow ssh
sudo ufw allow 80
sudo ufw allow 8000
sudo ufw enable
sudo ufw reload
sudo reboot
