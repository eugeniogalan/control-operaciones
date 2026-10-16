"""Documentos de contrato de arrendamiento por site (PDF e imágenes) en uploads/sitios/contratos."""
import os, uuid, datetime as dt
from flask import request, redirect, abort
import sitio_fotos as SF

SUB = 'sitios/contratos'
MAX_PDF = 15 * 1024 * 1024
CATS = {'Contrato arrendamiento': 'Rentado', 'Acuerdo intercambio': 'Intercambio'}
VENCE_SQL = "(CASE tenencia WHEN 'Rentado' THEN arr_vence WHEN 'Intercambio' THEN int_vence END)"
ALERTA_SQL = f"""CASE WHEN {VENCE_SQL} IS NOT NULL THEN CASE WHEN {VENCE_SQL} < date('now','localtime') THEN 'vencido'
    WHEN {VENCE_SQL} <= date('now','localtime','+60 days') THEN 'pronto' END END"""

def migrar(c):
    c.execute('''CREATE TABLE IF NOT EXISTS sitio_documentos(id INTEGER PRIMARY KEY, sitio_id INTEGER NOT NULL REFERENCES sitios(id) ON DELETE CASCADE,
        categoria TEXT DEFAULT 'Contrato', archivo TEXT NOT NULL, nombre_original TEXT, tipo TEXT, tamano INTEGER, fecha TEXT DEFAULT (datetime('now','localtime')), comentario TEXT)''')
    c.execute('CREATE INDEX IF NOT EXISTS ix_sitio_docs ON sitio_documentos(sitio_id)')
    c.execute("UPDATE sitio_documentos SET categoria='Contrato arrendamiento' WHERE categoria IS NULL OR categoria='Contrato'")

def carpeta(): return os.path.join(SF.UP_DIR, SUB)

def borrar_archivo(d):
    for n in ([d['archivo'], 't_' + d['archivo']] if d['tipo'] == 'img' else [d['archivo']]):
        try: os.remove(os.path.join(carpeta(), n))
        except OSError: pass

def guardar_doc(db, sid, cat, fs, com=None):
    """Guarda un archivo (PDF tal cual o imagen comprimida). Devuelve texto de error o None."""
    cab = fs.stream.read(5); fs.stream.seek(0)
    if cab == b'%PDF-':
        fs.stream.seek(0, os.SEEK_END); tam = fs.stream.tell(); fs.stream.seek(0)
        if tam > MAX_PDF: return f'{fs.filename} (excede 15 MB)'
        nombre = uuid.uuid4().hex + '.pdf'; fs.save(os.path.join(carpeta(), nombre)); tipo = 'pdf'
    else:
        try: nombre = SF.guardar_imagen(fs, carpeta()); tipo = 'img'
        except Exception: return f'{fs.filename} (no es PDF ni imagen)'
        tam = os.path.getsize(os.path.join(carpeta(), nombre))
    db().execute('INSERT INTO sitio_documentos(sitio_id,categoria,archivo,nombre_original,tipo,tamano,comentario) VALUES(?,?,?,?,?,?,?)', (sid, cat, nombre, fs.filename[:200], tipo, tam, com))

def registrar(app, q, db):
    os.makedirs(carpeta(), exist_ok=True)
    app.jinja_env.globals['sitio_docs'] = lambda sid, cat=None: q('SELECT * FROM sitio_documentos WHERE sitio_id=? AND (? IS NULL OR categoria=?) ORDER BY fecha, id', (sid, cat, cat))
    app.jinja_env.globals['DOCS_SUB'] = SUB

    def volver_ok(v, sid): return v if v and v.startswith('/') and not v.startswith('//') else f'/configuracion/sites/{sid}/editar'
    def con_msg(v, m): return v + ('&' if '?' in v else '?') + 'msg=' + m + '#blk_tenencia'

    @app.route('/sites/<int:sid>/documentos/subir', methods=['POST'])
    def sitio_docs_subir(sid):
        s = q('SELECT * FROM sitios WHERE id=?', (sid,), one=True) or abort(404)
        v = volver_ok(request.form.get('volver'), sid)
        cat = request.form.get('categoria') or 'Contrato arrendamiento'
        if cat not in CATS: abort(400)
        if s['tenencia'] != CATS[cat]: return redirect(con_msg(v, f'Solo se pueden subir documentos de «{cat}» cuando la tenencia es {CATS[cat]}'))
        com = (request.form.get('comentario') or '').strip() or None; n = 0; malos = []
        for fs in request.files.getlist('docs'):
            if not fs or not fs.filename: continue
            e = guardar_doc(db, sid, cat, fs, com)
            if e: malos.append(e)
            else: n += 1
        db().commit()
        return redirect(con_msg(v, f'{n} documento(s) agregado(s)' + (('; rechazados: ' + ', '.join(malos)) if malos else '')))

    @app.route('/sites/documentos/<int:did>/borrar', methods=['POST'])
    def sitio_docs_borrar(did):
        d = q('SELECT * FROM sitio_documentos WHERE id=?', (did,), one=True) or abort(404)
        db().execute('DELETE FROM sitio_documentos WHERE id=?', (did,)); db().commit(); borrar_archivo(d)
        return redirect(con_msg(volver_ok(request.form.get('volver'), d['sitio_id']), 'Documento eliminado'))
