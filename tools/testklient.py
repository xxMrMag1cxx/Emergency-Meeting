"""
En låtsas-Among Us som testar servern utan att man behöver spelet.

Starta servern i ett Terminal-fönster, och kör sedan i ett annat:

    python3 tools/testklient.py

Testklienten gör samma saker som spelet gör när man trycker "Create Game":
  1. hämtar en token via HTTP
  2. frågar var spelet ska skapas
  3. skickar Hello via UDP
  4. skickar HostGame
  5. väntar på svar och skriver ut vad servern sa
"""

import json
import socket
import struct
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import protocol  # noqa: E402
from server.messages import MessageReader, MessageWriter  # noqa: E402

HOST = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 22023
NAME = "Testis"
# Samma version som Among Us 17.4 skickar internt
VERSION = protocol.encode_game_version(2026, 3, 18)


def http(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(f"http://{HOST}:{PORT}{path}", data=data, method=method)
    request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.read().decode()


def build_hello():
    w = MessageWriter()
    w.write_byte(protocol.HELLO)
    w.write_uint16(0)  # paketnummer skrivs om nedan (big-endian)
    w.write_byte(1)  # hazel-version
    w.write_int32(VERSION)
    w.write_string(NAME)
    w.write_uint32(0)  # lastNonceReceived
    w.write_uint32(0)  # språk
    w.write_byte(1)  # chattläge
    w.start_message(2)  # plattform: Steam
    w.write_string("TestDator")
    w.end_message()
    w.write_int32(0)  # crossplayFlags
    w.write_byte(0)
    packet = bytearray(w.to_bytes())
    packet[1:3] = struct.pack(">H", 1)
    return bytes(packet)


def build_host_game():
    w = MessageWriter()
    w.write_byte(protocol.RELIABLE)
    w.write_bytes(struct.pack(">H", 2))
    w.start_message(protocol.HOST_GAME)
    w.write_bytes(b"\x00" * 8)  # låtsas-spelinställningar
    w.end_message()
    return w.to_bytes()


def main():
    print(f"Testar servern på {HOST}:{PORT}\n")

    print("1. Hämtar token...")
    token = http("POST", "/api/user", {"Puid": "test", "Username": NAME, "ClientVersion": VERSION, "Language": 0})
    print(f"   OK, fick en token på {len(token)} tecken")

    print("2. Frågar var spelet ska skapas...")
    answer = json.loads(http("PUT", "/api/games", {}))
    ip = socket.inet_ntoa(struct.pack("<I", answer["Ip"]))
    print(f"   OK, servern säger {ip}:{answer['Port']}")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(3)
    target = (HOST, answer["Port"])

    print("3. Skickar Hello via UDP...")
    sock.sendto(build_hello(), target)
    reply, _ = sock.recvfrom(2048)
    assert reply[0] == protocol.ACK, f"väntade kvitto, fick {reply.hex(' ')}"
    print("   OK, servern skickade kvitto (ack)")

    print("4. Skickar HostGame...")
    sock.sendto(build_host_game(), target)

    print("5. Väntar på svar...")
    while True:
        reply, _ = sock.recvfrom(2048)
        if reply[0] == protocol.ACK:
            continue
        if reply[0] == protocol.DISCONNECT:
            reader = MessageReader(reply[1:])
            if reader.read_bool():
                inner = reader.read_message()
                reason = inner.read_byte()
                text = inner.read_string() if reason == protocol.DisconnectReason.CUSTOM else ""
                print(f"   Servern kopplade bort oss med meddelandet:\n\n   \"{text}\"\n")
            break
        print(f"   Fick paket: {reply.hex(' ')}")

    print("Allt fungerar!")


if __name__ == "__main__":
    try:
        main()
    except (OSError, AssertionError) as error:
        print(f"\nNågot gick fel: {error}")
        print("Kör servern? Starta den först med: python3 -m server")
        sys.exit(1)
