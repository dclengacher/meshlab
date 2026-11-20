#!/usr/bin/env python3
"""Exp 1: H4 tx-power dose-response. Acked DMs H4 -> T1000, one CSV row per packet.
Power levels randomized; 24 sends each (120 total). Restores 30 dBm at end.
Run with meshmap stopped.
"""
import csv, os, random, sys, threading, time
from datetime import datetime
import meshtastic.serial_interface
from meshtastic.protobuf import portnums_pb2

DEST, DEST_NUM = "!c1ce9509", 0xc1ce9509
LEVELS = [1, 7, 13, 19, 25]   # dBm (0 would mean "default max", so avoid)
N = 24                        # sends per level
GAP = 6                       # seconds between sends
TIMEOUT = 30                  # seconds to wait for ACK/NAK
OUT = os.path.expanduser("~/mesh/exp1.csv")
FIELDS = ["ts", "block", "tx_power", "seq", "delivered", "reason",
          "latency_s", "ack_snr", "ack_rssi"]

def connect():
    for _ in range(12):
        try:
            return meshtastic.serial_interface.SerialInterface()
        except Exception:
            time.sleep(5)
    sys.exit("H4 not reachable")

def set_power(iface, p):
    iface.localNode.localConfig.lora.tx_power = p
    iface.localNode.writeConfig("lora")
    iface.close()
    time.sleep(25)  # H4 reboots after LoRa change
    return connect()

def run_block(iface, w, block, power):
    for seq in range(N):
        res, done = {}, threading.Event()
        def cb(pkt, res=res, done=done):
            r = pkt.get("decoded", {}).get("routing", {}).get("errorReason", "NONE")
            if r == "NONE" and pkt.get("from") != DEST_NUM:
                r = "IMPLICIT"
            res.update(reason=r, snr=pkt.get("rxSnr"), rssi=pkt.get("rxRssi"), t=time.time())
            done.set()
        t0 = time.time()
        iface.sendData(f"x{seq}".encode(), destinationId=DEST,
                       portNum=portnums_pb2.PortNum.TEXT_MESSAGE_APP,
                       wantAck=True, onResponse=cb, onResponseAckPermitted=True)
        done.wait(TIMEOUT)
        ok = int(done.is_set() and res.get("reason") == "NONE")
        w.writerow(dict(ts=datetime.now().isoformat(timespec="seconds"), block=block,
                        tx_power=power, seq=seq, delivered=ok,
                        reason=res.get("reason", "TIMEOUT"),
                        latency_s=round(res["t"] - t0, 2) if done.is_set() else "",
                        ack_snr=res.get("snr", ""), ack_rssi=res.get("rssi", "")))
        print(f"{power} dBm {seq+1}/{N} delivered={ok} snr={res.get('snr')}", flush=True)
        time.sleep(max(0, GAP - (time.time() - t0)))

def main():
    new = not os.path.exists(OUT)
    f = open(OUT, "a", newline="")
    w = csv.DictWriter(f, FIELDS)
    if new:
        w.writeheader()
    levels = LEVELS[:]
    random.shuffle(levels)
    print("Order:", levels)
    iface = connect()
    try:
        for b, p in enumerate(levels):
            iface = set_power(iface, p)
            run_block(iface, w, b, p)
            f.flush()
    finally:
        print("Restoring tx_power 30...")
        iface = set_power(iface, 30)
        iface.close()
        f.close()

if __name__ == "__main__":
    main()
