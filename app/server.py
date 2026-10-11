from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
from pathlib import Path
import json,webbrowser,sys,threading
from urllib.parse import urlparse
from .engine import load,save,scan,launch

PUBLIC=Path(__file__).parent.parent/'web'
class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(PUBLIC),**kwargs)
    def response(self,code,data):
        body=json.dumps(data,ensure_ascii=False).encode('utf-8');self.send_response(code);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body)
    def do_GET(self):
        path=urlparse(self.path).path
        if path=='/api/games':return self.response(200,load())
        if path=='/api/scan':return self.response(200,{'games':scan()})
        return super().do_GET()
    def do_POST(self):
        path=urlparse(self.path).path
        if path not in ('/api/games','/api/launch'):return self.response(404,{'error':'Rota desconhecida'})
        try:
            length=int(self.headers.get('Content-Length','0'))
            if length<1 or length>65536:return self.response(413,{'error':'Requisição inválida'})
            data=json.loads(self.rfile.read(length))
            if path=='/api/games':
                games=data.get('games')
                if not isinstance(games,list) or len(games)>400:return self.response(400,{'error':'Lista inválida'})
                clean=[]
                for g in games:
                    if not isinstance(g,dict):continue
                    name=str(g.get('name','')).strip()[:100];p=str(g.get('path','')).strip()[:2048]
                    if name and p:clean.append({'id':str(g.get('id') or p),'name':name,'path':p,'favorite':bool(g.get('favorite',False))})
                db=load();db['games']=clean;save(db);return self.response(200,{'ok':True,'games':clean})
            if path=='/api/launch':
                ident=str(data.get('id',''));mode=data.get('mode','normal')
                if mode not in ('normal','optimized'):return self.response(400,{'error':'Modo inválido'})
                db=load();game=next((x for x in db['games'] if x['id']==ident),None)
                if game is None:return self.response(404,{'error':'Jogo não cadastrado'})
                output=launch(game,mode)
                db['history']=[{'id':ident,'mode':mode,'date':__import__('datetime').datetime.now().isoformat(timespec='seconds')},*db.get('history',[])][:50]
                save(db);return self.response(200,{'ok':True,**output})
        except Exception as e:return self.response(400,{'error':str(e)})

def main():
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    url=f'http://127.0.0.1:{server.server_port}'
    print('SuperRender:',url,flush=True)
    threading.Timer(0.7,lambda:webbrowser.open(url)).start()
    try:server.serve_forever()
    except KeyboardInterrupt:pass
if __name__=='__main__':main()
