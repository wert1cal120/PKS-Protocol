import json
import logging
import socket
import time
import threading
from queue import Queue, Empty

from common import generate_sensor_data, SENSOR_SPECS, validate_ip, validate_port, log_event, validate_sensor_data
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


def input_sensor_data(sensor_type: str):
    data = {}

    print("Enter values for all parameters. Enter q to cancel.")

    for name, spec in SENSOR_SPECS[sensor_type].items():
        min_value = spec["min"]
        max_value = spec["max"]
        decimals = spec["decimals"]

        while True:
            text = input(f"{name} ({min_value} to {max_value}, decimals: {decimals}): ").strip()

            if text.lower() == "q":
                return None

            try:
                value = int(text) if decimals == 0 else float(text)

                if not (min_value <= value <= max_value and value == round(value, decimals)):
                    raise ValueError("Value is outside the range or has too many decimal places")

                data[name] = value
                break
            except ValueError as error:
                print(f"Invalid value: {error}")

    validate_sensor_data(sensor_type, data)
    return data


def run_sender(sock, server_address, sessions, message_id, commands, stop_event):
    while not stop_event.is_set():
        pending = []

        try:
            pending.append(commands.get_nowait())
        except Empty:
            pass

        for session in sessions:
            now = time.monotonic()

            if session["auto_send"] and now >= session["next_send_at"]:
                data = generate_sensor_data(session["sensor_type"])
                pending.append((session, data, None))
                session["next_send_at"] = now + 10

        for session, data, result in pending:
            if stop_event.is_set():
                break

            source = f"TESTER:{session['sensor_type']}:{session['sensor_id']}"
            current_id = message_id
            message_id += 1
            error_message = None

            try:
                send_measurement(
                    sock, server_address, session["sensor_id"], session["token"],
                    current_id, data, session["sensor_type"]
                )
            except (ValueError, OSError) as error:
                error_message = f"Measurement was not confirmed: {error}"
                log_event(source, error_message, level=logging.ERROR)

            if result is not None:
                result.put(error_message)

        stop_event.wait(0.05)


def tester_menu(sessions, commands, stop_event):
    while not stop_event.is_set():
        print("TESTER - automatic sending is active")
        print("1. Send custom measurement")
        print("0. Exit")
        op = input(": ").strip()

        match op:
            case "1":
                for i, session in enumerate(sessions):
                    print(f"{i + 1}. {session['sensor_type']} ({session['sensor_id']})")

                try:
                    choice = int(input("Choose sensor (0 to cancel): "))

                    if choice == 0:
                        continue

                    if not 1 <= choice <= len(sessions):
                        raise ValueError("Invalid sensor number")

                except ValueError as error:
                    print(f"Invalid selection: {error}")
                    continue

                session = sessions[choice - 1]
                data = input_sensor_data(session["sensor_type"])

                if data is None:
                    continue

                result = Queue()
                commands.put((session, data, result))

                while not stop_event.is_set():
                    try:
                        error_message = result.get(timeout=0.2)

                        if error_message is None:
                            print("Custom measurement confirmed by server")
                        else:
                            print(error_message)

                        break
                    except Empty:
                        continue

            case "0":
                return

            case _:
                print("Invalid option")


def main(server_address: tuple, sensors: list):
    source = "TESTER"

    if not sensors:
        print("Add at least one sensor first")
        return

    log_event(source, f"Tester started for server {server_address}")
    sessions = []

    for sensor in sensors:
        sessions.append(
            {"sensor_type": sensor, "sensor_id": f"{sensor[0]}-{len(sessions)}", "token": None}
        )

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as tester_socket:
        tester_socket.settimeout(3.0)
        message_id = 1

        try:
            for session in sessions:
                sensor_type = session["sensor_type"]
                sensor_id = session["sensor_id"]

                source = f"TESTER:{sensor_type}:{sensor_id}"

                session["token"] = register_sensor(tester_socket, server_address, sensor_type, sensor_id, message_id)
                message_id += 1

                session["auto_send"] = True
                session["next_send_at"] = time.monotonic() + 10

                log_event(source, "Sensor registered; automatic sending enabled")
        except (ValueError, OSError) as error:
            log_event(source, f"Registration failed: {error}", level=logging.ERROR)

            print(f"Registration failed: {error}")
            return

        commands = Queue()
        stop_event = threading.Event()
        sender = threading.Thread(
            target=run_sender,
            args=(tester_socket, server_address, sessions, message_id, commands, stop_event)
        )
        sender.start()

        try:
            tester_menu(sessions, commands, stop_event)
        except (KeyboardInterrupt, EOFError):
            pass
        finally:
            stop_event.set()
            sender.join()
            log_event("TESTER", "Tester stopped")


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
                print("Choose sensors:")

                available_sensors_list = list(SENSOR_SPECS.keys())

                for i, sensor in enumerate(available_sensors_list):
                    print(f"\t {i+1} - {sensor}")
                new_sensors = input("Enter numbers of sensors (1234): ").strip()
                if not new_sensors or any(number not in "1234" for number in new_sensors):
                    print("Enter only sensor numbers from 1 to 4")
                    continue

                for sensor in new_sensors:
                    sensors.append(available_sensors_list[int(sensor)-1])

            case "4":
                if not sensors:
                    print("Add at least one sensor first")
                    continue
                try:
                    main((ip, port), sensors)
                except KeyboardInterrupt:
                    log_event("TESTER", "Tester stopped")
                except OSError as error:
                    print(f"Socket error: {error}")
                    log_event("TESTER", f"Socket error: {error}", level=logging.ERROR)
                break

            case "0":
                break

        print("--------------------")

    log_event("TESTER", "Tester program closed")
