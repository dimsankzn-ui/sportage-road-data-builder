"""Fail before publishing if this isolated OSM processor contains private material."""
import argparse,re,subprocess
from pathlib import Path

ALLOWED={'README.md','.github/workflows/road-atlas-russia.yml',
 'server/build_drive_atlas.py','server/build_context_source.py','server/road_context.py',
 'server/road_limits.py','server/road_publications.py','server/road_sources.py',
 'server/ru_federal_districts.py','server/extend_ru_admin_boundaries.py','server/verify_public_source.py'}
PATTERNS={
 'credential':r'GOCSPX-[A-Za-z0-9_-]{20,}|github_pat_[A-Za-z0-9_]{20,}|gh[opusr]_[A-Za-z0-9]{20,}|ya29\.[A-Za-z0-9_-]{20,}',
 'private key':r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
 'IP address':r'\b(?:\d{1,3}\.){3}\d{1,3}\b',
 'personal path':r'/Users/[A-Za-z0-9_-]+/',
 'Google client':r'[0-9]+-[a-z0-9]+\.apps\.googleusercontent\.com',
 'Drive resource':r'drive\.google\.com/(?:drive/folders|file/d)/[A-Za-z0-9_-]{10,}',
 'email address':r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',
}

def verify(root):
    root=Path(root)
    files=subprocess.check_output(['git','-C',str(root),'ls-files','-z']).decode().split('\0')
    errors=[]
    for name in filter(None,files):
        if name not in ALLOWED:errors.append((name,'file outside public processor whitelist'));continue
        text=(root/name).read_text('utf8')
        for label,pattern in PATTERNS.items():
            if re.search(pattern,text):errors.append((name,label))
    meta=subprocess.check_output(['git','-C',str(root),'log','--all','--format=%an%n%ae%n%cn%n%ce']).decode().splitlines()
    for i,value in enumerate(meta):
        if i%4 in (1,3):
            if not value.endswith('@users.noreply.github.com'):errors.append(('history','non-generic author email'))
        elif value not in ('Sportage road data builder','github-actions[bot]','GitHub'):
            errors.append(('history','non-generic author name'))
    if errors:raise ValueError('Public source privacy check failed: '+repr(errors))
    return len([f for f in files if f])
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',default='.');a=p.parse_args()
    print('Verified public processor whitelist, credentials and generic history:',verify(a.root),'files')
