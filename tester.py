import socket

from protocol import REGISTER, encode_message, decode_message, REGISTER_ACK, TOKEN_MIN, TOKEN_MAX

#TODO REJECT ANSWER HANDLER
def main():
    server_address = ("127.0.0.1", 25565)

    message = {
        "type": REGISTER,
        "sensor_type": "ThermoNode",
        "sensor_id": "T-01",
        "message_id": 1,
    }

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as tester_socket:
        tester_socket.settimeout(3.0)

        try:
            raw_data = encode_message(message)
            tester_socket.sendto(raw_data, server_address)
            print("Registration request sent")

            raw_answer, sender_address = tester_socket.recvfrom(65535)

            if sender_address != server_address:
                raise ValueError("Invalid server address")

            answer = decode_message(raw_answer)

            if answer["type"] != REGISTER_ACK:
                raise ValueError("Invalid answer for registration")

            if answer["message_id"] != message["message_id"]:
                raise ValueError("Invalid message id")

            if not (TOKEN_MIN <= answer["token"] <= TOKEN_MAX):
                raise ValueError("Invalid token")

        except socket.timeout:
            print("Registration timed out: no response within 3 seconds")
            return

        except ValueError as error:
            print(f"Invalid data from {sender_address}: {error}")
            return

        except OSError as error:
            print(f"Socket error: {error}")
            return

        token = answer["token"]
        print(f"Tester successfully registered with token: {token}")

if __name__ == "__main__":
    main()

