import random
import socket

from common import SENSOR_SPECS, validate_sensor_data
from protocol import REGISTER, REGISTER_ACK, DATA, ACK, decode_message, encode_message, TOKEN_MIN, TOKEN_MAX


def main():
    host = "127.0.0.1"
    port = 25565

    sessions = {}

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server_socket:
        server_socket.bind((host, port))
        print(f"Listening on {host}:{port}")

        while True:
            raw_data, sender_address = server_socket.recvfrom(65535)

            try:
                message = decode_message(raw_data)
            except ValueError as error:
                print(f"Invalid data from {sender_address}: {error}")
                continue

            print(f"From {sender_address}: {message}")

            try:
                if handlers.get(message["type"]) is None:
                    raise ValueError("Invalid request type")

                #TODO FIX ARGUMENTS CONFLICTS IN DIFFERENT HANDLERS
                answer = handlers[message["type"]](message, sessions, sender_address)
                encoded_answer = encode_message(answer)

                server_socket.sendto(encoded_answer, sender_address)
            except ValueError as error:
                print(error)
                continue




def handle_register(message: dict, sessions: dict, sender_address: tuple):
    if not message["sensor_type"] in SENSOR_SPECS.keys():
        raise ValueError("Invalid sensor type")

    if message["sensor_id"].strip() == "":
        raise ValueError("Invalid sensor id")

    if message["sensor_id"] in sessions.keys():
        raise ValueError("Sensor with this id already registered")

    sensor_token = random.randint(TOKEN_MIN, TOKEN_MAX)
    while sensor_token in [tester["token"] for tester in sessions.values()]:
        sensor_token = random.randint(TOKEN_MIN, TOKEN_MAX)

    sessions[message["sensor_id"]] = {
        "sensor_type": message["sensor_type"],
        "token": sensor_token,
        "tester_addres": sender_address
    }

    return handle_register_ack(message["message_id"], sensor_token)

def handle_register_ack(message_id: int, token: int):
    message = {
        "type": REGISTER_ACK,
        "message_id": message_id,
        "token": token
    }
    return message

def handle_data(message: dict, sessions: dict, sender_address: tuple):
    if sessions.get(message["sensor_id"]) is None:
        raise ValueError("Session with this sensor does not exist")

    session = sessions[message["sensor_id"]]
    if session["token"] != message["token"]:
        raise ValueError("Invalid token for current session")

    validate_sensor_data(session["sensor_type"], message["data"])
    print(message["data"])
    return handle_ack(message["message_id"], message["token"])

def handle_ack(message_id: int, token: int):
    message = {
        "type": ACK,
        "message_id": message_id,
        "token": token
    }
    return message

handlers = {
    REGISTER: handle_register,
    REGISTER_ACK: handle_register_ack,
    DATA: handle_data,
    ACK: handle_ack
}

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Server stopped")
    except OSError as error:
        print(f"Socket error: {error}")