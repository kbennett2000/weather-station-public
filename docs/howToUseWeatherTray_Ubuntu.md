# How to Setup the Jones Big Ass Weather Widget on Ubuntu Desktop

## Description
The [Jones Big Ass Weather Widget](../weather_tray.py) displays sensor data from your Jones Big Ass Outdoor Weather Sensor. This instructions will show you how to install the widget in a Ubuntu Desktop (24.04) environment.

## Install required system packages
```bash
sudo apt update
```
```bash
sudo apt install python3-venv python3-gi python3-gi-cairo gir1.2-appindicator3-0.1 curl -y
```

## Create the project folder and virtual environment
- Move to project directory (may be different from below)
```bash
cd ~/Desktop/Projects/weather-widget
```

### Create venv that can see system tray libraries
```bash
python3 -m venv venv --system-site-packages
```

### Activate it
```bash
source venv/bin/activate
```

### Install the only Python package we need
```bash
pip install requests
```

## Make it executable and run it
```bash
chmod +x weather_tray.py
```
```bash
python weather_tray.py
```

## Make it start automatically on login
- Search for “Startup Applications” in the menu and open it.
- Click Add.
- Fill in:
  - Name: Home Weather Tray
- Command: (copy exactly)
```
/home/YOURUSERNAME/Desktop/Projects/weather-widget/venv/bin/python /home/YOURUSERNAME/Desktop/Projects/weather-widget/weather_tray.py
```
- Replace YOURUSERNAME with the actual username on this PC (type whoami in terminal to check).
- Click Save.
- Close the terminal — the tray will keep running in the background.

