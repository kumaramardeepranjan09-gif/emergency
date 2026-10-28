#!/usr/bin/env python3
"""Build classic ESP32 on Linux x86_64 using official SHA256-verified releases.
Alternative to PlatformIO when its registry is unavailable. No TLS bypasses.
Requires Python, curl, git, make, a C compiler and requirements-dev.txt.
"""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
LOCAL=ROOT/'.local'

def run(args, **kwargs):
    subprocess.run([str(a) for a in args],check=True,**kwargs)

def verified_download(item, offline):
    url=item['url']; path=LOCAL/'downloads'/url.rsplit('/',1)[1]
    path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists():
        if offline:raise RuntimeError('Missing cached archive: '+path.name)
        partial=path.with_suffix(path.suffix+'.part')
        run(['curl','-fsSL','--retry','2','--max-time','240',url,'-o',partial])
        partial.replace(path)
    digest=hashlib.sha256()
    with path.open('rb') as f:
        while chunk:=f.read(1024*1024):digest.update(chunk)
    if digest.hexdigest()!=item['sha256']:
        raise RuntimeError('SHA256 verification failed; archive will NOT be used: '+path.name)
    print('Verified SHA256:',path.name,flush=True)
    return path

def extract_tar(archive,dest):
    dest.mkdir(parents=True,exist_ok=True)
    with tarfile.open(archive) as tf:
        if sys.version_info >= (3,12):tf.extractall(dest,filter='data')
        else:
            for member in tf.getmembers():
                if not (dest/member.name).resolve().is_relative_to(dest.resolve()):raise ValueError('Unsafe archive path')
            tf.extractall(dest)

def checkout(url,commit,dest,offline):
    if dest.exists():
        actual=subprocess.check_output(['git','-C',str(dest),'rev-parse','HEAD'],text=True).strip()
        if actual!=commit:raise RuntimeError('Unexpected cached dependency commit: '+str(dest))
        # A configured Ctags build generates local files; do not reset them.
        return
    if offline:raise RuntimeError('Missing dependency checkout: '+str(dest))
    dest.parent.mkdir(parents=True,exist_ok=True)
    run(['git','init','-q',dest])
    run(['git','-C',dest,'fetch','-q','--depth','1',url,commit])
    run(['git','-C',dest,'checkout','-q','--detach',commit])

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--offline',action='store_true',help='Only use already verified cached dependencies')
    p.add_argument('--jobs',type=int,default=2)
    args=p.parse_args()
    if platform.system()!='Linux' or platform.machine() not in ('x86_64','amd64'):
        raise RuntimeError('This release lock targets Linux x86_64. Use PlatformIO on other systems.')
    if args.jobs<1:raise ValueError('--jobs must be positive')
    if not (ROOT/'firmware/include/secrets.h').exists():
        raise RuntimeError('Copy secrets.example.h to secrets.h and configure your AP password first.')
    import esptool  # verifies that Python uploader prerequisites are installed
    del esptool
    lock=json.loads((ROOT/'tools/esp32-toolchain-lock.json').read_text())
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        archives=list(pool.map(lambda item:verified_download(item,args.offline),lock))
    binaries=LOCAL/'bin';core=LOCAL/'arduino-user/hardware/espressif/esp32';tools=LOCAL/'esp-tools'
    if not (binaries/'arduino-cli').exists():extract_tar(archives[0],binaries)
    if not core.exists():
        with zipfile.ZipFile(archives[1]) as z:
            for name in z.namelist():
                if not (core.parent/name).resolve().is_relative_to(core.parent.resolve()):raise ValueError('Unsafe zip path')
            core.parent.mkdir(parents=True,exist_ok=True);z.extractall(core.parent)
        (core.parent/'esp32-2.0.17').rename(core)
    if not (tools/'xtensa-esp32-elf/bin/xtensa-esp32-elf-g++').exists():extract_tar(archives[2],tools)
    if not (tools/'esptool/esptool.py').exists():extract_tar(archives[3],tools)
    libraries=LOCAL/'arduino-user/libraries'
    checkout('https://github.com/PaulStoffregen/OneWire.git','72249e22ef9092b0750e303d266199965a89e500',libraries/'OneWire',args.offline)
    checkout('https://github.com/milesburton/Arduino-Temperature-Control-Library.git','4a0ccc11c5ba32a4ebf466d7706178c57a8ef61c',libraries/'DallasTemperature',args.offline)
    ctags=LOCAL/'upstream/ctags'
    checkout('https://github.com/arduino/ctags.git','abc8fca7499f44c725122881cd380a88c37abe0e',ctags,args.offline)
    if not (LOCAL/'ctags-install/bin/ctags').exists():
        with (LOCAL/'ctags-build.log').open('w') as log:
            run(['./configure','--prefix='+str(LOCAL/'ctags-install')],cwd=ctags,stdout=log,stderr=log)
            # Include glibc declarations before this older Ctags defines __unused__.
            run(['make','-j'+str(args.jobs),'CFLAGS=-O2 -include sys/cdefs.h'],cwd=ctags,stdout=log,stderr=log)
            run(['make','install','CFLAGS=-O2 -include sys/cdefs.h'],cwd=ctags,stdout=log,stderr=log)
    data=LOCAL/'arduino-data';data.mkdir(exist_ok=True)
    # Local sketchbook core is installed explicitly; no remote discovery/index is needed to compile.
    for name,key in [('package_index.json','packages'),('library_index.json','libraries')]:
        if not (data/name).exists():(data/name).write_text(json.dumps({key:[]}))
    config=LOCAL/'arduino.yaml'
    config.write_text('directories:\n  data: '+str(data)+'\n  downloads: '+str(LOCAL/'downloads')+'\n  user: '+str(LOCAL/'arduino-user')+'\n')
    run([sys.executable,ROOT/'tools/embed.py'])
    stage=LOCAL/'sketch/MotorGuard';stage.mkdir(parents=True,exist_ok=True)
    (stage/'MotorGuard.ino').write_text('// Application entry points are defined in main.cpp.\n')
    for source in ['firmware/src/main.cpp','firmware/include/dashboard.h','firmware/include/secrets.h']:
        shutil.copy2(ROOT/source,stage/Path(source).name)
    runtime_env=os.environ.copy()
    runtime_env['PATH']=str(Path(sys.executable).parent)+os.pathsep+runtime_env.get('PATH','')
    command=[binaries/'arduino-cli','--config-file',config,'compile','--fqbn','espressif:esp32:esp32','--build-path',LOCAL/'esp32-build','--jobs',str(args.jobs)]
    for name,value in [('tools.xtensa-esp32-elf-gcc.path',tools/'xtensa-esp32-elf'),('tools.esptool_py.path',tools/'esptool'),('runtime.tools.ctags.path',LOCAL/'ctags-install/bin')]:
        command+=['--build-property',name+'='+str(value)]
    run(command+[stage],env=runtime_env)
    binary=LOCAL/'esp32-build/MotorGuard.ino.bin'
    if not binary.exists() or not binary.stat().st_size:raise RuntimeError('Compiler produced no application image')
    print('Compiled application:',binary,flush=True)
    print('No board was flashed. Serial/MDNS/DFU discovery warnings are expected in this compile-only installation.',flush=True)
if __name__=='__main__':main()
