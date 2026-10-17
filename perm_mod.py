"""Perfiles y matriz de permisos (Configuración › Usuarios › Perfiles y permisos).
- El superadmin de entorno (perfil «Administrador») siempre tiene todo y no se edita.
- Cada persona con usuario tiene un perfil: el que le asigna el superadmin en Usuarios o, si no, el de su puesto.
- Los permisos se leen de la BD en cada petición: un cambio en la matriz aplica de inmediato."""
from flask import g, session, request, abort, redirect, render_template
_db = None   # función que devuelve la conexión de la petición (la fija auth_mod.registrar)

# ---- Catálogo de permisos (módulo -> acciones) ----
CONFIG_CATS = [('materiales', 'Materiales'), ('personal', 'Personal'), ('vehiculos', 'Vehículos'), ('cuadrillas', 'Cuadrillas'), ('sites', 'Sites'),
               ('almacenes', 'Almacenes'), ('herramientas', 'Herramientas y equipo'), ('proveedores', 'Proveedores'), ('evidencias', 'Reporte de evidencias'), ('checklist', 'Checklist diario (puntos)'), ('syscom', 'API SYSCOM')]
PERMISOS = [
    ('Panel', [('panel.ver', 'Ver panel')]),
    ('Órdenes', [('ordenes.ver', 'Ver'), ('ordenes.crear', 'Crear'), ('ordenes.editar', 'Editar'), ('ordenes.asignar', 'Asignar cuadrilla / personal'),
                 ('ordenes.estado', 'Cambiar estado / cerrar'), ('ordenes.cancelar', 'Cancelar'), ('ordenes.autorizar', 'Autorizar (instalación nueva)'),
                 ('ordenes.imprimir', 'Imprimir formato'), ('ordenes.eliminar', 'Eliminar')]),
    ('Evidencias', [('evidencias.subir', 'Subir'), ('evidencias.ver', 'Ver / imprimir')]),
    ('Materiales en orden', [('ordenes.materiales', 'Registrar')]),
    ('Inventario', [('inventario.ver', 'Ver existencias y movimientos'), ('inventario.entradas', 'Entradas'), ('inventario.salidas', 'Salidas'),
                    ('inventario.ajustes', 'Ajustes y mínimos'), ('inventario.transferencias', 'Transferencias')]),
    ('Escanear', [('escanear', 'Escanear códigos')]),
    ('Cuadrillas', [('cuadrillas.ver', 'Ver'), ('cuadrillas.editar', 'Editar')]),
    ('Vehículos', [('vehiculos.ver', 'Ver'), ('vehiculos.editar', 'Asignar a cuadrilla')]),
    ('Responsivas de vehículo', [('responsivas.ver', 'Ver cartas responsivas'), ('responsivas.firmar_presencial', 'Capturar firma en persona')]),
    ('Checklist diario', [('checklist.realizar', 'Rutina obligatoria al iniciar el día'), ('checklist.ver', 'Ver checklists diarios')]),
    ('Clientes / Prospectos', [('clientes.ver', 'Ver'), ('clientes.crear', 'Crear'), ('clientes.editar', 'Editar / baja'), ('clientes.convertir', 'Convertir prospecto')]),
    ('Reportes', [('reportes.ver', 'Reporte de materiales')]),
    ('Configuración (catálogos)', [('config.' + k, l) for k, l in CONFIG_CATS]),
]
TODOS = [k for _, acc in PERMISOS for k, _ in acc]
ETQ = {k: (m, l) for m, acc in PERMISOS for k, l in acc}
ALCANCES = [('todas', 'Todas'), ('tipo', 'Su área / tipo de trabajo'), ('equipo', 'Su equipo / cuadrilla'), ('propias', 'Solo propias / asignadas')]
CATS = [('infra', 'Infraestructura'), ('cliente', 'Clientes'), ('prospecto', 'Prospectos')]
TRABAJOS_TODOS = ['Instalación nueva', 'Mantenimiento preventivo', 'Mantenimiento correctivo', 'Factibilidad', 'Desinstalación']

def _s(*a): return set(a)
_ORD_OP = _s('ordenes.ver', 'ordenes.crear', 'ordenes.editar', 'ordenes.asignar', 'ordenes.estado', 'ordenes.imprimir')
_CAMPO = _s('evidencias.subir', 'evidencias.ver', 'ordenes.materiales')
_INV = _s('inventario.ver', 'inventario.entradas', 'inventario.salidas', 'inventario.ajustes', 'inventario.transferencias', 'escanear')
_CLI = _s('clientes.ver', 'clientes.crear', 'clientes.editar', 'clientes.convertir')
_ALL_CATS = 'infra,cliente,prospecto'
# clave: (nombre, permisos, alcance, categorías, variantes (solo con alcance «tipo»))
DEFAULTS = {
    'director': ('Director', set(TODOS) - {'checklist.realizar'}, 'todas', _ALL_CATS, ''),
    'gerente_admin': ('Gerente de administración', _s('panel.ver', 'ordenes.ver', 'ordenes.imprimir', 'ordenes.autorizar', 'ordenes.cancelar', 'evidencias.ver',
                      'cuadrillas.ver', 'vehiculos.ver', 'reportes.ver', 'checklist.ver', 'responsivas.ver', 'responsivas.firmar_presencial') | _INV | _CLI | {'config.' + k for k, _ in CONFIG_CATS}, 'todas', _ALL_CATS, ''),
    'gerente_operaciones': ('Gerente de operaciones', _s('panel.ver', 'ordenes.cancelar', 'cuadrillas.ver', 'cuadrillas.editar', 'vehiculos.ver', 'vehiculos.editar',
                            'clientes.ver', 'reportes.ver', 'inventario.ver', 'inventario.entradas', 'inventario.salidas', 'inventario.transferencias', 'escanear',
                            'config.cuadrillas', 'config.vehiculos', 'config.sites', 'config.almacenes', 'config.herramientas', 'config.evidencias', 'config.personal',
                            'checklist.ver', 'config.checklist', 'responsivas.ver', 'responsivas.firmar_presencial') | _ORD_OP | _CAMPO,
                            'todas', 'infra,cliente', ''),
    'gerente_ventas': ('Gerente de ventas', _s('panel.ver', 'ordenes.ver', 'ordenes.crear', 'ordenes.editar', 'ordenes.cancelar', 'ordenes.imprimir', 'evidencias.ver') | _CLI,
                       'todas', 'cliente,prospecto', ''),
    'gerente_soporte': ('Gerente de soporte / atención', _s('panel.ver', 'cuadrillas.ver', 'clientes.ver') | _ORD_OP | _CAMPO,
                        'tipo', 'cliente', 'Mantenimiento preventivo,Mantenimiento correctivo'),
    'ejecutivo': ('Ejecutivo comercial', _s('panel.ver', 'ordenes.ver', 'ordenes.crear', 'ordenes.editar', 'ordenes.imprimir', 'evidencias.ver') | _CLI,
                  'propias', 'cliente,prospecto', ''),
    'supervisor': ('Supervisor', _s('panel.ver', 'inventario.ver', 'inventario.salidas', 'escanear', 'cuadrillas.ver', 'vehiculos.ver', 'checklist.ver', 'responsivas.ver', 'responsivas.firmar_presencial') | _ORD_OP | _CAMPO,
                   'equipo', _ALL_CATS, ''),
    'tecnico': ('Técnico', _s('ordenes.ver', 'ordenes.estado', 'checklist.realizar') | _CAMPO, 'propias', _ALL_CATS, ''),
    'almacenista': ('Almacenista', _s('panel.ver', 'ordenes.ver', 'reportes.ver', 'config.materiales', 'config.almacenes', 'config.herramientas', 'config.proveedores') | _INV,
                    'todas', _ALL_CATS, ''),
}
ORDEN_DEF = list(DEFAULTS)
PERM_NUEVOS = ['checklist.realizar', 'checklist.ver', 'config.checklist', 'responsivas.ver', 'responsivas.firmar_presencial']   # agregados a la matriz después de su creación
# puesto (Configuración › Personal) -> perfil predeterminado
PUESTO_PERFIL = {'director': 'director', 'gerente de administracion': 'gerente_admin', 'gerente de operaciones': 'gerente_operaciones', 'gerente de ventas': 'gerente_ventas',
                 'gerente de soporte/atencion': 'gerente_soporte', 'ejecutivo comercial': 'ejecutivo', 'vendedor': 'ejecutivo', 'supervisor': 'supervisor',
                 'tecnico instalador': 'tecnico', 'tecnico': 'tecnico', 'proveedor externo': 'tecnico', 'almacenista': 'almacenista', 'gerente': 'gerente_operaciones'}

def _n(t):
    import unicodedata
    return ''.join(c for c in unicodedata.normalize('NFD', (t or '').strip().lower()) if unicodedata.category(c) != 'Mn')

def perfil_de_puesto(puesto): return PUESTO_PERFIL.get(_n(puesto), 'tecnico')

def migrar(c):
    c.execute('CREATE TABLE IF NOT EXISTS perfiles(id INTEGER PRIMARY KEY, clave TEXT UNIQUE NOT NULL, nombre TEXT NOT NULL, base TEXT, predeterminado INTEGER DEFAULT 0, alcance TEXT, categorias TEXT, trabajos TEXT, orden INTEGER DEFAULT 100)')
    c.execute('CREATE TABLE IF NOT EXISTS perfil_permisos(perfil_id INTEGER NOT NULL REFERENCES perfiles(id) ON DELETE CASCADE, permiso TEXT NOT NULL, PRIMARY KEY(perfil_id, permiso))')
    for i, (k, (nom, perms, alc, cats, trab)) in enumerate(DEFAULTS.items()):
        if not c.execute('SELECT 1 FROM perfiles WHERE clave=?', (k,)).fetchone():
            pid = c.execute('INSERT INTO perfiles(clave, nombre, base, predeterminado, alcance, categorias, trabajos, orden) VALUES (?,?,?,1,?,?,?,?)', (k, nom, k, alc, cats, trab, i + 1)).lastrowid
            c.executemany('INSERT OR IGNORE INTO perfil_permisos VALUES (?,?)', [(pid, p) for p in perms])
    # permisos agregados después de crear los perfiles: se otorgan UNA vez a los perfiles cuyo valor predeterminado los incluye
    # (si luego el superadmin los quita en la matriz, no vuelven a aparecer)
    c.execute('CREATE TABLE IF NOT EXISTS perm_migrados(permiso TEXT PRIMARY KEY)')
    for perm in PERM_NUEVOS:
        if c.execute('SELECT 1 FROM perm_migrados WHERE permiso=?', (perm,)).fetchone(): continue
        for pid, base in c.execute('SELECT id, base FROM perfiles').fetchall():
            if base in DEFAULTS and perm in DEFAULTS[base][1]: c.execute('INSERT OR IGNORE INTO perfil_permisos VALUES (?,?)', (pid, perm))
        c.execute('INSERT INTO perm_migrados VALUES (?)', (perm,))
    tc = [r[1] for r in c.execute('PRAGMA table_info(tecnicos)')]
    if 'perfil_id' not in tc:
        c.execute('ALTER TABLE tecnicos ADD COLUMN perfil_id INTEGER REFERENCES perfiles(id) ON DELETE SET NULL')
        # antiguo «rol en la app = Administrador» daba Configuración: se conserva con Gerente de administración si su puesto no la tiene
        ga = c.execute("SELECT id FROM perfiles WHERE clave='gerente_admin'").fetchone()[0]
        for tid, puesto in c.execute("SELECT id, puesto FROM tecnicos WHERE rol_app='Administrador'").fetchall():
            if perfil_de_puesto(puesto) not in ('director', 'gerente_admin'): c.execute('UPDATE tecnicos SET perfil_id=? WHERE id=?', (ga, tid))
    for t, col in (('clientes', 'ejecutivo_id'), ('ordenes', 'ejecutivo_id'), ('cuadrillas', 'supervisor_id')):
        if col not in [r[1] for r in c.execute(f'PRAGMA table_info({t})')]:
            c.execute(f'ALTER TABLE {t} ADD COLUMN {col} INTEGER REFERENCES tecnicos(id) ON DELETE SET NULL')
            if t == 'ordenes':   # órdenes existentes: propietario = quien ordenó si es ejecutivo comercial / vendedor
                c.execute("UPDATE ordenes SET ejecutivo_id=ordena_personal_id WHERE ordena_personal_id IN (SELECT id FROM tecnicos WHERE LOWER(puesto) IN ('vendedor','ejecutivo comercial'))")

def demo(c):
    """Solo datos de ejemplo: la ejecutiva comercial de ejemplo es propietaria de algunos clientes y sus órdenes."""
    e = c.execute("SELECT id FROM tecnicos WHERE ejemplo=1 AND puesto='Ejecutivo comercial' ORDER BY id LIMIT 1").fetchone()
    if not e or c.execute('SELECT 1 FROM clientes WHERE ejecutivo_id IS NOT NULL LIMIT 1').fetchone(): return
    ids = [r[0] for r in c.execute("SELECT id FROM clientes WHERE ejemplo=1 OR nombre LIKE 'Ejemplo %' ORDER BY id LIMIT 4")]
    for cid in ids:
        c.execute('UPDATE clientes SET ejecutivo_id=? WHERE id=?', (e[0], cid))
        c.execute("UPDATE ordenes SET ejecutivo_id=? WHERE cliente_id=? AND ejecutivo_id IS NULL", (e[0], cid))

# ---- Permisos del usuario actual ----
def es_su(): return bool(session.get('su'))

def perfil_actual():
    """Fila de perfiles del usuario actual (None para superadmin o sin sesión). Se cachea por petición."""
    if es_su(): return None
    if 'perfil' in g.__dict__: return g.perfil
    u = getattr(g, 'user', None); p = None
    con = _db()
    if u is not None:
        if u['perfil_id']: p = con.execute('SELECT * FROM perfiles WHERE id=?', (u['perfil_id'],)).fetchone()
        if not p: p = con.execute('SELECT * FROM perfiles WHERE clave=?', (perfil_de_puesto(u['puesto']),)).fetchone()
    g.perfil = p
    g.perms = {r[0] for r in _db().execute('SELECT permiso FROM perfil_permisos WHERE perfil_id=?', (p['id'],))} if p else set()
    return p

def can(*perms):
    """True si el usuario tiene alguno de los permisos."""
    if es_su(): return True
    if not session.get('ok'): return False
    perfil_actual()
    return any(x in g.perms for x in perms)

def can_config():
    return can(*(['config.' + k for k, _ in CONFIG_CATS] + ['clientes.ver']))

def alcance():
    """(alcance, categorías, variantes) del usuario actual."""
    p = perfil_actual()
    if es_su() or not p: return ('todas', [k for k, _ in CATS], []) if es_su() else ('propias', [], [])
    return (p['alcance'] or 'propias', [x for x in (p['categorias'] or '').split(',') if x], [x for x in (p['trabajos'] or '').split(',') if x])

def orden_scope(a='o'):
    """Filtro SQL de órdenes visibles para el usuario actual -> (sql, args)."""
    if es_su(): return '1=1', []
    alc, cats, trab = alcance()
    u = getattr(g, 'user', None)
    if not u: return '1=0', []
    w, args = [], []
    w.append(f"{a}.clase IN ({','.join('?' * len(cats)) or 'NULL'})"); args += cats
    if alc == 'tipo' and trab: w.append(f"{a}.trabajo IN ({','.join('?' * len(trab))})"); args += trab
    pid, cu = u['id'], u['cuadrilla_id']
    propias = (f"({a}.ejecutivo_id=? OR {a}.ordena_personal_id=? OR {a}.responsable_id=? OR {a}.audito_personal_id=? "
               f"OR EXISTS(SELECT 1 FROM orden_personal op WHERE op.orden_id={a}.id AND op.personal_id=?) OR {a}.cuadrilla_id=?)")
    pa = [pid, pid, pid, pid, pid, cu]
    if alc == 'propias': w.append(propias); args += pa
    elif alc == 'equipo':
        w.append(f"({propias} OR {a}.cuadrilla_id IN (SELECT id FROM cuadrillas WHERE supervisor_id=?) "
                 f"OR {a}.ejecutivo_id IN (SELECT id FROM tecnicos WHERE cuadrilla_id IS NOT NULL AND (cuadrilla_id=? OR cuadrilla_id IN (SELECT id FROM cuadrillas WHERE supervisor_id=?))))")
        args += pa + [pid, cu, pid]
    return ' AND '.join(w), args

def cliente_scope(a='cl'):
    """Clientes visibles: el ejecutivo comercial (alcance «propias») solo ve los suyos."""
    if es_su(): return '1=1', []
    alc = alcance()[0]; u = getattr(g, 'user', None)
    if alc == 'propias': return f'{a}.ejecutivo_id=?', [u['id'] if u else -1]
    return '1=1', []

def orden_visible(oid):
    s, a = orden_scope('o')
    return bool(_db().execute(f'SELECT 1 FROM ordenes o WHERE o.id=? AND {s}', [oid] + a).fetchone())

def cliente_visible(cid):
    s, a = cliente_scope('cl')
    return bool(_db().execute(f'SELECT 1 FROM clientes cl WHERE cl.id=? AND {s}', [cid] + a).fetchone())

# ---- Reglas por ruta (403 en servidor) ----
MOV_PERM = {'entrada': 'inventario.entradas', 'salida': 'inventario.salidas', 'ajuste': 'inventario.ajustes', 'transferencia': 'inventario.transferencias'}
def requerido(p, m):
    """Permisos requeridos (cualquiera) para la ruta; None = basta con sesión iniciada; 'SU' = solo superadmin."""
    import re
    post = m == 'POST'
    if p.startswith('/configuracion/usuarios') or p.startswith('/configuracion/perfiles'): return 'SU'
    if p == '/': return None   # el panel redirige a la primera sección permitida
    if p == '/api/resumen': return ['panel.ver']
    if p == '/api/ordenes' or p == '/ordenes' or p == '/tecnico': return ['ordenes.ver']
    if p == '/ordenes/nueva': return ['ordenes.crear']
    r = re.match(r'^/ordenes/\d+(/.*)?$', p)
    if r:
        s = r.group(1) or ''
        return {'': ['ordenes.ver'], '/editar': ['ordenes.editar'], '/autorizar': ['ordenes.autorizar'], '/eliminar': ['ordenes.eliminar'],
                '/estado': ['ordenes.estado', 'ordenes.cancelar'], '/nota': ['ordenes.ver'], '/foto': ['evidencias.subir'], '/evidencias': ['evidencias.ver', 'evidencias.subir'],
                '/materiales': ['ordenes.materiales'] if post else ['ordenes.ver'], '/imprimir/orden': ['ordenes.imprimir'], '/imprimir/evidencias': ['evidencias.ver']}.get(s, ['ordenes.ver'])
    if p == '/api/prospectos': return ['clientes.crear']
    if p.startswith('/cuadrillas'): return ['cuadrillas.editar'] if (post or p.endswith('/nueva')) else ['cuadrillas.ver']
    if p.startswith('/reportes'): return ['reportes.ver']
    if p == '/inventario/movimiento':
        t = request.values.get('tipo')
        return [MOV_PERM.get(t, 'inventario.entradas')] if (post or t) else list(MOV_PERM.values())
    if p == '/inventario/escanear' or p.startswith('/api/inventario/codigo'): return ['escanear']
    if p == '/api/inventario/escanear': return ['escanear']
    if p == '/inventario/nuevo' or re.match(r'^/inventario/\d+/(editar|eliminar)$', p): return ['config.materiales']
    if re.match(r'^/inventario/\d+/minimos$', p): return ['inventario.ajustes']
    if p.startswith('/inventario') : return ['inventario.ver']
    if p == '/api/materiales': return ['inventario.ver', 'ordenes.materiales']
    if p.startswith('/responsivas/generar/'): return ['config.vehiculos']
    if p.startswith('/uploads/responsivas/'): return ['responsivas.ver', 'config.vehiculos']   # firmas y PDFs (los firmantes descargan el PDF por /responsivas/<id>/pdf)
    if p.startswith('/checklists'): return ['checklist.ver']
    if p == '/checklist' or p.startswith('/checklist/'): return ['checklist.realizar']
    if p.startswith('/uploads/checklists/'): return ['checklist.ver', 'checklist.realizar']
    if p.startswith('/uploads/vehiculos/'): return ['vehiculos.ver', 'config.vehiculos']   # fotos, tarjeta de circulación y póliza
    if p.startswith('/vehiculos'): return ['vehiculos.editar'] if post else ['vehiculos.ver']
    if p.startswith('/proveedores/syscom') or p.startswith('/api/syscom') or p.startswith('/catalogo'): return ['config.syscom']
    if p.startswith('/sites/'): return ['config.sites']
    if p.startswith('/configuracion/evidencias'): return ['config.evidencias']
    if p == '/configuracion': return ['config.' + k for k, _ in CONFIG_CATS] + ['clientes.ver']
    r = re.match(r'^/configuracion/clientes(/(nuevo|\d+/(editar|baja|reactivar|convertir)))?$', p)
    if r:
        acc = r.group(3) or r.group(2)
        if acc == 'nuevo': return ['clientes.crear']
        if acc == 'convertir': return ['clientes.convertir']
        if acc in ('baja', 'reactivar'): return ['clientes.editar']
        if acc == 'editar': return ['clientes.editar'] if post else ['clientes.ver', 'clientes.editar']
        return ['clientes.ver']
    r = re.match(r'^/configuracion/([a-z_]+)', p)
    if r: return ['config.' + r.group(1)]
    return None

def inicio():
    """Primera sección permitida (para quien no ve el panel)."""
    for perm, url in (('panel.ver', '/'), ('ordenes.ver', '/tecnico'), ('inventario.ver', '/inventario'), ('clientes.ver', '/configuracion/clientes'),
                      ('escanear', '/inventario/escanear'), ('cuadrillas.ver', '/cuadrillas'), ('vehiculos.ver', '/vehiculos'), ('reportes.ver', '/reportes/materiales'), ('checklist.ver', '/checklists')):
        if can(perm): return url
    return None

# ---- Matriz de permisos (solo superadmin; ver requerido()) ----
def registrar(app, q, db, log):
    from urllib.parse import quote
    def volver(msg=None, err=None):
        return redirect('/configuracion/perfiles' + ('?msg=' + quote(msg) if msg else ('?err=' + quote(err) if err else '')))
    def datos():
        pfs = q('SELECT * FROM perfiles ORDER BY orden, id')
        perms = {p['id']: {r['permiso'] for r in q('SELECT permiso FROM perfil_permisos WHERE perfil_id=?', (p['id'],))} for p in pfs}
        usos = {}
        for t in q('SELECT perfil_id, puesto FROM tecnicos WHERE usuario IS NOT NULL AND login_activo=1'):
            k = t['perfil_id'] or next((p['id'] for p in pfs if p['clave'] == perfil_de_puesto(t['puesto'])), None)
            usos[k] = usos.get(k, 0) + 1
        return pfs, perms, usos
    def resumen(p, antes, despues, a0, a1):
        dif = [('+' if k in despues else '−') + ' ' + ' › '.join(ETQ[k]) for k in TODOS if (k in antes) != (k in despues)]
        dif += [f'{n}: {x or "—"} → {y or "—"}' for n, x, y in zip(('alcance', 'categorías', 'variantes'), a0, a1) if (x or '') != (y or '')]
        return dif

    @app.route('/configuracion/perfiles', methods=['GET', 'POST'])
    def perfiles_matriz():
        pfs, perms, usos = datos()
        if request.method == 'POST':
            F = request.form; con = db(); total = 0
            for p in pfs:
                nuevo = {k for k in F.getlist(f'p{p["id"]}') if k in ETQ}
                alc = F.get(f'a{p["id"]}') if F.get(f'a{p["id"]}') in dict(ALCANCES) else p['alcance']
                cats = ','.join(k for k, _ in CATS if k in F.getlist(f'c{p["id"]}'))
                trab = ','.join(t for t in TRABAJOS_TODOS if t in F.getlist(f't{p["id"]}')) if alc == 'tipo' else ''
                dif = resumen(p, perms[p['id']], nuevo, (p['alcance'], p['categorias'], p['trabajos']), (alc, cats, trab))
                if not dif: continue
                con.execute('DELETE FROM perfil_permisos WHERE perfil_id=?', (p['id'],))
                con.executemany('INSERT INTO perfil_permisos VALUES (?,?)', [(p['id'], k) for k in nuevo])
                con.execute('UPDATE perfiles SET alcance=?, categorias=?, trabajos=? WHERE id=?', (alc, cats, trab, p['id']))
                log(con, None, p['nombre'], 'permisos', '; '.join(dif)); total += 1
            con.commit()
            return volver(msg=f'Permisos guardados ({total} perfil(es) con cambios)' if total else 'Sin cambios')
        logs = q("SELECT * FROM usuarios_log WHERE accion LIKE 'perfil%' OR accion='permisos' ORDER BY id DESC LIMIT 20")
        return render_template('perfiles.html', pfs=pfs, perms=perms, usos=usos, PERMISOS=PERMISOS, ALCANCES=ALCANCES, CATS=CATS, TRABAJOS=TRABAJOS_TODOS,
                               DEFAULTS=DEFAULTS, logs=logs, msg=request.args.get('msg'), err=request.args.get('err'))

    @app.route('/configuracion/perfiles/<int:pid>/restaurar', methods=['POST'])
    def perfil_restaurar(pid):
        p = q('SELECT * FROM perfiles WHERE id=?', (pid,), one=True) or abort(404)
        if p['base'] not in DEFAULTS: return volver(err='Este perfil no tiene valores predeterminados')
        nom, perms, alc, cats, trab = DEFAULTS[p['base']]
        antes = {r['permiso'] for r in q('SELECT permiso FROM perfil_permisos WHERE perfil_id=?', (pid,))}
        dif = resumen(p, antes, perms, (p['alcance'], p['categorias'], p['trabajos']), (alc, cats, trab))
        con = db(); con.execute('DELETE FROM perfil_permisos WHERE perfil_id=?', (pid,))
        con.executemany('INSERT INTO perfil_permisos VALUES (?,?)', [(pid, k) for k in perms])
        con.execute('UPDATE perfiles SET alcance=?, categorias=?, trabajos=? WHERE id=?', (alc, cats, trab, pid))
        log(con, None, p['nombre'], 'perfil restaurado', f'valores predeterminados de «{nom}»' + ('; ' + '; '.join(dif) if dif else ' (sin cambios)')); con.commit()
        return volver(msg=f'«{p["nombre"]}» restaurado a sus valores predeterminados')

    @app.route('/configuracion/perfiles/nuevo', methods=['POST'])
    def perfil_nuevo():
        nom = (request.form.get('nombre') or '').strip()
        src = q('SELECT * FROM perfiles WHERE id=?', (request.form.get('base_id', type=int),), one=True)
        if not nom or len(nom) > 60: return volver(err='Escribe el nombre del perfil (máx. 60 caracteres)')
        if q('SELECT 1 FROM perfiles WHERE LOWER(nombre)=LOWER(?)', (nom,), one=True): return volver(err=f'Ya existe el perfil «{nom}»')
        con = db(); n = (q('SELECT MAX(id) m FROM perfiles', one=True)['m'] or 0) + 1
        pid = con.execute('INSERT INTO perfiles(clave, nombre, base, predeterminado, alcance, categorias, trabajos, orden) VALUES (?,?,?,0,?,?,?,?)',
                          (f'perfil_{n}', nom, src['base'] if src else None, src['alcance'] if src else 'propias', src['categorias'] if src else '', src['trabajos'] if src else '', 100 + n)).lastrowid
        if src: con.execute('INSERT INTO perfil_permisos SELECT ?, permiso FROM perfil_permisos WHERE perfil_id=?', (pid, src['id']))
        log(con, None, nom, 'perfil creado', f'copia de «{src["nombre"]}»' if src else 'vacío'); con.commit()
        return volver(msg=f'Perfil «{nom}» creado' + (f' como copia de «{src["nombre"]}»' if src else ''))

    @app.route('/configuracion/perfiles/<int:pid>/eliminar', methods=['POST'])
    def perfil_eliminar(pid):
        p = q('SELECT * FROM perfiles WHERE id=?', (pid,), one=True) or abort(404)
        if p['predeterminado']: return volver(err='Los perfiles predeterminados no se eliminan (puedes restaurarlos)')
        if q('SELECT 1 FROM tecnicos WHERE perfil_id=?', (pid,), one=True): return volver(err=f'«{p["nombre"]}» está asignado a usuarios; cámbialos primero')
        con = db(); con.execute('DELETE FROM perfiles WHERE id=?', (pid,)); log(con, None, p['nombre'], 'perfil eliminado'); con.commit()
        return volver(msg=f'Perfil «{p["nombre"]}» eliminado')
