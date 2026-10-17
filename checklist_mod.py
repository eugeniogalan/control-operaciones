"""Checklist diario obligatorio al iniciar el día (perfiles con permiso «checklist.realizar», p. ej. Técnico).
Rutina 1 – Vehículo (km, odómetro, combustible, revisión) y Rutina 2 – Seguridad (EPP y foto de la cuadrilla).
El día se cuenta con la fecha de America/Mexico_City. Revisión en /checklists (permiso «checklist.ver»)."""
import os, datetime as dt
from flask import request, redirect, abort, render_template, jsonify, g, session
import perm_mod as PERM
import sitio_fotos as SF

COMBUSTIBLE = ['1/8', '1/4', '3/8', '1/2', '5/8', '3/4', 'Lleno']
RUTINAS = ['Vehículo', 'Seguridad']
ITEMS_DEF = {'Vehículo': ['Calibración de llantas', 'Chequeo de nivel de aceite', 'Líquido limpiaparabrisas', 'Luces (faros, direccionales, freno)', 'Frenos'],
             'Seguridad': ['Casco', 'Chaleco', 'Guantes', 'Zapatos de seguridad', 'Lentes de seguridad', 'Reloj indicador de campo electromagnético',
                           'Arnés y línea de vida', 'Botiquín de primeros auxilios', 'Extintor', 'Conos / señalamientos']}
SUB = 'checklists'
UP_DIR = None
LIBRES = ('/checklist', '/logout', '/login', '/static/', '/uploads/checklists/')

def hoy_mx():
    """Fecha local de la Ciudad de México (sin horario de verano desde 2022 -> UTC-6 como respaldo)."""
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo('America/Mexico_City'))
    except Exception:
        return dt.datetime.now(dt.timezone(dt.timedelta(hours=-6)))
def fecha_hoy(): return hoy_mx().date().isoformat()
def ahora(): return hoy_mx().strftime('%Y-%m-%dT%H:%M')

def migrar(c):
    c.execute('''CREATE TABLE IF NOT EXISTS checklist_items(id INTEGER PRIMARY KEY, rutina TEXT NOT NULL, nombre TEXT NOT NULL, orden INTEGER DEFAULT 100,
        activo INTEGER DEFAULT 1, UNIQUE(rutina, nombre))''')
    for rut, items in ITEMS_DEF.items():
        if not c.execute('SELECT 1 FROM checklist_items WHERE rutina=? LIMIT 1', (rut,)).fetchone():
            c.executemany('INSERT OR IGNORE INTO checklist_items(rutina,nombre,orden) VALUES(?,?,?)', [(rut, n, (i + 1) * 10) for i, n in enumerate(items)])
    c.execute('''CREATE TABLE IF NOT EXISTS checklists(id INTEGER PRIMARY KEY, fecha TEXT NOT NULL, personal_id INTEGER NOT NULL REFERENCES tecnicos(id),
        cuadrilla_id INTEGER REFERENCES cuadrillas(id) ON DELETE SET NULL, vehiculo_id INTEGER REFERENCES vehiculos(id) ON DELETE SET NULL,
        km INTEGER, km_anterior INTEGER, km_alerta INTEGER DEFAULT 0, foto_odometro TEXT, combustible TEXT, foto_combustible TEXT, veh_obs TEXT, veh_fin TEXT,
        foto_epp TEXT, seg_obs TEXT, seg_fin TEXT, ejemplo INTEGER DEFAULT 0, UNIQUE(fecha, personal_id))''')
    c.execute('CREATE INDEX IF NOT EXISTS ix_chk_veh ON checklists(vehiculo_id, fecha)')
    c.execute('''CREATE TABLE IF NOT EXISTS checklist_respuestas(id INTEGER PRIMARY KEY, checklist_id INTEGER NOT NULL REFERENCES checklists(id) ON DELETE CASCADE,
        rutina TEXT NOT NULL, item TEXT NOT NULL, cumple INTEGER NOT NULL, comentario TEXT)''')
    c.execute('CREATE INDEX IF NOT EXISTS ix_chk_resp ON checklist_respuestas(checklist_id)')

def demo(c, up):
    """Solo datos de EJEMPLO: historial de los últimos 6 días (nunca hoy) para los técnicos de ejemplo. No hace nada si ya hay checklists."""
    if not up or not c.execute('SELECT 1 FROM ordenes WHERE ejemplo=1 LIMIT 1').fetchone() or c.execute('SELECT 1 FROM checklists LIMIT 1').fetchone(): return
    import random
    from PIL import Image, ImageDraw
    carpeta = os.path.join(up, SUB); os.makedirs(carpeta, exist_ok=True)
    def img(nombre, txt, col):
        im = Image.new('RGB', (640, 480), col); d = ImageDraw.Draw(im); d.rectangle([20, 20, 620, 460], outline=(255, 255, 255), width=4)
        d.text((40, 40), 'EJEMPLO', fill=(255, 255, 255)); d.text((40, 220), txt, fill=(255, 255, 255))
        im.save(os.path.join(carpeta, nombre), 'JPEG', quality=70); im.thumbnail((320, 320)); im.save(os.path.join(carpeta, 't_' + nombre), 'JPEG', quality=70)
        return nombre
    f_odo, f_comb, f_epp = img('ejemplo_odometro.jpg', 'Odometro', (40, 60, 90)), img('ejemplo_combustible.jpg', 'Indicador de combustible', (90, 70, 30)), img('ejemplo_epp.jpg', 'Cuadrilla con EPP', (30, 90, 60))
    rnd = random.Random(7); hoy = hoy_mx().date()
    items = {r: [n for (n,) in c.execute('SELECT nombre FROM checklist_items WHERE rutina=? AND activo=1 ORDER BY orden, id', (r,))] for r in RUTINAS}
    tecs = c.execute("""SELECT t.id, t.cuadrilla_id, (SELECT v.id FROM vehiculos v WHERE v.cuadrilla_id=t.cuadrilla_id AND v.activo=1 ORDER BY v.numero LIMIT 1)
        FROM tecnicos t WHERE t.ejemplo=1 AND t.puesto='Técnico Instalador' AND t.cuadrilla_id IS NOT NULL ORDER BY t.id""").fetchall()
    km = {}
    for dias in range(6, 0, -1):
        f = (hoy - dt.timedelta(days=dias)).isoformat()
        for tid, cid, vid in tecs:
            if not vid or rnd.random() < 0.12: continue   # algún día sin registro (descanso)
            km[vid] = km.get(vid, rnd.randint(18000, 95000)) + rnd.randint(25, 180)
            k, ant, alerta = km[vid], c.execute('SELECT km FROM checklists WHERE vehiculo_id=? ORDER BY fecha DESC, id DESC LIMIT 1', (vid,)).fetchone(), 0
            if dias == 2 and tid == tecs[0][0]: k, alerta = k - 400, 1   # captura con km menor (ejemplo de alerta)
            ch = c.execute('''INSERT INTO checklists(fecha,personal_id,cuadrilla_id,vehiculo_id,km,km_anterior,km_alerta,foto_odometro,combustible,foto_combustible,veh_fin,foto_epp,seg_fin,ejemplo)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,1)''', (f, tid, cid, vid, k, ant[0] if ant else None, alerta, f_odo, rnd.choice(COMBUSTIBLE), f_comb, f + 'T07:%02d' % rnd.randint(5, 40), f_epp, f + 'T07:%02d' % rnd.randint(41, 59))).lastrowid
            for r in RUTINAS:
                for n in items[r]:
                    falla = rnd.random() < 0.05
                    c.execute('INSERT INTO checklist_respuestas(checklist_id,rutina,item,cumple,comentario) VALUES(?,?,?,?,?)',
                              (ch, r, n, 0 if falla else 1, 'EJEMPLO: ' + rnd.choice(['se reporta a supervisor', 'pendiente reponer', 'dañado, se solicita cambio']) if falla else None))

# ---------- quién debe hacerlo ----------
def debe_hacer():
    return bool(getattr(g, 'user', None)) and not PERM.es_su() and PERM.can('checklist.realizar')

def registro_hoy(q):
    return q('SELECT * FROM checklists WHERE fecha=? AND personal_id=?', (fecha_hoy(), g.user['id']), one=True)

def completo(r): return bool(r and r['veh_fin'] and r['seg_fin'])

def ultimo_km(q, vid, excluir=None):
    return q('''SELECT c.km, c.fecha, t.nombre FROM checklists c LEFT JOIN tecnicos t ON t.id=c.personal_id
        WHERE c.vehiculo_id=? AND c.km IS NOT NULL AND c.id IS NOT ? ORDER BY c.fecha DESC, c.id DESC LIMIT 1''', (vid, excluir), one=True)

def alcance_sql(a='c'):
    """Filtro de la revisión según el alcance del perfil: todas / su equipo (cuadrilla propia o supervisada) / solo propios."""
    if PERM.es_su() or not getattr(g, 'user', None): return '1=1', []
    al = PERM.alcance()[0]; u = g.user
    if al == 'propias': return f'{a}.personal_id=?', [u['id']]
    if al == 'equipo':
        return (f'({a}.personal_id=? OR {a}.cuadrilla_id=? OR {a}.cuadrilla_id IN (SELECT id FROM cuadrillas WHERE supervisor_id=?) '
                f'OR {a}.personal_id IN (SELECT id FROM tecnicos WHERE cuadrilla_id=? OR cuadrilla_id IN (SELECT id FROM cuadrillas WHERE supervisor_id=?)))'), [u['id'], u['cuadrilla_id'], u['id'], u['cuadrilla_id'], u['id']]
    return '1=1', []

def registrar(app, q, db, UP):
    global UP_DIR; UP_DIR = UP
    carpeta = os.path.join(UP, SUB); os.makedirs(carpeta, exist_ok=True)
    app.jinja_env.globals.update(CHK_COMBUSTIBLE=COMBUSTIBLE, CHK_SUB=SUB)

    @app.context_processor
    def _chk_ctx():   # mientras falte el checklist del día no se muestra el menú (solo «Salir»)
        try: return dict(CHK_BLOQUEO=debe_hacer() and not completo(registro_hoy(q)))
        except Exception: return dict(CHK_BLOQUEO=False)

    @app.before_request
    def _checklist_obligatorio():
        """Hasta terminar las dos rutinas del día, el técnico solo puede usar /checklist (y salir)."""
        p = request.path
        if p.startswith(LIBRES) and not p.startswith('/checklists') or not debe_hacer(): return
        if completo(registro_hoy(q)): return
        if p.startswith('/api/'): return jsonify(error='Completa tu checklist diario antes de continuar'), 403
        return redirect('/checklist')

    def items(rut): return q('SELECT * FROM checklist_items WHERE rutina=? AND activo=1 ORDER BY orden, id', (rut,))

    def vehiculos(): return q("SELECT v.id, v.numero, v.placas, v.cuadrilla_id, v.personal_id, v.asignacion_tipo, c.nombre cuadrilla, t.nombre persona FROM vehiculos v LEFT JOIN cuadrillas c ON c.id=v.cuadrilla_id LEFT JOIN tecnicos t ON t.id=v.personal_id AND v.asignacion_tipo='Persona' WHERE COALESCE(v.activo,1)=1 ORDER BY v.numero")

    def respuestas(rut, its):
        """Lee las respuestas Cumple / No cumple. Cada punto debe contestarse; «No cumple» requiere comentario."""
        out, err = [], []
        for it in its:
            v = request.form.get(f'i{it["id"]}'); com = (request.form.get(f'c{it["id"]}') or '').strip()
            if v not in ('1', '0'): err.append(f'Contesta «{it["nombre"]}»'); continue
            if v == '0' and not com: err.append(f'«{it["nombre"]}»: explica por qué no cumple'); continue
            out.append((rut, it['nombre'], int(v), com[:500] if v == '0' else None))
        return out, err

    def foto(campo):
        fs = request.files.get(campo)
        if not fs or not fs.filename: return None, 'falta'
        try: return SF.guardar_imagen(fs, carpeta), None
        except Exception: return None, 'no es imagen'

    @app.route('/checklist', methods=['GET'])
    def checklist():
        if not debe_hacer(): return redirect(PERM.inicio() or '/')
        r = registro_hoy(q)
        if completo(r): return render_template('checklist.html', paso='listo', r=r, hoy=fecha_hoy(), ini=PERM.inicio() or '/', resumen=resumen(r['id']), veh=q('SELECT * FROM vehiculos WHERE id=?', (r['vehiculo_id'],), one=True))
        if r and r['veh_fin']: return render_template('checklist.html', paso='seguridad', r=r, items=items('Seguridad'), hoy=fecha_hoy(), err=None, F={}, veh=q('SELECT * FROM vehiculos WHERE id=?', (r['vehiculo_id'],), one=True))
        return form_vehiculo()

    def form_vehiculo(err=None, km_bajo=None):
        u = g.user; vs = vehiculos()
        # sugerido: el vehículo que ya registró hoy alguien de su cuadrilla; si no, el asignado a su cuadrilla
        hoy_cuad = q('SELECT c.vehiculo_id, c.km, t.nombre FROM checklists c JOIN tecnicos t ON t.id=c.personal_id WHERE c.fecha=? AND c.cuadrilla_id=? AND c.personal_id<>? AND c.vehiculo_id IS NOT NULL ORDER BY c.id LIMIT 1',
                     (fecha_hoy(), u['cuadrilla_id'], u['id']), one=True) if u['cuadrilla_id'] else None
        # prioridad: vehículo asignado directamente a la persona > el que ya usa hoy su cuadrilla > el asignado a su cuadrilla
        propio = next((v['id'] for v in vs if v['asignacion_tipo'] == 'Persona' and v['personal_id'] == u['id']), None)
        asignado = next((v['id'] for v in vs if u['cuadrilla_id'] and v['asignacion_tipo'] != 'Persona' and v['cuadrilla_id'] == u['cuadrilla_id']), None)
        sel = request.form.get('vehiculo_id', type=int) or propio or (hoy_cuad['vehiculo_id'] if hoy_cuad else asignado)
        ult = {v['id']: dict(ultimo_km(q, v['id']) or {}) for v in vs}
        return render_template('checklist.html', paso='vehiculo', vs=vs, sel=sel, asignado=asignado, propio=propio, hoy_cuad=hoy_cuad, ult=ult, items=items('Vehículo'),
                               hoy=fecha_hoy(), err=err, km_bajo=km_bajo, F=request.form if request.method == 'POST' else {})

    @app.route('/checklist/vehiculo', methods=['POST'])
    def checklist_vehiculo():
        if not debe_hacer(): abort(403)
        r = registro_hoy(q)
        if r and r['veh_fin']: return redirect('/checklist')
        F = request.form; err = []
        vid = F.get('vehiculo_id', type=int)
        v = q('SELECT * FROM vehiculos WHERE id=? AND COALESCE(activo,1)=1', (vid,), one=True) if vid else None
        if not v: err.append('Selecciona el vehículo')
        try: km = int((F.get('km') or '').replace(',', '').strip()); assert 0 <= km < 10_000_000
        except Exception: km = None; err.append('Captura el kilometraje (número entero)')
        comb = F.get('combustible')
        if comb not in COMBUSTIBLE: err.append('Selecciona el nivel de combustible')
        resp, e2 = respuestas('Vehículo', items('Vehículo')); err += e2
        ult = ultimo_km(q, vid) if v else None; km_bajo = None
        if v and km is not None and ult and km < ult['km']:
            km_bajo = dict(ult)
            if not F.get('km_confirmo'): err.append(f'El kilometraje es menor al último registrado del vehículo {v["numero"]} ({ult["km"]:,} km el {ult["fecha"]}). Verifica o confirma que es correcto.')
        if not request.files.get('foto_odometro') or not request.files['foto_odometro'].filename: err.append('Falta la foto del odómetro')
        if not request.files.get('foto_combustible') or not request.files['foto_combustible'].filename: err.append('Falta la foto del indicador de combustible')
        if err: return form_vehiculo(err, km_bajo)
        fo, e_o = foto('foto_odometro'); fc, e_c = foto('foto_combustible')
        if e_o or e_c: return form_vehiculo([x for x in ['La foto del odómetro no es una imagen válida' if e_o else '', 'La foto del indicador de combustible no es una imagen válida' if e_c else ''] if x])
        u = g.user; con = db()
        if r: con.execute('DELETE FROM checklist_respuestas WHERE checklist_id=?', (r['id'],)); cid = r['id']
        else: cid = con.execute('INSERT INTO checklists(fecha, personal_id) VALUES(?,?)', (fecha_hoy(), u['id'])).lastrowid
        con.execute('''UPDATE checklists SET cuadrilla_id=?, vehiculo_id=?, km=?, km_anterior=?, km_alerta=?, foto_odometro=?, combustible=?, foto_combustible=?, veh_obs=?, veh_fin=? WHERE id=?''',
                    (u['cuadrilla_id'], vid, km, ult['km'] if ult else None, 1 if km_bajo else 0, fo, comb, fc, (F.get('veh_obs') or '').strip()[:1000] or None, ahora(), cid))
        con.executemany('INSERT INTO checklist_respuestas(checklist_id,rutina,item,cumple,comentario) VALUES(?,?,?,?,?)', [(cid,) + x for x in resp])
        con.commit()
        return redirect('/checklist')

    @app.route('/checklist/seguridad', methods=['POST'])
    def checklist_seguridad():
        if not debe_hacer(): abort(403)
        r = registro_hoy(q)
        if not r or not r['veh_fin']: return redirect('/checklist')   # primero la rutina 1
        if r['seg_fin']: return redirect('/checklist')
        its = items('Seguridad'); resp, err = respuestas('Seguridad', its)
        if not request.files.get('foto_epp') or not request.files['foto_epp'].filename: err.append('Falta la foto de la cuadrilla con su EPP puesto')
        fe = None
        if not err:
            fe, e = foto('foto_epp')
            if e: err.append('La foto de la cuadrilla no es una imagen válida')
        if err: return render_template('checklist.html', paso='seguridad', r=r, items=its, hoy=fecha_hoy(), err=err, F=request.form, veh=q('SELECT * FROM vehiculos WHERE id=?', (r['vehiculo_id'],), one=True))
        con = db(); con.execute("DELETE FROM checklist_respuestas WHERE checklist_id=? AND rutina='Seguridad'", (r['id'],))
        con.execute('UPDATE checklists SET foto_epp=?, seg_obs=?, seg_fin=? WHERE id=?', (fe, (request.form.get('seg_obs') or '').strip()[:1000] or None, ahora(), r['id']))
        con.executemany('INSERT INTO checklist_respuestas(checklist_id,rutina,item,cumple,comentario) VALUES(?,?,?,?,?)', [(r['id'],) + x for x in resp])
        con.commit()
        return redirect('/checklist')

    def resumen(cid):
        return q('SELECT rutina, SUM(cumple=0) nc, COUNT(*) n FROM checklist_respuestas WHERE checklist_id=? GROUP BY rutina', (cid,))

    # ---------- revisión ----------
    BASE = '''SELECT c.*, t.nombre tecnico, cu.nombre cuadrilla, v.numero vnum, v.placas,
        (SELECT COUNT(*) FROM checklist_respuestas r WHERE r.checklist_id=c.id AND r.cumple=0) nc,
        CASE WHEN c.km_anterior IS NOT NULL AND c.km IS NOT NULL THEN c.km - c.km_anterior END km_delta
        FROM checklists c LEFT JOIN tecnicos t ON t.id=c.personal_id LEFT JOIN cuadrillas cu ON cu.id=c.cuadrilla_id LEFT JOIN vehiculos v ON v.id=c.vehiculo_id'''

    @app.route('/checklists')
    def checklists():
        A = request.args; hoy = fecha_hoy()
        desde = A.get('desde') or (hoy_mx().date() - dt.timedelta(days=6)).isoformat(); hasta = A.get('hasta') or hoy
        w, a = alcance_sql('c'); w = [w, 'c.fecha BETWEEN ? AND ?']; a = a + [desde, hasta]
        tid = A.get('tecnico', type=int); vid = A.get('vehiculo', type=int); solo = A.get('flags') == '1'
        if tid: w.append('c.personal_id=?'); a.append(tid)
        if vid: w.append('c.vehiculo_id=?'); a.append(vid)
        if solo: w.append('(c.km_alerta=1 OR EXISTS(SELECT 1 FROM checklist_respuestas r WHERE r.checklist_id=c.id AND r.cumple=0) OR c.seg_fin IS NULL)')
        rows = q(f'{BASE} WHERE {" AND ".join(w)} ORDER BY c.fecha DESC, c.veh_fin DESC LIMIT 300', a)
        fallas = {}
        for x in q(f"SELECT r.checklist_id, r.rutina, r.item, r.comentario FROM checklist_respuestas r WHERE r.cumple=0 AND r.checklist_id IN ({','.join(str(r['id']) for r in rows) or 'NULL'})"):
            fallas.setdefault(x['checklist_id'], []).append(x)
        # técnicos que deben hacerlo (perfil con «checklist.realizar» y acceso activo) y aún no terminan hoy
        sw, sa = alcance_sql('c2')
        obligados = [t for t in q('''SELECT t.id, t.nombre, t.puesto, t.perfil_id, cu.nombre cuadrilla, c2.veh_fin, c2.seg_fin, c2.personal_id, c2.cuadrilla_id FROM tecnicos t LEFT JOIN cuadrillas cu ON cu.id=t.cuadrilla_id
                     LEFT JOIN checklists c2 ON c2.personal_id=t.id AND c2.fecha=? WHERE COALESCE(t.activo,1)=1 AND t.login_activo=1 AND t.pass_hash IS NOT NULL ORDER BY t.nombre''', (hoy,))
                     if obligado(t) and visible_persona(t)]
        tecs = q(f"SELECT DISTINCT t.id, t.nombre FROM checklists c JOIN tecnicos t ON t.id=c.personal_id WHERE {alcance_sql('c')[0]} ORDER BY t.nombre", alcance_sql('c')[1])
        return render_template('checklists.html', rows=rows, fallas=fallas, desde=desde, hasta=hasta, tid=tid, vid=vid, solo=solo, tecs=tecs, vs=vehiculos(), hoy=hoy, obligados=obligados,
                               km_hist=km_historial(vid) if vid else None, veh=q('SELECT * FROM vehiculos WHERE id=?', (vid,), one=True) if vid else None)

    def obligado(t):
        """¿El perfil de esa persona incluye «checklist.realizar»?"""
        pf = q('SELECT id FROM perfiles WHERE id=?', (t['perfil_id'],), one=True) if t['perfil_id'] else None
        pid = pf['id'] if pf else (q('SELECT id FROM perfiles WHERE clave=?', (PERM.perfil_de_puesto(t['puesto']),), one=True) or {'id': None})['id']
        return bool(pid and q("SELECT 1 FROM perfil_permisos WHERE perfil_id=? AND permiso='checklist.realizar'", (pid,), one=True))

    def visible_persona(t):
        if PERM.es_su() or PERM.alcance()[0] in ('todas', 'tipo'): return True
        u = g.user
        if t['id'] == u['id']: return True
        if PERM.alcance()[0] == 'propias': return False
        cu = q('SELECT cuadrilla_id FROM tecnicos WHERE id=?', (t['id'],), one=True)['cuadrilla_id']
        return bool(cu and (cu == u['cuadrilla_id'] or q('SELECT 1 FROM cuadrillas WHERE id=? AND supervisor_id=?', (cu, u['id']), one=True)))

    def km_historial(vid):
        w, a = alcance_sql('c')
        h = q(f'{BASE} WHERE c.vehiculo_id=? AND c.km IS NOT NULL AND {w} ORDER BY c.fecha DESC, c.id DESC LIMIT 60', [vid] + a)
        return h

    @app.route('/checklists/<int:cid>')
    def checklist_ver(cid):
        w, a = alcance_sql('c')
        r = q(f'{BASE} WHERE c.id=? AND {w}', [cid] + a, one=True) or abort(404)
        resp = q('SELECT * FROM checklist_respuestas WHERE checklist_id=? ORDER BY id', (cid,))
        return render_template('checklist_ver.html', r=r, resp={rt: [x for x in resp if x['rutina'] == rt] for rt in RUTINAS})
