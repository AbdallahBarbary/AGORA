"""The agents. Zone agents forecast and recommend; the Manager is the only one that decides.
They communicate only through the message bus.

The utility weights in AgentConfig are still PROVISIONAL PLACEHOLDERS (not yet fitted).
Water costs are per moisture point, so decisions don't depend on how many litres a point is.
"""
from dataclasses import dataclass
from forecast import TrendForecaster

MANAGER = 'Manager'
OPTIONS = {'wait': 'Wait', 'part': 'Part of the gap', 'full': 'Full gap'}


@dataclass(frozen=True)
class AgentConfig:
    # --- Forecasting (PROVISIONAL placeholders) ---
    forecast_minutes: int = 60      # how far ahead zone agents look
    forecast_window: int = 4        # recent readings per cell used for the trend
    # --- Zone utility weights (PROVISIONAL placeholders) ---
    benefit_weight: float = .6      # per moisture point moved toward the target
    urgency_weight: float = 1.5     # per point of danger avoided below the request trigger
    critical_weight: float = 2      # points below the critical level count this much extra danger
    water_cost: float = .5          # per moisture point of water when it is plentiful
    scarcity_cost: float = .75      # extra cost per moisture point when the tank is empty
    dispatch_cost: float = 3        # fixed cost of any irrigation, so small top-ups wait
                                    # (with plenty of water, agents act once the forecast is below ~39%)
    part_fraction: float = .5       # share of the gap in the "part of the gap" option
    # --- Manager's scarcity signal ---
    comfortable_tank: float = 100_000  # ASSUMPTION: litres; a full Normal tank counts as plentiful


class ZoneAgent:
    """Watches one zone: forecasts each cell, scores its options, recommends to the Manager."""

    def __init__(self, name, agent_config=None, forecaster=None):
        self.name = name
        self.ac = agent_config or AgentConfig()
        self.forecaster = forecaster or TrendForecaster()   # anything with Forecaster.predict()
        self.memory = {}         # cell id -> [(reading, irrigation points since previous reading)]
        self.pending = {}        # cell id -> approved points not yet seen in a reading
        self.cost_per_point = self.ac.water_cost

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
                     f"Forecast {r['forecast']:.1f}% in 1 h.")
        status = self.zone_status(mine, readings, config, len(recommendations))
        bus.send(cycle, self.name, MANAGER, 'zone-status', status,
                 f"{status['cells']} cells checked, {status['dry']} read below {config.trigger:g}%"
                 f"{' (stressed)' if status['stressed'] else ''}. {len(recommendations)} recommendations.")
        return assessments

    def read_inbox(self, bus, config):
        """Take in the Manager's tank broadcast and last cycle's decisions."""
        for m in bus.receive(self.name):
            if m['kind'] == 'tank-status':
                self.cost_per_point = m['body']['cost_per_point']
            elif m['kind'] == 'decision':
                self.pending[m['body']['cell']] = m['body']['allocated'] / config.litres_per_point

    def assess_cell(self, cell, reading, config):
        """Record the reading, forecast about an hour ahead, and pick the best-scoring option."""
        history = self.memory.setdefault(cell, [])
        history.append((reading, self.pending.pop(cell, 0.0)))
        del history[:-self.ac.forecast_window]
        horizon = max(1, round(self.ac.forecast_minutes / config.tick_minutes))
        forecast = self.forecaster.predict([r for r, _ in history], [w for _, w in history[1:]], horizon)
        gap = max(0.0, config.target - forecast) * config.litres_per_point   # litres to reach target
        litres = {'wait': 0.0, 'part': gap * self.ac.part_fraction, 'full': gap} if gap else {'wait': 0.0}
        options = {k: dict(litres=v, utility=self.utility(forecast, v, config)) for k, v in litres.items()}
        choice = max(options, key=lambda k: options[k]['utility'])   # ties keep the earlier, cheaper option
        assessment = dict(cell=cell, zone=self.name, reading=reading, forecast=forecast,
                          rate=(forecast - reading) / horizon, option=choice, amount=options[choice]['litres'],
                          utility=options[choice]['utility'], options=options,
                          priority='critical' if min(reading, forecast) < config.critical else 'normal')
        assessment['rationale'] = self.rationale(assessment)
        return assessment

    def utility(self, forecast, litres, config):
        """Score of adding `litres` now, relative to waiting: benefit + urgency - water cost."""
        if not litres:
            return 0.0
        points = litres / config.litres_per_point
        after = min(100.0, forecast + points)
        deficit = lambda m: max(0.0, config.target - m)
        danger = lambda m: max(0.0, config.trigger - m) + self.ac.critical_weight * max(0.0, config.critical - m)
        benefit = deficit(forecast) - deficit(after)     # points closer to the target
        urgency = danger(forecast) - danger(after)       # danger points avoided
        return (self.ac.benefit_weight * benefit + self.ac.urgency_weight * urgency
                - self.cost_per_point * points - self.ac.dispatch_cost)

    def rationale(self, a):
        """One readable sentence explaining the chosen option."""
        head = f"Forecast {a['forecast']:.1f}% in 1 h ({a['rate']:+.1f} per cycle)"
        others = ', '.join(f"{OPTIONS[k].lower()} {v['utility']:.1f}" for k, v in a['options'].items() if k != a['option'])
        if not others:
            return f'{head}; at or above target, no water needed.'
        if a['option'] == 'wait':
            return f'{head}; waiting scores best (0.0 vs {others}).'
        critical = '; critical' if a['priority'] == 'critical' else ''
        return f"{head}{critical}. {OPTIONS[a['option']]} scores {a['utility']:.1f} vs {others}."

    def zone_status(self, cells, readings, config, recommendations=0):
        """Stressed flag: more than a quarter of the zone's cells read below the trigger."""
        dry = sum(readings[c['id']] < config.trigger for c in cells)
        return dict(zone=self.name, cells=len(cells), dry=dry, stressed=dry > len(cells) / 4,
                    recommendations=recommendations)


class ManagerAgent:
    """The only decision-maker: announces the tank, reviews recommendations, replies with reasons."""

    def __init__(self, agent_config=None):
        self.ac = agent_config or AgentConfig()

    def announce(self, bus, cycle, tank):
        """Broadcast the tank level and the cost per litre zones should weigh this cycle."""
        scarcity = max(0.0, 1 - tank / self.ac.comfortable_tank)
        cost = self.ac.water_cost + self.ac.scarcity_cost * scarcity
        mood = 'plentiful' if scarcity == 0 else 'scarce' if scarcity > .5 else 'limited'
        bus.send(cycle, MANAGER, 'all', 'tank-status', dict(tank=tank, scarcity=scarcity, cost_per_point=cost),
                 f'Tank {tank:,.0f} L. Water is {mood}: cost {cost:.2f} per moisture point.')

    def review(self, bus, cycle, tank):
        """Read this cycle's recommendations and zone statuses, decide each one, reply to each zone."""
        inbox = bus.receive(MANAGER)
        recommendations = [m['body'] for m in inbox if m['kind'] == 'recommendation']
        statuses = [m['body'] for m in inbox if m['kind'] == 'zone-status']
        allocations = self.allocate(recommendations, tank)
        decisions = [self.decide(r, allocations[r['cell']], tank) for r in recommendations]
        for d in decisions:
            bus.send(cycle, MANAGER, d['zone'], 'decision', d,
                     f"{d['cell']}: {d['status']} {d['allocated']:,.0f} of {d['amount']:,.0f} L. {d['reason']}")
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
