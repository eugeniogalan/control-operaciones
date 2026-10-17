"""Plantillas de Reporte de evidencias (Configuración › Reporte de evidencias).
Cada plantilla define, para un tipo de trabajo: las FOTOGRAFÍAS de evidencia requeridas, los REPORTES/archivos (PDF) a entregar
y el CATÁLOGO de materiales/equipo que se puede cargar a la orden. Se guardan en la BD (tabla plantillas_evidencia);
la primera vez se siembran desde plantillas.json (formatos de Excel originales)."""
import os, json, sqlite3
from flask import render_template, request, redirect, abort, url_for

SCHEMA = '''CREATE TABLE IF NOT EXISTS plantillas_evidencia(id INTEGER PRIMARY KEY, clave TEXT UNIQUE NOT NULL, nombre TEXT, descripcion TEXT,
 tipo_orden TEXT, fotos TEXT NOT NULL DEFAULT '[]', reportes TEXT NOT NULL DEFAULT '[]', materiales TEXT NOT NULL DEFAULT '[]',
 activo INTEGER DEFAULT 1, orden INTEGER DEFAULT 0, actualizado TEXT DEFAULT (datetime('now','localtime')), secciones TEXT)'''
NOMBRES = {'FO': 'Instalación – Internet por Fibra Óptica', 'MO': 'Instalación – Internet por Microondas', 'SAT': 'Instalación – Internet Satelital',
           'FO P-P': 'Instalación – Enlace Punto-Punto por Fibra', 'MO P-P': 'Instalación – Enlace Punto-Punto por Microondas',
           'Red WIFI': 'Instalación – Red Inalámbrica (Wi-Fi)', 'ROUTER-FW': 'Instalación – Router / Firewall / Switch'}
DB = None; JSON = None; MAPA_TIPO = {}

# ---------- Estructura de campos (tomada de formatos.xlsx) ----------
TIPOS_CAMPO = [('texto','Texto'),('texto_largo','Texto largo'),('numero','Número'),('fecha','Fecha'),('seleccion','Selección'),
               ('gps','Ubicación GPS'),('foto','Fotografía'),('pdf','Archivo PDF'),('firma','Firma')]
TIPOS_INSTALACION = ['Enlace a Internet vía Fibra Optica','Enlace a Internet vía Microondas','Enlace a Internet vía Satelital','Enlace Punto-Punto vía Fibra Optica',
    'Enlace Punto-Punto vía Microondas','Red Inalámbrica (Wi-Fi)','Router/Firewall/Switch','Sistema de Video-vigilancia (CCTV)','Cableado Estructurado',
    'Sistema de Telefonia IP','Control de Acceso (Humanos)','Control de Acceso (Automoviles)','Sistema de Energía Solar (Paneles)','Otros']
TITULOS = {'FO':'ENLACE A INTERNET VÍA FIBRA ÓPTICA','MO':'ENLACE A INTERNET VÍA MICROONDAS','SAT':'ENLACE A INTERNET VÍA SATELITAL','FO P-P':'ENLACE PUNTO-PUNTO VÍA FIBRA ÓPTICA',
           'MO P-P':'ENLACE PUNTO-PUNTO VÍA MICROONDAS','Red WIFI':'RED WI-FI ADMINISTRADA','ROUTER-FW':'ROUTER/FIREWALL'}
AYUDA_REP = {'Reporte generado (PDF)':'Subir Archivo Reporte Generado por Equipo EXFO','Reporte de datos de entrega (PDF)':'Subir Reporte de Datos de Entrega de Enlace',
             'Layout de instalación (PDF)':'Subir Layout de Instalación','Captura de pantalla del controlador (PDF)':'Subir Captura de Pantalla del Controlador en Nube de la red instalada.',
             'Captura de pantalla de la configuración (PDF)':'Subir Captura de Pantalla de la lista de Dispositivos que aparecen en el controlador en nube.'}
def F(nombre, tipo='texto', req=False, **kw): return dict(nombre=nombre, tipo=tipo, req=req, **kw)
def _split(n):
    g, _, r = n.partition(': ')
    return (g, r) if r else ('', n)

def secciones_base(clave, fotos, reportes, materiales, tipo_inst=None):
    """Secciones completas de una plantilla según el formato 'Reporte de Evidencias y Acta' + la hoja 'Plantilla Instalación <clave>'."""
    pp = 'P-P' in (clave or '')
    ss = [dict(titulo='Encabezado', clase='campos', campos=[F('Fecha','fecha',True), F('Folio','texto',True)]),
          dict(titulo='Persona que ejecutó', clase='campos', campos=[F('Nombre','texto',True), F('Puesto','seleccion',True, opciones=['Supervisor','Técnico Instalador','Proveedor Externo']),
               F('Firma','firma',True), F('Fecha en que se inició la instalación','fecha',True)]),
          dict(titulo='Datos del cliente', clase='campos', campos=[F('Nombre','texto',True), F('Calle y No.'), F('Ciudad'), F('Estado'), F('Coordenadas','gps'),
               F('Persona de contacto'), F('Teléfono')]),
          dict(titulo='Tipo de instalación', clase='campos', campos=[F('Tipo de instalación','seleccion',True, opciones=TIPOS_INSTALACION, valor=tipo_inst)]),
          dict(titulo='Ubicación', clase='campos', campos=([F('Punto A – Lectura GPS','gps',True, ayuda='Punto en donde se encuentra el domicilio de la instalación.'),
                F('Punto B – Lectura GPS','gps',True, ayuda='Punto en donde se encuentra el domicilio de la instalación.')] if pp else
               [F('Lectura GPS','gps',True, ayuda='Punto en donde se encuentra el domicilio de la instalación.')]))]
    fs = []
    for n in fotos:
        g, r = _split(n); fs.append(F(r, 'foto', True, **({'grupo': g} if g else {})))
    if fs: ss.append(dict(titulo='Fotografías', clase='campos', campos=fs))
    if reportes: ss.append(dict(titulo='Reportes', clase='campos', campos=[F(r, 'pdf', True, ayuda=AYUDA_REP.get(r, '')) for r in reportes]))
    cols = ['Concepto','Tipo','Cantidad','Unidad'] + (['Fotografía No.1','Fotografía No.2','Ubicación','Conectado a:'] if clave in ('Red WIFI','ROUTER-FW') else [])
    ss.append(dict(titulo='Equipo y materiales utilizados', clase='tabla', columnas=cols,
                   filas=[dict(seccion=m.get('seccion',''), concepto=m.get('concepto',''), tipos=m.get('tipos',''), unidad=m.get('unidad','')) for m in materiales]))
    ss.append(dict(titulo='Observaciones', clase='campos', campos=[F('Observaciones','texto_largo')]))
    return ss

def derivar(secciones):
    """De las secciones se obtienen las listas que usan las órdenes: fotos, reportes y materiales (los nombres no cambian)."""
    fotos, reps, mats = [], [], []
    for sc in secciones:
        if sc.get('clase') == 'tabla':
            mats += [dict(seccion=f.get('seccion',''), concepto=f.get('concepto',''), tipos=f.get('tipos',''), unidad=f.get('unidad','')) for f in sc.get('filas', []) if f.get('concepto')]
        for c in sc.get('campos', []) if sc.get('clase') != 'tabla' else []:
            n = (c.get('grupo') + ': ' + c['nombre']) if c.get('grupo') else c['nombre']
            if c.get('tipo') == 'foto': fotos.append(n)
            elif c.get('tipo') == 'pdf': reps.append(n)
    return fotos, reps, mats

def validar(secciones):
    tipos = {t for t, _ in TIPOS_CAMPO}; limpio = []
    if not isinstance(secciones, list): return None, 'Formato inválido'
    for sc in secciones:
        t = (sc.get('titulo') or '').strip()
        if not t: return None, 'Cada sección necesita un título'
        if sc.get('clase') == 'tabla':
            cols = [c.strip() for c in sc.get('columnas', []) if str(c).strip()] or ['Concepto','Tipo','Cantidad','Unidad']
            filas = [{k: str(f.get(k,'')).strip() for k in ('seccion','concepto','tipos','unidad')} for f in sc.get('filas', [])]
            limpio.append(dict(titulo=t, clase='tabla', columnas=cols, filas=[f for f in filas if f['concepto'] or f['seccion']]))
        else:
            cs = []
            for c in sc.get('campos', []):
                n = (c.get('nombre') or '').strip()
                if not n: continue
                tp = c.get('tipo') if c.get('tipo') in tipos else 'texto'
                d = dict(nombre=n, tipo=tp, req=bool(c.get('req')))
                for k in ('grupo','ayuda','valor'):
                    if (c.get(k) or '').strip(): d[k] = c[k].strip()
                if tp == 'seleccion':
                    op = [o.strip() for o in (c.get('opciones') or []) if str(o).strip()]
                    if not op: return None, f'El campo «{n}» es de selección y necesita opciones'
                    d['opciones'] = op
                cs.append(d)
            limpio.append(dict(titulo=t, clase='campos', campos=cs))
    return limpio, None


def migrar(c, ruta_json, mapa_tipo):
    c.execute(SCHEMA)
    if 'secciones' not in [r[1] for r in c.execute('PRAGMA table_info(plantillas_evidencia)')]:
        c.execute('ALTER TABLE plantillas_evidencia ADD COLUMN secciones TEXT')
    if not c.execute('SELECT COUNT(*) FROM plantillas_evidencia').fetchone()[0]: _sembrar(c, ruta_json, mapa_tipo)
    for pid, clave, fo, re_, ma, to in c.execute('SELECT id,clave,fotos,reportes,materiales,tipo_orden FROM plantillas_evidencia WHERE secciones IS NULL').fetchall():
        c.execute('UPDATE plantillas_evidencia SET secciones=? WHERE id=?', (json.dumps(secciones_base(clave, json.loads(fo or '[]'), json.loads(re_ or '[]'), json.loads(ma or '[]'), to), ensure_ascii=False), pid))

def _sembrar(c, ruta_json, mapa_tipo):
    P = json.load(open(ruta_json, encoding='utf-8')); inv = {v: k for k, v in mapa_tipo.items()}
    for i, (k, v) in enumerate(P.items()):
        c.execute('INSERT INTO plantillas_evidencia(clave,nombre,tipo_orden,fotos,reportes,materiales,orden) VALUES(?,?,?,?,?,?,?)',
                  (k, NOMBRES.get(k, k), inv.get(k), json.dumps(v.get('fotos', []), ensure_ascii=False), json.dumps(v.get('reportes', []), ensure_ascii=False),
                   json.dumps(v.get('materiales', []), ensure_ascii=False), i))

def _filas(solo_activas=False):
    try:
        c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
        rs = c.execute('SELECT * FROM plantillas_evidencia' + (' WHERE activo=1' if solo_activas else '') + ' ORDER BY orden, id').fetchall(); c.close()
        return rs
    except sqlite3.Error: return None

def _dic(r): return {'id': r['id'], 'clave': r['clave'], 'nombre': r['nombre'] or r['clave'], 'descripcion': r['descripcion'], 'tipo_orden': r['tipo_orden'],
                     'activo': r['activo'], 'titulo': TITULOS.get(r['clave'], (r['nombre'] or r['clave']).upper()),
                     'secciones': json.loads(r['secciones']) if r['secciones'] else secciones_base(r['clave'], json.loads(r['fotos'] or '[]'), json.loads(r['reportes'] or '[]'), json.loads(r['materiales'] or '[]'), r['tipo_orden']), 'fotos': json.loads(r['fotos'] or '[]'), 'reportes': json.loads(r['reportes'] or '[]'), 'materiales': json.loads(r['materiales'] or '[]')}

class Plantillas:
    """Vista tipo dict {clave: {fotos, reportes, materiales, ...}} leída de la BD en cada uso (seguro con varios workers de gunicorn)."""
    def _d(self):
        rs = _filas()
        if rs is None or not rs: return json.load(open(JSON, encoding='utf-8'))  # antes de migrar
        return {r['clave']: _dic(r) for r in rs}
    def get(self, k, d=None): return self._d().get(k, d)
    def __getitem__(self, k): return self._d()[k]
    def __contains__(self, k): return k in self._d()
    def __iter__(self): return iter(self._d())
    def __len__(self): return len(self._d())
    def keys(self): return self._d().keys()
    def values(self): return self._d().values()
    def items(self): return self._d().items()

def ligada_a(tipo):
    for r in (_filas(True) or []):
        if tipo and r['tipo_orden'] == tipo: return r['clave']

def por_tipo_orden(tipo):
    for r in (_filas() or []):
        if tipo and r['tipo_orden'] == tipo: return r['clave']
    return MAPA_TIPO.get(tipo)

def _lineas(t): return [x.strip() for x in (t or '').splitlines() if x.strip()]
def _mats(t):
    out = []
    for l in _lineas(t):
        p = [x.strip() for x in l.split('|')] + ['', '', '', '']
        if p[1] or p[0]: out.append({'seccion': p[0] if p[1] else '', 'concepto': p[1] or p[0], 'tipos': p[2], 'unidad': p[3]})
    return out

def registrar(app, q, db, tipos_orden):
    @app.route('/configuracion/evidencias')
    def evid_lista():
        rs = [_dic(r) for r in q('SELECT * FROM plantillas_evidencia ORDER BY activo DESC, orden, id')]
        return render_template('evid_lista.html', rs=rs, msg=request.args.get('msg'))

    @app.route('/configuracion/evidencias/<int:pid>')
    def evid_ver(pid):
        r = q('SELECT * FROM plantillas_evidencia WHERE id=?', (pid,), one=True) or abort(404)
        return render_template('evid_ver.html', p=_dic(r))

    @app.route('/configuracion/evidencias/nueva', methods=['GET', 'POST'])
    @app.route('/configuracion/evidencias/<int:pid>/editar', methods=['GET', 'POST'])
    def evid_form(pid=None):
        r = q('SELECT * FROM plantillas_evidencia WHERE id=?', (pid,), one=True) if pid else None
        if pid and not r: abort(404)
        p = _dic(r) if r else {'clave': '', 'nombre': '', 'descripcion': '', 'tipo_orden': '', 'activo': 1, 'fotos': [], 'reportes': [], 'materiales': [], 'secciones': secciones_base('', [], [], [])}
        if pid is None and request.args.get('copiar', type=int):
            c0 = q('SELECT * FROM plantillas_evidencia WHERE id=?', (request.args.get('copiar', type=int),), one=True)
            if c0: p = dict(_dic(c0), clave='', nombre='Copia de ' + (c0['nombre'] or c0['clave']), tipo_orden='', activo=1)
        err = None
        if request.method == 'POST':
            F_ = request.form
            clave = r['clave'] if r else (F_.get('clave') or '').strip()
            try: secs, err = validar(json.loads(F_.get('secciones') or '[]'))
            except ValueError: secs, err = None, 'Formato de secciones inválido'
            d = dict(nombre=(F_.get('nombre') or '').strip(), descripcion=(F_.get('descripcion') or '').strip() or None, tipo_orden=F_.get('tipo_orden') or None, activo=1 if F_.get('activo') else 0)
            if not err:
                fotos, reps, mats = derivar(secs)
                if not clave: err = 'La clave es obligatoria'
                elif not d['nombre']: err = 'El nombre es obligatorio'
                elif not fotos and not reps: err = 'Agrega al menos un campo de tipo Fotografía o Archivo PDF'
                elif not r and q('SELECT 1 FROM plantillas_evidencia WHERE clave=?', (clave,), one=True): err = 'Ya existe una plantilla con esa clave'
                elif d['tipo_orden'] and q('SELECT 1 FROM plantillas_evidencia WHERE tipo_orden=? AND id IS NOT ?', (d['tipo_orden'], pid), one=True): err = 'Ese tipo de orden ya está ligado a otra plantilla'
            if not err:
                J = lambda x: json.dumps(x, ensure_ascii=False)
                vals = (d['nombre'], d['descripcion'], d['tipo_orden'], J(fotos), J(reps), J(mats), d['activo'], J(secs))
                if r: db().execute("UPDATE plantillas_evidencia SET nombre=?,descripcion=?,tipo_orden=?,fotos=?,reportes=?,materiales=?,activo=?,secciones=?,actualizado=datetime('now','localtime') WHERE id=?", vals + (pid,))
                else: pid = db().execute('INSERT INTO plantillas_evidencia(nombre,descripcion,tipo_orden,fotos,reportes,materiales,activo,secciones,clave,orden) VALUES(?,?,?,?,?,?,?,?,?,(SELECT COALESCE(MAX(orden),0)+1 FROM plantillas_evidencia))', vals + (clave,)).lastrowid
                db().commit(); return redirect(url_for('evid_ver', pid=pid))
            p = dict(p, clave=clave, **d)
            try: p['secciones'] = json.loads(F_.get('secciones') or '[]')
            except ValueError: pass
        return render_template('evid_form.html', p=p, pid=pid, err=err, tipos_orden=tipos_orden, TIPOS_CAMPO=TIPOS_CAMPO)

    @app.route('/catalogo')
    def catalogo():  # ruta anterior "Plantillas": se conserva y redirige
        k = request.args.get('plantilla')
        r = q('SELECT id FROM plantillas_evidencia WHERE clave=?', (k,), one=True) if k else None
        return redirect(url_for('evid_ver', pid=r['id']) if r else url_for('evid_lista'))
