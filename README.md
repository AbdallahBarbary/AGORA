# AGORA — first milestone

A local Python prototype of Manager-led irrigation across an 8 × 8 simulated farm. The custom dashboard follows the supplied video's charcoal panels, status colors, filters, and side inspector.

## Run

Requires Python 3.10 or later. No third-party packages are required to run the application.

```powershell
cd path\to\AGORA
python server.py
```

Open http://127.0.0.1:8765 in your browser. Keep the terminal running. Stop it with Ctrl+C.

Run checks with `python -m unittest -v` from this directory.

## Demonstration

1. Select **Normal (healthy farm)** and start the simulation. Nobody needs water at first; watch cells dry faster in the afternoon heat, and watch rain showers top them up.
1. Select **One zone needs water**. Advance one cycle. The North agent recommends water for its cells; the other zones recommend waiting. Watch the exchange in **Agent messages**.
2. Select **Sufficient water**. Advance a cycle. All recommendations are approved.
3. Select **Critical shortage**. Advance a cycle. Because the Manager announces scarce water, zone agents recommend only part of each gap. Critical recommendations are adjusted proportionally; normal ones are rejected. The Manager report shows **water short**, the zones prioritised for critical cells, and the zones whose normal requests were reduced or delayed.
4. Select **Empty tank**. Advance a cycle, add 5,000 L, then advance again. Irrigation resumes.
5. Select any cell to inspect its history, its 1-hour forecast, the scores of each option, and the Manager's decision. Filter the log by zone or priority and export it (with the message feed) as JSON.
6. While it runs, trigger **Heatwave** (+10 °C for 2 days) or **Drought** (no rain and drier air for 3 days) from the Events bar. In the cell inspector, **Water cell** hand-waters the selected cell (+10 L, outside the shared tank).

Selecting a scenario resets the run immediately. Reset restarts the selected scenario with seed 42. Start runs cycles automatically; Next cycle pauses and advances exactly once. Speed controls wall-clock playback only; each cycle still represents 30 simulated minutes.

## How it works

`engine.py` contains Farm, SimulatedSensor, and SimulatedIrrigation, and runs each cycle. `agents.py` contains the four ZoneAgent instances and the ManagerAgent. They talk only through `messaging.py`'s MessageBus:

1. The Manager broadcasts the tank level and a cost per litre that rises as the tank empties.
2. Each zone agent records its cells' noisy readings and forecasts each cell about an hour ahead. The forecaster lives behind the `Forecaster` interface in `forecast.py`; the current `TrendForecaster` is rule-based: it extends the median recent change per cycle, net of the water the Manager approved.
3. For each cell it scores three options (wait, part of the gap, full gap) with `utility = benefit + urgency − water cost`. Benefit counts moisture points moved toward the 55% target, urgency counts points of danger avoided below 40% (extra below 25%), and cost is litres × cost per litre plus a fixed cost for any irrigation. It sends the Manager a recommendation with its reason for every cell that shouldn't wait, plus one zone status.
4. The Manager is the only agent that decides. It allocates critical recommendations first, then normal ones, sharing proportionally when short and never exceeding the tank. It marks each recommendation approved, adjusted or rejected, with a reason, and replies to each zone. Only approved water reaches the actuator.

The dashboard shows the message feed and, in the decision log, each zone's recommendation next to the Manager's decision.

`environment.py` holds the environment the agents live in: `EnvironmentConfig` (all weather and event numbers), `Weather` (daily temperature cycle, random rain, heatwave and drought), and `smooth_field` (starting moisture where neighbouring cells are similar), and `drying_scales` (per-cell drying multipliers in similar patches). Each cycle, irrigation is applied first, then rain adds moisture and evaporation removes `base drying rate × cell drying scale × weather drying factor`. The drying factor grows with temperature, drops while it rains, and rises during a drought. Weather uses its own random stream, so it never shifts the sensor noise.

`server.py` exposes the state and step/reset/refill/event actions on a local HTTP server. `web/` provides the custom browser interface. State lives in memory and is shared between browser tabs. Restarting the server resets it. The simulation advances only while the browser runs it or the user requests a step.

## Parameters and limitations

Each value in the code is labelled with its origin: **FITTED** (from real data), **REFERENCE** (from a published source), **ASSUMPTION** (a modelling choice), or **PROVISIONAL** (a placeholder still to be fitted). The data is described in `data/README.md`.

| Setting | Value | Origin |
|---|---|---|
| Daily temperature | mean 22.6 °C, ±5.6 °C, hottest at 15.7 h | FITTED: NOAA USCRN hourly, Tucson 11 W, 2024–2025 |
| Base drying rate | 0.09 points per 30-minute cycle at the mean temperature | REFERENCE: FAO-56 tomato water use ~5 mm/day ÷ 112 mm available water; consistent with USCRN dry-down |
| Heat effect on drying | +2% per °C | FITTED: USCRN rain-free day-to-day soil moisture loss (noisy, 1–3.5%) |
| Showers | 0.0037 chance per cycle, 2–8 cycles long, 0.45–0.71 points per cycle | FITTED: USCRN Tucson hourly precipitation |
| Litres per moisture point | 112 | REFERENCE: 100 m² cell × 0.7 m tomato roots × 160 mm/m available water (loam) |
| Tanks | Normal and Sufficient water 100,000 L, One zone 50,000 L, Critical shortage 10,000 L, Empty 0 | ASSUMPTION |
| Refill button / hand-watering | 5,000 L / 1,000 L | ASSUMPTION |
| Cell drying spread, rain evaporation ×0.3, minimum drying ×0.2, smoothing, heatwave and drought sizes | | ASSUMPTION |
| "Plentiful" tank level for the Manager's water cost | 100,000 L (a full Normal tank) | ASSUMPTION |
| Target 55%, request line 40%, critical 25%, starting moisture ranges, sensor noise ±0.6 | | unchanged; the moisture scale is a separate step |
| Agent weights: 1-hour forecast from 4 readings, benefit 0.6, urgency 1.5 (×3 below critical), water cost 0.5–1.25 per moisture point, fixed irrigation cost 3 | | PROVISIONAL |

Each cell dries at the base rate times its own drying scale. The scales sit around 1 (about 0.8–1.2), come in slow- and fast-drying patches made with the same smoothing as the starting moisture, and average exactly 1 across the farm, so the base rate is the farm-average rate. The agents' water cost is per moisture point, not per litre, so their decisions don't change when the litres-per-point conversion does. None of this is an agronomic recommendation.

The farm map shows internal simulator state. Agents receive noisy sensor values before the action; the inspector labels those separately. History retains 60 points; the decision log and export retain the latest 500 per-cell decisions. Zone totals describe the latest cycle, while tank usage is cumulative.

This milestone uses explicit rules, not a trained prediction model or an LLM. It does not include temperature control, seeding, soil water movement between cells, negotiation between zones, joint assessment, persistence, or real hardware. Hardware adapters can later implement the sensor and actuator boundaries, with additional feedback and failure handling required before physical use.

