# meshlab — Learnings & Decisions

> Read this first. Concise record of what was decided, why, and what bit us. Update in the same commit as any change.
> Whole-Pi architecture lives in `ARCHITECTURE.md` of `dclengacher/winstonsalembirds`.

## 0. Access
- Pi on home LAN: `192.168.1.245` (user `david`). SSH from Windows: `ssh david@192.168.1.245`. Copy files from Windows: `scp <file> david@192.168.1.245:~/mesh/`.

## 1. Hardware & IDs
| Node | ID | Role | Notes |
|---|---|---|---|
| Heltec V4 "Broad St Station" (H4) | `!1ba2a430` | Base, on Pi USB `/dev/ttyACM0` | 30 dBm (1 W), GPS on, CLIENT role, firmware 2.7.26 |
| SenseCAP T1000-E | `!c1ce9509` | Mobile receiver | ~22 dBm, tiny internal antenna |
| WisMesh Pocket V3 + 2 more nodes | — | Ordered | ~22 dBm; better antenna than T1000 |

- Only the H4 has a 1 W amplifier. Receivers hear about equally well; the gap is transmit only.
- One Android phone can control one node at a time over Bluetooth. The Pi controls the H4 over USB.

## 2. Channels (never switch — both radios always run both)
| Index | Name | Key | Position precision | Purpose |
|---|---|---|---|---|
| 0 PRIMARY | LongFast | public default | 0 (not shared) | Public service: relay neighbors, be visible to them |
| 1 SECONDARY | Birdmesh | private (keep URL secret) | 32 (exact) | T1000 exact position for the map |

- Firmware sends position on the first channel with precision > 0, so positions go only on Birdmesh.
- Default is public service. Running private-only was a test-day exception.
- Never paste `--info` output publicly: it contains the private key and channel key.

## 3. Operating modes
| | Home (default) | Drive test |
|---|---|---|
| meshmap | `sudo systemctl stop meshmap` | `sudo systemctl start meshmap` |
| INTERVAL | 1200 s (or off) | 60 s |
| Boot | disabled (`systemctl disable meshmap`) | start manually |

**T1000 universal position settings (set once):** broadcast 900 s, smart on, smart min distance 50 m, smart min interval 30 s, GPS update 30 s. Smart position = silent when parked. Meshtastic has no profiles.

## 4. Software layout
- `~/mesh-venv` — dedicated Python env. CLI: `~/mesh-venv/bin/meshtastic`.
- `~/mesh/meshmap.py` (+ `meshmap.service`) — ACK-requested DM to T1000 with time, humidity, latest bird; logs `sends` (seq, status, SNR, RSSI) and `positions` to `~/mesh/meshmap.db`.
- `~/mesh/exp1.py` — tx-power experiment, randomized levels, one CSV row per packet, restores 30 dBm at end.
- Website page: `~/birdnet/app/meshmap_page.py` reads `meshmap.db` read-only.
- **Only one program can hold the H4 USB port.** Stop meshmap before CLI/experiments. "H4 not reachable" = meshmap still running.

## 5. What the Pi can and cannot see
- Pi sees only what the H4 hears: its own sends, rebroadcasts of its packets (relay = last byte of `relayNode`), ACKs, other nodes' packets.
- Each node's reception SNR/RSSI stays on that node. To get other links: **traceroute** (`snrTowards`/`snrBack` per hop), NeighborInfo module, or device telemetry broadcasts.
- Packet fields: `rxSnr`, `rxRssi`, `hopStart`, `hopLimit`, `rxTime`. Device: `batteryLevel`, `voltage`, `channelUtilization`, `airUtilTx`, `uptimeSeconds`. LocalStats: `numPacketsTx/Rx/RxBad`, `numRxDupe`, `numTxRelay(Canceled)`.
- Airtime is not reported per packet — compute from preset + payload (LongFast 24 B ≈ 0.48 s).

## 6. Hard-won lessons
1. **Red dot ≠ not received.** H4 (1 W) reaches the T1000 but the T1000's ACK can't get back. ACK is one-shot with a few retries; there is no catch-up later. Fix: import phone-side received log, or match transmit power during tests.
2. **SNR on LongFast fails near −20 dB.** SNR saturates at strong signals (~+6 dB indoors); use RSSI or latency there.
3. **ACK RSSI ≈ −35 dBm from a truck was physically implausible** → treat ACK SNR/RSSI fields with suspicion until validated. Run a negative control (T1000 off → 100 % fail).
4. **Latency is the trustworthy early signal:** at 1 dBm in the truck, latency rose 2.2 → 5.0 s (retries) before any delivery loss.
5. **Ceiling effect:** on one property, even 1 dBm delivers 100 %. Need ~5–10 dB more loss: sealed metal tin, real distance, or lower power. An open bowl leaks.
6. **Body blocks 4–6 dB;** wear the T1000 outside clothing. Ferrite clip on H4 USB cable near the H4.
7. **tx_power 0 means "default max",** not 0 dBm. Use 1 as minimum.
8. **Long heredoc pastes break in the terminal.** After pasting a script: `python -m py_compile file.py && echo OK`. A `>` prompt means the paste is still open → Ctrl+C and re-paste.
9. Run commands on the Pi, not the Windows prompt (`~` fails there).
10. Experiments on the shared LongFast frequency add load for neighbors — run late, keep payloads tiny, or use a private primary channel/preset for heavy tests.

## 7. Experiment log
| Date | Experiment | Result |
|---|---|---|
| 2026-11-14 | Drive test, LongFast, 60 s | Edge SNR −15 to −19 dB at ~0.5–1 mi; many red dots were ACK failures |
| 2026-11-14 | Exp 1: H4 power 1/7/13/19/25 dBm × 24, T1000 on patio | 100 % delivery all levels (ceiling); ACK SNR flat ~6.1 dB |
| 2026-11-15 | Pilot 1/4/7/10 dBm × 5, three placements | Still 100 %; truck run 1 dBm latency 5.0 s (retries) |

## 8. Research direction
- Working title: "Emergent behavior in Meshtastic node experiments."
- Prior work: guided-link preset study (arXiv 2605.17063), MeshRoute flooding simulation (not peer-reviewed). No DEA/fsQCA on Meshtastic found.
- Methods edge: GLMM (node-pair random effects, weather covariates), DEA, fsQCA, physical test of flooding collapse.
- **DEA design:** input = energy per message (W × airtime, not dBm); outputs = delivery rate, 1/latency; 4 presets × 3 power levels = 12 DMUs × 24 messages. Preset change must be made on every node.
- Planned 4-node experiments: preset comparison, relay/hidden-node behavior, congestion curve, weather sensitivity, antenna factorial.
- Simulated 4-node template dataset: `sim.py` → `meshtastic_4node_sim.csv` (13,842 rows; tuned assumptions, not findings).

## 9. APRS comparison (planned)
- Base TX: Pi4 + Direwolf + Digirig + Yaesu FT-65. Mobile RX: BTech UV-Pro (built-in TNC + GPS) + APRSdroid on Android, auto-ACKs messages.
- Pi logs sends, ACKs and audio level via Direwolf. No LoRa-style SNR; compare on delivery, latency, energy per delivered message, coverage. Optional: one RTL-SDR measures both bands for matched SNR.
- Use a simplex frequency, not 144.39 MHz.

## 10. Use cases worth building
- Event-driven messages (rare bird, pressure drop, thresholds) instead of fixed timers.
- Remote BirdNET field nodes, sensor-triggered camera, irrigation, microclimate grid (Remote Hardware / Detection Sensor / environment telemetry).
