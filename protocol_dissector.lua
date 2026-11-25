local protocol = Proto("protocol", "Protocol")
local PORT = 25565

local message_names = {
    [0] = "REGISTER",
    [1] = "REGISTER_ACK",
    [2] = "DATA",
    [3] = "ACK",
    [4] = "RESEND",
    [5] = "KEEPALIVE",
    [6] = "KEEPALIVE_ACK",
    [7] = "REJECT"
}

local sensor_names = {
    [0] = "ThermoNode",
    [1] = "WindSense",
    [2] = "RainDetect",
    [3] = "AirQuality"
}

local f_type = ProtoField.uint8("protocol.type", "Message type", base.DEC, message_names)
local f_id = ProtoField.uint16("protocol.id", "Message ID", base.DEC)
local f_token = ProtoField.uint16("protocol.token", "Token", base.DEC)
local f_sensor = ProtoField.uint8("protocol.sensor", "Sensor type", base.DEC, sensor_names)
local f_id_length = ProtoField.uint8("protocol.id_length", "Sensor ID length", base.DEC)
local f_sensor_id = ProtoField.string("protocol.sensor_id", "Sensor ID")
local f_reason = ProtoField.uint8("protocol.reason", "Reject reason", base.DEC)
local f_data = ProtoField.bytes("protocol.data", "Packed data")
local f_crc = ProtoField.uint16("protocol.crc", "CRC", base.HEX)
local f_crc_status = ProtoField.string("protocol.crc_status", "CRC check")
local f_error = ProtoField.string("protocol.error", "Problem")

local temperature = ProtoField.double("protocol.temperature", "Temperature")
local humidity = ProtoField.double("protocol.humidity", "Humidity")
local dew_point = ProtoField.double("protocol.dew_point", "Dew point")
local pressure = ProtoField.double("protocol.pressure", "Pressure")
local wind_speed = ProtoField.double("protocol.wind_speed", "Wind speed")
local wind_gust = ProtoField.double("protocol.wind_gust", "Wind gust")
local wind_direction = ProtoField.double("protocol.wind_direction", "Wind direction")
local turbulence = ProtoField.double("protocol.turbulence", "Turbulence")
local rainfall = ProtoField.double("protocol.rainfall", "Rainfall")
local soil_moisture = ProtoField.double("protocol.soil_moisture", "Soil moisture")
local flood_risk = ProtoField.double("protocol.flood_risk", "Flood risk")
local rain_duration = ProtoField.double("protocol.rain_duration", "Rain duration")
local co2 = ProtoField.double("protocol.co2", "CO2")
local ozone = ProtoField.double("protocol.ozone", "Ozone")
local air_quality_index = ProtoField.double("protocol.air_quality_index", "Air quality index")

protocol.fields = {
    f_type, f_id, f_token, f_sensor, f_id_length, f_sensor_id,
    f_reason, f_data, f_crc, f_crc_status, f_error,
    temperature, humidity, dew_point, pressure,
    wind_speed, wind_gust, wind_direction, turbulence,
    rainfall, soil_moisture, flood_risk, rain_duration,
    co2, ozone, air_quality_index
}

local layouts = {
    [0] = {6, 47, {
        {temperature, 11, 10, -50}, {humidity, 10, 10, 0},
        {dew_point, 11, 10, -50}, {pressure, 15, 100, 800}
    }},
    [1] = {4, 32, {
        {wind_speed, 9, 10, 0}, {wind_gust, 10, 10, 0},
        {wind_direction, 9, 1, 0}, {turbulence, 4, 10, 0}
    }},
    [2] = {4, 31, {
        {rainfall, 13, 10, 0}, {soil_moisture, 10, 10, 0},
        {flood_risk, 2, 1, 0}, {rain_duration, 6, 1, 0}
    }},
    [3] = {5, 35, {
        {co2, 13, 1, 300}, {ozone, 13, 10, 0},
        {air_quality_index, 9, 1, 0}
    }}
}

local function add_error(tree, text)
    tree:add(f_error, text)
end

local function read_bits(packet, start_bit, count)
    local value = 0

    for i = 0, count - 1 do
        local bit_number = start_bit + i
        local byte = packet(6 + math.floor(bit_number / 8), 1):uint()
        local shift = 7 - (bit_number % 8)
        value = value * 2 + math.floor(byte / (2 ^ shift)) % 2
    end

    return value
end

local function xor16(a, b)
    local result = 0
    local place = 1

    for i = 1, 16 do
        if a % 2 ~= b % 2 then result = result + place end
        a = math.floor(a / 2)
        b = math.floor(b / 2)
        place = place * 2
    end

    return result
end

local function crc16(packet, count)
    local crc = 0xFFFF

    for i = 0, count - 1 do
        crc = xor16(crc, packet(i, 1):uint() * 256)

        for j = 1, 8 do
            local high_bit = crc >= 0x8000
            crc = (crc * 2) % 65536
            if high_bit then crc = xor16(crc, 0x1021) end
        end
    end

    return crc
end

function protocol.dissector(packet, pinfo, tree)
    local length = packet:len()
    if length < 1 then return end

    local code = packet(0, 1):uint()
    local name = message_names[code] or "Unknown"
    pinfo.cols.protocol = "Protocol"
    pinfo.cols.info = name

    local root = tree:add(protocol, packet(), "Protocol: " .. name)
    root:add(f_type, packet(0, 1))

    if length < 3 then
        add_error(root, "Packet is too short")
        return
    end

    root:add(f_id, packet(1, 2))

    if code == 0 then
        if length < 5 then
            add_error(root, "REGISTER is too short")
            return
        end

        local id_length = packet(4, 1):uint()
        root:add(f_sensor, packet(3, 1))
        root:add(f_id_length, packet(4, 1))

        if id_length < 1 or id_length > 32 then
            add_error(root, "Bad Sensor ID length")
        elseif length == 5 + id_length then
            root:add(f_sensor_id, packet(5, id_length))
        else
            add_error(root, "REGISTER length is wrong")
        end

    elseif code == 2 then
        if length < 8 then
            add_error(root, "DATA is too short")
            return
        end

        root:add(f_token, packet(3, 2))
        root:add(f_sensor, packet(5, 1))

        local sensor = packet(5, 1):uint()
        local layout = layouts[sensor]
        local crc_offset = length - 2
        local sent_crc = packet(crc_offset, 2):uint()

        root:add(f_crc, packet(crc_offset, 2))
        local ok = crc16(packet, crc_offset) == sent_crc
        root:add(f_crc_status, ok and "OK" or "BAD")
        if not ok then add_error(root, "CRC mismatch") end

        if layout == nil then
            add_error(root, "Unknown sensor type")
            return
        end

        if length ~= 8 + layout[1] then
            add_error(root, "DATA length is wrong")
            return
        end

        root:add(f_data, packet(6, layout[1]))

        local bit_position = 0
        for _, field in ipairs(layout[3]) do
            local raw = read_bits(packet, bit_position, field[2])
            bit_position = bit_position + field[2]
            root:add(field[1], field[4] + raw / field[3])
        end

    elseif code == 7 then
        if length == 4 then
            root:add(f_reason, packet(3, 1))
        else
            add_error(root, "REJECT must be 4 bytes")
        end

    elseif code >= 1 and code <= 6 then
        if length == 5 then
            root:add(f_token, packet(3, 2))
        else
            add_error(root, "Message must be 5 bytes")
        end

    else
        add_error(root, "Unknown message type")
    end
end

DissectorTable.get("udp.port"):add(PORT, protocol)