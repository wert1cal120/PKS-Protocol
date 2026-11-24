# PKS-Protocol — binary protocol specification

**Status:** initial implementation specification  
**Protocol version:** 1  
**Transport:** one protocol message per UDP datagram  
**Purpose:** compact communication between the sensor tester and the weather server.

This file defines the wire format. Both `server.py` and `tester.py` must follow it. The
Lua Wireshark dissector must decode the same fields and rules. Application logs may use
readable names and JSON-like values; JSON is not sent over the network in version 1.

## 1. General wire rules

- One UDP datagram contains exactly one protocol message. Messages are not split across
  datagrams.
- Multi-byte integers use **big-endian** byte order: the most significant byte is sent
  first. For example, `0x1234` is sent as `12 34`.
- Bits in a byte are written and read from the most significant bit to the least
  significant bit: bit weights `128, 64, 32, 16, 8, 4, 2, 1`.
- Multi-bit sensor values are packed in the field order listed in this document. Each
  field is written most-significant bit first. If the last payload byte is incomplete,
  unused low-order bits are zero.
- Unless stated otherwise, unsigned integer fields use their full binary range.
- This document defines protocol version 1. There is no version byte in the packets.
- Sensor IDs are UTF-8, 1–32 bytes long, nonempty, and contain printable characters.
- Tokens are unsigned 16-bit values in the range `1..65535`. Token `0` is invalid.
- Message IDs are unsigned 16-bit values. A response copies the request's message ID.
- The message ID is chosen by the sender. A sender must not reuse an ID while a request
  with that ID is still pending. A retransmission keeps the original ID.
- A token identifies the active sensor session. The server also checks the sender's UDP
  address and the sensor type associated with that token. The sensor ID is therefore sent
  during registration, not repeated in every data message.
- No sensor timestamp is carried on the wire in version 1. Log timestamps are generated
  locally in UTC and are not part of the protocol packet.

## 2. Message and sensor codes

Every packet starts with a one-byte message code. `REGISTER` and `DATA` also carry a
one-byte sensor code. These are separate bytes; there are no packed control bits.

### Message type codes

| Code | Name | Direction |
|---:|---|---|
| `0x00` | `REGISTER` | tester → server |
| `0x01` | `REGISTER_ACK` | server → tester |
| `0x02` | `DATA` | tester → server |
| `0x03` | `ACK` | server → tester |
| `0x04` | `RESEND` | server → tester |
| `0x05` | `KEEPALIVE` | server → tester |
| `0x06` | `KEEPALIVE_ACK` | tester → server |
| `0x07` | `REJECT` | server → tester |

### Sensor type codes

| Code | Sensor |
|---:|---|
| `0x00` | `ThermoNode` |
| `0x01` | `WindSense` |
| `0x02` | `RainDetect` |
| `0x03` | `AirQuality` |

`REGISTER` carries the sensor code requested by the tester. `DATA` carries the sensor
code needed to decode its measurement fields. Other messages do not carry a sensor code;
the token or message ID identifies the session or request. The server checks the DATA
sensor code against the type registered for that token.

## 3. Shared field definitions

| Field | Width | Encoding |
|---|---:|---|
| `message_type` | 1 byte | Code from the message table above |
| `sensor_type` | 1 byte | Code from the sensor table; present only in REGISTER and DATA |
| `message_id` | 2 bytes | Unsigned 16-bit, big-endian |
| `token` | 2 bytes | Unsigned 16-bit, big-endian; `1..65535` |
| `sensor_id_length` | 1 byte | Number of following UTF-8 bytes; `1..32` |
| `reason_code` | 1 byte | Code from the REJECT table |
| `crc` | 2 bytes | CRC-16/CCITT-FALSE, big-endian |

The CRC parameters are: polynomial `0x1021`, initial value `0xFFFF`, input reflected
`false`, output reflected `false`, final XOR `0x0000`. The CRC covers every DATA byte
from `message_type` through the final padded payload byte. The CRC field itself is excluded.

## 4. Message layouts

The byte offsets below are zero-based. Variable and packed fields follow immediately
after the listed fields; there is no alignment padding except the zero low-order bits
needed to complete the final packed DATA byte.

### 4.1 REGISTER — tester requests a session

```text
+-------------+----------------------+-----------------+--------------------+---------------------+
| message_type| message_id (2 bytes)| sensor_type (1) | sensor_id_length   | sensor_id (N bytes) |
+-------------+----------------------+-----------------+--------------------+---------------------+
```

| Offset | Field | Width | Rule |
|---:|---|---:|---|
| 0 | `message_type` | 1 byte | `0x00` |
| 1–2 | `message_id` | 2 bytes | New tester request ID |
| 3 | `sensor_type` | 1 byte | Code from the sensor table |
| 4 | `sensor_id_length` | 1 byte | UTF-8 byte count, 1–32 |
| 5… | `sensor_id` | N bytes | UTF-8 ID |

The server rejects an ID that is already active. On success it creates a session and
returns a new token in `REGISTER_ACK`.

### 4.2 REGISTER_ACK — server grants a session

```text
+-------------+----------------------+--------------------+
| message_type| message_id (2 bytes)| token (2 bytes)    |
+-------------+----------------------+--------------------+
```

Length: 5 bytes. The message ID is copied from `REGISTER`; the token is newly assigned
by the server and must be nonzero.

### 4.3 DATA — tester sends a measurement

```text
+-------------+----------------------+--------------------+-----------------+------------------+----------+
| message_type| message_id (2 bytes)| token (2 bytes)    | sensor_type (1) | packed data      | CRC (2)  |
+-------------+----------------------+--------------------+-----------------+------------------+----------+
```

The `sensor_type` byte selects the packed data layout in Section 5. The server
validates the token, sender address, sensor type, CRC, and decoded value ranges before
accepting the measurement.

| Sensor | Packed data | Total DATA length |
|---|---:|---:|
| ThermoNode | 6 bytes | 14 bytes |
| WindSense | 4 bytes | 12 bytes |
| RainDetect | 4 bytes | 12 bytes |
| AirQuality | 5 bytes | 13 bytes |

Length includes the one-byte message type, two-byte message ID, two-byte token, one-byte
sensor type, packed data, and two-byte CRC.

### 4.4 ACK — server accepted a measurement

```text
+-------------+----------------------+--------------------+
| message_type| message_id (2 bytes)| token (2 bytes)    |
+-------------+----------------------+--------------------+
```

Length: 5 bytes. It acknowledges the DATA request with the same message ID and session
token. An ACK is sent only after the DATA CRC and measurement values have been accepted.

### 4.5 RESEND — server requests a clean retransmission

```text
+-------------+----------------------+--------------------+
| message_type| message_id (2 bytes)| token (2 bytes)    |
+-------------+----------------------+--------------------+
```

Length: 5 bytes. Sent when a DATA packet has a bad CRC. The tester retransmits the
original uncorrupted DATA using the same message ID, token, values, and CRC. RESEND is
not used for an invalid token or out-of-range sensor values; those are rejected.

### 4.6 KEEPALIVE — server checks an idle sensor

```text
+-------------+----------------------+--------------------+
| message_type| message_id (2 bytes)| token (2 bytes)    |
+-------------+----------------------+--------------------+
```

Length: 5 bytes. Sent after 15 seconds without accepted DATA, then every 5 seconds while
checking an idle session. The server sends at most three unanswered KEEPALIVE messages.
It waits 5 seconds after the third; if there is still no response, it removes the
session and invalidates the token (30 seconds after the last accepted DATA).

### 4.7 KEEPALIVE_ACK — tester confirms it is active

```text
+-------------+----------------------+--------------------+
| message_type| message_id (2 bytes)| token (2 bytes)    |
+-------------+----------------------+--------------------+
```

Length: 5 bytes. It copies the KEEPALIVE message ID and token. The tester answers even
when automatic measurement sending is disabled. The server accepts it only for the
matching active session and pending KEEPALIVE ID.

### 4.8 REJECT — server declines a request

```text
+-------------+----------------------+--------------------+
| message_type| message_id (2 bytes)| reason_code        |
+-------------+----------------------+--------------------+
```

Length: 4 bytes. The message ID identifies the rejected request. The reason is a stable
one-byte code; human-readable text is produced by the programs' logs.

| Code | Meaning |
|---:|---|
| `0x01` | Sensor ID is already registered |
| `0x02` | No tokens are available |
| `0x03` | No active session for this sensor |
| `0x04` | Invalid token |
| `0x05` | Sender address does not match the session |
| `0x06` | Sensor value is out of range or has invalid precision |
| `0x07` | Message is not valid for the current session state |
| `0x08` | Reused message ID has different DATA content |

Malformed packets whose message ID cannot safely be read are dropped and logged; the
server does not attempt to construct a REJECT for them.

## 5. Sensor value encoding

All numeric values are validated against their specified range and decimal precision
before encoding. Decimal values are scaled to integers; ranges are offset so that the
minimum valid value encodes as zero. For example, `temperature = 21.3` becomes
`(21.3 - (-50.0)) * 10 = 713`.

Fields are concatenated in the order shown. Each value is an unsigned integer occupying
the listed number of bits. The packed payload is the minimum whole number of bytes; any
unused low-order bits in its last byte are zero.

### ThermoNode — 47 bits, padded to 6 bytes

| Order | Field | Range / step | Encoded integer | Bits |
|---:|---|---|---|---:|
| 1 | `temperature` | -50.0..60.0, step 0.1 | `(value + 50.0) * 10` | 11 |
| 2 | `humidity` | 0.0..100.0, step 0.1 | `value * 10` | 10 |
| 3 | `dew_point` | -50.0..60.0, step 0.1 | `(value + 50.0) * 10` | 11 |
| 4 | `pressure` | 800.00..1100.00, step 0.01 | `(value - 800.00) * 100` | 15 |

### WindSense — 32 bits, 4 bytes

| Order | Field | Range / step | Encoded integer | Bits |
|---:|---|---|---|---:|
| 1 | `wind_speed` | 0.0..50.0, step 0.1 | `value * 10` | 9 |
| 2 | `wind_gust` | 0.0..70.0, step 0.1 | `value * 10` | 10 |
| 3 | `wind_direction` | 0..359, step 1 | `value` | 9 |
| 4 | `turbulence` | 0.0..1.0, step 0.1 | `value * 10` | 4 |

### RainDetect — 31 bits, padded to 4 bytes

| Order | Field | Range / step | Encoded integer | Bits |
|---:|---|---|---|---:|
| 1 | `rainfall` | 0.0..500.0, step 0.1 | `value * 10` | 13 |
| 2 | `soil_moisture` | 0.0..100.0, step 0.1 | `value * 10` | 10 |
| 3 | `flood_risk` | 0..3, step 1 | `value` | 2 |
| 4 | `rain_duration` | 0..60, step 1 | `value` | 6 |

### AirQuality — 35 bits, padded to 5 bytes

| Order | Field | Range / step | Encoded integer | Bits |
|---:|---|---|---|---:|
| 1 | `co2` | 300..5000, step 1 | `value - 300` | 13 |
| 2 | `ozone` | 0.0..500.0, step 0.1 | `value * 10` | 13 |
| 3 | `air_quality_index` | 0..500, step 1 | `value` | 9 |

## 6. CRC, retransmission, and duplicate handling

### Corrupted DATA

1. The tester constructs DATA and calculates CRC over all bytes except the CRC field.
2. For the corruption demonstration, the tester changes a payload bit after calculating
   CRC, leaving the original CRC in place.
3. The server detects the mismatch, does not accept or log the measurement as valid, and
   sends `RESEND` with the same message ID and token.
4. The tester resends the saved original DATA unchanged. The server validates and accepts
   it, then sends `ACK`.

### Missing ACK (UAT 5)

1. The tester sends DATA and waits 3 seconds for its ACK.
2. If no ACK arrives, it retransmits the identical DATA bytes. The message ID, token,
   payload, and CRC do not change.
3. There are at most three sends in total: the original plus two retransmissions. After
   another 3-second wait without ACK, the tester drops the pending request and logs the
   timeout.
4. The server keeps the most recently accepted DATA message ID and CRC for each session.
   If the same ID and CRC arrive again, it sends ACK again without recording the
   measurement a second time. The same ID with different DATA content is rejected with
   reason `0x08`.
5. To demonstrate UAT 5, the server can be configured to suppress ACKs for the next N
   DATA messages from a selected sensor. Suppressed ACKs do not change the server's
   acceptance or duplicate-detection behavior.

## 7. Session and timer behavior

- A sensor must register before sending DATA.
- The server assigns a nonzero token and binds it to sensor ID, sensor type, and sender
  UDP address for that session.
- DATA with an unknown, expired, or mismatched token is rejected.
- Accepted DATA resets the server's idle timer and KEEPALIVE retry count.
- When no DATA has been accepted for 15 seconds, the server logs `SENSOR IDLE` and sends
  the first KEEPALIVE. Further KEEPALIVE messages are sent every 5 seconds.
- The tester answers KEEPALIVE even while automatic DATA sending is disabled.
- After three unanswered KEEPALIVE messages and a final 5-second wait, the server logs
  `SENSOR DISCONNECTED`, removes the session, and invalidates its token.
- The tester ends its local session after 30 seconds without server activity. A new
  registration creates a new server session and token.

## 8. Illustrative message examples

These are field-level examples, not literal hex dumps. The implementation and dissector
must use the byte layouts above. Version 1 is described here; it is not sent in packets.

| Message | Example field values |
|---|---|
| `REGISTER` | type `REGISTER`, sensor `ThermoNode`, ID `T-0`, message ID 1 |
| `REGISTER_ACK` | type `REGISTER_ACK`, message ID 1, token 1234 |
| `DATA` | type `DATA`, sensor `ThermoNode`, message ID 2, token 1234, values `{temperature: 21.3, humidity: 55.4, dew_point: 11.9, pressure: 1013.25}`, valid CRC |
| `ACK` | type `ACK`, message ID 2, token 1234 |
| `RESEND` | type `RESEND`, message ID 2, token 1234 |
| `KEEPALIVE` | type `KEEPALIVE`, message ID 7, token 1234 |
| `KEEPALIVE_ACK` | type `KEEPALIVE_ACK`, message ID 7, token 1234 |
| `REJECT` | type `REJECT`, message ID 3, reason `0x04` (invalid token) |

## 9. Implementation checklist

- [ ] Implement bit/byte packing and unpacking exactly as specified.
- [ ] Validate exact packet length for each message and sensor type.
- [ ] Validate message type, sensor type, token, ID length, ranges, and decimal precision.
- [ ] Add CRC-16/CCITT-FALSE generation and verification for DATA.
- [ ] Keep readable structured values for logs while sending only binary packets.
- [ ] Ensure retries use the saved original DATA bytes and do not create a new message ID.
- [ ] Ensure duplicate DATA is ACKed but accepted/logged only once.
- [ ] Implement every message type in the Lua dissector.
- [ ] Add literal hex test vectors for all message types, especially packed DATA and CRC,
  before relying on Wireshark captures.
