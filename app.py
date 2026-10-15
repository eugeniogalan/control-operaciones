import sqlite3, json, os, math, datetime as dt
from flask import Flask, g, render_template, request, redirect, url_for, jsonify, send_from_directory, abort
from werkzeug.utils import secure_filename

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get('DB_PATH') or os.path.join(BASE, 'ops.db')
UP = os.environ.get('UPLOAD_DIR') or os.path.join(BASE, 'uploads')
os.makedirs(UP, exist_ok=True)
os.makedirs(os.path.dirname(os.path.abspath(DB)), exist_ok=True)
app = Flask(__name__)
import hmac
from flask import session
_envf = os.path.join(BASE, '.env')
_FILE = dict(l.strip().split('=',1) for l in open(_envf) if '=' in l) if os.path.exists(_envf) else {}
def _cfg(*keys):
    for k in keys:
        if os.environ.get(k): return os.environ[k]
    for k in keys:
        if _FILE.get(k): return _FILE[k]
    return None
CFG = {'APP_USER': _cfg('ADMIN_USER','APP_USER') or 'admin', 'APP_PASSWORD': _cfg('ADMIN_PASSWORD','APP_PASSWORD'), 'SECRET_KEY': _cfg('SECRET_KEY')}
if not CFG['APP_PASSWORD'] or not CFG['SECRET_KEY']:
    raise RuntimeError('Faltan ADMIN_PASSWORD y/o SECRET_KEY (variables de entorno o .env)')
app.secret_key = CFG['SECRET_KEY']
_HTTPS = bool(os.environ.get('RENDER')) or os.environ.get('SESSION_COOKIE_SECURE','').lower() in ('1','true','yes')
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.config.update(SESSION_COOKIE_SECURE=_HTTPS, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', PERMANENT_SESSION_LIFETIME=dt.timedelta(days=14))

@app.before_request
def _auth():
    if request.endpoint in ('login',) or session.get('ok'): return
    if request.path.startswith('/api/'): return jsonify(error='no autorizado'), 401
    return redirect(url_for('login', next=request.full_path))

@app.route('/login', methods=['GET','POST'])
def login():
    err = None
    if request.method == 'POST':
        if hmac.compare_digest(request.form.get('usuario',''), CFG['APP_USER']) and hmac.compare_digest(request.form.get('clave',''), CFG['APP_PASSWORD']):
            session.clear(); session['ok'] = True; session.permanent = True
            nxt = request.args.get('next') or '/'
            return redirect(nxt if nxt.startswith('/') and not nxt.startswith('//') else '/')
        err = 'Usuario o contraseña incorrectos'
    return render_template('login.html', err=err)

@app.route('/logout')
def logout():
    session.clear(); return redirect(url_for('login'))
PLANT = json.load(open(os.path.join(BASE, 'plantillas.json'), encoding='utf-8'))

# ---- Catálogos tomados de los formatos de Excel ----
CATEGORIAS = {
 'EJ-FO': 'Orden de ejecución - Red de Fibra Óptica',
 'EJ-MO': 'Orden de ejecución - Red de Microondas',
 'INST': 'Orden de instalación a cliente',
}
TIPOS = {
 'EJ-FO': {'Mantenimiento correctivo': ['Reparación por Corte','Reparación por Atenuación','Reparación por Modificación'],
           'Mantenimiento preventivo': ['Revisión de circuito Larga Distancia','Revisión de circuito Urbano','Revisión de circuito FTTH'],
           'Construcción': ['Circuito Larga Distancia','Circuito Urbano','Circuito FTTH'],
           'Ingeniería': ['Estudio para circuito Larga Distancia','Estudio para circuito Urbano','Estudio para circuito FTTH']},
 'EJ-MO': {'Mantenimiento correctivo': ['Reparación por Daño','Reparación por Señal Baja','Reparación por Modificación'],
           'Mantenimiento preventivo': ['Revisión de status de Radios/Antenas','Revisión de POE/Electricidad','Revisión de Torre/Sitio'],
           'Construcción': ['Enlace Punto-Punto (Backbone)','Enlace Punto-Multipunto (AP)','Repetidor Grande (Sitio de Concreto)','Repetidor Grande (Gabinete p/ Ext)','Repetidor Chico (Gabinete p/Exterior)','Circuito de Tierra Física','Sistema de Energía de Emergencia']},
 'INST': {'Tipo de instalación': ['Enlace a Internet vía Fibra Optica','Enlace a Internet vía Microondas','Enlace a Internet vía Satelital','Enlace Punto-Punto vía Fibra Optica','Enlace Punto-Punto vía Microondas','Red Inalámbrica (Wi-Fi)','Router/Firewall/Switch','Sistema de Video-vigilancia (CCTV)','Cableado Estructurado','Sistema de Telefonia IP','Control de Acceso (Humanos)','Control de Acceso (Automoviles)','Sistema de Energía Solar (Paneles)','Otros']},
}
PLANT_DE_TIPO = {'Enlace a Internet vía Fibra Optica':'FO','Enlace a Internet vía Microondas':'MO','Enlace a Internet vía Satelital':'SAT',
 'Enlace Punto-Punto vía Fibra Optica':'FO P-P','Enlace Punto-Punto vía Microondas':'MO P-P','Red Inalámbrica (Wi-Fi)':'Red WIFI','Router/Firewall/Switch':'ROUTER-FW'}
def plantilla_de(o):
    if o['categoria']=='EJ-FO': return 'FO'
    if o['categoria']=='EJ-MO': return 'MO'
    return PLANT_DE_TIPO.get(o['tipo_orden'])
ESTADOS = ['pendiente','asignada','en curso','completada','cancelada']
PRIORIDADES = ['baja','media','alta','urgente']
PUESTOS_ORDENA = ['Director','Gerente','Vendedor','Supervisor']
PUESTOS_EJEC = ['Supervisor','Técnico Instalador','Proveedor Externo']
PUESTOS_AUD = ['Director','Gerente','Supervisor']
TIPOS_CLIENTE = ['Empresa','PYME','Residencial','Gobierno']

SCHEMA = '''
CREATE TABLE IF NOT EXISTS cuadrillas(id INTEGER PRIMARY KEY, nombre TEXT NOT NULL, especialidad TEXT, zona TEXT, activa INTEGER DEFAULT 1, ejemplo INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS tecnicos(id INTEGER PRIMARY KEY, cuadrilla_id INTEGER REFERENCES cuadrillas(id), rol TEXT CHECK(rol IN ('líder','técnico')), nombre TEXT NOT NULL, telefono TEXT, especialidad TEXT, puesto TEXT DEFAULT 'Técnico Instalador', ejemplo INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS ordenes(id INTEGER PRIMARY KEY, folio TEXT UNIQUE, categoria TEXT, tipo_grupo TEXT, tipo_orden TEXT, prioridad TEXT DEFAULT 'media', estado TEXT DEFAULT 'pendiente',
 fecha_emision TEXT, fecha_programada TEXT, fecha_inicio TEXT, fecha_cierre TEXT,
 ordena_nombre TEXT, ordena_puesto TEXT,
 cliente TEXT, tipo_cliente TEXT, calle TEXT, ciudad TEXT, estado_geo TEXT, contacto TEXT, telefono TEXT, coordenadas TEXT, coordenadas_b TEXT,
 sitio TEXT, descripcion TEXT, cuadrilla_id INTEGER REFERENCES cuadrillas(id), ejecuto_puesto TEXT, personas_adicionales TEXT, observaciones TEXT, notas TEXT,
 folio_evidencias TEXT, audito_nombre TEXT, audito_puesto TEXT, fecha_auditoria TEXT, aprobacion TEXT, obs_auditoria TEXT, ejemplo INTEGER DEFAULT 0, creado TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS orden_materiales(id INTEGER PRIMARY KEY, orden_id INTEGER REFERENCES ordenes(id) ON DELETE CASCADE, seccion TEXT, concepto TEXT, tipo TEXT, cantidad REAL, unidad TEXT);
CREATE TABLE IF NOT EXISTS orden_fotos(id INTEGER PRIMARY KEY, orden_id INTEGER REFERENCES ordenes(id) ON DELETE CASCADE, item TEXT, archivo TEXT, subido TEXT);
CREATE TABLE IF NOT EXISTS bitacora(id INTEGER PRIMARY KEY, orden_id INTEGER, fecha TEXT, texto TEXT);
'''
def db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB); g.db.row_factory = sqlite3.Row; g.db.execute('PRAGMA foreign_keys=ON')
    return g.db
@app.teardown_appcontext
def _c(e):
    d = g.pop('db', None)
    if d: d.close()
def q(sql, a=(), one=False):
    r = db().execute(sql, a).fetchall(); return (r[0] if r else None) if one else r
def hoy(): return dt.date.today().isoformat()
def ahora(): return dt.datetime.now().strftime('%Y-%m-%dT%H:%M')
def log(oid, t): db().execute('INSERT INTO bitacora(orden_id,fecha,texto) VALUES(?,?,?)', (oid, ahora(), t))

@app.context_processor
def ctx(): return dict(ESTADOS=ESTADOS, PRIORIDADES=PRIORIDADES, CATEGORIAS=CATEGORIAS, TIPOS=TIPOS, PUESTOS_ORDENA=PUESTOS_ORDENA,
    PUESTOS_EJEC=PUESTOS_EJEC, PUESTOS_AUD=PUESTOS_AUD, TIPOS_CLIENTE=TIPOS_CLIENTE, hoy=hoy(), tipos_json=json.dumps(TIPOS, ensure_ascii=False))

VENCIDA = "(o.estado NOT IN ('completada','cancelada') AND o.fecha_programada < date('now','localtime'))"

@app.route('/')
def dashboard():
    por_estado = {e: 0 for e in ESTADOS}
    for r in q('SELECT estado, COUNT(*) n FROM ordenes GROUP BY estado'): por_estado[r['estado']] = r['n']
    por_cuad = q(f'''SELECT c.id, c.nombre, COUNT(o.id) total, SUM(o.estado='completada') comp, SUM(o.estado IN ('pendiente','asignada','en curso')) abiertas,
        SUM({VENCIDA}) venc FROM cuadrillas c LEFT JOIN ordenes o ON o.cuadrilla_id=c.id GROUP BY c.id ORDER BY c.id''')
    vencidas = q(f'SELECT o.*, c.nombre cuad FROM ordenes o LEFT JOIN cuadrillas c ON c.id=o.cuadrilla_id WHERE {VENCIDA} ORDER BY o.fecha_programada LIMIT 50')
    por_cat = q('SELECT categoria, COUNT(*) n FROM ordenes GROUP BY categoria')
    hoy_n = q("SELECT COUNT(*) n FROM ordenes WHERE fecha_programada=date('now','localtime')", one=True)['n']
    pend_aud = q("SELECT COUNT(*) n FROM ordenes WHERE estado='completada' AND (aprobacion IS NULL OR aprobacion='')", one=True)['n']
    total = sum(por_estado.values()); maxc = max([r['total'] for r in por_cuad] + [1])
    return render_template('dashboard.html', por_estado=por_estado, por_cuad=por_cuad, vencidas=vencidas, total=total, maxc=maxc, por_cat=por_cat, hoy_n=hoy_n, pend_aud=pend_aud)

# ---------- Órdenes ----------
@app.route('/ordenes')
def ordenes():
    f = {k: request.args.get(k, '') for k in ('estado','cuadrilla','cliente','desde','hasta','categoria','buscar','vencidas')}
    w, a = ['1=1'], []
    if f['estado']: w.append('o.estado=?'); a.append(f['estado'])
    if f['cuadrilla']: w.append('o.cuadrilla_id=?'); a.append(f['cuadrilla'])
    if f['categoria']: w.append('o.categoria=?'); a.append(f['categoria'])
    if f['cliente']: w.append('o.cliente LIKE ?'); a.append('%'+f['cliente']+'%')
    if f['buscar']: w.append('(o.folio LIKE ? OR o.sitio LIKE ? OR o.tipo_orden LIKE ?)'); a += ['%'+f['buscar']+'%']*3
    if f['desde']: w.append('o.fecha_programada>=?'); a.append(f['desde'])
    if f['hasta']: w.append('o.fecha_programada<=?'); a.append(f['hasta'])
    if f['vencidas']: w.append(VENCIDA)
    where = ' AND '.join(w)
    total = q(f'SELECT COUNT(*) n FROM ordenes o WHERE {where}', a, one=True)['n']
    per = 20; pages = max(1, math.ceil(total/per)); page = min(max(1, int(request.args.get('page', 1) or 1)), pages)
    rows = q(f'SELECT o.*, c.nombre cuad, {VENCIDA} vencida FROM ordenes o LEFT JOIN cuadrillas c ON c.id=o.cuadrilla_id WHERE {where} ORDER BY o.fecha_programada DESC, o.id DESC LIMIT ? OFFSET ?', a+[per, (page-1)*per])
    clientes = [r['cliente'] for r in q('SELECT DISTINCT cliente FROM ordenes WHERE cliente IS NOT NULL ORDER BY cliente')]
    qs = {k: v for k, v in f.items() if v}
    return render_template('ordenes.html', rows=rows, f=f, total=total, page=page, pages=pages, cuadrillas=q('SELECT * FROM cuadrillas ORDER BY id'), clientes=clientes, qs=qs)

CAMPOS = ['categoria','tipo_grupo','tipo_orden','prioridad','estado','fecha_emision','fecha_programada','fecha_inicio','fecha_cierre','ordena_nombre','ordena_puesto',
 'cliente','tipo_cliente','calle','ciudad','estado_geo','contacto','telefono','coordenadas','coordenadas_b','sitio','descripcion','cuadrilla_id','ejecuto_puesto',
 'personas_adicionales','observaciones','notas','folio_evidencias','audito_nombre','audito_puesto','fecha_auditoria','aprobacion','obs_auditoria']

def siguiente_folio(cat):
    pref = {'EJ-FO':'FO','EJ-MO':'MO','INST':'IC'}[cat] + dt.date.today().strftime('%y%m')
    n = q('SELECT COUNT(*) n FROM ordenes WHERE folio LIKE ?', (pref+'%',), one=True)['n']
    while q('SELECT 1 FROM ordenes WHERE folio=?', (f'{pref}{n+1:04d}',), one=True): n += 1
    return f'{pref}{n+1:04d}'

@app.route('/ordenes/nueva', methods=['GET','POST'])
@app.route('/ordenes/<int:oid>/editar', methods=['GET','POST'])
def orden_form(oid=None):
    o = q('SELECT * FROM ordenes WHERE id=?', (oid,), one=True) if oid else None
    if oid and not o: abort(404)
    if request.method == 'POST':
        d = {k: (request.form.get(k) or None) for k in CAMPOS}
        if d['cuadrilla_id'] and d['estado'] == 'pendiente': d['estado'] = 'asignada'
        if d['estado'] == 'completada' and not d['fecha_cierre']: d['fecha_cierre'] = ahora()
        folio = request.form.get('folio') or (o['folio'] if o else siguiente_folio(d['categoria'] or 'INST'))
        if o:
            db().execute(f"UPDATE ordenes SET folio=?, {', '.join(k+'=?' for k in CAMPOS)} WHERE id=?", [folio]+[d[k] for k in CAMPOS]+[oid])
            if o['estado'] != d['estado']: log(oid, f"Estado: {o['estado']} → {d['estado']} (oficina)")
        else:
            cur = db().execute(f"INSERT INTO ordenes(folio,{','.join(CAMPOS)}) VALUES(?{',?'*len(CAMPOS)})", [folio]+[d[k] for k in CAMPOS]); oid = cur.lastrowid
            log(oid, 'Orden creada')
        db().commit(); return redirect(url_for('orden_ver', oid=oid))
    return render_template('orden_form.html', o=o, cuadrillas=q('SELECT * FROM cuadrillas ORDER BY id'))

@app.route('/ordenes/<int:oid>')
def orden_ver(oid):
    o = q('SELECT o.*, c.nombre cuad FROM ordenes o LEFT JOIN cuadrillas c ON c.id=o.cuadrilla_id WHERE o.id=?', (oid,), one=True) or abort(404)
    p = plantilla_de(o); pl = PLANT.get(p) if p else None
    fotos = {r['item']: r for r in q('SELECT * FROM orden_fotos WHERE orden_id=?', (oid,))}
    return render_template('orden_ver.html', o=o, plantilla=p, pl=pl, fotos=fotos,
        mats=q('SELECT * FROM orden_materiales WHERE orden_id=? ORDER BY id', (oid,)), bit=q('SELECT * FROM bitacora WHERE orden_id=? ORDER BY id DESC', (oid,)),
        equipo=q('SELECT * FROM tecnicos WHERE cuadrilla_id=? ORDER BY rol', (o['cuadrilla_id'],)))

@app.route('/ordenes/<int:oid>/eliminar', methods=['POST'])
def orden_eliminar(oid):
    db().execute('DELETE FROM ordenes WHERE id=?', (oid,)); db().commit(); return redirect(url_for('ordenes'))

@app.route('/ordenes/<int:oid>/estado', methods=['POST'])
def orden_estado(oid):
    o = q('SELECT * FROM ordenes WHERE id=?', (oid,), one=True) or abort(404)
    e = request.form['estado']; assert e in ESTADOS
    sets = {'estado': e}
    if e == 'en curso' and not o['fecha_inicio']: sets['fecha_inicio'] = request.form.get('hora') or ahora()
    if e == 'completada': sets['fecha_cierre'] = request.form.get('hora') or ahora()
    nota = (request.form.get('nota') or '').strip()
    if nota: sets['notas'] = ((o['notas'] or '') + f"\n[{ahora().replace('T',' ')}] {nota}").strip()
    db().execute(f"UPDATE ordenes SET {', '.join(k+'=?' for k in sets)} WHERE id=?", list(sets.values())+[oid])
    log(oid, f"Estado: {o['estado']} → {e}" + (f' · Nota: {nota}' if nota else '') + (' (campo)' if request.form.get('origen')=='campo' else ''))
    db().commit()
    if request.form.get('origen') == 'campo': return redirect(url_for('tecnico', cuadrilla=o['cuadrilla_id'], _anchor=f'o{oid}'))
    return redirect(url_for('orden_ver', oid=oid))

@app.route('/ordenes/<int:oid>/nota', methods=['POST'])
def orden_nota(oid):
    o = q('SELECT * FROM ordenes WHERE id=?', (oid,), one=True) or abort(404)
    nota = (request.form.get('nota') or '').strip()
    if nota:
        db().execute('UPDATE ordenes SET notas=? WHERE id=?', (((o['notas'] or '') + f"\n[{ahora().replace('T',' ')}] {nota}").strip(), oid)); log(oid, 'Nota: '+nota); db().commit()
    if request.form.get('origen') == 'campo': return redirect(url_for('tecnico', cuadrilla=o['cuadrilla_id'], _anchor=f'o{oid}'))
    return redirect(url_for('orden_ver', oid=oid))

@app.route('/ordenes/<int:oid>/materiales', methods=['GET','POST'])
def orden_materiales(oid):
    o = q('SELECT * FROM ordenes WHERE id=?', (oid,), one=True) or abort(404)
    p = plantilla_de(o) or request.args.get('plantilla') or 'FO'
    cat = PLANT[p]['materiales']
    if request.method == 'POST':
        db().execute('DELETE FROM orden_materiales WHERE orden_id=?', (oid,))
        for i, m in enumerate(cat):
            c = request.form.get(f'q{i}')
            if c and float(c) > 0:
                db().execute('INSERT INTO orden_materiales(orden_id,seccion,concepto,tipo,cantidad,unidad) VALUES(?,?,?,?,?,?)', (oid, m['seccion'], m['concepto'], request.form.get(f't{i}'), float(c), m['unidad']))
        for j in range(3):
            c = request.form.get(f'oq{j}'); n = request.form.get(f'on{j}')
            if n and c: db().execute('INSERT INTO orden_materiales(orden_id,seccion,concepto,tipo,cantidad,unidad) VALUES(?,?,?,?,?,?)', (oid,'OTROS MATERIALES',n,'',float(c),request.form.get(f'ou{j}') or ''))
        log(oid, 'Materiales actualizados'); db().commit()
        if request.form.get('origen') == 'campo': return redirect(url_for('tecnico', cuadrilla=o['cuadrilla_id']))
        return redirect(url_for('orden_ver', oid=oid))
    actual = {r['concepto']+'|'+r['seccion']: r for r in q('SELECT * FROM orden_materiales WHERE orden_id=?', (oid,))}
    return render_template('materiales.html', o=o, cat=cat, plantilla=p, actual=actual, origen=request.args.get('origen',''))

@app.route('/ordenes/<int:oid>/foto', methods=['POST'])
def orden_foto(oid):
    o = q('SELECT * FROM ordenes WHERE id=?', (oid,), one=True) or abort(404)
    f = request.files.get('archivo'); item = request.form['item']
    if f and f.filename:
        name = f'{oid}_{dt.datetime.now().strftime("%H%M%S%f")}_' + secure_filename(f.filename); f.save(os.path.join(UP, name))
        db().execute('DELETE FROM orden_fotos WHERE orden_id=? AND item=?', (oid, item))
        db().execute('INSERT INTO orden_fotos(orden_id,item,archivo,subido) VALUES(?,?,?,?)', (oid, item, name, ahora())); log(oid, 'Evidencia: '+item); db().commit()
    if request.form.get('origen') == 'campo': return redirect(url_for('evidencias', oid=oid, origen='campo'))
    return redirect(url_for('orden_ver', oid=oid, _anchor='evidencias'))

@app.route('/ordenes/<int:oid>/evidencias')
def evidencias(oid):
    o = q('SELECT * FROM ordenes WHERE id=?', (oid,), one=True) or abort(404)
    p = plantilla_de(o); pl = PLANT.get(p) if p else None
    fotos = {r['item']: r for r in q('SELECT * FROM orden_fotos WHERE orden_id=?', (oid,))}
    return render_template('evidencias.html', o=o, pl=pl, plantilla=p, fotos=fotos)

@app.route('/uploads/<path:n>')
def uploads(n): return send_from_directory(UP, n)

@app.route('/ordenes/<int:oid>/imprimir/<fmt>')
def imprimir(oid, fmt):
    o = q('SELECT o.*, c.nombre cuad FROM ordenes o LEFT JOIN cuadrillas c ON c.id=o.cuadrilla_id WHERE o.id=?', (oid,), one=True) or abort(404)
    p = plantilla_de(o); pl = PLANT.get(p) if p else None
    equipo = q('SELECT * FROM tecnicos WHERE cuadrilla_id=? ORDER BY rol', (o['cuadrilla_id'],))
    mats = q('SELECT * FROM orden_materiales WHERE orden_id=? ORDER BY id', (oid,))
    fotos = {r['item']: r for r in q('SELECT * FROM orden_fotos WHERE orden_id=?', (oid,))}
    return render_template('imprimir_orden.html' if fmt == 'orden' else 'imprimir_evidencias.html', o=o, pl=pl, plantilla=p, equipo=equipo, mats=mats, fotos=fotos)

# ---------- Cuadrillas / técnicos ----------
@app.route('/cuadrillas')
def cuadrillas():
    cs = q('SELECT * FROM cuadrillas ORDER BY id'); t = {}
    for r in q("SELECT * FROM tecnicos ORDER BY CASE rol WHEN 'líder' THEN 0 ELSE 1 END"): t.setdefault(r['cuadrilla_id'], []).append(r)
    sin = q('SELECT * FROM tecnicos WHERE cuadrilla_id IS NULL')
    return render_template('cuadrillas.html', cs=cs, t=t, sin=sin)

@app.route('/cuadrillas/nueva', methods=['GET','POST'])
@app.route('/cuadrillas/<int:cid>', methods=['GET','POST'])
def cuadrilla_form(cid=None):
    c = q('SELECT * FROM cuadrillas WHERE id=?', (cid,), one=True) if cid else None
    miembros = {r['rol']: r for r in q('SELECT * FROM tecnicos WHERE cuadrilla_id=?', (cid,))} if cid else {}
    if request.method == 'POST':
        F = request.form
        if c: db().execute('UPDATE cuadrillas SET nombre=?,especialidad=?,zona=?,activa=? WHERE id=?', (F['nombre'], F.get('especialidad'), F.get('zona'), 1 if F.get('activa') else 0, cid))
        else: cid = db().execute('INSERT INTO cuadrillas(nombre,especialidad,zona,activa) VALUES(?,?,?,1)', (F['nombre'], F.get('especialidad'), F.get('zona'))).lastrowid
        for rol, k in (('líder','l'), ('técnico','t')):
            vals = (F.get(k+'_nombre'), F.get(k+'_tel'), F.get(k+'_esp'), F.get(k+'_puesto') or 'Técnico Instalador')
            if not vals[0]: continue
            if rol in miembros: db().execute('UPDATE tecnicos SET nombre=?,telefono=?,especialidad=?,puesto=? WHERE id=?', vals+(miembros[rol]['id'],))
            else: db().execute('INSERT INTO tecnicos(nombre,telefono,especialidad,puesto,cuadrilla_id,rol) VALUES(?,?,?,?,?,?)', vals+(cid, rol))
        db().commit(); return redirect(url_for('cuadrillas'))
    return render_template('cuadrilla_form.html', c=c, m=miembros)

@app.route('/cuadrillas/<int:cid>/eliminar', methods=['POST'])
def cuadrilla_eliminar(cid):
    db().execute('UPDATE ordenes SET cuadrilla_id=NULL WHERE cuadrilla_id=?', (cid,)); db().execute('DELETE FROM tecnicos WHERE cuadrilla_id=?', (cid,))
    db().execute('DELETE FROM cuadrillas WHERE id=?', (cid,)); db().commit(); return redirect(url_for('cuadrillas'))

# ---------- Vista técnico ----------
@app.route('/tecnico')
def tecnico():
    cid = request.args.get('cuadrilla', type=int); cs = q('SELECT * FROM cuadrillas ORDER BY id')
    if not cid: return render_template('tecnico_elegir.html', cs=cs)
    c = q('SELECT * FROM cuadrillas WHERE id=?', (cid,), one=True) or abort(404)
    base = f'SELECT o.*, {VENCIDA} vencida FROM ordenes o WHERE o.cuadrilla_id=? '
    de_hoy = q(base + "AND (o.fecha_programada=date('now','localtime') OR (o.estado='completada' AND substr(o.fecha_cierre,1,10)=date('now','localtime'))) ORDER BY CASE o.estado WHEN 'en curso' THEN 0 WHEN 'asignada' THEN 1 WHEN 'pendiente' THEN 1 ELSE 2 END, o.prioridad='urgente' DESC", (cid,))
    ids = [o['id'] for o in de_hoy]
    pend = [o for o in q(base + "AND o.estado IN ('pendiente','asignada','en curso') ORDER BY o.fecha_programada", (cid,)) if o['id'] not in ids]
    return render_template('tecnico.html', c=c, cs=cs, de_hoy=de_hoy, pend=pend, equipo=q('SELECT * FROM tecnicos WHERE cuadrilla_id=? ORDER BY rol', (cid,)), ahora=ahora())

# ---------- Catálogo de materiales ----------
@app.route('/catalogo')
def catalogo():
    p = request.args.get('plantilla', 'FO')
    return render_template('catalogo.html', plant=PLANT, p=p)

@app.route('/reportes/materiales')
def reporte_materiales():
    desde = request.args.get('desde') or (dt.date.today().replace(day=1)).isoformat(); hasta = request.args.get('hasta') or hoy()
    rows = q('''SELECT m.seccion, m.concepto, m.tipo, m.unidad, SUM(m.cantidad) total, COUNT(DISTINCT m.orden_id) ordenes FROM orden_materiales m JOIN ordenes o ON o.id=m.orden_id
       WHERE substr(COALESCE(o.fecha_cierre,o.fecha_programada),1,10) BETWEEN ? AND ? GROUP BY m.seccion,m.concepto,m.tipo,m.unidad ORDER BY m.seccion,m.concepto''', (desde, hasta))
    return render_template('reporte_materiales.html', rows=rows, desde=desde, hasta=hasta)

# ---------- API JSON ----------
@app.route('/api/resumen')
def api_resumen():
    return jsonify(estados={r['estado']: r['n'] for r in q('SELECT estado, COUNT(*) n FROM ordenes GROUP BY estado')},
                   total=q('SELECT COUNT(*) n FROM ordenes', one=True)['n'], vencidas=q(f'SELECT COUNT(*) n FROM ordenes o WHERE {VENCIDA}', one=True)['n'],
                   cuadrillas=q('SELECT COUNT(*) n FROM cuadrillas', one=True)['n'], tecnicos=q('SELECT COUNT(*) n FROM tecnicos', one=True)['n'])
@app.route('/api/ordenes')
def api_ordenes():
    return jsonify([dict(r) for r in q('SELECT * FROM ordenes ORDER BY fecha_programada DESC LIMIT 500')])

def init_db():
    c = sqlite3.connect(DB); c.executescript(SCHEMA); c.commit(); c.close()
init_db()
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), debug=False)
