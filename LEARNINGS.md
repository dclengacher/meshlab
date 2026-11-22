# meshlab — Learnings & Decisions

> Read this first. Concise record of what exists, what was decided, why, and what bit us. Update in the same commit as any change.
> Whole-Pi architecture (all three code bases) lives in `ARCHITECTURE.md` of `dclengacher/winstonsalembirds`.
> Last full rewrite: 2026-11-22.

## 0. Access
- Pi on home LAN: `192.168.1.245` (user `david`). SSH from Windows: `ssh david@192.168.1.245`.
- Copy files from Windows: `scp %USERPROFILE%\Downloads\<file> david@192.168.1.245:~/mesh/` (run in the `C:\Users\dclen>` window, never the Pi window).
- Long heredoc pastes break in the terminal — deliver files by download + scp instead.

## 1. Folder layout (repo `dclengacher/meshlab`, public, = `~/mesh` on the Pi)
```
~/mesh/
├── LEARNINGS.md            this file
├── exp2.py                 4-node experiment logger (Meshtastic)          -> ~/mesh/exp2.db
├── exp2.service            systemd unit (installed in /etc/systemd/system)
├── exp1.py                 tx-power sweep (2026-11-14), kept for future power tests
├── meshmap.py              original drive-test logger (retired; service disabled) -> ~/mesh/meshmap.db
├── snrtest.py              early SNR test
├── deploy/meshmap.service  retired unit, kept for reference
├── aprs/
│   ├── direwolf.conf       Direwolf TNC config (Digirig card 4, PTT /dev/ttyUSB0 RTS, KISS 8101, AGW 8100)
│   ├── direwolf.service    systemd unit, logs to ~/mesh/aprs/direwolf.log
│   ├── aprs_exp.py         APRS twin of exp2                             -> ~/mesh/aprs.db
│   └── aprs_exp.service    systemd unit
└── experiments/
    └── segments.csv        time windows: where every node was, include flag, confounders
```
- Python env: `~/mesh-venv` (outside the repo). CLI: `~/mesh-venv/bin/meshtastic`.
- Not in git (`.gitignore`): `*.db`, `*.csv` data, logs, keys — except `experiments/segments.csv`, which is whitelisted.
- Website pages live in the *other* repo (`~/birdnet`): `app/mesh_status.py` + `templates/mesh_status.html` (`/mesh-status`, reads `exp2.db` read-only), `app/meshmap_page.py` (`/meshmap`), `app/radio_lab.py` (`/radio-lab`).

## 2. Hardware & IDs
| Device | ID / call | Role | Notes |
|---|---|---|---|
| Heltec V4 "Broad St Station" (H4) | `!1ba2a430` | Home base on Pi USB `/dev/ttyACM0` | 30 dBm (1 W), GPS, CLIENT, fw 2.7.26 |
| RAK WisMesh Pocket V3 "Rak White v3 2" (Rak2) | `!054f6fbf` | Fixed relay, UNCSA catwalk (since 2026-11-20 16:45) | ~22 dBm, buzzer off, GPS off/fixed |
| RAK WisMesh Pocket V3 "Rak White v3 1" (Rak1) | `!2344b302` | Mobile/field node | ~22 dBm, buzzer off; GPS still ON |
| SenseCAP T1000-E | `!c1ce9509` | Mobile node (car/backpack) | ~22 dBm, tiny internal antenna, GPS on |
| Yaesu FT-65 + Digirig Mobile | KR4QIB-10 | APRS home station via Direwolf | 5 W, 145.010 simplex, ARS off; Digirig = USB audio card 4 + CP210x `/dev/ttyUSB0` |
| BTech UV-Pro + Android APRSdroid | KR4QIB-7 | APRS mobile; APRSdroid auto-ACKs | 145.010, BW 25 kHz, Digital mode OFF, TX High |
- Last-byte relay IDs (for `relayNode`): H4 `0x30`, T1000 `0x09`, Rak1 `0x02`, Rak2 `0xbf`.
- WisMesh battery ≈ 0.5 %/h; T1000 ≈ 3 %/h — fixed/unattended spots get a WisMesh.

## 3. Current radio configuration (since 2026-11-20 ~14:00)
- **Preset LONG_MODERATE, frequency slot 20, on all 4 nodes** — off the public LongFast mesh until changed back on every node.
- Channels: 0 PRIMARY "LongFast" (default key, position precision 0), 1 SECONDARY "Birdmesh" (private key, precision 32). Positions go only on Birdmesh.
- WisMesh buzzers disabled; screen timeout short. T1000 position: broadcast 900 s, smart on (50 m / 30 s), GPS update 30 s.
- To return to public service: set LONG_FAST on all 4 nodes (app for remote nodes; `--set lora.modem_preset LONG_FAST` for the H4).

## 4. Services and run state
| Service | State | What it does |
|---|---|---|
| `exp2` | **enabled, running** | Every 240 s, per node (random order): traceroute + ACK'd weather DM (random op order, 5 s gap, traceroutes ≥45 s apart). Battery request hourly. |
| `meshmap` | disabled | Retired drive-test logger. Must stay stopped — only one program can hold the H4 USB port. |
| `direwolf`, `aprs_exp` | **disabled** (stopped 2026-11-21 20:02) | APRS twin: weather message every 240 s to KR4QIB-7, up to 3 retries 30 s apart. Start: `sudo systemctl enable --now direwolf aprs_exp`. |
- Before any CLI/experiment script: `sudo systemctl stop exp2` (USB port). Restart after.
- Live view: winstonsalembirds.com/mesh-status (summary only; full data on the Pi).

## 5. Data model
- `~/mesh/exp2.db`
  - `sends` — one row per weather DM: ts, cycle, dest_name, delivered (real end-to-end ACK only), reason, latency_s, ack_snr/ack_rssi (last hop into H4), ack_hops, relay_node (last byte), relay_heard, weather, battery cols.
  - `traceroutes` — ts, cycle, dest_name, ok, route_out, snr_out, route_back, snr_back (per-hop SNR in dB, comma-separated). **SNR out = node's receive side; SNR back = node's transmit side.**
  - `telemetry` — battery, voltage, channel util, airtime, uptime per node (hourly).
  - `positions` — every position packet heard (T1000/Rak1 GPS fixes with rx SNR).
- `~/mesh/aprs.db` — `sends` (seq, msgno, attempts, acked, latency_s, weather) and `rx` (every decoded frame incl. UV-Pro beacons with lat/lon/alt).
- `~/mesh/aprs/direwolf.log` — per-packet audio level (target 30–80; FM audio level does NOT track signal strength).
- `experiments/segments.csv` — join any record to a segment by timestamp; analyse only `include=yes`.

## 6. Pi system changes made for this project
- `/etc/modprobe.d/usb-audio-order.conf`: pins BirdNET mic (TI PCM2902 `08bb:2902`) = card 3, Digirig (C-Media `0d8c:0012`) = card 4.
- `/etc/udev/rules.d/90-digirig-no-pulse.rules`: PulseAudio ignores the Digirig so BirdNET's `REC_CARD=default` can never grab it.
- BirdNET `REC_CARD` left at `default` (direct `plughw:3,0` broke recording — the mic is shared via PulseAudio). Backup: `/etc/birdnet/birdnet.conf.bak`.
- Digirig capture gain set to 26 % (−3 dB) and saved with `sudo alsactl store` (was clipping at level ~180).
- Ports 8000/8001 are used by BirdNET services → Direwolf uses 8100/8101.

## 7. What the Pi can and cannot see
- Pi sees only what the H4 hears. Each node's own reception SNR stays on that node — unless returned by a **traceroute** (both directions, every hop), telemetry, or NeighborInfo.
- A message receipt shows only the last hop into the H4; the traceroute in the same cycle gives the full path.
- Airtime is not reported per packet — compute from preset + payload.

## 8. Hard-won lessons
1. **Red dot ≠ not received.** The 1 W H4 reaches nodes whose replies can't get back. Confirmed twice: Meshtastic (H4→T1000 direct −10 dB, T1000→H4 only via Rak2) and APRS (UV-Pro received every message at the brewery, 0/18 receipts reached home).
2. **Height beats distance.** The catwalk node (0.6 mi) outperformed closer nodes in dips; it became the backbone relay.
3. **Traceroutes are rate-limited (~30 s).** One sent within ~25 s of the previous gets no answer. exp2 spaces them 45 s apart since 2026-11-21 11:50; earlier close-spaced failures are artifacts.
4. **A relay's implicit ACK can masquerade as delivery** — exp2 counts only the destination's own ACK.
5. **LoRa SNR saturates** at strong signals (~+6 to +11 dB); use RSSI/latency there. Latency rises (retries) before delivery drops.
6. **Ceiling effect:** on one property everything delivers; real separation or shielding is needed. An open bowl leaks.
7. **`tx_power 0` = region max**, not 0 dBm.
8. **Text messages wake screens and phones** — exp2 uses `PRIVATE_APP` port (invisible in the app; monitor via the website).
9. **APRS setup traps:** FT-65 had a −600 kHz repeater shift (transmitted on 144.410); UV-Pro needed BW 25 kHz, Digital mode OFF (else packets go to the BTech app, not APRSdroid), the edited channel actually selected, and TX High; APRSdroid needs the UV-Pro chosen as "TNC Bluetooth device" with Client mode on; APRS-IS passcode not needed for RF.
10. **One Bluetooth link per radio** — close the BTech app (force-stop) while APRSdroid is connected.
11. **Keep the FT-65 upright** — found tipped on 2026-11-21 (horizontal antenna ≈ 10–20 dB polarization loss).
12. Run commands in the right window: `C:\Users\dclen>` = Windows (scp), `david:~$` = Pi.

## 9. Experiment log (segments in `experiments/segments.csv`)
| Date / segment | Setup | Result |
|---|---|---|
| 11-14 | Drive test LongFast 60 s | Edge SNR −15 to −19 dB at 0.5–1 mi; many reds were ACK failures |
| 11-14 / 11-15 | Exp1 power sweep 1–25 dBm, pilots | 100 % everywhere (ceiling); truck run latency 5 s at 1 dBm |
| 11-20 S02 17:25–20:15 | Rak2 catwalk, Rak1 Swaim's, T1000 car (43 Park Blvd) | Rak2 94 % direct; Rak1 51 %, T1000 59 % — receipts always via Rak2 |
| 11-20/21 S04 overnight | Rak2 + T1000 car | Rak2 99 %, T1000 82 %; better after midnight (colder/humid vs time of day — confounded) |
| 11-21 S06 yard | Rak1 + T1000 in yard | 100 %; yard nodes relayed Rak2's receipts |
| 11-21 S08 brewery (0.2 mi S, downhill) | T1000, Rak1, UV-Pro with user | Mesh 100 % via mobile relays (car nodes relayed Rak2). APRS 0/18 receipts (UV-Pro Low; FT-65 tipped) though UV-Pro received all |
| 11-21 S10 under Rak2 | same | Mesh 100 %; APRS 3/3 first try |
| 11-21 S15 Swaim's (~1.04 mi, 2 h) | same, UV-Pro High, FT-65 upright | Mesh Rak2 93 %, T1000 48 %, Rak1 35 % via 2–3 hop chains (Rak1→T1000→Rak2→H4). APRS 0/34 both ways |
- T1000 vs Rak1 side by side at Swaim's (48 % vs 35 %): not significant (two-proportion p ≈ 0.30).

## 10. Findings so far (for the paper)
- **Link asymmetry:** 10–17 dB weaker on the return leg (power 30 vs 22 dBm + home noise); appears on both LoRa and APRS.
- **Emergent routing:** without any configuration change the mesh formed 2–3 hop relay chains and switched routes minute to minute.
- **APRS vs LoRa physics:** APRS gains ~7 dB (5 W) + ~16 dB (145 vs 907 MHz path loss), but 1200-baud FM packet needs ~+10 dB SNR vs LoRa Long Moderate decoding at ~−17 dB (~27 dB swing). At ~1 mi with no infrastructure APRS failed completely; the relaying mesh partly succeeded. Fair framing: "equal home setups, no digipeaters".
- Next idea: LoRa APRS (433 MHz boards) to separate protocol from modulation.

## 11. Research methods plan
- GLMM: node-pair / segment random effects, weather and time-of-day covariates.
- DEA: input = energy per delivered message (W × airtime × tries); outputs = delivery rate, 1/latency, link margin.
- fsQCA: combinations of conditions sufficient for delivery (emergent behaviour claim).
- Crossover designs (A-B-A-B swaps) to compare devices; traceroute SNR out vs back separates receive vs transmit performance.
