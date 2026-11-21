#!/usr/bin/env python3
"""APRS twin of exp2: every INTERVAL s the Pi (KR4QIB-10, FT-65 via Digirig + Direwolf)
sends an APRS message with live wittboy weather to the UV-Pro (KR4QIB-7, APRSdroid
auto-ACKs). Retries like a normal APRS client (up to RETRIES extra tries, RETRY_GAP s
apart) until the ACK arrives. One row per message in ~/mesh/aprs.db; every decoded
frame is also logged. Talks to Direwolf over KISS TCP (localhost:8101).
Signal level per packet is in ~/mesh/aprs/direwolf.log ("audio level") for later joins.
"""
import os, socket, sqlite3, threading, time
from datetime import datetime

MYCALL, DEST = "KR4QIB-10", "KR4QIB-7"
KISS = ("127.0.0.1", 8101)
INTERVAL = 240     # seconds between new messages
RETRIES = 3        # extra transmissions if no ACK (APRS-style)
RETRY_GAP = 30     # seconds between tries
DB = os.path.expanduser("~/mesh/aprs.db")
BIRDS = "/home/david/BirdNET-Pi/scripts/birds.db"

db = sqlite3.connect(DB, check_same_thread=False)
lock = threading.Lock()
db.executescript("""
CREATE TABLE IF NOT EXISTS sends(
  ts TEXT, seq INTEGER, msgno TEXT, msg TEXT, attempts INTEGER, acked INTEGER,
  latency_s REAL, ack_ts TEXT, temp_f REAL, hum REAL, pres_in REAL, wind_mph REAL, wx_ts TEXT);
CREATE TABLE IF NOT EXISTS rx(ts TEXT, src TEXT, dst TEXT, path TEXT, info TEXT);
""")
db.commit()
ACKS = {}  # msgno -> time ACK received


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


# ---- AX.25 / KISS encoding ----
def _addr(call, last):
    base, _, ssid = call.partition("-")
    b = bytes((ord(ch) << 1) for ch in base.upper().ljust(6)[:6])
    return b + bytes([0x60 | ((int(ssid or 0) & 0x0F) << 1) | (1 if last else 0)])


def kiss_frame(info):
    ax = _addr("APRS", False) + _addr(MYCALL, True) + b"\x03\xf0" + info.encode("ascii", "replace")
    esc = ax.replace(b"\xdb", b"\xdb\xdd").replace(b"\xc0", b"\xdb\xdc")
    return b"\xc0\x00" + esc + b"\xc0"


def _call(b):
    base = "".join(chr(x >> 1) for x in b[:6]).strip()
    ssid = (b[6] >> 1) & 0x0F
    return f"{base}-{ssid}" if ssid else base


def decode(ax):
    addrs, i = [], 0
    while i + 7 <= len(ax):
        addrs.append(_call(ax[i:i + 7]))
        last = ax[i + 6] & 1
        i += 7
        if last:
            break
    info = ax[i + 2:].decode("ascii", "replace")
    return addrs, info


def reader(sock):
    buf = b""
    while True:
        data = sock.recv(4096)
        if not data:
            raise ConnectionError("KISS closed")
        buf += data
        while buf.count(b"\xc0") >= 2:
            start = buf.index(b"\xc0")
            end = buf.index(b"\xc0", start + 1)
            frame, buf = buf[start + 1:end], buf[end:]
            if len(frame) < 16 or frame[0] & 0x0F != 0:
                continue
            ax = frame[1:].replace(b"\xdb\xdc", b"\xc0").replace(b"\xdb\xdd", b"\xdb")
            try:
                addrs, info = decode(ax)
            except Exception:
                continue
            dst, src, path = addrs[0], addrs[1] if len(addrs) > 1 else "?", ",".join(addrs[2:])
            now = time.time()
            write("INSERT INTO rx VALUES (?,?,?,?,?)",
                  (datetime.now().isoformat(timespec="seconds"), src, dst, path, info))
            tag = f":{MYCALL.ljust(9)}:ack"
            if src == DEST and info.startswith(tag):
                ACKS.setdefault(info[len(tag):].strip(), now)
                print(f"ack {info[len(tag):].strip()} from {src}", flush=True)


def main():
    while True:
        try:
            sock = socket.create_connection(KISS, timeout=10)
            sock.settimeout(None)
            break
        except OSError as e:
            print("waiting for Direwolf:", e, flush=True)
            time.sleep(10)
    threading.Thread(target=reader, args=(sock,), daemon=True).start()
    seq = db.execute("SELECT COALESCE(MAX(seq),0) FROM sends").fetchone()[0]
    while True:
        start = time.time()
        seq += 1
        msgno = f"{seq % 100000:05d}"
        wx_ts, t, h, p, w = weather()
        f = lambda v, n=1: "?" if v is None else f"{v:.{n}f}"
        msg = f"#{seq} {datetime.now():%H:%M} T{f(t)}F H{f(h, 0)}% P{f(p, 2)} W{f(w)}"[:67]
        info = f":{DEST.ljust(9)}:{msg}{{{msgno}"
        t0, attempts = time.time(), 0
        while attempts <= RETRIES and msgno not in ACKS:
            sock.sendall(kiss_frame(info))
            attempts += 1
            waited = 0
            while waited < RETRY_GAP and msgno not in ACKS:
                time.sleep(1)
                waited += 1
        ack_t = ACKS.get(msgno)
        write("INSERT INTO sends VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (datetime.fromtimestamp(t0).isoformat(timespec="seconds"), seq, msgno, msg,
               attempts, int(ack_t is not None),
               round(ack_t - t0, 2) if ack_t else None,
               datetime.fromtimestamp(ack_t).isoformat(timespec="seconds") if ack_t else None,
               t, h, p, w, wx_ts))
        print(f"seq {seq} acked={int(ack_t is not None)} tries={attempts} "
              f"lat={round(ack_t - t0, 1) if ack_t else None}", flush=True)
        time.sleep(max(0, INTERVAL - (time.time() - start)))


if __name__ == "__main__":
    main()
