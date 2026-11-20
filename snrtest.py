#!/usr/bin/env python3
"""Send N acked DMs to T1000, report ACK SNR/RSSI. Usage: snrtest.py LABEL [N]"""
import sys, time, statistics
from pubsub import pub
import meshtastic.serial_interface
from meshtastic.protobuf import portnums_pb2

DEST, DEST_NUM = "!c1ce9509", 0xc1ce9509
label = sys.argv[1] if len(sys.argv) > 1 else "test"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 10
sent, res = set(), {}

def on_rx(packet, interface):
    d = packet.get("decoded", {})
    if d.get("portnum") == "ROUTING_APP" and d.get("requestId") in sent and packet.get("from") == DEST_NUM:
        res[d["requestId"]] = (packet.get("rxSnr"), packet.get("rxRssi"))

pub.subscribe(on_rx, "meshtastic.receive")
iface = meshtastic.serial_interface.SerialInterface()
for i in range(N):
    p = iface.sendData(f"{label} {i+1}/{N}".encode(), destinationId=DEST,
                       portNum=portnums_pb2.PortNum.TEXT_MESSAGE_APP, wantAck=True)
    sent.add(p.id)
    time.sleep(15)
iface.close()
snr = [v[0] for v in res.values() if v[0] is not None]
rssi = [v[1] for v in res.values() if v[1] is not None]
print(f"{label}: acks {len(res)}/{N}")
if snr:
    print(f"  SNR  mean {statistics.mean(snr):.1f}  min {min(snr):.1f}  max {max(snr):.1f}")
    print(f"  RSSI mean {statistics.mean(rssi):.1f}  min {min(rssi)}  max {max(rssi)}")
