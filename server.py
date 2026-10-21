import json
import logging
import random
import socket

from common import SENSOR_SPECS, validate_sensor_data, validate_ip, validate_port, log_event
from protocol import REGISTER, REGISTER_ACK, DATA, ACK, decode_message, encode_message, TOKEN_MIN, TOKEN_MAX


def main(host: str, port: int):

    sessions = {}

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server_socket:
        server_socket.bind((host, port))
        log_event("SERVER", f"Server listening on {host}:{port}")

        while True:
            raw_data, sender_address = server_socket.recvfrom(65535)

            try:
                message = decode_message(raw_data)
            except ValueError as error:
                log_event("SERVER", f"Invalid data from {sender_address}: {error}; raw={raw_data!r}", level=logging.ERROR)
                continue

            log_event("SERVER", f"Received from {sender_address}: {json.dumps(message)}", "MESSAGE")

            try:
                if handlers.get(message["type"]) is None:
                    raise ValueError("Invalid request type")

                #TODO FIX ARGUMENTS CONFLICTS IN DIFFERENT HANDLERS
                answer = handlers[message["type"]](message, sessions, sender_address)
                encoded_answer = encode_message(answer)

                server_socket.sendto(encoded_answer, sender_address)
                log_event("SERVER", f"Sent to {sender_address}: {json.dumps(answer)}", "MESSAGE")
            except ValueError as error:
                log_event("SERVER", f"Rejected message from {sender_address}: {error}", level=logging.ERROR)
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

    log_event("SERVER", f"Sensor registered: {message['sensor_type']}:{message['sensor_id']}")
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
    DATA: handle_data,
}

if __name__ == "__main__":
    log_event("SERVER", "Server program started")
    host = "127.0.0.1"
    port = 25565

    while True:
        print("SERVER")
        print(f"1. Set IP ({host})")
        print(f"2. Set port ({port})")
        print("3. Start listening")
        print("0. Exit")
        op = input(": ")
        print("--------------------")

        match (op):
            case "1":
                try:
                    new_ip = input("Enter server IP: ").strip()
                    validate_ip(new_ip)
                    host = new_ip
                except ValueError as error:
                    print(f"Invalid IP: {error}")
                    log_event("SERVER", f"Invalid IP input: {error}", level=logging.WARNING)

            case "2":
                try:
                    new_port = int(input("Enter server port: "))
                    validate_port(new_port)
                    port = new_port
                except ValueError as error:
                    print(f"Invalid port: {error}")
                    log_event("SERVER", f"Invalid port input: {error}", level=logging.WARNING)

            case "3":
                try:
                    main(host, port)
                except KeyboardInterrupt:
                    log_event("SERVER", "Server stopped")
                except OSError as error:
                    print(f"Socket error: {error}")
                    log_event("SERVER", f"Socket error: {error}", level=logging.ERROR)

            case "0":
                break

            case _:
                print("Invalid option")

        print("--------------------")

    log_event("SERVER", "Server program closed")
