"""Documentos de contrato de arrendamiento por site (PDF e imágenes) en uploads/sitios/contratos."""
import os, uuid, datetime as dt
from flask import request, redirect, abort
import sitio_fotos as SF

SUB = 'sitios/contratos'
MAX_PDF = 15 * 1024 * 1024
ALERTA_SQL = """CASE WHEN tenencia='Rentado' AND arr_vence IS NOT NULL THEN CASE WHEN arr_vence < date('now','localtime') THEN 'vencido'
    WHEN arr_vence <= date('now','localtime','+60 days') THEN 'pronto' END END"""

def migrar(c):
    c.execute('''CREATE TABLE IF NOT EXISTS sitio_documentos(id INTEGER PRIMARY KEY, sitio_id INTEGER NOT NULL REFERENCES sitios(id) ON DELETE CASCADE,
        categoria TEXT DEFAULT 'Contrato', archivo TEXT NOT NULL, nombre_original TEXT, tipo TEXT, tamano INTEGER, fecha TEXT DEFAULT (datetime('now','localtime')), comentario TEXT)''')
    c.execute('CREATE INDEX IF NOT EXISTS ix_sitio_docs ON sitio_documentos(sitio_id)')

def carpeta(): return os.path.join(SF.UP_DIR, SUB)

def borrar_archivo(d):
    for n in ([d['archivo'], 't_' + d['archivo']] if d['tipo'] == 'img' else [d['archivo']]):
        try: os.remove(os.path.join(carpeta(), n))
        except OSError: pass

def registrar(app, q, db):
    os.makedirs(carpeta(), exist_ok=True)
    app.jinja_env.globals['sitio_docs'] = lambda sid: q('SELECT * FROM sitio_documentos WHERE sitio_id=? ORDER BY fecha, id', (sid,))
    app.jinja_env.globals['DOCS_SUB'] = SUB

    def volver_ok(v, sid): return v if v and v.startswith('/') and not v.startswith('//') else f'/configuracion/sites/{sid}/editar'
    def con_msg(v, m): return v + ('&' if '?' in v else '?') + 'msg=' + m + '#blk_arr'

    @app.route('/sites/<int:sid>/documentos/subir', methods=['POST'])
    def sitio_docs_subir(sid):
        s = q('SELECT * FROM sitios WHERE id=?', (sid,), one=True) or abort(404)
        v = volver_ok(request.form.get('volver'), sid)
        if s['tenencia'] != 'Rentado': return redirect(con_msg(v, 'Solo se pueden subir contratos cuando la tenencia es Rentado'))
        com = (request.form.get('comentario') or '').strip() or None; n = 0; malos = []
        for fs in request.files.getlist('docs'):
            if not fs or not fs.filename: continue
            cab = fs.stream.read(5); fs.stream.seek(0)
            if cab == b'%PDF-':
                fs.stream.seek(0, os.SEEK_END); tam = fs.stream.tell(); fs.stream.seek(0)
                if tam > MAX_PDF: malos.append(f'{fs.filename} (excede 15 MB)'); continue
                nombre = uuid.uuid4().hex + '.pdf'; fs.save(os.path.join(carpeta(), nombre)); tipo = 'pdf'
            else:
                try: nombre = SF.guardar_imagen(fs, carpeta()); tipo = 'img'
                except Exception: malos.append(f'{fs.filename} (no es PDF ni imagen)'); continue
                tam = os.path.getsize(os.path.join(carpeta(), nombre))
            db().execute('INSERT INTO sitio_documentos(sitio_id,archivo,nombre_original,tipo,tamano,comentario) VALUES(?,?,?,?,?,?)', (sid, nombre, fs.filename[:200], tipo, tam, com)); n += 1
        db().commit()
        return redirect(con_msg(v, f'{n} documento(s) agregado(s)' + (('; rechazados: ' + ', '.join(malos)) if malos else '')))

    @app.route('/sites/documentos/<int:did>/borrar', methods=['POST'])
    def sitio_docs_borrar(did):
        d = q('SELECT * FROM sitio_documentos WHERE id=?', (did,), one=True) or abort(404)
        db().execute('DELETE FROM sitio_documentos WHERE id=?', (did,)); db().commit(); borrar_archivo(d)
        return redirect(con_msg(volver_ok(request.form.get('volver'), d['sitio_id']), 'Documento eliminado'))
