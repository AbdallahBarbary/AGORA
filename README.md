# AGORA

A local Python prototype of agent-led irrigation on an 8 × 8 simulated tomato farm. Four zone agents forecast their cells' soil moisture and recommend irrigation; a Manager agent decides how the shared tank is spent; they talk through a message bus you can watch on the dashboard. The weather is fitted to NOAA data from Tucson, Arizona, and the water amounts follow FAO-56. The dashboard follows the AGORA design mock-up (warm dark panels, the field seen from above, a shared tank at the centre).

## Run

Requires Python 3.10 or later. The dashboard runs with the Python standard library. Install the optional PDF report dependency once if you want PDF export:

```powershell
cd path\to\AGORA
python -m pip install -r requirements.txt
python server.py
```

Open http://127.0.0.1:8765 in your browser. Keep the terminal running. Stop it with Ctrl+C.

Run checks with `python -m unittest -v` from this directory. Re-derive the FITTED numbers from the downloaded data with `python calibrate.py`. The data files are git-ignored; `data/README.md` says where to download them. Without them the app and tests still run, and only the calibration check is skipped.

## Moisture scale

Moisture is **percent of available water**: 0 = wilting point, 100 = field capacity. A cell is healthy at 60% or more, needs water below 60% (40% of its available water used up, the FAO-56 tomato depletion fraction), and is critical below 30%. Irrigation refills to 100%. One point is 1% of a cell's available water, which is 112 L.

## The dashboard

**Farm** (the main view), top to bottom:

- **Controls.** Play/Pause, Step one cycle, Skip one day and a Speed switch, with the simulated clock, air temperature and Reset. Below: the scenario, then the four events (Heatwave, Drought, Top up tank, Pump failure), each with a one-line explanation, and the events still running.
- **The field.** The 64 plots in their four zones, seen from above. Colour is soil moisture: brown below the critical line (30%), straw below the irrigation line (60%), green above; the numbers are each plot's real moisture. Blue pipes run from the shared tank at the centre (its dial shows how full it is; the pipes turn grey when it's empty). A blue badge marks plots watered this cycle; each zone shows its average, how many plots need water, a *Stressed* tag and *Receiving water* when it applies.
- **What the Manager is doing.** The farm assessment (normal, local or farm-wide), what was asked for and what was approved, reduced or rejected and why, and a *Water is short* box when the tank can't cover everything.
- **Water tank.** Litres left against the tank's capacity (30,000 L), how many days of average use that covers, the supply coming in (or that the pump has failed), and what has been used, supplied, topped up and overflowed. An empty tank shows a button to top it up.
- **Selected plot.** Click a plot: its real moisture, sensor reading, the agent's estimate and forecast, its recent history, and in plain sentences what its zone agent asked for and what the Manager decided. You can water it by hand from here.
- **Moisture over time.** Each zone's average over the last 7 days, with the 60% and 30% lines, heatwaves and droughts as shaded bands and water added as markers. Hover (or focus it and use the arrow keys) to read every zone at one moment.

**Details** has the agents' message feed (filterable; unchanged repeats are folded) and the decision table, with search, priority and zone filters and a CSV export.

Thresholds, sizes, names and amounts on screen come from the server's settings. The page loads its two typefaces (Instrument Sans, IBM Plex Mono) from Google Fonts and falls back to system fonts offline.

## Demonstration

**Water supply.** The farm gets a steady inflow into its tank of **31,000 L a day**, its daily water quota: about what it uses on an average day (64 plots × 0.09% of available water per cycle × 48 cycles × 112 L = 30,966 L). The tank holds **30,000 L**, about a day's quota, as a buffer for bursts of refills; inflow beyond that overflows. On a normal day supply and use balance. A heatwave raises use by about a fifth, above the quota, and a hot, dry spell by much more.

**Scenarios** (dropdown; selecting one resets the run with seed 42). Every scenario starts with a few plots just under the 60% line, so the agents act within the first second at normal speed.

| Name | Supply | Tank at start | Starting moisture | What happens over 10 days |
|---|---|---|---|---|
| Healthy farm | 31,000 L/day | full (30,000 L) | 55–100% | Supply matches need. 0–10 plots a day ask for water and every request is approved; the tank swings between about 2,600 L and full. No plot ever goes critical. |
| One zone dries out | 46,500 L/day (1.5×) | full | North 18–36%, the rest 55–100% | A local problem: North's 16 parched plots ask for far more than the tank holds, so for about a day the Manager serves North's critical plots first and shares the inflow between them (all 17 critical requests served; 14 other requests wait). North recovers by day 2; after that every request is approved. |
| Heatwave week | 31,000 L/day | full | 55–100% | Hot and dry from day 2 to day 5 (+10 °C and no rain), so the soil loses about 55,700 L a day against 31,000 L of supply. The tank drains, and on days 5–6 the Manager cuts back 10 requests. The heat breaks after day 5 and by days 7–9 every request is approved again. No plot goes critical. |
| Water shortage | 15,500 L/day (half) | a quarter | 50–90% | The Manager rations every day: requests are cut back in proportion (up to 30 reductions a day by day 10) while the average moisture slides from about 71% to about 61% and the zones become stressed. No plot goes critical and nothing collapses within 10 days. |

**Events** (in the controls, any time): **Heatwave** (+10 °C for 2 days), **Drought** (no rain, drying ×1.5 for 3 days), **Pump failure** (no supply into the tank for 1 day) and **Top up tank** (adds 5,000 L, up to the tank's capacity). In the selected-plot panel, **Water by hand** adds 1,000 L to one plot without using the tank.

**Guided demo.** Press **Start guided demo** (top right). It walks through four steps, each with a caption explaining what to notice. The numbers in the captions are read from the run as it happens:

1. **A healthy farm.** The supply matches the farm's use. A few plots start just under the line, their agents ask within minutes and the Manager approves every request, while the tank dips and refills.
2. **One zone dries out.** North starts parched: a local problem. The Manager serves North's critical plots first and shares the water between them while the other zones wait their turn; two figures compare what North asked for with what it got.
3. **A heatwave causes a shortage.** The Heatwave week scenario runs until the Manager first has to cut back requests (day 5), showing the day's evaporation next to the supply.
4. **Recovery.** The run continues to two days after the heat breaks: demand falls back to about the supply, the tank recovers and requests are approved again.

**Playback.** Each cycle is 30 simulated minutes, whatever the speed:

| Speed | Wall-clock |
|---|---|
| Slow | 1 cycle a second (a day in 48 s) |
| Normal | 4 cycles a second (a day in 12 s) |
| Fast | a day in 4 s |

**Step one cycle** advances exactly one cycle and **Skip one day** advances 48; both pause playback. Speed only changes how fast you see it: results are the same at every speed and repeat exactly with the seed.

Click any plot to read, in plain sentences, what its zone agent asked for and what the Manager decided. **Details** shows the message feed and the decision table; filter it by zone or priority and export it as CSV.

## How it works

`engine.py` contains Farm, SimulatedSensor, and SimulatedIrrigation, and runs each cycle. `agents.py` contains the four ZoneAgent instances and the ManagerAgent. They talk only through `messaging.py`'s MessageBus:

1. The Manager broadcasts the tank level and a water price that rises from ×1 (plentiful) to ×3 (empty tank).
2. Each zone agent records its cells' noisy readings (±9.4 points) and keeps two days of them per cell. The forecaster lives behind the `Forecaster` interface in `forecast.py`; the current `TrendForecaster` is rule-based: it fits a straight line through the readings, net of the water the Manager approved, which averages the noise away. It gives a smoothed estimate of the moisture now and a forecast about an hour ahead. With less than a day of readings (48) it uses their average and no trend; with fewer than 4 an agent recommends nothing unless the cell is already critical.
3. For each cell it scores three options (wait, part of the gap, full gap) with the project deck's utility `0.5 × benefit + 0.3 × urgency − 0.2 × cost`, each term scaled 0–1. Benefit is the share of the cell's available water restored, counted only below the 60% line (above it the crop isn't stressed). Urgency is the stress avoided: how far below 60% the cell would be, counted double below 30%. Cost is the share of available water used, times the Manager's price. It sends the Manager a recommendation with its reason for every cell that shouldn't wait, plus one zone status. A zone is stressed when more than 4 of its 16 cells are estimated below 60%.
4. The Manager is the only agent that decides. It allocates critical recommendations first, then normal ones, sharing proportionally when short and never exceeding the tank. It marks each recommendation approved, adjusted or rejected, with a reason, and replies to each zone. Only approved water reaches the actuator.

The **Details** view shows the message feed and, in the decision table, each zone's recommendation next to the Manager's decision. Every message is delivered every cycle, but the feed folds an unchanged repeat (the same rejection, the same recommendation, the same tank broadcast within 3 hours) into one entry with its cycle range and a repeat count, so an empty tank doesn't flood it.

`environment.py` holds the environment the agents live in: `EnvironmentConfig` (all weather and event numbers), `Weather` (daily temperature cycle, random rain, heatwave and drought), and `smooth_field` (starting moisture where neighbouring cells are similar), and `drying_scales` (per-cell drying multipliers in similar patches). Each cycle, irrigation is applied first, then rain adds moisture and evaporation removes `base drying rate × cell drying scale × weather drying factor`. The drying factor grows with temperature, drops while it rains, and rises during a drought. Weather uses its own random stream, so it never shifts the sensor noise.

`server.py` exposes the state and step/reset/refill/event actions on a local HTTP server; a step can advance up to 480 cycles at once (that's how fast playback and **Skip one day** work). `web/` provides the custom browser interface. State lives in memory and is shared between browser tabs. Restarting the server resets it. The simulation advances only while the browser runs it or the user requests a step.

`calibrate.py` re-derives the FITTED weather numbers from the NOAA data in `data/uscrn/` and compares them with the code. `test_engine.py` holds the unit tests. `data/` holds the downloaded calibration data (git-ignored, apart from its README).

## PDF run report

Open **Details** and choose **Download report (PDF)** to create a concise, two-page report from the current in-memory simulation run. It uses AGORA's charcoal, green, soil-amber, and water-blue palette. Page one highlights run metrics, moisture and allocation charts, the Manager assessment, and follow-up recommendations. Page two keeps only the key model settings, limitations, recent events, and clickable source references. It intentionally omits an executive summary, milestone summary, and system architecture/how-it-works section. The report labels results as simulated and does not claim ML performance; the full settings catalogue remains in this README.

The report timestamp uses `Africa/Cairo` by default and also includes UTC. Set `AGORA_REPORT_TIMEZONE` to an IANA timezone (for example `America/Phoenix`) before starting the server to use another local display timezone. The simulation run itself is not saved; restarting the server or resetting the scenario starts a new run. Keep a copy of each exported PDF if you need a permanent record.

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
| Water supply | 31,000 L a day, steady, into the tank | ASSUMPTION (the farm's daily water quota) | About the farm's average daily water use: 64 plots × 0.09% × 48 cycles × 112 L = 30,966 L | `Config.supply_litres_per_day` |
| Tank capacity | 30,000 L | ASSUMPTION | About one day's quota, a buffer for bursts of refills; inflow beyond it overflows | `Config.tank_capacity_litres` |
| Scenarios | supply ×1 / ×1.5 / ×1 / ×0.5; tank full / full / full / a quarter; moisture 55–100% (One zone: North 18–36%; Water shortage 50–90%); Heatwave week: heatwave and drought on days 2–5 | ASSUMPTION (scenario settings) | | `engine.SCENARIO` |
| Top-up / hand-watering | 5,000 L into the tank (up to capacity) / 1,000 L onto one plot | ASSUMPTION | Dashboard events | `refill_litres`, `manual_water_litres` |
| Heatwave / drought / pump failure | +10 °C for 2 days / no rain and drying ×1.5 for 3 days / no supply for 1 day | ASSUMPTION | Dashboard events | `heatwave_*`, `drought_*`, `pump_failure_ticks` |
| Decision cycle | 30 minutes | ASSUMPTION | | `Config.tick_minutes` |
| "Stressed" zone | more than a quarter of its cells (> 4 of 16) estimated below the trigger | ASSUMPTION (project design) | | `AgentConfig.stressed_share` |
| "Farm-wide" problem | 3 or more stressed zones (1–2 = local) | ASSUMPTION (project design) | | `AgentConfig.farm_wide_zones` |
| Urgency below critical | points below 30% count double | ASSUMPTION (project design) | | `AgentConfig.critical_stress_weight` |
| Utility weights | benefit 0.5, urgency 0.3, cost 0.2 | ASSUMPTION | The project deck | `AgentConfig` |
| Water price | ×1 when the tank is full (30,000 L), rising to ×3 when empty | ASSUMPTION | A full tank counts as plentiful | `comfortable_tank`, `scarcity_price` |
| Forecasting | 1 h ahead; 96-reading (2-day) window; trend from 48 readings; act from 4 readings unless critical; part of the gap = ½ | ASSUMPTION | | `AgentConfig` |
| Feed folding | an unchanged repeat within 6 cycles (3 h) folds into one entry | ASSUMPTION | | `MessageBus.fold_cycles` |
| Guided demo | Healthy farm 12 h; One zone dries out 6 h; Heatwave week until the first cut-back; then 2 days after the heat breaks | ASSUMPTION (demo setting) | | `web/app.js` `DEMO` |

### Numbers still without a label or a precise source

- **Daily water use** (~5 mm/day) cites FAO-56 in general, not a table or an ET₀ × crop-coefficient calculation.
- **Temperature shape:** the daily cycle is a pure sine wave, an unlabelled modelling choice. The real Tucson cycle is lopsided (slow evening cooling), which the sine flattens by 0.3 °C at the cool end and 0.4 °C at the hot end.
- **Display only:** the Manager calls water "scarce" above 50% scarcity in its broadcast text. It doesn't affect any decision.
- **Farm layout and run settings:** 8 × 8 grid in four 4 × 4 zones, seed 42 (`engine.py`). These are structural rather than calibration numbers.
- **Display and memory limits (not model parameters):** 60 history points per cell, 500 decisions in the log, 20 events, 150 feed entries sent to the browser, 300 kept on the bus, a 1,000,000 L refill limit, a 4 KB request limit and port 8765.

### Known limitations

- **Available water is a stand-in.** 160 mm/m for loam comes from UMN Extension and is used in place of a value from FAO-56 Table 19, which still needs verifying for this soil. Total available water per cell, litres per point, and every litre amount in the project scale with it.
- **The heat effect comes from day-to-day data, not hourly.** USCRN's hourly soil moisture at Tucson was too noisy to show a usable hourly dry-down, so the heat effect comes from day-to-day losses on rain-free days. It's noisy: the main estimate is 1.6% with a 90% range of 0.4–2.8%, and other choices of days give up to 3.2%. It also can't show how drying changes within a day.
- **The sensor noise is optimistic.** ±9.375 points assumes a soil-specific calibration that reaches the middle of METER's ±0.01–0.02 m³/m³ claim. METER's generic figure (±0.03 m³/m³ = ±18.75 points) is the worst case, and independent tests found errors near ±0.03 m³/m³ even after calibration. Noise is also modelled as uniform and independent per reading, with no fixed per-sensor bias.
- **Rain uses even ranges, not the real distribution.** Showers and their intensity are drawn evenly from ranges that keep the data's averages and annual total. Real Tucson rain is lumpier: most showers last an hour, and a few heavy storms bring much of the year's rain.
- **The water supply is a modelling choice.** A steady 31,000 L a day into a 30,000 L tank stands in for a real allocation: it doesn't vary by season, time of day or a water authority's schedule, and the tank has no losses.
- **The USCRN station only measures soil moisture at 5 and 10 cm**, shallower than the 0.7 m root zone, and 2024 has nightly gaps from 1 January to 20 February.

### Model notes

Each cell dries at the base rate times its own drying scale. The scales sit around 1 (about 0.8–1.2), come in slow- and fast-drying patches made with the same smoothing as the starting moisture, and average exactly 1 across the farm, so the base rate is the farm-average rate. The agents' water cost is a share of the cell's available water, not litres, so their decisions don't change when the litres-per-point conversion does. None of this is an agronomic recommendation.

The farm map shows internal simulator state. Agents receive noisy sensor values (not clipped, so they can read past 0 or 100) and act on their smoothed estimate; the selected-plot panel shows the real moisture, the raw reading, the estimate and the forecast separately. History retains 60 points; the decision log and export retain the latest 500 per-cell decisions. Zone totals describe the latest cycle, while tank usage is cumulative.

The agents use explicit rules, not a trained prediction model or an LLM; the forecaster sits behind an interface so a trained model can replace it later. It does not include temperature control, seeding, soil water movement between cells, negotiation between zones, joint assessment, persistence, or real hardware. Hardware adapters can later implement the sensor and actuator boundaries, with additional feedback and failure handling required before physical use.

