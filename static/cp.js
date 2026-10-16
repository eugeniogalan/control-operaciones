/* Domicilio MX: Estado/Municipio en listas (municipio filtrado por estado) y autollenado por Código Postal
   con lista de colonias del CP (catálogo SEPOMEX local, /api/cp y /api/municipios). Siempre hay opción "Otra…" de texto libre.
   Uso: <div data-cpmx data-cp="cp" data-estado="estado" data-municipio="municipio" data-colonia="colonia"> (nombres de campos; cualquiera opcional) */
(function(){
var OTRA='__otra__', cacheMun={};
function get(u){return fetch(u,{credentials:'same-origin'}).then(function(r){return r.ok?r.json():null;}).catch(function(){return null;});}
function combo(inp,ph){ // select delante del input original; el input conserva el name y es lo que se envía
  if(inp._combo)return inp._combo;
  var s=document.createElement('select');s.className='cpmx-sel';s.style.marginTop='4px';
  inp.parentNode.insertBefore(s,inp);
  var c={sel:s,inp:inp,lista:[],
    set:function(lista,valor){this.lista=lista||[];var v=valor===undefined?inp.value:valor;
      s.innerHTML='';var o=document.createElement('option');o.value='';o.textContent=ph;s.appendChild(o);
      this.lista.forEach(function(x){var o=document.createElement('option');o.value=x;o.textContent=x;s.appendChild(o);});
      o=document.createElement('option');o.value=OTRA;o.textContent='Otra… (escribir)';s.appendChild(o);
      if(!this.lista.length){this.libre(true);inp.value=v||'';return;}
      if(v&&this.lista.indexOf(v)<0){s.value=OTRA;this.libre(true);inp.value=v;}else{s.value=v||'';inp.value=v||'';this.libre(false);}},
    libre:function(on){s.style.display=this.lista.length?'':'none';inp.style.display=on||!this.lista.length?'':'none';if(on&&this.lista.length)inp.placeholder='Escribe '+ph.replace(/[—\s]/g,'').toLowerCase();}};
  s.addEventListener('change',function(){if(s.value===OTRA){c.libre(true);inp.value='';inp.focus();}else{inp.value=s.value;c.libre(false);}inp.dispatchEvent(new Event('change',{bubbles:true}));});
  inp._combo=c;return c;}
function municipios(est){if(!est)return Promise.resolve([]);if(cacheMun[est])return Promise.resolve(cacheMun[est]);
  return get('/api/municipios/'+encodeURIComponent(est)).then(function(j){return cacheMun[est]=(j&&j.municipios)||[];});}
function init(box){
  var f=function(n){var k=box.dataset[n];return k?box.querySelector('[name="'+k+'"]'):null;};
  var cp=f('cp'),es=f('estado'),mu=f('municipio'),co=f('colonia'),msg=null;
  var ce=null;
  if(es&&es.tagName!=='SELECT')ce=combo(es,'— Estado —');
  var cm=mu?combo(mu,'— Municipio / Alcaldía —'):null, cc=co?combo(co,'— Colonia —'):null;
  if(cc)cc.set([]);
  function estVal(){return es?es.value:'';}
  function cargarMun(valor){if(!cm)return Promise.resolve();return municipios(estVal()).then(function(l){cm.set(l,valor);});}
  if(es)es.addEventListener('change',function(){if(cm)cargarMun('');});
  if(cp){msg=document.createElement('div');msg.className='muted';msg.style.fontSize='12px';cp.parentNode.appendChild(msg);cp.setAttribute('inputmode','numeric');cp.maxLength=5;}
  function porCP(inicial){var v=(cp.value||'').replace(/\D/g,'');if(v.length!==5){if(!inicial&&cc)cc.set([],co.value);msg.textContent='';return;}
    msg.textContent='Buscando CP…';
    get('/api/cp/'+v).then(function(r){
      if(!r){msg.textContent='CP no encontrado en el catálogo SEPOMEX; captura estado, municipio y colonia manualmente.';if(cc)cc.set([],co.value);return;}
      msg.textContent='✓ '+r.municipio+', '+r.estado+' · '+r.colonias.length+' colonia(s)';
      if(es){if(es.tagName==='SELECT')es.value=r.estado;else if(ce)ce.set(ce.lista,r.estado);}
      cargarMun(inicial&&mu.value?mu.value:r.municipio);
      if(cc)cc.set(r.colonias,inicial?co.value:(r.colonias.length===1?r.colonias[0]:(r.colonias.indexOf(co.value)>=0?co.value:'')));});}
  if(cp){cp.addEventListener('input',function(){porCP(false);});}
  // estado inicial (el select de Sites ya trae valor) -> municipios; luego CP existente -> colonias
  Promise.resolve(ce?get('/api/estados').then(function(j){ce.set((j&&j.estados)||[]);}):null).then(function(){return cargarMun(mu?mu.value:'');}).then(function(){if(cp&&cp.value)porCP(true);});
}
function arrancar(){document.querySelectorAll('[data-cpmx]').forEach(init);}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',arrancar);else arrancar();
})();
