"""The agents. Zone agents forecast and recommend; the Manager is the only one that decides.
They communicate only through the message bus.

Moisture is % of available water (0 = wilting point, 100 = field capacity). Every number in
AgentConfig is labelled REFERENCE or ASSUMPTION. Water cost is measured as a share of the
cell's available water, so decisions don't depend on how many litres a point is.
"""
from dataclasses import dataclass
from forecast import TrendForecaster

MANAGER = 'Manager'
OPTIONS = {'wait': 'Wait', 'part': 'Part of the gap', 'full': 'Full gap'}


@dataclass(frozen=True)
class AgentConfig:
    # --- Forecasting: ASSUMPTIONS ---
    forecast_minutes: int = 60      # how far ahead zone agents look
    forecast_window: int = 96       # readings per cell kept for the trend (2 days); long enough that
                                    # +-9.4 points of sensor noise doesn't dominate a 0.09/cycle trend
    min_trend_readings: int = 48    # 1 day; a slope from fewer readings is mostly noise (from 8 readings
                                    # it is off by ~1.7 points/cycle vs ~0.09 real drying), so use their average
    min_readings: int = 4           # readings before a zone recommends anything, unless already critical
    # --- Zone utility: weights from the project deck (ASSUMPTION); each term is scaled 0..1 ---
    benefit_weight: float = .5      # share of the cell's available water restored (only below the trigger)
    urgency_weight: float = .3      # stress avoided: how far below the trigger, counted double below critical
    cost_weight: float = .2         # share of the cell's available water used, times the scarcity price
    scarcity_price: float = 2.0     # ASSUMPTION: water's price rises from 1x (plentiful) to 3x (empty tank)
    part_fraction: float = .5       # ASSUMPTION: share of the gap in the "part of the gap" option
    # --- Manager's scarcity signal ---
    comfortable_tank: float = 100_000  # ASSUMPTION: litres; a full Normal tank counts as plentiful
    # --- Problem scope and urgency: ASSUMPTION (project design) ---
    stressed_share: float = .25     # a zone is stressed when MORE than this share of its cells (> 4 of 16)
                                    # is estimated below the trigger
    farm_wide_zones: int = 3        # this many stressed zones or more = farm-wide problem; 1-2 = local
    critical_stress_weight: float = 2   # in urgency, points below the critical level count double


class ZoneAgent:
    """Watches one zone: forecasts each cell, scores its options, recommends to the Manager."""

    def __init__(self, name, agent_config=None, forecaster=None):
        self.name = name
        self.ac = agent_config or AgentConfig()
        self.forecaster = forecaster or TrendForecaster(self.ac.min_trend_readings)   # any Forecaster
        self.memory = {}         # cell id -> [(reading, irrigation points since previous reading)]
        self.pending = {}        # cell id -> approved points not yet seen in a reading
        self.price = 1.0         # water price multiplier from the Manager's latest broadcast

    def act(self, bus, cycle, cells, readings, config):
        """One cycle: read the inbox, assess every cell, send recommendations and a zone status.
        Returns the assessments so the dashboard can show each cell's forecast and scores."""
        self.read_inbox(bus, config)
        mine = [c for c in cells if c['zone'] == self.name]
        assessments = [self.assess_cell(c['id'], readings[c['id']], config) for c in mine]
        recommendations = [a for a in assessments if a['option'] != 'wait']
        for r in recommendations:
            bus.send(cycle, self.name, MANAGER, 'recommendation', r,
                     f"{r['cell']}: {OPTIONS[r['option']].lower()}, {r['amount']:,.0f} L ({r['priority']}). "
                     f"Forecast {r['forecast']:.1f}% in 1 h.", topic=r['cell'], signature=r['option'])   # repeats fold in the feed
        status = self.zone_status(mine, {a['cell']: a['level'] for a in assessments}, config, len(recommendations))
        bus.send(cycle, self.name, MANAGER, 'zone-status', status,
                 f"{status['cells']} cells checked, {status['dry']} estimated below {config.trigger:g}%"
                 f"{' (stressed)' if status['stressed'] else ''}. {len(recommendations)} recommendations.")
        return assessments

    def read_inbox(self, bus, config):
        """Take in the Manager's tank broadcast and last cycle's decisions."""
        for m in bus.receive(self.name):
            if m['kind'] == 'tank-status':
                self.price = m['body']['price']
            elif m['kind'] == 'decision':
                self.pending[m['body']['cell']] = m['body']['allocated'] / config.litres_per_point

    def assess_cell(self, cell, reading, config):
        """Record the reading, estimate the moisture now and about an hour ahead, and pick the
        best-scoring option. The estimate (not the noisy raw reading) drives every decision."""
        history = self.memory.setdefault(cell, [])
        history.append((reading, self.pending.pop(cell, 0.0)))
        del history[:-self.ac.forecast_window]
        readings, irrigation = [r for r, _ in history], [w for _, w in history[1:]]
        horizon = max(1, round(self.ac.forecast_minutes / config.tick_minutes))
        level = self.forecaster.predict(readings, irrigation, 0)
        forecast = self.forecaster.predict(readings, irrigation, horizon)
        priority = 'critical' if min(level, forecast) < config.critical else 'normal'
        warming_up = len(history) < self.ac.min_readings and priority != 'critical'
        gap = max(0.0, config.target - forecast) * config.litres_per_point   # litres to reach target
        litres = {'wait': 0.0, 'part': gap * self.ac.part_fraction, 'full': gap} if gap and not warming_up else {'wait': 0.0}
        options = {k: dict(litres=v, utility=self.utility(forecast, v, config)) for k, v in litres.items()}
        choice = max(options, key=lambda k: options[k]['utility'])   # ties keep the earlier, cheaper option
        assessment = dict(cell=cell, zone=self.name, reading=reading, level=level, forecast=forecast,
                          rate=(forecast - level) / horizon, option=choice, amount=options[choice]['litres'],
                          utility=options[choice]['utility'], options=options, priority=priority,
                          readings=len(history), warming_up=warming_up)
        assessment['rationale'] = self.rationale(assessment)
        return assessment

    def utility(self, forecast, litres, config):
        """Score of adding `litres` now, relative to waiting (0 = wait):
        0.5 x benefit + 0.3 x urgency - 0.2 x cost, each term scaled 0..1."""
        if not litres:
            return 0.0
        points = litres / config.litres_per_point
        after = min(100.0, forecast + points)
        # Benefit: share of the available water restored. Above the trigger the crop isn't
        # stressed (FAO-56 readily available water), so topping up there earns nothing.
        benefit = (min(after, config.target) - forecast) / 100 if forecast < config.trigger else 0.0
        urgency = self.stress(forecast, config) - self.stress(after, config)   # stress avoided
        cost = points / 100 * self.price               # share of available water used, priced by scarcity
        return self.ac.benefit_weight * benefit + self.ac.urgency_weight * urgency - self.ac.cost_weight * cost

    def stress(self, moisture, config):
        """0 at or above the trigger, rising to 1 at the wilting point; points below critical count
        `critical_stress_weight` times (double by default)."""
        extra = self.ac.critical_stress_weight - 1
        below = max(0.0, config.trigger - moisture) + extra * max(0.0, config.critical - moisture)
        return min(1.0, below / (config.trigger + extra * config.critical))

    def rationale(self, a):
        """One readable sentence explaining the chosen option."""
        head = f"Estimate {a['level']:.1f}%, forecast {a['forecast']:.1f}% in 1 h ({a['rate']:+.2f} per cycle)"
        others = ', '.join(f"{OPTIONS[k].lower()} {v['utility']:.2f}" for k, v in a['options'].items() if k != a['option'])
        if a['warming_up']:
            return f"{head}; only {a['readings']} readings so far, waiting for {self.ac.min_readings} before acting."
        if not others:
            return f'{head}; at or above target, no water needed.'
        if a['option'] == 'wait':
            return f'{head}; waiting scores best (0.00 vs {others}).'
        critical = '; critical' if a['priority'] == 'critical' else ''
        return f"{head}{critical}. {OPTIONS[a['option']]} scores {a['utility']:.2f} vs {others}."

    def zone_status(self, cells, levels, config, recommendations=0):
        """Stressed flag: more than a quarter of the zone's cells are estimated below the trigger."""
        dry = sum(levels[c['id']] < config.trigger for c in cells)
        return dict(zone=self.name, cells=len(cells), dry=dry, stressed=dry > len(cells) * self.ac.stressed_share,
                    recommendations=recommendations)


class ManagerAgent:
    """The only decision-maker: announces the tank, reviews recommendations, replies with reasons."""

    def __init__(self, agent_config=None):
        self.ac = agent_config or AgentConfig()

    def announce(self, bus, cycle, tank):
        """Broadcast the tank level and the water price multiplier zones should weigh this cycle."""
        scarcity = max(0.0, 1 - tank / self.ac.comfortable_tank)
        price = 1 + self.ac.scarcity_price * scarcity
        mood = 'plentiful' if scarcity == 0 else 'scarce' if scarcity > .5 else 'limited'
        bus.send(cycle, MANAGER, 'all', 'tank-status', dict(tank=tank, scarcity=scarcity, price=price),
                 f'Tank {tank:,.0f} L. Water is {mood}: price x{price:.2f}.')

    def review(self, bus, cycle, tank):
        """Read this cycle's recommendations and zone statuses, decide each one, reply to each zone."""
        inbox = bus.receive(MANAGER)
        recommendations = [m['body'] for m in inbox if m['kind'] == 'recommendation']
        statuses = [m['body'] for m in inbox if m['kind'] == 'zone-status']
        allocations = self.allocate(recommendations, tank)
        decisions = [self.decide(r, allocations[r['cell']], tank) for r in recommendations]
        for d in decisions:
            bus.send(cycle, MANAGER, d['zone'], 'decision', d,
                     f"{d['cell']}: {d['status']} {d['allocated']:,.0f} of {d['amount']:,.0f} L. {d['reason']}",
                     topic=d['cell'], signature=(d['status'], d['reason']))   # repeats fold in the feed
        assessment = dict(self.assess(statuses), shortage=self.explain_shortage(recommendations, allocations, tank))
        return dict(decisions=decisions, allocations=allocations, assessment=assessment)

    def decide(self, rec, allocated, tank):
        """Label one recommendation approved, adjusted or rejected, with the Manager's reason."""
        normal = rec['priority'] == 'normal'
        if abs(allocated - rec['amount']) < 1e-8:
            status, reason = 'approved', f"Approved: enough water for every {rec['priority']} recommendation."
        elif allocated > 1e-8:
            status = 'adjusted'
            reason = ('Adjusted: critical needs served first; normal recommendations share what is left in proportion.'
                      if normal else 'Adjusted: critical recommendations share the available water in proportion.')
        else:
            status = 'rejected'
            reason = 'Rejected: the tank is empty.' if tank <= 1e-8 else 'Rejected: critical needs used all available water.'
        return dict(rec, allocated=allocated, status=status, reason=reason)

    def assess(self, reports):
        """farm_wide_zones or more stressed zones (3-4 by default): farm-wide; fewer: local; none: normal."""
        stressed=[r['zone'] for r in reports if r['stressed']]
        if len(stressed) >= self.ac.farm_wide_zones:
            level='farm-wide'
            message=(f'Farm-wide: all {len(reports)} zones stressed.' if len(stressed)==len(reports)
                     else f'Farm-wide: {len(stressed)} of {len(reports)} zones stressed ({", ".join(stressed)}).')
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

    def explain_shortage(self, requests, allocations, available):
        """Explain a cycle's allocation when the tank can't cover every request; None if it can.
        Reads the finished allocation only; it never changes who gets water."""
        requested = sum(r['amount'] for r in requests)
        if requested <= available + 1e-8:
            return None
        zones = lambda rs: list(dict.fromkeys(r['zone'] for r in rs))  # unique, in agent order
        critical = [r for r in requests if r['priority']=='critical']
        normal = [r for r in requests if r['priority']=='normal']
        got = lambda r: allocations[r['cell']]
        critical_total = sum(r['amount'] for r in critical)
        coverage = sum(map(got, critical))/critical_total if critical_total else 1.0
        prioritised = zones(critical)
        reduced = zones(r for r in normal if 1e-8 < got(r) < r['amount']-1e-8)    # got some water
        delayed = zones(r for r in normal if got(r) <= 1e-8)                      # got none this cycle
        parts = [f'Water short: {requested:,.0f} L requested, {available:,.0f} L available.']
        if prioritised: parts.append(f'Prioritised for critical cells: {", ".join(prioritised)}.')
        if coverage < 1-1e-8: parts.append(f'Critical requests only {coverage:.0%} covered.')
        if reduced: parts.append(f'Normal requests reduced: {", ".join(reduced)}.')
        if delayed: parts.append(f'Normal requests delayed: {", ".join(delayed)}.')
        return dict(requested=requested, available=available, critical_coverage=coverage,
                    prioritised=prioritised, reduced=reduced, delayed=delayed, message=' '.join(parts))
