"""Farm simulation. Moisture is "percent of available water": 0 = wilting point, 100 = field capacity.
Deterministic for a given seed. Not an agronomic recommendation."""
from dataclasses import dataclass, asdict
import random
from environment import EnvironmentConfig, Weather, smooth_field, drying_scales
from agents import AgentConfig, ZoneAgent, ManagerAgent, MANAGER
from messaging import MessageBus

ZONES = ('North', 'East', 'West', 'South')
EVENTS = ('heatwave', 'drought', 'pump', 'water')
# Scenarios: ASSUMPTIONS (scenario settings). `supply` scales the daily water quota, `tank` is the
# starting fill as a share of capacity, `moisture` the starting range (% of available water) and
# `events` the scheduled (cycle, event, length in cycles). Every
# range starts just under the 60% line (55%; 50% in Water shortage), so a few plots need water in the first cycles.
SCENARIO = {
    'healthy':  dict(name='Healthy farm', supply=1.0, tank=1.0, moisture=(55, 100)),
    'one-zone': dict(name='One zone dries out', supply=1.5, tank=1.0, moisture=(55, 100), north=(18, 36)),
    'heatwave': dict(name='Heatwave week', supply=1.0, tank=1.0, moisture=(55, 100),
                     events=((48, 'heatwave', 192), (48, 'drought', 192))),  # hot and dry, days 2-5
    'shortage': dict(name='Water shortage', supply=.5, tank=.25, moisture=(50, 90)),   # half the quota, a drier start
}
SCENARIOS = tuple(SCENARIO)
SCENARIO_NAMES = {k: v['name'] for k, v in SCENARIO.items()}
MOISTURE = {k: v['moisture'] for k, v in SCENARIO.items()}
MAX_ADVANCE = 480   # most cycles one request may advance (10 days)
ZONE_HISTORY = 337  # zone-average points kept for the dashboard chart (7 days + the start)
EVENT_LOG = 100     # dashboard events kept (heatwaves, droughts, refills, hand-watering)

@dataclass(frozen=True)
class Config:
    # Moisture is % of available water (AW): 0 = wilting point, 100 = field capacity.
    target: float = 100             # ASSUMPTION: irrigation refills a cell to field capacity
    trigger: float = 60             # REFERENCE: FAO-56 Table 22, tomato depletion fraction p = 0.40
                                    # (water can stress the crop once 40% of AW is used up)
    critical: float = 30            # ASSUMPTION: well past the stress line; served first in shortages
    # Water held by one cell (1 mm of water over 1 m2 = 1 L):
    cell_area_m2: float = 100       # ASSUMPTION: each of the 64 cells is 10 m x 10 m
    root_depth_m: float = .7        # REFERENCE: FAO-56 Table 22, tomato root depth (0.7-1.5 m; shallow end)
    available_water_mm_per_m: float = 160   # REFERENCE: UMN Extension, available water of loam. A stand-in
                                            # for FAO-56 Table 19 that still needs verifying
    litres_per_point: float = 112   # REFERENCE (derived): 100 m2 x 0.7 m x 160 mm/m = 11,200 L of
                                    # available water = 100 points, so 1 point = 1% of AW (checked by a test)
    sensor_noise: float = 9.375     # ASSUMPTION: METER TEROS 10 accuracy with soil-specific calibration,
                                    # +-0.015 m3/m3 (midpoint of METER's +-0.01-0.02 range; source: METER
                                    # TEROS 10 tech specs, metergroup.com/products/teros-10/teros-10-tech-specs/)
                                    # / 0.16 m3/m3 AW of loam = +-9.375 points, uniform. Worst case: METER's
                                    # generic-calibration +-0.03 m3/m3 = +-18.75 points.
    tick_minutes: int = 30          # ASSUMPTION: decision cycle length
    # Water supply: ASSUMPTION (the farm's daily water quota). A steady inflow into the tank about equal
    # to the farm's average daily water use: 64 plots x 0.09% of AW per cycle x 48 cycles x 112 L = 30,966 L.
    # A heatwave (+10 C, about 20% faster drying) raises use to about 37,000 L a day, above the quota.
    supply_litres_per_day: float = 31_000
    tank_capacity_litres: float = 30_000    # ASSUMPTION: about one day's quota, a buffer for bursts of refills

class SimulatedSensor:
    def read(self, cells, rng, config):
        """One noisy reading per cell. Not clipped to 0-100: real sensors can read past the
        wilting point or field capacity, and clipping would bias the agents' averages."""
        return {c['id']: c['moisture'] + rng.uniform(-config.sensor_noise, config.sensor_noise) for c in cells}

class SimulatedIrrigation:
    def apply(self, cells, allocations, config):
        for cell in cells:
            cell['moisture'] = min(100, cell['moisture']+allocations.get(cell['id'],0)/config.litres_per_point)
        return sum(allocations.values())

class Farm:
    def __init__(self, scenario='healthy', seed=42, config=None, env=None, agent_config=None):
        if scenario not in SCENARIOS: raise ValueError('Unknown scenario')
        self.config=config or Config(); self.rng=random.Random(seed)
        self.env=env or EnvironmentConfig(); self.weather=Weather(self.env,self.config.tick_minutes,seed); self.conditions=None
        self.scenario=scenario; self.plan=SCENARIO[scenario]; self.tick=0; self.used=0; self.logs=[]; self.last=[]; self.assessment=None
        self.capacity=self.config.tank_capacity_litres
        self.supply_per_cycle=self.config.supply_litres_per_day*self.plan['supply']*self.config.tick_minutes/(24*60)
        self.tank=self.capacity*self.plan['tank']
        self.initial_water=self.tank; self.added=0; self.manual=0; self.events=[]
        self.supplied=0.0; self.spilled=0.0; self.pump_off_left=0   # litres in from the supply, litres that overflowed
        self.evaporated=0.0; self.rain_kept=0.0   # litres, whole farm, since the start (soil water balance)
        self.zone_history=[]   # [tick, average moisture per zone in ZONES order], for the dashboard chart
        self.sensor=SimulatedSensor(); self.actuator=SimulatedIrrigation()
        self.agent_config=agent_config or AgentConfig()
        self.agents=[ZoneAgent(z,self.agent_config) for z in ZONES]; self.manager=ManagerAgent(self.agent_config)
        self.bus=MessageBus(); self.assessments={}
        for name in (MANAGER,*ZONES): self.bus.register(name)
        self.cells=[]; counts={z:0 for z in ZONES}
        field=smooth_field(self.rng,8,8,self.env.smoothing_passes)  # neighbours start with similar moisture
        scales=drying_scales(self.rng,8,8,self.env)                # ...and dry at similar speeds
        for row in range(8):
            for col in range(8):
                zone=ZONES[(row//4)*2+col//4]; counts[zone]+=1
                low,high=self.plan['north'] if 'north' in self.plan and zone=='North' else self.plan['moisture']
                moisture=low+field[row][col]*(high-low)
                self.cells.append(dict(id=f'{zone[0]}-{counts[zone]:02}',zone=zone,row=row,col=col,moisture=moisture,drying_scale=scales[row][col],history=[moisture]))
        self.readings=self.sensor.read(self.cells,self.rng,self.config)
        self.record_zones()

    def step(self):
        for at,kind,ticks in self.plan.get('events',()):    # the scenario's scheduled events
            if self.tick==at: self.trigger(kind,ticks=ticks)
        self.inflow()                               # the supply arrives before the Manager plans
        conditions=self.weather.advance(self.tick)  # weather for the coming 30 minutes
        self.readings=self.sensor.read(self.cells,self.rng,self.config)
        cycle=self.tick+1
        # Agents talk only through the bus: Manager broadcasts the tank, zones recommend, Manager decides and replies.
        self.manager.announce(self.bus,cycle,self.tank)
        self.assessments={a['cell']:a for agent in self.agents for a in agent.act(self.bus,cycle,self.cells,self.readings,self.config)}
        review=self.manager.review(self.bus,cycle,self.tank)
        self.assessment=review['assessment']   # farm report: problem scope plus shortage reasoning
        used=self.actuator.apply(self.cells,review['allocations'],self.config)   # only approved water is applied
        self.tank=max(0,self.tank-used); self.used+=used; self.tick=cycle
        self.last=[dict(d,tick=cycle) for d in review['decisions']]
        lpp=self.config.litres_per_point
        for c in self.cells:  # weather acts after irrigation: rain adds, evaporation removes
            old=c['moisture']; dry=self.drying_rate(c)*conditions['drying_factor']
            c['moisture']=max(0,min(100,old+conditions['rain']-dry))
            evaporated=dry-max(0,dry-old-conditions['rain'])        # can't evaporate water the cell doesn't have
            self.evaporated+=evaporated*lpp
            self.rain_kept+=(c['moisture']-old+evaporated)*lpp      # rain that stayed; any excess drains away
            c['history'].append(c['moisture']); c['history']=c['history'][-60:]
        self.logs=(self.last+self.logs)[:500]; self.conditions=conditions; self.record_zones()
        return self.state()

    def drying_rate(self, cell):
        """Points a cell loses per cycle at mean temperature: farm base rate × the cell's scale.
        The weather's drying factor then adjusts this for heat, rain and drought."""
        return self.env.base_drying_rate*cell['drying_scale']

    def inflow(self):
        """One cycle of the steady supply into the tank, unless the pump has failed. Water beyond
        the tank's capacity overflows and is lost."""
        if self.pump_off_left: self.pump_off_left-=1; return
        room=self.capacity-self.tank; got=min(room,self.supply_per_cycle)
        self.tank+=got; self.supplied+=got; self.spilled+=self.supply_per_cycle-got

    def refill(self, amount=None):
        """Top up the shared tank by hand, up to its capacity; defaults to the dashboard's size."""
        amount=self.env.refill_litres if amount is None else amount
        if not 0 < amount <= 1_000_000: raise ValueError('Refill must be between 0 and 1,000,000 L')
        got=min(amount,self.capacity-self.tank)
        self.tank+=got; self.added+=got
        self.log_event('refill',f'Topped up the tank by {got:,.0f} L' + ('' if got==amount else f' (it was nearly full; {amount-got:,.0f} L did not fit)'))

    def record_zones(self):
        """Append each zone's average true moisture at the current tick (for the zone chart)."""
        avg=lambda z:sum(c['moisture'] for c in self.cells if c['zone']==z)/sum(c['zone']==z for c in self.cells)
        self.zone_history=(self.zone_history+[[self.tick]+[avg(z) for z in ZONES]])[-ZONE_HISTORY:]

    def log_event(self, kind, text, cell=None, until=None):
        """Record a dashboard event; `until` is the tick a timed event (heatwave, drought) ends."""
        self.events=([dict(tick=self.tick,kind=kind,cell=cell,text=text,until=until)]+self.events)[:EVENT_LOG]

    def trigger(self, kind, cell=None, ticks=None):
        """Apply a dashboard event immediately. Cell events need a cell id; `ticks` overrides a
        heatwave's or drought's length (used by scheduled scenario events)."""
        if kind not in EVENTS: raise ValueError('Unknown event')
        e=self.env
        until=None
        if kind=='heatwave':
            n=e.heatwave_ticks if ticks is None else ticks
            self.weather.start_heatwave(n); until=self.tick+n
            text=f'Heatwave: +{e.heatwave_extra_temp:g} °C for {n*self.config.tick_minutes/60:g} h'
        elif kind=='pump':
            self.pump_off_left=e.pump_failure_ticks; until=self.tick+e.pump_failure_ticks
            text=f'Pump failure: no supply into the tank for {e.pump_failure_ticks*self.config.tick_minutes/60:g} h'
        elif kind=='drought':
            n=e.drought_ticks if ticks is None else ticks
            self.weather.start_drought(n); until=self.tick+n
            text=f'Drought: no rain for {n*self.config.tick_minutes/60:g} h'
        else:
            c=next((c for c in self.cells if c['id']==cell),None)
            if c is None: raise ValueError('Unknown cell')
            c['moisture']=min(100,c['moisture']+e.manual_water_litres/self.config.litres_per_point)
            self.manual+=e.manual_water_litres; text=f'{cell} hand-watered (+{e.manual_water_litres:,.0f} L, outside the tank)'
        self.log_event(kind,text,cell,until)

    def advance(self, cycles=1):
        """Run several cycles in a row (for fast playback and 'skip a day'); same result as
        calling step() that many times."""
        if isinstance(cycles,bool) or not isinstance(cycles,int) or not 1<=cycles<=MAX_ADVANCE:
            raise ValueError(f'Cycles must be a whole number from 1 to {MAX_ADVANCE}')
        for _ in range(cycles): self.step()
        return self.state()

    def state(self):
        return dict(tick=self.tick,scenario=self.scenario,scenarios=SCENARIO_NAMES,tank=self.tank,used=self.used,added=self.added,manual=self.manual,events=self.events,
            capacity=self.capacity,supply_per_day=self.supply_per_cycle*(24*60)/self.config.tick_minutes,supplied=self.supplied,spilled=self.spilled,pump_off_left=self.pump_off_left,
            evaporated=self.evaporated,rain_kept=self.rain_kept,zone_names=ZONES,zone_history=self.zone_history,
            config=asdict(self.config),agent_config=asdict(self.agent_config),
            cells=[dict(c,reading=self.readings[c['id']],plan=self.assessments.get(c['id'])) for c in self.cells],
            messages=[{k:m[k] for k in ('id','first_cycle','cycle','repeats','sender','recipient','kind','text')} for m in self.bus.feed[:150]],
            environment=asdict(self.env),weather=self.weather.now(self.tick),last_conditions=self.conditions,
            requests=self.last,logs=self.logs,assessment=self.assessment,zones=[dict(name=z,
                stressed=bool(self.assessment) and z in self.assessment['stressed'],
                critical=sum(c['moisture']<self.config.critical for c in self.cells if c['zone']==z),
                requested=sum(r['amount'] for r in self.last if r['zone']==z),
                allocated=sum(r['allocated'] for r in self.last if r['zone']==z)) for z in ZONES])
