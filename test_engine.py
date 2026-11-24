import unittest
from engine import Farm, ManagerAgent

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
    def test_bad_scenario(self):
        with self.assertRaises(ValueError): Farm('unknown')

if __name__=='__main__': unittest.main()
