#!/usr/bin/env python3
"""Exp 2: 4-node baseline. Every INTERVAL s the H4 sends one ACK-requested DM
with live wittboy weather to each of 3 nodes (random order each cycle).
Fixed: Long Moderate, slot 20, 30 dBm. One row per send in ~/mesh/exp2.db.
Also logs every position packet heard (T1000 moves daily).
Run via exp2.service. meshmap must be stopped (one USB client only).
"""
import os, random, sqlite3, threading, time
from datetime import datetime
from pubsub import pub
import meshtastic.serial_interface
from meshtastic.protobuf import portnums_pb2

NODES = {"!c1ce9509": "T1000", "!2344b302": "Rak1", "!054f6fbf": "Rak2"}
INTERVAL = 120   # seconds between cycle starts
TIMEOUT = 45     # seconds to wait for ACK/NAK per send (relays add time)
DB = os.path.expanduser("~/mesh/exp2.db")
BIRDS = "/home/david/BirdNET-Pi/scripts/birds.db"

db = sqlite3.connect(DB, check_same_thread=False)
lock = threading.Lock()
db.executescript("""
CREATE TABLE IF NOT EXISTS sends(
  ts TEXT, cycle INTEGER, order_idx INTEGER, dest TEXT, dest_name TEXT, msg TEXT,
  delivered INTEGER, reason TEXT, latency_s REAL, ack_snr REAL, ack_rssi INTEGER,
  ack_hops INTEGER, relay_node INTEGER, preset INTEGER, tx_power INTEGER,
  temp_f REAL, hum REAL, pres_in REAL, wind_mph REAL, wx_ts TEXT,
  h4_ch_util REAL, h4_air_tx REAL);
CREATE TABLE IF NOT EXISTS positions(
  ts TEXT, node TEXT, lat REAL, lon REAL, alt REAL, rx_snr REAL, rx_rssi INTEGER);
""")
for col in ("batt INTEGER", "volt REAL", "node_last_heard INTEGER", "relay_heard INTEGER"):
    try:
        db.execute(f"ALTER TABLE sends ADD COLUMN {col}")
    except sqlite3.OperationalError:
        pass
db.commit()

COLS = ("ts,cycle,order_idx,dest,dest_name,msg,delivered,reason,latency_s,ack_snr,ack_rssi,"
        "ack_hops,relay_node,preset,tx_power,temp_f,hum,pres_in,wind_mph,wx_ts,"
        "h4_ch_util,h4_air_tx,batt,volt,node_last_heard,relay_heard")

def write(sql, args):
    with lock:
        db.execute(sql, args)
        db.commit()

def weather():
    try:
        c = sqlite3.connect(f"file:{BIRDS}?mode=ro", uri=True, timeout=5)
        r = c.execute("SELECT timestamp, tempf, humidity, baromrelin, windspeedmph "
                      "FROM wittboy ORDER BY timestamp DESC LIMIT 1").fetchone()
        c.close()
        return r or (None,) * 5
    except Exception:
        return (None,) * 5

def fmt(v, nd=1):
    return "?" if v is None else f"{v:.{nd}f}"

def on_position(packet, interface):
    p = packet.get("decoded", {}).get("position", {})
    if "latitude" in p:
        write("INSERT INTO positions VALUES (?,?,?,?,?,?,?)",
              (datetime.now().isoformat(timespec="seconds"), packet.get("fromId"),
               p.get("latitude"), p.get("longitude"), p.get("altitude"),
               packet.get("rxSnr"), packet.get("rxRssi")))

pub.subscribe(on_position, "meshtastic.receive.position")

def connect():
    while True:
        try:
            return meshtastic.serial_interface.SerialInterface()
        except Exception as e:
            print("connect failed:", e, flush=True)
            time.sleep(10)

PENDING = {}  # packet id -> {"dest", "ev", "res"}

def on_any(packet, interface):
    """Catch every routing reply, so a relay's implicit ACK can't hide the real one."""
    d = packet.get("decoded", {})
    if d.get("portnum") != "ROUTING_APP":
        return
    p = PENDING.get(d.get("requestId"))
    if not p:
        return
    reason = d.get("routing", {}).get("errorReason", "NONE")
    res = p["res"]
    if packet.get("fromId") == p["dest"]:            # real end-to-end ACK/NAK
        hs, hl = packet.get("hopStart"), packet.get("hopLimit")
        res.update(reason=reason, snr=packet.get("rxSnr"), rssi=packet.get("rxRssi"),
                   hops=(hs - hl) if hs is not None and hl is not None else None,
                   relay=packet.get("relayNode"), t=time.time())
        p["ev"].set()
    elif reason == "NONE":                           # implicit ACK: a relay repeated it
        res["relay_heard"] = 1
    else:                                            # local NAK, e.g. MAX_RETRANSMIT
        res.update(reason=reason, t=time.time())
        p["ev"].set()

pub.subscribe(on_any, "meshtastic.receive")

def send_one(iface, dest, msg):
    res, ev = {"relay_heard": 0}, threading.Event()
    t0 = time.time()
    pkt = iface.sendData(msg.encode(), destinationId=dest,
                         portNum=portnums_pb2.PortNum.PRIVATE_APP, wantAck=True)
    PENDING[pkt.id] = {"dest": dest, "ev": ev, "res": res}
    ev.wait(TIMEOUT)
    PENDING.pop(pkt.id, None)
    res["delivered"] = int(ev.is_set() and res.get("reason") == "NONE" and "snr" in res)
    res["latency"] = round(res["t"] - t0, 2) if ev.is_set() else None
    res.setdefault("reason", "TIMEOUT")
    return res

def main():
    iface = connect()
    cycle = (db.execute("SELECT MAX(cycle) FROM sends").fetchone()[0] or 0)
    while True:
        start = time.time()
        cycle += 1
        try:
            lora = iface.localNode.localConfig.lora
            dm = (iface.getMyNodeInfo() or {}).get("deviceMetrics", {})
            wx_ts, t, h, p, w = weather()
            order = list(NODES)
            random.shuffle(order)
            for i, dest in enumerate(order):
                msg = (f"#{cycle} {datetime.now():%H:%M} Temp {fmt(t)}F Hum {fmt(h, 0)}% "
                       f"Pres {fmt(p, 2)}in Wind {fmt(w)}mph")
                r = send_one(iface, dest, msg)
                node = (iface.nodes or {}).get(dest, {})
                nm = node.get("deviceMetrics", {})
                write(f"INSERT INTO sends ({COLS}) VALUES ({','.join('?' * 26)})",
                      (datetime.now().isoformat(timespec="seconds"), cycle, i, dest,
                       NODES[dest], msg, r["delivered"], r["reason"], r["latency"],
                       r.get("snr"), r.get("rssi"), r.get("hops"), r.get("relay"),
                       lora.modem_preset, lora.tx_power, t, h, p, w, wx_ts,
                       dm.get("channelUtilization"), dm.get("airUtilTx"),
                       nm.get("batteryLevel"), nm.get("voltage"), node.get("lastHeard"),
                       r["relay_heard"]))
                print(f"cycle {cycle} {NODES[dest]:6} delivered={r['delivered']} "
                      f"snr={r.get('snr')} lat={r['latency']}", flush=True)
        except Exception as e:
            print("error, reconnecting:", e, flush=True)
            try:
                iface.close()
            except Exception:
                pass
            time.sleep(10)
            iface = connect()
        time.sleep(max(0, INTERVAL - (time.time() - start)))

if __name__ == "__main__":
    main()
