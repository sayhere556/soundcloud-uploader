'use strict';
const $ = id => document.getElementById(id);
let state = {accounts: [], jobs: [], demo: false}, selection = [], view = 'upload', editing = null, trackAccount = '', refreshInFlight = false;
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const account = () => $('account').value;
const pretty = value => value.replaceAll('_', ' ');
function notice(message, error=false) { $('notice').textContent=message; $('notice').className=error?'error':''; $('notice').hidden=false; }
async function api(path, options={}) {
  const response = await fetch(path, {...options, headers:{'X-SCM-Request':'1', ...(options.body && !(options.body instanceof FormData) ? {'Content-Type':'application/json'} : {}), ...options.headers}});
  const result = await response.json();
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Check the supplied fields and try again.');
  return result;
}
const empty = (text, icon='♫') => '<div class="empty"><span class="empty-icon">'+icon+'</span>'+escapeHTML(text)+'</div>';
function showView(name) {
  view=name;
  document.querySelectorAll('.view').forEach(el=>el.hidden=el.id!=='view-'+name);
  document.querySelectorAll('nav .nav').forEach(el=>el.classList.toggle('active',el.dataset.view===name));
  $('page-label').textContent={upload:'Upload music',queue:'Upload queue',tracks:'Your tracks',accounts:'Accounts'}[name];
  if(name==='tracks') loadTracks();
}
document.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>showView(button.dataset.view)));
function jobHTML(job, mini=false) {
  const scheduled = job.state==='queued' && job.scheduled > Date.now()/1000;
  const when = scheduled ? ' · '+new Date(job.scheduled*1000).toLocaleString() : '';
  const status = scheduled ? 'scheduled' : pretty(job.state);
  const body = '<div class="job-title">'+escapeHTML(job.title)+'</div><div class="job-sub">'+escapeHTML(job.account+when)+'</div>';
  const badge = '<span class="status '+escapeHTML(job.state)+'">'+escapeHTML(status)+'</span>';
  if(mini) return '<div class="mini-job">'+body+badge+'</div>';
  return '<div class="job"><div class="job-icon">♫</div><div class="job-main">'+body+(job.error?'<div class="job-error">'+escapeHTML(job.error)+'</div>':'')+'</div>'+badge+(job.state==='queued'?'<button class="secondary" data-cancel="'+escapeHTML(job.id)+'">Cancel</button>':'')+'</div>';
}
function renderState() {
  const current=account(), options=state.accounts.map(a=>'<option value="'+escapeHTML(a.name)+'">'+escapeHTML(a.name+' · '+a.username)+'</option>').join('');
  if($('account').innerHTML!==options) {
    $('account').innerHTML=options || '<option value="">No accounts connected</option>';
    if(state.accounts.some(a=>a.name===current)) $('account').value=current;
  }
  $('demo-banner').hidden=!state.demo;
  $('mode-label').textContent=state.demo?'Demo workspace · No SoundCloud uploads':'Private workspace · CLI + Web';
  const waiting=state.jobs.filter(j=>['queued','uploading'].includes(j.state));
  $('stat-accounts').textContent=state.accounts.length;
  $('stat-waiting').textContent=waiting.length;
  $('queue-count').textContent=waiting.length;
  $('stat-done').textContent=state.jobs.filter(j=>j.state==='succeeded').length;
  $('jobs').innerHTML=state.jobs.length?state.jobs.map(j=>jobHTML(j)).join(''):empty('Nothing queued yet. Add a track from Upload music.','☷');
  const recent=waiting.length?waiting:state.jobs;
  $('recent-jobs').innerHTML=recent.length?recent.slice(0,4).map(j=>jobHTML(j,true)).join(''):empty('A little quiet here. Your next upload will appear in this space.');
  $('accounts-list').innerHTML=state.accounts.map(a=>'<div class="card account-card"><div class="avatar">'+escapeHTML(a.name[0].toUpperCase())+'</div><h2>'+escapeHTML(a.username)+'</h2><p>'+escapeHTML(a.name)+' · '+(state.demo?'Sample account':'Connected')+'</p><button class="secondary" data-disconnect="'+escapeHTML(a.name)+'">Disconnect</button></div>').join('');
  $('connect-form').hidden=state.demo;
  $('connection-help').textContent=state.oauth_configured?'You’ll authorize access on SoundCloud. Credentials stay on the server.':'Before connecting: add your SoundCloud app client ID and secret to the server environment. Setup steps are in SC_MANAGER.md.';
}
async function refresh() {
  if(refreshInFlight) return;
  refreshInFlight=true;
  try {state=await api('/api/state');renderState();}
  catch(error){notice('Cannot reach the app. '+error.message,true);}
  finally{refreshInFlight=false;}
}
$('jobs').addEventListener('click', async event=>{
  const button=event.target.closest('[data-cancel]');if(!button)return;
  try{await api('/api/jobs/'+encodeURIComponent(button.dataset.cancel)+'/cancel',{method:'POST'});await refresh();}
  catch(error){notice(error.message,true);}
});
$('accounts-list').addEventListener('click',async event=>{
  const button=event.target.closest('[data-disconnect]');if(!button)return;
  if(!confirm('Disconnect '+button.dataset.disconnect+' from this app?'))return;
  try{await api('/api/accounts/'+encodeURIComponent(button.dataset.disconnect)+'/disconnect',{method:'POST'});await refresh();}
  catch(error){notice(error.message,true);}
});
$('connect-form').addEventListener('submit',async event=>{
  event.preventDefault();
  try{const result=await api('/api/accounts/connect',{method:'POST',body:JSON.stringify({name:new FormData(event.target).get('name')})});location.assign(result.url);}
  catch(error){notice(error.message,true);}
});
function renderSelection(){
  $('selected-files').innerHTML=selection.map((file,i)=>'<div class="file-chip">♫ <span>'+escapeHTML(file.name)+'</span><small>'+(file.size/1024/1024).toFixed(1)+' MB</small><button type="button" aria-label="Remove '+escapeHTML(file.name)+'" data-remove="'+i+'">×</button></div>').join('');
  $('title').disabled=selection.length>1;
}
function addFiles(files){selection.push(...Array.from(files));renderSelection();}
$('audio').addEventListener('change',event=>{addFiles(event.target.files);event.target.value='';});
$('selected-files').addEventListener('click',event=>{const button=event.target.closest('[data-remove]');if(button){selection.splice(Number(button.dataset.remove),1);renderSelection();}});
['dragenter','dragover'].forEach(type=>$('drop-zone').addEventListener(type,event=>{event.preventDefault();$('drop-zone').classList.add('drag');}));
['dragleave','drop'].forEach(type=>$('drop-zone').addEventListener(type,event=>{event.preventDefault();$('drop-zone').classList.remove('drag');}));
$('drop-zone').addEventListener('drop',event=>addFiles(event.dataTransfer.files));
function sendFile(form,file,position,total){
  return new Promise((resolve,reject)=>{
    const xhr=new XMLHttpRequest();xhr.open('POST','/api/uploads');xhr.setRequestHeader('X-SCM-Request','1');xhr.timeout=30*60*1000;
    xhr.upload.onprogress=event=>{if(event.lengthComputable){$('transfer-progress').value=event.loaded/event.total*100;$('transfer-label').textContent='Transferring '+position+'/'+total+': '+file.name;}};
    xhr.onload=()=>{let body;try{body=JSON.parse(xhr.responseText);}catch{reject(new Error('Upload response was interrupted. Check the queue before retrying.'));return;}if(xhr.status>=200&&xhr.status<300)resolve(body);else reject(new Error(typeof body.detail==='string'?body.detail:'Upload rejected. Check the file and fields.'));};
    xhr.onerror=xhr.ontimeout=()=>reject(new Error('Transfer interrupted. Check the queue before retrying this file.'));
    xhr.send(form);
  });
}
$('upload-form').addEventListener('submit',async event=>{
  event.preventDefault();
  if(!account()){notice('Connect an account first, then select it above.',true);showView('accounts');return;}
  if(!selection.length){notice('Choose at least one audio file.',true);return;}
  const form=event.target, input=new FormData(form), targetAccount=account(), batch=[...selection], cover=$('cover').files[0];
  if(cover&&cover.size>20*1024*1024){notice('Cover art must be 20 MB or smaller.',true);return;}
  $('submit-upload').disabled=true;$('transfer').hidden=false;
  let completed=0;
  try{
    for(const file of batch){
      const body=new FormData();
      ['description','genre','tags','sharing'].forEach(key=>body.append(key,input.get(key)||''));
      body.append('account',targetAccount);body.append('audio',file);
      body.append('title',batch.length===1?(input.get('title')||''):'');
      if(cover)body.append('artwork',cover);
      if(input.get('scheduled'))body.append('scheduled',new Date(input.get('scheduled')).toISOString());
      await sendFile(body,file,completed+1,batch.length);completed++;
      const index=selection.indexOf(file);if(index>=0)selection.splice(index,1);
      renderSelection();
    }
    notice(completed+' track'+(completed===1?'':'s')+' added to the '+(state.demo?'demo ':'')+'queue.');
    form.reset();showView('queue');
  }catch(error){notice(error.message+' '+completed+' file(s) were queued successfully.',true);}
  finally{$('submit-upload').disabled=false;$('transfer').hidden=true;await refresh();}
});
async function loadTracks(){
  const selected=account();trackAccount=selected;
  if(!selected){$('tracks').innerHTML=empty('Connect an account to see its tracks.');return;}
  $('tracks').innerHTML=empty('Loading tracks…');
  try{
    const data=await api('/api/tracks/'+encodeURIComponent(selected));
    if(selected!==account())return;
    $('tracks-label').textContent=selected+' · '+data.tracks.length+' tracks';
    $('tracks').innerHTML=data.tracks.length?data.tracks.map((track,i)=>'<div class="job"><div class="job-icon">♫</div><div class="job-main"><div class="job-title">'+escapeHTML(track.title)+'</div><div class="job-sub">'+escapeHTML(track.genre||'No genre')+' · '+Number(track.playback_count||0).toLocaleString()+' plays</div></div><span class="status">'+escapeHTML(track.sharing||'private')+'</span><div class="track-controls"><button class="secondary" data-edit="'+i+'">Edit</button></div></div>').join(''):empty(state.demo?'Try a sample upload. Finished demo tracks will appear here.':'No tracks on this account yet.');
    $('tracks').querySelectorAll('[data-edit]').forEach(button=>button.addEventListener('click',()=>{
      editing={account:selected,track:data.tracks[Number(button.dataset.edit)]};
      for(const name of ['title','description','genre','sharing'])$('edit-form').elements[name].value=editing.track[name]||(name==='sharing'?'private':'');
      $('edit-dialog').showModal();
    }));
  }catch(error){$('tracks').innerHTML=empty(error.message);notice(error.message,true);}
}
$('account').addEventListener('change',()=>{if(view==='tracks')loadTracks();});
$('refresh-tracks').addEventListener('click',loadTracks);
$('close-edit').addEventListener('click',()=>$('edit-dialog').close());
$('edit-form').addEventListener('submit',async event=>{
  event.preventDefault();if(!editing)return;
  const button=event.submitter;button.disabled=true;
  try{await api('/api/tracks/'+encodeURIComponent(editing.account)+'/'+encodeURIComponent(editing.track.urn||editing.track.id),{method:'PATCH',body:JSON.stringify(Object.fromEntries(new FormData(event.target)))});$('edit-dialog').close();notice('Track updated.');await loadTracks();}
  catch(error){$('edit-dialog').close();notice(error.message,true);}
  finally{button.disabled=false;}
});
$('demo-upload').addEventListener('click',()=>{
  const samples=44100, bytes=new ArrayBuffer(44+samples*2), data=new DataView(bytes);
  const text=(offset,value)=>{for(let i=0;i<value.length;i++)data.setUint8(offset+i,value.charCodeAt(i));};
  text(0,'RIFF');data.setUint32(4,36+samples*2,true);text(8,'WAVEfmt ');data.setUint32(16,16,true);data.setUint16(20,1,true);data.setUint16(22,1,true);data.setUint32(24,44100,true);data.setUint32(28,88200,true);data.setUint16(32,2,true);data.setUint16(34,16,true);text(36,'data');data.setUint32(40,samples*2,true);
  selection=[new File([bytes],'Midnight Sketch.wav',{type:'audio/wav'})];renderSelection();showView('upload');notice('A one-second silent WAV is ready. Add it to the demo queue to test the workflow.');
});
const login=new URLSearchParams(location.search).get('login');
if(login){notice(login==='success'?'Account connected.':'Connection did not complete. Start again from Accounts.',login!=='success');history.replaceState({},'',location.pathname);}
refresh();setInterval(refresh,2500);
