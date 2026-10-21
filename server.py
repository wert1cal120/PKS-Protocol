import json
import logging
import random
import socket
import threading
import time

from common import (
    SENSOR_SPECS, validate_sensor_data, validate_ip, validate_port,
    log_event, set_console_logging
)
from protocol import (
    REGISTER, REGISTER_ACK, DATA, ACK, RESEND, KEEPALIVE, KEEPALIVE_ACK, REJECT,
    decode_message, encode_message, calculate_checksum,
    TOKEN_MIN, TOKEN_MAX, IDLE_TIMEOUT, KEEPALIVE_INTERVAL
)


def send_message(sock, address, message):
    sock.sendto(encode_message(message), address)
    log_event("SERVER", f"Sent to {address}: {json.dumps(message)}", "MESSAGE")


def check_sessions(sock, sessions):
    now = time.monotonic()

    for sensor_id, session in list(sessions.items()):
        if now < session["next_keepalive_at"]:
            continue

        sensor_name = f"{session['sensor_type']}:{sensor_id}"

        if not session["idle"]:
            session["idle"] = True
            log_event("SERVER", f"SENSOR IDLE: {sensor_name}")

        if session["keepalive_attempts"] >= 3:
            del sessions[sensor_id]
            log_event("SERVER", f"SENSOR DISCONNECTED: {sensor_name}")
            continue

        message = {
            "type": KEEPALIVE,
            "sensor_id": sensor_id,
            "message_id": session["next_keepalive_id"],
            "token": session["token"]
        }

        session["pending_keepalive_id"] = message["message_id"]
        session["next_keepalive_id"] += 1
        session["keepalive_attempts"] += 1
        session["next_keepalive_at"] += KEEPALIVE_INTERVAL

        try:
            send_message(sock, session["address"], message)
        except OSError as error:
            log_event("SERVER", f"KEEPALIVE send failed for {sensor_name}: {error}", level=logging.ERROR)


def run_server(server_socket, stop_event):
    sessions = {}
    used_tokens = set()

    while not stop_event.is_set():
        check_sessions(server_socket, sessions)

        try:
            raw_data, sender_address = server_socket.recvfrom(65535)
        except socket.timeout:
            continue
        except OSError as error:
            log_event("SERVER", f"Socket error: {error}", level=logging.ERROR)
            stop_event.wait(0.05)
            continue

        try:
            message = decode_message(raw_data)
        except ValueError as error:
            log_event("SERVER", f"Invalid data from {sender_address}: {error}; raw={raw_data!r}", level=logging.ERROR)
            continue

        log_event("SERVER", f"Received from {sender_address}: {json.dumps(message)}", "MESSAGE")

        try:
            if message["type"] == REGISTER:
                answer = handle_register(message, sessions, sender_address, used_tokens)
            elif message["type"] == DATA:
                answer = handle_data(message, sessions, sender_address)
            elif message["type"] == KEEPALIVE_ACK:
                handle_keepalive_ack(message, sessions, sender_address)
                continue
            else:
                raise ValueError("Invalid request type")

            send_message(server_socket, sender_address, answer)

        except ValueError as error:
            log_event("SERVER", f"Rejected message from {sender_address}: {error}", level=logging.WARNING)

            if message["type"] in (REGISTER, DATA):
                answer = {
                    "type": REJECT,
                    "message_id": message["message_id"],
                    "reason": str(error)
                }

                try:
                    send_message(server_socket, sender_address, answer)
                except OSError as send_error:
                    log_event("SERVER", f"Socket error: {send_error}", level=logging.ERROR)

        except OSError as error:
            log_event("SERVER", f"Socket error: {error}", level=logging.ERROR)


def get_session(message, sessions, sender_address):
    session = sessions.get(message["sensor_id"])

    if session is None:
        raise ValueError("Session with this sensor does not exist")

    if session["token"] != message["token"]:
        raise ValueError("Invalid token for current session")

    if session["address"] != sender_address:
        raise ValueError("Invalid sensor address")

    return session


def handle_keepalive_ack(message, sessions, sender_address):
    session = get_session(message, sessions, sender_address)

    if message["message_id"] != session["pending_keepalive_id"]:
        raise ValueError("Unexpected KEEPALIVE_ACK message id")

    session["keepalive_attempts"] = 0
    session["pending_keepalive_id"] = None


def main(host: str, port: int):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server_socket:
        server_socket.bind((host, port))
        server_socket.settimeout(0.05)
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


def handle_register(message: dict, sessions: dict, sender_address: tuple, used_tokens: set):
    if message["sensor_type"] not in SENSOR_SPECS:
        raise ValueError("Invalid sensor type")

    if message["sensor_id"].strip() == "":
        raise ValueError("Invalid sensor id")

    if message["sensor_id"] in sessions:
        raise ValueError("Sensor with this id already registered")

    if len(used_tokens) >= TOKEN_MAX:
        raise ValueError("No unused tokens available; restart the server")

    sensor_token = random.randint(TOKEN_MIN, TOKEN_MAX)

    while sensor_token in used_tokens:
        sensor_token = random.randint(TOKEN_MIN, TOKEN_MAX)

    used_tokens.add(sensor_token)
    now = time.monotonic()

    sessions[message["sensor_id"]] = {
        "sensor_type": message["sensor_type"],
        "token": sensor_token,
        "address": sender_address,
        "last_data_at": now,
        "idle": False,
        "next_keepalive_at": now + IDLE_TIMEOUT,
        "keepalive_attempts": 0,
        "next_keepalive_id": 1,
        "pending_keepalive_id": None
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
    session = get_session(message, sessions, sender_address)

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

    session["last_data_at"] = time.monotonic()
    session["next_keepalive_at"] = session["last_data_at"] + IDLE_TIMEOUT
    session["idle"] = False
    session["keepalive_attempts"] = 0
    session["pending_keepalive_id"] = None

    log_event("SERVER", f"Measurement accepted: {sensor_name} {json.dumps(message['data'])}")

    return handle_ack(message["message_id"], message["token"])


def handle_ack(message_id: int, token: int):
    message = {
        "type": ACK,
        "message_id": message_id,
        "token": token
    }
    return message


def settings_menu():
    log_event("SERVER", "Server program started")
    host = "127.0.0.1"
    port = 25565
    console_logging = False

    while True:
        print("SERVER")
        print(f"1. Set IP ({host})")
        print(f"2. Set port ({port})")
        print("3. Start listening")
        print(f"4. Console logging: {'ON' if console_logging else 'OFF'}")
        print("0. Exit")
        op = input(": ").strip()
        print("--------------------")

        match op:
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

            case "4":
                console_logging = not console_logging
                set_console_logging("SERVER", console_logging)

            case "0":
                break

            case _:
                print("Invalid option")

        print("--------------------")


if __name__ == "__main__":
    try:
        settings_menu()
    except (KeyboardInterrupt, EOFError):
        print("\nServer closed")
    finally:
        log_event("SERVER", "Server program closed")
