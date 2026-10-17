/* Editor por campos de plantillas de Reporte de evidencias: secciones, campos (nombre, tipo, obligatorio, grupo, opciones, ayuda) y tablas de materiales. */
function EvidEditor(S, TIPOS){
var box=document.getElementById('eds');
function el(t,a,h){var e=document.createElement(t);for(var k in a||{}){if(k==='class')e.className=a[k];else if(k==='text')e.textContent=a[k];else e.setAttribute(k,a[k]);}(h||[]).forEach(function(c){if(c)e.appendChild(c);});return e;}
function ib(txt,tit,fn,x){var b=el('button',{type:'button',class:'ib'+(x?' x':''),title:tit,text:txt});b.onclick=fn;return b;}
function mover(arr,i,d){var j=i+d;if(j<0||j>=arr.length)return;var t=arr[i];arr[i]=arr[j];arr[j]=t;pintar();}
function inp(v,ph,fn,cls){var e=el('input',{placeholder:ph||''});e.value=v||'';if(cls)e.className=cls;e.oninput=function(){fn(e.value);resumen();};return e;}
function btn(t,fn){var b=el('button',{type:'button',class:'btn sec',text:t});b.onclick=fn;return b;}
function campoRow(sc,c,i){
  var sel=el('select');TIPOS.forEach(function(t){var o=el('option',{value:t[0],text:t[1]});if(t[0]===c.tipo)o.selected=true;sel.appendChild(o);});
  var op=inp((c.opciones||[]).join(', '),'Opciones separadas por coma',function(v){c.opciones=v.split(',').map(function(x){return x.trim();}).filter(Boolean);});
  var gr=inp(c.grupo,'Grupo (p.ej. PUNTO A)',function(v){c.grupo=v;});
  var ay=inp(c.ayuda,'Texto de ayuda (opcional)',function(v){c.ayuda=v;});
  function vis(){op.style.display=c.tipo==='seleccion'?'':'none';gr.style.display=c.tipo==='foto'?'':'none';}
  sel.onchange=function(){c.tipo=sel.value;vis();resumen();};vis();
  var rq=el('input',{type:'checkbox'});rq.checked=!!c.req;rq.onchange=function(){c.req=rq.checked;};
  return el('div',{class:'ed-row'},[el('div',{class:'top'},[inp(c.nombre,'Nombre del campo',function(v){c.nombre=v;}),ib('▲','Subir',function(){mover(sc.campos,i,-1);}),ib('▼','Bajar',function(){mover(sc.campos,i,1);}),
      ib('✕','Quitar campo',function(){if(confirm('¿Quitar «'+(c.nombre||'campo')+'»?')){sc.campos.splice(i,1);pintar();}},1)]),
    el('div',{class:'meta'},[sel,el('label',{},[rq,document.createTextNode('Obligatorio')]),gr,op,ay])]);}
function filaRow(sc,f,i){return el('div',{class:'ed-tr'},[inp(f.seccion,'Sección',function(v){f.seccion=v;}),inp(f.concepto,'Concepto',function(v){f.concepto=v;}),inp(f.tipos,'Tipos / variantes',function(v){f.tipos=v;}),inp(f.unidad,'Unidad',function(v){f.unidad=v;}),
  el('div',{class:'acts',style:'display:flex;gap:4px'},[ib('▲','Subir',function(){mover(sc.filas,i,-1);}),ib('▼','Bajar',function(){mover(sc.filas,i,1);}),ib('✕','Quitar',function(){sc.filas.splice(i,1);pintar();},1)])]);}
function pintar(){box.innerHTML='';S.forEach(function(sc,si){
  var head=el('div',{class:'ed-sh'},[el('span',{class:'chip-t',text:sc.clase==='tabla'?'Tabla':'Campos'}),inp(sc.titulo,'Título de la sección',function(v){sc.titulo=v;}),
    ib('▲','Subir sección',function(){mover(S,si,-1);}),ib('▼','Bajar sección',function(){mover(S,si,1);}),ib('✕','Quitar sección',function(){if(confirm('¿Quitar la sección «'+sc.titulo+'» y todo su contenido?')){S.splice(si,1);pintar();}},1)]);
  var cuerpo=el('div');
  if(sc.clase==='tabla'){sc.filas=sc.filas||[];sc.columnas=sc.columnas||['Concepto','Tipo','Cantidad','Unidad'];
    cuerpo.appendChild(el('label',{style:'font-size:12px;color:#6b6b70;display:block;margin-bottom:8px'},[document.createTextNode('Columnas del formato'),inp(sc.columnas.join(', '),'Concepto, Tipo, Cantidad, Unidad',function(v){sc.columnas=v.split(',').map(function(x){return x.trim();}).filter(Boolean);},'ed-cols')]));
    sc.filas.forEach(function(f,i){cuerpo.appendChild(filaRow(sc,f,i));});
    cuerpo.appendChild(el('div',{class:'ed-add'},[btn('+ Concepto',function(){var u=sc.filas[sc.filas.length-1];sc.filas.push({seccion:u?u.seccion:'',concepto:'',tipos:'',unidad:'pzas.'});pintar();})]));
  }else{sc.campos=sc.campos||[];sc.campos.forEach(function(c,i){cuerpo.appendChild(campoRow(sc,c,i));});
    var add=el('div',{class:'ed-add'});[['texto','+ Campo'],['foto','+ Fotografía'],['pdf','+ Archivo PDF'],['firma','+ Firma']].forEach(function(t){add.appendChild(btn(t[1],function(){sc.campos.push({nombre:'',tipo:t[0],req:t[0]!=='texto'});pintar();
      var r=box.querySelectorAll('.ed-sec')[si].querySelectorAll('.ed-row');r[r.length-1].querySelector('input').focus();}));});cuerpo.appendChild(add);}
  box.appendChild(el('div',{class:'ed-sec'},[head,cuerpo]));});resumen();}
function resumen(){var c=0,f=0,r=0,m=0;S.forEach(function(sc){(sc.campos||[]).forEach(function(x){c++;if(x.tipo==='foto')f++;if(x.tipo==='pdf')r++;});m+=(sc.filas||[]).length;});
  document.getElementById('resumen').textContent=S.length+' secciones · '+c+' campos · '+f+' fotografías · '+r+' PDF · '+m+' conceptos';}
document.querySelectorAll('[data-addsec]').forEach(function(b){b.onclick=function(){var t=b.dataset.addsec;S.push(t==='tabla'?{titulo:'Equipo y materiales utilizados',clase:'tabla',columnas:['Concepto','Tipo','Cantidad','Unidad'],filas:[]}:{titulo:'Nueva sección',clase:'campos',campos:[]});pintar();box.lastChild.querySelector('.ed-sh input').select();};});
document.getElementById('fp').addEventListener('submit',function(){document.getElementById('secjson').value=JSON.stringify(S);});
pintar();}
