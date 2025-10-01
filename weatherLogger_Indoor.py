import requests
import time
from datetime import datetime
import mysql.connector
import logging

# Set up logging
logging.basicConfig(
    filename='weather_logger_indoor.log',
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

def get_weather_data():
    try:
        response = requests.get('http://192.168.1.61/data')
        return response.json()
    except Exception as e:
        logging.error(f"Error getting data: {e}")
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
        conn = connect_to_database()
        cursor = conn.cursor()
        
        query = """
        INSERT INTO indoor_weather (timestamp, temperatureC, temperatureF, humidity, pressure)
        VALUES (%s, %s, %s, %s, %s)
        """
        values = (
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            data['temperatureC'],
            data['temperatureF'],
            data['humidity'],
            data['pressure']
        )
        
        cursor.execute(query, values)
        conn.commit()
        logging.info("Data inserted successfully")
        return True
    except mysql.connector.Error as err:
        logging.error(f"Database error: {err}")
        return False
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

def main():
    consecutive_failures = 0
    max_failures = 5
    retry_delay = 60
    
    logging.info("Indoor weather logging started")
    
    while True:
        try:
            data = get_weather_data()
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
                logging.error("Too many consecutive failures. Increasing retry delay...")
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