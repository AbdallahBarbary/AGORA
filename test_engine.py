import unittest
from dataclasses import replace
from environment import EnvironmentConfig
from engine import Farm, ManagerAgent, ZoneAgent, MOISTURE, SCENARIOS

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
        self.assertEqual({r['zone'] for r in f.last},{'North'})
        self.assertTrue(all(r['status']=='approved' for r in f.last))
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
                    expected=max(0,min(100,min(100,old[c['id']]+allocation/f.config.litres_per_point)+w['rain']-c['drying']*w['drying_factor']))
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
            self.assertEqual(ZoneAgent('North').report(north,readings,f.config)['stressed'],dry>4)
    def test_assessment_levels(self):
        m=ManagerAgent(); rep=lambda n:[dict(zone=z,stressed=i<n) for i,z in enumerate(('North','East','West','South'))]
        self.assertEqual([m.assess(rep(n))['level'] for n in range(5)],['normal','local','local','farm-wide','farm-wide'])
        self.assertEqual(m.assess(rep(0))['message'],'Normal: no zones stressed.')
        self.assertEqual(m.assess(rep(2))['message'],'Local problem: North, East.')
        self.assertEqual(m.assess(rep(3))['message'],'Farm-wide: 3 of 4 zones stressed (North, East, West).')
    def test_temperature_cycle(self):
        w=Farm().weather; temps=[w.temperature(t) for t in range(48)]
        self.assertEqual(temps.index(max(temps)),28)  # 14:00
        self.assertEqual(temps.index(min(temps)),4)   # 02:00
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
        f=Farm('one-zone',env=replace(EnvironmentConfig(),rain_chance=1)); old=f.cells[4]['moisture']; f.step()
        lo,hi=f.env.rain_points
        self.assertTrue(lo<=f.conditions['rain']<=hi)
        self.assertGreater(f.cells[4]['moisture'],old)  # E-01: no irrigation, rain outweighs drying
        self.assertTrue(f.state()['weather']['raining'] or f.weather.rain_left==0)
    def test_rain_is_occasional(self):
        dry=Farm(env=replace(EnvironmentConfig(),rain_chance=0))
        for _ in range(48): dry.step(); self.assertEqual(dry.conditions['rain'],0)
        f=Farm(); rainy=0
        for _ in range(480): f.step(); rainy+=f.conditions['rain']>0
        self.assertTrue(0<rainy<480*.3)  # some showers over 10 days, but mostly dry
    def test_start_moisture_is_smooth(self):
        for scenario in ('normal','balanced','shortage'):
            f=Farm(scenario); low,high=MOISTURE[scenario]; m={(c['row'],c['col']):c['moisture'] for c in f.cells}
            self.assertTrue(all(low-1e-9<=v<=high+1e-9 for v in m.values()))
            diffs=[abs(m[r,c]-m[r+dr,c+dc]) for r,c in m for dr,dc in ((0,1),(1,0)) if (r+dr,c+dc) in m]
            self.assertLess(sum(diffs)/len(diffs),.15*(high-low))  # independent values would average about a third
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
