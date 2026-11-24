"""Reproduce the FITTED numbers in environment.py from the NOAA USCRN data in data/uscrn,
print them next to the values in the code, and say where they differ.

Run:  python calibrate.py        (needs the Tucson 11 W files listed in data/README.md)

Methods (all on hourly02 data; USCRN missing codes -9999.0 / -99.000 are skipped):
  temperature   mean of the 24 hour-of-day averages of T_HR_AVG (so the 2024 nightly gaps don't
                bias it), then the first harmonic (sine) of that daily cycle: amplitude and the
                hour of its peak. Hours are stamped at their END, so each hour is centred 0.5 h earlier.
  heat effect   day-to-day loss of mean soil moisture (5 and 10 cm averaged) on rain-free days
                (no rain that day or the 3 before) with soil wetter than 0.05 m3/m3, regressed on
                the day's mean temperature; the slope divided by the mean loss is the % change per C.
                Noisy, so it also reports a bootstrap range and alternative day filters.
  showers       a spell is a run of consecutive wet hours (P_CALC > 0). Chance = spells per dry
                30-minute cycle. Rain per cycle = rain per wet hour / 2, as % of available water.
"""
import math
import random
import statistics as st
import sys
from pathlib import Path

from engine import Config
from environment import EnvironmentConfig

DATA = Path(__file__).parent / 'data' / 'uscrn'
FILES = sorted(DATA.glob('CRNH0203-*-AZ_Tucson_11_W.txt'))
MISSING = {'-9999.0', '-99.000'}
COL = dict(lst_date=3, lst_time=4, t=9, p=12, sm5=28, sm10=29)   # 0-based, from HEADERS.txt


def load(files=FILES):
    """Hourly rows as dicts; missing values become None."""
    if not files:
        raise FileNotFoundError(f'No USCRN files in {DATA}; see data/README.md for how to download them.')
    rows = []
    for path in files:
        for line in open(path, encoding='ascii'):
            f = line.split()
            if len(f) != 38:
                continue
            val = lambda i: None if f[i] in MISSING else float(f[i])
            rows.append(dict(date=f[COL['lst_date']], hour=int(f[COL['lst_time']][:2]),
                             t=val(COL['t']), p=val(COL['p']), sm5=val(COL['sm5']), sm10=val(COL['sm10'])))
    return rows


def fit_temperature(rows):
    """Mean, daily swing (half of the sine's peak-to-trough) and hottest hour, local standard time."""
    by_hour = {}
    for r in rows:
        if r['t'] is not None:
            by_hour.setdefault(r['hour'], []).append(r['t'])
    cycle = {h: st.mean(v) for h, v in by_hour.items()}
    mean = st.mean(cycle.values())
    a = sum(t * math.cos(2 * math.pi * (h - .5) / 24) for h, t in cycle.items()) * 2 / 24
    b = sum(t * math.sin(2 * math.pi * (h - .5) / 24) for h, t in cycle.items()) * 2 / 24
    peak = (math.degrees(math.atan2(b, a)) / 15) % 24
    return dict(mean=mean, amplitude=math.hypot(a, b), peak=peak,
                hourly_range=(min(cycle.values()), max(cycle.values())))


def _daily(rows):
    days = {}
    for r in rows:
        days.setdefault(r['date'], []).append(r)
    out = {}
    for d, hs in days.items():
        ts = [h['t'] for h in hs if h['t'] is not None]
        sm = [(h['sm5'] + h['sm10']) / 2 for h in hs if h['sm5'] is not None and h['sm10'] is not None]
        if len(hs) >= 24 and len(ts) >= 20 and len(sm) >= 20:
            out[d] = dict(t=st.mean(ts), p=sum(h['p'] or 0 for h in hs), sm=st.mean(sm))
    return out


def _heat_effect(pairs):
    xs, ys = [p[0] for p in pairs], [p[1] for p in pairs]
    mx, my = st.mean(xs), st.mean(ys)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    return slope / my


def fit_heat_effect(rows, seed=1):
    """% more drying per C, with a bootstrap 90% range and how much the day filter matters."""
    daily = _daily(rows)
    keys = sorted(daily)
    pairs = []   # (day's mean temperature, loss since the day before, soil moisture the day before)
    for i in range(3, len(keys)):
        window = keys[i - 3:i + 1]
        if any(daily[k]['p'] > 0 for k in window):
            continue
        prev, day = daily[keys[i - 1]], daily[keys[i]]
        pairs.append((day['t'], prev['sm'] - day['sm'], prev['sm']))
    main = [p for p in pairs if p[2] > .05]
    rng = random.Random(seed)
    boot = sorted(_heat_effect([rng.choice(main) for _ in main]) for _ in range(500))
    variants = {'all rain-free days': pairs, 'soil > 0.05 (main)': main,
                'soil > 0.08': [p for p in pairs if p[2] > .08], 'losses > 0 only': [p for p in pairs if p[1] > 0]}
    return dict(value=_heat_effect(main), n=len(main), range90=(boot[25], boot[475]),
                variants={k: _heat_effect(v) for k, v in variants.items()})


def fit_rain(rows, available_water_mm):
    """Shower chance per dry cycle, spell length and rain per cycle (% of available water)."""
    rain = [r['p'] or 0.0 for r in rows]
    spells, current = [], []
    for p in rain + [0.0]:
        if p > 0:
            current.append(p)
        elif current:
            spells.append(current)
            current = []
    per_cycle = sorted(p / 2 / available_water_mm * 100 for s in spells for p in s)   # per wet hour, halved
    lengths = sorted(2 * len(s) for s in spells)                                          # in 30-min cycles
    q = lambda xs, f: xs[min(len(xs) - 1, int(f * len(xs)))]
    years = len(rows) / 8766
    dry_cycles = 2 * sum(p == 0 for p in rain)
    mean_len, mean_rate, median_rate = st.mean(lengths), st.mean(per_cycle), q(per_cycle, .5)
    # Uniform ranges for the simulator that keep the data's averages (method of moments):
    # length starts at the shortest spell; rain per cycle starts at the median intensity.
    shortest = lengths[0]
    return dict(chance=len(spells) / dry_cycles, spells_per_year=len(spells) / years,
                length_mean=mean_len, length_typical=(q(lengths, .1), q(lengths, .9)), length_full=(lengths[0], lengths[-1]),
                length_fit=(shortest, round(2 * mean_len - shortest)),
                rate_mean=mean_rate, rate_median=median_rate, rate_iqr=(q(per_cycle, .25), q(per_cycle, .75)),
                rate_fit=(round(median_rate, 2), round(2 * mean_rate - median_rate, 2)),
                annual=sum(rain) / years / available_water_mm * 100)


def simulated_annual_rain(env):
    """Expected rain per year (% of AW) from the simulator's settings."""
    spells = env.rain_chance * 2 * 8766
    return spells * st.mean(range(env.rain_ticks[0], env.rain_ticks[1] + 1)) * st.mean(env.rain_points)


def compare(rows=None, env=None, config=None):
    """Rows of (name, fitted, in code, verdict)."""
    rows = rows if rows is not None else load()
    env, config = env or EnvironmentConfig(), config or Config()
    aw_mm = config.litres_per_point * 100 / config.cell_area_m2          # available water as mm of water
    t, h, r = fit_temperature(rows), fit_heat_effect(rows), fit_rain(rows, aw_mm)
    close = lambda a, b, tol: abs(a - b) <= tol
    out = [
        ('mean temperature (C)', f"{t['mean']:.1f}", f'{env.mean_temp:g}', close(t['mean'], env.mean_temp, .15)),
        ('daily swing (+- C)', f"{t['amplitude']:.1f}", f'{env.temp_amplitude:g}', close(t['amplitude'], env.temp_amplitude, .15)),
        ('hottest hour (LST)', f"{t['peak']:.1f}", f'{env.peak_hour:g}', close(t['peak'], env.peak_hour, .25)),
        ('heat effect (% per C)', f"{h['value'] * 100:.1f} (90%: {h['range90'][0] * 100:.1f}-{h['range90'][1] * 100:.1f})",
         f'{env.drying_per_degree * 100:g}', h['range90'][0] <= env.drying_per_degree <= h['range90'][1]),
        ('shower chance per dry cycle', f"{r['chance']:.4f}", f'{env.rain_chance:g}', close(r['chance'], env.rain_chance, .0002)),
        ('shower length (cycles)', f"{r['length_fit'][0]}-{r['length_fit'][1]} (mean {r['length_mean']:.1f})",
         f'{env.rain_ticks[0]}-{env.rain_ticks[1]}', tuple(env.rain_ticks) == r['length_fit']),
        ('rain per cycle (% AW)', f"{r['rate_fit'][0]:.2f}-{r['rate_fit'][1]:.2f} (mean {r['rate_mean']:.2f})",
         f'{env.rain_points[0]:g}-{env.rain_points[1]:g}', all(close(a, b, .03) for a, b in zip(env.rain_points, r['rate_fit']))),
        ('annual rain (% AW)', f"{r['annual']:.0f}", f'{simulated_annual_rain(env):.0f}', close(simulated_annual_rain(env), r['annual'], .05 * r['annual'])),
    ]
    return out, dict(temperature=t, heat=h, rain=r)


def main():
    try:
        rows = load()
    except FileNotFoundError as e:
        sys.exit(str(e))
    table, detail = compare(rows)
    print(f'USCRN Tucson 11 W: {len(rows):,} hours from {len(FILES)} files\n')
    print(f"{'value':30} {'fitted from data':32} {'in code':10} verdict")
    for name, fitted, code, ok in table:
        print(f"{name:30} {fitted:32} {code:10} {'matches' if ok else 'DIFFERS'}")
    t, h, r = detail['temperature'], detail['heat'], detail['rain']
    print('\nNotes')
    print(f"  temperature: the sine has +-{t['amplitude']:.1f} C, while the hour-by-hour average runs "
          f"{t['hourly_range'][0]:.1f}-{t['hourly_range'][1]:.1f} C (the real cycle isn't a perfect sine).")
    print(f"  heat effect: {h['n']} rain-free days; other day filters give "
          + ', '.join(f'{k} {v * 100:.1f}%' for k, v in h['variants'].items()) + '.')
    print(f"  showers: {r['spells_per_year']:.1f} per year. Length full range {r['length_full'][0]}-{r['length_full'][1]} cycles, "
          f"typical (10th-90th percentile) {r['length_typical'][0]}-{r['length_typical'][1]}; the fitted range keeps the mean.")
    print(f"  rain per cycle: median {r['rate_median']:.2f}, middle half {r['rate_iqr'][0]:.2f}-{r['rate_iqr'][1]:.2f}; "
          f"the fitted uniform range starts at the median and keeps the mean, so annual rain matches.")


if __name__ == '__main__':
    main()
