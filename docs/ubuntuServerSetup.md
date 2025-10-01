# Installation Instructions for Ubuntu Server 24.04 LTS

**Assumptions**:
- Ubuntu Server 24.04 LTS installed on a PC.
- The server has network access and can reach the sensors (test with `ping 192.168.1.60`).
- Replace example IPs, passwords, and interface names (e.g., `eth0`) with your own.
- Run all commands as a non-root user with `sudo` where specified.
- The system uses port 8000 internally for the dashboard but forwards port 80 for access at `http://<server-ip>` (no port needed).

## Step 1: Update the System and Install Dependencies
1. Update packages:
   ```sh
   sudo apt update
   sudo apt upgrade -y
   ```

2. Install required packages (Python, MariaDB, venv support, iptables tools):
   ```sh
   sudo apt install python3 python3-venv mariadb-server iptables-persistent -y
   ```

3. Install NetworkManager
```sh
sudo apt update
sudo apt install network-manager -y
```

### Step 1.5: Configure Netplan to Use NetworkManager
Netplan must be set to use NetworkManager as the renderer.
1. Create or edit the Netplan configuration file:
   ```sh
   sudo nano /etc/netplan/01-network-manager-all.yaml
   ```
   Add the following content (this tells Netplan to hand off control to NetworkManager):
   ```
   network:
     version: 2
     renderer: NetworkManager
   ```
   Save and exit (`Ctrl+O`, `Enter`, `Ctrl+X`).

2. Apply the changes:
   ```sh
   sudo netplan generate
   sudo netplan apply
   ```

3. Restart NetworkManager to ensure it's active:
   ```sh
   sudo systemctl restart NetworkManager
   sudo systemctl enable NetworkManager
   ```

### Step 3: Verify NetworkManager and Connections
1. Check if NetworkManager is running:
   ```sh
   sudo systemctl status NetworkManager
   ```
   - It should show "active (running)".

2. List connections again:
   ```sh
   nmcli con show
   ```
   - Now it should display your connections (e.g., "Wired connection 1" or similar). If still empty, reboot:
     ```sh
     sudo reboot
     ```
     And recheck after reboot.

3. If no connections appear post-reboot:
   - Check devices:
     ```sh
     nmcli device status
     ```
     - If devices show as "unmanaged," edit `/etc/NetworkManager/NetworkManager.conf`:
       ```sh
       sudo nano /etc/NetworkManager/NetworkManager.conf
       ```
       Under `[main]`, add or change to:
       ```
       plugins=ifupdown,keyfile
       ```
       Under `[ifupdown]`, add:
       ```
       managed=true
       ```
       Save, then restart:
       ```sh
       sudo systemctl restart NetworkManager
       ```

## Step 2: Set a Static IP (Recommended)
Use NetworkManager to set a static IP (e.g., 192.168.1.62). Replace `"Wired connection 1"` with your connection name (find with `nmcli con show`).
```sh
sudo nmcli con mod "Wired connection 1" ipv4.method manual ipv4.addresses 192.168.1.62/24 ipv4.gateway 192.168.1.1 ipv4.dns "192.168.1.1 8.8.8.8"
sudo nmcli con up "Wired connection 1"
```
Verify:
```sh
ip addr show
ping 8.8.8.8
```
Reboot and recheck to confirm persistence.

## Step 3: Clone the Repository
Clone the code from GitHub:
```sh
cd ~
git clone https://github.com/kbennett2000/weather-station.git
cd weather-station
```

## Step 4: Set Up MariaDB Database
1. Secure MariaDB:
   ```sh
   sudo mysql_secure_installation
   ```
   - Set a root password and answer 'Y' to all prompts.

2. Create database, user, and tables:
   ```sh
   sudo mysql
   ```
   In the MySQL prompt:
   ```
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
   (Add a basement table if needed, similar to indoor.)

3. Start and enable MariaDB:
   ```sh
   sudo systemctl start mariadb
   sudo systemctl enable mariadb
   ```

## Step 5: Set Up Virtual Environment and Dependencies
1. Create venv:
   ```sh
   python3 -m venv ~/weather-station/venv
   ```

2. Activate:
   ```sh
   source ~/weather-station/venv/bin/activate
   ```

3. Install Python packages:
   ```
   pip install mysql-connector-python requests
   ```

4. Deactivate:
   ```
   deactivate
   ```

## Step 6: Configure Scripts
1. Update database config in scripts (replace `'your_secure_password'`):
   ```sh
   nano ~/weather-station/weatherProxy.py
   ```
   Set:
   ```
   db_config = {
       'user': 'weatheruser',
       'password': 'your_secure_password',
       'host': 'localhost',
       'database': 'weather_station',
   }
   ```
   Repeat for `weatherLogger_Indoor.py` and `weatherLogger_Outdoor.py` (and basement if present).

2. Set proxy to port 8000:
   In `weatherProxy.py`:
   ```
   server = HTTPServer(('0.0.0.0', 8000), ProxyHandler)
   ```

## Step 7: Test Scripts Manually
1. Activate venv:
   ```sh
   source ~/weather-station/venv/bin/activate
   ```

2. Test proxy:
   ```
   python ~/weather-station/weatherProxy.py
   ```
   Browse to http://<server-ip>:8000. Ctrl+C to stop.

3. Test loggers:
   ```
   python ~/weather-station/weatherLogger_Indoor.py
   ```
   Ctrl+C, check DB:
   ```
   mysql -u weatheruser -p'your_secure_password' -e "SELECT * FROM weather_station.indoor_weather LIMIT 5"
   ```
   Repeat for outdoor.

4. Deactivate:
   ```
   deactivate
   ```

## Step 8: Set Up Port Forwarding (80 to 8000)
1. Add rule (replace `eth0` with your interface from `ip link show`):
   ```sh
   sudo iptables -t nat -A PREROUTING -i eth0 -p tcp --dport 80 -j REDIRECT --to-port 8000
   ```

2. Save rules:
   ```sh
   sudo mkdir -p /etc/iptables
   sudo iptables-save | sudo tee /etc/iptables/rules.v4
   ```

3. Create restore service:
   ```sh
   sudo nano /etc/systemd/system/iptables-restore.service
   ```
   Add:
   ```
   [Unit]
   Description=Restore iptables rules
   After=network.target

   [Service]
   ExecStart=/usr/sbin/iptables-restore /etc/iptables/rules.v4
   Type=oneshot
   RemainAfterExit=true

   [Install]
   WantedBy=multi-user.target
   ```
   Enable/start:
   ```sh
   sudo systemctl daemon-reload
   sudo systemctl enable iptables-restore.service
   sudo systemctl start iptables-restore.service
   ```

4. Verify:
   ```sh
   sudo iptables -t nat -L -v -n
   ```

## Step 9: Set Up Systemd Services
1. Dashboard:
   ```sh
   sudo nano /etc/systemd/system/weather-dashboard.service
   ```
   Add:
   ```
   [Unit]
   Description=Weather Dashboard Server
   After=network.target mariadb.service

   [Service]
   ExecStart=/home/kb/weather-station/venv/bin/python /home/kb/weather-station/weatherProxy.py
   WorkingDirectory=/home/kb/weather-station
   Restart=always
   User=kb

   [Install]
   WantedBy=multi-user.target
   ```
   Enable/start:
   ```sh
   sudo systemctl daemon-reload
   sudo systemctl enable weather-dashboard.service
   sudo systemctl start weather-dashboard.service
   ```

2. Indoor logger:
   ```sh
   sudo nano /etc/systemd/system/indoor-weather.service
   ```
   Add similar, with `weatherLogger_Indoor.py`. Enable/start.

3. Outdoor logger:
   Similar for `weatherLogger_Outdoor.py`. Enable/start.

## Step 10: Firewall Configuration (Optional)
Install UFW
```sh
sudo apt install ufw -y
```

If UFW is disabled (default), traffic is allowed. To enable:
```sh
sudo ufw allow ssh
sudo ufw allow 80
sudo ufw allow 8000
sudo ufw enable
sudo ufw reload
```

## Step 11: Verification
1. Reboot:
   ```sh
   sudo reboot
   ```

2. Check services:
   ```sh
   sudo systemctl status weather-dashboard.service
   sudo systemctl status indoor-weather.service
   sudo systemctl status outdoor-weather.service
   sudo systemctl status iptables-restore.service
   ```

3. Check iptables:
   ```sh
   sudo iptables -t nat -L -v -n
   ```

4. Access dashboard: http://192.168.1.62 (no port) from network devices.

5. Check logs:
   ```sh
   cat ~/weather-station/weather_proxy.log
   sudo journalctl -u weather-dashboard.service -e
   ```

## Troubleshooting
- **No Access on Port 80**: Re-add/save rules, check interface.
- **DB Errors**: Verify password, test connection.
- **Services Fail**: Check journalctl logs.
- **Sensors Offline**: Test `curl http://192.168.1.60/data`.

For support, check logs and repo issues.
