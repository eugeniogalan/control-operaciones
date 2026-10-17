"""Plantillas de Reporte de evidencias (Configuración › Reporte de evidencias).
Cada plantilla define, para un tipo de trabajo: las FOTOGRAFÍAS de evidencia requeridas, los REPORTES/archivos (PDF) a entregar
y el CATÁLOGO de materiales/equipo que se puede cargar a la orden. Se guardan en la BD (tabla plantillas_evidencia);
la primera vez se siembran desde plantillas.json (formatos de Excel originales)."""
import os, json, sqlite3
from flask import render_template, request, redirect, abort, url_for

SCHEMA = '''CREATE TABLE IF NOT EXISTS plantillas_evidencia(id INTEGER PRIMARY KEY, clave TEXT UNIQUE NOT NULL, nombre TEXT, descripcion TEXT,
 tipo_orden TEXT, fotos TEXT NOT NULL DEFAULT '[]', reportes TEXT NOT NULL DEFAULT '[]', materiales TEXT NOT NULL DEFAULT '[]',
 activo INTEGER DEFAULT 1, orden INTEGER DEFAULT 0, actualizado TEXT DEFAULT (datetime('now','localtime')))'''
NOMBRES = {'FO': 'Instalación – Internet por Fibra Óptica', 'MO': 'Instalación – Internet por Microondas', 'SAT': 'Instalación – Internet Satelital',
           'FO P-P': 'Instalación – Enlace Punto-Punto por Fibra', 'MO P-P': 'Instalación – Enlace Punto-Punto por Microondas',
           'Red WIFI': 'Instalación – Red Inalámbrica (Wi-Fi)', 'ROUTER-FW': 'Instalación – Router / Firewall / Switch'}
DB = None; JSON = None; MAPA_TIPO = {}

def migrar(c, ruta_json, mapa_tipo):
    c.execute(SCHEMA)
    if c.execute('SELECT COUNT(*) FROM plantillas_evidencia').fetchone()[0]: return
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
                     'activo': r['activo'], 'fotos': json.loads(r['fotos'] or '[]'), 'reportes': json.loads(r['reportes'] or '[]'), 'materiales': json.loads(r['materiales'] or '[]')}

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
        p = _dic(r) if r else {'clave': '', 'nombre': '', 'descripcion': '', 'tipo_orden': '', 'activo': 1, 'fotos': [], 'reportes': [], 'materiales': []}
        if pid is None and request.args.get('copiar', type=int):
            c0 = q('SELECT * FROM plantillas_evidencia WHERE id=?', (request.args.get('copiar', type=int),), one=True)
            if c0: p = dict(_dic(c0), clave='', nombre='Copia de ' + (c0['nombre'] or c0['clave']), tipo_orden='', activo=1)
        err = None
        if request.method == 'POST':
            F = request.form
            clave = r['clave'] if r else (F.get('clave') or '').strip()
            d = dict(nombre=(F.get('nombre') or '').strip(), descripcion=(F.get('descripcion') or '').strip() or None, tipo_orden=F.get('tipo_orden') or None,
                     fotos=_lineas(F.get('fotos')), reportes=_lineas(F.get('reportes')), materiales=_mats(F.get('materiales')), activo=1 if F.get('activo') else 0)
            if not clave: err = 'La clave es obligatoria'
            elif not d['nombre']: err = 'El nombre es obligatorio'
            elif not d['fotos'] and not d['reportes']: err = 'Agrega al menos una fotografía o un reporte requerido'
            elif not r and q('SELECT 1 FROM plantillas_evidencia WHERE clave=?', (clave,), one=True): err = 'Ya existe una plantilla con esa clave'
            elif d['tipo_orden'] and q('SELECT 1 FROM plantillas_evidencia WHERE tipo_orden=? AND id IS NOT ?', (d['tipo_orden'], pid), one=True): err = 'Ese tipo de orden ya está ligado a otra plantilla'
            if not err:
                vals = (d['nombre'], d['descripcion'], d['tipo_orden'], json.dumps(d['fotos'], ensure_ascii=False), json.dumps(d['reportes'], ensure_ascii=False), json.dumps(d['materiales'], ensure_ascii=False), d['activo'])
                if r: db().execute("UPDATE plantillas_evidencia SET nombre=?,descripcion=?,tipo_orden=?,fotos=?,reportes=?,materiales=?,activo=?,actualizado=datetime('now','localtime') WHERE id=?", vals + (pid,))
                else: pid = db().execute('INSERT INTO plantillas_evidencia(nombre,descripcion,tipo_orden,fotos,reportes,materiales,activo,clave,orden) VALUES(?,?,?,?,?,?,?,?,(SELECT COALESCE(MAX(orden),0)+1 FROM plantillas_evidencia))', vals + (clave,)).lastrowid
                db().commit(); return redirect(url_for('evid_ver', pid=pid))
            p = dict(p, clave=clave, **d)
        return render_template('evid_form.html', p=p, pid=pid, err=err, tipos_orden=tipos_orden)

    @app.route('/catalogo')
    def catalogo():  # ruta anterior "Plantillas": se conserva y redirige
        k = request.args.get('plantilla')
        r = q('SELECT id FROM plantillas_evidencia WHERE clave=?', (k,), one=True) if k else None
        return redirect(url_for('evid_ver', pid=r['id']) if r else url_for('evid_lista'))
