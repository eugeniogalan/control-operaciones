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
    c.execute('CREATE TABLE IF NOT EXISTS usuarios_log(id INTEGER PRIMARY KEY, fecha TEXT, actor TEXT, personal_id INTEGER, usuario TEXT, accion TEXT, detalle TEXT)')
    PERM.migrar(c)

def usuario_actual():
    return getattr(g, 'user', None)

def es_su(): return bool(session.get('su'))

import perm_mod as PERM
def puede_config(u=None): return PERM.can_config()          # algún catálogo de Configuración (matriz de permisos)
def puede_autorizar(u=None): return PERM.can('ordenes.autorizar')

def nombre_actual():
    u = usuario_actual()
    if es_su(): return session.get('nombre') or 'Superadmin'
    return u['nombre'] if u else 'sistema'

def registrar(app, q, db, CFG):
    PERM._db = db
    app.jinja_env.globals['can'] = PERM.can
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
        req = PERM.requerido(p, request.method)
        if p == '/' and not PERM.can('panel.ver'):
            ini = PERM.inicio()
            if ini: return redirect(ini)
            abort(403)
        if req == 'SU':
            if not es_su(): abort(403)
        elif req and not PERM.can(*req):
            if p.startswith('/api/'): return jsonify(error='sin permiso'), 403
            abort(403)

    @app.context_processor
    def _ctx():
        ok = session.get('ok'); pf = PERM.perfil_actual() if ok else None
        return dict(USR=dict(nombre=nombre_actual(), puesto=(g.user['puesto'] if getattr(g, 'user', None) else ('Superadmin' if es_su() else '')),
                             su=es_su(), perfil=('Administrador' if es_su() else (pf['nombre'] if pf else '')),
                             config=puede_config() if ok else False, autoriza=puede_autorizar() if ok else False), AREAS=AREAS, can=PERM.can)

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

    registrar_usuarios(app, q, db)

# Usuarios de ejemplo. La contraseña NO está en el código: solo tienen acceso si existe la variable
# de entorno DEMO_USERS_PASSWORD (misma para los tres); si no, quedan como Personal sin acceso.
DEMO_USUARIOS = [('director', 'Director', 'Dirección'), ('administracion', 'Gerente de administración', 'Administración'), ('tecnico', 'Técnico Instalador', 'Operaciones')]
def demo_usuarios(c):
    if not c.execute('SELECT 1 FROM tecnicos WHERE ejemplo=1 LIMIT 1').fetchone(): return []
    c.execute("UPDATE tecnicos SET area=CASE puesto WHEN 'Director' THEN 'Dirección' WHEN 'Vendedor' THEN 'Ventas' WHEN 'Ejecutivo comercial' THEN 'Ventas' WHEN 'Gerente de administración' THEN 'Administración' WHEN 'Gerente de ventas' THEN 'Ventas' WHEN 'Almacenista' THEN 'Almacén' ELSE 'Operaciones' END WHERE ejemplo=1 AND area IS NULL")
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


USR_RE = r'[A-Za-z0-9._-]{3,40}'

def registrar_usuarios(app, q, db):
    """Configuración › Usuarios: altas, bajas y cambios de acceso. Solo superadmin (ver _auth)."""
    import re
    from urllib.parse import quote
    def log(con, pid, usuario, accion, detalle=''):
        con.execute('INSERT INTO usuarios_log(fecha, actor, personal_id, usuario, accion, detalle) VALUES (?,?,?,?,?,?)',
                    (ahora_mx(), session.get('nombre') or 'superadmin', pid, usuario, accion, detalle))
    def val_usuario(us, pid):
        if not re.fullmatch(USR_RE, us or ''): return 'Usuario: 3 a 40 caracteres (letras, números, punto, guion o guion bajo), sin espacios'
        if q('SELECT 1 FROM tecnicos WHERE LOWER(usuario)=LOWER(?) AND id IS NOT ?', (us, pid), one=True): return f'El usuario «{us}» ya existe'
    def val_clave(c1, c2):
        if len(c1) < MIN_CLAVE: return f'La contraseña debe tener al menos {MIN_CLAVE} caracteres'
        if c1 != c2: return 'Las contraseñas no coinciden'
    def perfiles(): return q('SELECT id, clave, nombre FROM perfiles ORDER BY orden, nombre')
    def leer_perfil(F):
        v = F.get('perfil_id') or ''
        return int(v) if v.isdigit() and q('SELECT 1 FROM perfiles WHERE id=?', (int(v),), one=True) else None
    def nombre_perfil(perfil_id, puesto):
        r = q('SELECT nombre FROM perfiles WHERE id=?', (perfil_id,), one=True) if perfil_id else None
        if r: return r['nombre']
        r = q('SELECT nombre FROM perfiles WHERE clave=?', (PERM.perfil_de_puesto(puesto),), one=True)
        return (r['nombre'] if r else '—') + ' (según puesto)'
    app.jinja_env.globals['nombre_perfil'] = nombre_perfil
    PERM.registrar(app, q, db, log)
    def volver(url, msg=None, err=None):
        return redirect(url + ('?msg=' + quote(msg) if msg else '?err=' + quote(err)))

    @app.route('/configuracion/usuarios')
    def usuarios():
        ver = request.args.get('ver', 'activos')
        w = {'activos': 'AND t.login_activo=1', 'bajas': 'AND t.login_activo=0', 'todos': ''}.get(ver, '')
        rows = q(f"SELECT t.*, COALESCE(t.activo,1) pers_activa FROM tecnicos t WHERE t.usuario IS NOT NULL {w} ORDER BY t.login_activo DESC, t.nombre")
        logs = q('SELECT * FROM usuarios_log ORDER BY id DESC LIMIT 30')
        n = q("SELECT SUM(login_activo=1) a, SUM(login_activo=0) b FROM tecnicos WHERE usuario IS NOT NULL", one=True)
        return render_template('usuarios.html', rows=rows, logs=logs, ver=ver, n=n)

    @app.route('/configuracion/usuarios/nuevo', methods=['GET', 'POST'])
    def usuario_nuevo():
        F = request.form; err = None
        libres = q("SELECT id, nombre, puesto, area FROM tecnicos WHERE usuario IS NULL AND COALESCE(activo,1)=1 ORDER BY nombre")
        if request.method == 'POST':
            us = (F.get('usuario') or '').strip(); pf = leer_perfil(F)
            modo = F.get('modo') or 'existente'
            if modo == 'existente':
                pid = int(F.get('personal_id') or 0)
                per = q('SELECT * FROM tecnicos WHERE id=? AND usuario IS NULL AND COALESCE(activo,1)=1', (pid,), one=True) if pid else None
                if not per: err = 'Elige una persona de Personal sin usuario'
            else:
                pid = None
                if not (F.get('nombre') or '').strip(): err = 'Escribe el nombre de la persona'
                elif F.get('area') and F.get('area') not in AREAS: err = 'Área inválida'
            err = err or val_usuario(us, pid) or val_clave(F.get('clave') or '', F.get('clave2') or '')
            if not err:
                con = db()
                if pid is None:
                    import config_mod as CM
                    pid = con.execute('INSERT INTO tecnicos(nombre, puesto, area, activo) VALUES (?,?,?,1)',
                                      (F['nombre'].strip(), CM.puesto_canonico(F.get('puesto') or '') or None, F.get('area') or None)).lastrowid
                    log(con, pid, us, 'persona creada', F['nombre'].strip())
                con.execute('UPDATE tecnicos SET usuario=?, pass_hash=?, login_activo=1, perfil_id=? WHERE id=?', (us, generate_password_hash(F['clave']), pf, pid))
                log(con, pid, us, 'alta', 'perfil ' + nombre_perfil(pf, q('SELECT puesto FROM tecnicos WHERE id=?', (pid,), one=True)['puesto'])); con.commit()
                return volver('/configuracion/usuarios', msg=f'Usuario «{us}» dado de alta')
        import config_mod as CM
        return render_template('usuario_form.html', u=None, libres=libres, err=err, F=F, PERFILES=perfiles(), PUESTOS=CM.PUESTOS)

    @app.route('/configuracion/usuarios/<int:pid>', methods=['GET', 'POST'])
    def usuario_editar(pid):
        u = q('SELECT * FROM tecnicos WHERE id=? AND usuario IS NOT NULL', (pid,), one=True) or abort(404)
        err = None; F = request.form
        if request.method == 'POST':
            us = (F.get('usuario') or '').strip(); pf = leer_perfil(F)
            act = 1 if F.get('login_activo') else 0
            if act and not u['pass_hash']: err = 'Asigna una contraseña antes de activar el acceso'
            err = err or val_usuario(us, pid)
            if not err:
                cambios = [f'{n}: {a} → {b}' for n, a, b in (('usuario', u['usuario'], us), ('perfil', nombre_perfil(u['perfil_id'], u['puesto']), nombre_perfil(pf, u['puesto'])), ('acceso', 'activo' if u['login_activo'] else 'inactivo', 'activo' if act else 'inactivo')) if a != b]
                con = db()
                con.execute('UPDATE tecnicos SET usuario=?, perfil_id=?, login_activo=? WHERE id=?', (us, pf, act, pid))
                if cambios: log(con, pid, us, 'cambio', '; '.join(cambios))
                con.commit()
                return volver(f'/configuracion/usuarios/{pid}', msg='Cambios guardados' if cambios else 'Sin cambios')
        logs = q('SELECT * FROM usuarios_log WHERE personal_id=? ORDER BY id DESC LIMIT 30', (pid,))
        return render_template('usuario_form.html', u=u, err=err or request.args.get('err'), F=F, PERFILES=perfiles(), logs=logs)

    @app.route('/configuracion/usuarios/<int:pid>/clave', methods=['POST'])
    def usuario_clave(pid):
        u = q('SELECT * FROM tecnicos WHERE id=? AND usuario IS NOT NULL', (pid,), one=True) or abort(404)
        e = val_clave(request.form.get('clave') or '', request.form.get('clave2') or '')
        if e: return volver(f'/configuracion/usuarios/{pid}', err=e)
        con = db(); con.execute('UPDATE tecnicos SET pass_hash=? WHERE id=?', (generate_password_hash(request.form['clave']), pid))
        log(con, pid, u['usuario'], 'contraseña restablecida', 'sesiones abiertas cerradas'); con.commit()
        return volver(f'/configuracion/usuarios/{pid}', msg='Contraseña actualizada; sus sesiones abiertas se cerraron')

    @app.route('/configuracion/usuarios/<int:pid>/baja', methods=['POST'])
    def usuario_baja(pid):
        u = q('SELECT * FROM tecnicos WHERE id=? AND usuario IS NOT NULL', (pid,), one=True) or abort(404)
        con = db(); con.execute('UPDATE tecnicos SET login_activo=0 WHERE id=?', (pid,))
        log(con, pid, u['usuario'], 'baja', 'acceso desactivado; sesiones cerradas; se conserva historial'); con.commit()
        return volver('/configuracion/usuarios', msg=f'Acceso de «{u["usuario"]}» dado de baja')

    @app.route('/configuracion/usuarios/<int:pid>/reactivar', methods=['POST'])
    def usuario_reactivar(pid):
        u = q('SELECT * FROM tecnicos WHERE id=? AND usuario IS NOT NULL', (pid,), one=True) or abort(404)
        if not u['pass_hash']: return volver(f'/configuracion/usuarios/{pid}', err='Asigna una contraseña antes de reactivar')
        con = db(); con.execute('UPDATE tecnicos SET login_activo=1 WHERE id=?', (pid,))
        log(con, pid, u['usuario'], 'reactivado'); con.commit()
        return volver('/configuracion/usuarios', msg=f'Acceso de «{u["usuario"]}» reactivado')
