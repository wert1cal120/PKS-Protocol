import socket

from protocol import REGISTER, REGISTER_ACK, DATA, ACK, decode_message

def main():
    host = "127.0.0.1"
    port = 25565

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


def handle_register(message):
    # Handle registration message
    pass

handlers = {
    REGISTER: handle_register,
    REGISTER_ACK: "",
    DATA: "",
    ACK: ""
}

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Server stopped")
    except OSError as error:
        print(f"Socket error: {error}")