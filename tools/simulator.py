#!/usr/bin/env python3
"""Offline development server. Synthetic telemetry, never controls real hardware."""
import argparse
import json
import math
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
LIFE = 36000.0

class Controller:
    def __init__(self, clock=time.monotonic, state_path=None):
        self.clock = clock
        self.boot = self.last = clock()
        self.state_path = state_path
        used = [0, 0]
        if state_path and state_path.exists():
            saved = json.loads(state_path.read_text())
            used = saved['used']
            if len(used) != 2 or any(not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in used):
                raise ValueError('Invalid persisted usage; refusing to reset service budget')
        self.motors = [dict(id=i+1, state='STOP', speed=150, relay=False, usedSeconds=float(used[i]), remainingSeconds=max(0, LIFE-used[i]), risk=0) for i in range(2)]
        self.scenario = 'normal'
        self.locked = False
        self.reason = ''
        self.events = []
        self.event_count = 0
        self.status = 'STARTING'
        self.critical_samples = 0
        self.last_sample = self.last
        self.sample_steps = 0
        self.log('Simulator boot; synthetic telemetry; outputs OFF')
        self.tick()

    def log(self, text):
        self.event_count += 1
        self.events.insert(0, dict(at=int(self.clock()-self.boot), text=text))
        self.events = self.events[:32]

    def persist(self):
        if self.state_path:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_path.with_suffix('.tmp')
            tmp.write_text(json.dumps({'used': [m['usedSeconds'] for m in self.motors]}))
            tmp.replace(self.state_path)

    def trip(self, reason):
        first = not self.locked
        if first:
            self.locked = True
            self.reason = reason
            self.log('CRITICAL: ' + reason)
        for m in self.motors:
            m['state'] = 'STOP'
            m['relay'] = False
        if first:
            self.persist()

    def tick(self):
        now = self.clock()
        delta = max(0, now-self.last)
        self.last = now
        for m in self.motors:
            if m['state'] != 'STOP' and m['speed'] > 0:
                m['usedSeconds'] += delta
            m['remainingSeconds'] = max(0, LIFE-m['usedSeconds'])
        values = {
            'normal': (28.4, 29.1, .035, 2.1, True),
            'warm': (33.6, 31.1, .04, 3, True),
            'hot': (36.7, 37.2, .05, 4, True),
            'motion': (29, 29.4, .38, 45, True),
            'shock': (29, 29.4, .90, 110, True),
            'disconnect': (None, 29, 0, 0, False),
        }
        self.t1, self.t2, self.vib, self.rot, self.ready = values[self.scenario]
        steps = int((now-self.last_sample)/.1 + 1e-9)
        if steps:
            self.last_sample += steps*.1
            self.critical_samples = min(2, self.critical_samples+steps) if self.vib > .70 or self.rot > 90 else 0
        if (self.t1 is not None and self.t1 > 35) or self.t2 > 35:
            self.trip('Temperature above 35 C')
        elif self.critical_samples >= 2:
            self.trip('Excessive movement / vibration')
        elif not self.ready and any(m['state'] != 'STOP' and m['speed'] > 0 or m['relay'] for m in self.motors):
            self.trip('Sensor missing or stale')
        elif any(m['usedSeconds'] >= LIFE and m['state'] != 'STOP' and m['speed'] > 0 for m in self.motors):
            self.trip('Motor service budget exhausted')
        old = self.status
        self.status = 'CRITICAL' if self.locked else 'WARNING' if not self.ready or self.t1 > 32 or self.t2 > 32 or self.vib > .25 or self.rot > 30 else 'NORMAL'
        self.warning = self.reason if self.locked else 'Sensor missing / waiting for fresh readings' if not self.ready else 'Temperature above 32 C' if self.t1 > 32 or self.t2 > 32 else 'Sudden movement / vibration detected' if self.vib > .25 or self.rot > 30 else 'System operating normally'
        if old != self.status:
            self.log(self.status + ': ' + self.warning)
        for m in self.motors:
            t = self.t1 if m['id'] == 1 else self.t2
            m['risk'] = round(max(min(100, max(0, (t-25)/10*100)), min(100, max(self.vib/.70, self.rot/90)*100), min(100, m['usedSeconds']/LIFE*100)), 2) if self.ready else -1

    def set_scenario(self, scenario):
        if scenario not in {'normal','warm','hot','motion','shock','disconnect'}:
            return 400, 'Unknown scenario'
        self.tick()
        self.scenario = scenario
        self.critical_samples = 0
        self.last_sample = self.clock()
        self.log('Simulator scenario: ' + scenario)
        self.tick()
        return 200, 'OK'

    def command(self, command, value=None):
        self.tick()
        c = command.upper()
        if c == 'ALLSTOP':
            self.trip('Operator emergency stop')
        elif c == 'RESET':
            if not self.ready or self.t1 > 32 or self.t2 > 32 or self.vib > .25 or self.rot > 30:
                return 409, 'Reset blocked: fresh sensors below warning thresholds required'
            self.locked = False
            self.reason = ''
            self.critical_samples = 0
            for m in self.motors:
                m['state'] = 'STOP'
                m['relay'] = False
            self.log('Safety reset; outputs remain OFF')
        else:
            valid = {f'{prefix}{n}{suffix}' for n in (1,2) for prefix,suffix in [('M','F'),('M','R'),('M','S'),('R','ON'),('R','OFF')]} | {'SPEED1','SPEED2'}
            if c not in valid:
                return 400, 'Unknown command'
            off = c in {'M1S','M2S','R1OFF','R2OFF'}
            if not off and (self.locked or not self.ready):
                return 423, 'Outputs inhibited: resolve fault and reset'
            m = self.motors[1 if '2' in c else 0]
            if c.startswith('SPEED'):
                if value is None or not 1 <= len(value) <= 3 or not value.isascii() or not value.isdigit() or int(value) > 255:
                    return 400, 'Speed must be an integer from 0 to 255'
                if m['remainingSeconds'] <= 0:
                    return 409, 'Service budget exhausted'
                m['speed'] = int(value)
            elif c.startswith('R'):
                m['relay'] = c.endswith('ON')
            elif c.endswith('S'):
                m['state'] = 'STOP'
            else:
                if m['remainingSeconds'] <= 0:
                    return 409, 'Service budget exhausted'
                direction = 'FORWARD' if c.endswith('F') else 'REVERSE'
                if m['state'] != 'STOP' and m['state'] != direction:
                    return 409, 'Stop the motor before reversing'
                m['state'] = direction
        self.log('Command: ' + c)
        self.tick()
        self.persist()
        return 200, 'OK'

    def snapshot(self):
        self.tick()
        return dict(mode='simulator', uptime=int(self.clock()-self.boot), status=self.status, warning=self.warning, critical=self.locked, ready=self.ready, storageOK=True, t1=self.t1, t2=self.t2, t1OK=self.t1 is not None, t2OK=True, mpuOK=self.ready, vib=self.vib, rot=self.rot, mt=31.5, motors=self.motors, events=self.events, eventCount=self.event_count)


def serve(port=8080, host='127.0.0.1', state_path=None):
    controller = Controller(state_path=state_path)
    class Handler(BaseHTTPRequestHandler):
        def send(self, status, body, kind='text/plain; charset=utf-8'):
            raw = body.encode()
            self.send_response(status)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(raw)
        def do_GET(self):
            path = urlsplit(self.path).path
            if path == '/':
                self.send(200, (ROOT/'web/index.html').read_text(), 'text/html; charset=utf-8')
            elif path == '/api':
                self.send(200, json.dumps(controller.snapshot(), allow_nan=False), 'application/json')
            else:
                self.send(404, 'Not found')
        def do_POST(self):
            if self.headers.get("X-MotorGuard") != "1":
                return self.send(403, "Missing command header")
            try:
                size = int(self.headers.get('Content-Length','0'))
            except ValueError:
                return self.send(400, 'Invalid content length')
            if size > 1024 or size < 0:
                return self.send(413, 'Request too large')
            form = parse_qs(self.rfile.read(size).decode(), keep_blank_values=True)
            arg = lambda name: form.get(name,[''])[0]
            if self.path == '/cmd':
                status, body = controller.command(arg('c'), arg('v'))
            elif self.path == '/scenario':
                status, body = controller.set_scenario(arg('scenario'))
            else:
                status, body = 404, 'Not found'
            self.send(status, body)
    httpd = HTTPServer((host,port), Handler)
    httpd.timeout = .1
    print(f'MotorGuard SIMULATOR on {host}:{port}; synthetic data only', flush=True)
    last_saved = time.monotonic()
    try:
        while True:
            httpd.handle_request()
            controller.tick()
            if time.monotonic() - last_saved >= 30:
                controller.persist()
                last_saved = time.monotonic()
    except KeyboardInterrupt:
        controller.tick()
        controller.persist()
    finally:
        httpd.server_close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--host', default='127.0.0.1')
    args = parser.parse_args()
    serve(args.port, args.host, ROOT/'.local/simulator-state.json')
