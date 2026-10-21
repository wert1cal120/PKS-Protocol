import json
import logging
import random
import socket
import threading

from common import SENSOR_SPECS, validate_sensor_data, validate_ip, validate_port, log_event
from protocol import REGISTER, REGISTER_ACK, DATA, ACK, decode_message, encode_message, TOKEN_MIN, TOKEN_MAX, RESEND, calculate_checksum


def run_server(server_socket, stop_event):
    sessions = {}

    while not stop_event.is_set():
        try:
            raw_data, sender_address = server_socket.recvfrom(65535)
        except socket.timeout:
            continue
        except OSError as error:
            log_event("SERVER", f"Socket error: {error}", level=logging.ERROR)
            stop_event.set()
            return

        try:
            message = decode_message(raw_data)
        except ValueError as error:
            log_event("SERVER", f"Invalid data from {sender_address}: {error}; raw={raw_data!r}", level=logging.ERROR)
            continue

        log_event("SERVER", f"Received from {sender_address}: {json.dumps(message)}", "MESSAGE")
        try:
            if handlers.get(message["type"]) is None:
                raise ValueError("Invalid request type")

            answer = handlers[message["type"]](message, sessions, sender_address)
            encoded_answer = encode_message(answer)
            server_socket.sendto(encoded_answer, sender_address)
            log_event("SERVER", f"Sent to {sender_address}: {json.dumps(answer)}", "MESSAGE")
        except (ValueError, OSError) as error:
            log_event("SERVER", f"Cannot process message from {sender_address}: {error}", level=logging.ERROR)


def main(host: str, port: int):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server_socket:
        server_socket.bind((host, port))
        server_socket.settimeout(0.2)
        log_event("SERVER", f"Server listening on {host}:{port}")

        stop_event = threading.Event()
        receiver = threading.Thread(target=run_server, args=(server_socket, stop_event))
        receiver.start()

        try:
            while not stop_event.is_set():
                print(f"SERVER - listening on {host}:{port}")
                print("0. Stop listening and return to settings")
                op = input(": ").strip()

                if op == "0":
                    break

                print("Invalid option")
        except (KeyboardInterrupt, EOFError):
            pass
        finally:
            stop_event.set()
            receiver.join()
            log_event("SERVER", "Server stopped")


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

    sensor_name = f"{session['sensor_type']}:{message['sensor_id']}"

    if message["checksum"] != calculate_checksum(message):
        log_event(
            "SERVER",
            f"Integrity check failed for {sensor_name}, message {message['message_id']}; retransmission requested",
            level=logging.WARNING
        )

        return {
            "type": RESEND,
            "message_id": message["message_id"],
            "token": message["token"]
        }

    validate_sensor_data(session["sensor_type"], message["data"])
    log_event("SERVER", f"Measurement accepted: {sensor_name} {json.dumps(message['data'])}")

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
