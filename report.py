"""Create a run-specific AGORA PDF report from the current simulation state."""
from datetime import datetime, timezone
from io import BytesIO
import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (BaseDocTemplate, Frame, PageTemplate, Paragraph,
                                Spacer, Table, TableStyle, KeepTogether, PageBreak)
from reportlab.graphics.shapes import Drawing, Line, PolyLine, String, Circle, Rect


INK = colors.HexColor('#141412')
PANEL = colors.HexColor('#1C1B18')
MUTED = colors.HexColor('#716E66')
TEAL = colors.HexColor('#199E70')
WATER = colors.HexColor('#2867B2')
GOLD = colors.HexColor('#C98500')
RED = colors.HexColor('#C8664A')
PALE = colors.HexColor('#F1EFE8')
GRID = colors.HexColor('#D9D4C8')
ZONE_COLORS = [colors.HexColor(x) for x in ('#199E70', '#D95926', '#7669D4', '#C98500')]


def _num(value, places=0):
    try:
        return f'{float(value):,.{places}f}'
    except (TypeError, ValueError):
        return '0'


def _litres(value):
    return f'{_num(value)} L'


def _time_label(tick, tick_minutes):
    total = max(0, int(tick)) * tick_minutes
    day = total // 1440 + 1
    hour = total // 60 % 24
    minute = total % 60
    return f'Day {day} {hour:02d}:{minute:02d}'


def _styles():
    base = getSampleStyleSheet()
    return {
        'title': ParagraphStyle('AgoraTitle', parent=base['Title'], fontName='Helvetica-Bold',
                                fontSize=24, leading=27, textColor=INK, alignment=TA_LEFT,
                                spaceAfter=3),
        'subtitle': ParagraphStyle('AgoraSubtitle', parent=base['Normal'], fontSize=9,
                                   leading=12, textColor=MUTED, spaceAfter=8),
        'h1': ParagraphStyle('AgoraH1', parent=base['Heading1'], fontName='Helvetica-Bold',
                             fontSize=13, leading=16, textColor=INK, spaceBefore=8,
                             spaceAfter=5, keepWithNext=True),
        'h2': ParagraphStyle('AgoraH2', parent=base['Heading2'], fontName='Helvetica-Bold',
                             fontSize=9, leading=11, textColor=TEAL, spaceBefore=5,
                             spaceAfter=3, keepWithNext=True),
        'body': ParagraphStyle('AgoraBody', parent=base['BodyText'], fontSize=8,
                               leading=10.5, textColor=INK, spaceAfter=3),
        'small': ParagraphStyle('AgoraSmall', parent=base['BodyText'], fontSize=7,
                                leading=9, textColor=MUTED, spaceAfter=2),
        'cell': ParagraphStyle('AgoraCell', parent=base['BodyText'], fontSize=7,
                               leading=8.5, textColor=INK),
        'metriclabel': ParagraphStyle('AgoraMetricLabel', parent=base['BodyText'], fontName='Helvetica-Bold',
                                      fontSize=6.5, leading=8, textColor=MUTED),
        'metricvalue': ParagraphStyle('AgoraMetricValue', parent=base['BodyText'], fontName='Helvetica-Bold',
                                      fontSize=13, leading=15, textColor=INK),
        'headcell': ParagraphStyle('AgoraHeadCell', parent=base['BodyText'], fontName='Helvetica-Bold',
                                   fontSize=7.5, leading=9.5, textColor=colors.white),
        'callout': ParagraphStyle('AgoraCallout', parent=base['BodyText'], fontSize=8.5,
                                  leading=12, textColor=INK, leftIndent=7, rightIndent=7,
                                  spaceBefore=4, spaceAfter=4),
    }


def _table(rows, widths, header=True, font_size=7.5):
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0, hAlign='LEFT')
    commands = [
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('GRID', (0, 0), (-1, -1), .3, GRID),
    ]
    if header:
        commands += [('BACKGROUND', (0, 0), (-1, 0), PANEL),
                     ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, PALE])]
    else:
        commands += [('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.white, PALE])]
    t.setStyle(TableStyle(commands))
    return t


def _moisture_chart(history, zones, config, styles):
    width, height = 174 * mm, 62 * mm
    d = Drawing(width, height)
    left, right, top, bottom = 38, width - 14, height - 18, 28
    plot_w, plot_h = right - left, top - bottom
    rows = history or []
    start = max(0, len(rows) - 337)
    rows = rows[start:]
    max_tick = max((float(row[0]) for row in rows), default=0)
    min_tick = float(rows[0][0]) if rows else 0
    if max_tick <= min_tick:
        max_tick = min_tick + 1
    def X(t): return left + (float(t) - min_tick) / (max_tick - min_tick) * plot_w
    def Y(v): return bottom + max(0, min(100, float(v))) / 100 * plot_h
    for value in (0, 20, 40, 60, 80, 100):
        y = Y(value)
        d.add(Line(left, y, right, y, strokeColor=GRID, strokeWidth=.45))
        d.add(String(left - 7, y - 2, str(value), fontName='Helvetica', fontSize=7,
                     fillColor=MUTED, textAnchor='end'))
    for value, color, label in ((config['critical'], RED, 'Critical'), (config['trigger'], GOLD, 'Irrigation')):
        y = Y(value)
        d.add(Line(left, y, right, y, strokeColor=color, strokeWidth=.9, strokeDashArray=[3, 2]))
        d.add(String(right - 2, y + 3, f'{label} {value:g}%', fontName='Helvetica-Bold',
                     fontSize=6.5, fillColor=color, textAnchor='end'))
    d.add(Line(left, bottom, left, top, strokeColor=MUTED, strokeWidth=.7))
    d.add(Line(left, bottom, right, bottom, strokeColor=MUTED, strokeWidth=.7))
    for i, zone in enumerate(zones):
        pts = []
        for row in rows:
            if len(row) > i + 1:
                pts.extend([X(row[0]), Y(row[i + 1])])
        if len(pts) >= 4:
            d.add(PolyLine(pts, strokeColor=ZONE_COLORS[i % len(ZONE_COLORS)], strokeWidth=1.7))
            d.add(Circle(pts[-2], pts[-1], 2.2, fillColor=ZONE_COLORS[i % len(ZONE_COLORS)],
                         strokeColor=colors.white, strokeWidth=.7))
    d.add(String(left, 6, _time_label(min_tick, config['tick_minutes']), fontName='Helvetica',
                 fontSize=6.5, fillColor=MUTED))
    d.add(String(right, 6, _time_label(max_tick, config['tick_minutes']), fontName='Helvetica',
                 fontSize=6.5, fillColor=MUTED, textAnchor='end'))
    legend_d = Drawing(width, 12)
    x = 42
    for i, zone in enumerate(zones):
        legend_d.add(Line(x, 7, x + 12, 7, strokeColor=ZONE_COLORS[i % len(ZONE_COLORS)], strokeWidth=2))
        legend_d.add(String(x + 16, 4, zone, fontName='Helvetica', fontSize=7, fillColor=INK))
        x += 92
    return [d, legend_d]


def _zone_bar_chart(zones, logs):
    width, height = 174 * mm, 44 * mm
    d = Drawing(width, height)
    left, right, top, bottom = 76, width - 18, height - 8, 15
    totals = {z.get('name'): {'requested': 0.0, 'allocated': 0.0} for z in zones}
    for row in logs:
        bucket = totals.get(row.get('zone'))
        if bucket is not None:
            bucket['requested'] += float(row.get('amount', 0))
            bucket['allocated'] += float(row.get('allocated', 0))
    maxv = max([value['requested'] for value in totals.values()] + [1])
    maxv = max(maxv, max((value['allocated'] for value in totals.values()), default=0))
    for i, zone in enumerate(zones):
        y = top - (i + 1) * (top - bottom) / (len(zones) + 1)
        d.add(String(left - 8, y + 2, str(zone.get('name', '')), fontName='Helvetica',
                     fontSize=7.5, fillColor=INK, textAnchor='end'))
        values = totals.get(zone.get('name'), {})
        req = values.get('requested', 0.0); alloc = values.get('allocated', 0.0)
        req_w = (right - left) * req / maxv
        alloc_w = (right - left) * alloc / maxv
        d.add(Rect(left, y, req_w, 5, fillColor=colors.HexColor('#DDE4E2'), strokeColor=None))
        d.add(Rect(left, y + 7, alloc_w, 5, fillColor=WATER, strokeColor=None))
        d.add(String(min(right - 3, left + req_w + 4), y + 1, _num(req), fontName='Helvetica',
                     fontSize=6.5, fillColor=INK))
        d.add(String(min(right - 3, left + alloc_w + 4), y + 8, _num(alloc), fontName='Helvetica',
                     fontSize=6.5, fillColor=WATER))
    d.add(Line(left, bottom - 2, right, bottom - 2, strokeColor=MUTED, strokeWidth=.6))
    d.add(String(left, 1, 'Grey: requested L     Blue: allocated L', fontName='Helvetica',
                 fontSize=6.5, fillColor=MUTED))
    return d


def _recommendations(state):
    out = []
    cfg = state['config']; capacity = float(state.get('capacity') or 0)
    tank = float(state.get('tank') or 0)
    if not state.get('tick'):
        out.append('Run the simulation before exporting if you want cycle-level results in this report.')
    if capacity and tank / capacity < .2:
        out.append('The tank ended below 20% of capacity. Review whether the modeled water supply and storage buffer match the intended farm.')
    critical = [c for c in state.get('cells', []) if c.get('moisture', 100) < cfg.get('critical', 0)]
    if critical:
        zones = sorted({c.get('zone', '') for c in critical})
        out.append(f'{len(critical)} plots ended below the configured critical threshold. Review plots in {", ".join(zones)} and check sensor and water-allocation assumptions.')
    last = state.get('requests', [])
    short = [r for r in last if r.get('status') in ('adjusted', 'rejected')]
    if short:
        out.append(f'{len(short)} requests were reduced or rejected in the latest cycle. Review available supply, tank capacity, and the reported priority decisions.')
    if state.get('pump_off_left'):
        out.append('A pump-failure event was still active at report time. Treat the current supply level as affected by the simulated outage.')
    if state.get('weather', {}).get('heatwave_left') or state.get('weather', {}).get('drought_left'):
        out.append('A weather event was active at report time. Compare recovery after the event ends before drawing conclusions about routine operation.')
    if not out:
        out.append('No configured critical-threshold breach or reduced/rejected request was present in the latest state. Continue testing shortage and equipment-failure scenarios.')
    return out


def _key_settings(state, styles):
    cfg, env, agents = state.get('config', {}), state.get('environment', {}), state.get('agent_config', {})
    pairs = [
        ('Irrigation line', f"{_num(cfg.get('trigger', 0))}%"),
        ('Critical line', f"{_num(cfg.get('critical', 0))}%"),
        ('Moisture target', f"{_num(cfg.get('target', 0))}%"),
        ('Decision cycle', f"{_num(cfg.get('tick_minutes', 0))} min"),
        ('Tank capacity', _litres(state.get('capacity', 0))),
        ('Daily supply quota', _litres(state.get('supply_per_day', 0))),
        ('Water per moisture point', _litres(cfg.get('litres_per_point', 0))),
        ('Sensor noise', f"±{_num(cfg.get('sensor_noise', 0), 3)} points"),
        ('Forecast horizon', f"{_num(agents.get('forecast_minutes', 0))} min"),
        ('Base drying rate', f"{_num(env.get('base_drying_rate', 0), 3)} points/cycle"),
    ]
    rows = []
    for i in range(0, len(pairs), 2):
        left = pairs[i]; right = pairs[i + 1] if i + 1 < len(pairs) else ('', '')
        rows.append([Paragraph(left[0], styles['cell']), Paragraph(left[1], styles['cell']),
                     Paragraph(right[0], styles['cell']), Paragraph(right[1], styles['cell'])])
    return rows


def _metric_grid(items, width, styles):
    tile_w = width / 3
    tiles = []
    for label, value, accent in items:
        tile = Table([[Paragraph(label.upper(), styles['metriclabel'])],
                      [Paragraph(value, styles['metricvalue'])]], colWidths=[tile_w - 4*mm])
        tile.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),PALE), ('BOX',(0,0),(-1,-1),.4,GRID),
                                  ('LINEBEFORE',(0,0),(0,-1),2.5,accent), ('LEFTPADDING',(0,0),(-1,-1),7),
                                  ('RIGHTPADDING',(0,0),(-1,-1),5), ('TOPPADDING',(0,0),(-1,-1),4),
                                  ('BOTTOMPADDING',(0,0),(-1,-1),4)]))
        tiles.append(tile)
    rows = [tiles[0:3], tiles[3:6]]
    grid = Table(rows, colWidths=[tile_w]*3, hAlign='LEFT')
    grid.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'), ('LEFTPADDING',(0,0),(-1,-1),0),
                              ('RIGHTPADDING',(0,0),(-1,-1),3), ('TOPPADDING',(0,0),(-1,-1),2),
                              ('BOTTOMPADDING',(0,0),(-1,-1),2)]))
    return grid


def _on_page(canvas, doc):
    canvas.saveState()
    width, height = A4
    canvas.setFillColor(PANEL)
    canvas.rect(0, height - 17*mm, width, 17*mm, fill=1, stroke=0)
    canvas.setFillColor(WATER)
    canvas.rect(0, height - 17*mm, 3*mm, 17*mm, fill=1, stroke=0)
    canvas.setFont('Helvetica-Bold', 10); canvas.setFillColor(colors.HexColor('#ECE9E2'))
    canvas.drawString(18 * mm, height - 10.5 * mm, 'AGORA')
    canvas.setFont('Helvetica', 7); canvas.setFillColor(colors.HexColor('#B9B4A8'))
    canvas.drawString(39 * mm, height - 10.2 * mm, 'FARM OPERATIONS')
    canvas.setFont('Helvetica-Bold', 7); canvas.setFillColor(colors.HexColor('#B9D6AE'))
    canvas.drawRightString(width - 18 * mm, height - 10.2 * mm, 'SIMULATION RUN REPORT')
    canvas.setStrokeColor(GRID); canvas.setLineWidth(.5)
    canvas.line(18 * mm, 13 * mm, width - 18 * mm, 13 * mm)
    canvas.setFont('Helvetica', 7); canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, 8.5 * mm, 'SIMULATED DATA  /  Verify locally before field use')
    canvas.drawRightString(width - 18 * mm, 8.5 * mm, f'Page {doc.page}')
    canvas.restoreState()


def build_report(state, timezone_name=None):
    """Return a concise two-part PDF from the current Farm.state() payload."""
    timezone_name = timezone_name or os.environ.get('AGORA_REPORT_TIMEZONE', 'Africa/Cairo')
    try:
        local_tz = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        timezone_name, local_tz = 'UTC', timezone.utc
    generated_utc = datetime.now(timezone.utc)
    generated_local = generated_utc.astimezone(local_tz)
    styles = _styles(); stream = BytesIO()
    doc = BaseDocTemplate(stream, pagesize=A4, leftMargin=18*mm, rightMargin=18*mm,
                          topMargin=23*mm, bottomMargin=18*mm,
                          title='AGORA Farm Run Report', author='AGORA')
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id='main',
                  leftPadding=0, rightPadding=0, topPadding=1*mm, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id='report', frames=frame, onPage=_on_page)])

    tick = int(state.get('tick', 0)); cfg = state.get('config', {})
    tick_minutes = int(cfg.get('tick_minutes', 30)); duration_minutes = tick * tick_minutes
    scenario = state.get('scenarios', {}).get(state.get('scenario'), state.get('scenario', 'Unknown'))
    cells = state.get('cells', []); zones = state.get('zones', [])
    average = sum(float(c.get('moisture', 0)) for c in cells) / max(1, len(cells))
    critical_n = sum(float(c.get('moisture', 100)) < float(cfg.get('critical', 0)) for c in cells)
    requests = state.get('requests', [])
    counts = {s: sum(r.get('status') == s for r in requests) for s in ('approved', 'adjusted', 'rejected')}
    capacity = float(state.get('capacity') or 0)
    tank_text = f'{_num(state.get("tank", 0))} / {_num(capacity)} L'
    if tick == 0:
        run_window = 'No cycles run yet'
    else:
        run_window = f'Day 1 00:00 to {_time_label(tick, tick_minutes)}'

    # Page 1: run indicators, charts, and findings for quick reading.
    story = [Spacer(1, 1*mm), Paragraph('Farm Run Report', styles['title']),
             Paragraph('Simulation results and operational observations', styles['subtitle'])]
    meta = Table([
        [Paragraph('SCENARIO', styles['metriclabel']), Paragraph('SIMULATION WINDOW', styles['metriclabel']),
         Paragraph('SIMULATED TIME', styles['metriclabel']), Paragraph('REPORT TIME', styles['metriclabel'])],
        [Paragraph(str(scenario), styles['cell']), Paragraph(run_window, styles['cell']),
         Paragraph(f'{tick} cycles / {duration_minutes / 60:g} hours', styles['cell']),
         Paragraph(generated_local.strftime('%d %b %Y, %H:%M %Z') +
                   f'<br/><font color="#716E66">UTC {generated_utc:%Y-%m-%d %H:%M}</font>', styles['cell'])],
    ], colWidths=[35*mm, 52*mm, 36*mm, 51*mm])
    meta.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),PALE), ('BOX',(0,0),(-1,-1),.4,GRID),
                              ('INNERGRID',(0,0),(-1,-1),.3,GRID), ('VALIGN',(0,0),(-1,-1),'TOP'),
                              ('LEFTPADDING',(0,0),(-1,-1),6), ('RIGHTPADDING',(0,0),(-1,-1),5),
                              ('TOPPADDING',(0,0),(-1,-1),4), ('BOTTOMPADDING',(0,0),(-1,-1),4),
                              ('LINEBEFORE',(0,0),(0,-1),2.5,WATER)]))
    story += [meta, Paragraph('Run results', styles['h1'])]
    metrics = [
        ('Average moisture', f'{_num(average, 1)}%', TEAL),
        ('Below critical', f'{critical_n} / {len(cells)} plots', RED if critical_n else TEAL),
        ('Water in tank', tank_text, WATER),
        ('Irrigation applied', _litres(state.get('used', 0)), WATER),
        ('Water supplied', _litres(state.get('supplied', 0)), TEAL),
        ('Evaporation', _litres(state.get('evaporated', 0)), GOLD),
    ]
    story += [_metric_grid(metrics, doc.width, styles), Paragraph('Moisture by zone', styles['h1']),
              Paragraph('Dashed lines mark the configured critical and irrigation thresholds.', styles['small'])]
    story.extend(_moisture_chart(state.get('zone_history', []), state.get('zone_names', []), cfg, styles))
    story += [Paragraph('Recent water requests by zone', styles['h1']),
              Paragraph('Totals across up to 500 decision records retained by the app.', styles['small']),
              _zone_bar_chart(zones, state.get('logs', []))]

    assessment = state.get('assessment')
    if assessment:
        assessment_text = assessment.get('message') or f"Farm assessment: {assessment.get('level', 'unknown')}"
        shortage = assessment.get('shortage') or {}
        if shortage.get('message'):
            assessment_text += ' ' + shortage['message']
    else:
        assessment_text = 'No cycle-level assessment is available yet.'
    assessment_box = Table([[Paragraph(assessment_text, styles['callout'])]], colWidths=[doc.width])
    assessment_box.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),PALE), ('BOX',(0,0),(-1,-1),.4,GRID),
                                        ('LINEBEFORE',(0,0),(0,-1),3,TEAL), ('VALIGN',(0,0),(-1,-1),'TOP')]))
    story += [Paragraph('Manager assessment', styles['h2']), assessment_box,
              Paragraph(f'Latest-cycle decisions: {counts["approved"]} approved, {counts["adjusted"]} adjusted, {counts["rejected"]} rejected.', styles['small']),
              Paragraph('Recommended follow-up', styles['h2'])]
    for item in _recommendations(state)[:3]:
        story.append(Paragraph('&bull; ' + item, styles['body']))

    # Page 2: only settings and caveats that help interpret the run.
    story += [PageBreak(), Paragraph('Data notes and limitations', styles['title']),
              Paragraph('Context needed to interpret this simulation report', styles['subtitle'])]
    note = ('Results are from AGORA\'s simulator, not field measurements. Weather settings are documented as fitted to NOAA USCRN data for Tucson, Arizona (2024-2025). '
            'Soil, crop, sensor, and water-supply values include references and provisional assumptions.')
    story += [Paragraph(note, styles['body']), Paragraph('Key model settings', styles['h1'])]
    key_rows = _key_settings(state, styles)
    key_table = Table(key_rows, colWidths=[39*mm, 48*mm, 39*mm, 48*mm], hAlign='LEFT')
    key_table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'), ('ROWBACKGROUNDS',(0,0),(-1,-1),[colors.white,PALE]),
                                   ('GRID',(0,0),(-1,-1),.3,GRID), ('LEFTPADDING',(0,0),(-1,-1),5),
                                   ('RIGHTPADDING',(0,0),(-1,-1),5), ('TOPPADDING',(0,0),(-1,-1),4),
                                   ('BOTTOMPADDING',(0,0),(-1,-1),4)]))
    story += [key_table, Paragraph('Limitations and next steps', styles['h1'])]
    limits = [
        'Agents and forecasts are rule-based; the current report contains no machine-learning performance results.',
        'The simulation does not validate performance on a physical farm. Confirm soil, crop, sensor, and supply settings with local data.',
        'Before hardware use, field-test recommendations and verify sensor faults, pump interruptions, water limits, and manual override.',
    ]
    for item in limits:
        story.append(Paragraph('&bull; ' + item, styles['body']))

    events = list(reversed(state.get('events', [])))[:6]
    story.append(Paragraph('Recent events', styles['h1']))
    if events:
        rows = [[Paragraph('Simulated time', styles['headcell']), Paragraph('Event', styles['headcell']),
                 Paragraph('Details', styles['headcell'])]]
        for event in events:
            rows.append([Paragraph(_time_label(event.get('tick', 0), tick_minutes), styles['cell']),
                         Paragraph(str(event.get('kind', '')).replace('-', ' ').title(), styles['cell']),
                         Paragraph(str(event.get('text', '')), styles['cell'])])
        story.append(_table(rows, [34*mm, 28*mm, 112*mm]))
    else:
        story.append(Paragraph('No manual or scheduled events were recorded in this run.', styles['body']))

    story.append(Paragraph('Sources', styles['h1']))
    refs = [
        ('NOAA NCEI USCRN hourly data - Tucson 11 W, Arizona, 2024-2025', 'https://www.ncei.noaa.gov/pub/data/uscrn/products/hourly02/'),
        ('FAO Irrigation and Drainage Paper 56', 'https://www.fao.org/4/X0490E/x0490e00.htm'),
        ('UMN Extension - soil water holding capacity', 'https://extension.umn.edu/soil-management-and-health/soil-water-holding-capacity'),
        ('METER TEROS 10 technical specifications', 'https://metergroup.com/products/teros-10/teros-10-tech-specs/'),
    ]
    for label, url in refs:
        story.append(Paragraph(f'&bull; <link href="{url}" color="#2867B2">{label}</link>', styles['small']))

    doc.build(story)
    return stream.getvalue()

