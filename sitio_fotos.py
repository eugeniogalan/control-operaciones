"""Fotografías de Sites: categorías, subida con redimensión (Pillow) y miniaturas."""
import os, uuid, datetime
from flask import request, redirect, abort, render_template
from PIL import Image, ImageOps

GENERALES = ['Fachada exterior', 'Interior del sitio', 'Interior del gabinete', 'Torre / Mástil', 'Banco de baterías', 'Generador', 'UPS', 'Medidor de electricidad']
CATEGORIAS = GENERALES + ['Recibo CFE']
RENOMBRAR = {'Gabinete / Site': 'Interior del gabinete'}
CAT_CFE = 'Recibo CFE'
CAT_BAT = 'Banco de baterías'
# categoría -> tipo de energía requerido (se muestran dentro del bloque de esa energía)
CAT_UPS = 'UPS'
CAT_ENERGIA = {CAT_CFE: 'CFE', CAT_BAT: 'Solar', CAT_UPS: 'UPS'}
CAT_TORRE = 'Torre / Mástil'
SUB = 'sitios'
UP_DIR = None

def migrar(c):
    c.execute('''CREATE TABLE IF NOT EXISTS sitio_fotos(id INTEGER PRIMARY KEY, sitio_id INTEGER NOT NULL REFERENCES sitios(id) ON DELETE CASCADE,
        categoria TEXT NOT NULL, archivo TEXT NOT NULL, fecha TEXT DEFAULT (datetime('now','localtime')), comentario TEXT)''')
    c.execute('CREATE INDEX IF NOT EXISTS ix_sitio_fotos ON sitio_fotos(sitio_id)')
    for a, b in RENOMBRAR.items(): c.execute('UPDATE sitio_fotos SET categoria=? WHERE categoria=?', (b, a))

def cats_permitidas(s):
    # Las fotos SIEMPRE se pueden subir en cualquier categoría, sin importar tipo de site ni energía
    return list(CATEGORIAS)

def guardar_imagen(fs, carpeta):
    img = Image.open(fs.stream); img = ImageOps.exif_transpose(img).convert('RGB')
    nombre = uuid.uuid4().hex + '.jpg'
    g = img.copy(); g.thumbnail((1600, 1600)); g.save(os.path.join(carpeta, nombre), 'JPEG', quality=82, optimize=True)
    t = img.copy(); t.thumbnail((320, 320)); t.save(os.path.join(carpeta, 't_' + nombre), 'JPEG', quality=75)
    return nombre

def borrar_archivos(UP, archivo):
    for n in (archivo, 't_' + archivo):
        try: os.remove(os.path.join(UP, SUB, n))
        except OSError: pass

def registrar(app, q, db, UP):
    global UP_DIR; UP_DIR = UP
    carpeta = os.path.join(UP, SUB); os.makedirs(carpeta, exist_ok=True)

    def ctx(sid):
        s = q('SELECT * FROM sitios WHERE id=?', (sid,), one=True) or abort(404)
        fotos = q('SELECT * FROM sitio_fotos WHERE sitio_id=? ORDER BY fecha, id', (sid,))
        return dict(sitio=s, fotos={c: [f for f in fotos if f['categoria'] == c] for c in CATEGORIAS},
                    permitidas=cats_permitidas(s), CATEGORIAS=CATEGORIAS, GENERALES=GENERALES, SUB=SUB, CAT_CFE=CAT_CFE, CAT_ENERGIA=CAT_ENERGIA, CAT_POR_ENERGIA={v: k for k, v in CAT_ENERGIA.items()})
    app.jinja_env.globals['sitio_fotos_ctx'] = ctx
    app.jinja_env.globals['FOTO_CATS'] = CATEGORIAS

    @app.route('/sites/<int:sid>/fotos')
    def sitio_fotos(sid):
        return render_template('sitio_fotos.html', msg=request.args.get('msg'), **ctx(sid))

    @app.route('/sites/<int:sid>/fotos/subir', methods=['POST'])
    def sitio_fotos_subir(sid):
        s = q('SELECT * FROM sitios WHERE id=?', (sid,), one=True) or abort(404)
        cat = request.form.get('categoria'); volver = request.form.get('volver') or f'/sites/{sid}/fotos'
        if not volver.startswith('/') or volver.startswith('//'): volver = f'/sites/{sid}/fotos'
        if cat not in CATEGORIAS: return redirect(volver + ('&' if '?' in volver else '?') + 'msg=Categoría de foto desconocida')
        ups_id = request.form.get('ups_id')
        if ups_id:
            if cat != CAT_UPS or not ups_id.isdigit() or not q('SELECT 1 FROM sitio_ups WHERE id=? AND sitio_id=?', (int(ups_id), sid), one=True): abort(400)
            ups_id = int(ups_id)
        else: ups_id = None
        com = (request.form.get('comentario') or '').strip() or None; n = err = 0
        for fs in request.files.getlist('fotos'):
            if not fs or not fs.filename: continue
            try: arch = guardar_imagen(fs, carpeta)
            except Exception: err += 1; continue
            db().execute('INSERT INTO sitio_fotos(sitio_id,categoria,archivo,comentario,ups_id) VALUES(?,?,?,?,?)', (sid, cat, arch, com, ups_id)); n += 1
        db().commit()
        m = f'{n} foto(s) agregada(s)' + (f', {err} archivo(s) no son imagen' if err else '')
        return redirect(volver + ('&' if '?' in volver else '?') + 'msg=' + m + '#fotos')

    @app.route('/sites/fotos/<int:fid>/borrar', methods=['POST'])
    def sitio_foto_borrar(fid):
        f = q('SELECT * FROM sitio_fotos WHERE id=?', (fid,), one=True) or abort(404)
        db().execute('DELETE FROM sitio_fotos WHERE id=?', (fid,)); db().commit(); borrar_archivos(UP, f['archivo'])
        volver = request.form.get('volver') or f"/sites/{f['sitio_id']}/fotos"
        if not volver.startswith('/') or volver.startswith('//'): volver = f"/sites/{f['sitio_id']}/fotos"
        return redirect(volver + ('&' if '?' in volver else '?') + 'msg=Foto eliminada#fotos')


def adjuntos_nuevo(db, sid, tenencia):
    """Procesa fotos/documentos enviados junto con el formulario de ALTA del site. Devuelve resumen."""
    import sitio_docs as SD
    carpeta = os.path.join(UP_DIR, SUB); n = 0; malos = []
    for i, cat in enumerate(CATEGORIAS):
        com = (request.form.get(f'nfc_{i}') or '').strip() or None
        for fs in request.files.getlist(f'nf_{i}'):
            if not fs or not fs.filename: continue
            try: arch = guardar_imagen(fs, carpeta)
            except Exception: malos.append(fs.filename); continue
            db().execute('INSERT INTO sitio_fotos(sitio_id,categoria,archivo,comentario) VALUES(?,?,?,?)', (sid, cat, arch, com)); n += 1
    nd = 0
    for slug, cat in (('arr', 'Contrato arrendamiento'), ('int', 'Acuerdo intercambio')):
        if SD.CATS[cat] != tenencia: continue
        com = (request.form.get(f'ndc_{slug}') or '').strip() or None
        for fs in request.files.getlist(f'nd_{slug}'):
            if not fs or not fs.filename: continue
            e = SD.guardar_doc(db, sid, cat, fs, com)
            if e: malos.append(e)
            else: nd += 1
    return (f'{n} foto(s)' + (f', {nd} documento(s)' if nd else '') + (('; rechazados: ' + ', '.join(malos)) if malos else '')) if (n or nd or malos) else ''
