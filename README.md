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
1. Select **One zone needs water**. Advance one cycle. North requests water; the other zones receive none.
2. Select **Sufficient water**. Advance a cycle. All requests are approved.
3. Select **Critical shortage**. Advance a cycle. Critical cells receive proportional allocations; normal requests wait.
4. Select **Empty tank**. Advance a cycle, add 250 L, then advance again. Irrigation resumes.
5. Select any cell to inspect its history and latest decision. Filter the log by zone or priority and export it as JSON.
6. While it runs, trigger **Heatwave** (+10 °C for 2 days) or **Drought** (no rain and drier air for 3 days) from the Events bar. In the cell inspector, **Water cell** hand-waters the selected cell (+10 L, outside the shared tank).

Selecting a scenario resets the run immediately. Reset restarts the selected scenario with seed 42. Start runs cycles automatically; Next cycle pauses and advances exactly once. Speed controls wall-clock playback only; each cycle still represents 30 simulated minutes.

## How it works

`engine.py` contains Farm, four ZoneAgent instances, ManagerAgent, SimulatedSensor, and SimulatedIrrigation. Zones read noisy measurements and submit per-cell requests. The Manager collects all requests, allocates critical needs first, then normal needs. Inside each tier, shortages are shared in proportion to requested amounts (equivalent to moisture deficits because the conversion factor is common). Zones have no reserved water share. Only approved amounts reach the actuator.

`environment.py` holds the environment the agents live in: `EnvironmentConfig` (all weather and event numbers), `Weather` (daily temperature cycle, random rain, heatwave and drought), and `smooth_field` (starting moisture where neighbouring cells are similar). Each cycle, irrigation is applied first, then rain adds moisture and evaporation removes `base drying rate × drying factor`. The drying factor grows with temperature, drops while it rains, and rises during a drought. Weather uses its own random stream, so it never shifts the sensor noise.

`server.py` exposes the state and step/reset/refill/event actions on a local HTTP server. `web/` provides the custom browser interface. State lives in memory and is shared between browser tabs. Restarting the server resets it. The simulation advances only while the browser runs it or the user requests a step.

## Parameters and limitations

Configuration is in the Config dataclass: target 55%, request below 40%, critical below 25%, 0.5 L per moisture point, noise ±0.6 points, and 30-minute ticks. Cells dry by a seeded 0.6–1.4 points per cycle. Weather and event values live in `EnvironmentConfig`: 12–28 °C daily cycle peaking at 14:00, ±5% drying per °C, showers about once a day (1–3 hours, 1–3 points per cycle), 3 smoothing passes for the starting field. All of these are provisional placeholders, to be replaced by values fitted from real data. They are not calibrated soil volumetric-water measurements or agronomic recommendations.

The farm map shows internal simulator state. Agents receive noisy sensor values before the action; the inspector labels those separately. History retains 60 points; the decision log and export retain the latest 500 per-cell decisions. Zone totals describe the latest cycle, while tank usage is cumulative.

This milestone uses explicit rules, not a trained prediction model or an LLM. It does not include temperature control, seeding, soil water movement between cells, negotiation, joint assessment, persistence, or real hardware. Hardware adapters can later implement the sensor and actuator boundaries, with additional feedback and failure handling required before physical use.

