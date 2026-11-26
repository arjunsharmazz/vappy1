"""Resumable range downloads from official hosts; verifies complete SHA256."""
import concurrent.futures
import hashlib
import html
import json
from pathlib import Path
import re
import subprocess
import urllib.parse
import urllib.request

BASE=Path(__file__).resolve().parents[2]/'.tools'/'neural-evaluation'

def fetch(url,target,size,digest):
    if target.exists() and hashlib.file_digest(target.open('rb'),'sha256').hexdigest()==digest:
        print('Verified cached',target.name,flush=True);return
    folder=target.parent/(target.name+'.chunks');folder.mkdir(exist_ok=True)
    chunk=1024*1024
    def part(i):
        start=i*chunk;end=min(size-1,start+chunk-1);out=folder/str(i)
        if out.exists() and out.stat().st_size==end-start+1:return out
        subprocess.run(['curl.exe','--fail','--location','--silent','--show-error','--retry','2','--max-time','240',
                        '--range',f'{start}-{end}','--output',str(out),url],check=True)
        if out.stat().st_size!=end-start+1:raise RuntimeError('Server did not honor Range for '+target.name)
        return out
    count=(size+chunk-1)//chunk
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for n,_ in enumerate(pool.map(part,range(count)),1):
            if n%20==0 or n==count:print(target.name,n,'/',count,'MiB chunks',flush=True)
    pending=target.with_suffix(target.suffix+'.pending');sha=hashlib.sha256()
    with pending.open('wb') as output:
        for i in range(count):
            data=(folder/str(i)).read_bytes();sha.update(data);output.write(data)
    if sha.hexdigest()!=digest:raise RuntimeError('SHA256 mismatch '+target.name)
    pending.replace(target)
    for item in folder.iterdir():item.unlink()
    folder.rmdir()
    print('Verified',target.name,size,'bytes',flush=True)

if __name__=='__main__':
    wheel='torch-2.6.0+cpu-cp311-cp311-win_amd64.whl'
    index=urllib.request.urlopen('https://download.pytorch.org/whl/cpu/torch/',timeout=30).read().decode()
    links=re.findall(r'href="([^"]+)"',index)
    link=next(html.unescape(v) for v in links if urllib.parse.unquote(v.split('/')[-1].split('#')[0])==wheel)
    digest=link.split('#sha256=')[1];url=link.split('#')[0]
    fetch(url,BASE/wheel,206540444,digest)
    for item in json.loads((BASE/'weights.json').read_text()):
        fetch('https://huggingface.co/KlingTeam/LivePortrait/resolve/main/'+item['path'],BASE/'weights'/Path(item['path']).name,item['size'],item['lfs']['oid'])
