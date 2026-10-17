import os
"""Usuarios por persona (Configuración › Personal) y permisos simples.
- Superadmin: ADMIN_USER / ADMIN_PASSWORD de entorno (siempre funciona, todos los permisos).
- Usuarios de Personal: usuario + contraseña (hash werkzeug), 'Acceso al sistema' activo y persona activa.
- Configuración: superadmin, puesto Director, área Administración o rol de app Administrador.
- Autorizar órdenes: superadmin, puesto Director o área Administración."""
import datetime as dt, hmac
from flask import session, g, request, abort, redirect, url_for, render_template, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo('America/Mexico_City')
except Exception: TZ = None

AREAS = ['Administración', 'Operaciones', 'Ventas', 'Almacén', 'Dirección', 'Otro']
ROLES_APP = ['Usuario', 'Administrador']
MIN_CLAVE = 8

def ahora_mx():
    return (dt.datetime.now(TZ) if TZ else dt.datetime.now()).strftime('%Y-%m-%dT%H:%M')

def _n(t):
    import unicodedata
    return ''.join(c for c in unicodedata.normalize('NFD', (t or '').strip().lower()) if unicodedata.category(c) != 'Mn')

def migrar(c):
    cols = [r[1] for r in c.execute('PRAGMA table_info(tecnicos)')]
    for col, typ in (('usuario', 'TEXT'), ('pass_hash', 'TEXT'), ('login_activo', 'INTEGER DEFAULT 0'), ('rol_app', "TEXT DEFAULT 'Usuario'"), ('area', 'TEXT'), ('ultimo_acceso', 'TEXT')):
        if col not in cols: c.execute(f'ALTER TABLE tecnicos ADD COLUMN {col} {typ}')
    c.execute("UPDATE tecnicos SET usuario=NULL WHERE TRIM(COALESCE(usuario,''))=''")
    c.execute('CREATE UNIQUE INDEX IF NOT EXISTS ux_tec_usuario ON tecnicos(LOWER(usuario)) WHERE usuario IS NOT NULL')

def usuario_actual():
    return getattr(g, 'user', None)

def es_su(): return bool(session.get('su'))

def puede_config(u=None):
    u = u or usuario_actual()
    if es_su(): return True
    return bool(u) and (_n(u['puesto']) == 'director' or _n(u['area']) == 'administracion' or u['rol_app'] == 'Administrador')

def puede_autorizar(u=None):
    u = u or usuario_actual()
    if es_su(): return True
    return bool(u) and (_n(u['puesto']) == 'director' or _n(u['area']) == 'administracion')

def nombre_actual():
    u = usuario_actual()
    if es_su(): return session.get('nombre') or 'Superadmin'
    return u['nombre'] if u else 'sistema'

def registrar(app, q, db, CFG):
    @app.before_request
    def _auth():
        g.user = None
        if request.endpoint in ('login', 'logout') or request.path == '/static/logo-spectro.png': return
        if not session.get('ok'):
            if request.path.startswith('/api/'): return jsonify(error='no autorizado'), 401
            return redirect(url_for('login', next=request.full_path))
        if not session.get('su'):
            u = q('SELECT * FROM tecnicos WHERE id=? AND COALESCE(activo,1)=1 AND login_activo=1 AND pass_hash IS NOT NULL', (session.get('pid'),), one=True)
            if not u or (session.get('pv') != (u['pass_hash'] or '')[-12:]):   # baja, acceso desactivado o contraseña cambiada -> fuera
                session.clear(); return redirect(url_for('login', next=request.full_path))
            g.user = u
        p = request.path
        if (p.startswith('/configuracion') or p.startswith('/proveedores') or p.startswith('/api/syscom') or p.startswith('/catalogo')) and not puede_config():
            abort(403)

    @app.context_processor
    def _ctx():
        return dict(USR=dict(nombre=nombre_actual(), puesto=(g.user['puesto'] if getattr(g, 'user', None) else ('Superadmin' if es_su() else '')),
                             su=es_su(), config=puede_config() if session.get('ok') else False, autoriza=puede_autorizar() if session.get('ok') else False), AREAS=AREAS)

    @app.errorhandler(403)
    def _403(e):
        return render_template('prohibido.html'), 403

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        err = None
        if request.method == 'POST':
            us, cl = (request.form.get('usuario') or '').strip(), request.form.get('clave') or ''
            nxt = request.args.get('next') or '/'
            nxt = nxt if nxt.startswith('/') and not nxt.startswith('//') else '/'
            if hmac.compare_digest(us, CFG['APP_USER']) and hmac.compare_digest(cl, CFG['APP_PASSWORD']):
                session.clear(); session.update(ok=True, su=True, nombre='Superadmin (' + CFG['APP_USER'] + ')'); session.permanent = True
                return redirect(nxt)
            u = q('SELECT * FROM tecnicos WHERE LOWER(usuario)=LOWER(?) AND COALESCE(activo,1)=1 AND login_activo=1 AND pass_hash IS NOT NULL', (us,), one=True) if us else None
            if u and check_password_hash(u['pass_hash'], cl):
                session.clear(); session.update(ok=True, su=False, pid=u['id'], nombre=u['nombre'], pv=u['pass_hash'][-12:]); session.permanent = True
                db().execute('UPDATE tecnicos SET ultimo_acceso=? WHERE id=?', (ahora_mx(), u['id'])); db().commit()
                return redirect(nxt)
            err = 'Usuario o contraseña incorrectos'
        return render_template('login.html', err=err)

    @app.route('/logout')
    def logout():
        session.clear(); return redirect(url_for('login'))

    @app.route('/configuracion/personal/<int:rid>/clave', methods=['POST'])
    def personal_clave(rid):
        u = q('SELECT id, nombre, usuario FROM tecnicos WHERE id=?', (rid,), one=True) or abort(404)
        c1, c2 = request.form.get('clave') or '', request.form.get('clave2') or ''
        if not u['usuario']: m = 'Primero asigna un usuario y guarda la persona'
        elif len(c1) < MIN_CLAVE: m = f'La contraseña debe tener al menos {MIN_CLAVE} caracteres'
        elif c1 != c2: m = 'Las contraseñas no coinciden'
        else:
            db().execute('UPDATE tecnicos SET pass_hash=? WHERE id=?', (generate_password_hash(c1), rid)); db().commit()
            return redirect(f'/configuracion/personal/{rid}/editar?msg=' + 'Contraseña actualizada para ' + u['usuario'] + '#acceso')
        return redirect(f'/configuracion/personal/{rid}/editar?err=' + m + '#acceso')

# ---- Solo para la base de EJEMPLO (seed.py): usuarios demo con contraseñas demo ----
# Usuarios de ejemplo. La contraseña NO está en el código: solo tienen acceso si existe la variable
# de entorno DEMO_USERS_PASSWORD (misma para los tres); si no, quedan como Personal sin acceso.
DEMO_USUARIOS = [('director', 'Director', 'Dirección'), ('administracion', 'Gerente', 'Administración'), ('tecnico', 'Técnico Instalador', 'Operaciones')]
def demo_usuarios(c):
    if not c.execute('SELECT 1 FROM tecnicos WHERE ejemplo=1 LIMIT 1').fetchone(): return []
    c.execute("UPDATE tecnicos SET area=CASE puesto WHEN 'Director' THEN 'Dirección' WHEN 'Vendedor' THEN 'Ventas' WHEN 'Almacenista' THEN 'Almacén' ELSE 'Operaciones' END WHERE ejemplo=1 AND area IS NULL")
    hechos = []
    cl = os.environ.get('DEMO_USERS_PASSWORD') or ''
    if cl and len(cl) < MIN_CLAVE: cl = ''
    for us, puesto, area in DEMO_USUARIOS:
        if c.execute('SELECT 1 FROM tecnicos WHERE LOWER(usuario)=?', (us,)).fetchone(): continue
        r = c.execute('SELECT id, nombre FROM tecnicos WHERE ejemplo=1 AND puesto=? AND usuario IS NULL ORDER BY id LIMIT 1', (puesto,)).fetchone()
        if not r: continue
        c.execute("UPDATE tecnicos SET usuario=?, pass_hash=?, login_activo=?, area=?, rol_app='Usuario' WHERE id=?",
                  (us, generate_password_hash(cl) if cl else None, 1 if cl else 0, area, r[0]))
        hechos.append((us, r[1], puesto, area, bool(cl)))
    return hechos
