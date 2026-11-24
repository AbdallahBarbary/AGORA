# AGORA — first milestone

A local Python prototype of Manager-led irrigation across an 8 × 8 simulated farm. The custom dashboard follows the supplied video's charcoal panels, status colors, filters, and side inspector.

## Run

Requires Python 3.10 or later. No third-party packages are required to run the application.

```powershell
cd path\to\AGORA
python server.py
```

Open http://127.0.0.1:8765 in your browser. Keep the terminal running. Stop it with Ctrl+C.

Run checks with `python -m unittest -v` from this directory. Re-derive the FITTED numbers from the downloaded data with `python calibrate.py`.

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

## Numbers and sources

Every tunable number in the project, taken from the code (`engine.py` `Config`, `TANK`, `MOISTURE`; `environment.py` `EnvironmentConfig`; `agents.py` `AgentConfig`; `messaging.py`). **FITTED** = estimated from real data, **REFERENCE** = taken from a published source, **ASSUMPTION** = a modelling choice. The data is described in `data/README.md`. Moisture is % of available water (AW): 0 = wilting point, 100 = field capacity.

**Reproducing the FITTED values:** `python calibrate.py` reads `data/uscrn/`, re-derives every FITTED number, prints it next to the value in the code and marks any difference. All of them currently match. A test runs the same check whenever the data files are present.

| Number | Value in the code | Type | Source / note | Where |
|---|---|---|---|---|
| Cell size | 100 m² | ASSUMPTION | 10 m × 10 m cells | `Config.cell_area_m2` |
| Root depth | 0.7 m | REFERENCE | FAO-56 Table 22, tomato (0.7–1.5 m; the shallow end) | `Config.root_depth_m` |
| Available water per metre of soil | 160 mm/m (0.16 m³/m³) | REFERENCE | UMN Extension, loam. A stand-in for FAO-56 Table 19 that still needs verifying (see Known limitations) | `Config.available_water_mm_per_m` |
| Total available water per cell | 11,200 L (112 mm) | REFERENCE (derived) | 100 m² × 0.7 m × 160 mm/m | follows from the three above |
| Litres per point | 112 L | REFERENCE (derived) | 11,200 L ÷ 100 points, so 1 point = 1% of AW; a test checks it against the three inputs | `Config.litres_per_point` |
| Irrigation trigger | 60% | REFERENCE | FAO-56 Table 22, tomato depletion fraction p = 0.40 (40% of AW used up) | `Config.trigger` |
| Target | 100% (field capacity) | ASSUMPTION | Irrigation refills a cell to field capacity | `Config.target` |
| Critical level | 30% | ASSUMPTION | Well past the stress line; served first in shortages | `Config.critical` |
| Daily water use | ~5 mm/day → 0.09% of AW per 30-min cycle at the mean temperature | REFERENCE ⚠ | "FAO-56 tomato water use" ÷ 112 mm AW; consistent with the USCRN dry-down. Cites FAO-56 generally, not a table or an ET₀ × Kc calculation | `EnvironmentConfig.base_drying_rate` |
| Heat effect | +2% drying per °C above the mean (−2% below), floor ×0.2 | FITTED (floor: ASSUMPTION) | USCRN Tucson day-to-day soil moisture loss on rain-free days. Noisy: `calibrate.py` estimates 1.6% (90% range 0.4–2.8%), and other choices of days give 1.6–3.2%. 2% sits inside that range, so it was kept | `drying_per_degree`, `min_drying_factor` |
| Temperature cycle | mean 22.6 °C, ±5.6 °C, hottest at 15.2 h (17.0–28.2 °C) | FITTED | NOAA USCRN hourly, Tucson 11 W, 2024–2025. The sine is the daily cycle's main harmonic; the real hour-by-hour average runs 16.7–28.6 °C | `mean_temp`, `temp_amplitude`, `peak_hour` |
| Shower chance | 0.0037 per dry 30-min cycle (~65 showers a year) | FITTED | NOAA USCRN hourly precipitation, Tucson 11 W, 2024–2025 | `rain_chance` |
| Shower length | 2–6 cycles (1–3 h), uniform; mean 2 h | FITTED (a range chosen to keep the mean) | Data: mean 2.05 h, typical 1–4 h (10th–90th percentile), full range 1–9 h. The range keeps the data's mean length rather than covering every shower | `rain_ticks` |
| Rain per cycle | 0.40–1.12% of AW per rainy cycle, uniform; mean 0.76 | FITTED (a range chosen to keep the mean) | Data: per-hour intensity median 0.40, mean 0.76, middle half 0.18–0.94, heaviest hours more. The range runs from the median and keeps the mean, so annual rain matches (model 197% of AW a year, data 202%) | `rain_points` |
| Evaporation while raining | ×0.3 | ASSUMPTION | Cloudy, humid air | `rain_drying_factor` |
| Cell drying spread | each cell × 0.8–1.2 (1 ± 0.2), smoothed in patches, farm average exactly 1 | ASSUMPTION | | `drying_spread`, `smoothing_passes` = 3 |
| Sensor noise | ±9.375 points, uniform | ASSUMPTION | METER TEROS 10 tech specs: ±0.015 m³/m³, the midpoint of the ±0.01–0.02 soil-specific-calibration accuracy, ÷ 0.16 m³/m³. Worst case: generic calibration ±0.03 m³/m³ = ±18.75 points | `Config.sensor_noise` |
| Tank sizes | Normal 100,000 L, One zone 50,000 L, Critical shortage 10,000 L, Empty 0 | ASSUMPTION | Sized for 100 m² cells | `TANK` |
| Starting moisture | Normal 70–100%, One zone 80–100% (North 18–36%), Critical shortage and Empty 15–45% | ASSUMPTION | | `MOISTURE`, `NORTH_DRY` |
| Refill / hand-watering | 5,000 L / 1,000 L | ASSUMPTION | Dashboard events | `refill_litres`, `manual_water_litres` |
| Heatwave / drought | +10 °C for 2 days / no rain and drying ×1.5 for 3 days | ASSUMPTION | Dashboard events | `heatwave_*`, `drought_*` |
| Decision cycle | 30 minutes | ASSUMPTION | | `Config.tick_minutes` |
| "Stressed" zone | more than a quarter of its cells (> 4 of 16) estimated below the trigger | ASSUMPTION (project design) | | `AgentConfig.stressed_share` |
| "Farm-wide" problem | 3 or more stressed zones (1–2 = local) | ASSUMPTION (project design) | | `AgentConfig.farm_wide_zones` |
| Urgency below critical | points below 30% count double | ASSUMPTION (project design) | | `AgentConfig.critical_stress_weight` |
| Utility weights | benefit 0.5, urgency 0.3, cost 0.2 | ASSUMPTION | The project deck | `AgentConfig` |
| Water price | ×1 at 100,000 L or more, rising to ×3 when empty | ASSUMPTION | A full Normal tank counts as plentiful | `comfortable_tank`, `scarcity_price` |
| Forecasting | 1 h ahead; 96-reading (2-day) window; trend from 48 readings; act from 4 readings unless critical; part of the gap = ½ | ASSUMPTION | | `AgentConfig` |
| Feed folding | an unchanged repeat within 6 cycles (3 h) folds into one entry | ASSUMPTION | | `MessageBus.fold_cycles` |

### Numbers still without a label or a precise source

- **Daily water use** (~5 mm/day) cites FAO-56 in general, not a table or an ET₀ × crop-coefficient calculation.
- **Temperature shape:** the daily cycle is a pure sine wave, an unlabelled modelling choice. The real Tucson cycle is lopsided (slow evening cooling), which the sine flattens by 0.3 °C at the cool end and 0.4 °C at the hot end.
- **Display only:** the Manager calls water "scarce" above 50% scarcity in its broadcast text. It doesn't affect any decision.
- **Farm layout and run settings:** 8 × 8 grid in four 4 × 4 zones, seed 42 (`engine.py`). These are structural rather than calibration numbers.
- **Display and memory limits (not model parameters):** 60 history points per cell, 500 decisions in the log, 20 events, 150 feed entries sent to the browser, 300 kept on the bus, a 1,000,000 L refill limit, a 4 KB request limit and port 8765.

### Known limitations

- **Available water is a stand-in.** 160 mm/m for loam comes from UMN Extension and is used in place of a value from FAO-56 Table 19, which still needs verifying for this soil. Total available water per cell, litres per point, and every litre amount in the project scale with it.
- **The heat effect comes from day-to-day data, not hourly.** USCRN's hourly soil moisture at Tucson was too noisy to show a usable hourly dry-down, so the heat effect comes from day-to-day losses on rain-free days. It's noisy (0.4–2.8%, depending on which days are used up to 3.2%), and it can't show how drying changes within a day.
- **The sensor noise is optimistic.** ±9.375 points assumes a soil-specific calibration that reaches the middle of METER's ±0.01–0.02 m³/m³ claim. METER's generic figure (±0.03 m³/m³ = ±18.75 points) is the worst case, and independent tests found errors near ±0.03 m³/m³ even after calibration. Noise is also modelled as uniform and independent per reading, with no fixed per-sensor bias.
- **Rain uses even ranges, not the real distribution.** Showers and their intensity are drawn evenly from ranges that keep the data's averages and annual total. Real Tucson rain is lumpier: most showers last an hour, and a few heavy storms bring much of the year's rain.
- **The USCRN station only measures soil moisture at 5 and 10 cm**, shallower than the 0.7 m root zone, and 2024 has nightly gaps from 1 January to 20 February.

### Model notes

Each cell dries at the base rate times its own drying scale. The scales sit around 1 (about 0.8–1.2), come in slow- and fast-drying patches made with the same smoothing as the starting moisture, and average exactly 1 across the farm, so the base rate is the farm-average rate. The agents' water cost is a share of the cell's available water, not litres, so their decisions don't change when the litres-per-point conversion does. None of this is an agronomic recommendation.

The farm map shows internal simulator state. Agents receive noisy sensor values (not clipped, so they can read past 0 or 100) and act on their smoothed estimate; the inspector shows the raw reading, the estimate and the forecast separately. History retains 60 points; the decision log and export retain the latest 500 per-cell decisions. Zone totals describe the latest cycle, while tank usage is cumulative.

This milestone uses explicit rules, not a trained prediction model or an LLM. It does not include temperature control, seeding, soil water movement between cells, negotiation between zones, joint assessment, persistence, or real hardware. Hardware adapters can later implement the sensor and actuator boundaries, with additional feedback and failure handling required before physical use.

