from protocol import REGISTER, REGISTER_ACK, DATA, ACK

def handle_register(message):
    # Handle registration message
    pass

handlers = {
    REGISTER: handle_registration,
    REGISTER_ACK: "",
    DATA: "",
    ACK: ""
}