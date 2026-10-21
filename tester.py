import json
import logging
import socket
import time
import threading
from queue import Queue, Empty

from common import (
    SENSOR_SPECS, generate_sensor_data, validate_sensor_data, validate_ip,
    validate_port, log_event, set_console_logging
)
from protocol import (
    REGISTER, REGISTER_ACK, ACK, DATA, RESEND, KEEPALIVE, KEEPALIVE_ACK, REJECT,
    encode_message, decode_message, calculate_checksum,
    TOKEN_MIN, TOKEN_MAX, AUTO_SEND_INTERVAL, SESSION_TIMEOUT, REPLY_TIMEOUT
)


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

    return message


def send_measurement(sock, server_address, sensor_id, token, message_id, data, sensor_type, corrupt=False):
    source = f"TESTER:{sensor_type}:{sensor_id}"

    data_message = {
        "type": DATA,
        "sensor_id": sensor_id,
        "message_id": message_id,
        "token": token,
        "data": data.copy(),
    }
    data_message["checksum"] = calculate_checksum(data_message)

    message_to_send = data_message

    if corrupt:
        message_to_send = data_message.copy()
        message_to_send["data"] = data.copy()

        parameter = next(iter(data))
        spec = SENSOR_SPECS[sensor_type][parameter]
        damaged_value = spec["min"] if data[parameter] != spec["min"] else spec["max"]
        message_to_send["data"][parameter] = damaged_value

        log_event(source, f"Corrupting next DATA message: {message_id}", level=logging.WARNING)

    raw_data = encode_message(message_to_send)
    sock.sendto(raw_data, server_address)
    log_event(source, f"Sent to {server_address}: {json.dumps(message_to_send)}", "MESSAGE")

    return data_message


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


def finish_request(pending, message_id, error=None):
    request = pending.pop(message_id, None)

    if request is None:
        return

    session = request["session"]

    if request["message"]["type"] == REGISTER:
        session["registering"] = False

    if error is not None:
        source = f"TESTER:{session['sensor_type']}:{session['sensor_id']}"
        log_event(source, error, level=logging.WARNING)

    if request["result"] is not None:
        request["result"].put(error)


def disconnect_sensor(session, pending, reason):
    session["token"] = None
    session["auto_send"] = False
    session["corrupt_next"] = False
    session["registering"] = False
    session["last_server_activity"] = None

    for message_id, request in list(pending.items()):
        if request["session"] is session:
            finish_request(pending, message_id, reason)

    source = f"TESTER:{session['sensor_type']}:{session['sensor_id']}"
    log_event(source, f"SENSOR DISCONNECTED: {reason}")


def start_request(sock, server_address, session, message_id, pending, result=None, data=None):
    if data is None:
        message = register_sensor(
            sock, server_address, session["sensor_type"], session["sensor_id"], message_id
        )
        session["registering"] = True
    else:
        message = send_measurement(
            sock, server_address, session["sensor_id"], session["token"],
            message_id, data, session["sensor_type"], session["corrupt_next"]
        )
        session["corrupt_next"] = False

    pending[message_id] = {
        "session": session,
        "message": message,
        "sent_at": time.monotonic(),
        "attempts": 1,
        "result": result
    }


def handle_command(sock, server_address, command, message_id, pending):
    action, session, data, result = command
    source = f"TESTER:{session['sensor_type']}:{session['sensor_id']}"

    if action == "register":
        if session["token"] is not None or session["registering"]:
            raise ValueError("Sensor is already registered or registration is pending")

        start_request(sock, server_address, session, message_id, pending, result)
        return

    if action == "disconnect":
        if session["token"] is None and not session["registering"]:
            raise ValueError("Sensor is already disconnected")

        disconnect_sensor(session, pending, "Disconnected locally by user")
        result.put(None)
        return

    if session["token"] is None:
        raise ValueError("Sensor is disconnected; register it first")

    if action == "toggle_auto":
        session["auto_send"] = not session["auto_send"]

        if session["auto_send"]:
            session["next_send_at"] = time.monotonic() + AUTO_SEND_INTERVAL

        state = "enabled" if session["auto_send"] else "disabled"
        log_event(source, f"Automatic sending {state}")
        result.put(None)

    elif action == "corrupt":
        session["corrupt_next"] = True
        log_event(source, "Corruption enabled for the next DATA message")
        result.put(None)

    elif action == "send":
        validate_sensor_data(session["sensor_type"], data)
        start_request(sock, server_address, session, message_id, pending, result, data)

    else:
        raise ValueError("Unknown command")


def handle_answer(sock, server_address, sessions, pending, answer):
    if answer["type"] == KEEPALIVE:
        session = next((item for item in sessions if item["sensor_id"] == answer["sensor_id"]), None)

        if session is None or session["token"] is None:
            return

        if answer["token"] != session["token"]:
            return

        session["last_server_activity"] = time.monotonic()

        response = {
            "type": KEEPALIVE_ACK,
            "sensor_id": session["sensor_id"],
            "message_id": answer["message_id"],
            "token": session["token"]
        }

        source = f"TESTER:{session['sensor_type']}:{session['sensor_id']}"
        sock.sendto(encode_message(response), server_address)
        log_event(source, f"Sent to {server_address}: {json.dumps(response)}", "MESSAGE")
        return

    request = pending.get(answer["message_id"])

    if request is None:
        return

    session = request["session"]
    message = request["message"]
    source = f"TESTER:{session['sensor_type']}:{session['sensor_id']}"

    if answer["type"] == REJECT:
        finish_request(pending, answer["message_id"], f"Server rejected request: {answer['reason']}")
        return

    if message["type"] == REGISTER:
        if answer["type"] != REGISTER_ACK:
            return

        if not TOKEN_MIN <= answer["token"] <= TOKEN_MAX:
            raise ValueError("Invalid registration token")

        session["token"] = answer["token"]
        session["auto_send"] = True
        session["corrupt_next"] = False
        session["next_send_at"] = time.monotonic() + AUTO_SEND_INTERVAL
        session["last_server_activity"] = time.monotonic()

        log_event(source, "Sensor registered; automatic sending enabled")
        finish_request(pending, answer["message_id"])
        return

    if answer["type"] not in (ACK, RESEND) or answer["token"] != message["token"]:
        return

    if answer["type"] == ACK:
        session["last_server_activity"] = time.monotonic()
        finish_request(pending, answer["message_id"])
        return

    if request["attempts"] >= 3:
        finish_request(pending, answer["message_id"], "Server still rejects the measurement after 3 attempts")
        return

    sock.sendto(encode_message(message), server_address)
    log_event(source, f"Sent to {server_address}: {json.dumps(message)}", "MESSAGE")
    log_event(source, f"Resending original DATA message: {message['message_id']}")

    request["attempts"] += 1
    request["sent_at"] = time.monotonic()


def check_timeouts(sessions, pending):
    now = time.monotonic()

    for session in sessions:
        if session["token"] is not None and now - session["last_server_activity"] >= SESSION_TIMEOUT:
            disconnect_sensor(session, pending, "No server response for 30 seconds")

    for message_id, request in list(pending.items()):
        if now - request["sent_at"] >= REPLY_TIMEOUT:
            finish_request(pending, message_id, "No response within 3 seconds")


def run_sender(sock, server_address, sessions, message_id, commands, stop_event):
    pending = {}

    try:
        while not stop_event.is_set():
            try:
                raw_answer, sender_address = sock.recvfrom(65535)

                if sender_address != server_address:
                    log_event("TESTER", f"Ignored packet from {sender_address}", level=logging.WARNING)
                    continue

                answer = decode_message(raw_answer)
                request = pending.get(answer["message_id"])
                session = request["session"] if request is not None else None

                if answer["type"] == KEEPALIVE:
                    session = next((item for item in sessions if item["sensor_id"] == answer["sensor_id"]), None)

                source = f"TESTER:{session['sensor_type']}:{session['sensor_id']}" if session else "TESTER"
                log_event(source, f"Received from {sender_address}: {json.dumps(answer)}", "MESSAGE")
                handle_answer(sock, server_address, sessions, pending, answer)

            except socket.timeout:
                pass
            except (ValueError, OSError) as error:
                log_event("TESTER", f"Receive error: {error}", level=logging.WARNING)

            check_timeouts(sessions, pending)

            try:
                command = commands.get_nowait()
            except Empty:
                command = None

            if command is not None:
                try:
                    handle_command(sock, server_address, command, message_id, pending)
                except (ValueError, OSError) as error:
                    command[3].put(str(error))
                    session = command[1]
                    source = f"TESTER:{session['sensor_type']}:{session['sensor_id']}"
                    log_event(source, f"Command failed: {error}", level=logging.WARNING)

                message_id += 1

            for session in sessions:
                if session["token"] is None or not session["auto_send"]:
                    continue

                now = time.monotonic()

                if now < session["next_send_at"]:
                    continue

                session["next_send_at"] = now + AUTO_SEND_INTERVAL
                data = generate_sensor_data(session["sensor_type"])

                try:
                    start_request(sock, server_address, session, message_id, pending, data=data)
                except (ValueError, OSError) as error:
                    source = f"TESTER:{session['sensor_type']}:{session['sensor_id']}"
                    log_event(source, f"Send failed: {error}", level=logging.WARNING)

                message_id += 1

    finally:
        stop_event.set()

        for pending_id in list(pending):
            finish_request(pending, pending_id, "Tester stopped")


def wait_for_result(result, stop_event):
    while not stop_event.is_set():
        try:
            return result.get(timeout=0.2)
        except Empty:
            continue

    return "Tester stopped"


def tester_menu(sessions, commands, stop_event):
    actions = {
        "1": "send",
        "2": "corrupt",
        "3": "toggle_auto",
        "4": "disconnect",
        "5": "register"
    }

    while not stop_event.is_set():
        print("TESTER - sensor control")
        print("1. Send custom measurement")
        print("2. Corrupt next measurement")
        print("3. Enable/disable automatic sending")
        print("4. Disconnect sensor locally")
        print("5. Register disconnected sensor")
        print("0. Exit")
        op = input(": ").strip()

        if op == "0":
            return

        if op not in actions:
            print("Invalid option")
            continue

        for i, session in enumerate(sessions):
            if session["registering"]:
                state = "registering"
            elif session["token"] is None:
                state = "disconnected"
            else:
                state = "auto ON" if session["auto_send"] else "auto OFF"

            print(f"{i + 1}. {session['sensor_type']} ({session['sensor_id']}) - {state}")

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
        action = actions[op]
        data = None

        if action == "send":
            if session["token"] is None:
                print("Sensor is disconnected; register it first")
                continue

            data = input_sensor_data(session["sensor_type"])

            if data is None:
                continue

        result = Queue()
        commands.put((action, session, data, result))
        error = wait_for_result(result, stop_event)

        if error is not None:
            print(error)
        elif action == "send":
            print("Custom measurement confirmed by server")
        elif action == "corrupt":
            print(f"Next measurement for {session['sensor_id']} will be corrupted")
        elif action == "toggle_auto":
            state = "ON" if session["auto_send"] else "OFF"
            print(f"Automatic sending for {session['sensor_id']}: {state}")
        elif action == "disconnect":
            print(f"Sensor {session['sensor_id']} disconnected locally")
        elif action == "register":
            print(f"Sensor {session['sensor_id']} registered; automatic sending enabled")


def main(server_address: tuple, sensors: list):
    if not sensors:
        print("Add at least one sensor first")
        return

    log_event("TESTER", f"Tester started for server {server_address}")
    sessions = []

    for sensor in sensors:
        sessions.append({
            "sensor_type": sensor,
            "sensor_id": f"{sensor[0]}-{len(sessions)}",
            "token": None,
            "registering": False,
            "auto_send": False,
            "corrupt_next": False,
            "next_send_at": 0,
            "last_server_activity": None
        })

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as tester_socket:
        tester_socket.bind(("0.0.0.0", 0))
        tester_socket.settimeout(0.05)
        commands = Queue()
        stop_event = threading.Event()
        sender = threading.Thread(
            target=run_sender,
            args=(tester_socket, server_address, sessions, 1, commands, stop_event)
        )
        sender.start()

        try:
            for session in sessions:
                result = Queue()
                commands.put(("register", session, None, result))
                error = wait_for_result(result, stop_event)

                if error is not None:
                    print(f"Registration failed for {session['sensor_id']}: {error}")

            tester_menu(sessions, commands, stop_event)

        except (KeyboardInterrupt, EOFError):
            pass
        finally:
            stop_event.set()
            sender.join()
            log_event("TESTER", "Tester stopped")


def settings_menu():
    log_event("TESTER", "Tester program started")
    ip = "127.0.0.1"
    port = 25565
    console_logging = False
    sensors = []

    while True:
        print("TESTER")
        print(f"1. Set server IP ({ip})")
        print(f"2. Set server port ({port})")
        print(f"3. Add sensors (configured: {len(sensors)})")
        if sensors:
            print("   " + ", ".join(sensors))
        print("4. Start")
        print(f"5. Console logging: {'ON' if console_logging else 'OFF'}")
        print("0. Exit")
        op = input(": ").strip()
        print("--------------------")

        match op:
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
                print("Choose sensors (repeat a number to add another of the same type):")

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

            case "5":
                console_logging = not console_logging
                set_console_logging("TESTER", console_logging)

            case "0":
                break

            case _:
                print("Invalid option")

        print("--------------------")


if __name__ == "__main__":
    try:
        settings_menu()
    except (KeyboardInterrupt, EOFError):
        print("\nTester closed")
    finally:
        log_event("TESTER", "Tester program closed")
