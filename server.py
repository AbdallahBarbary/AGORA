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
            with lock:
                if self.path=='/api/step': farm.step()
                elif self.path=='/api/reset': farm=Farm(data.get('scenario','balanced'))
                elif self.path=='/api/refill': farm.refill(250)
                else: return self.respond({'error':'Not found'},404)
                self.respond(farm.state())
        except (ValueError,TypeError) as e: self.respond({'error':str(e)},400)
if __name__=='__main__':
    print('AGORA running at http://127.0.0.1:8765',flush=True)
    ThreadingHTTPServer(('127.0.0.1',8765),Handler).serve_forever()
