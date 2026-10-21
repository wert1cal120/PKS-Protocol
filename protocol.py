import json
import zlib

REGISTER = "REGISTER"
REGISTER_ACK = "REGISTER_ACK"
DATA = "DATA"
ACK = "ACK"
RESEND = "RESEND"
KEEPALIVE = "KEEPALIVE"
KEEPALIVE_ACK = "KEEPALIVE_ACK"
REJECT = "REJECT"


MESSAGE_FORMATS = {
    REGISTER: {
        "type": str,
        "sensor_type": str,
        "sensor_id": str,
        "message_id": int
    },
    REGISTER_ACK: {
        "type": str,
        "message_id": int,
        "token": int
    },
    DATA: {
        "type": str,
        "sensor_id": str,
        "message_id": int,
        "data": dict,
        "token": int,
        "checksum": int
    },
    KEEPALIVE: {
        "type": str,
        "sensor_id": str,
        "message_id": int,
        "token": int
    },
    KEEPALIVE_ACK: {
        "type": str,
        "sensor_id": str,
        "message_id": int,
        "token": int
    },
    REJECT: {
        "type": str,
        "message_id": int,
        "reason": str
    },
    RESEND: {
        "type": str,
        "message_id": int,
        "token": int
    },
    ACK: {
        "type": str,
        "message_id": int,
        "token": int
    }
}

AUTO_SEND_INTERVAL = 10
IDLE_TIMEOUT = 15
KEEPALIVE_INTERVAL = 5
SESSION_TIMEOUT = 30
REPLY_TIMEOUT = 3

TOKEN_MIN = 1
TOKEN_MAX = 65535  # 2**16 - 1


def encode_message(message: dict) -> bytes:
    validate_message(message)
    json_text = json.dumps(message, allow_nan=False)
    return json_text.encode('utf-8')


def decode_message(message: bytes) -> dict:
    try:
        json_text = json.loads(message.decode('utf-8'))
    except RecursionError as error:
        raise ValueError("Message is nested too deeply") from error

    if not isinstance(json_text, dict):
        raise ValueError("Decoded message is not a dictionary")

    validate_message(json_text)
    return json_text


def validate_message(message: dict) -> bool:
    if not isinstance(message, dict):
        raise ValueError("Message must be a dictionary")

    if "type" not in message:
        raise ValueError("Message does not contain 'type' field")

    message_type = message["type"]

    if type(message_type) is not str:
        raise ValueError("Invalid message type")

    if message_type not in MESSAGE_FORMATS:
        raise ValueError(f"Unknown message type: {message_type}")

    expected_format = MESSAGE_FORMATS[message_type]

    if message.keys() != expected_format.keys():
        raise ValueError("Unexpected keys in message")

    for key, value in message.items():
        if type(value) is not expected_format[key]:
            raise ValueError("Invalid value type")

    if message["message_id"] < 1:
        raise ValueError("Message id must be positive")

    if "sensor_id" in message:
        sensor_id = message["sensor_id"]
        if not sensor_id.strip() or not sensor_id.isprintable():
            raise ValueError("Sensor id must be nonempty printable text")

    if "token" in message and not TOKEN_MIN <= message["token"] <= TOKEN_MAX:
        raise ValueError("Token is outside the allowed range")

    if "checksum" in message and not 0 <= message["checksum"] <= 0xFFFFFFFF:
        raise ValueError("Checksum must be an unsigned 32-bit integer")

    return True


def calculate_checksum(message: dict) -> int:
    content = message.copy()
    content.pop("checksum", None)

    json_text = json.dumps(content, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return zlib.crc32(json_text.encode("utf-8"))
