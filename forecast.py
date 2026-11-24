"""Moisture forecasting behind a small interface, so a trained model can replace the rule later."""
from statistics import median
from typing import Protocol, Sequence


class Forecaster(Protocol):
    def predict(self, readings: Sequence[float], irrigation: Sequence[float], horizon: int) -> float:
        """Moisture expected `horizon` cycles after the last reading, assuming no further irrigation.

        readings:   a cell's recent sensor values, oldest first.
        irrigation: moisture points of approved water added between readings[i] and readings[i+1]
                    (one shorter than readings), so the forecaster can separate watering from drying.
        """
        ...


class TrendForecaster:
    """Rule-based forecast: extend the cell's typical recent change per cycle.

    Uses the median change (net of known irrigation), so a single jump from rain or
    hand-watering doesn't distort the trend. With one reading there is no trend yet,
    so it assumes no change."""

    def predict(self, readings, irrigation, horizon):
        if len(readings) < 2:
            return readings[-1]
        changes = [after - before - water for before, after, water in zip(readings, readings[1:], irrigation)]
        return max(0.0, min(100.0, readings[-1] + median(changes) * horizon))
