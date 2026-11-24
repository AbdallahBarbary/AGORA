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

## Moisture scale

Moisture is **percent of available water**: 0 = wilting point, 100 = field capacity. A cell is healthy at 60% or more, needs water below 60% (40% of its available water used up, the FAO-56 tomato depletion fraction), and is critical below 30%. Irrigation refills to 100%. One point is 1% of a cell's available water, which is 112 L.

## Demonstration

1. Select **Normal (healthy farm)** (70–100%) and start the simulation. Nobody needs water for the first days; cells dry a little faster in the afternoon heat and the odd shower tops them up. After about three days cells start crossing 60% and get refilled.
2. Select **One zone needs water**. Advance one cycle. The North agent recommends water for its critical cells; the other zones recommend waiting. North needs more water to reach field capacity than the 50,000 L tank holds, so its recommendations are adjusted. Watch the exchange in **Agent messages**.
3. Select **Critical shortage**. Advance a cycle. Because the Manager announces scarce water, zone agents recommend only part of each gap. Critical recommendations are adjusted proportionally; normal ones are rejected. The Manager report shows **water short**, the zones prioritised for critical cells, and the zones whose normal requests were reduced or delayed.
4. Select **Empty tank**. Advance a cycle, add 5,000 L, then advance again. Irrigation resumes.
5. Select any cell to inspect its history, its 1-hour forecast, the scores of each option, and the Manager's decision. Filter the log by zone or priority and export it (with the message feed) as JSON.
6. While it runs, trigger **Heatwave** (+10 °C for 2 days) or **Drought** (no rain and drier air for 3 days) from the Events bar. In the cell inspector, **Water cell** hand-waters the selected cell (+1,000 L, outside the shared tank).

Selecting a scenario resets the run immediately. Reset restarts the selected scenario with seed 42. Start runs cycles automatically; Next cycle pauses and advances exactly once. Speed controls wall-clock playback only; each cycle still represents 30 simulated minutes.

## How it works

`engine.py` contains Farm, SimulatedSensor, and SimulatedIrrigation, and runs each cycle. `agents.py` contains the four ZoneAgent instances and the ManagerAgent. They talk only through `messaging.py`'s MessageBus:

1. The Manager broadcasts the tank level and a water price that rises from ×1 (plentiful) to ×3 (empty tank).
2. Each zone agent records its cells' noisy readings (±9.4 points) and keeps two days of them per cell. The forecaster lives behind the `Forecaster` interface in `forecast.py`; the current `TrendForecaster` is rule-based: it fits a straight line through the readings, net of the water the Manager approved, which averages the noise away. It gives a smoothed estimate of the moisture now and a forecast about an hour ahead. With less than a day of readings (48) it uses their average and no trend; with fewer than 4 an agent recommends nothing unless the cell is already critical.
3. For each cell it scores three options (wait, part of the gap, full gap) with the project deck's utility `0.5 × benefit + 0.3 × urgency − 0.2 × cost`, each term scaled 0–1. Benefit is the share of the cell's available water restored, counted only below the 60% line (above it the crop isn't stressed). Urgency is the stress avoided: how far below 60% the cell would be, counted double below 30%. Cost is the share of available water used, times the Manager's price. It sends the Manager a recommendation with its reason for every cell that shouldn't wait, plus one zone status. A zone is stressed when more than 4 of its 16 cells are estimated below 60%.
4. The Manager is the only agent that decides. It allocates critical recommendations first, then normal ones, sharing proportionally when short and never exceeding the tank. It marks each recommendation approved, adjusted or rejected, with a reason, and replies to each zone. Only approved water reaches the actuator.

The dashboard shows the message feed and, in the decision log, each zone's recommendation next to the Manager's decision. Every message is delivered every cycle, but the feed folds an unchanged repeat (the same rejection, the same recommendation, the same tank broadcast within 3 hours) into one entry with its cycle range and a repeat count, so an empty tank doesn't flood it.

`environment.py` holds the environment the agents live in: `EnvironmentConfig` (all weather and event numbers), `Weather` (daily temperature cycle, random rain, heatwave and drought), and `smooth_field` (starting moisture where neighbouring cells are similar), and `drying_scales` (per-cell drying multipliers in similar patches). Each cycle, irrigation is applied first, then rain adds moisture and evaporation removes `base drying rate × cell drying scale × weather drying factor`. The drying factor grows with temperature, drops while it rains, and rises during a drought. Weather uses its own random stream, so it never shifts the sensor noise.

`server.py` exposes the state and step/reset/refill/event actions on a local HTTP server. `web/` provides the custom browser interface. State lives in memory and is shared between browser tabs. Restarting the server resets it. The simulation advances only while the browser runs it or the user requests a step.

## Parameters and limitations

Each value in the code is labelled with its origin: **FITTED** (from real data), **REFERENCE** (from a published source) or **ASSUMPTION** (a modelling choice). The data is described in `data/README.md`.

| Setting | Value | Origin |
|---|---|---|
| Daily temperature | mean 22.6 °C, ±5.6 °C, hottest at 15.7 h | FITTED: NOAA USCRN hourly, Tucson 11 W, 2024–2025 |
| Base drying rate | 0.09% of available water per 30-minute cycle at the mean temperature | REFERENCE: FAO-56 tomato water use ~5 mm/day ÷ 112 mm available water; consistent with USCRN dry-down |
| Heat effect on drying | +2% per °C | FITTED: USCRN rain-free day-to-day soil moisture loss (noisy, 1–3.5%) |
| Showers | 0.0037 chance per cycle, 2–8 cycles long, 0.45–0.71% of available water per cycle | FITTED: USCRN Tucson hourly precipitation |
| Litres per point | 112 (11,200 L of available water ÷ 100) | REFERENCE: 100 m² cell × 0.7 m tomato roots × 160 mm/m available water (loam) |
| Irrigation trigger | 60% (40% of available water used up) | REFERENCE: FAO-56 Table 22, tomato p = 0.40 |
| Target / critical | 100% (field capacity) / 30% | ASSUMPTION |
| Sensor noise | ±9.375 points, uniform | ASSUMPTION: METER TEROS 10 accuracy with soil-specific calibration, ±0.015 m³/m³ (midpoint of METER's ±0.01–0.02), ÷ 0.16 m³/m³ available water (loam). Worst case: generic calibration ±0.03 m³/m³ = ±18.75 points. Independent tests report errors nearer ±0.03 even after calibration |
| Starting moisture | Normal 70–100%, One zone 80–100% (North 18–36%), Critical shortage and Empty 15–45% | ASSUMPTION |
| Tanks | Normal 100,000 L, One zone 50,000 L, Critical shortage 10,000 L, Empty 0 | ASSUMPTION |
| Refill button / hand-watering | 5,000 L / 1,000 L | ASSUMPTION |
| Cell drying spread, rain evaporation ×0.3, minimum drying ×0.2, smoothing, heatwave and drought sizes | | ASSUMPTION |
| "Plentiful" tank level for the Manager's water price | 100,000 L (a full Normal tank); price ×1 to ×3 | ASSUMPTION |
| Utility weights | benefit 0.5, urgency 0.3, cost 0.2 | ASSUMPTION: the project deck |
| Forecasting | 1 hour ahead, 2-day window, trend from 48 readings (1 day), act from 4 (sooner if critical), part of the gap = half | ASSUMPTION |

Each cell dries at the base rate times its own drying scale. The scales sit around 1 (about 0.8–1.2), come in slow- and fast-drying patches made with the same smoothing as the starting moisture, and average exactly 1 across the farm, so the base rate is the farm-average rate. The agents' water cost is a share of the cell's available water, not litres, so their decisions don't change when the litres-per-point conversion does. None of this is an agronomic recommendation.

The farm map shows internal simulator state. Agents receive noisy sensor values (not clipped, so they can read past 0 or 100) and act on their smoothed estimate; the inspector shows the raw reading, the estimate and the forecast separately. History retains 60 points; the decision log and export retain the latest 500 per-cell decisions. Zone totals describe the latest cycle, while tank usage is cumulative.

This milestone uses explicit rules, not a trained prediction model or an LLM. It does not include temperature control, seeding, soil water movement between cells, negotiation between zones, joint assessment, persistence, or real hardware. Hardware adapters can later implement the sensor and actuator boundaries, with additional feedback and failure handling required before physical use.

