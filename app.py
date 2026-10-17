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

import auth_mod as AU
import perm_mod as PERM
AU.registrar(app, lambda *a, **k: q(*a, **k), lambda: db(), CFG)
import plantillas_mod as PM
PM.JSON = os.path.join(BASE, 'plantillas.json'); PM.DB = DB
PLANT = PM.Plantillas()  # plantillas de Reporte de evidencias (BD; ver plantillas_mod.py)

# ---- Catálogos tomados de los formatos de Excel ----
CATEGORIAS = {
 'EJ-FO': 'Orden de ejecución - Red de Fibra Óptica',
 'EJ-MO': 'Orden de ejecución - Red de Microondas',
 'EJ-EQ': 'Orden de ejecución - Equipo activo y sitios',
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
# ---- Clasificación de órdenes (dos niveles) ----
CLASES = {'infra': 'Infraestructura propia', 'cliente': 'Clientes', 'prospecto': 'Prospecto'}
REDES = {'fibra': 'Red de fibra óptica', 'microondas': 'Red de microondas', 'equipo': 'Equipo activo y sitios'}
TRABAJOS = {'infra': ['Instalación nueva', 'Mantenimiento preventivo', 'Mantenimiento correctivo'],
            'cliente': ['Instalación nueva', 'Mantenimiento preventivo', 'Mantenimiento correctivo', 'Factibilidad', 'Desinstalación'],
            'prospecto': ['Factibilidad']}
FACTIBILIDAD = 'Factibilidad'
CAT_DE_RED = {'fibra': 'EJ-FO', 'microondas': 'EJ-MO', 'equipo': 'EJ-EQ'}
_EQ_CONS = ['Repetidor Grande (Sitio de Concreto)','Repetidor Grande (Gabinete p/ Ext)','Repetidor Chico (Gabinete p/Exterior)','Circuito de Tierra Física','Sistema de Energía de Emergencia']
_EQ_PREV = ['Revisión de POE/Electricidad','Revisión de Torre/Sitio']
TIPOS['EJ-EQ'] = {'Mantenimiento correctivo': ['Reparación por Daño','Reparación por Modificación','Falla de energía','Falla de equipo activo','Otros'],
                  'Mantenimiento preventivo': _EQ_PREV + ['Revisión de equipo activo (Router/Switch/Radio)','Revisión de energía (UPS/Solar/Generador)','Otros'],
                  'Construcción': _EQ_CONS + ['Instalación de equipo activo (Router/Switch)','Otros']}
TIPOS['EJ-MO']['Construcción'] = [t for t in TIPOS['EJ-MO']['Construcción'] if t not in _EQ_CONS]
TIPOS['EJ-MO']['Mantenimiento preventivo'] = [t for t in TIPOS['EJ-MO']['Mantenimiento preventivo'] if t not in _EQ_PREV] + ['Revisión de alineación/enlace']
INSTALACIONES = TIPOS['INST']['Tipo de instalación']
GRUPO_DE_TRABAJO = {'Instalación nueva': 'Construcción', 'Mantenimiento preventivo': 'Mantenimiento preventivo', 'Mantenimiento correctivo': 'Mantenimiento correctivo'}
def detalles(red, trabajo):
    """Opciones de 'Detalle' (tipo_orden) para una orden de infraestructura propia."""
    T = TIPOS[CAT_DE_RED[red]]; g = GRUPO_DE_TRABAJO.get(trabajo)
    return (T.get(g, []) + (T.get('Ingeniería', []) if trabajo == 'Instalación nueva' else [])) if g else []
DETALLES = {r: {t: detalles(r, t) for t in TRABAJOS['infra']} for r in REDES}

def clasificar_legado(cat, grupo, tipo):
    """Orden antigua (categoria/tipo_grupo/tipo_orden) -> (clase, red, trabajo)."""
    if cat == 'INST' or not cat: return 'cliente', None, 'Instalación nueva'
    red = 'fibra' if cat == 'EJ-FO' else ('equipo' if cat == 'EJ-EQ' or tipo in _EQ_CONS + _EQ_PREV else 'microondas')
    trabajo = {'Construcción': 'Instalación nueva', 'Ingeniería': 'Instalación nueva'}.get(grupo, grupo if grupo in TRABAJOS['infra'] else 'Instalación nueva')
    return 'infra', red, trabajo

def migrar_ordenes(c):
    cols = [r[1] for r in c.execute('PRAGMA table_info(ordenes)')]
    for col in ('clase', 'red', 'trabajo', 'clasif_otro'):
        if col not in cols: c.execute(f'ALTER TABLE ordenes ADD COLUMN {col} TEXT')
    c.execute('CREATE TABLE IF NOT EXISTS orden_sitios(orden_id INTEGER NOT NULL REFERENCES ordenes(id) ON DELETE CASCADE, site_id INTEGER NOT NULL REFERENCES sitios(id) ON DELETE CASCADE, PRIMARY KEY(orden_id, site_id))')
    for oid, cat, grp, tipo in c.execute('SELECT id, categoria, tipo_grupo, tipo_orden FROM ordenes WHERE clase IS NULL').fetchall():
        cl, red, tr = clasificar_legado(cat, grp, tipo)
        nc = 'INST' if cl == 'cliente' else CAT_DE_RED[red]
        ng = (tr if cl == 'cliente' else (grp if nc == cat else GRUPO_DE_TRABAJO[tr]))
        c.execute('UPDATE ordenes SET clase=?, red=?, trabajo=?, categoria=?, tipo_grupo=? WHERE id=?', (cl, red, tr, nc, ng, oid))
    c.execute("UPDATE ordenes SET trabajo='Instalación nueva' WHERE clase='cliente' AND trabajo='Instalación'")
    c.execute("UPDATE ordenes SET trabajo='Factibilidad' WHERE clase='cliente' AND trabajo='Estudio de factibilidad'")
    # órdenes cuyo cliente sigue siendo prospecto -> categoría Prospecto (Factibilidad)
    c.execute("UPDATE ordenes SET clase='prospecto', trabajo='Factibilidad' WHERE clase='cliente' AND cliente_id IN (SELECT id FROM clientes WHERE estatus='Prospecto')")
    c.execute("UPDATE ordenes SET tipo_grupo=trabajo WHERE clase IN ('cliente','prospecto') AND COALESCE(tipo_grupo,'')<>trabajo")
    c.execute('INSERT OR IGNORE INTO orden_sitios(orden_id, site_id) SELECT id, site_id FROM ordenes WHERE site_id IS NOT NULL AND site_id IN (SELECT id FROM sitios)')
    c.execute('CREATE INDEX IF NOT EXISTS ix_ord_clase ON ordenes(clase, red, trabajo)')
    migrar_personal(c)
    AU.migrar(c)
    migrar_autorizacion(c)

def migrar_personal(c):
    """Liga órdenes con Configuración › Personal: quien ordena, responsable (ejecutó), técnicos y quien auditó."""
    cols = [r[1] for r in c.execute('PRAGMA table_info(ordenes)')]
    nuevas = [k for k in ('ordena_personal_id', 'responsable_id', 'audito_personal_id') if k not in cols]
    for col in nuevas: c.execute(f'ALTER TABLE ordenes ADD COLUMN {col} INTEGER REFERENCES tecnicos(id) ON DELETE SET NULL')
    if 'personal_ok' not in cols: c.execute('ALTER TABLE ordenes ADD COLUMN personal_ok INTEGER')
    c.execute("CREATE TABLE IF NOT EXISTS orden_personal(orden_id INTEGER NOT NULL REFERENCES ordenes(id) ON DELETE CASCADE, personal_id INTEGER NOT NULL REFERENCES tecnicos(id) ON DELETE CASCADE, PRIMARY KEY(orden_id, personal_id))")
    P = 'AND personal_ok IS NULL'   # solo órdenes aún no mapeadas (las guardadas desde el formulario quedan con personal_ok=1)
    norm = "LOWER(TRIM({}))"
    for txt, col in (('ordena_nombre', 'ordena_personal_id'), ('audito_nombre', 'audito_personal_id')):   # nombres en texto libre que coinciden con Personal
        c.execute(f"UPDATE ordenes SET {col}=(SELECT MIN(t.id) FROM tecnicos t WHERE {norm.format('t.nombre')}={norm.format('ordenes.'+txt)}) WHERE {col} IS NULL AND TRIM(COALESCE({txt},''))<>'' {P}")
    # responsable = líder de la cuadrilla asignada; técnicos = resto de la cuadrilla (lo que ya imprimía el formato)
    c.execute(f"UPDATE ordenes SET responsable_id=(SELECT MIN(t.id) FROM tecnicos t WHERE t.cuadrilla_id=ordenes.cuadrilla_id AND t.rol='líder') WHERE responsable_id IS NULL AND cuadrilla_id IS NOT NULL {P}")
    c.execute("INSERT OR IGNORE INTO orden_personal SELECT o.id, t.id FROM ordenes o JOIN tecnicos t ON t.cuadrilla_id=o.cuadrilla_id AND t.rol='técnico' WHERE o.cuadrilla_id IS NOT NULL AND o.personal_ok IS NULL")
    for oid, extra in c.execute("SELECT id, personas_adicionales FROM ordenes WHERE TRIM(COALESCE(personas_adicionales,''))<>'' AND personal_ok IS NULL").fetchall():   # personas adicionales que coinciden
        resto = []
        for n in [x.strip() for x in extra.replace(';', ',').split(',') if x.strip()]:
            t = c.execute('SELECT id FROM tecnicos WHERE LOWER(TRIM(nombre))=LOWER(?)', (n,)).fetchone()
            if t: c.execute('INSERT OR IGNORE INTO orden_personal VALUES(?,?)', (oid, t[0]))
            else: resto.append(n)
        c.execute('UPDATE ordenes SET personas_adicionales=? WHERE id=?', (', '.join(resto) or None, oid))
    c.execute('UPDATE ordenes SET personal_ok=1 WHERE personal_ok IS NULL')

def personal_orden(o):
    """Responsable + técnicos de la orden (Personal); si la orden no tiene, los integrantes de su cuadrilla."""
    resp = q('SELECT *, \'líder\' rol_orden FROM tecnicos WHERE id=?', (o['responsable_id'],), one=True) if o['responsable_id'] else None
    tecs = q('SELECT t.*, \'técnico\' rol_orden FROM orden_personal op JOIN tecnicos t ON t.id=op.personal_id WHERE op.orden_id=? AND t.id IS NOT ? ORDER BY t.nombre', (o['id'], o['responsable_id']))
    if resp or tecs: return [dict(r, rol=r['rol_orden']) for r in ([resp] if resp else []) + list(tecs)]
    return [dict(r) for r in q("SELECT * FROM tecnicos WHERE cuadrilla_id=? ORDER BY CASE rol WHEN 'líder' THEN 0 ELSE 1 END", (o['cuadrilla_id'],))] if o['cuadrilla_id'] else []

def plantilla_de(o):
    k = PM.ligada_a(o['tipo_orden'])  # plantilla ligada explícitamente a este tipo de orden (Configuración › Reporte de evidencias)
    if k: return k
    try: clase, red, trabajo = o['clase'], o['red'], o['trabajo']
    except (KeyError, IndexError): clase, red, trabajo = clasificar_legado(o['categoria'], None, o['tipo_orden'])
    if clase == 'infra': return {'fibra': 'FO', 'microondas': 'MO', 'equipo': 'MO'}.get(red)
    return PM.por_tipo_orden(o['tipo_orden'])   # clientes: la clasificación (FO, MO, SAT, FO P-P, MO P-P, Wi-Fi, Router) define la plantilla en cualquier variante
ESTADOS = ['pendiente','asignada','en curso','completada','cancelada']
PRIORIDADES = ['baja','media','alta','urgente']
PUESTOS_ORDENA = ['Director','Gerente','Ejecutivo comercial','Supervisor']   # casillas del formato impreso (Gerente = cualquier «Gerente…»)
PUESTOS_EJEC = ['Supervisor','Técnico Instalador','Proveedor Externo']
PUESTOS_AUD = ['Director','Gerente','Supervisor']   # formato impreso
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
CREATE TABLE IF NOT EXISTS materiales(id INTEGER PRIMARY KEY, sku TEXT UNIQUE NOT NULL, nombre TEXT NOT NULL, categoria TEXT, variantes TEXT, unidad TEXT DEFAULT 'pza',
 stock_actual REAL NOT NULL DEFAULT 0, stock_minimo REAL NOT NULL DEFAULT 0, ubicacion TEXT, activo INTEGER DEFAULT 1, notas TEXT, ejemplo INTEGER DEFAULT 0, creado TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS movimientos(id INTEGER PRIMARY KEY, material_id INTEGER NOT NULL REFERENCES materiales(id), tipo TEXT NOT NULL CHECK(tipo IN ('entrada','salida','ajuste','devolucion','transferencia')),
 almacen_id INTEGER REFERENCES almacenes(id), fecha TEXT NOT NULL, cantidad REAL NOT NULL, stock_resultante REAL, motivo TEXT, referencia TEXT, orden_id INTEGER REFERENCES ordenes(id) ON DELETE SET NULL, usuario TEXT);
CREATE TABLE IF NOT EXISTS almacenes(id INTEGER PRIMARY KEY, nombre TEXT UNIQUE NOT NULL, tipo TEXT DEFAULT 'bodega' CHECK(tipo IN ('bodega','vehiculo')), cuadrilla_id INTEGER REFERENCES cuadrillas(id) ON DELETE SET NULL, activo INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS existencias(material_id INTEGER NOT NULL REFERENCES materiales(id) ON DELETE CASCADE, almacen_id INTEGER NOT NULL REFERENCES almacenes(id), stock REAL NOT NULL DEFAULT 0, minimo REAL NOT NULL DEFAULT 0, PRIMARY KEY(material_id, almacen_id));
CREATE INDEX IF NOT EXISTS ix_mov_mat ON movimientos(material_id, fecha);
CREATE INDEX IF NOT EXISTS ix_mov_orden ON movimientos(orden_id);
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
def hoy(): return AU.ahora_mx()[:10]
def ahora(): return AU.ahora_mx()   # hora de Ciudad de México aunque el servidor (Render) esté en UTC
def log(oid, t): db().execute('INSERT INTO bitacora(orden_id,fecha,texto) VALUES(?,?,?)', (oid, ahora(), t))

@app.context_processor
def ctx(): return dict(CLASES=CLASES, REDES=REDES, TRABAJOS=TRABAJOS, DETALLES=DETALLES, INSTALACIONES=INSTALACIONES, FACTIBILIDAD=FACTIBILIDAD, ESTADOS=ESTADOS, PRIORIDADES=PRIORIDADES, CATEGORIAS=CATEGORIAS, TIPOS=TIPOS, PUESTOS_ORDENA=PUESTOS_ORDENA,
    PUESTOS_EJEC=PUESTOS_EJEC, PUESTOS_AUD=PUESTOS_AUD, TIPOS_CLIENTE=TIPOS_CLIENTE, hoy=hoy(), tipos_json=json.dumps(TIPOS, ensure_ascii=False))

VENCIDA = "(o.estado NOT IN ('completada','cancelada') AND o.fecha_programada < date('now','localtime'))"

@app.route('/')
def dashboard():
    S, SA = PERM.orden_scope('o')   # el panel solo cuenta las órdenes que el perfil puede ver
    por_estado = {e: 0 for e in ESTADOS}
    for r in q(f'SELECT estado, COUNT(*) n FROM ordenes o WHERE {S} GROUP BY estado', SA): por_estado[r['estado']] = r['n']
    por_cuad = q(f'''SELECT c.id, c.nombre, COUNT(o.id) total, SUM(o.estado='completada') comp, SUM(o.estado IN ('pendiente','asignada','en curso')) abiertas,
        SUM({VENCIDA}) venc FROM cuadrillas c LEFT JOIN ordenes o ON o.cuadrilla_id=c.id AND {S} GROUP BY c.id {'' if PERM.alcance()[0] in ('todas','tipo') else 'HAVING COUNT(o.id)>0'} ORDER BY c.id''', SA)
    vencidas = q(f'SELECT o.*, c.nombre cuad FROM ordenes o LEFT JOIN cuadrillas c ON c.id=o.cuadrilla_id WHERE {VENCIDA} AND {S} ORDER BY o.fecha_programada LIMIT 50', SA)
    por_cat = q(f"SELECT clase, red, trabajo, COUNT(*) n, SUM(estado IN ('pendiente','asignada','en curso')) abiertas FROM ordenes o WHERE {S} GROUP BY clase, red, trabajo ORDER BY clase='cliente', red, trabajo", SA)
    pend_autoriz = q(f"SELECT COUNT(*) n, SUM(autorizacion='rechazada') r FROM ordenes o WHERE autorizacion IN ('pendiente','rechazada') AND {S}", SA, one=True)
    hoy_n = q(f"SELECT COUNT(*) n FROM ordenes o WHERE fecha_programada=date('now','localtime') AND {S}", SA, one=True)['n']
    pend_aud = q(f"SELECT COUNT(*) n FROM ordenes o WHERE estado='completada' AND (aprobacion IS NULL OR aprobacion='') AND {S}", SA, one=True)['n']
    stock_alm = q(f"SELECT a.id, a.nombre, a.tipo, c.nombre cuad, COUNT(CASE WHEN e.stock>0 THEN 1 END) n, SUM(CASE WHEN e.stock<0 THEN 1 ELSE 0 END) neg, SUM(CASE WHEN m.activo=1 AND {BAJO_ALM} THEN 1 ELSE 0 END) bajo FROM almacenes a LEFT JOIN existencias e ON e.almacen_id=a.id LEFT JOIN materiales m ON m.id=e.material_id LEFT JOIN cuadrillas c ON c.id=a.cuadrilla_id GROUP BY a.id ORDER BY a.tipo='vehiculo', CASE WHEN a.tipo='bodega' THEN a.id END, a.nombre")
    bajo_min = q(f'''SELECT m.id, m.sku, m.nombre, m.unidad, a.nombre alm, e.stock, e.minimo FROM existencias e JOIN materiales m ON m.id=e.material_id JOIN almacenes a ON a.id=e.almacen_id
        WHERE m.activo=1 AND {BAJO_ALM} ORDER BY (e.stock - e.minimo) / e.minimo LIMIT 10''')
    nbajo = q(f'SELECT COUNT(*) n FROM materiales m WHERE {BAJO_ALGUNO}', one=True)['n']
    bat_cambio = q(f"""SELECT * FROM (
        SELECT id, codigo, nombre, 'Solar' fuente, NULL ups_id, solar_num_baterias num_baterias, solar_bat_marca marca, solar_bat_cambio cambio, alerta FROM (SELECT *, {CM.BAT_ALERTA_SQL} alerta FROM sitios WHERE activo=1)
        UNION ALL SELECT id, codigo, nombre, 'UPS', ups_id, num_baterias, TRIM(COALESCE(marca,'')||' '||(CASE WHEN capacidad_kva=CAST(capacidad_kva AS INT) THEN CAST(capacidad_kva AS INT) ELSE capacidad_kva END)||'kVA'), bat_cambio, alerta FROM ({UPS.PANEL_SQL})
        ) WHERE alerta IS NOT NULL ORDER BY cambio""")
    contratos = q(f"SELECT id, codigo, nombre, tenencia, CASE tenencia WHEN 'Rentado' THEN arr_nombre ELSE int_nombre END contraparte, vence, CASE WHEN tenencia='Rentado' THEN arr_renta END arr_renta, alerta FROM (SELECT *, {SD.VENCE_SQL} vence, {SD.ALERTA_SQL} alerta FROM sitios WHERE activo=1) WHERE alerta IS NOT NULL ORDER BY vence")
    total = sum(por_estado.values()); maxc = max([r['total'] for r in por_cuad] + [1])
    return render_template('dashboard.html', pend_autoriz=pend_autoriz, por_estado=por_estado, por_cuad=por_cuad, vencidas=vencidas, total=total, maxc=maxc, por_cat=por_cat, hoy_n=hoy_n, pend_aud=pend_aud, bajo_min=bajo_min, nbajo=nbajo, stock_alm=stock_alm, bat_cambio=bat_cambio, contratos=contratos, hoy=dt.date.today())

# ---------- Órdenes ----------
@app.route('/ordenes')
def ordenes():
    f = {k: request.args.get(k, '') for k in ('estado','cuadrilla','cliente','desde','hasta','categoria','clase','red','trabajo','clasif','aut','buscar','vencidas')}
    S, SA = PERM.orden_scope('o')
    w, a = [S], list(SA)
    for k in ('clase','red','trabajo'):
        if f[k]: w.append(f'o.{k}=?'); a.append(f[k])
    if f['estado']: w.append('o.estado=?'); a.append(f['estado'])
    if f['cuadrilla']: w.append('o.cuadrilla_id=?'); a.append(f['cuadrilla'])
    if f['categoria']: w.append('o.categoria=?'); a.append(f['categoria'])
    if f['cliente']: w.append('o.cliente LIKE ?'); a.append('%'+f['cliente']+'%')
    if f.get('clasif'): w.append('o.tipo_orden=?'); a.append(f['clasif'])
    if f.get('aut') in ('pendiente', 'rechazada', 'autorizada'): w.append('o.autorizacion=?'); a.append(f['aut'])
    if f['buscar']: w.append('(o.folio LIKE ? OR o.sitio LIKE ? OR o.tipo_orden LIKE ? OR o.cliente LIKE ? OR o.clasif_otro LIKE ?)'); a += ['%'+f['buscar']+'%']*5
    if f['desde']: w.append('o.fecha_programada>=?'); a.append(f['desde'])
    if f['hasta']: w.append('o.fecha_programada<=?'); a.append(f['hasta'])
    if f['vencidas']: w.append(VENCIDA)
    where = ' AND '.join(w)
    total = q(f'SELECT COUNT(*) n FROM ordenes o WHERE {where}', a, one=True)['n']
    per = 20; pages = max(1, math.ceil(total/per)); page = min(max(1, int(request.args.get('page', 1) or 1)), pages)
    rows = q(f'SELECT o.*, c.nombre cuad, {VENCIDA} vencida, cl.estatus cli_estatus, (SELECT nombre||COALESCE(\' — \'||puesto,\'\') FROM tecnicos WHERE id=o.responsable_id) resp_txt, (SELECT COUNT(*) FROM orden_personal op WHERE op.orden_id=o.id AND op.personal_id IS NOT o.responsable_id) n_tecs, (SELECT GROUP_CONCAT(st.codigo, \', \') FROM orden_sitios os JOIN sitios st ON st.id=os.site_id WHERE os.orden_id=o.id) sites_txt FROM ordenes o LEFT JOIN cuadrillas c ON c.id=o.cuadrilla_id LEFT JOIN clientes cl ON cl.id=o.cliente_id WHERE {where} ORDER BY o.fecha_programada DESC, o.id DESC LIMIT ? OFFSET ?', a+[per, (page-1)*per])
    clientes = [r['cliente'] for r in q(f'SELECT DISTINCT cliente FROM ordenes o WHERE cliente IS NOT NULL AND {S} ORDER BY cliente', SA)]
    qs = {k: v for k, v in f.items() if v}
    return render_template('ordenes.html', rows=rows, f=f, total=total, page=page, pages=pages, cuadrillas=q('SELECT * FROM cuadrillas ORDER BY id'), clientes=clientes, qs=qs)

CAMPOS = ['ejecutivo_id','clase','red','trabajo','clasif_otro','ordena_personal_id','responsable_id','audito_personal_id','categoria','tipo_grupo','tipo_orden','prioridad','estado','fecha_emision','fecha_programada','fecha_inicio','fecha_cierre','ordena_nombre','ordena_puesto',
 'cliente','cliente_id','tipo_cliente','calle','ciudad','estado_geo','contacto','telefono','coordenadas','coordenadas_b','sitio','site_id','descripcion','cuadrilla_id','ejecuto_puesto',
 'personas_adicionales','observaciones','notas','folio_evidencias','audito_nombre','audito_puesto','fecha_auditoria','aprobacion','obs_auditoria']

def siguiente_folio(cat):
    pref = {'EJ-FO':'FO','EJ-MO':'MO','EJ-EQ':'EQ','INST':'IC'}[cat] + dt.date.today().strftime('%y%m')
    n = q('SELECT COUNT(*) n FROM ordenes WHERE folio LIKE ?', (pref+'%',), one=True)['n']
    while q('SELECT 1 FROM ordenes WHERE folio=?', (f'{pref}{n+1:04d}',), one=True): n += 1
    return f'{pref}{n+1:04d}'

@app.route('/ordenes/nueva', methods=['GET','POST'])
@app.route('/ordenes/<int:oid>/editar', methods=['GET','POST'])
def orden_form(oid=None):
    o = q('SELECT * FROM ordenes WHERE id=?', (oid,), one=True) if oid else None
    if oid and not o: abort(404)
    alc, cats_ok, trab_ok = PERM.alcance()
    tec_sel = [r['personal_id'] for r in q('SELECT personal_id FROM orden_personal WHERE orden_id=?', (oid,))] if oid else []
    err = None; sel_sites = [r['site_id'] for r in q('SELECT site_id FROM orden_sitios WHERE orden_id=?', (oid,))] if oid else []
    if request.method == 'POST':
        d = {k: (request.form.get(k) or '').strip() or None for k in CAMPOS}
        sel_sites = [int(x) for x in request.form.getlist('sites') if x.isdigit() and q('SELECT 1 FROM sitios WHERE id=?', (int(x),), one=True)]
        sel_tecs = [int(x) for x in request.form.getlist('tecnicos') if x.isdigit()]
        err = permisos_orden(d, o, sel_tecs, tec_sel)
        err = err or validar_orden(d, sel_sites, o) or validar_personal(d, sel_tecs, o)
        if not err:
            folio = (request.form.get('folio') or '').strip() or (o['folio'] if o else siguiente_folio(d['categoria']))
            if q('SELECT 1 FROM ordenes WHERE folio=? AND id IS NOT ?', (folio, oid), one=True): err = f'El folio {folio} ya existe'
        if not err:
            aut, aut_log = calc_autorizacion(o, d)
            if aut in ('pendiente', 'rechazada') and d['estado'] not in ('pendiente', 'cancelada'):
                d['estado'] = 'pendiente'; aut_log = (aut_log + ' · ' if aut_log else '') + 'estado se mantiene pendiente hasta autorizar'
            if d['cuadrilla_id'] and d['estado'] == 'pendiente' and aut not in ('pendiente', 'rechazada'): d['estado'] = 'asignada'
            if d['estado'] == 'completada' and not d['fecha_cierre']: d['fecha_cierre'] = ahora()
            if o:
                db().execute(f"UPDATE ordenes SET folio=?, {', '.join(k+'=?' for k in CAMPOS)} WHERE id=?", [folio]+[d[k] for k in CAMPOS]+[oid])
                if o['estado'] != d['estado']: log(oid, f"Estado: {o['estado']} → {d['estado']} (oficina)")
                if (o['clase'], o['red'], o['trabajo']) != (d['clase'], d['red'], d['trabajo']): log(oid, f"Clasificación: {etiqueta(o)} → {etiqueta(d)}")
            else:
                cur = db().execute(f"INSERT INTO ordenes(folio,{','.join(CAMPOS)}) VALUES(?{',?'*len(CAMPOS)})", [folio]+[d[k] for k in CAMPOS]); oid = cur.lastrowid
                log(oid, 'Orden creada · ' + etiqueta(d))
            if aut == 'pendiente' and (not o or o['autorizacion'] != 'pendiente'):
                db().execute("UPDATE ordenes SET autorizacion='pendiente', aut_solicitada=?, aut_solicito=? WHERE id=?", (ahora(), AU.nombre_actual(), oid))
            elif aut is None: db().execute('UPDATE ordenes SET autorizacion=NULL WHERE id=?', (oid,))
            if aut_log: log(oid, aut_log)
            db().execute('DELETE FROM orden_sitios WHERE orden_id=?', (oid,))
            for sid in sel_sites: db().execute('INSERT OR IGNORE INTO orden_sitios(orden_id, site_id) VALUES(?,?)', (oid, sid))
            db().execute('DELETE FROM orden_personal WHERE orden_id=?', (oid,)); db().execute('UPDATE ordenes SET personal_ok=1 WHERE id=?', (oid,))
            for pid in sel_tecs: db().execute('INSERT OR IGNORE INTO orden_personal(orden_id, personal_id) VALUES(?,?)', (oid, pid))
            db().commit(); return redirect(url_for('orden_ver', oid=oid))
        v = dict(o or {}); v.update(d); v['folio'] = request.form.get('folio') or (o['folio'] if o else '')
        tec_sel = sel_tecs
        for k in ('cliente_id', 'site_id', 'cuadrilla_id', 'ordena_personal_id', 'responsable_id', 'audito_personal_id'): v[k] = int(v[k]) if v.get(k) and str(v[k]).isdigit() else None
    else:
        v = dict(o) if o else {'clase': request.args.get('clase') or 'cliente', 'red': request.args.get('red'), 'trabajo': request.args.get('trabajo')}
        if not o and v['clase'] not in cats_ok: v['clase'] = cats_ok[0] if cats_ok else None
    plant_map = {t: plantilla_de({'tipo_orden': t, 'clase': 'cliente', 'red': None, 'trabajo': None, 'categoria': 'INST'}) for t in INSTALACIONES}
    ids = set(tec_sel) | {v.get(k) for k in ('ordena_personal_id', 'responsable_id', 'audito_personal_id') if v.get(k)}
    personal = q(f"SELECT t.id, t.nombre, t.puesto, t.rol, t.cuadrilla_id, t.activo, c.nombre cuad FROM tecnicos t LEFT JOIN cuadrillas c ON c.id=t.cuadrilla_id WHERE COALESCE(t.activo,1)=1 OR t.id IN ({','.join('?'*len(ids)) or 'NULL'}) ORDER BY t.nombre", list(ids))
    ordenantes = [dict(t, no_aut=not CM.puede_ordenar(t['puesto'])) for t in personal if CM.puede_ordenar(t['puesto']) and t['activo'] != 0 or t['id'] == v.get('ordena_personal_id')]
    CS, CSA = PERM.cliente_scope('clientes')
    trab_form = {k: [t for t in ts if alc != 'tipo' or not trab_ok or t in trab_ok] for k, ts in TRABAJOS.items()}
    ejecutivos = q("SELECT id, nombre, puesto FROM tecnicos WHERE (COALESCE(activo,1)=1 AND (puesto IN ('Ejecutivo comercial','Vendedor','Director','Supervisor') OR puesto LIKE 'Gerente%')) OR id=? ORDER BY nombre", (v.get('ejecutivo_id'),))
    return render_template('orden_form.html', cats_ok=cats_ok, trab_form=trab_form, ejecutivos=ejecutivos, fija_ejecutivo=(alc == 'propias' and not AU.es_su()), o=o, v=v, err=err, plant_map=plant_map, personal=personal, ordenantes=ordenantes, tec_sel=tec_sel, sel_sites=sel_sites, cuadrillas=q('SELECT * FROM cuadrillas ORDER BY id'), sitios=q('SELECT id, codigo, nombre, tipo, municipio, estado FROM sitios WHERE activo=1 OR id IN (SELECT site_id FROM orden_sitios WHERE orden_id=?) OR id=? ORDER BY codigo', (oid, (o['site_id'] if o else None))),
        clientes_cat=q(f"SELECT *, COALESCE(estatus,'Cliente') estatus FROM clientes WHERE (activo=1 AND {CS}) OR id=? ORDER BY estatus='Prospecto', nombre", CSA + [(o['cliente_id'] if o else None)]), ESTADOS_MX=CM.ESTADOS_MX)

def permisos_orden(d, o, sel_tecs, tec_prev):
    """Aplica la matriz de permisos al guardar una orden: categoría/variante y clientes del alcance, asignación, estado y propietario."""
    alc, cats, trab = PERM.alcance(); su = AU.es_su(); u = AU.usuario_actual()
    if not su:
        if d['clase'] not in cats: return f"Tu perfil no puede crear ni editar órdenes de la categoría «{CLASES.get(d['clase'], d['clase'] or '—')}»"
        if alc == 'tipo' and trab and d['trabajo'] not in trab: return f"Tu perfil solo maneja: {', '.join(trab)}"
        if d['cliente_id'] and str(d['cliente_id']).isdigit() and d['clase'] != 'infra' and not PERM.cliente_visible(int(d['cliente_id'])) and not (o and str(o['cliente_id']) == str(d['cliente_id'])):
            return 'Ese cliente no está asignado a ti'
    if not PERM.can('ordenes.asignar'):   # sin permiso de asignar: se conservan cuadrilla, responsable y técnicos
        d['cuadrilla_id'] = str(o['cuadrilla_id']) if o and o['cuadrilla_id'] else None
        d['responsable_id'] = str(o['responsable_id']) if o and o['responsable_id'] else None
        sel_tecs[:] = list(tec_prev) if o else []
    prev = o['estado'] if o else 'pendiente'
    if d['estado'] != prev:
        if d['estado'] == 'cancelada' and not PERM.can('ordenes.cancelar'): return 'Tu perfil no puede cancelar órdenes'
        if d['estado'] != 'cancelada' and not PERM.can('ordenes.estado'): d['estado'] = prev
    if d['estado'] is None: d['estado'] = prev
    ej = d.get('ejecutivo_id')
    if not su and alc == 'propias': d['ejecutivo_id'] = o['ejecutivo_id'] if o else u['id']
    elif ej and str(ej).isdigit() and q('SELECT 1 FROM tecnicos WHERE id=?', (int(ej),), one=True): d['ejecutivo_id'] = int(ej)
    else: d['ejecutivo_id'] = None if o else (u['id'] if u else None)   # nueva: propietario = quien la crea
    return None

# ---- Autorización de órdenes (clientes · Instalación nueva) ----
CAMPOS_CLAVE_AUT = ('clase', 'trabajo', 'cliente_id', 'tipo_orden', 'clasif_otro')
def requiere_aut(o): return o['clase'] == 'cliente' and o['trabajo'] == 'Instalación nueva'
def bloqueada(o):
    try: return requiere_aut(o) and o['autorizacion'] != 'autorizada'
    except (KeyError, IndexError): return False
def calc_autorizacion(o, d):
    """Nuevo estado de autorización al guardar desde el formulario -> (autorizacion, texto para bitácora)."""
    if not requiere_aut(d): return None, ('Ya no requiere autorización' if o and o['autorizacion'] else '')
    if not o: return 'pendiente', 'Enviada a autorización'
    prev = o['autorizacion']
    if prev == 'rechazada': return 'pendiente', 'Corregida y reenviada a autorización'
    if prev == 'autorizada':
        cambio = [k for k in CAMPOS_CLAVE_AUT if str(o[k] or '') != str(d[k] or '')]
        if cambio: return 'pendiente', 'Autorización reiniciada: cambió ' + ', '.join({'clase':'categoría','trabajo':'variante','cliente_id':'cliente','tipo_orden':'clasificación','clasif_otro':'clasificación (Otros)'}[k] for k in cambio)
        return 'autorizada', ''
    return 'pendiente', ('' if prev == 'pendiente' else 'Enviada a autorización')

def migrar_autorizacion(c):
    cols = [r[1] for r in c.execute('PRAGMA table_info(ordenes)')]
    for col, typ in (('autorizacion', 'TEXT'), ('aut_por', 'INTEGER REFERENCES tecnicos(id) ON DELETE SET NULL'), ('aut_por_nombre', 'TEXT'), ('aut_fecha', 'TEXT'), ('aut_motivo', 'TEXT'), ('aut_solicitada', 'TEXT'), ('aut_solicito', 'TEXT')):
        if col not in cols: c.execute(f'ALTER TABLE ordenes ADD COLUMN {col} {typ}')
    # órdenes anteriores: ya autorizadas por «migración» para no bloquear nada
    c.execute("UPDATE ordenes SET autorizacion='autorizada', aut_por_nombre='migración', aut_fecha=COALESCE(fecha_emision, substr(creado,1,10)) WHERE clase='cliente' AND trabajo='Instalación nueva' AND autorizacion IS NULL")
    c.execute('CREATE INDEX IF NOT EXISTS ix_ord_aut ON ordenes(autorizacion)')

def exigir_autorizada(o, campo=False):
    """Bloquea ejecución (estado, evidencias, materiales) mientras la orden no esté autorizada."""
    if bloqueada(o):
        msg = 'Orden pendiente de autorización' if o['autorizacion'] == 'pendiente' else 'Orden rechazada: corrígela y reenvíala a autorización'
        abort(409, msg)

@app.before_request
def _alcance():
    """Una orden o cliente fuera del alcance del perfil no se puede abrir ni modificar (403)."""
    import re
    if not getattr(g, 'user', None): return   # superadmin o rutas sin sesión
    m = re.match(r'^/ordenes/(\d+)(/|$)', request.path)
    if m and q('SELECT 1 FROM ordenes WHERE id=?', (int(m.group(1)),), one=True) and not PERM.orden_visible(int(m.group(1))): abort(403)
    m = re.match(r'^/configuracion/clientes/(\d+)/', request.path)
    if m and not PERM.cliente_visible(int(m.group(1))): abort(403)

@app.errorhandler(409)
def _409(e):
    return render_template('prohibido.html', titulo='Orden bloqueada', mensaje=e.description), 409

@app.route('/ordenes/<int:oid>/autorizar', methods=['POST'])
def orden_autorizar(oid):
    o = q('SELECT * FROM ordenes WHERE id=?', (oid,), one=True) or abort(404)
    if not AU.puede_autorizar(): abort(403)
    if not requiere_aut(o) or o['autorizacion'] != 'pendiente': return redirect(url_for('orden_ver', oid=oid))
    acc = request.form.get('accion'); motivo = (request.form.get('motivo') or '').strip()
    u = AU.usuario_actual(); quien = AU.nombre_actual(); cuando = ahora()
    if acc == 'autorizar':
        db().execute("UPDATE ordenes SET autorizacion='autorizada', aut_por=?, aut_por_nombre=?, aut_fecha=?, aut_motivo=NULL, estado=CASE WHEN estado='pendiente' AND cuadrilla_id IS NOT NULL THEN 'asignada' ELSE estado END WHERE id=?", (u['id'] if u else None, quien, cuando, oid))
        log(oid, f'✅ Autorizada por {quien}')
    elif acc == 'rechazar':
        if not motivo: return redirect(url_for('orden_ver', oid=oid, err='Escribe el motivo del rechazo') + '#aut')
        db().execute("UPDATE ordenes SET autorizacion='rechazada', aut_por=?, aut_por_nombre=?, aut_fecha=?, aut_motivo=? WHERE id=?", (u['id'] if u else None, quien, cuando, motivo, oid))
        log(oid, f'⛔ Rechazada por {quien} · Motivo: {motivo}')
    else: abort(400)
    db().commit(); return redirect(url_for('orden_ver', oid=oid))

def validar_personal(d, sel_tecs, o=None):
    """Personal elegido: debe existir (activo, salvo que ya estuviera en la orden); copia nombre/puesto a los campos del formato."""
    for k in ('ordena_personal_id', 'responsable_id', 'audito_personal_id'):
        if d[k] and not str(d[k]).isdigit(): d[k] = None
    todos = [int(d[k]) for k in ('ordena_personal_id', 'responsable_id', 'audito_personal_id') if d[k]] + sel_tecs
    if todos:
        ok = {r['id']: r for r in q(f"SELECT id, nombre, puesto FROM tecnicos WHERE id IN ({','.join('?'*len(todos))})", todos)}
        if any(i not in ok for i in todos): return 'Persona no encontrada en Configuración › Personal'
        if d['ordena_personal_id']:
            p = ok[int(d['ordena_personal_id'])]
            sin_cambio = o is not None and str(o['ordena_personal_id']) == str(d['ordena_personal_id'])
            if not CM.puede_ordenar(p['puesto']) and not sin_cambio:
                return f"«{p['nombre']}» ({p['puesto'] or 'sin puesto'}) no puede ordenar: la persona que ordena debe ser Supervisor, Gerente, Director o Ejecutivo comercial"
        if d['ordena_personal_id']: p = ok[int(d['ordena_personal_id'])]; d['ordena_nombre'], d['ordena_puesto'] = p['nombre'], p['puesto'] or d['ordena_puesto']
        if d['audito_personal_id']: p = ok[int(d['audito_personal_id'])]; d['audito_nombre'], d['audito_puesto'] = p['nombre'], p['puesto'] or d['audito_puesto']
        if d['responsable_id'] and not d['ejecuto_puesto'] and ok[int(d['responsable_id'])]['puesto'] in PUESTOS_EJEC: d['ejecuto_puesto'] = ok[int(d['responsable_id'])]['puesto']
    if d['responsable_id'] and int(d['responsable_id']) in sel_tecs: sel_tecs.remove(int(d['responsable_id']))
    return None

def etiqueta(o):
    if o['clase'] == 'infra': return f"Infraestructura propia › {REDES.get(o['red'], '?')} › {o['trabajo']}"
    return f"{CLASES.get(o['clase'], 'Clientes')} › {o['tipo_orden'] if o['tipo_orden'] != 'Otros' else 'Otros: ' + (o['clasif_otro'] or '')} › {o['trabajo']}"

def validar_orden(d, sel_sites, o=None):
    """Valida la clasificación de dos niveles y normaliza campos derivados (categoria, tipo_grupo, cliente, sitio). Devuelve mensaje de error o None."""
    if d['clase'] not in CLASES: return 'Elige la categoría: Infraestructura propia o Clientes'
    if d['trabajo'] not in TRABAJOS[d['clase']]: return 'Elige el tipo de trabajo'
    if not d['fecha_programada']: return 'La fecha programada es obligatoria'
    if d['clase'] == 'infra':
        if d['red'] not in REDES: return 'Elige la red: fibra óptica, microondas o equipo activo y sitios'
        if d['red'] == 'equipo' and not sel_sites: return 'Las órdenes de «Equipo activo y sitios» requieren al menos un Site del catálogo'
        if d['tipo_orden'] and d['tipo_orden'] not in DETALLES[d['red']][d['trabajo']]: d['tipo_orden'] = None
        d['categoria'] = CAT_DE_RED[d['red']]; d['tipo_grupo'] = GRUPO_DE_TRABAJO[d['trabajo']]
        if d['tipo_orden'] in TIPOS[d['categoria']].get('Ingeniería', []): d['tipo_grupo'] = 'Ingeniería'
        d['cliente_id'] = d['cliente'] = d['tipo_cliente'] = d['clasif_otro'] = None   # infraestructura propia: sin cliente
    else:
        d['red'] = None
        pro = d['clase'] == 'prospecto'
        if not d['cliente_id'] or not str(d['cliente_id']).isdigit(): return 'Elige el prospecto' if pro else 'Elige el cliente'
        cl = q("SELECT nombre, COALESCE(estatus,'Cliente') estatus FROM clientes WHERE id=?", (int(d['cliente_id']),), one=True)
        if not cl: return 'El cliente elegido no existe'
        # una orden Prospecto ya existente conserva su prospecto aunque después se haya convertido a cliente (historial)
        historial = pro and o is not None and o['clase'] == 'prospecto' and str(o['cliente_id']) == str(d['cliente_id'])
        if pro and cl['estatus'] != 'Prospecto' and not historial:
            return f"«{cl['nombre']}» ya es cliente: crea la orden en la categoría Clientes"
        if not pro and cl['estatus'] == 'Prospecto':
            return f"«{cl['nombre']}» es prospecto: usa la categoría Prospecto (Factibilidad) o conviértelo a cliente en Configuración › Clientes"
        d['cliente'] = cl['nombre']
        if d['tipo_orden'] not in INSTALACIONES: return 'Elige la clasificación de la orden (Enlace a Internet vía Fibra Optica, CCTV, Otros…)'
        if d['tipo_orden'] == 'Otros':
            if not d['clasif_otro']: return 'Describe la clasificación «Otros»'
        else: d['clasif_otro'] = None
        d['categoria'] = 'INST'; d['tipo_grupo'] = d['trabajo']
    d['site_id'] = sel_sites[0] if sel_sites else None
    if sel_sites:
        d['sitio'] = ', '.join(f"{r['codigo']} · {r['nombre']}" for r in q(f"SELECT codigo, nombre FROM sitios WHERE id IN ({','.join('?'*len(sel_sites))}) ORDER BY codigo", sel_sites))
    return None

@app.route('/api/prospectos', methods=['POST'])
def api_prospecto():
    """Alta rápida de prospecto desde el formulario de orden (Factibilidad)."""
    j = request.get_json(silent=True) or {}
    g = lambda k: (str(j.get(k) or '')).strip() or None
    d = {k: g(k) for k in ('nombre','contacto','telefono','email','calle','num_ext','colonia','cp','municipio','estado','lat','lng')}
    if not d['nombre']: return jsonify(error='El nombre es obligatorio'), 400
    if d['cp'] and not (len(d['cp']) == 5 and d['cp'].isdigit()): return jsonify(error='Código postal debe tener 5 dígitos'), 400
    if d['telefono'] and len(''.join(ch for ch in d['telefono'] if ch.isdigit())) < 10: return jsonify(error='Teléfono debe tener 10 dígitos'), 400
    if d['email'] and '@' not in d['email']: return jsonify(error='Correo inválido'), 400
    for k in ('lat','lng'):
        if d[k]:
            try: d[k] = float(d[k])
            except ValueError: return jsonify(error='Coordenadas inválidas'), 400
    if q('SELECT 1 FROM clientes WHERE nombre=?', (d['nombre'],), one=True): return jsonify(error='Ya existe un cliente o prospecto con ese nombre'), 400
    calle = ' '.join(x for x in (d['calle'], d['num_ext']) if x) or None
    u = AU.usuario_actual()
    cid = db().execute("INSERT INTO clientes(nombre,contacto,telefono,email,calle,colonia,cp,municipio,ciudad,estado,lat,lng,estatus,activo,ejecutivo_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'Prospecto',1,?)",
        (d['nombre'], d['contacto'], d['telefono'], d['email'], calle, d['colonia'], d['cp'], d['municipio'], d['municipio'], d['estado'], d['lat'], d['lng'], u['id'] if u else None)).lastrowid
    db().commit()
    return jsonify(id=cid, nombre=d['nombre'], estatus='Prospecto', contacto=d['contacto'] or '', telefono=d['telefono'] or '', calle=calle or '', ciudad=d['municipio'] or '', estado=d['estado'] or '', lat=d['lat'], lng=d['lng'])

@app.route('/ordenes/<int:oid>')
def orden_ver(oid):
    o = q("SELECT o.*, c.nombre cuad, cl.estatus cli_estatus FROM ordenes o LEFT JOIN cuadrillas c ON c.id=o.cuadrilla_id LEFT JOIN clientes cl ON cl.id=o.cliente_id WHERE o.id=?", (oid,), one=True) or abort(404)
    p = plantilla_de(o); pl = PLANT.get(p) if p else None
    fotos = {r['item']: r for r in q('SELECT * FROM orden_fotos WHERE orden_id=?', (oid,))}
    return render_template('orden_ver.html', o=o, bloq=bloqueada(o), req_aut=requiere_aut(o), aut_err=request.args.get('err'), sites=q('SELECT s.id, s.codigo, s.nombre, s.tipo FROM orden_sitios os JOIN sitios s ON s.id=os.site_id WHERE os.orden_id=? ORDER BY s.codigo', (oid,)), plantilla=p, pl=pl, fotos=fotos,
        mats=q('SELECT m.*, a.nombre alm FROM orden_materiales m LEFT JOIN almacenes a ON a.id=m.almacen_id WHERE m.orden_id=? ORDER BY m.id', (oid,)), bit=q('SELECT * FROM bitacora WHERE orden_id=? ORDER BY id DESC', (oid,)),
        equipo=personal_orden(o))

@app.route('/ordenes/<int:oid>/eliminar', methods=['POST'])
def orden_eliminar(oid):
    db().execute('DELETE FROM ordenes WHERE id=?', (oid,)); db().commit(); return redirect(url_for('ordenes'))

@app.route('/ordenes/<int:oid>/estado', methods=['POST'])
def orden_estado(oid):
    o = q('SELECT * FROM ordenes WHERE id=?', (oid,), one=True) or abort(404)
    e = request.form['estado']; assert e in ESTADOS
    if not PERM.can('ordenes.cancelar' if e == 'cancelada' else 'ordenes.estado'): abort(403)
    if e != 'cancelada': exigir_autorizada(o)
    sets = {'estado': e}
    if e == 'en curso' and not o['fecha_inicio']: sets['fecha_inicio'] = request.form.get('hora') or ahora()
    if e == 'completada': sets['fecha_cierre'] = request.form.get('hora') or ahora()
    nota = (request.form.get('nota') or '').strip()
    if nota: sets['notas'] = ((o['notas'] or '') + f"\n[{ahora().replace('T',' ')}] {nota}").strip()
    db().execute(f"UPDATE ordenes SET {', '.join(k+'=?' for k in sets)} WHERE id=?", list(sets.values())+[oid])
    log(oid, f"Estado: {o['estado']} → {e}" + (f' · Nota: {nota}' if nota else '') + (' (campo)' if request.form.get('origen')=='campo' else ''))
    db().commit()
    if request.form.get('origen') == 'campo': return redirect(url_campo(o, _anchor=f'o{oid}'))
    return redirect(url_for('orden_ver', oid=oid))

@app.route('/ordenes/<int:oid>/nota', methods=['POST'])
def orden_nota(oid):
    o = q('SELECT * FROM ordenes WHERE id=?', (oid,), one=True) or abort(404)
    nota = (request.form.get('nota') or '').strip()
    if nota:
        db().execute('UPDATE ordenes SET notas=? WHERE id=?', (((o['notas'] or '') + f"\n[{ahora().replace('T',' ')}] {nota}").strip(), oid)); log(oid, 'Nota: '+nota); db().commit()
    if request.form.get('origen') == 'campo': return redirect(url_campo(o, _anchor=f'o{oid}'))
    return redirect(url_for('orden_ver', oid=oid))

@app.route('/ordenes/<int:oid>/materiales', methods=['GET','POST'])
def orden_materiales(oid):
    o = q('SELECT * FROM ordenes WHERE id=?', (oid,), one=True) or abort(404)
    if request.method == 'POST': exigir_autorizada(o)
    p = plantilla_de(o) or request.args.get('plantilla') or 'FO'
    cat = PLANT[p]['materiales']
    porclave = {(r['categoria'], r['nombre']): r for r in q('SELECT * FROM materiales')}
    matid = {r['id']: r for r in porclave.values()}
    warn = None
    if request.method == 'POST':
        lineas = []  # (material_id, seccion, concepto, tipo, cantidad, unidad)
        for i, m in enumerate(cat):
            c = request.form.get(f'q{i}')
            if c and float(c) > 0:
                r = porclave.get((m['seccion'], m['concepto']))
                lineas.append((r['id'] if r else None, m['seccion'], m['concepto'], request.form.get(f't{i}'), float(c), r['unidad'] if r else norm_unidad(m['unidad'])))
        for j in range(int(request.form.get('nextra') or 0)):
            mid_, c = request.form.get(f'em{j}'), request.form.get(f'eq{j}')
            if mid_ and c and float(c) > 0 and int(mid_) in matid:
                r = matid[int(mid_)]; lineas.append((r['id'], 'OTROS MATERIALES', r['nombre'], request.form.get(f'et{j}') or '', float(c), r['unidad']))
        alm = int(request.form.get('almacen_id') or 1); nalm = {r['id']: r['nombre'] for r in almacenes()}
        lineas = [l + (alm if l[0] else None,) for l in lineas]
        con = db(); con.execute('BEGIN IMMEDIATE')
        antes, despues = {}, {}  # clave (material_id, almacen_id)
        for r in con.execute('SELECT material_id, COALESCE(almacen_id,1), SUM(cantidad) s FROM orden_materiales WHERE orden_id=? AND material_id IS NOT NULL GROUP BY 1,2', (oid,)):
            antes[(r[0], r[1])] = r[2]
        for l in lineas:
            if l[0]: despues[(l[0], alm)] = despues.get((l[0], alm), 0) + l[4]
        deltas = {k: despues.get(k, 0) - antes.get(k, 0) for k in set(antes) | set(despues)}
        negs = []
        for k, d in deltas.items():
            st = stock_en(*k)
            if d > 0 and st - d < 0: negs.append(f"{matid[k[0]]['nombre']} en {nalm.get(k[1])} (quedaría en {st-d:g} {matid[k[0]]['unidad']})")
        if negs and not request.form.get('permitir_negativo'):
            con.rollback()
            warn = 'Stock insuficiente: ' + '; '.join(negs) + '. Marca «Permitir stock negativo» para guardar de todos modos, o registra antes una entrada.'
            actual = {l[2]+'|'+l[1]: {'tipo': l[3], 'cantidad': l[4], 'material_id': l[0]} for l in lineas}
            extras = [{'material_id': l[0], 'tipo': l[3], 'cantidad': l[4]} for l in lineas if l[1] == 'OTROS MATERIALES']
            return render_template('materiales.html', o=o, cat=cat, plantilla=p, actual=actual, extras=extras, origen=request.form.get('origen',''), warn=warn, porclave=porclave, mats=mat_opciones(), alms=almacenes(), alm=alm, ex=existencias_map())
        con.execute('DELETE FROM orden_materiales WHERE orden_id=?', (oid,))
        for l in lineas:
            con.execute('INSERT INTO orden_materiales(orden_id,material_id,seccion,concepto,tipo,cantidad,unidad,almacen_id) VALUES(?,?,?,?,?,?,?,?)', (oid,)+l)
        for k, d in sorted(deltas.items(), key=lambda x: x[1]):  # primero devoluciones
            if d > 0: mover(con, k[0], k[1], 'salida', d, 'Consumo en orden', o['folio'], oid, permitir_negativo=True)
            elif d < 0: mover(con, k[0], k[1], 'devolucion', -d, 'Devolución / corrección de orden', o['folio'], oid)
        log(oid, 'Materiales actualizados' + (f' · {sum(1 for d in deltas.values() if d)} movimientos de inventario' if any(deltas.values()) else '') + (' · con stock negativo' if negs else ''))
        con.commit()
        if request.form.get('origen') == 'campo': return redirect(url_campo(o))
        return redirect(url_for('orden_ver', oid=oid))
    filas = q('SELECT * FROM orden_materiales WHERE orden_id=?', (oid,))
    actual = {r['concepto']+'|'+r['seccion']: r for r in filas}
    extras = [r for r in filas if r['seccion'] == 'OTROS MATERIALES']
    veh = q("SELECT id FROM almacenes WHERE tipo='vehiculo' AND cuadrilla_id=? ORDER BY nombre", (o['cuadrilla_id'],), one=True) if o['cuadrilla_id'] else None
    alm = next((r['almacen_id'] for r in filas if r['almacen_id']), None) or int(request.args.get('almacen') or (veh['id'] if veh else 1))
    return render_template('materiales.html', o=o, cat=cat, plantilla=p, actual=actual, extras=extras, origen=request.args.get('origen',''), warn=None, porclave=porclave, mats=mat_opciones(), alms=almacenes(), alm=alm, ex=existencias_map())

@app.route('/ordenes/<int:oid>/foto', methods=['POST'])
def orden_foto(oid):
    o = q('SELECT * FROM ordenes WHERE id=?', (oid,), one=True) or abort(404)
    exigir_autorizada(o)
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
    equipo = personal_orden(o)
    mats = q('SELECT * FROM orden_materiales WHERE orden_id=? ORDER BY id', (oid,))
    fotos = {r['item']: r for r in q('SELECT * FROM orden_fotos WHERE orden_id=?', (oid,))}
    if fmt != 'orden' and not pl:   # sin plantilla: mismas fotos libres que la pantalla de evidencias
        pl = {'fotos': ['Foto libre 1','Foto libre 2','Foto libre 3','Foto libre 4'] + sorted(k for k in fotos if not k.startswith('Foto libre')), 'reportes': []}
    sites = q('SELECT s.codigo, s.nombre FROM orden_sitios os JOIN sitios s ON s.id=os.site_id WHERE os.orden_id=? ORDER BY s.codigo', (oid,))
    return render_template('imprimir_orden.html' if fmt == 'orden' else 'imprimir_evidencias.html', o=o, sites=sites, pl=pl, plantilla=p, equipo=equipo, mats=mats, fotos=fotos)

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
def url_campo(o, **kw):
    """Regreso a la vista técnico; quien solo ve sus órdenes vuelve a «Mis órdenes» si la cuadrilla no es suya."""
    cid = o['cuadrilla_id']
    if PERM.alcance()[0] in ('propias', 'equipo') and not AU.es_su():
        u = AU.usuario_actual()
        if not (cid and (cid == u['cuadrilla_id'] or q('SELECT 1 FROM cuadrillas WHERE id=? AND supervisor_id=?', (cid, u['id']), one=True))): cid = None
    return url_for('tecnico', cuadrilla=cid, **kw)
app.jinja_env.globals['url_campo'] = url_campo

@app.route('/tecnico')
def tecnico():
    S, SA = PERM.orden_scope('o'); alc = PERM.alcance()[0]
    cid = request.args.get('cuadrilla', type=int)
    if alc in ('propias', 'equipo') and not AU.es_su():   # solo «mis órdenes» y las cuadrillas propias / supervisadas
        u = AU.usuario_actual()
        cs = q('SELECT * FROM cuadrillas WHERE id=? OR (? AND supervisor_id=?) ORDER BY id', (u['cuadrilla_id'], alc == 'equipo', u['id']))
        mias = True
        if cid and cid not in [x['id'] for x in cs]: abort(403)
    else:
        cs = q('SELECT * FROM cuadrillas ORDER BY id'); mias = False
        if not cid: return render_template('tecnico_elegir.html', cs=cs)
    if cid: c = q('SELECT * FROM cuadrillas WHERE id=?', (cid,), one=True) or abort(404)
    else: c = {'id': 0, 'nombre': 'Mis órdenes', 'especialidad': ''}
    base = (f"SELECT o.*, {VENCIDA} vencida FROM ordenes o WHERE {S} AND " + ('o.cuadrilla_id=? ' if cid else '1=1 ') +
            "AND NOT (o.clase='cliente' AND o.trabajo='Instalación nueva' AND COALESCE(o.autorizacion,'')<>'autorizada') ")
    args = SA + ([cid] if cid else [])
    de_hoy = q(base + "AND (o.fecha_programada=date('now','localtime') OR (o.estado='completada' AND substr(o.fecha_cierre,1,10)=date('now','localtime'))) ORDER BY CASE o.estado WHEN 'en curso' THEN 0 WHEN 'asignada' THEN 1 WHEN 'pendiente' THEN 1 ELSE 2 END, o.prioridad='urgente' DESC", args)
    ids = [o['id'] for o in de_hoy]
    pend = [o for o in q(base + "AND o.estado IN ('pendiente','asignada','en curso') ORDER BY o.fecha_programada", args) if o['id'] not in ids]
    return render_template('tecnico.html', c=c, cs=cs, mias=mias, de_hoy=de_hoy, pend=pend, equipo=q('SELECT * FROM tecnicos WHERE cuadrilla_id=? ORDER BY rol', (cid,)) if cid else [], ahora=ahora())

@app.route('/reportes/materiales')
def reporte_materiales():
    desde = request.args.get('desde') or (dt.date.today().replace(day=1)).isoformat(); hasta = request.args.get('hasta') or hoy()
    rows = q('''SELECT m.seccion, m.concepto, m.tipo, m.unidad, SUM(m.cantidad) total, COUNT(DISTINCT m.orden_id) ordenes FROM orden_materiales m JOIN ordenes o ON o.id=m.orden_id
       WHERE substr(COALESCE(o.fecha_cierre,o.fecha_programada),1,10) BETWEEN ? AND ? GROUP BY m.seccion,m.concepto,m.tipo,m.unidad ORDER BY m.seccion,m.concepto''', (desde, hasta))
    return render_template('reporte_materiales.html', rows=rows, desde=desde, hasta=hasta)


# ---------- Inventario de materiales ----------
CATS_MAT = ['FIBRA PLANTA EXTERNA','FIBRA PLANTA INTERNA','PLANTA EXTERNA','PLANTA INTERNA','EQUIPOS','EQUIPOS DE RED','GABINETES, RACKS, ACCESORIOS','EQUIPO ELÉCTRICO','MATERIALES CONSUMIBLES','OTROS']
UNIDADES = ['m','pza','rollo','caja','kit','cm','lt','juego']
TIPOS_MOV = {'entrada': 'Entrada', 'salida': 'Salida', 'ajuste': 'Ajuste', 'devolucion': 'Devolución', 'transferencia': 'Transferencia'}
ALMACENES = ['Torrelit', 'Autosound']
def norm_unidad(u):
    return {'metros':'m','pzas.':'pza','pza.':'pza','cms.':'cm','kit':'kit'}.get((u or '').strip(), 'pza')
BAJO = 'm.activo=1 AND m.stock_minimo>0 AND m.stock_actual <= m.stock_minimo'   # total bajo el mínimo global
BAJO_ALM = 'e.minimo>0 AND e.stock <= e.minimo'                                 # por almacén (en tabla existencias e)
BAJO_ALGUNO = f'({BAJO} OR EXISTS(SELECT 1 FROM existencias e WHERE e.material_id=m.id AND {BAJO_ALM}))'
def usuario():
    u = AU.usuario_actual()
    return (f"{u['usuario']} · {u['nombre']}" if u else (CFG['APP_USER'] + ' (superadmin)'))

def mover(con, mid, alm, tipo, cantidad, motivo='', referencia='', orden_id=None, permitir_negativo=False, fecha=None):
    """Registra un movimiento en un almacén y actualiza existencias + stock_actual (total) en la misma transacción.
    cantidad: positiva para entrada/salida/devolución; con signo para ajuste/transferencia."""
    delta = {'entrada': 1, 'devolucion': 1, 'salida': -1, 'ajuste': 1, 'transferencia': 1}[tipo] * float(cantidad)
    if con.execute('SELECT 1 FROM materiales WHERE id=?', (mid,)).fetchone() is None: raise ValueError('Material no existe')
    con.execute('INSERT OR IGNORE INTO existencias(material_id,almacen_id,stock) VALUES(?,?,0)', (mid, alm))
    nuevo = con.execute('SELECT stock FROM existencias WHERE material_id=? AND almacen_id=?', (mid, alm)).fetchone()[0] + delta
    if nuevo < 0 and delta < 0 and not permitir_negativo: raise ValueError('stock negativo')
    con.execute('UPDATE existencias SET stock=stock+? WHERE material_id=? AND almacen_id=?', (delta, mid, alm))
    con.execute('UPDATE materiales SET stock_actual=stock_actual+? WHERE id=?', (delta, mid))
    con.execute('INSERT INTO movimientos(material_id,almacen_id,tipo,fecha,cantidad,stock_resultante,motivo,referencia,orden_id,usuario) VALUES(?,?,?,?,?,?,?,?,?,?)',
                (mid, alm, tipo, fecha or ahora(), delta, nuevo, motivo, referencia, orden_id, usuario() if has_request_context() else 'admin'))
    return nuevo
def stock_en(mid, alm):
    r = db().execute('SELECT stock FROM existencias WHERE material_id=? AND almacen_id=?', (mid, alm)).fetchone(); return r[0] if r else 0
N_VEHICULOS = 18
def asegurar_vehiculos(con):
    # 18 almacenes móviles "Vehículo 01".."Vehículo 18". Cada uno se asigna (reasignable) a una cuadrilla en /vehiculos.
    if con.execute("SELECT 1 FROM almacenes WHERE tipo='vehiculo' LIMIT 1").fetchone(): return  # ya creados; se administran en Configuración
    for i in range(1, N_VEHICULOS + 1):
        con.execute("INSERT OR IGNORE INTO almacenes(nombre,tipo) VALUES(?,'vehiculo')", (f'Vehículo {i:02d}',))
def almacenes():
    return q("SELECT a.*, c.nombre cuad FROM almacenes a LEFT JOIN cuadrillas c ON c.id=a.cuadrilla_id WHERE a.activo=1 ORDER BY a.tipo='vehiculo', CASE WHEN a.tipo='bodega' THEN a.id END, a.nombre")
def minimos_map(): return {(r['material_id'], r['almacen_id']): r['minimo'] for r in q('SELECT material_id, almacen_id, minimo FROM existencias WHERE minimo>0')}
def existencias_map():
    d = {}
    for r in q('SELECT * FROM existencias'): d[(r['material_id'], r['almacen_id'])] = r['stock']
    return d
from flask import has_request_context

def mat_opciones(): return q('SELECT * FROM materiales WHERE activo=1 ORDER BY categoria, nombre')

@app.route('/inventario')
def inventario():
    f = {k: request.args.get(k, '') for k in ('buscar','categoria','bajo','inactivos','almacen')}
    w, a = ['1=1'], []
    if not f['inactivos']: w.append('m.activo=1')
    if f['buscar']: w.append('(m.sku LIKE ? OR m.nombre LIKE ? OR m.variantes LIKE ? OR m.ubicacion LIKE ? OR m.codigo_barras LIKE ?)'); a += ['%'+f['buscar']+'%']*5
    if f['categoria']: w.append('m.categoria=?'); a.append(f['categoria'])
    if f['bajo'] and f['almacen']: w.append(f'EXISTS(SELECT 1 FROM existencias e WHERE e.material_id=m.id AND e.almacen_id=? AND {BAJO_ALM})'); a.append(f['almacen'])
    elif f['bajo']: w.append(BAJO_ALGUNO)
    if f['almacen'] and not f['bajo']: w.append('EXISTS(SELECT 1 FROM existencias e WHERE e.material_id=m.id AND e.almacen_id=? AND e.stock<>0)'); a.append(f['almacen'])
    rows = q(f'SELECT m.*, ({BAJO}) bajo, ({BAJO_ALGUNO}) bajo_alg FROM materiales m WHERE {" AND ".join(w)} ORDER BY m.categoria, m.nombre', a)
    nbajo = q(f'SELECT COUNT(*) n FROM materiales m WHERE {BAJO_ALGUNO}', one=True)['n']
    bajo_por_alm = {r['almacen_id']: r['n'] for r in q(f'SELECT e.almacen_id, COUNT(*) n FROM existencias e JOIN materiales m ON m.id=e.material_id WHERE m.activo=1 AND {BAJO_ALM} GROUP BY 1')}
    if f['almacen']: nbajo = bajo_por_alm.get(int(f['almacen']), 0)
    return render_template('inventario.html', bajo_por_alm=bajo_por_alm, mins=minimos_map(), rows=rows, f=f, CATS_MAT=CATS_MAT, nbajo=nbajo, alms=almacenes(), ex=existencias_map())

@app.route('/inventario/nuevo', methods=['GET','POST'])
@app.route('/inventario/<int:mid>/editar', methods=['GET','POST'])
def material_form(mid=None):
    m = q('SELECT * FROM materiales WHERE id=?', (mid,), one=True) if mid else None
    if mid and not m: abort(404)
    err = None
    if request.method == 'POST':
        d = {k: (request.form.get(k) or '').strip() for k in ('sku','nombre','categoria','variantes','unidad','ubicacion','notas')}
        d['stock_minimo'] = float(request.form.get('stock_minimo') or 0); d['activo'] = 1 if request.form.get('activo') else 0
        d['codigo_barras'] = (request.form.get('codigo_barras') or '').strip() or None
        for k in ('numero_parte','syscom_id','marca','imagen_url'): d[k] = (request.form.get(k) or '').strip() or None
        d['proveedor_id'] = int(request.form['proveedor_id']) if (request.form.get('proveedor_id') or '').isdigit() else None
        if d['imagen_url'] and not (d['imagen_url'].startswith(('https://','http://','/static/','/uploads/'))): d['imagen_url'] = None
        if not d['sku'] or not d['nombre']: err = 'SKU y nombre son obligatorios'
        elif d['codigo_barras'] and q('SELECT 1 FROM materiales WHERE codigo_barras=? AND id IS NOT ?', (d['codigo_barras'], mid), one=True): err = 'Ese código de barras ya está asignado a otro material'
        elif q('SELECT 1 FROM materiales WHERE sku=? AND id IS NOT ?', (d['sku'], mid), one=True): err = 'Ese SKU ya existe'
        if not err:
            ks = list(d)
            if m: db().execute(f"UPDATE materiales SET {', '.join(k+'=?' for k in ks)} WHERE id=?", [d[k] for k in ks]+[mid])
            else:
                mid = db().execute(f"INSERT INTO materiales({','.join(ks)}) VALUES({','.join('?'*len(ks))})", [d[k] for k in ks]).lastrowid
                ini = float(request.form.get('stock_inicial') or 0)
                if ini: mover(db(), mid, int(request.form.get('almacen_id') or 1), 'entrada', ini, 'Inventario inicial')
            db().commit()
            nxt = request.form.get('next') or ''
            return redirect(nxt if nxt.startswith('/inventario/escanear') else url_for('material_ver', mid=mid))
        m = d
    if not m and request.args.get('codigo'): m = {'codigo_barras': request.args['codigo'], 'activo': 1}
    return render_template('material_form.html', m=m, mid=mid, err=err, nxt=request.values.get('next',''), CATS_MAT=CATS_MAT, UNIDADES=UNIDADES, alms=almacenes(), provs=q('SELECT id, razon_social FROM proveedores WHERE activo=1 OR id=? ORDER BY razon_social', (m.get('proveedor_id') if isinstance(m, dict) else (m['proveedor_id'] if m else None),)))

@app.route('/inventario/<int:mid>')
def material_ver(mid):
    m = q('SELECT * FROM materiales WHERE id=?', (mid,), one=True) or abort(404)
    movs = q('SELECT v.*, o.folio, a.nombre alm FROM movimientos v LEFT JOIN ordenes o ON o.id=v.orden_id LEFT JOIN almacenes a ON a.id=v.almacen_id WHERE v.material_id=? ORDER BY v.id DESC LIMIT 100', (mid,))
    return render_template('material_ver.html', m=m, movs=movs, TIPOS_MOV=TIPOS_MOV, alms=almacenes(), ex=existencias_map(), mins=minimos_map())

@app.route('/inventario/<int:mid>/minimos', methods=['POST'])
def material_minimos(mid):
    for a in almacenes():
        v = request.form.get(f'min{a["id"]}')
        if v is not None:
            db().execute('INSERT OR IGNORE INTO existencias(material_id,almacen_id,stock) VALUES(?,?,0)', (mid, a['id']))
            db().execute('UPDATE existencias SET minimo=? WHERE material_id=? AND almacen_id=?', (float(v or 0), mid, a['id']))
    db().commit(); return redirect(url_for('material_ver', mid=mid))

@app.route('/inventario/<int:mid>/eliminar', methods=['POST'])
def material_eliminar(mid):
    # Si tiene movimientos se desactiva (para conservar el historial); si no, se borra.
    if q('SELECT 1 FROM movimientos WHERE material_id=? LIMIT 1', (mid,), one=True) or q('SELECT 1 FROM orden_materiales WHERE material_id=? LIMIT 1', (mid,), one=True):
        db().execute('UPDATE materiales SET activo=0 WHERE id=?', (mid,))
    else: db().execute('DELETE FROM materiales WHERE id=?', (mid,))
    db().commit(); return redirect(url_for('inventario'))

@app.route('/inventario/movimiento', methods=['GET','POST'])
def movimiento_form():
    tipo = request.values.get('tipo') or next((t for t in ('entrada','salida','ajuste','transferencia') if PERM.can(PERM.MOV_PERM[t])), 'entrada')
    if tipo not in ('entrada','salida','ajuste','transferencia'): tipo = 'entrada'
    err = warn = None; fv = request.form
    if request.method == 'POST':
        con = db()
        try:
            mid = int(fv['material_id']); m = q('SELECT * FROM materiales WHERE id=?', (mid,), one=True) or abort(400)
            alm = int(fv['almacen_id']); cant = float(fv.get('cantidad') or 0)
            if tipo != 'ajuste' and cant <= 0: raise ValueError('La cantidad debe ser mayor a 0')
            oid = None
            if fv.get('folio'):
                o = q('SELECT id FROM ordenes WHERE folio=?', (fv['folio'].strip(),), one=True)
                if not o: raise ValueError('No existe la orden '+fv['folio'])
                oid = o['id']
            permitir = bool(fv.get('permitir_negativo'))
            nalm = {r['id']: r['nombre'] for r in almacenes()}
            con.execute('BEGIN IMMEDIATE')
            try:
                if tipo == 'ajuste':  # se captura el conteo físico del almacén
                    mover(con, mid, alm, 'ajuste', cant - stock_en(mid, alm), fv.get('motivo') or 'Conteo físico', fv.get('referencia',''), oid)
                elif tipo == 'transferencia':
                    dest = int(fv['destino_id'])
                    if dest == alm: raise ValueError('Origen y destino deben ser distintos')
                    ref = fv.get('referencia') or f'{nalm[alm]} → {nalm[dest]}'
                    mover(con, mid, alm, 'transferencia', -cant, fv.get('motivo') or f'Transferencia a {nalm[dest]}', ref, oid, permitir)
                    mover(con, mid, dest, 'transferencia', cant, fv.get('motivo') or f'Transferencia desde {nalm[alm]}', ref, oid)
                else:
                    mover(con, mid, alm, tipo, cant, fv.get('motivo',''), fv.get('referencia',''), oid, permitir)
            except ValueError as e:
                con.rollback()
                if str(e) == 'stock negativo':
                    warn = f"La operación deja «{m['nombre']}» en {stock_en(mid, alm)-cant:g} {m['unidad']} en {nalm[alm]} (negativo). Marca «Permitir stock negativo» para registrarla de todos modos."
                raise
            con.commit(); return redirect(url_for('movimientos', material=mid))
        except ValueError as e:
            if not warn: err = str(e)
    return render_template('movimiento_form.html', tipo=tipo, mats=mat_opciones(), err=err, warn=warn, fv=fv, sel=request.values.get('material_id',''),
        TIPOS_MOV=TIPOS_MOV, alms=almacenes(), ex=existencias_map())

@app.route('/inventario/movimientos')
def movimientos():
    f = {k: request.args.get(k, '') for k in ('material','tipo','desde','hasta','folio','buscar','almacen')}
    w, a = ['1=1'], []
    if f['material']: w.append('v.material_id=?'); a.append(f['material'])
    if f['tipo']: w.append('v.tipo=?'); a.append(f['tipo'])
    if f['almacen']: w.append('v.almacen_id=?'); a.append(f['almacen'])
    if f['desde']: w.append('substr(v.fecha,1,10)>=?'); a.append(f['desde'])
    if f['hasta']: w.append('substr(v.fecha,1,10)<=?'); a.append(f['hasta'])
    if f['folio']: w.append('o.folio LIKE ?'); a.append('%'+f['folio']+'%')
    if f['buscar']: w.append('(m.nombre LIKE ? OR m.sku LIKE ? OR v.motivo LIKE ? OR v.referencia LIKE ?)'); a += ['%'+f['buscar']+'%']*4
    where = ' AND '.join(w)
    total = q(f'SELECT COUNT(*) n FROM movimientos v JOIN materiales m ON m.id=v.material_id LEFT JOIN ordenes o ON o.id=v.orden_id WHERE {where}', a, one=True)['n']
    per = 50; pages = max(1, math.ceil(total/per)); page = min(max(1, int(request.args.get('page', 1) or 1)), pages)
    rows = q(f'''SELECT v.*, m.sku, m.nombre, m.unidad, o.folio, al.nombre alm FROM movimientos v JOIN materiales m ON m.id=v.material_id LEFT JOIN ordenes o ON o.id=v.orden_id LEFT JOIN almacenes al ON al.id=v.almacen_id
        WHERE {where} ORDER BY v.fecha DESC, v.id DESC LIMIT ? OFFSET ?''', a+[per, (page-1)*per])
    return render_template('movimientos.html', rows=rows, f=f, total=total, page=page, pages=pages, mats=q('SELECT id,sku,nombre FROM materiales ORDER BY nombre'),
        TIPOS_MOV=TIPOS_MOV, alms=almacenes(), qs={k: v for k, v in f.items() if v})

@app.route('/api/materiales')
def api_materiales():
    ex = existencias_map(); al = almacenes()
    return jsonify([dict(r, existencias={a['nombre']: ex.get((r['id'], a['id']), 0) for a in al}) for r in q('SELECT * FROM materiales ORDER BY categoria, nombre')])

# ---------- Escaneo por código de barras ----------
@app.route('/inventario/escanear')
def escanear():
    return render_template('escanear.html', alms=almacenes())

def _mat_por_codigo(cb):
    return q('SELECT * FROM materiales WHERE codigo_barras=? OR (sku=? AND codigo_barras IS NULL) ORDER BY codigo_barras IS NULL LIMIT 1', (cb, cb), one=True)

@app.route('/api/inventario/codigo/<path:cb>')
def api_codigo(cb):
    m = _mat_por_codigo(cb.strip())
    if not m: return jsonify(ok=False, error='Código no registrado', codigo=cb), 404
    alm = request.args.get('almacen_id', type=int)
    return jsonify(ok=True, material=dict(id=m['id'], sku=m['sku'], nombre=m['nombre'], unidad=m['unidad'], activo=m['activo'], codigo_barras=m['codigo_barras'], stock_total=m['stock_actual']),
                   stock=stock_en(m['id'], alm) if alm else None)

@app.route('/api/inventario/escanear', methods=['POST'])
def api_escanear():
    d = request.get_json(silent=True) or request.form
    cb = str(d.get('codigo_barras') or d.get('barcode') or '').strip(); tipo = d.get('tipo')
    try: alm = int(d.get('almacen_id')); cant = float(d.get('cantidad') or 1)
    except (TypeError, ValueError): return jsonify(ok=False, error='almacen_id/cantidad inválidos'), 400
    if tipo not in ('entrada', 'salida'): return jsonify(ok=False, error='tipo debe ser entrada o salida'), 400
    if not PERM.can(PERM.MOV_PERM[tipo]): return jsonify(ok=False, error=f'Tu perfil no permite registrar {tipo}s'), 403
    if cant <= 0: return jsonify(ok=False, error='La cantidad debe ser mayor a 0'), 400
    a = q('SELECT * FROM almacenes WHERE id=? AND activo=1', (alm,), one=True)
    if not a: return jsonify(ok=False, error='Almacén no existe'), 400
    m = _mat_por_codigo(cb)
    if not m: return jsonify(ok=False, error='Código no registrado', codigo=cb), 404
    if not m['activo']: return jsonify(ok=False, error='Material inactivo'), 400
    con = db()
    try: nuevo = mover(con, m['id'], alm, tipo, cant, d.get('motivo') or f'Escaneo ({TIPOS_MOV[tipo].lower()})', referencia=f'CB {cb}')
    except ValueError as e:
        con.rollback()
        if str(e) == 'stock negativo': return jsonify(ok=False, error=f"Stock insuficiente en {a['nombre']}: hay {stock_en(m['id'], alm):g} {m['unidad']}"), 409
        return jsonify(ok=False, error=str(e)), 400
    con.commit()
    return jsonify(ok=True, material=dict(id=m['id'], sku=m['sku'], nombre=m['nombre'], unidad=m['unidad']), almacen=a['nombre'], tipo=tipo, cantidad=cant, stock=nuevo)

@app.route('/vehiculos', methods=['GET','POST'])
def vehiculos():
    if request.method == 'POST':
        for v in q("SELECT id FROM almacenes WHERE tipo='vehiculo'"):
            cid = request.form.get(f'v{v["id"]}')
            if cid is not None:
                db().execute('UPDATE almacenes SET cuadrilla_id=? WHERE id=?', (int(cid) if cid else None, v['id']))
                db().execute('UPDATE vehiculos SET cuadrilla_id=? WHERE almacen_id=?', (int(cid) if cid else None, v['id']))
        db().commit(); return redirect(url_for('vehiculos', ok=1))
    vs = q('''SELECT a.*, (SELECT COUNT(*) FROM existencias e WHERE e.almacen_id=a.id AND e.stock>0) nmat FROM almacenes a WHERE a.tipo='vehiculo' ORDER BY a.nombre''')
    cu = q('SELECT * FROM cuadrillas ORDER BY id')
    return render_template('vehiculos.html', vs=vs, cu=cu, ok=request.args.get('ok'))

# ---------- API JSON ----------
@app.route('/api/resumen')
def api_resumen():
    S, SA = PERM.orden_scope('o')
    return jsonify(estados={r['estado']: r['n'] for r in q(f'SELECT estado, COUNT(*) n FROM ordenes o WHERE {S} GROUP BY estado', SA)},
                   total=q(f'SELECT COUNT(*) n FROM ordenes o WHERE {S}', SA, one=True)['n'], vencidas=q(f'SELECT COUNT(*) n FROM ordenes o WHERE {VENCIDA} AND {S}', SA, one=True)['n'],
                   cuadrillas=q('SELECT COUNT(*) n FROM cuadrillas', one=True)['n'], tecnicos=q('SELECT COUNT(*) n FROM tecnicos', one=True)['n'])
@app.route('/api/ordenes')
def api_ordenes():
    S, SA = PERM.orden_scope('o')
    return jsonify([dict(r) for r in q(f'SELECT o.* FROM ordenes o WHERE {S} ORDER BY o.fecha_programada DESC LIMIT 500', SA)])

def ean13(base12):
    d = [int(x) for x in base12]; s = sum(d[0::2]) + 3*sum(d[1::2]); return base12 + str((10 - s % 10) % 10)
def sembrar_codigos(c, n=30):
    # EJEMPLO: EAN-13 ficticios con apariencia de proveedor (prefijo 750 = México). Reemplazar por los códigos reales de las etiquetas.
    if c.execute('SELECT 1 FROM materiales WHERE codigo_barras IS NOT NULL LIMIT 1').fetchone(): return
    for mid, in c.execute('SELECT id FROM materiales WHERE ejemplo=1 ORDER BY id LIMIT ?', (n,)).fetchall():
        c.execute('UPDATE materiales SET codigo_barras=? WHERE id=?', (ean13(f'7501{(mid*7919)%100000000:08d}'), mid))

SYSCOM_COLS = [('numero_parte','TEXT'),('syscom_id','TEXT'),('marca','TEXT'),('imagen_url','TEXT'),('imagen_local','TEXT'),
    ('precio_syscom','REAL'),('syscom_link','TEXT'),('syscom_sync','TEXT'),('imagen_ejemplo','INTEGER DEFAULT 0')]
def sembrar_imagenes_ejemplo(c, n=6):
    """Pone miniaturas de EJEMPLO (static/productos/ejemplo-N.svg) a unos materiales para que la UI muestre fotos antes de la sync real."""
    if c.execute('SELECT 1 FROM materiales WHERE imagen_url IS NOT NULL OR imagen_local IS NOT NULL LIMIT 1').fetchone(): return
    for i, (mid,) in enumerate(c.execute('SELECT id FROM materiales WHERE activo=1 ORDER BY categoria, nombre LIMIT ?', (n,)).fetchall(), 1):
        c.execute("UPDATE materiales SET imagen_url=?, imagen_ejemplo=1, marca=COALESCE(marca,'EJEMPLO') WHERE id=?", (f'/static/productos/ejemplo-{i}.svg', mid))
def miniatura(m):
    try:
        if m['imagen_local']: return '/uploads/' + m['imagen_local']
        return m['imagen_url'] or None
    except (KeyError, IndexError, TypeError): return None
app.jinja_env.globals['miniatura'] = miniatura

def init_db():
    c = sqlite3.connect(DB); c.executescript(SCHEMA)
    if 'material_id' not in [r[1] for r in c.execute('PRAGMA table_info(orden_materiales)')]:
        c.execute('ALTER TABLE orden_materiales ADD COLUMN material_id INTEGER REFERENCES materiales(id)')
    if 'minimo' not in [r[1] for r in c.execute('PRAGMA table_info(existencias)')]:
        c.execute('ALTER TABLE existencias ADD COLUMN minimo REAL NOT NULL DEFAULT 0')
    if 'almacen_id' not in [r[1] for r in c.execute('PRAGMA table_info(orden_materiales)')]:
        c.execute('ALTER TABLE orden_materiales ADD COLUMN almacen_id INTEGER REFERENCES almacenes(id)')
    for n in ALMACENES: c.execute("INSERT OR IGNORE INTO almacenes(nombre,tipo) VALUES(?,'bodega')", (n,))
    asegurar_vehiculos(c)
    if 'codigo_barras' not in [r[1] for r in c.execute('PRAGMA table_info(materiales)')]:
        c.execute('ALTER TABLE materiales ADD COLUMN codigo_barras TEXT')
    c.execute('CREATE UNIQUE INDEX IF NOT EXISTS ux_mat_cb ON materiales(codigo_barras) WHERE codigo_barras IS NOT NULL')
    sembrar_codigos(c)
    mc = [r[1] for r in c.execute('PRAGMA table_info(materiales)')]
    for col, typ in SYSCOM_COLS:
        if col not in mc: c.execute(f'ALTER TABLE materiales ADD COLUMN {col} {typ}')
    c.execute('CREATE INDEX IF NOT EXISTS ix_mat_np ON materiales(numero_parte)')
    sembrar_imagenes_ejemplo(c)
    CM.migrar(c)
    SF.migrar(c)
    UPS.migrar(c)
    SD.migrar(c)
    PM.migrar(c, PM.JSON, PLANT_DE_TIPO)
    migrar_ordenes(c)
    PERM.demo(c)   # solo datos de ejemplo; no hace nada si ya hay propietarios asignados
    c.commit(); c.close()
import syscom_client as SC
import config_mod as CM
import sitio_fotos as SF
import sitio_ups as UPS
import sitio_docs as SD
import sepomex
app.jinja_env.filters['todate'] = lambda v: dt.date.fromisoformat(v)
CONFIG = CM.registrar(app, q, db)
SF.registrar(app, q, db, UP)
UPS.registrar(app, q, db)
sepomex.registrar(app)
PM.MAPA_TIPO = PLANT_DE_TIPO
PM.registrar(app, q, db, [t for cat in TIPOS.values() for lst in cat.values() for t in lst])
SD.registrar(app, q, db)
app.config.setdefault('MAX_CONTENT_LENGTH', 80 * 1024 * 1024)

@app.route('/proveedores/syscom', methods=['GET','POST'])
def syscom_config():
    msg = err = None
    if request.method == 'POST':
        acc = request.form.get('accion')
        if acc == 'guardar':
            cid, sec = (request.form.get('client_id') or '').strip(), (request.form.get('client_secret') or '').strip()
            if os.environ.get('SYSCOM_CLIENT_ID'): err = 'Las credenciales vienen de variables de entorno (Render); cámbialas ahí.'
            elif not cid or not sec: err = 'Escribe client_id y client_secret'
            else:
                SC.guardar_credenciales(cid, sec); ok, m = SC.probar_conexion()
                if ok: msg = 'Credenciales guardadas en .env. ' + m
                else: err = 'Credenciales guardadas, pero la prueba falló: ' + m
        elif acc == 'probar':
            ok, m = SC.probar_conexion(); msg, err = (m, None) if ok else (None, m)
        elif acc == 'sincronizar':
            if not SC.estado().get('conexion_ok'): err = 'Primero prueba la conexión'
            else:
                try:
                    modelos = [x.strip() for x in (request.form.get('modelos') or '').replace(',', '\n').splitlines() if x.strip()]
                    c = sqlite3.connect(DB); r = SC.sincronizar(c, UP, crear_nuevos=bool(modelos), consultas=modelos); c.close()
                    msg = f"Sincronización: {r['revisados']} revisados, {r['actualizados']} actualizados, {r['creados']} nuevos, {r['imagenes']} fotos, {r['sin_coincidencia']} sin coincidencia" + (f", {len(r['errores'])} errores" if r['errores'] else '')
                except SC.SyscomError as e: err = str(e)
    cid, sec = SC.credenciales(); est = SC.estado()
    st = 'conectado' if (cid and sec and est.get('conexion_ok')) else ('credenciales sin probar' if cid and sec else 'sin credenciales')
    stats = q("SELECT COUNT(*) n, SUM(syscom_id IS NOT NULL) con_sys, SUM(imagen_local IS NOT NULL OR imagen_url IS NOT NULL) con_img, SUM(imagen_ejemplo=1) ej FROM materiales WHERE activo=1", one=True)
    return render_template('syscom.html', st=st, est=est, cid_mask=(cid[:4] + '…' + cid[-2:]) if cid and len(cid) > 8 else ('••••' if cid else ''),
        origen=SC.origen_credenciales(), msg=msg, err=err, stats=stats, desde_env=bool(os.environ.get('SYSCOM_CLIENT_ID')))

@app.route('/api/syscom/buscar')
def syscom_buscar():
    t = (request.args.get('q') or '').strip()
    if len(t) < 2: return jsonify(error='consulta muy corta'), 400
    try: return jsonify(SC.buscar_productos(t))
    except SC.SyscomError as e: return jsonify(error=str(e)), 503

init_db()
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), debug=False)
