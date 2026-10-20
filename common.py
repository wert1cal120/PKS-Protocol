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