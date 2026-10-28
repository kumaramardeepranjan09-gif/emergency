import tempfile
import unittest
from pathlib import Path
from tools.simulator import Controller, LIFE

class Clock:
    def __init__(self): self.now=0.0
    def __call__(self): return self.now
    def advance(self, seconds): self.now+=seconds

class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock()
        self.c=Controller(self.clock)
    def command(self, c, v=None): return self.c.command(c,v)[0]
    def test_boot_outputs_off(self):
        self.assertTrue(self.c.snapshot()['ready'])
        self.assertTrue(all(m['state']=='STOP' and not m['relay'] for m in self.c.motors))
    def test_warning_does_not_stop_motor(self):
        self.command('M1F'); self.c.set_scenario('warm')
        self.assertEqual(self.c.status,'WARNING')
        self.assertEqual(self.c.motors[0]['state'],'FORWARD')
    def test_overheat_latches_all_outputs(self):
        self.command('M1F');self.command('M2R');self.command('R1ON');self.command('R2ON')
        self.c.set_scenario('hot')
        self.assertTrue(self.c.locked)
        self.assertTrue(all(m['state']=='STOP' and not m['relay'] for m in self.c.motors))
        self.assertEqual(self.command('M1F'),423)
        self.assertEqual(self.command('RESET'),409)
        self.c.set_scenario('normal');self.assertTrue(self.c.locked)
        self.assertEqual(self.command('RESET'),200)
        self.assertEqual(self.c.motors[0]['state'],'STOP')
    def test_motion_warning_and_two_sample_trip(self):
        self.command('M1F');self.c.set_scenario('motion')
        self.assertEqual(self.c.status,'WARNING');self.assertFalse(self.c.locked)
        self.c.set_scenario('shock');self.assertFalse(self.c.locked)
        self.clock.advance(.1);self.c.tick();self.assertFalse(self.c.locked)
        self.clock.advance(.1);self.c.tick();self.assertTrue(self.c.locked)
    def test_sensor_fault_stop_and_reset_rejection(self):
        self.command('M2F');self.c.set_scenario('disconnect')
        self.assertTrue(self.c.locked);self.assertEqual(self.command('RESET'),409)
        self.assertEqual(self.command('R1ON'),423)
        self.assertEqual(self.command('R1OFF'),200)
    def test_sensor_fault_inhibits_idle_start(self):
        self.c.set_scenario('disconnect');self.assertEqual(self.command('M1F'),423)
        self.assertEqual(self.c.snapshot()['motors'][0]['risk'],-1)
    def test_independent_runtime_and_zero_pwm(self):
        self.command('M1F');self.clock.advance(10);self.c.tick()
        self.assertEqual(self.c.motors[0]['usedSeconds'],10)
        self.assertEqual(self.c.motors[1]['usedSeconds'],0)
        self.command('SPEED1','0');self.clock.advance(10);self.c.tick()
        self.assertEqual(self.c.motors[0]['usedSeconds'],10)
        self.command('SPEED1','100');self.command('M2R');self.clock.advance(5);self.c.tick()
        self.assertEqual(self.c.motors[0]['usedSeconds'],15)
        self.assertEqual(self.c.motors[1]['usedSeconds'],5)
    def test_exhausted_life_stops_and_blocks(self):
        self.c.motors[0]['usedSeconds']=LIFE-1
        self.command('M1F');self.clock.advance(2);self.c.tick()
        self.assertTrue(self.c.locked);self.assertEqual(self.c.motors[0]['remainingSeconds'],0)
        self.command('RESET');self.assertEqual(self.command('M1F'),409)
    def test_emergency_stop_latches_relays_too(self):
        self.command('R2ON');self.command('M1F');self.command('ALLSTOP')
        self.assertTrue(self.c.locked);self.assertFalse(self.c.motors[1]['relay'])
    def test_reversal_requires_stop(self):
        self.command('M1F');self.assertEqual(self.command('M1R'),409)
        self.command('M1S');self.assertEqual(self.command('M1R'),200)
    def test_malformed_speed_never_changes_output(self):
        for value in ('','abc','-1','256','1.5','12x','9999','１２'):
            self.assertEqual(self.command('SPEED1',value),400)
            self.assertEqual(self.c.motors[0]['speed'],150)
        self.assertEqual(self.command('BOGUS'),400)
    def test_reboot_preserves_usage_but_outputs_off(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'state.json'
            self.c.state_path=path
            self.command('M1F');self.clock.advance(60);self.command('M1S')
            new=Controller(self.clock,path)
            self.assertEqual(new.motors[0]['usedSeconds'],60)
            self.assertEqual(new.motors[0]['state'],'STOP')
    def test_event_log_bounded(self):
        for _ in range(50):self.command('M1S')
        self.assertEqual(len(self.c.events),32)
        self.assertGreater(self.c.event_count,50)
    def test_corrupt_usage_refuses_silent_reset(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'state.json';path.write_text('{"used":[-1,0]}')
            with self.assertRaises(ValueError):Controller(self.clock,path)

if __name__=='__main__': unittest.main()
