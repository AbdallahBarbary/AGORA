"""Simulated environment: weather that acts on the farm, independent of the agents.

Every number in EnvironmentConfig is a PROVISIONAL PLACEHOLDER chosen to make the
demonstration readable. They will be replaced by values fitted from real data.
"""
from dataclasses import dataclass
import math
import random


@dataclass(frozen=True)
class EnvironmentConfig:
    # --- Temperature (PROVISIONAL placeholders) ---
    mean_temp: float = 20            # °C, daily average
    temp_amplitude: float = 8        # °C, half the day/night swing (12–28 °C)
    peak_hour: float = 14            # hottest hour of the day
    # --- Drying (PROVISIONAL placeholders) ---
    drying_per_degree: float = .05   # +5% drying per °C above mean_temp, -5% below
    min_drying_factor: float = .2    # cells never stop drying completely
    # --- Rain (PROVISIONAL placeholders) ---
    rain_chance: float = .02         # chance a shower starts in a dry 30-minute cycle (~1 per day)
    rain_ticks: tuple = (2, 6)       # shower length in cycles (1–3 hours)
    rain_points: tuple = (1.0, 3.0)  # moisture points added to every cell per rainy cycle
    rain_drying_factor: float = .3   # evaporation multiplier while it rains (cloudy, humid air)
    # --- Starting moisture (PROVISIONAL placeholder) ---
    smoothing_passes: int = 3        # more passes = larger patches of similar moisture
    # --- Events triggered from the dashboard (PROVISIONAL placeholders) ---
    heatwave_extra_temp: float = 10  # °C added on top of the daily cycle
    heatwave_ticks: int = 96         # 2 days
    drought_ticks: int = 144         # 3 days with no rain
    drought_drying_factor: float = 1.5  # dry air speeds up evaporation
    manual_water_litres: float = 10  # hand-watering one cell, from outside the shared tank


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
