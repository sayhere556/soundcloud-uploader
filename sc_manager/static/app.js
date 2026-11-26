'use strict';
const $=id=>document.getElementById(id);
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const clamp=value=>Math.min(1,Math.max(0,value));
let state=null, files=[], tape=false, art={source:'none',color:'#000000',asset:'',url:'',fit:'crop',fill:'#ffffff',zoom:1,x:.5,y:.5};
let activeSubmission=null, defaultArtDraft=null, disconnectTarget=null, accountSignature='';
let sourceImage=null, loadedAsset='', ready=false, busy=false, submissionId=null, refreshing=false;
function message(text,error=false){$('notice').textContent=text;$('notice').className=error?'error':'';$('notice').hidden=false;}
async function api(path,options={}){
 const response=await fetch(path,{...options,headers:{'X-SCM-Request':'1',...(options.body&&!(options.body instanceof FormData)?{'Content-Type':'application/json'}:{}),...options.headers}});
 const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'Check the supplied fields.');return data;
}
function setMode(value){if(busy)return;tape=value;$('singles-mode').setAttribute('aria-pressed',String(!tape));$('tape-mode').setAttribute('aria-pressed',String(tape));$('tape-details').hidden=!tape;renderFiles();}
$('singles-mode').onclick=()=>setMode(false);$('tape-mode').onclick=()=>setMode(true);
function renderFiles(){
 $('file-list').innerHTML=files.map((item,i)=>'<li class="file-row"><span class="file-number">'+String(i+1).padStart(2,'0')+'</span><div><input class="file-title" data-title="'+i+'" value="'+esc(item.title)+'" maxlength="200" aria-label="Title for track '+(i+1)+'"><div class="filename">'+esc(item.file.name)+' · '+(item.file.size/1024/1024).toFixed(1)+' MB</div></div><div class="row-actions">'+(tape?'<button data-move="'+i+'" data-step="-1" '+(i===0?'disabled':'')+'>Earlier</button><button data-move="'+i+'" data-step="1" '+(i===files.length-1?'disabled':'')+'>Later</button>':'')+'<button class="remove" data-remove="'+i+'" aria-label="Remove track '+(i+1)+'">×</button></div></li>').join('');
 $('file-count').textContent=files.length?files.length+' TRACK'+(files.length===1?'':'S'):'NO FILES SELECTED';
 $('clear-files').hidden=!files.length;$('empty-list').hidden=!!files.length;
 $('upload-button').innerHTML=(tape?'Upload tape':'Upload tracks')+' <span id="upload-count">'+files.length+'</span>';
 $('upload-button').disabled=busy||!files.length;
}
function addFiles(list){
 if(busy)return;
 const accepted=Array.from(list).filter(file=>/\.(wav|wave|flac|mp3|aiff|aif|m4a|ogg)$/i.test(file.name)&&file.size>0&&file.size<=4*1024**3);
 if(accepted.length!==list.length)message('Some files were skipped. Use supported audio files between 1 byte and 4 GB.',true);
 if(files.length+accepted.length>100){message('A batch can contain up to 100 tracks.',true);return;}
 files.push(...accepted.map(file=>({file,title:file.name.replace(/\.[^.]+$/,''),asset:null})));submissionId=null;renderFiles();
}
$('audio-files').onchange=event=>{addFiles(event.target.files);event.target.value='';};
$('file-list').oninput=event=>{if(!busy&&event.target.dataset.title!==undefined)files[Number(event.target.dataset.title)].title=event.target.value;};
$('file-list').onclick=event=>{
 if(busy)return;const remove=event.target.closest('[data-remove]'),move=event.target.closest('[data-move]');
 if(remove){files.splice(Number(remove.dataset.remove),1);submissionId=null;renderFiles();}
 if(move){const from=Number(move.dataset.move),to=from+Number(move.dataset.step);if(to>=0&&to<files.length){[files[from],files[to]]=[files[to],files[from]];submissionId=null;renderFiles();}}
};
$('clear-files').onclick=()=>{if(!busy){files=[];submissionId=null;renderFiles();}};
['dragenter','dragover'].forEach(type=>$('drop').addEventListener(type,event=>{event.preventDefault();$('drop').classList.add('drag');}));
['dragleave','drop'].forEach(type=>$('drop').addEventListener(type,event=>{event.preventDefault();$('drop').classList.remove('drag');}));
$('drop').addEventListener('drop',event=>{if(!busy)addFiles(event.dataTransfer.files);});
function geometry(){
 if(!sourceImage)return null;
 const width=sourceImage.naturalWidth,height=sourceImage.naturalHeight,size=3000;
 const scale=(art.fit==='crop'?Math.max(size/width,size/height):Math.min(size/width,size/height))*art.zoom;
 return {width:Math.round(width*scale),height:Math.round(height*scale)};
}
function drawArt(){
 const canvas=$('art-preview'),ctx=canvas.getContext('2d');
 if(art.source==='none'){ctx.fillStyle='#efefeb';ctx.fillRect(0,0,3000,3000);ctx.fillStyle='#aaa';ctx.font='90px Arial';ctx.textAlign='center';ctx.fillText('No artwork',1500,1515);$('preview-tag').textContent='NOT ATTACHED';return;}
 ctx.fillStyle=art.source==='solid'?art.color:art.fill;ctx.fillRect(0,0,3000,3000);
 const geom=geometry();if(art.source!=='solid'&&sourceImage&&geom){ctx.imageSmoothingQuality='high';ctx.drawImage(sourceImage,Math.round((3000-geom.width)*art.x),Math.round((3000-geom.height)*art.y),geom.width,geom.height);}
 $('preview-tag').textContent=art.source==='solid'?'SOLID COLOR':(sourceImage?(art.fit==='crop'?'CROPPED IMAGE':'IMAGE + COLOR FILL'):'LOAD AN IMAGE');
}
async function loadAsset(){
 if(!art.asset){sourceImage=null;loadedAsset='';drawArt();return;}
 if(loadedAsset===art.asset){drawArt();return;}
 const selected=art.asset,image=new Image();
 image.onload=()=>{if(art.asset!==selected)return;sourceImage=image;loadedAsset=selected;drawArt();};
 image.onerror=()=>{sourceImage=null;loadedAsset='';drawArt();message('Artwork could not load. Choose the image again.',true);};
 image.src='/api/artwork/'+encodeURIComponent(selected);
}
const palette=['#000000','#ffffff','#6e5191'];
function preset(value){return palette.includes(value.toLowerCase())?value.toLowerCase():'custom';}
function renderArtControls(){
 $('art-source').value=art.source;
 $('solid-controls').hidden=art.source!=='solid';$('image-controls').hidden=art.source!=='file';$('pinterest-controls').hidden=art.source!=='pinterest';$('crop-controls').hidden=!['file','pinterest'].includes(art.source);$('no-art-note').hidden=art.source!=='none';
 $('color-preset').value=preset(art.color);$('fill-preset').value=preset(art.fill);$('custom-color').hidden=preset(art.color)!=='custom';$('custom-fill').hidden=preset(art.fill)!=='custom';
 $('solid-color').value=art.color;$('solid-hex').value=art.color;$('fill-color').value=art.fill;$('fill-hex').value=art.fill;$('fit').value=art.fit;$('zoom').value=art.zoom;$('crop-x').value=art.x;$('crop-y').value=art.y;$('zoom-value').textContent=Number(art.zoom).toFixed(2)+'×';$('pin-url').value=art.url;
 if(['file','pinterest'].includes(art.source))loadAsset();drawArt();
}
$('art-source').onchange=event=>{art.source=event.target.value;renderArtControls();};
for(const [id,field,custom] of [['color-preset','color','custom-color'],['fill-preset','fill','custom-fill']])$(id).onchange=event=>{
 $(custom).hidden=event.target.value!=='custom';if(event.target.value!=='custom'){art[field]=event.target.value;renderArtControls();}
};
for(const [id,field] of [['solid-color','color'],['solid-hex','color'],['fill-color','fill'],['fill-hex','fill']])$(id).addEventListener('input',event=>{if(/^#[0-9a-fA-F]{6}$/.test(event.target.value)){art[field]=event.target.value;$(field==='color'?'solid-color':'fill-color').value=art[field];$(field==='color'?'solid-hex':'fill-hex').value=art[field];drawArt();}});
$('fit').onchange=event=>{art.fit=event.target.value;drawArt();};
for(const [id,field] of [['zoom','zoom'],['crop-x','x'],['crop-y','y']])$(id).oninput=event=>{art[field]=Number(event.target.value);$('zoom-value').textContent=art.zoom.toFixed(2)+'×';drawArt();};
$('reset-crop').onclick=()=>{art.zoom=1;art.x=.5;art.y=.5;renderArtControls();};
let drag=null;
$('art-preview').onpointerdown=event=>{if(!['file','pinterest'].includes(art.source)||!sourceImage)return;const g=geometry();drag={x:event.clientX,y:event.clientY,startX:art.x,startY:art.y,g};event.target.setPointerCapture(event.pointerId);};
$('art-preview').onpointermove=event=>{if(!drag)return;const ratio=3000/event.target.getBoundingClientRect().width,dx=3000-drag.g.width,dy=3000-drag.g.height;if(Math.abs(dx)>1)art.x=clamp(drag.startX+(event.clientX-drag.x)*ratio/dx);if(Math.abs(dy)>1)art.y=clamp(drag.startY+(event.clientY-drag.y)*ratio/dy);$('crop-x').value=art.x;$('crop-y').value=art.y;drawArt();};
$('art-preview').onpointerup=$('art-preview').onpointercancel=()=>{drag=null;};
$('art-file').onchange=async event=>{
 const file=event.target.files[0];if(!file)return;
 const body=new FormData();body.append('image',file);
 try{const result=await api('/api/artwork',{method:'POST',body});art.asset=result.asset;art.source='file';art.url='';art.zoom=1;art.x=.5;art.y=.5;renderArtControls();}
 catch(error){message(error.message,true);}finally{event.target.value='';}
};
$('load-pin').onclick=async()=>{
 const button=$('load-pin');button.disabled=true;button.textContent='Loading…';
 try{const url=$('pin-url').value.trim(),result=await api('/api/pinterest',{method:'POST',body:JSON.stringify({url})});art.asset=result.asset;art.url=url;art.source='pinterest';art.zoom=1;art.x=.5;art.y=.5;renderArtControls();}
 catch(error){message(error.message,true);}finally{button.disabled=false;button.textContent='Load image';}
};
function visibilityNote(){$('visibility-note').textContent=$('visibility').value==='private'?'Only you can hear private uploads.':'These tracks will be public on SoundCloud.';}
$('visibility').onchange=visibilityNote;
function dialogMessage(id,text,error=false){const target=$(id);target.textContent=text;target.className='dialog-notice'+(error?' error':'');target.hidden=false;}
function defaultControls(){
 const source=$('default-source').value;$('default-solid').hidden=source!=='solid';$('default-image').hidden=!['file','pinterest'].includes(source);
 $('default-custom-color').hidden=$('default-color').value!=='custom';$('default-custom-fill').hidden=$('default-fill').value!=='custom';
}
for(const id of ['default-source','default-color','default-fill'])$(id).onchange=defaultControls;
$('defaults-button').onclick=()=>{
 if(!state)return;defaultArtDraft=structuredClone(state.defaults.art);$('defaults-notice').hidden=true;
 $('default-account').innerHTML='<option value="">Choose when uploading</option>'+state.accounts.map(a=>'<option value="'+esc(a.name)+'">'+esc(a.label||a.name)+'</option>').join('');
 $('default-account').value=state.defaults.account||'';$('default-visibility').value=state.defaults.visibility;$('default-source').value=defaultArtDraft.source;
 $('default-color').value=preset(defaultArtDraft.color);$('default-custom-color').value=defaultArtDraft.color;$('default-fit').value=defaultArtDraft.fit;$('default-fill').value=preset(defaultArtDraft.fill);$('default-custom-fill').value=defaultArtDraft.fill;
 defaultControls();$('defaults-dialog').showModal();
};
$('defaults-form').onsubmit=async event=>{
 event.preventDefault();const source=$('default-source').value;
 let selected=structuredClone(defaultArtDraft);
 if(['file','pinterest'].includes(source)){
  if(art.source===source&&art.asset)selected=structuredClone(art);
  else if(selected.source!==source||!selected.asset){dialogMessage('defaults-notice','Choose and load this image in the artwork panel first.',true);return;}
 }
 selected.source=source;selected.color=$('default-color').value==='custom'?$('default-custom-color').value:$('default-color').value;
 selected.fit=$('default-fit').value;selected.fill=$('default-fill').value==='custom'?$('default-custom-fill').value:$('default-fill').value;
 if(source==='none'||source==='solid'){selected.asset='';selected.url='';}
 try{state.defaults=await api('/api/defaults',{method:'POST',body:JSON.stringify({account:$('default-account').value,visibility:$('default-visibility').value,art:selected})});
 art=structuredClone(state.defaults.art);$('visibility').value=state.defaults.visibility;if(state.defaults.account)$('account').value=state.defaults.account;renderArtControls();visibilityNote();$('defaults-dialog').close();message('Defaults saved.');}
 catch(error){dialogMessage('defaults-notice',error.message,true);}
};
$('accounts-button').onclick=()=>{$('account-notice').hidden=true;$('accounts-dialog').showModal();};
document.querySelectorAll('[data-close]').forEach(button=>button.onclick=()=>$(button.dataset.close).close());
async function linkAccount(name){
 if(!state?.connection.configured){$('connection-settings').open=true;dialogMessage('account-notice','Add your SoundCloud app credentials below to enable linking.',true);$('client-id').focus();return;}
 $('auth-link').hidden=true;
 try{const data=await api('/api/accounts/connect',{method:'POST',body:JSON.stringify({name})});$('auth-link').href=data.url;$('auth-link').hidden=false;dialogMessage('account-notice','Your link is ready. Continue to SoundCloud below, approve the account, then return here.');$('auth-link').focus();}
 catch(error){dialogMessage('account-notice',error.message,true);}
}
$('connect-form').onsubmit=async event=>{event.preventDefault();await linkAccount($('account-name').value.trim());};
$('connection-form').onsubmit=async event=>{
 event.preventDefault();const button=event.target.querySelector('button');button.disabled=true;
 try{await api('/api/connection',{method:'POST',body:JSON.stringify({client_id:$('client-id').value,client_secret:$('client-secret').value,redirect_uri:$('callback-input').value})});$('client-id').value='';$('client-secret').value='';await refresh();$('connection-settings').open=false;dialogMessage('account-notice','Connection settings saved. You can now link an account.');}
 catch(error){dialogMessage('account-notice',error.message,true);}finally{button.disabled=false;}
};
$('account-list').onclick=async event=>{
 const reconnect=event.target.closest('[data-reconnect]'),label=event.target.closest('[data-save-label]'),disconnect=event.target.closest('[data-disconnect]');
 if(reconnect){await linkAccount(reconnect.dataset.reconnect);return;}
 if(label){try{const name=label.dataset.saveLabel;await api('/api/accounts/'+encodeURIComponent(name)+'/label',{method:'POST',body:JSON.stringify({label:document.getElementById('label-'+name).value})});await refresh();dialogMessage('account-notice','Account label saved.');}catch(error){dialogMessage('account-notice',error.message,true);}}
 if(disconnect){disconnectTarget=disconnect.dataset.disconnect;$('disconnect-description').textContent='Disconnect '+disconnectTarget+' from this app? Your SoundCloud tracks and playlists stay on SoundCloud.';$('disconnect-dialog').showModal();}
};
$('disconnect-confirm').onclick=async()=>{
 if(!disconnectTarget)return;const button=$('disconnect-confirm');button.disabled=true;
 try{await api('/api/accounts/'+encodeURIComponent(disconnectTarget)+'/disconnect',{method:'POST'});$('disconnect-dialog').close();await refresh();dialogMessage('account-notice','Account disconnected.');}
 catch(error){$('disconnect-dialog').close();dialogMessage('account-notice',error.message,true);}finally{button.disabled=false;disconnectTarget=null;}
};
async function refresh(){
 if(refreshing)return;refreshing=true;
 try{const updated=await api('/api/state'),current=$('account').value;state=updated;
 const signature=JSON.stringify(state.accounts);
 if(signature!==accountSignature){accountSignature=signature;
 $('account').innerHTML=state.accounts.map(a=>'<option value="'+esc(a.name)+'">'+esc((a.label||a.name)+' / '+a.username)+'</option>').join('')||'<option value="">Link an account</option>';
 if(state.accounts.some(a=>a.name===current))$('account').value=current;else if(state.accounts.some(a=>a.name===state.defaults.account))$('account').value=state.defaults.account;
 $('account-list').innerHTML=state.accounts.map(a=>'<div class="account-row"><small>'+esc(a.username)+' · '+esc(a.name)+'</small><div class="account-edit"><input id="label-'+esc(a.name)+'" value="'+esc(a.label||a.name)+'" maxlength="60" aria-label="Label for '+esc(a.name)+'"><button class="outline" data-save-label="'+esc(a.name)+'">Save label</button></div><div class="account-actions"><button class="quiet" data-reconnect="'+esc(a.name)+'">Reconnect</button><button class="quiet" data-disconnect="'+esc(a.name)+'">Disconnect</button></div></div>').join('')||'<p class="help">No accounts linked yet.</p>';
 }
 $('connect-help').textContent=state.connection.configured?'Authorize on SoundCloud, then return here.':'Add your SoundCloud app credentials in Connection settings first.';
 $('connection-note').textContent=state.connection.configured?'Your SoundCloud app is configured.':'One-time setup for your SoundCloud app.';
 $('connection-form').hidden=state.connection.managed_by_environment;$('callback-display').textContent=state.connection.redirect_uri;
 if(!ready){ready=true;art=structuredClone(state.defaults.art);$('visibility').value=state.defaults.visibility;$('callback-input').value=state.connection.redirect_uri;$('connection-settings').open=!state.connection.configured;renderArtControls();visibilityNote();}
 if(activeSubmission){const progress=await api('/api/submissions/'+encodeURIComponent(activeSubmission));
  $('transfer-text').textContent=progress.completed+'/'+progress.total+' tracks uploaded'+(progress.playlist?' · creating one playlist':'');$('transfer-progress').value=progress.completed/progress.total*100;$('transfer-percent').textContent=Math.round(progress.completed/progress.total*100)+'%';
  if(progress.state==='succeeded'||progress.state==='needs_review'){activeSubmission=null;busy=false;$('transfer').hidden=true;message(progress.state==='succeeded'?(progress.playlist?'Tape uploaded. Playlist created.':'Upload complete.'):(progress.error||'Check SoundCloud before retrying.'),progress.state!=='succeeded');renderFiles();}
 }
 }catch(error){message('Could not reach the upload desk. '+error.message,true);}finally{refreshing=false;}
}
function transfer(item,index,total){return new Promise((resolve,reject)=>{const xhr=new XMLHttpRequest(),body=new FormData();body.append('audio',item.file);xhr.open('POST','/api/stage');xhr.setRequestHeader('X-SCM-Request','1');xhr.timeout=30*60*1000;xhr.upload.onprogress=event=>{if(event.lengthComputable){const percent=Math.round(event.loaded/event.total*100);$('transfer-progress').value=percent;$('transfer-percent').textContent=percent+'%';$('transfer-text').textContent='Preparing '+index+'/'+total+': '+item.file.name;}};xhr.onload=()=>{let data;try{data=JSON.parse(xhr.responseText);}catch{return reject(new Error('Transfer response interrupted. Try again.'));}if(xhr.status>=200&&xhr.status<300)resolve(data.asset);else reject(new Error(typeof data.detail==='string'?data.detail:'The file could not be staged.'));};xhr.onerror=xhr.ontimeout=()=>reject(new Error('File transfer interrupted. Try again.'));xhr.send(body);});}
$('upload-button').onclick=async()=>{
 if(busy)return;if(!$('account').value){$('accounts-dialog').showModal();return;}if(!files.length){message('Add at least one audio file.',true);return;}if(tape&&!$('tape-title').value.trim()){message('Give this tape a title.',true);$('tape-title').focus();return;}if(files.some(item=>!item.title.trim())){message('Every track needs a title.',true);return;}if(['file','pinterest'].includes(art.source)&&!art.asset){message('Load an artwork image first.',true);return;}
 busy=true;$('upload-button').disabled=true;$('transfer').hidden=false;const batch=[...files],target=$('account').value,title=tape?$('tape-title').value.trim():'',visibility=$('visibility').value,cover=structuredClone(art);submissionId=submissionId||crypto.randomUUID();
 try{for(let i=0;i<batch.length;i++){if(!batch[i].asset)batch[i].asset=await transfer(batch[i],i+1,batch.length);}$('transfer-text').textContent='Adding to the upload queue';await api('/api/submit',{method:'POST',body:JSON.stringify({account:target,items:batch.map(item=>({asset:item.asset,title:item.title})),tape_title:title,visibility,art:cover,request_id:submissionId})});files=files.filter(item=>!batch.includes(item));activeSubmission=submissionId;submissionId=null;message(title?'Uploading tracks in order, then creating your playlist.':'Uploading to SoundCloud.');renderFiles();await refresh();}
 catch(error){message(error.message+' Your selection is kept so you can retry.',true);}
 finally{busy=!!activeSubmission;$('transfer').hidden=!activeSubmission;renderFiles();}
};
const login=new URLSearchParams(location.search).get('login');if(login){message(login==='success'?'Account linked. You can return to your original upload tab.':'Connection did not complete. Try again from Accounts.',login!=='success');history.replaceState({},'',location.pathname);}
renderFiles();renderArtControls();refresh();setInterval(refresh,2000);
