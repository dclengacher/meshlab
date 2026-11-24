#!/usr/bin/env python3
"""Weekly weather model for the fixed H4 <-> Rak2 link.

Target: return-link SNR (Rak2 -> H4, direct traceroutes only). Delivery to Rak2
is ~100 %, so link *margin* is the outcome that varies with weather.
Data: home-only periods (Rak1 and T1000 not out on a trip; Rak2 on the catwalk),
taken from ~/mesh/experiments/segments.csv.

For each weather variable, finds the single cut that best splits SNR
(least squares, min 40 obs per side). Writes the ranked splits to
~/mesh/model/wx_splits.json; /mesh-status uses the top two.
Stdlib only. Run weekly from cron.
"""
import csv, json, os, sqlite3
from datetime import datetime

DB = "/home/david/mesh/exp2.db"
SEG = "/home/david/mesh/experiments/segments.csv"
OUT = "/home/david/mesh/model/wx_splits.json"
HOME = {"home", "home_on", "off", "yard_20ft_lower_30ft_N", "yard_20ft_lower_30ft_W",
        "home_indoors_unknown_spot"}
VARS = {"hum": "Humidity", "temp_f": "Temperature", "pres_in": "Pressure", "hour": "Hour of day"}
UNITS = {"hum": "%", "temp_f": "°F", "pres_in": " inHg", "hour": ":00"}
MIN_SIDE = 40


def home_windows():
    out = []
    with open(SEG) as f:
        for r in csv.DictReader(f):
            if r["rak2"] == "uncsa_catwalk" and r["rak1"] in HOME and r["t1000"] in HOME:
                out.append((r["start"].replace(" ", "T"), (r["end"] or "2100-01-01 00:00").replace(" ", "T")))
    return out


def in_any(ts, wins):
    return any(a <= ts < b for a, b in wins)


def load():
    wins = home_windows()
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    wx = {c: (t, h, p) for c, t, h, p in con.execute(
        "SELECT cycle, temp_f, hum, pres_in FROM sends WHERE dest_name='Rak2'")}
    rows = []
    for ts, cyc, sb in con.execute(
            "SELECT ts, cycle, snr_back FROM traceroutes WHERE dest_name='Rak2' AND ok=1 "
            "AND route_out='H4 > Rak2' AND route_back='Rak2 > H4'"):
        if cyc not in wx or not in_any(ts, wins) or None in wx[cyc]:
            continue
        try:
            y = float(sb.split(",")[-1])
        except (ValueError, AttributeError):
            continue
        t, h, p = wx[cyc]
        rows.append(dict(y=y, temp_f=t, hum=h, pres_in=p, hour=int(ts[11:13]), day=ts[:10]))
    con.close()
    return rows


def mean(v):
    return sum(v) / len(v)


def best_split(rows, var):
    ys = [r["y"] for r in rows]
    m = mean(ys)
    tot = sum((y - m) ** 2 for y in ys)
    best = None
    for cut in sorted({r[var] for r in rows}):
        lo = [r["y"] for r in rows if r[var] <= cut]
        hi = [r["y"] for r in rows if r[var] > cut]
        if len(lo) < MIN_SIDE or len(hi) < MIN_SIDE:
            continue
        ml, mh = mean(lo), mean(hi)
        sse = sum((y - ml) ** 2 for y in lo) + sum((y - mh) ** 2 for y in hi)
        if best is None or sse < best["sse"]:
            best = dict(sse=sse, cut=cut, mean_le=ml, mean_gt=mh, n_le=len(lo), n_gt=len(hi))
    if not best or not tot:
        return None
    lo_days = {r["day"] for r in rows if r[var] <= best["cut"]}
    hi_days = {r["day"] for r in rows if r[var] > best["cut"]}
    return dict(var=var, label=VARS[var], unit=UNITS[var], cut=round(best["cut"], 3),
                r2=round(1 - best["sse"] / tot, 3),
                snr_le=round(best["mean_le"], 2), snr_gt=round(best["mean_gt"], 2),
                n_le=best["n_le"], n_gt=best["n_gt"], days_le=len(lo_days), days_gt=len(hi_days))


def main():
    rows = load()
    splits = [s for s in (best_split(rows, v) for v in VARS) if s]
    splits.sort(key=lambda s: s["r2"], reverse=True)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    res = dict(fitted=datetime.now().isoformat(timespec="minutes"), n=len(rows),
               target="Return-link SNR Rak2→H4 (dB), direct traceroutes, home-only periods",
               splits=splits)
    with open(OUT, "w") as f:
        json.dump(res, f, indent=1)
    print(f"{res['fitted']} n={len(rows)}")
    for s in splits:
        print(f"  {s['label']:12s} cut {s['cut']}{s['unit']}  R2={s['r2']}  "
              f"SNR {s['snr_le']} (n={s['n_le']}) vs {s['snr_gt']} (n={s['n_gt']})")


if __name__ == "__main__":
    main()
