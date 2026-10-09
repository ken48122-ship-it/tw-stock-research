"""Pinned official Ollama on the ephemeral GitHub runner."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request

VERSION='v0.40.2'
DIGEST='726bee78706c281b0eeef00746efe51a044d71c592c3f0b195820707f31fdf04'
URL=f'https://github.com/ollama/ollama/releases/download/{VERSION}/ollama-linux-amd64.tar.zst'

def main():
    root=Path(os.environ['RUNNER_TEMP'])/'tw-stock-ai'
    root.mkdir(exist_ok=True)
    executable=root/'bin'/'ollama'
    if not executable.exists():
        archive=root/'ollama.tar.zst';digest=hashlib.sha256()
        with urllib.request.urlopen(URL,timeout=90) as response, archive.open('wb') as f:
            while chunk:=response.read(1024*1024):
                digest.update(chunk);f.write(chunk)
        if digest.hexdigest()!=DIGEST: raise RuntimeError('Official binary checksum mismatch')
        subprocess.run(['tar','--zstd','-xf',str(archive),'-C',str(root)],check=True,timeout=180)
        archive.unlink()
    env={**os.environ,'OLLAMA_HOST':'127.0.0.1:11434','OLLAMA_MODELS':str(root/'models'),'OLLAMA_NUM_PARALLEL':'1','OLLAMA_MAX_LOADED_MODELS':'1'}
    log=(root/'server.log').open('w')
    subprocess.Popen([str(executable),'serve'],env=env,stdout=log,stderr=log,start_new_session=True)
    for _ in range(30):
        try:
            with urllib.request.urlopen('http://127.0.0.1:11434/api/tags',timeout=2):break
        except Exception:time.sleep(1)
    else: raise RuntimeError('Local inference server did not start')
    subprocess.run([str(executable),'pull','qwen2.5:1.5b-instruct-q4_K_M'],env=env,check=True,timeout=360,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    with urllib.request.urlopen('http://127.0.0.1:11434/api/tags',timeout=5) as r:tags=json.load(r)
    model=next(m for m in tags['models'] if m['name']=='qwen2.5:1.5b-instruct-q4_K_M')
    if not model['digest'].removeprefix('sha256:').startswith('65ec06548149'):raise RuntimeError('Model digest changed')
    print(json.dumps({'ollama_version':VERSION,'model_digest':model['digest']}))

if __name__=='__main__':main()
