import os, json, secrets, socket, sqlite3, sys, threading, webbrowser
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs

page = Path(__file__).with_name('play.html').read_bytes()
db = sqlite3.connect(':memory:', check_same_thread=False)
db.executescript('CREATE TABLE rooms(id TEXT PRIMARY KEY, host TEXT, stage INTEGER); CREATE TABLE votes(room,stage,voter,choice,PRIMARY KEY(room,stage,voter));')
lock = threading.Lock()

class Handler(BaseHTTPRequestHandler):
    def send(self, value, code=200):
        raw = value if isinstance(value,bytes) else json.dumps(value).encode()
        self.send_response(code)
        self.send_header('Content-Type','text/html; charset=utf-8' if isinstance(value,bytes) else 'application/json')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Length',str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        url=urlsplit(self.path)
        assets={'/manifest.webmanifest':'application/manifest+json','/arcade-192.png':'image/png','/arcade-512.png':'image/png'}
        if url.path in assets:
            data=Path(__file__).with_name(url.path[1:]).read_bytes()
            self.send_response(200)
            self.send_header('Content-Type',assets[url.path])
            self.send_header('Content-Length',str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if url.path=='/': return self.send(page)
        if url.path=='/join':
            with lock:
                latest=db.execute('SELECT id FROM rooms ORDER BY rowid DESC LIMIT 1').fetchone()
            if not latest:
                return self.send(b'<meta name="viewport" content="width=device-width"><meta http-equiv="refresh" content="3"><h1>Waiting for the presenter to create a game...</h1>')
            self.send_response(302)
            self.send_header('Location','/?join='+latest[0])
            self.send_header('Cache-Control','no-store')
            self.end_headers()
            return
        if url.path!='/api': return self.send({},404)
        q=parse_qs(url.query)
        room=q.get('room',[''])[0]
        with lock:
            row=db.execute('SELECT stage FROM rooms WHERE id=?',(room,)).fetchone()
            if not row: return self.send({'error':'Room unavailable. Scan the current QR code.'},404)
            stage=row[0]
            voting=stage if stage%2 else stage-1
            total,a=db.execute('SELECT count(*),coalesce(sum(choice=0),0) FROM votes WHERE room=? AND stage=?',(room,voting)).fetchone()
            mine=db.execute('SELECT choice FROM votes WHERE room=? AND stage=? AND voter=?',(room,voting,q.get('voter',[''])[0])).fetchone()
            rounds=[] if stage!=11 else [
                dict(total=n,a=auto) for n,auto in
                (db.execute('SELECT count(*),coalesce(sum(choice=0),0) FROM votes WHERE room=? AND stage=?',(room,k)).fetchone() for k in (1,3,5,7,9))]
        self.send(dict(stage=stage,total=total,a=a if stage and not stage%2 else None,mine=mine[0] if mine else None,rounds=rounds))

    def do_POST(self):
        if self.path!='/api': return self.send({},404)
        try:
            size=int(self.headers.get('Content-Length',0))
            if not 0<size<4096: raise ValueError()
            b=json.loads(self.rfile.read(size))
            if not isinstance(b,dict): raise ValueError()
        except (ValueError,TypeError): return self.send({'error':'Invalid request'},400)
        with lock:
            if b.get('op')=='create':
                room,host=secrets.token_hex(12),secrets.token_hex(24)
                db.execute('INSERT INTO rooms VALUES(?,?,0)',(room,host))
                return self.send(dict(id=room,host=host))
            room=b.get('room','')
            row=db.execute('SELECT host,stage FROM rooms WHERE id=?',(room,)).fetchone()
            if not row: return self.send({'error':'Room unavailable'},404)
            host,stage=row
            if b.get('stage')!=stage: return self.send({'error':'The round has changed.'},409)
            if b.get('op')=='advance' and b.get('host')==host and stage<11:
                db.execute('UPDATE rooms SET stage=stage+1 WHERE id=?',(room,))
            elif b.get('op')=='vote' and stage in (1,3,5,7,9) and b.get('choice') in (0,1) and isinstance(b.get('voter'),str):
                db.execute('INSERT OR IGNORE INTO votes VALUES(?,?,?,?)',(room,stage,b['voter'],b['choice']))
            else: return self.send({'error':'Action unavailable'},403)
        self.send({'ok':True})

    def log_message(self,*args): pass

if __name__=='__main__':
    try:
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
            sock.connect(('192.0.2.1',9))
            ip=sock.getsockname()[0]
    except OSError: ip=socket.gethostbyname(socket.gethostname())
    server=ThreadingHTTPServer(('',int(os.environ.get('PORT',8765))),Handler)
    url='http://'+ip+':'+str(server.server_port)
    print('Presenter screen: '+url+'\nKeep this window open during the game. Press Ctrl+C to end.')
    if not os.environ.get('PORT'): webbrowser.open(url)
    server.serve_forever()

