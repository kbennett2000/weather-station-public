from http.server import HTTPServer, SimpleHTTPRequestHandler
import requests
from urllib.parse import parse_qs, urlparse
import os
import mysql.connector
import logging
from datetime import datetime, timedelta
import io
import csv

# Set up logging
logging.basicConfig(
    filename='weather_proxy.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Database configuration
db_config = {
    'user': 'weatheruser',
    'password': 'password',  # Replace with your actual password
    'host': 'localhost',
    'database': 'weather_station',
}

def connect_to_database():
    """Create a connection to the database."""
    try:
        conn = mysql.connector.connect(**db_config)
        return conn
    except mysql.connector.Error as err:
        logging.error(f"Database connection failed: {err}")
        return None

class ProxyHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        SimpleHTTPRequestHandler.end_headers(self)

    def do_GET(self):
        # Add proper MIME type for .js files
        if self.path.endswith('.js'):
            self.send_response(200)
            self.send_header('Content-type', 'application/javascript')
            self.end_headers()
            with open(self.path.lstrip('/'), 'rb') as f:
                self.wfile.write(f.read())
            return

        if self.path == '/':
            self.path = 'dashboard.html'
            return SimpleHTTPRequestHandler.do_GET(self)
        
        # Extract path and query parameters
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        query_params = parse_qs(parsed_url.query)
        
        # Handle data requests
        if path == '/weather_data_indoor.csv':
            hours = int(query_params.get('hours', [24])[0])
            self.send_indoor_data(hours)
            return
        
        if path == '/weather_data_outdoor.csv':
            hours = int(query_params.get('hours', [24])[0])
            self.send_outdoor_data(hours)
            return

        # Handle proxy requests for sensor data
        if parsed_url.query:
            query = parse_qs(parsed_url.query)
            url = query.get('url', [None])[0]
            
            if url:
                try:
                    # Set a shorter timeout for direct device requests
                    response = requests.get(url, timeout=5)
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(response.content)
                except Exception as e:
                    self.send_error(500, str(e))
            else:
                self.send_error(400, "Missing URL parameter")
            return

        # Serve static files
        return SimpleHTTPRequestHandler.do_GET(self)
    
    def send_indoor_data(self, hours=24):
        """Fetch indoor weather data from MySQL and send as CSV"""
        conn = connect_to_database()
        if not conn:
            self.send_error(500, "Database connection failed")
            return
        
        try:
            cursor = conn.cursor(dictionary=True)
            
            # Get data from the last X hours
            time_threshold = (datetime.now() - timedelta(hours=hours)).strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute(
                "SELECT * FROM indoor_weather WHERE timestamp >= %s ORDER BY timestamp",
                (time_threshold,)
            )
            
            rows = cursor.fetchall()
            
            self.send_response(200)
            self.send_header('Content-Type', 'text/csv')
            self.end_headers()
            
            # Create CSV in memory
            output = io.StringIO()
            csv_writer = csv.writer(output)
            
            # Write header
            csv_writer.writerow(['timestamp', 'temperatureC', 'temperatureF', 'humidity', 'pressure'])
            
            # Write data rows
            for row in rows:
                csv_writer.writerow([
                    row['timestamp'].strftime('%Y-%m-%d %H:%M:%S') if row['timestamp'] else '',
                    row['temperatureC'] if row['temperatureC'] is not None else '',
                    row['temperatureF'] if row['temperatureF'] is not None else '',
                    row['humidity'] if row['humidity'] is not None else '',
                    row['pressure'] if row['pressure'] is not None else ''
                ])
            
            self.wfile.write(output.getvalue().encode('utf-8'))
                
        except Exception as e:
            logging.error(f"Error fetching indoor data: {e}")
            self.send_error(500, f"Error fetching data: {str(e)}")
        finally:
            if conn and conn.is_connected():
                cursor.close()
                conn.close()
    
    def send_outdoor_data(self, hours=24):
        """Fetch outdoor weather data from MySQL and send as CSV"""
        logging.info(f"Requested outdoor data with hours={hours}")
        conn = connect_to_database()
        if not conn:
            self.send_error(500, "Database connection failed")
            return
        
        try:
            cursor = conn.cursor(dictionary=True)
            
            # Get data from the last X hours
            time_threshold = (datetime.now() - timedelta(hours=hours)).strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute(
                "SELECT * FROM outdoor_weather WHERE timestamp >= %s ORDER BY timestamp",
                (time_threshold,)
            )
            
            rows = cursor.fetchall()
            
            logging.info(f"Fetched {len(rows)} rows from outdoor_weather for hours={hours}")
            
            self.send_response(200)
            self.send_header('Content-Type', 'text/csv')
            self.end_headers()
            
            # Create CSV in memory
            output = io.StringIO()
            csv_writer = csv.writer(output)
            
            # Write header with all columns
            csv_writer.writerow([
                'timestamp', 'temperatureC', 'temperatureF', 'humidity', 'pressure',
                'lux', 'ir', 'visible', 'full', 'latitude', 'longitude', 'altitude',
                'speed', 'course', 'satellites', 'tempOffset', 'rssi', 'uptime', 'freeHeap'
            ])
            
            # Write data rows
            for row in rows:
                csv_writer.writerow([
                    row['timestamp'].strftime('%Y-%m-%d %H:%M:%S') if row['timestamp'] else '',
                    row['temperatureC'] if row['temperatureC'] is not None else '',
                    row['temperatureF'] if row['temperatureF'] is not None else '',
                    row['humidity'] if row['humidity'] is not None else '',
                    row['pressure'] if row['pressure'] is not None else '',
                    row['lux'] if row['lux'] is not None else '',
                    row['ir'] if row['ir'] is not None else '',
                    row['visible'] if row['visible'] is not None else '',
                    row['full'] if row['full'] is not None else '',
                    row['latitude'] if row['latitude'] is not None else '',
                    row['longitude'] if row['longitude'] is not None else '',
                    row['altitude'] if row['altitude'] is not None else '',
                    row['speed'] if row['speed'] is not None else '',
                    row['course'] if row['course'] is not None else '',
                    row['satellites'] if row['satellites'] is not None else '',
                    row['tempOffset'] if row['tempOffset'] is not None else '',
                    row['rssi'] if row['rssi'] is not None else '',
                    row['uptime'] if row['uptime'] is not None else '',
                    row['freeHeap'] if row['freeHeap'] is not None else ''
                ])
            
            self.wfile.write(output.getvalue().encode('utf-8'))
                
        except Exception as e:
            logging.error(f"Error fetching outdoor data: {e}")
            self.send_error(500, f"Error fetching data: {str(e)}")
        finally:
            if conn and conn.is_connected():
                cursor.close()
                conn.close()

if __name__ == '__main__':
    try:
        server = HTTPServer(('0.0.0.0', 8000), ProxyHandler)
        print(f"Server running on http://0.0.0.0:80")
        print(f"Current directory: {os.getcwd()}")
        logging.info("Weather proxy server started")
        server.serve_forever()
    except Exception as e:
        logging.error(f"Server error: {e}")

        print(f"Error: {e}")
