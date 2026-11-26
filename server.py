"""Local-only HTTP application. Run: python server.py"""
import json
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from threading import Lock
from engine import Farm

farm=Farm(); lock=Lock(); root=Path(__file__).parent/'web'
class Handler(BaseHTTPRequestHandler):
    def respond(self, data, status=200):
        payload=json.dumps(data).encode(); self.send_response(status)
        self.send_header('Content-Type','application/json'); self.send_header('Cache-Control','no-store')
        self.end_headers(); self.wfile.write(payload)
    def do_GET(self):
        if self.path=='/api/state':
            with lock: return self.respond(farm.state())
        if self.path=='/api/report.pdf':
            with lock: snapshot=farm.state()
            try:
                from report import build_report
                payload=build_report(snapshot)
            except ImportError:
                return self.respond({'error':'PDF export requires the optional dependency. Run: python -m pip install -r requirements.txt'},503)
            except Exception as e:
                return self.respond({'error':f'Could not create report: {e}'},500)
            day=1+(snapshot['tick']*snapshot['config']['tick_minutes'])//1440
            filename=f"agora-simulation-report-{snapshot['scenario']}-day-{day}.pdf"
            self.send_response(200)
            self.send_header('Content-Type','application/pdf')
            self.send_header('Content-Disposition',f'attachment; filename="{filename}"')
            self.send_header('Cache-Control','no-store')
            self.end_headers(); self.wfile.write(payload); return
        paths={'/':'index.html','/app.js':'app.js','/style.css':'style.css'}
        if self.path not in paths: return self.respond({'error':'Not found'},404)
        p=root/paths[self.path]; self.send_response(200)
        self.send_header('Content-Type',{'html':'text/html','js':'text/javascript','css':'text/css'}[p.suffix[1:]])
        self.end_headers(); self.wfile.write(p.read_bytes())
    def do_POST(self):
        global farm
        if self.headers.get('Origin') not in (None,'http://127.0.0.1:8765','http://localhost:8765'):
            return self.respond({'error':'Origin rejected'},403)
        try:
            length=int(self.headers.get('Content-Length',0))
            if length>4096: raise ValueError('Request too large')
            data=json.loads(self.rfile.read(length) or b'{}')
            if not isinstance(data,dict): raise ValueError('Expected a JSON object')
            with lock:
                if self.path=='/api/step': farm.advance(data.get('cycles',1))
                elif self.path=='/api/reset': farm=Farm(data.get('scenario','healthy'))
                elif self.path=='/api/refill': farm.refill(_litres(data.get('litres')))
                elif self.path=='/api/event': farm.trigger(data.get('type'),data.get('cell'))
                else: return self.respond({'error':'Not found'},404)
                self.respond(farm.state())
        except (ValueError,TypeError) as e: self.respond({'error':str(e)},400)
def _litres(value):
    """Optional refill amount from a request: a positive number, or None for the default."""
    if value is None: return None
    if isinstance(value,bool) or not isinstance(value,(int,float)): raise ValueError('Litres must be a number')
    return value
if __name__=='__main__':
    print('AGORA running at http://127.0.0.1:8765',flush=True)
    ThreadingHTTPServer(('127.0.0.1',8765),Handler).serve_forever()
