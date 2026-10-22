"""Rock-only -j8 build supervisor for the approved 30 GiB task directory.

Requires the existing OpenWrt prerequisites; installs no software. Run only after
reviewing the fixed work path. The current build must finish before another run.
Copy existing native-build.log/state files aside before a deliberate next run.
"""
import pathlib,subprocess,time,os,signal,json,datetime,traceback,fcntl
w=pathlib.Path('/srv/alwayroute/openwrt-build')

def refuse_active_make():
 for proc in pathlib.Path('/proc').iterdir():
  if not proc.name.isdecimal():continue
  try:
   if (proc/'comm').read_text().strip()=='make' and (proc/'cwd').resolve(strict=True)==w/'source':
    raise SystemExit('Refusing to start: make PID '+proc.name+' is already active in this source directory')
  except (FileNotFoundError,ProcessLookupError,PermissionError):continue

# First check is read-only, including when taking over an older supervisor that
# predates this lock. The second closes the race between two guarded starts.
refuse_active_make()
lock=(w/'.native-build.lock').open('a')
try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
except BlockingIOError:raise SystemExit('Refusing to start: another build supervisor holds the task lock')
refuse_active_make()
statefile=w/'native-build-state.json';begin=time.monotonic();p=None
with (w/'native-build.log').open('wb') as log:
 try:
  p=subprocess.Popen(['make','-j8','V=s'],cwd=w/'source',stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,env={**os.environ,'TMPDIR':str(w/'tmp'),'CMAKE_BUILD_PARALLEL_LEVEL':'8'})
  state={'pid':p.pid,'monitor_pid':os.getpid(),'started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'command':['make','-j8','V=s'],'disk_limit_bytes':30*1024**3,'status':'running','incremental':True}
  while p.poll() is None:
   d=subprocess.run(['du','-sb',str(w)],capture_output=True,text=True,timeout=60)
   if d.returncode not in (0,1) or not d.stdout.strip():raise RuntimeError('No valid workspace size measurement')
   size=int(d.stdout.split()[0]);state.update(elapsed_seconds=round(time.monotonic()-begin),workspace_bytes=size,last_check_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
   tmp=statefile.with_suffix('.json.tmp');tmp.write_text(json.dumps(state,indent=2)+'\n');tmp.replace(statefile)
   if size>state['disk_limit_bytes'] or time.monotonic()-begin>7200:
    state['stop_reason']='budget guard';os.killpg(p.pid,signal.SIGTERM);p.wait(timeout=20);break
   try:p.wait(timeout=20)
   except subprocess.TimeoutExpired:pass
  rc=p.wait();state.update(status='succeeded' if rc==0 else 'failed',returncode=rc,elapsed_seconds=round(time.monotonic()-begin,3),image_inspection_required=True);statefile.write_text(json.dumps(state,indent=2)+'\n');print(json.dumps(state),flush=True)
 except BaseException:
  if p and p.poll() is None:
   try:os.killpg(p.pid,signal.SIGTERM);p.wait(timeout=15)
   except Exception:os.killpg(p.pid,signal.SIGKILL)
  statefile.write_text(json.dumps({'status':'supervisor_failed_build_stopped','error':traceback.format_exc()},indent=2)+'\n');raise
