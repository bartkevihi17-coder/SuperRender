import os,json,subprocess,threading,time,ctypes,winreg
from pathlib import Path
from datetime import datetime

APP_DIR=Path(os.environ.get('LOCALAPPDATA',Path.home()))/'SuperRender'
DB=APP_DIR/'library.json'

def load():
    try:return json.loads(DB.read_text(encoding='utf-8'))
    except (ValueError,OSError):return {'games':[],'history':[]}

def save(db):
    APP_DIR.mkdir(parents=True,exist_ok=True)
    temp=DB.with_suffix('.tmp')
    temp.write_text(json.dumps(db,ensure_ascii=False,indent=2),encoding='utf-8')
    temp.replace(DB)

def scan():
    games=[];seen=set()
    roots=[Path(x) for x in [r'C:\Riot Games',r'D:\Games',r'D:\SteamLibrary\steamapps\common',r'C:\Program Files (x86)\Steam\steamapps\common',r'D:\Assassins Creed III',r'D:\Assassins Creed IV Black Flag',r'D:\Tools\NBA2K20-FPS\LiteMod',r'D:\Steep [FitGirl Repack]']]
    preferred={'NBA2K20.exe':'NBA 2K20','AC3SP.exe':'Assassin’s Creed III','AC4BFSP.exe':'Assassin’s Creed IV: Black Flag','LeagueClient.exe':'League of Legends','Steep.exe':'Steep','RDR.exe':'Red Dead Redemption'}
    known=[]
    for base in roots:
        if not base.is_dir():continue
        try:
            for here,dirs,files in os.walk(base):
                depth=len(Path(here).relative_to(base).parts)
                if depth>=3:dirs[:]=[]
                if any(k in here.lower() for k in ('_redist','redistributable','support','uninstall')):continue
                for filename in files:
                    if filename.casefold() not in {x.casefold() for x in preferred}:continue
                    p=str(Path(here)/filename)
                    if p.casefold() in seen:continue
                    seen.add(p.casefold())
                    display=next(v for k,v in preferred.items() if k.casefold()==filename.casefold())
                    known.append({'name':display,'path':p})
        except OSError:pass
    for entry in known:
        entry['id']=str(abs(hash(entry['path'])))
        games.append(entry)
    return games

def power_scheme():
    try:
        cp=subprocess.run(['powercfg','/GETACTIVESCHEME'],capture_output=True,text=True,timeout=8)
        import re
        m=re.search(r'([a-f0-9]{8}-[a-f0-9-]{27,})',cp.stdout,re.I)
        return m.group(1) if m else None
    except (OSError,subprocess.TimeoutExpired):return None

def launch(game,mode):
    path=Path(game['path']);args=game.get('args',[])
    if not path.is_file():raise FileNotFoundError(str(path))
    if path.suffix.lower() not in ('.exe','.bat','.cmd'):raise ValueError('Selecione um executável Windows.')
    if not isinstance(args,list) or not all(isinstance(a,str) for a in args):raise ValueError('Argumentos inválidos')
    previous=power_scheme() if mode=='optimized' else None
    applied=False
    if mode=='optimized':
        try:
            subprocess.run(['powercfg','/SETACTIVE','SCHEME_MIN'],timeout=8,check=True,capture_output=True)
            applied=True
        except (OSError,subprocess.SubprocessError):pass
    try:
        p=subprocess.Popen([str(path),*args],cwd=str(path.parent),creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        if mode=='optimized':
            try:
                import psutil
                psutil.Process(p.pid).nice(psutil.ABOVE_NORMAL_PRIORITY_CLASS)
            except (ImportError, OSError, ValueError):pass
    except Exception:
        if applied and previous:
            try:subprocess.run(['powercfg','/SETACTIVE',previous],timeout=8,capture_output=True)
            except Exception:pass
        raise
    def restore():
        try:p.wait()
        finally:
            if applied and previous:
                try:subprocess.run(['powercfg','/SETACTIVE',previous],timeout=8,capture_output=True)
                except Exception:pass
    threading.Thread(target=restore,daemon=True).start()
    return {'pid':p.pid,'profile':mode,'power_changed':applied,'priority':'above normal if psutil available' if mode=='optimized' else 'default'}
