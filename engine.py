"""Deterministic demonstration model; parameters are not agronomic calibration."""
from dataclasses import dataclass, asdict
import random

ZONES = ('North', 'East', 'West', 'South')
SCENARIOS = ('balanced', 'one-zone', 'shortage', 'empty')

@dataclass(frozen=True)
class Config:
    target: float = 55
    trigger: float = 40
    critical: float = 25
    litres_per_point: float = .5
    sensor_noise: float = .6
    tick_minutes: int = 30

class SimulatedSensor:
    def read(self, cells, rng, config):
        return {c['id']: max(0, min(100, c['moisture'] + rng.uniform(-config.sensor_noise, config.sensor_noise))) for c in cells}

class ZoneAgent:
    def __init__(self, name): self.name = name
    def request(self, cells, readings, config):
        return [dict(cell=c['id'], zone=self.name, reading=readings[c['id']],
                     amount=(config.target-readings[c['id']])*config.litres_per_point,
                     priority='critical' if readings[c['id']] < config.critical else 'normal')
                for c in cells if c['zone']==self.name and readings[c['id']] < config.trigger]
    def report(self, cells, readings, config):
        """Requests plus a stressed flag: more than a quarter of the zone's cells are below the trigger."""
        requests=self.request(cells, readings, config)
        size=sum(c['zone']==self.name for c in cells)
        return dict(zone=self.name, requests=requests, dry=len(requests), stressed=len(requests) > size/4)

class ManagerAgent:
    def assess(self, reports):
        """3-4 stressed zones: farm-wide; 1-2: local; 0: normal."""
        stressed=[r['zone'] for r in reports if r['stressed']]
        if len(stressed) >= 3:
            level='farm-wide'
            message='Farm-wide: all 4 zones stressed.' if len(stressed)==4 else f'Farm-wide: 3 of 4 zones stressed ({", ".join(stressed)}).'
        elif stressed:
            level='local'; message=f'Local problem: {", ".join(stressed)}.'
        else:
            level='normal'; message='Normal: no zones stressed.'
        return dict(level=level, stressed=stressed, message=message)

    def allocate(self, requests, tank):
        allocations = {r['cell']: 0.0 for r in requests}
        remaining = tank
        for priority in ('critical', 'normal'):
            group = [r for r in requests if r['priority']==priority]
            total = sum(r['amount'] for r in group)
            ratio = min(1, remaining/total) if total else 0
            for r in group: allocations[r['cell']] = r['amount']*ratio
            remaining = max(0, remaining-total*ratio)
        return allocations

class SimulatedIrrigation:
    def apply(self, cells, allocations, config):
        for cell in cells:
            cell['moisture'] = min(100, cell['moisture']+allocations.get(cell['id'],0)/config.litres_per_point)
        return sum(allocations.values())

class Farm:
    def __init__(self, scenario='balanced', seed=42, config=None):
        if scenario not in SCENARIOS: raise ValueError('Unknown scenario')
        self.config=config or Config(); self.rng=random.Random(seed)
        self.scenario=scenario; self.tick=0; self.used=0; self.logs=[]; self.last=[]; self.assessment=None
        self.tank={'balanced':1000,'one-zone':400,'shortage':100,'empty':0}[scenario]
        self.initial_water=self.tank; self.added=0
        self.sensor=SimulatedSensor(); self.actuator=SimulatedIrrigation()
        self.agents=[ZoneAgent(z) for z in ZONES]; self.manager=ManagerAgent()
        self.cells=[]; counts={z:0 for z in ZONES}
        for row in range(8):
            for col in range(8):
                zone=ZONES[(row//4)*2+col//4]; counts[zone]+=1
                low,high=(30,65)
                if scenario=='one-zone': low,high=(15,28) if zone=='North' else (60,75)
                if scenario in ('shortage','empty'): low,high=(12,32)
                moisture=self.rng.uniform(low,high)
                self.cells.append(dict(id=f'{zone[0]}-{counts[zone]:02}',zone=zone,row=row,col=col,moisture=moisture,drying=self.rng.uniform(.6,1.4),history=[moisture]))
        self.readings=self.sensor.read(self.cells,self.rng,self.config)

    def step(self):
        self.readings=self.sensor.read(self.cells,self.rng,self.config)
        reports=[agent.report(self.cells,self.readings,self.config) for agent in self.agents]
        requests=[r for report in reports for r in report['requests']]
        self.assessment=self.manager.assess(reports)
        allocations=self.manager.allocate(requests,self.tank)
        used=self.actuator.apply(self.cells,allocations,self.config)
        self.tank=max(0,self.tank-used); self.used+=used; self.tick+=1
        self.last=[]
        for r in requests:
            amount=allocations[r['cell']]
            status='approved' if abs(amount-r['amount'])<1e-8 else ('partial' if amount else 'waiting')
            reason=('Request fully covered' if status=='approved' else 'Limited water; critical needs first' if status=='partial' else 'No water available for this priority')
            self.last.append(dict(**r,allocated=amount,status=status,reason=reason,tick=self.tick))
        for c in self.cells:
            c['moisture']=max(0,c['moisture']-c['drying'])
            c['history'].append(c['moisture']); c['history']=c['history'][-60:]
        self.logs=(self.last+self.logs)[:500]
        return self.state()

    def refill(self, amount=250):
        if not 0 < amount <= 10000: raise ValueError('Refill must be between 0 and 10,000 L')
        self.tank+=amount; self.added+=amount

    def state(self):
        return dict(tick=self.tick,scenario=self.scenario,tank=self.tank,used=self.used,added=self.added,
            config=asdict(self.config),cells=[dict(c,reading=self.readings[c['id']]) for c in self.cells],
            requests=self.last,logs=self.logs,assessment=self.assessment,zones=[dict(name=z,
                stressed=bool(self.assessment) and z in self.assessment['stressed'],
                critical=sum(c['moisture']<self.config.critical for c in self.cells if c['zone']==z),
                requested=sum(r['amount'] for r in self.last if r['zone']==z),
                allocated=sum(r['allocated'] for r in self.last if r['zone']==z)) for z in ZONES])
