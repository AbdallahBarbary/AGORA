import unittest
from engine import Farm, ManagerAgent, ZoneAgent

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
        for scenario in ('balanced','one-zone','shortage','empty'):
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
                    expected=max(0,min(100,old[c['id']]+allocation/f.config.litres_per_point)-c['drying'])
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
    def test_bad_scenario(self):
        with self.assertRaises(ValueError): Farm('unknown')

if __name__=='__main__': unittest.main()
