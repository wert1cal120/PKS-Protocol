import json
import logging
import socket
import time

from common import generate_sensor_data, SENSOR_SPECS, validate_ip, validate_port, log_event
from protocol import REGISTER, encode_message, decode_message, REGISTER_ACK, TOKEN_MIN, TOKEN_MAX, ACK, DATA

def register_sensor(sock, server_address, sensor_type, sensor_id, message_id):
    source = f"TESTER:{sensor_type}:{sensor_id}"
    message = {
        "type": REGISTER,
        "sensor_type": sensor_type,
        "sensor_id": sensor_id,
        "message_id": message_id,
    }

    raw_data = encode_message(message)
    sock.sendto(raw_data, server_address)
    log_event(source, f"Sent to {server_address}: {json.dumps(message)}", "MESSAGE")

    raw_answer, sender_address = sock.recvfrom(65535)

    answer = decode_message(raw_answer)
    log_event(source, f"Received from {sender_address}: {json.dumps(answer)}", "MESSAGE")

    if sender_address != server_address:
        raise ValueError("Invalid server address")

    if answer["type"] != REGISTER_ACK:
        raise ValueError("Invalid answer for registration")

    if answer["message_id"] != message["message_id"]:
        raise ValueError("Invalid message id")

    if not (TOKEN_MIN <= answer["token"] <= TOKEN_MAX):
        raise ValueError("Invalid token")

    return answer["token"]

def send_measurement(sock, server_address, sensor_id, token, message_id, data, sensor_type):
    source = f"TESTER:{sensor_type}:{sensor_id}"
    data_message = {
        "type": DATA,
        "sensor_id": sensor_id,
        "message_id": message_id,
        "token": token,
        "data": data,
    }

    raw_data = encode_message(data_message)
    sock.sendto(raw_data, server_address)
    log_event(source, f"Sent to {server_address}: {json.dumps(data_message)}", "MESSAGE")

    raw_answer, sender_address = sock.recvfrom(65535)

    answer = decode_message(raw_answer)
    log_event(source, f"Received from {sender_address}: {json.dumps(answer)}", "MESSAGE")

    if sender_address != server_address:
        raise ValueError("Invalid server address")
    if answer["type"] != ACK:
        raise ValueError("Invalid answer for ACK")

    if answer["message_id"] != data_message["message_id"]:
        raise ValueError("Invalid message id")

    if answer["token"] != token:
        raise ValueError("Invalid token")


#TODO REJECT ANSWER HANDLER
def main(server_address: tuple, sensors: list):
    source = "TESTER"
    log_event(source, f"Tester started for server {server_address}")
    sessions = []

    for sensor in sensors:
        sessions.append(
            {"sensor_type": sensor, "sensor_id": f"{sensor[0]}-{len(sessions)}", "token": None}
        )

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as tester_socket:
        tester_socket.settimeout(3.0)

        try:
            message_id = 1
            for session in sessions:
                sensor_type = session["sensor_type"]
                sensor_id = session["sensor_id"]
                source = f"TESTER:{sensor_type}:{sensor_id}"

                session["token"] = register_sensor(tester_socket, server_address, sensor_type, sensor_id, message_id)
                message_id += 1

                session["auto_send"] = True
                session["next_send_at"] = time.monotonic() + 10
                log_event(source, "Sensor registered; automatic sending enabled")

            while True:
                now = time.monotonic()
                for session in sessions:
                    if not session["auto_send"]:
                        continue

                    if now >= session["next_send_at"]:
                        sensor_type = session["sensor_type"]
                        sensor_id = session["sensor_id"]
                        token = session["token"]
                        source = f"TESTER:{sensor_type}:{sensor_id}"

                        send_measurement(tester_socket, server_address, sensor_id, token, message_id,
                                        generate_sensor_data(sensor_type), sensor_type)
                        message_id += 1

                        session["next_send_at"] = now + 10

                time.sleep(0.05)

        except socket.timeout:
            log_event(source, "Socket timed out: no response within 3 seconds", level=logging.ERROR)
            return

        except ValueError as error:
            log_event(source, f"Invalid message: {error}", level=logging.ERROR)
            return

        except OSError as error:
            log_event(source, f"Socket error: {error}", level=logging.ERROR)
            return

if __name__ == "__main__":
    log_event("TESTER", "Tester program started")
    ip = "127.0.0.1"
    port = 25565
    sensors = []

    while True:
        print("TESTER")
        print(f"1. Set server IP ({ip})")
        print(f"2. Set server port ({port})")
        print(f"3. Add sensor {sensors}")
        print(f"4. Start")
        print(f"0. Exit")
        op = input(": ")
        print("--------------------")

        match (op):
            case "1":
                try:
                    new_ip = input("Enter server IP: ").strip()
                    validate_ip(new_ip)
                    ip = new_ip
                except ValueError as error:
                    print(f"Invalid IP: {error}")
                    log_event("TESTER", f"Invalid IP input: {error}", level=logging.WARNING)

            case "2":
                try:
                    new_port = int(input("Enter server port: "))
                    validate_port(new_port)
                    port = new_port
                except ValueError as error:
                    print(f"Invalid port: {error}")
                    log_event("TESTER", f"Invalid port input: {error}", level=logging.WARNING)

            case "3":
                # TODO ADD VALIDATION!!!
                print("Choose sensors:")

                available_sensors_list = list(SENSOR_SPECS.keys())

                for i, sensor in enumerate(available_sensors_list):
                    print(f"\t {i+1} - {sensor}")
                new_sensors = input("Enter numbers of sensors (1234): ")

                for sensor in new_sensors:
                    sensors.append(available_sensors_list[int(sensor)-1])

            case "4":
                try:
                    main((ip, port), sensors)
                except KeyboardInterrupt:
                    log_event("TESTER", "Tester stopped")
                break

            case "0":
                break

        print("--------------------")

    log_event("TESTER", "Tester program closed")
