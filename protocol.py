REGISTER = "REGISTER"
REGISTER_ACK = "REGISTER_ACK"
DATA = "DATA"
ACK = "ACK"
RESEND = "RESEND"
KEEPALIVE = "KEEPALIVE"
KEEPALIVE_ACK = "KEEPALIVE_ACK"
REJECT = "REJECT"

MESSAGE_TYPES = {
    REGISTER: 0,
    REGISTER_ACK: 1,
    DATA: 2,
    ACK: 3,
    RESEND: 4,
    KEEPALIVE: 5,
    KEEPALIVE_ACK: 6,
    REJECT: 7,
}
MESSAGE_NAMES = {number: name for name, number in MESSAGE_TYPES.items()}

SENSOR_TYPES = {
    "ThermoNode": 0,
    "WindSense": 1,
    "RainDetect": 2,
    "AirQuality": 3,
}
SENSOR_NAMES = {number: name for name, number in SENSOR_TYPES.items()}

MESSAGE_FORMATS = {
    REGISTER: {"type": str, "sensor_type": str, "sensor_id": str, "message_id": int},
    REGISTER_ACK: {"type": str, "message_id": int, "token": int},
    DATA: {"type": str, "message_id": int, "data": dict, "token": int, "checksum": int},
    ACK: {"type": str, "message_id": int, "token": int},
    RESEND: {"type": str, "message_id": int, "token": int},
    KEEPALIVE: {"type": str, "message_id": int, "token": int},
    KEEPALIVE_ACK: {"type": str, "message_id": int, "token": int},
    REJECT: {"type": str, "message_id": int, "reason": str},
}

# The program uses sensor_id locally for logging. It is not sent in these packets.
OPTIONAL_LOCAL_FIELDS = {
    DATA: {"sensor_id": str},
    KEEPALIVE: {"sensor_id": str},
    KEEPALIVE_ACK: {"sensor_id": str},
}

AUTO_SEND_INTERVAL = 10
IDLE_TIMEOUT = 15
KEEPALIVE_INTERVAL = 5
SESSION_TIMEOUT = 30
REPLY_TIMEOUT = 3

TOKEN_MIN = 1
TOKEN_MAX = 65535
MESSAGE_ID_MIN = 1
MESSAGE_ID_MAX = 65535

# name: (minimum, scale, bit width, maximum)
SENSOR_FIELDS = {
    "ThermoNode": (
        ("temperature", -50.0, 10, 11, 60.0),
        ("humidity", 0.0, 10, 10, 100.0),
        ("dew_point", -50.0, 10, 11, 60.0),
        ("pressure", 800.0, 100, 15, 1100.0),
    ),
    "WindSense": (
        ("wind_speed", 0.0, 10, 9, 50.0),
        ("wind_gust", 0.0, 10, 10, 70.0),
        ("wind_direction", 0, 1, 9, 359),
        ("turbulence", 0.0, 10, 4, 1.0),
    ),
    "RainDetect": (
        ("rainfall", 0.0, 10, 13, 500.0),
        ("soil_moisture", 0.0, 10, 10, 100.0),
        ("flood_risk", 0, 1, 2, 3),
        ("rain_duration", 0, 1, 6, 60),
    ),
    "AirQuality": (
        ("co2", 300, 1, 13, 5000),
        ("ozone", 0.0, 10, 13, 500.0),
        ("air_quality_index", 0, 1, 9, 500),
    ),
}

FIELDS_BY_KEY = {
    frozenset(field[0] for field in fields): name
    for name, fields in SENSOR_FIELDS.items()
}

REJECT_REASONS = {
    1: "Sensor with this id already registered",
    2: "No unused tokens available",
    3: "Session with this sensor does not exist",
    4: "Invalid token for current session",
    5: "Invalid sensor address",
    6: "Sensor value not in accepted range",
    7: "Invalid request type",
    8: "Message id reused with different DATA content",
}
REJECT_CODES = {reason: number for number, reason in REJECT_REASONS.items()}


def _sensor_for_data(data):
    sensor_type = FIELDS_BY_KEY.get(frozenset(data))
    if sensor_type is None:
        raise ValueError("Invalid sensor data fields")
    return sensor_type


def _pack_data(sensor_type, data):
    fields = SENSOR_FIELDS[sensor_type]
    if data.keys() != {field[0] for field in fields}:
        raise ValueError("Invalid sensor data fields")

    bits = ""
    for name, minimum, scale, width, maximum in fields:
        value = data[name]
        if type(value) not in (int, float) or not minimum <= value <= maximum:
            raise ValueError(f"Invalid value for {name}")

        scaled = (value - minimum) * scale
        encoded = round(scaled)
        if abs(scaled - encoded) > 1e-7 or encoded >= 2 ** width:
            raise ValueError(f"Invalid precision for {name}")
        bits += format(encoded, f"0{width}b")

    bits += "0" * (-len(bits) % 8)
    return bytes(int(bits[i:i + 8], 2) for i in range(0, len(bits), 8))


def _unpack_data(sensor_type, payload):
    fields = SENSOR_FIELDS[sensor_type]
    bit_count = sum(field[3] for field in fields)
    expected_length = (bit_count + 7) // 8
    if len(payload) != expected_length:
        raise ValueError("Invalid DATA payload length")

    bits = "".join(format(byte, "08b") for byte in payload)
    data = {}
    offset = 0
    for name, minimum, scale, width, maximum in fields:
        encoded = int(bits[offset:offset + width], 2)
        offset += width
        value = minimum + encoded / scale
        if value > maximum:
            raise ValueError(f"Invalid value for {name}")
        data[name] = int(value) if scale == 1 else round(value, 1 if scale == 10 else 2)

    if "1" in bits[bit_count:]:
        raise ValueError("Invalid DATA padding")
    return data


def calculate_checksum(message):
    """Return CRC-16/CCITT-FALSE for the DATA bytes before the CRC field."""
    if not isinstance(message, dict) or message.get("type") != DATA:
        raise ValueError("CRC can only be calculated for DATA")

    sensor_type = _sensor_for_data(message["data"])
    packet = (
        bytes((MESSAGE_TYPES[DATA],))
        + message["message_id"].to_bytes(2, "big")
        + message["token"].to_bytes(2, "big")
        + bytes((SENSOR_TYPES[sensor_type],))
        + _pack_data(sensor_type, message["data"])
    )

    crc = 0xFFFF
    for byte in packet:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def encode_message(message):
    validate_message(message)
    kind = message["type"]
    packet = bytes((MESSAGE_TYPES[kind],)) + message["message_id"].to_bytes(2, "big")

    if kind == REGISTER:
        sensor_id = message["sensor_id"].encode("utf-8")
        return packet + bytes((SENSOR_TYPES[message["sensor_type"]], len(sensor_id))) + sensor_id

    if kind == REGISTER_ACK or kind in (ACK, RESEND, KEEPALIVE, KEEPALIVE_ACK):
        return packet + message["token"].to_bytes(2, "big")

    if kind == DATA:
        sensor_type = _sensor_for_data(message["data"])
        packet += message["token"].to_bytes(2, "big")
        packet += bytes((SENSOR_TYPES[sensor_type],))
        packet += _pack_data(sensor_type, message["data"])
        return packet + message["checksum"].to_bytes(2, "big")

    reason_code = REJECT_CODES.get(message["reason"], 7)
    return packet + bytes((reason_code,))


def decode_message(packet):
    if not isinstance(packet, bytes) or len(packet) < 3:
        raise ValueError("Message is too short")

    kind = MESSAGE_NAMES.get(packet[0])
    if kind is None:
        raise ValueError("Unknown message type")
    message_id = int.from_bytes(packet[1:3], "big")

    if kind == REGISTER:
        if len(packet) < 6:
            raise ValueError("REGISTER is too short")
        sensor_type = SENSOR_NAMES.get(packet[3])
        sensor_id_length = packet[4]
        if sensor_type is None or not 1 <= sensor_id_length <= 32:
            raise ValueError("Invalid REGISTER fields")
        if len(packet) != 5 + sensor_id_length:
            raise ValueError("Invalid REGISTER length")
        try:
            sensor_id = packet[5:].decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("Sensor id is not valid UTF-8") from error
        message = {
            "type": kind,
            "sensor_type": sensor_type,
            "sensor_id": sensor_id,
            "message_id": message_id,
        }

    elif kind == REGISTER_ACK or kind in (ACK, RESEND, KEEPALIVE, KEEPALIVE_ACK):
        if len(packet) != 5:
            raise ValueError(f"Invalid {kind} length")
        message = {
            "type": kind,
            "message_id": message_id,
            "token": int.from_bytes(packet[3:5], "big"),
        }

    elif kind == DATA:
        if len(packet) < 8:
            raise ValueError("DATA is too short")
        sensor_type = SENSOR_NAMES.get(packet[5])
        if sensor_type is None:
            raise ValueError("Invalid DATA sensor type")
        token = int.from_bytes(packet[3:5], "big")
        data_fields = SENSOR_FIELDS[sensor_type]
        data_length = (sum(field[3] for field in data_fields) + 7) // 8
        if len(packet) != 6 + data_length + 2:
            raise ValueError("Invalid DATA length")
        data = _unpack_data(sensor_type, packet[6:6 + data_length])
        message = {
            "type": kind,
            "message_id": message_id,
            "token": token,
            "data": data,
            "checksum": int.from_bytes(packet[-2:], "big"),
        }

    else:  # REJECT
        if len(packet) != 4 or packet[3] not in REJECT_REASONS:
            raise ValueError("Invalid REJECT message")
        message = {
            "type": kind,
            "message_id": message_id,
            "reason": REJECT_REASONS[packet[3]],
        }

    validate_message(message)
    return message


def validate_message(message):
    if not isinstance(message, dict) or "type" not in message:
        raise ValueError("Invalid message")

    kind = message["type"]
    if kind not in MESSAGE_FORMATS:
        raise ValueError("Unknown message type")

    expected = MESSAGE_FORMATS[kind]
    optional = OPTIONAL_LOCAL_FIELDS.get(kind, {})
    keys = set(message)
    if keys != set(expected) and keys != set(expected) | set(optional):
        raise ValueError("Unexpected message fields")

    for key, value in message.items():
        expected_type = expected.get(key, optional.get(key))
        if type(value) is not expected_type:
            raise ValueError(f"Invalid value type for {key}")

    message_id = message["message_id"]
    if not 1 <= message_id <= MESSAGE_ID_MAX:
        raise ValueError("Message id is outside the allowed range")

    if "token" in message and not TOKEN_MIN <= message["token"] <= TOKEN_MAX:
        raise ValueError("Token is outside the allowed range")

    if "sensor_type" in message and message["sensor_type"] not in SENSOR_TYPES:
        raise ValueError("Invalid sensor type")

    if "sensor_id" in message:
        sensor_id = message["sensor_id"]
        size = len(sensor_id.encode("utf-8"))
        if not sensor_id.strip() or not sensor_id.isprintable() or not 1 <= size <= 32:
            raise ValueError("Sensor id must be 1 to 32 printable bytes")

    if kind == DATA:
        sensor_type = _sensor_for_data(message["data"])
        _pack_data(sensor_type, message["data"])
        if type(message["checksum"]) is not int or not 0 <= message["checksum"] <= 0xFFFF:
            raise ValueError("Invalid DATA checksum")

    return True
