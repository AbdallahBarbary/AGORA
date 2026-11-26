"""Small SQLite archive for saved AGORA simulation runs."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3


class RunStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS saved_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                scenario TEXT NOT NULL,
                saved_at_utc TEXT NOT NULL,
                tick INTEGER NOT NULL,
                summary_json TEXT NOT NULL,
                state_json TEXT NOT NULL
            )''')

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _summary(state):
        cells = state.get('cells', [])
        config = state.get('config', {})
        average = sum(float(c.get('moisture', 0)) for c in cells) / max(1, len(cells))
        critical = sum(float(c.get('moisture', 100)) < float(config.get('critical', 0)) for c in cells)
        latest = state.get('requests', [])
        decisions = {key: sum(r.get('status') == key for r in latest)
                     for key in ('approved', 'adjusted', 'rejected')}
        zone_avgs = {}
        for zone in state.get('zone_names', []):
            group = [c for c in cells if c.get('zone') == zone]
            zone_avgs[zone] = sum(float(c.get('moisture', 0)) for c in group) / max(1, len(group))
        tick_minutes = int(config.get('tick_minutes', 30))
        return {
            'scenario_name': state.get('scenarios', {}).get(state.get('scenario'), state.get('scenario', 'Unknown')),
            'simulated_hours': int(state.get('tick', 0)) * tick_minutes / 60,
            'average_moisture': average,
            'critical_plots': critical,
            'plot_count': len(cells),
            'tank': float(state.get('tank', 0)),
            'capacity': float(state.get('capacity', 0)),
            'used': float(state.get('used', 0)),
            'supplied': float(state.get('supplied', 0)),
            'evaporated': float(state.get('evaporated', 0)),
            'spilled': float(state.get('spilled', 0)),
            'latest_decisions': decisions,
            'zone_averages': zone_avgs,
        }

    def save(self, state, name=None):
        scenario = state.get('scenario', 'run')
        scenario_name = state.get('scenarios', {}).get(scenario, scenario)
        saved_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
        label = str(name or '').strip()
        if len(label) > 80:
            raise ValueError('Run name must be 80 characters or fewer')
        if not label:
            day = 1 + (int(state.get('tick', 0)) * int(state.get('config', {}).get('tick_minutes', 30))) // 1440
            label = f'{scenario_name} - Day {day} - {saved_at[:16].replace("T", " ")} UTC'
        summary = self._summary(state)
        with self._connect() as db:
            cur = db.execute('''INSERT INTO saved_runs
                (name, scenario, saved_at_utc, tick, summary_json, state_json)
                VALUES (?, ?, ?, ?, ?, ?)''',
                (label, scenario, saved_at, int(state.get('tick', 0)),
                 json.dumps(summary, separators=(',', ':')),
                 json.dumps(state, separators=(',', ':'))))
            run_id = cur.lastrowid
        return self.get(run_id)

    def list_runs(self, limit=100):
        with self._connect() as db:
            rows = db.execute('''SELECT id, name, scenario, saved_at_utc, tick, summary_json
                                 FROM saved_runs ORDER BY id DESC LIMIT ?''', (limit,)).fetchall()
        return [dict(id=row['id'], name=row['name'], scenario=row['scenario'],
                     saved_at_utc=row['saved_at_utc'], tick=row['tick'],
                     summary=json.loads(row['summary_json'])) for row in rows]

    def get(self, run_id):
        with self._connect() as db:
            row = db.execute('''SELECT id, name, scenario, saved_at_utc, tick, summary_json
                                FROM saved_runs WHERE id=?''', (run_id,)).fetchone()
        if row is None:
            return None
        return dict(id=row['id'], name=row['name'], scenario=row['scenario'],
                    saved_at_utc=row['saved_at_utc'], tick=row['tick'],
                    summary=json.loads(row['summary_json']))

    def get_state(self, run_id):
        with self._connect() as db:
            row = db.execute('SELECT state_json FROM saved_runs WHERE id=?', (run_id,)).fetchone()
        return json.loads(row['state_json']) if row else None
