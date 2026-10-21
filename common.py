import ipaddress
import random
import logging
import time
from pathlib import Path

SENSOR_SPECS = {
    "ThermoNode": {
        "temperature": {
            "min": -50.0,
            "max": 60.0,
            "decimals": 1
        },
        "humidity": {
            "min": 0.0,
            "max": 100.0,
            "decimals": 1
        },
        "dew_point": {
            "min": -50.0,
            "max": 60.0,
            "decimals": 1
        },
        "pressure": {
            "min": 800.00,
            "max": 1100.00,
            "decimals": 2
        }
    },
    "WindSense": {
        "wind_speed": {
            "min": 0.0,
            "max": 50.0,
            "decimals": 1
        },
        "wind_gust": {
            "min": 0.0,
            "max": 70.0,
            "decimals": 1
        },
        "wind_direction": {
            "min": 0,
            "max": 359,
            "decimals": 0
        },
        "turbulence": {
            "min": 0.0,
            "max": 1.0,
            "decimals": 1
        }
    },
    "RainDetect": {
        "rainfall": {
            "min": 0.0,
            "max": 500.0,
            "decimals": 1
        },
        "soil_moisture": {
            "min": 0.0,
            "max": 100.0,
            "decimals": 1
        },
        "flood_risk": {
            "min": 0,
            "max": 3,
            "decimals": 0
        },
        "rain_duration": {
            "min": 0,
            "max": 60,
            "decimals": 0
        }
    },
    "AirQuality": {
        "co2": {
            "min": 300,
            "max": 5000,
            "decimals": 0
        },
        "ozone": {
            "min": 0.0,
            "max": 500.0,
            "decimals": 1
        },
        "air_quality_index": {
            "min": 0,
            "max": 500,
            "decimals": 0
        }
    }
}

def validate_sensor_data(sensor_type: str, data: dict) -> bool:
    if not isinstance(sensor_type, str):
        raise ValueError("Sensor type is not str")

    if not sensor_type in SENSOR_SPECS.keys():
        raise ValueError("Invalid sensor type")

    sensor_format = SENSOR_SPECS[sensor_type]

    if not isinstance(data, dict):
        raise ValueError("Data is not dict")

    if data.keys() != sensor_format.keys():
        raise ValueError("Invalid data dict")

    for key, value in data.items():
        min_value, max_value, decimals = sensor_format[key].values()

        if (decimals == 0 and type(value) != int) or (decimals > 0 and type(value) not in (int, float)):
            raise ValueError("Unexpected value type")

        if not (min_value <= value <= max_value and value == round(value, decimals)):
            raise ValueError("Sensor value not in accepted range")

    return True

def generate_sensor_data(sensor_type: str):
    if not sensor_type in SENSOR_SPECS.keys():
        raise ValueError("Invalid sensor_type")

    data = {}

    sensor_type_format = SENSOR_SPECS[sensor_type]

    for key, value in sensor_type_format.items():
        min_value, max_value, decimals = value.values()
        data[key] = round(random.uniform(min_value, max_value), decimals) if decimals != 0 else random.randint(min_value, max_value)

    validate_sensor_data(sensor_type, data)
    return data

def validate_ip(ip: str) -> bool:
    if not isinstance(ip, str):
        raise ValueError("IP is not str")

    ipaddress.IPv4Address(ip)
    return True

def validate_port(port: int) -> bool:
    if type(port) is not int:
        raise ValueError("Port is not int")

    if not 1 <= port <= 65535:
        raise ValueError("Port must be between 1 and 65535")

    return True

def log_event(source: str, message: str, log_type: str = "SYSTEM", level: int = logging.INFO):
    program = source.split(":")[0]
    logger = logging.getLogger(f"PKS.{program}")

    if not logger.handlers:
        log_directory = Path(__file__).parent / "logs"
        log_directory.mkdir(exist_ok=True)
        log_file = log_directory / f"{program.lower()}.log"
        handler = logging.FileHandler(log_file, encoding="utf-8")
        formatter = logging.Formatter(
            "%(asctime)s.%(msecs)03dZ | %(log_type)s | %(levelname)s | %(source)s | %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S"
        )
        formatter.converter = time.gmtime
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False

    logger.log(level, message, extra={"log_type": log_type, "source": source})
