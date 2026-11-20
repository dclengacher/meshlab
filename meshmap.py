#!/usr/bin/env python3
"""Pi -> H4 -> T1000 coverage logger: DM every INTERVAL s with time + WittBoy weather; log ACKs + T1000 positions."""
import os, sqlite3, threading, time
from datetime import datetime
from pubsub import pub
import meshtastic.serial_interface
from meshtastic.protobuf import portnums_pb2

DEST = "!c1ce9509"
DEST_NUM = 0xc1ce9509
INTERVAL = 1200  # seconds (20 min), aligned to :00/:20/:40
DB = os.path.expanduser("~/mesh/meshmap.db")
BIRDS = "/home/david/BirdNET-Pi/scripts/birds.db"
COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]

lock = threading.Lock()
db = sqlite3.connect(DB, check_same_thread=False)
db.executescript("""
CREATE TABLE IF NOT EXISTS sends(seq INTEGER PRIMARY KEY, pkt_id INTEGER, ts_sent INTEGER,
  status TEXT DEFAULT 'pending', ts_resp INTEGER, reason TEXT);
CREATE TABLE IF NOT EXISTS positions(ts INTEGER, lat REAL, lon REAL, alt REAL, snr REAL, rssi INTEGER);
""")
for col in ("snr REAL", "rssi INTEGER", "msg TEXT"):
    try:
        db.execute(f"ALTER TABLE sends ADD COLUMN {col}")
    except sqlite3.OperationalError:
        pass
db.commit()

def q(sql, args=()):
    with lock:
        db.execute(sql, args)
        db.commit()

def weather():
    """Latest WittBoy reading as short text; never let this break sending."""
    try:
        b = sqlite3.connect(f"file:{BIRDS}?mode=ro", uri=True, timeout=5)
        r = b.execute("SELECT tempf, humidity, baromrelin, winddir, windspeedmph, windgustmph "
                      "FROM wittboy ORDER BY rowid DESC LIMIT 1").fetchone()
        b.close()
        if not r:
            return "no wx data"
        t, h, p, wd, ws, wg = r
        f = lambda v, fmt: fmt.format(float(v)) if v is not None else "?"
        d = COMPASS[int((float(wd) + 22.5) // 45) % 8] if wd is not None else "?"
        return (f"{f(t, '{:.0f}')}F {f(h, '{:.0f}')}%RH {f(p, '{:.2f}')}inHg | "
                f"Wind {d} {f(ws, '{:.0f}')} G{f(wg, '{:.0f}')}mph")
    except Exception as e:
        print(f"wx err {e}", flush=True)
        return "wx err"

def on_receive(packet, interface):
    d = packet.get("decoded", {})
    port = d.get("portnum")
    if port == "ROUTING_APP":
        req = d.get("requestId")
        reason = d.get("routing", {}).get("errorReason", "NONE")
        if not req:
            return
        if reason == "NONE" and packet.get("from") == DEST_NUM:
            status = "ack"
        elif reason != "NONE":
            status = "fail"
        else:
            return  # implicit ack from a relay, not proof of delivery
        q("UPDATE sends SET status=?, ts_resp=?, reason=?, snr=?, rssi=? WHERE pkt_id=? AND status='pending'",
          (status, int(time.time()), reason, packet.get("rxSnr"), packet.get("rxRssi"), req))
        print(f"resp {req} {status} {reason} snr={packet.get('rxSnr')}", flush=True)
    elif port == "POSITION_APP" and packet.get("from") == DEST_NUM:
        p = d.get("position", {})
        if "latitude" in p:
            q("INSERT INTO positions VALUES (?,?,?,?,?,?)",
              (packet.get("rxTime", int(time.time())), p["latitude"], p["longitude"],
               p.get("altitude"), packet.get("rxSnr"), packet.get("rxRssi")))
            print(f"pos {p['latitude']:.5f},{p['longitude']:.5f}", flush=True)

def on_lost(interface):
    os._exit(1)  # let systemd restart

pub.subscribe(on_receive, "meshtastic.receive")
pub.subscribe(on_lost, "meshtastic.connection.lost")
iface = meshtastic.serial_interface.SerialInterface()

with lock:
    seq = db.execute("SELECT MAX(seq) FROM sends").fetchone()[0] or 0

while True:
    seq += 1
    now = datetime.now()
    text = f"#{seq} {now:%m-%d %H:%M} | {weather()}"[:200]
    pkt = iface.sendData(text.encode(), destinationId=DEST,
                         portNum=portnums_pb2.PortNum.TEXT_MESSAGE_APP, wantAck=True)
    q("INSERT INTO sends(seq, pkt_id, ts_sent, msg) VALUES (?,?,?,?)",
      (seq, pkt.id, int(now.timestamp()), text))
    print(f"sent {text} id={pkt.id}", flush=True)
    time.sleep(INTERVAL - time.time() % INTERVAL)
