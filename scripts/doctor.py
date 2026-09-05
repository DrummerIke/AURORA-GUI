#!/usr/bin/env python3
from __future__ import annotations
import os, importlib.util, shutil, socket, sys
from pathlib import Path
try:
    import yaml
except Exception:
    yaml=None
REQ_ENV={"virustotal":["VIRUSTOTAL_API_KEY"],"shodan":["SHODAN_API_KEY"],"censys":["CENSYS_API_ID","CENSYS_API_SECRET"],"securitytrails":["SECURITYTRAILS_API_KEY"],"haveibeenpwned":["HIBP_API_KEY"],"twilio_lookup":["TWILIO_ACCOUNT_SID","TWILIO_AUTH_TOKEN"],"ipqualityscore":["IPQUALITYSCORE_API_KEY"],"abstract_phone":["ABSTRACT_PHONE_API_KEY"]}
BINS=["phoneinfoga","sherlock","maigret","holehe","dnsx"]
PYMOD=["flask","phonenumbers","ddgs","requests"]
def main():
    cfg=Path(os.getenv('AURORA_CONNECTORS_CONFIG','config/connectors.yaml')); problems=[]; warnings=[]
    print(f"Python: {sys.version.split()[0]}")
    for m in PYMOD:
        ok=importlib.util.find_spec(m) is not None; print(("OK" if ok else "MISS"),"python",m); problems += ([] if ok else [f"python:{m}"])
    print(("OK" if yaml else "WARN"), "python", "yaml", "optional config parser")
    if not yaml: warnings.append('yaml')
    for b in BINS:
        ok=bool(shutil.which(b)); print(("OK" if ok else "WARN"),"binary",b); warnings += ([] if ok else [f"binary:{b}"])
    if cfg.exists():
        print("OK config",cfg)
        if yaml:
            data=yaml.safe_load(cfg.read_text()) or {}
            if not data.get('connectors'): problems.append('connectors_config_empty')
        for cid, envs in REQ_ENV.items():
            miss=[e for e in envs if not os.getenv(e)]
            if miss: print("CONFIGURATION_REQUIRED",cid,",".join(miss)); warnings.append(cid)
    else: print("MISS config",cfg); problems.append('config')
    for host,port,name in [('127.0.0.1',5432,'PostgreSQL'),('127.0.0.1',6379,'Redis')]:
        s=socket.socket(); s.settimeout(.4)
        try: s.connect((host,port)); print('OK',name)
        except OSError: print('WARN',name,'not reachable'); warnings.append(name)
        finally: s.close()
    try: socket.create_connection(('1.1.1.1',53),timeout=1).close(); print('OK network timeout probe')
    except OSError: print('WARN network limited'); warnings.append('network')
    status='NOT_READY' if problems else ('PARTIALLY_READY' if warnings else 'READY')
    print('SUMMARY:',status)
    return 2 if problems else 0
if __name__=='__main__': raise SystemExit(main())
