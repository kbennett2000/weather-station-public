import requests
import time
from datetime import datetime
import mysql.connector
import logging
import json
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Set up logging
logging.basicConfig(
    filename='weather_logger_outdoor.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Database configuration
db_config = {
    'user': 'weatheruser',
    'password': 'password',
    'host': 'localhost',
    'database': 'weather_station',
}

def create_session():
    session = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504]
    )
    session.mount('http://', HTTPAdapter(max_retries=retries))
    return session

def get_weather_data(session):
    try:
        response = session.get('http://192.168.1.60/data', timeout=10)
        response.raise_for_status()
        
        # Get raw response and replace 'nan' with 'null'
        raw_response = response.text
        cleaned_response = raw_response.replace(':nan,', ':null,')
        
        try:
            return json.loads(cleaned_response)
        except ValueError as json_error:
            logging.error(f"JSON Parse Error. Raw response: {raw_response}")
            logging.error(f"Error message: {str(json_error)}")
            
            # Additional cleaning if needed
            cleaned_response = cleaned_response.strip()
            if cleaned_response.endswith(','):
                cleaned_response = cleaned_response[:-1]
            if not cleaned_response.endswith('}'):
                cleaned_response = cleaned_response + '}'
                
            try:
                return json.loads(cleaned_response)
            except:
                logging.error("Failed to parse even after additional cleaning")
                return None
                
    except requests.exceptions.RequestException as e:
        logging.error(f"Request Error: {e}")
        return None

def connect_to_database():
    """Create a connection to the database with retry logic."""
    max_attempts = 5
    attempt = 0
    
    while attempt < max_attempts:
        try:
            conn = mysql.connector.connect(**db_config)
            return conn
        except mysql.connector.Error as err:
            attempt += 1
            logging.error(f"Database connection attempt {attempt} failed: {err}")
            if attempt >= max_attempts:
                raise
            time.sleep(5)  # Wait before retrying

def insert_weather_data(data):
    conn = None
    try:
        # Convert any remaining nan values to None
        for key, value in data.items():
            if isinstance(value, str) and value.lower() == 'nan':
                data[key] = None
        
        conn = connect_to_database()
        cursor = conn.cursor()
        
        query = """
        INSERT INTO outdoor_weather (
            timestamp, temperatureC, temperatureF, humidity, pressure, 
            lux, ir, visible, full, latitude, longitude, altitude, 
            speed, course, satellites, tempOffset, rssi, uptime, freeHeap
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        """
        
        values = (
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            data.get('temperatureC'),
            data.get('temperatureF'),
            data.get('humidity'),
            data.get('pressure'),
            data.get('lux'),
            data.get('ir'),
            data.get('visible'),
            data.get('full'),
            data.get('latitude'),
            data.get('longitude'),
            data.get('altitude'),
            data.get('speed'),
            data.get('course'),
            data.get('satellites'),
            data.get('tempOffset'),
            data.get('rssi'),
            data.get('uptime'),
            data.get('freeHeap')
        )
        
        cursor.execute(query, values)
        conn.commit()
        logging.info(f"Data logged successfully: Temp={data.get('temperatureC')}°C, Humidity={data.get('humidity')}%")
        return True
    except mysql.connector.Error as err:
        logging.error(f"Database error: {err}")
        return False
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

def main():
    session = create_session()
    consecutive_failures = 0
    max_failures = 5
    retry_delay = 60

    logging.info("Outdoor weather logging started")
    
    while True:
        try:
            data = get_weather_data(session)
            
            if data:
                success = insert_weather_data(data)
                if success:
                    consecutive_failures = 0
                    retry_delay = 60  # Reset delay on success
                else:
                    consecutive_failures += 1
            else:
                consecutive_failures += 1
                logging.warning(f"Failed to get data. Consecutive failures: {consecutive_failures}")
                
            if consecutive_failures >= max_failures:
                logging.error("Too many consecutive failures. Recreating session...")
                session = create_session()
                consecutive_failures = 0
                retry_delay = min(retry_delay * 2, 300)  # Exponential backoff up to 5 minutes
                
            time.sleep(retry_delay)

        except Exception as e:
            logging.error(f"Unexpected error: {e}")
            time.sleep(retry_delay)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logging.info("Program stopped by user")
    except Exception as e:
        logging.error(f"Fatal error: {e}")