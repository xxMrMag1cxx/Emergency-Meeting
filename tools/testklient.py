"""
Två låtsas-Among Us som testar servern utan att man behöver spelet.

Starta servern i ett fönster och kör sedan (eller dubbelklicka testa.command):

    python3 tools/testklient.py

Testet gör ungefär det som händer när två kompisar spelar:
  1. "Röd" skapar ett spel och får en spelkod
  2. Röd går in i lobbyn och servern skapar Röds spelarinfo
  3. "Blå" letar upp spelet med koden och går med
  4. Röd byter färg och ändrar inställningar, Blå chattar
  5. Blå lämnar, och Röd får veta det
"""

import json
import socket
import struct
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import gamecode, protocol  # noqa: E402
from server.messages import MessageReader, MessageWriter  # noqa: E402

HOST = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 22023
VERSION = protocol.encode_game_version(2026, 3, 18)  # som Among Us 17.4


def http(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(f"http://{HOST}:{PORT}{path}", data=data, method=method)
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


class FakePlayer:
    """En låtsasspelare som pratar Hazel med servern."""

    def __init__(self, name):
        self.name = name
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(0.5)
        self.next_id = 1
        self.inbox = []  # mottagna meddelanden: (tagg, MessageReader)
        self.seen = set()  # paketnummer vi redan fått (servern skickar om ibland)
        self.client_id = None

    def send_raw(self, data):
        self.sock.sendto(data, (HOST, PORT))

    def send_reliable(self, payload):
        packet = bytes([protocol.RELIABLE]) + struct.pack(">H", self.next_id) + payload
        self.next_id += 1
        self.send_raw(packet)

    def hello(self):
        w = MessageWriter()
        w.write_byte(protocol.HELLO).write_bytes(struct.pack(">H", self.next_id)).write_byte(1)
        self.next_id += 1
        w.write_int32(VERSION).write_string(self.name)
        w.write_uint32(0).write_uint32(0).write_byte(1)
        w.start_message(2).write_string("TestDator").end_message()  # Steam
        w.write_int32(0).write_byte(0)
        self.send_raw(w.to_bytes())

    def receive(self, seconds=1.0):
        """Tar emot allt servern skickar under en stund och svarar med kvitton."""
        end = time.time() + seconds
        while time.time() < end:
            try:
                data, _ = self.sock.recvfrom(4096)
            except socket.timeout:
                continue
            kind = data[0]
            if kind == protocol.RELIABLE:
                self.send_raw(bytes([protocol.ACK, data[1], data[2], 0xFF]))
                packet_id = (data[1] << 8) | data[2]
                if packet_id not in self.seen:
                    self.seen.add(packet_id)
                    self._store(data[3:])
            elif kind == protocol.UNRELIABLE:
                self._store(data[1:])
            elif kind == protocol.DISCONNECT:
                self.inbox.append(("disconnect", MessageReader(data[1:])))

    def _store(self, payload):
        for message in MessageReader(payload).messages():
            self.inbox.append((message.tag, message))

    def take(self, tag, seconds=2.0):
        """Väntar på ett visst sorts meddelande och plockar ut det."""
        end = time.time() + seconds
        while time.time() < end:
            for i, (t, msg) in enumerate(self.inbox):
                if t == tag:
                    del self.inbox[i]
                    return msg
            self.receive(0.2)
        raise AssertionError(f"{self.name} fick aldrig {protocol.message_name(tag)}")

    def game_data(self, code_int, *parts, tag=protocol.GAME_DATA):
        w = MessageWriter().start_message(tag).write_int32(code_int)
        for part in parts:
            w.write_bytes(part)
        w.end_message()
        self.send_reliable(w.to_bytes())

    def scene_change(self, code_int):
        part = MessageWriter().start_message(protocol.GameDataTag.SCENE_CHANGE)
        part.write_packed_int32(self.client_id).write_string("OnlineGame").end_message()
        self.game_data(code_int, part.to_bytes())

    def disconnect(self):
        self.send_raw(bytes([protocol.DISCONNECT]))


def game_options(kill_cooldown=30.0, impostors=2, discussion=15):
    """Spelinställningar i samma format som spelet (version 10, vanligt läge)."""
    w = MessageWriter()
    w.write_packed_uint32(0).write_byte(10)  # version 10
    w.start_message(0)
    w.write_byte(1)  # vanligt läge
    w.write_byte(0).write_byte(0)  # specialläge, regelförval
    w.write_byte(10)  # max 10 spelare
    w.write_uint32(256)  # språk: engelska
    w.write_byte(2)  # Polus
    w.write_bytes(struct.pack("<ffff", 1.0, 1.0, 1.5, kill_cooldown))
    w.write_bytes(bytes([1, 1, 2]))  # uppdrag
    w.write_int32(1)  # nödmöten
    w.write_byte(impostors)
    w.write_byte(1)  # kill-avstånd
    w.write_int32(discussion).write_int32(120)  # diskussion, röstning
    w.write_bool(False).write_byte(15)  # standard?, nödmötes-cooldown
    w.write_bool(True).write_bool(True).write_bool(False).write_byte(0)
    w.write_byte(1)  # lobbynivå
    w.write_packed_uint32(1)  # en roll:
    w.write_bytes(struct.pack("<h", 2)).write_byte(1).write_byte(50)  # Scientist, max 1, 50 %
    w.start_message(0).write_byte(15).write_byte(5).end_message()
    w.end_message()
    return w.to_bytes()


def host_game_message():
    w = MessageWriter().start_message(protocol.HOST_GAME)
    w.write_bytes(game_options())
    w.write_int32(0)  # crossplay
    w.write_packed_uint32(0)  # filter
    w.end_message()
    return w.to_bytes()


def spawn_part(spawn_type, owner, net_id, data=b""):
    w = MessageWriter().start_message(protocol.GameDataTag.SPAWN)
    w.write_packed_uint32(spawn_type).write_packed_int32(owner).write_byte(0)
    w.write_packed_uint32(1).write_packed_uint32(net_id)
    w.start_message(1).write_bytes(data).end_message()
    w.end_message()
    return w.to_bytes()


def game_manager_options(options):
    """GameManager-data: del nr 4 är inställningarna."""
    return MessageWriter().start_message(4).write_bytes(options).end_message().to_bytes()


def rpc_part(net_id, call, payload):
    w = MessageWriter().start_message(protocol.GameDataTag.RPC)
    w.write_packed_uint32(net_id).write_byte(call).write_bytes(payload).end_message()
    return w.to_bytes()


def spawned_player_info(message):
    """Läser ut (netId, klient-id) ur ett spawn-meddelande för spelarinfo."""
    reader = MessageReader(message.data)
    reader.read_int32()
    if message.tag == protocol.GAME_DATA_TO:
        reader.read_packed_int32()
    part = reader.read_message()
    assert part.tag == protocol.GameDataTag.SPAWN
    assert part.read_packed_uint32() == protocol.SPAWN_PLAYER_INFO
    assert part.read_packed_int32() == protocol.SERVER_OWNED
    part.read_byte()
    part.read_packed_uint32()
    net_id = part.read_packed_uint32()
    state = part.read_message()
    state.read_byte()
    return net_id, state.read_packed_int32()


def step(text):
    print(f"\n{text}")


def ok(text):
    print(f"   OK, {text}")


def main():
    print(f"Testar servern på {HOST}:{PORT}")

    step("1. Röd skapar ett spel")
    red = FakePlayer("Röd")
    status, _ = http("POST", "/api/user", {"Puid": "röd", "Username": "Röd", "ClientVersion": VERSION, "Language": 0})
    assert status == 200, "kunde inte hämta token"
    red.hello()
    red.receive(0.3)
    red.send_reliable(host_game_message())
    code_int = red.take(protocol.HOST_GAME).read_int32()
    code = gamecode.int_to_code(code_int)
    ok(f"fick spelkoden {code}")

    step("2. Röd går in i lobbyn")
    red.send_reliable(MessageWriter().start_message(protocol.JOIN_GAME).write_int32(code_int).write_bool(False).end_message().to_bytes())
    joined = red.take(protocol.JOINED_GAME)
    joined.read_int32()
    red.client_id = joined.read_int32()
    host_id = joined.read_int32()
    assert host_id == red.client_id, "Röd borde vara värd"
    ok(f"Röd är inne och är värd (spelar-id {red.client_id})")
    red.take(protocol.ALTER_GAME)
    red.scene_change(code_int)
    net_id, owner = spawned_player_info(red.take(protocol.GAME_DATA))
    assert owner == red.client_id
    ok(f"servern skapade Röds spelarinfo (objekt {net_id})")

    step("3. Blå letar upp spelet med koden och går med")
    status, body = http("GET", f"/api/games/{code_int}")
    assert status == 200, f"hittade inte spelet: {body}"
    game = json.loads(body)["Game"]
    ok(f"hittade {code}: värd {game['HostName']}, {game['PlayerCount']}/{game['MaxPlayers']} spelare, karta {game['MapId']}")
    blue = FakePlayer("Blå")
    blue.hello()
    blue.receive(0.3)
    blue.send_reliable(MessageWriter().start_message(protocol.JOIN_GAME).write_int32(code_int).write_bool(False).end_message().to_bytes())
    joined = blue.take(protocol.JOINED_GAME)
    joined.read_int32()
    blue.client_id = joined.read_int32()
    joined.read_int32()
    assert joined.read_packed_uint32() == 1, "Blå borde se en annan spelare"
    joined.read_packed_int32()
    ok(f"Blå är inne och ser {joined.read_string()} i lobbyn")
    news = red.take(protocol.JOIN_GAME)
    news.read_int32()
    assert news.read_int32() == blue.client_id
    ok("Röd fick veta att Blå kom")

    blue.scene_change(code_int)
    synced = spawned_player_info(blue.take(protocol.GAME_DATA_TO))
    assert synced[1] == red.client_id
    ok("Blå fick Röds spelarinfo")
    spawned_player_info(blue.take(protocol.GAME_DATA))
    _, owner = spawned_player_info(red.take(protocol.GAME_DATA))
    assert owner == blue.client_id
    ok("båda fick Blås spelarinfo")
    red.take(protocol.GAME_DATA)  # Blås "jag har laddat lobbyn", vidareskickat till Röd

    step("4. Röd och Blå spelar i lobbyn")
    # Röd (värden) skapar sin gubbe och GameManager, precis som spelet gör.
    red.game_data(code_int, spawn_part(protocol.SPAWN_PLAYER_CONTROL, red.client_id, 10))
    red.game_data(code_int, spawn_part(protocol.SPAWN_NORMAL_GAME_MANAGER, -2, 20, game_manager_options(game_options())))
    blue.take(protocol.GAME_DATA)
    blue.take(protocol.GAME_DATA)
    ok("Blå ser Röds gubbe och lobbyn")

    color = MessageWriter().write_uint32(net_id).write_byte(11).to_bytes()  # Lime
    red.game_data(code_int, rpc_part(10, protocol.RPC_SET_COLOR, color))
    blue.take(protocol.GAME_DATA)
    ok("Röd bytte färg och Blå fick veta det")

    change = MessageWriter().start_message(protocol.GameDataTag.DATA).write_packed_uint32(20)
    change.write_bytes(game_manager_options(game_options(kill_cooldown=25.0, impostors=1))).end_message()
    red.game_data(code_int, change.to_bytes())
    blue.take(protocol.GAME_DATA)
    ok("Röd ändrade inställningar och Blå fick dem (servern ska logga ändringarna)")
    status, body = http("GET", f"/api/games/{code_int}")
    assert json.loads(body)["Game"]["NumImpostors"] == 1, "spellistan borde visa 1 impostor nu"
    ok("spellistan visar de nya inställningarna")

    chat = rpc_part(30, protocol.RPC_SEND_CHAT, MessageWriter().write_string("hej Röd!").to_bytes())
    blue.game_data(code_int, chat)
    relayed = red.take(protocol.GAME_DATA)
    assert chat in relayed.data
    ok("Röd fick Blås chattmeddelande")

    step("5. Blå lämnar")
    blue.disconnect()
    removed = red.take(protocol.REMOVE_PLAYER)
    removed.read_int32()
    assert removed.read_int32() == blue.client_id
    ok("Röd fick veta att Blå lämnade")
    red.disconnect()

    print("\nAllt fungerar!")


if __name__ == "__main__":
    try:
        main()
    except (OSError, AssertionError) as error:
        print(f"\nNågot gick fel: {error}")
        print("Kör servern? Starta den först med start.command")
        sys.exit(1)
