import json

REGISTER = "REGISTER"
REGISTER_ACK = "REGISTER_ACK"
DATA = "DATA"
ACK = "ACK"


MESSAGE_FORMATS ={
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
        "token": int
    },
    ACK: {
        "type": str,
        "message_id": int,
        "token": int
    }
}

TOKEN_MIN = 1
TOKEN_MAX = 65535  # 2**16 - 1

def encode_message(message: dict) -> bytes:
    validate_message(message)
    json_text = json.dumps(message)
    return json_text.encode('utf-8')

def decode_message(message: bytes) -> dict:
    json_text = message.decode('utf-8')
    json_text = json.loads(json_text)

    if not isinstance(json_text, dict):
        raise ValueError("Decoded message is not a dictionary")

    validate_message(json_text)
    return json_text

def validate_message(message: dict) -> bool:
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

    return True