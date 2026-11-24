"""Moisture forecasting behind a small interface, so a trained model can replace the rule later."""
from typing import Protocol, Sequence


class Forecaster(Protocol):
    def predict(self, readings: Sequence[float], irrigation: Sequence[float], horizon: int) -> float:
        """Moisture expected `horizon` cycles after the last reading, assuming no further irrigation.
        horizon=0 gives the forecaster's best estimate of the moisture now.

        readings:   a cell's recent sensor values, oldest first.
        irrigation: moisture points of approved water added between readings[i] and readings[i+1]
                    (one shorter than readings), so the forecaster can separate watering from drying.
        """
        ...


class TrendForecaster:
    """Rule-based forecast: a straight-line (least-squares) trend through the recent readings.

    Known irrigation is removed first, so the line shows drying, rain and sensor noise only.
    Fitting a line through many readings averages the noise away: with the default two-day
    window and +-9.4 points of sensor noise (+-18.75 worst case), the trend's error is a few hundredths of a point
    per cycle, well below the ~0.09 points per cycle the soil actually dries. With fewer than
    `min_trend` readings (default 1 day) the slope is too noisy to trust, so it assumes no change
    and uses the readings' average as the estimate."""

    def __init__(self, min_trend=48):
        self.min_trend = min_trend

    def predict(self, readings, irrigation, horizon):
        added = [0.0]                                    # irrigation received since the first reading
        for water in irrigation:
            added.append(added[-1] + water)
        dry = [r - a for r, a in zip(readings, added)]    # readings as if no water had been added
        n = len(dry)
        mean_x, mean_y = (n - 1) / 2, sum(dry) / n
        slope = 0.0
        if n >= self.min_trend:
            sxx = sum((i - mean_x) ** 2 for i in range(n))
            slope = sum((i - mean_x) * (y - mean_y) for i, y in enumerate(dry)) / sxx
        now = mean_y + slope * (n - 1 - mean_x) + added[-1]   # fitted value at the latest reading
        return max(0.0, min(100.0, now + slope * horizon))
