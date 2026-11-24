"""Simulated environment: weather that acts on the farm, independent of the agents.
Moisture amounts are in points of available water (1 point = 1% of AW = 112 L per cell).

Each number in EnvironmentConfig is labelled with where it comes from:
  FITTED      estimated from real data (source named on the line; data described in data/README.md)
  REFERENCE   taken from a published reference
  ASSUMPTION  a modelling choice with no data behind it yet
"""
from dataclasses import dataclass
import math
import random


@dataclass(frozen=True)
class EnvironmentConfig:
    # --- Temperature: FITTED, NOAA USCRN hourly data, Tucson 11 W, 2024-2025 (reproduce: python calibrate.py) ---
    mean_temp: float = 22.6          # °C, daily average
    temp_amplitude: float = 5.6      # °C, half the day/night swing of the fitted sine (17.0–28.2 °C);
                                     # the real hour-by-hour average runs 16.7–28.6 °C
    peak_hour: float = 15.2          # hottest time of day, local standard time (USCRN hours are stamped
                                     # at their end, so each hourly average is centred half an hour earlier)
    # --- Drying ---
    base_drying_rate: float = .09    # REFERENCE: % of AW lost per cycle at mean_temp, farm average. FAO-56 tomato
                                     # water use ~5 mm/day / 112 mm total available water; consistent with USCRN dry-down
    drying_spread: float = .2        # ASSUMPTION: cell scales span about 1 ± this (0.8–1.2)
    drying_per_degree: float = .02   # FITTED: +2% drying per °C above mean_temp, -2% below. USCRN Tucson
                                     # day-to-day soil moisture loss on rain-free days. Noisy: calibrate.py's
                                     # main estimate is 1.6% (90% range 0.4–2.8%), other day filters give 1.6–3.2%
    min_drying_factor: float = .2    # ASSUMPTION: cells never stop drying completely
    # --- Rain: FITTED, NOAA USCRN hourly precipitation, Tucson 11 W, 2024-2025 (reproduce: python calibrate.py) ---
    # Uniform ranges chosen to keep the data's averages, so annual rain matches (~200% of AW a year).
    rain_chance: float = .0037       # chance a shower starts in a dry 30-minute cycle (~1 every 5.6 days)
    rain_ticks: tuple = (2, 6)       # shower length in cycles (1–3 h, mean 2 h as in the data);
                                     # data: typical 1–4 h (10th–90th percentile), full range 1–9 h
    rain_points: tuple = (.40, 1.12) # % of AW added to every cell per rainy cycle: from the median
                                     # intensity, mean 0.76; data: middle half 0.18–0.94, heaviest hours more
    rain_drying_factor: float = .3   # ASSUMPTION: evaporation multiplier while it rains (cloudy, humid air)
    # --- Starting moisture ---
    smoothing_passes: int = 3        # ASSUMPTION: more passes = larger patches of similar moisture
    # --- Events triggered from the dashboard: all ASSUMPTIONS ---
    heatwave_extra_temp: float = 10  # °C added on top of the daily cycle
    heatwave_ticks: int = 96         # 2 days
    drought_ticks: int = 144         # 3 days with no rain
    drought_drying_factor: float = 1.5  # dry air speeds up evaporation
    manual_water_litres: float = 1000   # hand-watering one cell (~9 points), from outside the shared tank
    refill_litres: float = 5000      # the dashboard's "Add water" refill of the shared tank


def smooth_field(rng, rows, cols, passes):
    """Random values in 0..1 where neighbouring cells are similar.

    Starts from independent noise, then repeatedly replaces each cell with the
    average of itself and its 4 neighbours, and finally stretches the result
    back to the full 0..1 range."""
    grid = [[rng.random() for _ in range(cols)] for _ in range(rows)]
    for _ in range(passes):
        grid = [[_neighbourhood_mean(grid, r, c) for c in range(cols)] for r in range(rows)]
    flat = [v for row in grid for v in row]
    low, high = min(flat), max(flat)
    return [[(v - low) / (high - low) if high > low else .5 for v in row] for row in grid]


def drying_scales(rng, rows, cols, env):
    """Per-cell multipliers on the farm's base drying rate, in slow- and fast-drying patches.

    Uses the same smoothing as the starting moisture, maps it to 1 ± drying_spread, then
    shifts it so the farm average is exactly 1. That keeps base_drying_rate meaning
    "the farm's average rate", which is what a fit to real data will estimate."""
    field = smooth_field(rng, rows, cols, env.smoothing_passes)
    scales = [[1 + env.drying_spread * (2 * v - 1) for v in row] for row in field]
    mean = sum(map(sum, scales)) / (rows * cols)
    return [[s - mean + 1 for s in row] for row in scales]


def _neighbourhood_mean(grid, r, c):
    """Mean of a cell and its up/down/left/right neighbours that exist."""
    spots = [(r, c), (r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)]
    values = [grid[i][j] for i, j in spots if 0 <= i < len(grid) and 0 <= j < len(grid[0])]
    return sum(values) / len(values)


class Weather:
    """Produces the conditions for each 30-minute interval. Uses its own random
    stream so weather draws never shift the sensor noise sequence."""

    def __init__(self, env, tick_minutes, seed):
        self.env = env
        self.tick_minutes = tick_minutes
        self.rng = random.Random(f'{seed}-weather')
        self.rain_left = 0      # cycles left in the current shower
        self.rain_rate = 0.0    # points per cycle of the current shower
        self.heatwave_left = 0  # cycles left in a triggered heatwave
        self.drought_left = 0   # cycles left in a triggered drought

    def hour(self, tick):
        """Hour of day (0–24) at the start of `tick`; tick 0 is midnight."""
        return (tick * self.tick_minutes / 60) % 24

    def temperature(self, tick):
        """Smooth day/night cycle: hottest at peak_hour, coolest 12 hours later."""
        e = self.env
        extra = e.heatwave_extra_temp if self.heatwave_left else 0
        return e.mean_temp + extra + e.temp_amplitude * math.cos(2 * math.pi * (self.hour(tick) - e.peak_hour) / 24)

    def drying_factor(self, temperature):
        """Multiplier on each cell's base drying rate; hotter air dries faster."""
        e = self.env
        return max(e.min_drying_factor, 1 + e.drying_per_degree * (temperature - e.mean_temp))

    def rain(self):
        """Start a shower at random, or continue the current one. Returns points added this cycle."""
        e = self.env
        if self.drought_left:
            self.rain_left = 0
            return 0.0
        if not self.rain_left and self.rng.random() < e.rain_chance:
            self.rain_left = self.rng.randint(*e.rain_ticks)
            self.rain_rate = self.rng.uniform(*e.rain_points)
        if not self.rain_left:
            return 0.0
        self.rain_left -= 1
        return self.rain_rate

    def advance(self, tick):
        """Conditions for the interval starting at `tick`. Call once per cycle."""
        temperature = self.temperature(tick)
        rain = self.rain()
        factor = self.drying_factor(temperature) * (self.env.rain_drying_factor if rain else 1)
        if self.drought_left:
            factor *= self.env.drought_drying_factor
        self.heatwave_left = max(0, self.heatwave_left - 1)
        self.drought_left = max(0, self.drought_left - 1)
        return dict(temperature=temperature, drying_factor=factor, rain=rain)

    def start_heatwave(self):
        """Raise temperatures for heatwave_ticks cycles (restarts if already active)."""
        self.heatwave_left = self.env.heatwave_ticks

    def start_drought(self):
        """Stop all rain and dry the air for drought_ticks cycles (restarts if already active)."""
        self.drought_left = self.env.drought_ticks
        self.rain_left = 0

    def now(self, tick):
        """Conditions shown on the dashboard for the current clock time."""
        temperature = self.temperature(tick)
        factor = self.drying_factor(temperature) * (self.env.drought_drying_factor if self.drought_left else 1)
        return dict(temperature=temperature, drying_factor=factor,
                    raining=self.rain_left > 0, rain_rate=self.rain_rate if self.rain_left else 0.0,
                    heatwave_left=self.heatwave_left, drought_left=self.drought_left)
