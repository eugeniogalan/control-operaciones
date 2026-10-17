"""Vehículos: fotografías (4 vistas fijas), documentos PDF (tarjeta de circulación y póliza) y datos del seguro.
Reutiliza la compresión de fotos de Sites (sitio_fotos.guardar_imagen)."""
import os, uuid, datetime as dt
from flask import request, redirect, abort
import sitio_fotos as SF

FOTO_CATS = ['Frente del vehículo', 'Trasero del vehículo', 'Costado derecho', 'Costado izquierdo']
DOC_CATS = ['Tarjeta de circulación', 'Póliza de seguro']
SUB = 'vehiculos'
SUB_DOCS = 'vehiculos/docs'
MAX_PDF = 15 * 1024 * 1024
DIAS_AVISO = 30
COLS = [('seguro_compania', 'TEXT'), ('seguro_poliza', 'TEXT'), ('seguro_vence', 'TEXT')]
SEGURO = [c for c, _ in COLS]
# clave -> (texto, estilo del badge)
ESTADOS = {'vigente': ('Vigente', 'background:#e7f6ec;color:#15803d;border:1px solid #b9e3c6'),
           'proxima': ('Próxima a vencer', 'background:#fdf6e3;color:#a16207;border:1px solid #ecd59a'),
           'vencida': ('Vencida', 'background:#fdecec;color:#c62828;border:1px solid #f3c4c4')}
FILTROS = [('', 'Todos'), ('vigente', 'Vigente'), ('proxima', 'Próxima a vencer'), ('vencida', 'Vencida'), ('alerta', '⚠ Por atender'), ('sin', 'Sin vencimiento')]

def seg_sql(p=''):
    """Expresión SQL con el estado del seguro: vigente / proxima / vencida / NULL (sin fecha)."""
    v = f'{p}seguro_vence'
    return (f"(CASE WHEN COALESCE({v},'')='' THEN NULL WHEN {v} < date('now','localtime') THEN 'vencida' "
            f"WHEN {v} <= date('now','localtime','+{DIAS_AVISO} days') THEN 'proxima' ELSE 'vigente' END)")

def estado(fecha):
    try: f = dt.date.fromisoformat(fecha) if fecha else None
    except (TypeError, ValueError): return None
    if not f: return None
    h = dt.date.today()
    return 'vencida' if f < h else ('proxima' if f <= h + dt.timedelta(days=DIAS_AVISO) else 'vigente')

def filtro_sql(clave, p=''):
    """(condición, args) para el filtro de la lista; None si la clave no es válida o es 'Todos'."""
    e = seg_sql(p)
    if clave in ('vigente', 'proxima', 'vencida'): return f'{e}=?', [clave]
    if clave == 'alerta': return f"{e} IN ('proxima','vencida')", []
    if clave == 'sin': return f'{e} IS NULL', []
    return None

def migrar(c):
    c.execute('''CREATE TABLE IF NOT EXISTS vehiculo_fotos(id INTEGER PRIMARY KEY, vehiculo_id INTEGER NOT NULL REFERENCES vehiculos(id) ON DELETE CASCADE,
        categoria TEXT NOT NULL, archivo TEXT NOT NULL, fecha TEXT DEFAULT (datetime('now','localtime')), comentario TEXT)''')
    c.execute('CREATE INDEX IF NOT EXISTS ix_veh_fotos ON vehiculo_fotos(vehiculo_id)')
    c.execute('''CREATE TABLE IF NOT EXISTS vehiculo_documentos(id INTEGER PRIMARY KEY, vehiculo_id INTEGER NOT NULL REFERENCES vehiculos(id) ON DELETE CASCADE,
        categoria TEXT NOT NULL, archivo TEXT NOT NULL, nombre_original TEXT, tamano INTEGER, fecha TEXT DEFAULT (datetime('now','localtime')))''')
    c.execute('CREATE INDEX IF NOT EXISTS ix_veh_docs ON vehiculo_documentos(vehiculo_id)')
    vc = [r[1] for r in c.execute('PRAGMA table_info(vehiculos)')]
    for col, typ in COLS:
        if col not in vc: c.execute(f'ALTER TABLE vehiculos ADD COLUMN {col} {typ}')

def demo(c):
    """Solo datos de EJEMPLO: seguro ficticio para los vehículos (mezcla de vigentes, próximos a vencer y vencidos).
    No hace nada si la BD no es de ejemplo o si algún vehículo ya tiene datos de seguro."""
    if not c.execute('SELECT 1 FROM ordenes WHERE ejemplo=1 LIMIT 1').fetchone(): return
    if c.execute("SELECT 1 FROM vehiculos WHERE COALESCE(seguro_compania,'')<>'' OR COALESCE(seguro_poliza,'')<>'' OR COALESCE(seguro_vence,'')<>'' LIMIT 1").fetchone(): return
    if c.execute('SELECT 1 FROM vehiculo_documentos LIMIT 1').fetchone(): return
    cias = ['Seguros Ejemplo A', 'Aseguradora Ejemplo B', 'Seguros Ejemplo C']
    dias = [-12, 9, 21, -40, 27] + [90 + 17 * i for i in range(20)]
    h = dt.date.today()
    for i, (vid,) in enumerate(c.execute('SELECT id FROM vehiculos ORDER BY numero').fetchall()):
        c.execute('UPDATE vehiculos SET seguro_compania=?, seguro_poliza=?, seguro_vence=? WHERE id=?',
                  (cias[i % 3], f'EJEMPLO-POL-{i + 1:04d}', (h + dt.timedelta(days=dias[i % len(dias)])).isoformat(), vid))

def carpeta(sub): return os.path.join(SF.UP_DIR, sub)

def borrar_foto(f):
    for n in (f['archivo'], 't_' + f['archivo']):
        try: os.remove(os.path.join(carpeta(SUB), n))
        except OSError: pass

def borrar_doc(d):
    try: os.remove(os.path.join(carpeta(SUB_DOCS), d['archivo']))
    except OSError: pass

def es_pdf(fs):
    cab = fs.stream.read(5); fs.stream.seek(0)
    return cab == b'%PDF-'

def guardar_doc(db, q, vid, cat, fs):
    """Valida y guarda un PDF; reemplaza el documento anterior de esa categoría. Devuelve texto de error o None."""
    if not es_pdf(fs): return f'{fs.filename}: no es un PDF válido'
    fs.stream.seek(0, os.SEEK_END); tam = fs.stream.tell(); fs.stream.seek(0)
    if tam > MAX_PDF: return f'{fs.filename}: excede 15 MB'
    nombre = uuid.uuid4().hex + '.pdf'; fs.save(os.path.join(carpeta(SUB_DOCS), nombre))
    for d in q('SELECT * FROM vehiculo_documentos WHERE vehiculo_id=? AND categoria=?', (vid, cat)):
        borrar_doc(d); db().execute('DELETE FROM vehiculo_documentos WHERE id=?', (d['id'],))
    db().execute('INSERT INTO vehiculo_documentos(vehiculo_id,categoria,archivo,nombre_original,tamano) VALUES(?,?,?,?,?)',
                 (vid, cat, nombre, (fs.filename or 'documento.pdf')[:200], tam))

def adjuntos(db, q, vid):
    """Procesa las fotos y PDFs enviados junto con el formulario del vehículo (alta o cambios). Devuelve (resumen, errores)."""
    n = nd = 0; malos = []
    for i, cat in enumerate(FOTO_CATS):
        com = (request.form.get(f'vfc_{i}') or '').strip() or None
        for fs in request.files.getlist(f'vf_{i}'):
            if not fs or not fs.filename: continue
            try: arch = SF.guardar_imagen(fs, carpeta(SUB))
            except Exception: malos.append(f'{fs.filename}: no es una imagen'); continue
            db().execute('INSERT INTO vehiculo_fotos(vehiculo_id,categoria,archivo,comentario) VALUES(?,?,?,?)', (vid, cat, arch, com)); n += 1
    for i, cat in enumerate(DOC_CATS):
        fs = [f for f in request.files.getlist(f'vd_{i}') if f and f.filename]
        if fs:
            e = guardar_doc(db, q, vid, cat, fs[-1])
            if e: malos.append(e)
            else: nd += 1
    partes = ([f'{n} foto(s)'] if n else []) + ([f'{nd} documento(s)'] if nd else [])
    return ', '.join(partes), malos

def validar_pdfs():
    """Antes de guardar: rechaza archivos que no son PDF en Documentos (para no guardar nada a medias)."""
    for i, cat in enumerate(DOC_CATS):
        for fs in request.files.getlist(f'vd_{i}'):
            if fs and fs.filename and not es_pdf(fs): return f'«{cat}» debe ser un archivo PDF ({fs.filename} no lo es)'
            if fs and fs.filename:
                fs.stream.seek(0, os.SEEK_END); tam = fs.stream.tell(); fs.stream.seek(0)
                if tam > MAX_PDF: return f'«{cat}»: el PDF excede 15 MB'

def borrar_todo(db, q, vid):
    for f in q('SELECT * FROM vehiculo_fotos WHERE vehiculo_id=?', (vid,)): borrar_foto(f)
    for d in q('SELECT * FROM vehiculo_documentos WHERE vehiculo_id=?', (vid,)): borrar_doc(d)
    db().execute('DELETE FROM vehiculo_fotos WHERE vehiculo_id=?', (vid,)); db().execute('DELETE FROM vehiculo_documentos WHERE vehiculo_id=?', (vid,))

def registrar(app, q, db):
    for s in (SUB, SUB_DOCS): os.makedirs(carpeta(s), exist_ok=True)
    def ctx(vid):
        fotos = q('SELECT * FROM vehiculo_fotos WHERE vehiculo_id=? ORDER BY fecha, id', (vid,)) if vid else []
        docs = q('SELECT * FROM vehiculo_documentos WHERE vehiculo_id=? ORDER BY id', (vid,)) if vid else []
        return dict(fotos={c: [f for f in fotos if f['categoria'] == c] for c in FOTO_CATS}, docs={c: next((d for d in docs if d['categoria'] == c), None) for c in DOC_CATS},
                    FOTO_CATS=FOTO_CATS, DOC_CATS=DOC_CATS, SUB=SUB, SUB_DOCS=SUB_DOCS)
    app.jinja_env.globals.update(veh_adj=ctx, seguro_estado=estado, SEGURO_ESTADOS=ESTADOS, SEGURO_FILTROS=FILTROS, SEGURO_DIAS=DIAS_AVISO)

    def volver(vid):
        v = request.form.get('volver') or ''
        return v if v.startswith('/') and not v.startswith('//') else f'/configuracion/vehiculos/{vid}/editar'

    @app.route('/configuracion/vehiculos/fotos/<int:fid>/borrar', methods=['POST'])
    def veh_foto_borrar(fid):
        f = q('SELECT * FROM vehiculo_fotos WHERE id=?', (fid,), one=True) or abort(404)
        db().execute('DELETE FROM vehiculo_fotos WHERE id=?', (fid,)); db().commit(); borrar_foto(f)
        return redirect(volver(f['vehiculo_id']) + '?msg=Foto eliminada#fotos')

    @app.route('/configuracion/vehiculos/documentos/<int:did>/borrar', methods=['POST'])
    def veh_doc_borrar(did):
        d = q('SELECT * FROM vehiculo_documentos WHERE id=?', (did,), one=True) or abort(404)
        db().execute('DELETE FROM vehiculo_documentos WHERE id=?', (did,)); db().commit(); borrar_doc(d)
        return redirect(volver(d['vehiculo_id']) + '?msg=Documento eliminado#documentos')
