import unittest
from dataclasses import replace
from environment import EnvironmentConfig, Weather, drying_scales
import random
from collections import Counter
from engine import Farm, MOISTURE, SCENARIOS, TANK, Config
from agents import AgentConfig
from agents import ManagerAgent, ZoneAgent, MANAGER
from forecast import TrendForecaster
from messaging import MessageBus

class EngineTests(unittest.TestCase):
    def test_grid_and_repeatability(self):
        a,b=Farm(),Farm()
        for _ in range(10): a.step(); b.step()
        self.assertEqual(a.state(),b.state())
        self.assertEqual(len(a.cells),64)
        self.assertEqual(len({c['id'] for c in a.cells}),64)
        for z in a.agents: self.assertEqual(sum(c['zone']==z.name for c in a.cells),16)
    def test_one_zone(self):
        f=Farm('one-zone'); f.step()
        self.assertEqual({r['zone'] for r in f.last},{'North'})                  # only the dry zone asks
        self.assertTrue(all(r['priority']=='critical' for r in f.last))         # cycle 1: only critical cells act
        self.assertAlmostEqual(f.used,min(TANK['one-zone'],sum(r['amount'] for r in f.last)))   # never over the tank
    def test_shortage_priority_and_proportion(self):
        rs=[dict(cell='a',priority='critical',amount=30),dict(cell='b',priority='critical',amount=60),dict(cell='c',priority='normal',amount=20)]
        a=ManagerAgent().allocate(rs,45)
        self.assertEqual(a,{'a':15,'b':30,'c':0})
        self.assertEqual(ManagerAgent().allocate(rs,100),{'a':30,'b':60,'c':10})
    def test_empty_and_refill(self):
        f=Farm('empty'); f.step(); self.assertEqual(f.used,0)
        f.refill(); f.step(); self.assertGreater(f.used,0)
    def test_accounting_and_bounds_over_time(self):
        for scenario in SCENARIOS:
            f=Farm(scenario)
            for tick in range(100):
                if tick%10==0: f.refill()
                before=f.tank; old={c['id']:c['moisture'] for c in f.cells}; f.step()
                used=sum(r['allocated'] for r in f.last)
                self.assertLessEqual(used,before+1e-8)
                self.assertAlmostEqual(f.initial_water+f.added,f.tank+f.used)
                for r in f.last:
                    self.assertGreaterEqual(r['allocated'],0)
                    self.assertLessEqual(r['allocated'],r['amount']+1e-8)
                for c in f.cells:
                    allocation=next((r['allocated'] for r in f.last if r['cell']==c['id']),0)
                    w=f.conditions
                    expected=max(0,min(100,min(100,old[c['id']]+allocation/f.config.litres_per_point)+w['rain']-f.drying_rate(c)*w['drying_factor']))
                    self.assertAlmostEqual(c['moisture'],expected)
                    self.assertTrue(0<=c['moisture']<=100)
    def test_assessment_local_one_zone(self):
        f=Farm('one-zone'); self.assertIsNone(f.state()['assessment']); f.step()
        a=f.state()['assessment']
        self.assertEqual((a['level'],a['stressed']),('local',['North']))
        self.assertEqual(a['message'],'Local problem: North.')
        self.assertEqual([z['name'] for z in f.state()['zones'] if z['stressed']],['North'])
    def test_assessment_farm_wide_all_dry(self):
        for scenario in ('shortage','empty'):
            f=Farm(scenario); f.step()
            self.assertEqual(f.assessment['level'],'farm-wide')
            self.assertEqual(f.assessment['stressed'],['North','East','West','South'])
            self.assertEqual(f.assessment['message'],'Farm-wide: all 4 zones stressed.')
    def test_stressed_threshold(self):
        f=Farm(); north=[c for c in f.cells if c['zone']=='North']
        for dry in (4,5):
            readings={c['id']:(30 if i<dry else 60) for i,c in enumerate(north)}
            self.assertEqual(ZoneAgent('North').zone_status(north,readings,f.config)['stressed'],dry>4)
    def test_assessment_levels(self):
        m=ManagerAgent(); rep=lambda n:[dict(zone=z,stressed=i<n) for i,z in enumerate(('North','East','West','South'))]
        self.assertEqual([m.assess(rep(n))['level'] for n in range(5)],['normal','local','local','farm-wide','farm-wide'])
        self.assertEqual(m.assess(rep(0))['message'],'Normal: no zones stressed.')
        self.assertEqual(m.assess(rep(2))['message'],'Local problem: North, East.')
        self.assertEqual(m.assess(rep(3))['message'],'Farm-wide: 3 of 4 zones stressed (North, East, West).')
    def test_shortage_explanation(self):
        m=ManagerAgent()
        rs=[dict(cell='a',zone='North',priority='critical',amount=30),dict(cell='b',zone='East',priority='critical',amount=60),
            dict(cell='c',zone='West',priority='normal',amount=20),dict(cell='d',zone='South',priority='normal',amount=20)]
        explain=lambda tank:m.explain_shortage(rs,m.allocate(rs,tank),tank)
        x=explain(45)   # half of the critical needs, nothing for normal
        self.assertEqual((x['prioritised'],x['reduced'],x['delayed']),(['North','East'],[],['West','South']))
        self.assertAlmostEqual(x['critical_coverage'],.5)
        self.assertEqual(x['message'],'Water short: 130 L requested, 45 L available. Prioritised for critical cells: North, East. '
                         'Critical requests only 50% covered. Normal requests delayed: West, South.')
        x=explain(100)  # critical covered, 10 L shared by the normal requests
        self.assertEqual((x['reduced'],x['delayed'],x['critical_coverage']),(['West','South'],[],1.0))
        self.assertNotIn('Critical requests only',x['message'])
        self.assertIsNone(explain(130))  # exactly enough: no shortage
        self.assertIsNone(m.explain_shortage([],{},0))
    def test_shortage_in_farm_report(self):
        f=Farm('shortage'); f.step(); x=f.assessment['shortage']
        crit={r['zone'] for r in f.last if r['priority']=='critical'}
        waiting={r['zone'] for r in f.last if r['priority']=='normal' and r['status']=='rejected'}
        self.assertEqual(set(x['prioritised']),crit); self.assertEqual(set(x['delayed']),waiting)
        self.assertAlmostEqual(x['available'],TANK['shortage']); self.assertAlmostEqual(f.used,TANK['shortage'])  # whole tank, never more
        self.assertTrue(x['message'].startswith('Water short:'))
        f=Farm('normal'); f.step(); self.assertIsNone(f.state()['assessment']['shortage'])
    def test_shortage_reported_exactly_when_requests_cut(self):
        for scenario in SCENARIOS:
            f=Farm(scenario)
            for _ in range(60):
                f.step()
                self.assertEqual(f.assessment['shortage'] is not None,any(r['status']!='approved' for r in f.last))
    # --- Stage 3: forecasting zone agents, message bus, Manager review ---
    def test_trend_forecaster(self):
        tf=TrendForecaster(min_trend=3)
        self.assertAlmostEqual(tf.predict([50,49,48,47],[0,0,0],2),45)    # steady drying, 1 h ahead
        self.assertAlmostEqual(tf.predict([50,49,48,47],[0,0,0],0),47)    # horizon 0: estimate now
        self.assertAlmostEqual(tf.predict([40,55,54,53],[16,0,0],2),51)   # known irrigation is not mistaken for a trend
        self.assertAlmostEqual(TrendForecaster(min_trend=8).predict([30,34],[0],2),32)   # too few: average, no trend
        self.assertEqual(tf.predict([3,2,1],[0,0],5),0)                    # clamped
    def test_forecaster_smooths_sensor_noise(self):
        cfg=Config(); rng=random.Random(1); n=AgentConfig().forecast_window; tf=TrendForecaster()
        errors_fit,errors_raw=[],[]
        for trial in range(30):
            truth=[80-.09*i for i in range(n+2)]
            readings=[t+rng.uniform(-cfg.sensor_noise,cfg.sensor_noise) for t in truth[:n]]
            errors_fit.append(abs(tf.predict(readings,[0]*(n-1),2)-truth[n+1]))
            errors_raw.append(abs(readings[-1]-truth[n+1]))
        self.assertLess(max(errors_fit),6)                         # +-9.4 noise shrinks to a few points
        self.assertLess(sum(errors_fit)/30,sum(errors_raw)/30/3)   # far better than trusting the last reading
    def test_forecaster_is_pluggable(self):
        class Pessimist:
            def predict(self,readings,irrigation,horizon): return 10.0
        a=ZoneAgent('North',forecaster=Pessimist()).assess_cell('N-01',60,Config())
        self.assertEqual((a['forecast'],a['priority']),(10.0,'critical'))
        self.assertNotEqual(a['option'],'wait')
    def test_zone_agent_acts_on_forecast_not_threshold(self):
        cfg=Config(); quick=replace(AgentConfig(),min_trend_readings=3)
        falling=ZoneAgent('North',quick); steady=ZoneAgent('North',quick)
        for r in range(80,61,-2): a=falling.assess_cell('N-01',r,cfg)   # still above the 60% trigger, dropping fast
        self.assertGreater(a['level'],cfg.trigger); self.assertLess(a['forecast'],cfg.trigger)
        self.assertNotEqual(a['option'],'wait')
        for _ in range(10): b=steady.assess_cell('N-01',62,cfg)          # same level, stable
        self.assertEqual(b['option'],'wait'); self.assertIn('waiting scores best',b['rationale'])
        for _ in range(4): c=steady.assess_cell('N-02',100,cfg)
        self.assertEqual((c['option'],list(c['options'])),('wait',['wait']))
        self.assertIn('no water needed',c['rationale'])
    def test_agents_wait_for_enough_readings(self):
        cfg=Config(); z=ZoneAgent('North'); need=z.ac.min_readings
        for i in range(need-1):
            a=z.assess_cell('N-01',45,cfg)             # below the trigger, but too little evidence yet
            self.assertEqual(a['option'],'wait'); self.assertIn('readings so far',a['rationale'])
        self.assertNotEqual(z.assess_cell('N-01',45,cfg)['option'],'wait')
        self.assertNotEqual(ZoneAgent('North').assess_cell('N-02',10,cfg)['option'],'wait')   # critical: act at once
        f=Farm('normal')
        for _ in range(need-1): f.step(); self.assertEqual(f.last,[])
    def test_utility_balances_benefit_urgency_and_cost(self):
        cfg=Config(); z=ZoneAgent('North'); u=lambda f,points:z.utility(f,points*cfg.litres_per_point,cfg)
        ac=AgentConfig(); self.assertEqual((ac.benefit_weight,ac.urgency_weight,ac.cost_weight),(.5,.3,.2))   # the deck
        self.assertEqual(u(20,0),0)                       # waiting is the baseline
        self.assertGreater(u(20,40),u(50,40))             # the same water is worth more to a drier cell (urgency)
        self.assertGreater(u(50,50),u(50,10))             # refilling to field capacity beats a token top-up
        self.assertLess(u(65,35),0)                       # above the trigger the crop isn't stressed: not worth it
        self.assertAlmostEqual(u(40,60),.5*.6+.3*20/90-.2*.6)   # 0.5 benefit + 0.3 urgency - 0.2 cost
        before=u(20,40); z.price*=2; self.assertLess(u(20,40),before)   # dearer water lowers the score
        self.assertEqual((z.stress(60,cfg),z.stress(0,cfg)),(0,1))
    def test_scarcity_makes_agents_ask_for_less(self):
        cfg=Config(); chosen={}
        full=TANK['normal']
        for tank in (full,0):
            bus=MessageBus()
            for n in (MANAGER,'North'): bus.register(n)
            ManagerAgent().announce(bus,1,tank)
            a=ZoneAgent('North').act(bus,1,[dict(id='N-01',zone='North')],{'N-01':20},cfg)[0]
            chosen[tank]=(a['option'],a['amount'])
        self.assertEqual(chosen[full][0],'full'); self.assertEqual(chosen[0][0],'part')
        self.assertLess(chosen[0][1],chosen[full][1])
    def test_message_bus(self):
        bus=MessageBus(keep=3)
        for n in ('Manager','North','East'): bus.register(n)
        bus.send(1,'Manager','all','tank-status',{},'hello')
        bus.send(1,'North','Manager','recommendation',{'x':1},'rec')
        self.assertEqual([m['kind'] for m in bus.receive('North')],['tank-status'])
        self.assertEqual(bus.receive('North'),[])                                    # receiving clears the inbox
        self.assertEqual([m['text'] for m in bus.receive('Manager')],['rec'])         # sender skips its own broadcast
        self.assertEqual(len(bus.inboxes['East']),1)
        for i in range(3): bus.send(2,'Manager','East','decision',{},str(i))
        self.assertEqual([m['text'] for m in bus.feed],['2','1','0'])                # newest first, capped
        with self.assertRaises(ValueError): bus.send(1,'Manager','Nowhere','decision',{},'x')
    def test_feed_folds_repeated_messages(self):
        bus=MessageBus()
        for n in ('Manager','North'): bus.register(n)
        for cycle in (1,2,3): bus.send(cycle,'Manager','North','decision',{},f'N-01 rejected ({cycle})',topic='N-01',signature='rejected')
        self.assertEqual(len(bus.feed),1); e=bus.feed[0]
        self.assertEqual((e['first_cycle'],e['cycle'],e['repeats'],e['text']),(1,3,3,'N-01 rejected (3)'))
        self.assertEqual(len(bus.receive('North')),3)                     # still delivered every cycle
        bus.send(4,'Manager','North','decision',{},'N-01 approved',topic='N-01',signature='approved')
        bus.send(6,'Manager','North','decision',{},'N-01 approved',topic='N-01',signature='approved')   # short gap: folds
        bus.send(20,'Manager','North','decision',{},'N-01 approved',topic='N-01',signature='approved')  # long gap: new entry
        self.assertEqual(len(bus.feed),3); self.assertEqual(bus.feed[1]['repeats'],2)
        f=Farm('empty')
        for _ in range(30): f.step()
        per_cell=Counter(m['body']['cell'] for m in f.bus.feed if m['kind']=='decision')
        decisions=len(f.last)*30                                          # roughly what 30 unfolded cycles would show
        self.assertLessEqual(max(per_cell.values()),3)                    # a new entry only when a cell's run is broken
        self.assertLess(sum(per_cell.values()),decisions/10)              # instead of one per cell per cycle
        self.assertEqual(sum(m['kind']=='tank-status' for m in f.bus.feed),1)
        self.assertTrue(any(m['repeats']>=20 for m in f.state()['messages']))
    def test_manager_review_and_reasons(self):
        bus=MessageBus()
        for n in ('Manager','North','East'): bus.register(n)
        def rec(cell,zone,priority,amount): bus.send(1,zone,'Manager','recommendation',dict(cell=cell,zone=zone,priority=priority,amount=amount),'')
        rec('a','North','critical',30); rec('b','East','normal',20); rec('c','East','normal',20)
        for z,st in (('North',True),('East',False)): bus.send(1,z,'Manager','zone-status',dict(zone=z,stressed=st),'')
        out=ManagerAgent().review(bus,1,40)
        d={x['cell']:x for x in out['decisions']}
        self.assertEqual([d[c]['status'] for c in 'abc'],['approved','adjusted','adjusted'])
        self.assertEqual(out['allocations'],ManagerAgent().allocate(list(d.values()),40))   # same critical-first rule
        self.assertAlmostEqual(sum(out['allocations'].values()),40)                         # never over the tank
        self.assertIn('critical needs served first',d['b']['reason'])
        self.assertEqual(out['assessment']['level'],'local')
        self.assertEqual({m['body']['cell'] for m in bus.receive('East')},{'b','c'})         # replies go to each zone
        m=ManagerAgent()
        self.assertEqual(m.decide(dict(priority='normal',amount=5),0,30)['reason'],'Rejected: critical needs used all available water.')
        self.assertEqual(m.decide(dict(priority='critical',amount=5),0,0)['reason'],'Rejected: the tank is empty.')
    def test_cycle_message_flow(self):
        f=Farm('shortage'); sent=[]; send=f.bus.send
        f.bus.send=lambda *a,**k: sent.append(a) or send(*a,**k)
        for cycle in (1,2):
            f.step(); kinds=[a[3] for a in sent if a[0]==cycle]
            self.assertEqual(kinds.count('tank-status'),1); self.assertEqual(kinds.count('zone-status'),4)
            self.assertEqual(kinds.count('recommendation'),kinds.count('decision'))
            self.assertEqual(len(f.last),kinds.count('decision'))
            for d in f.last:   # each zone recommendation sits next to the Manager's decision
                for key in ('option','amount','rationale','forecast','allocated','status','reason'): self.assertIn(key,d)
        watered=[w for h in f.agents[0].memory.values() for _,w in h[1:]]   # North learned its approved water from replies
        self.assertTrue(any(w>0 for w in watered))
        s=f.state(); self.assertTrue(s['messages']); self.assertNotIn('body',s['messages'][0])
        self.assertTrue(all(c['plan'] for c in s['cells']))
    def test_temperature_cycle(self):
        w=Farm().weather; temps=[w.temperature(t) for t in range(48)]; peak=w.env.peak_hour
        self.assertEqual(temps.index(max(temps)),round(peak*2))           # 15:30, nearest cycle to 15:42
        self.assertEqual(temps.index(min(temps)),round((peak-12)%24*2))   # 03:30
        self.assertAlmostEqual(max(temps)-min(temps),2*w.env.temp_amplitude,delta=.1)
        self.assertAlmostEqual(sum(temps)/48,w.env.mean_temp)
        self.assertAlmostEqual(w.temperature(7),w.temperature(7+48))
    def test_hotter_dries_faster(self):
        w=Farm().weather
        self.assertGreater(w.drying_factor(w.temperature(28)),w.drying_factor(w.temperature(4)))
        self.assertEqual(w.drying_factor(-50),w.env.min_drying_factor)
        f=Farm('one-zone'); losses={}
        for t in range(29):
            old=f.cells[4]['moisture']; f.step(); losses[t]=old-f.cells[4]['moisture']  # E-01, never irrigated here
        self.assertGreater(losses[28],losses[4])
    def test_rain_adds_moisture(self):
        f=Farm('one-zone',env=replace(EnvironmentConfig(),rain_chance=1))
        cell=next(c for c in f.cells if c['zone']=='East' and c['moisture']<99); old=cell['moisture']; f.step()
        lo,hi=f.env.rain_points
        self.assertTrue(lo<=f.conditions['rain']<=hi)
        self.assertGreater(cell['moisture'],old)        # East cell: no irrigation, rain outweighs drying
        self.assertTrue(f.state()['weather']['raining'] or f.weather.rain_left==0)
    def test_rain_is_occasional(self):
        dry=Farm(env=replace(EnvironmentConfig(),rain_chance=0))
        for _ in range(48): dry.step(); self.assertEqual(dry.conditions['rain'],0)
        w=Weather(EnvironmentConfig(),30,42); rain=[w.advance(t)['rain'] for t in range(48*365)]
        wet=[r for r in rain if r]; lo,hi=w.env.rain_points
        self.assertTrue(.01<len(wet)/len(rain)<.03)   # about 1.8% of cycles expected
        self.assertTrue(all(lo<=r<=hi for r in wet))
    def test_start_moisture_is_smooth(self):
        for scenario in ('normal','shortage','empty'):
            f=Farm(scenario); low,high=MOISTURE[scenario]; m={(c['row'],c['col']):c['moisture'] for c in f.cells}
            self.assertTrue(all(low-1e-9<=v<=high+1e-9 for v in m.values()))
            diffs=[abs(m[r,c]-m[r+dr,c+dc]) for r,c in m for dr,dc in ((0,1),(1,0)) if (r+dr,c+dc) in m]
            self.assertLess(sum(diffs)/len(diffs),.15*(high-low))  # independent values would average about a third
    def test_drying_scales_are_patchy_around_one(self):
        env=EnvironmentConfig(); f=Farm(); s={(c['row'],c['col']):c['drying_scale'] for c in f.cells}
        self.assertAlmostEqual(sum(s.values())/64,1)                                   # base rate = farm average
        self.assertAlmostEqual(max(s.values())-min(s.values()),2*env.drying_spread)    # modest spread...
        self.assertTrue(all(abs(v-1)<2*env.drying_spread for v in s.values()))         # ...centred near 1
        diffs=[abs(s[r,c]-s[r+dr,c+dc]) for r,c in s for dr,dc in ((0,1),(1,0)) if (r+dr,c+dc) in s]
        self.assertLess(sum(diffs)/len(diffs),.15*2*env.drying_spread)                 # neighbours are similar
        self.assertEqual(drying_scales(random.Random(7),8,8,env),drying_scales(random.Random(7),8,8,env))  # seeded
        self.assertNotEqual([c['drying_scale'] for c in Farm(seed=1).cells],list(s.values()))
        flat=Farm(env=replace(env,drying_spread=0))
        self.assertTrue(all(abs(c['drying_scale']-1)<1e-12 for c in flat.cells))
    def test_base_drying_rate_scales_every_cell(self):
        def losses(base):
            f=Farm(env=replace(EnvironmentConfig(),base_drying_rate=base,rain_chance=0)); old=[c['moisture'] for c in f.cells]
            f.step(); self.assertEqual(f.last,[])   # healthy farm: no irrigation in cycle 1
            return [o-c['moisture'] for o,c in zip(old,f.cells)]
        one,two=losses(1.0),losses(2.0)
        for a,b in zip(one,two): self.assertAlmostEqual(b,2*a)
        f=Farm(); c=f.cells[0]; self.assertAlmostEqual(f.drying_rate(c),f.env.base_drying_rate*c['drying_scale'])
    def test_available_water_scale(self):
        cfg=Config()
        self.assertEqual((cfg.target,cfg.trigger,cfg.critical,cfg.litres_per_point),(100,60,30,112))
        self.assertEqual(MOISTURE['normal'],(70,100)); self.assertNotIn('balanced',SCENARIOS)
        self.assertAlmostEqual(cfg.sensor_noise,.015/.16*100)             # calibrated TEROS 10 accuracy over loam's AW
        f=Farm(); f.step()
        self.assertTrue(any(f.readings[c['id']]>100 for c in f.cells))    # readings aren't clipped
    def test_normal_scenario_is_healthy(self):
        f=Farm('normal'); f.step()
        self.assertEqual(f.last,[])
        self.assertEqual(f.assessment['level'],'normal')
    def test_heatwave(self):
        f=Farm(); base=f.weather.temperature(0); f.trigger('heatwave')
        self.assertAlmostEqual(f.weather.temperature(0),base+f.env.heatwave_extra_temp)
        f.step(); self.assertAlmostEqual(f.conditions['temperature'],base+f.env.heatwave_extra_temp)
        for _ in range(f.env.heatwave_ticks): f.step()
        self.assertAlmostEqual(f.weather.temperature(f.tick),Farm().weather.temperature(f.tick))  # over
    def test_drought(self):
        env=replace(EnvironmentConfig(),rain_chance=1); f=Farm(env=env); f.trigger('drought')
        for _ in range(env.drought_ticks):
            f.step(); self.assertEqual(f.conditions['rain'],0)
            self.assertAlmostEqual(f.conditions['drying_factor'],f.weather.drying_factor(f.conditions['temperature'])*env.drought_drying_factor)
        f.step(); self.assertGreater(f.conditions['rain'],0)  # rain allowed again
    def test_water_one_cell(self):
        f=Farm(); c=f.cells[0]; old,tank=c['moisture'],f.tank; f.trigger('water','N-01')
        self.assertAlmostEqual(c['moisture'],min(100,old+f.env.manual_water_litres/f.config.litres_per_point))
        self.assertEqual((f.tank,f.manual),(tank,f.env.manual_water_litres))
        self.assertTrue(all(o['moisture']==n['moisture'] for o,n in zip(Farm().cells[1:],f.cells[1:])))
    def test_bad_events(self):
        f=Farm()
        for kind,cell in (('flood',None),('water','Z-99'),('water',None)):
            with self.assertRaises(ValueError): f.trigger(kind,cell)
    def test_bad_scenario(self):
        with self.assertRaises(ValueError): Farm('unknown')

if __name__=='__main__': unittest.main()
