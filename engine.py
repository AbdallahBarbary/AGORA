"""Farm simulation. Moisture is "percent of available water": 0 = wilting point, 100 = field capacity.
Deterministic for a given seed. Not an agronomic recommendation."""
from dataclasses import dataclass, asdict
import random
from environment import EnvironmentConfig, Weather, smooth_field, drying_scales
from agents import AgentConfig, ZoneAgent, ManagerAgent, MANAGER
from messaging import MessageBus

ZONES = ('North', 'East', 'West', 'South')
EVENTS = ('heatwave', 'drought', 'water')
SCENARIOS = ('normal', 'one-zone', 'shortage', 'empty')
# Starting tank (L) per scenario: ASSUMPTIONS sized for 100 m2 cells.
TANK = {'normal': 100_000, 'one-zone': 50_000, 'shortage': 10_000, 'empty': 0}
# Starting moisture range (% of available water) per scenario: ASSUMPTIONS.
# 'one-zone': the other zones are well watered and North gets NORTH_DRY.
MOISTURE = {'normal': (70, 100), 'one-zone': (80, 100), 'shortage': (15, 45), 'empty': (15, 45)}
NORTH_DRY = (18, 36)

@dataclass(frozen=True)
class Config:
    # Moisture is % of available water (AW): 0 = wilting point, 100 = field capacity.
    target: float = 100             # ASSUMPTION: irrigation refills a cell to field capacity
    trigger: float = 60             # REFERENCE: FAO-56 Table 22, tomato depletion fraction p = 0.40
                                    # (water can stress the crop once 40% of AW is used up)
    critical: float = 30            # ASSUMPTION: well past the stress line; served first in shortages
    litres_per_point: float = 112   # REFERENCE: 100 m2 cell x 0.7 m tomato roots x 160 mm/m AW for loam
                                    # = 11,200 L of available water = 100 points, so 1 point = 1% of AW
    sensor_noise: float = 9.375     # ASSUMPTION: METER TEROS 10 accuracy with soil-specific calibration,
                                    # +-0.015 m3/m3 (midpoint of METER's +-0.01-0.02 range; source: METER
                                    # TEROS 10 tech specs, metergroup.com/products/teros-10/teros-10-tech-specs/)
                                    # / 0.16 m3/m3 AW of loam = +-9.375 points, uniform. Worst case: METER's
                                    # generic-calibration +-0.03 m3/m3 = +-18.75 points.
    tick_minutes: int = 30          # ASSUMPTION: decision cycle length

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
    def __init__(self, scenario='normal', seed=42, config=None, env=None, agent_config=None):
        if scenario not in SCENARIOS: raise ValueError('Unknown scenario')
        self.config=config or Config(); self.rng=random.Random(seed)
        self.env=env or EnvironmentConfig(); self.weather=Weather(self.env,self.config.tick_minutes,seed); self.conditions=None
        self.scenario=scenario; self.tick=0; self.used=0; self.logs=[]; self.last=[]; self.assessment=None
        self.tank=TANK[scenario]
        self.initial_water=self.tank; self.added=0; self.manual=0; self.events=[]
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
                low,high=NORTH_DRY if scenario=='one-zone' and zone=='North' else MOISTURE[scenario]
                moisture=low+field[row][col]*(high-low)
                self.cells.append(dict(id=f'{zone[0]}-{counts[zone]:02}',zone=zone,row=row,col=col,moisture=moisture,drying_scale=scales[row][col],history=[moisture]))
        self.readings=self.sensor.read(self.cells,self.rng,self.config)

    def step(self):
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
        for c in self.cells:  # weather acts after irrigation: rain adds, evaporation removes
            c['moisture']=max(0,min(100,c['moisture']+conditions['rain']-self.drying_rate(c)*conditions['drying_factor']))
            c['history'].append(c['moisture']); c['history']=c['history'][-60:]
        self.logs=(self.last+self.logs)[:500]; self.conditions=conditions
        return self.state()

    def drying_rate(self, cell):
        """Points a cell loses per cycle at mean temperature: farm base rate × the cell's scale.
        The weather's drying factor then adjusts this for heat, rain and drought."""
        return self.env.base_drying_rate*cell['drying_scale']

    def refill(self, amount=None):
        """Add water to the shared tank; defaults to the dashboard's refill size."""
        amount=self.env.refill_litres if amount is None else amount
        if not 0 < amount <= 1_000_000: raise ValueError('Refill must be between 0 and 1,000,000 L')
        self.tank+=amount; self.added+=amount

    def trigger(self, kind, cell=None):
        """Apply a dashboard event immediately. Cell events need a cell id."""
        if kind not in EVENTS: raise ValueError('Unknown event')
        e=self.env
        if kind=='heatwave':
            self.weather.start_heatwave(); text=f'Heatwave: +{e.heatwave_extra_temp:g} °C for {e.heatwave_ticks*self.config.tick_minutes/60:g} h'
        elif kind=='drought':
            self.weather.start_drought(); text=f'Drought: no rain for {e.drought_ticks*self.config.tick_minutes/60:g} h'
        else:
            c=next((c for c in self.cells if c['id']==cell),None)
            if c is None: raise ValueError('Unknown cell')
            c['moisture']=min(100,c['moisture']+e.manual_water_litres/self.config.litres_per_point)
            self.manual+=e.manual_water_litres; text=f'{cell} hand-watered (+{e.manual_water_litres:,.0f} L, outside the tank)'
        self.events=([dict(tick=self.tick,kind=kind,cell=cell,text=text)]+self.events)[:20]

    def state(self):
        return dict(tick=self.tick,scenario=self.scenario,tank=self.tank,used=self.used,added=self.added,manual=self.manual,events=self.events,
            config=asdict(self.config),agent_config=asdict(self.agent_config),
            cells=[dict(c,reading=self.readings[c['id']],plan=self.assessments.get(c['id'])) for c in self.cells],
            messages=[{k:m[k] for k in ('id','first_cycle','cycle','repeats','sender','recipient','kind','text')} for m in self.bus.feed[:150]],
            environment=asdict(self.env),weather=self.weather.now(self.tick),last_conditions=self.conditions,
            requests=self.last,logs=self.logs,assessment=self.assessment,zones=[dict(name=z,
                stressed=bool(self.assessment) and z in self.assessment['stressed'],
                critical=sum(c['moisture']<self.config.critical for c in self.cells if c['zone']==z),
                requested=sum(r['amount'] for r in self.last if r['zone']==z),
                allocated=sum(r['allocated'] for r in self.last if r['zone']==z)) for z in ZONES])
