"""MIO/DNA layout, packing metadata and reversible in-place transactions."""
from pathlib import Path,PurePosixPath
import datetime,json,os,re,shutil,uuid
from sources import RomSource

RECEIPT='.mio_origin_patch.json'

class Layout(RomSource):
    def __init__(self,path):
        path=Path(str(path).strip().strip('"')).resolve()
        if not path.is_dir():raise ValueError('请选择已解包的 ROM 目录。')
        super().__init__(path)
        self.root=path
        self.double=(path/'system/system/etc').is_dir()
        self.prefix='files/' if (path/'files/system').is_dir() else ''

    def physical(self,canonical):
        p=PurePosixPath(canonical)
        if p.is_absolute() or '..' in p.parts or ':' in canonical:raise ValueError('Unsafe path')
        rel=canonical
        if self.double and p.parts[0]=='system':rel='system/'+rel
        path=self.root/self.prefix/rel
        if not path.resolve().is_relative_to(self.root):raise ValueError('路径越出解包目录：'+str(path))
        if path.is_symlink() or (path.exists() and getattr(path,'is_junction',lambda:False)()):
            raise ValueError('目标是符号链接/连接点：'+str(path))
        return path

    def relative(self,canonical):return self.physical(canonical).relative_to(self.root).as_posix()

    def native_original(self,key):
        receipt=self.root/RECEIPT
        if receipt.is_file():
            state=json.loads(receipt.read_text(encoding='utf8'))
            session=Path(state['session']);rel=self.relative(key)
            after=session/'after'/rel;before=session/'native_originals'/key
            if after.is_file() and before.is_file() and self.read(key)==after.read_bytes():return before.read_bytes()
        return self.read(key)


def file_spec(name):
    label='system_file';gid=0;mode='0644'
    if name=='system/bin/surfaceflinger':label='surfaceflinger_exec';gid=2000;mode='0755'
    elif name.startswith('system/lib64/'):label='system_lib_file'
    elif '/etc/selinux/' in name:label='sepolicy_file'
    elif name.startswith('vendor/etc/'):label='vendor_configs_file'
    elif name.startswith('vendor/'):label='vendor_file'
    elif name.startswith('odm/etc/'):label='vendor_configs_file'
    elif name.startswith('odm/'):label='vendor_file'
    return {'uid':0,'gid':gid,'mode':mode,'label':f'u:object_r:{label}:s0'}

def metadata(layout,payload):
    out={};specs={};reports=[]
    for part in sorted({p.split('/')[0] for p in payload}):
        fs_path=layout.root/'config'/f'{part}_fs_config'
        fc_path=layout.root/'config'/f'{part}_file_contexts'
        if not fs_path.is_file() or not fc_path.is_file():raise ValueError(f'缺少 {part} 的 MIO/DNA 打包 config')
        fs=fs_path.read_text(encoding='utf8').splitlines();fc=fc_path.read_text(encoding='utf8').splitlines()
        known={}
        for i,line in enumerate(fs):
            fields=line.split()
            if not fields or line.lstrip().startswith('#'):continue
            if len(fields)<4 or not all(v.isdecimal() for v in fields[1:3]) or not re.fullmatch('[0-7]{3,4}',fields[3]):
                raise ValueError(f'fs_config 格式不支持：{fs_path}:{i+1}')
            known.setdefault(fields[0].rstrip('/'),[]).append(i)
        for i,line in enumerate(fc):
            fields=line.split()
            if not fields or line.lstrip().startswith('#'):continue
            if len(fields) not in (2,3) or not fields[-1].startswith('u:object_r:'):
                raise ValueError(f'file_contexts 格式不支持：{fc_path}:{i+1}')
        double=part=='system' and any(k.startswith('system/system/') for k in known)
        canonical={p:False for p in payload if p.startswith(part+'/')}
        for p in list(canonical):
            parent=PurePosixPath(p).parent
            while len(parent.parts)>1:
                if not layout.physical(str(parent)).exists():canonical.setdefault(str(parent),True)
                parent=parent.parent
        for name,isdir in sorted(canonical.items()):
            key=('system/'+name) if double else name
            rows=known.get(key,[])
            if len(rows)>1:raise ValueError('重复 fs_config 项：'+key)
            spec=file_spec(name)
            if isdir:spec['mode']='0755'
            # Existing SELinux paths retain their actual policy-file labels.
            expression=re.escape('/'+key)
            hits=[i for i,l in enumerate(fc) if l.split() and l.split()[0]==expression]
            if len(hits)>1:raise ValueError('重复精确 file_contexts 项：'+key)
            if hits and '/etc/selinux/' in name:spec['label']=fc[hits[0]].split()[-1]
            fields=fs[rows[0]].split() if rows else [key,'0','0','0644']
            fields[1:4]=[str(spec['uid']),str(spec['gid']),spec['mode']]
            if rows:fs[rows[0]]=' '.join(fields)
            else:known[key]=[len(fs)];fs.append(' '.join(fields))
            line=expression+' '+spec['label']
            if hits:fc[hits[0]]=line
            else:fc.append(line)
            specs[name]=dict(spec,directory=isdir,packing_key=key)
        out[f'config/{part}_fs_config']=('\n'.join(fs)+'\n').encode()
        out[f'config/{part}_file_contexts']=('\n'.join(fc)+'\n').encode()
        reports.append({'partition':part,'files':sum(p.startswith(part+'/') for p in payload),
                        'system_double_prefix':double})
    return out,specs,reports

def atomic_write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.mio-'+uuid.uuid4().hex+'.tmp')
    try:
        with temp.open('xb') as out:out.write(data);out.flush();os.fsync(out.fileno())
        os.replace(temp,path)
    finally:
        if temp.exists():temp.unlink()

def new_session(layout):
    root=layout.root.parent/(layout.root.name+'_MIO_Backups')
    if root.resolve().is_relative_to(layout.root):raise ValueError('Backup must be outside ROM')
    folder=root/datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    folder.mkdir(parents=True,exist_ok=False)
    return folder

def restore(session,log=print):
    session=Path(session).resolve();state=json.loads((session/'TRANSACTION.json').read_text(encoding='utf8'))
    layout=Layout(state['target']);root=layout.root
    for rel in reversed(state['written']):
        path=root/rel
        if not path.resolve().is_relative_to(root):raise ValueError('Rollback escapes ROM')
        before=session/'before'/rel
        if before.is_file():atomic_write(path,before.read_bytes())
        elif rel in state['absent'] and path.is_file():path.unlink()
    for rel in sorted(state.get('created_dirs',[]),key=len,reverse=True):
        path=root/rel
        if path.resolve().is_relative_to(root) and path.is_dir() and not any(path.iterdir()):path.rmdir()
    state['status']='restored';atomic_write(session/'TRANSACTION.json',json.dumps(state,ensure_ascii=False,indent=2).encode())
    log('已恢复至本次 PATCH 前：'+str(root))

def commit(layout,session,physical_files,report,fail_after=None):
    state={'target':str(layout.root),'session':str(session),'status':'prepared','written':[], 'absent':[], 'created_dirs':[]}
    payload=dict(physical_files)
    receipt={'version':1,'session':str(session),'changed_partitions':report['changed_partitions']}
    payload[RECEIPT]=(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n').encode()
    for rel,data in payload.items():
        path=layout.root/rel
        if not path.resolve().is_relative_to(layout.root) or path.is_symlink():raise ValueError('写入路径越界：'+rel)
        if path.exists():
            backup=session/'before'/rel;backup.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,backup)
        else:state['absent'].append(rel)
        after=session/'after'/rel;after.parent.mkdir(parents=True,exist_ok=True);after.write_bytes(data)
    journal=session/'TRANSACTION.json'
    atomic_write(journal,json.dumps(state,ensure_ascii=False,indent=2).encode())
    try:
        state['status']='applying'
        for rel,data in payload.items():
            path=layout.root/rel;parent=path.parent
            while parent!=layout.root and not parent.exists():
                item=parent.relative_to(layout.root).as_posix()
                if item not in state['created_dirs']:state['created_dirs'].append(item)
                parent=parent.parent
            # Journal first so an interrupted atomic replacement can be restored.
            state['written'].append(rel)
            atomic_write(journal,json.dumps(state,ensure_ascii=False,indent=2).encode())
            atomic_write(path,data)
            if fail_after and len(state['written'])==fail_after:raise OSError('Injected transaction failure')
        state['status']='complete';atomic_write(journal,json.dumps(state,ensure_ascii=False,indent=2).encode())
    except BaseException:
        restore(session,log=lambda _:None)
        raise
