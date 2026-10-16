"""UPS por site (varias unidades): tabla sitio_ups, alta/cambio/baja, fotos por unidad y alertas de cambio de baterías."""
import datetime as dt
from flask import request, redirect, abort, render_template
import config_mod as CM
import sitio_fotos as SF

CAMPOS = ['marca', 'modelo', 'capacidad_kva', 'autonomia_min', 'num_baterias', 'bat_instalacion']
_HOY = "date('now','localtime')"
ALERTA_UNIDAD = f"CASE WHEN u.bat_cambio IS NULL THEN NULL WHEN u.bat_cambio <= {_HOY} THEN 'vencido' WHEN u.bat_cambio <= date('now','localtime','+90 days') THEN 'pronto' END"
_UPS_ON = "','||COALESCE(sitios.energia,'')||',' LIKE '%,UPS,%'"
_KVA = "(CASE WHEN u.capacidad_kva=CAST(u.capacidad_kva AS INT) THEN CAST(u.capacidad_kva AS INT) ELSE u.capacidad_kva END)||'kVA'||COALESCE(' '||u.marca,'')"
# columnas para el SELECT de la lista de Sites
RESUMEN_SQL = f"""(SELECT CASE WHEN COUNT(*)=0 THEN NULL WHEN COUNT(*)=1 THEN 'UPS '||MAX(d) ELSE 'UPS '||COUNT(*)||'× ('||GROUP_CONCAT(d, ', ')||')' END
    FROM (SELECT {_KVA} d FROM sitio_ups u WHERE u.sitio_id=sitios.id ORDER BY u.capacidad_kva DESC, u.id)) """
ALERTA_SITIO_SQL = f"""CASE WHEN {_UPS_ON} THEN (SELECT CASE WHEN MIN(u.bat_cambio) <= {_HOY} THEN 'vencido' WHEN MIN(u.bat_cambio) <= date('now','localtime','+90 days') THEN 'pronto' END FROM sitio_ups u WHERE u.sitio_id=sitios.id) END"""
CAMBIO_MIN_SQL = "(SELECT MIN(u.bat_cambio) FROM sitio_ups u WHERE u.sitio_id=sitios.id)"
# para el Panel: una fila por unidad con alerta
PANEL_SQL = f"""SELECT sitios.id, sitios.codigo, sitios.nombre, u.id ups_id, u.num_baterias, u.marca, u.modelo, u.capacidad_kva, u.bat_cambio, {ALERTA_UNIDAD} alerta
    FROM sitio_ups u JOIN sitios ON sitios.id=u.sitio_id WHERE sitios.activo=1 AND {_UPS_ON}"""

def migrar(c):
    c.execute('''CREATE TABLE IF NOT EXISTS sitio_ups(id INTEGER PRIMARY KEY, sitio_id INTEGER NOT NULL REFERENCES sitios(id) ON DELETE CASCADE,
        marca TEXT, modelo TEXT, capacidad_kva REAL NOT NULL, autonomia_min INTEGER, num_baterias INTEGER, bat_instalacion TEXT, bat_cambio TEXT)''')
    c.execute('CREATE INDEX IF NOT EXISTS ix_sitio_ups ON sitio_ups(sitio_id)')
    if 'ups_id' not in [r[1] for r in c.execute('PRAGMA table_info(sitio_fotos)')]:
        c.execute('ALTER TABLE sitio_fotos ADD COLUMN ups_id INTEGER REFERENCES sitio_ups(id) ON DELETE SET NULL')
    if not c.execute('SELECT 1 FROM sitio_ups LIMIT 1').fetchone():
        r = c.execute("SELECT id, energia FROM sitios WHERE codigo='SPN-POP-01' AND ejemplo=1").fetchone()
        if r:
            if 'UPS' not in (r[1] or '').split(','): c.execute("UPDATE sitios SET energia=TRIM(COALESCE(energia,'')||',UPS', ',') WHERE id=?", (r[0],))
            hoy = dt.date.today()
            for ma, mo, kva, aut, nb, ins in (('APC', 'Smart-UPS SRT 3000', 3, 15, 8, (hoy - dt.timedelta(days=365)).isoformat()),                     # bien
                                              ('Eaton', '5E 1100', 1, 8, 2, (hoy.replace(year=hoy.year - 3) + dt.timedelta(days=30)).isoformat())):  # vence en ~30 días
                c.execute('INSERT INTO sitio_ups(sitio_id,marca,modelo,capacidad_kva,autonomia_min,num_baterias,bat_instalacion,bat_cambio) VALUES(?,?,?,?,?,?,?,?)',
                          (r[0], ma, mo, kva, aut, nb, ins, CM.fecha_cambio_bat(ins)))

def ups_activo(s): return 'UPS' in (s['energia'] or '').split(',')

def registrar(app, q, db):
    def unidades(sid):
        return q(f"SELECT u.*, {ALERTA_UNIDAD} alerta, (SELECT COUNT(*) FROM sitio_fotos f WHERE f.ups_id=u.id) nfotos FROM sitio_ups u WHERE u.sitio_id=? ORDER BY u.id", (sid,))
    app.jinja_env.globals['sitio_ups_unidades'] = unidades

    def leer(F):
        d, err = {}, None
        d['marca'] = (F.get('marca') or '').strip() or None; d['modelo'] = (F.get('modelo') or '').strip() or None
        for col, lab, conv in (('capacidad_kva', 'Capacidad (kVA)', float), ('autonomia_min', 'Autonomía (min)', int), ('num_baterias', 'Número de baterías', int)):
            v = (F.get(col) or '').strip()
            try: d[col] = conv(v) if v else None
            except ValueError: err = err or f'{lab} debe ser numérico'; d[col] = None
        d['bat_instalacion'] = (F.get('bat_instalacion') or '').strip() or None; d['bat_cambio'] = None
        if not err:
            if d['capacidad_kva'] is None or d['capacidad_kva'] <= 0: err = 'Capacidad (kVA) es obligatoria y debe ser mayor a 0'
            elif d['autonomia_min'] is not None and d['autonomia_min'] <= 0: err = 'Autonomía debe ser mayor a 0'
            elif d['num_baterias'] is not None and d['num_baterias'] <= 0: err = 'Número de baterías debe ser mayor a 0'
            elif d['bat_instalacion']:
                try: d['bat_cambio'] = CM.fecha_cambio_bat(d['bat_instalacion'])
                except ValueError: err = 'Fecha de instalación de baterías inválida'
        return d, err

    @app.route('/sites/<int:sid>/ups/nuevo', methods=['GET', 'POST'])
    @app.route('/sites/ups/<int:uid>/editar', methods=['GET', 'POST'])
    def sitio_ups_form(sid=None, uid=None):
        u = dict(q('SELECT * FROM sitio_ups WHERE id=?', (uid,), one=True) or abort(404)) if uid else {}
        sid = u.get('sitio_id', sid); s = q('SELECT * FROM sitios WHERE id=?', (sid,), one=True) or abort(404)
        volver = f'/configuracion/sites/{sid}/editar'; err = None
        if not uid and not ups_activo(s): return redirect(volver + '?msg=Activa UPS en Tipo de energía (y guarda) para agregar unidades#blk_UPS')
        if request.method == 'POST':
            d, err = leer(request.form)
            if not err:
                if uid: db().execute(f"UPDATE sitio_ups SET {', '.join(k+'=?' for k in d)} WHERE id=?", list(d.values()) + [uid])
                else: db().execute(f"INSERT INTO sitio_ups(sitio_id,{','.join(d)}) VALUES(?,{','.join('?'*len(d))})", [sid] + list(d.values()))
                db().commit(); return redirect(volver + '?msg=UPS guardado#blk_UPS')
            u.update(d)
        fotos = q('SELECT * FROM sitio_fotos WHERE ups_id=? ORDER BY fecha, id', (uid,)) if uid else []
        return render_template('sitio_ups_form.html', s=s, u=u, uid=uid, err=err, fotos=fotos, SUB=SF.SUB, puede_fotos=True, msg=request.args.get('msg'))

    @app.route('/sites/ups/<int:uid>/borrar', methods=['POST'])
    def sitio_ups_borrar(uid):
        u = q('SELECT * FROM sitio_ups WHERE id=?', (uid,), one=True) or abort(404)
        for f in q('SELECT archivo FROM sitio_fotos WHERE ups_id=?', (uid,)): SF.borrar_archivos(SF.UP_DIR, f['archivo'])
        db().execute('DELETE FROM sitio_fotos WHERE ups_id=?', (uid,)); db().execute('DELETE FROM sitio_ups WHERE id=?', (uid,)); db().commit()
        return redirect(f"/configuracion/sites/{u['sitio_id']}/editar?msg=UPS eliminado#blk_UPS")
