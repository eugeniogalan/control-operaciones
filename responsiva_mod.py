"""Cartas responsivas de vehículo: una por cada asignación (a persona o a cuadrilla).
Firma en pantalla (cada integrante si es cuadrilla), por el propio asignado o capturada en persona por quien tenga
«responsivas.firmar_presencial». Al completarse las firmas se genera el PDF en uploads/responsivas."""
import os, io, json, uuid, base64, datetime as dt
from flask import request, redirect, abort, render_template, g, send_file
import perm_mod as PERM

SUB = 'responsivas'
UP_DIR = None
EMPRESA = 'Spectro Networks'
ESTADOS = {'pendiente': ('Pendiente de firma', 'background:#fdf6e3;color:#a16207;border:1px solid #ecd59a'),
           'firmada': ('Firmada', 'background:#e7f6ec;color:#15803d;border:1px solid #b9e3c6'),
           'sustituida': ('Sustituida', 'background:#f2f2f5;color:#8e8e93;border:1px solid #e5e5ea')}

def clausulas(cuadrilla=False):
    yo = 'Los integrantes de la cuadrilla recibimos' if cuadrilla else 'Recibo'
    nos = 'nos comprometemos' if cuadrilla else 'me comprometo'
    return [
        ('Custodia', f'{yo} en custodia el vehículo descrito, con la documentación, llaves y accesorios con que se entrega, y {nos} a conservarlo limpio y en buen estado de funcionamiento.'),
        ('Uso adecuado', f'El vehículo se usará exclusivamente para actividades de trabajo de {EMPRESA}, por personal con licencia de conducir vigente, respetando el reglamento de tránsito y sin permitir su uso a terceros no autorizados.'),
        ('Revisión diaria', 'Se realizará el checklist diario de inicio de jornada (kilometraje, combustible, llantas, aceite, luces y frenos) y se reportará cualquier anomalía.'),
        ('Daños y accidentes', 'Cualquier daño, falla, robo, siniestro o accidente se reportará de inmediato al jefe inmediato y a Administración, siguiendo el procedimiento de la aseguradora.'),
        ('Devolución', f'El vehículo, sus llaves, tarjeta de circulación, póliza y accesorios se devolverán cuando {EMPRESA} lo solicite, al terminar esta asignación o al concluir la relación laboral.'),
        ('Responsabilidad', 'Los daños por uso indebido, negligencia o conducción bajo los efectos del alcohol o drogas, así como las multas e infracciones generadas durante el resguardo, serán responsabilidad de quien firma, conforme a la ley y a la normativa interna de la empresa.'),
    ]

def migrar(c):
    c.execute('''CREATE TABLE IF NOT EXISTS vehiculo_responsivas(id INTEGER PRIMARY KEY, vehiculo_id INTEGER NOT NULL REFERENCES vehiculos(id) ON DELETE CASCADE,
        asignacion_id INTEGER REFERENCES vehiculo_asignaciones(id) ON DELETE CASCADE, tipo TEXT, cuadrilla_id INTEGER, personal_id INTEGER, asignado TEXT,
        fecha_asignacion TEXT, km INTEGER, datos TEXT, estado TEXT DEFAULT 'pendiente', creada TEXT DEFAULT (datetime('now','localtime')), creada_por TEXT, firmada TEXT, pdf TEXT)''')
    c.execute('CREATE INDEX IF NOT EXISTS ix_resp_veh ON vehiculo_responsivas(vehiculo_id)')
    c.execute('''CREATE TABLE IF NOT EXISTS responsiva_firmas(id INTEGER PRIMARY KEY, responsiva_id INTEGER NOT NULL REFERENCES vehiculo_responsivas(id) ON DELETE CASCADE,
        personal_id INTEGER, nombre TEXT, puesto TEXT, rol TEXT, firma TEXT, fecha TEXT, capturada_por TEXT, en_persona INTEGER DEFAULT 0)''')
    c.execute('CREATE INDEX IF NOT EXISTS ix_resp_firmas ON responsiva_firmas(responsiva_id)')

def ahora():
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo('America/Mexico_City')).strftime('%Y-%m-%d %H:%M')
    except Exception:
        return dt.datetime.now(dt.timezone(dt.timedelta(hours=-6))).strftime('%Y-%m-%d %H:%M')

def crear(con, vid, aid):
    """Crea la responsiva de la asignación aid (las pendientes anteriores del vehículo quedan «sustituidas»). Sin asignar -> no hay carta."""
    a = con.execute('SELECT tipo, cuadrilla_id, personal_id, asignado, fecha, cambiado_por FROM vehiculo_asignaciones WHERE id=?', (aid,)).fetchone()
    con.execute("UPDATE vehiculo_responsivas SET estado='sustituida' WHERE vehiculo_id=? AND estado='pendiente'", (vid,))
    if not a or a[0] not in ('Persona', 'Cuadrilla'): return None
    v = con.execute('SELECT numero, marca, modelo, anio, placas, numero_serie, seguro_compania, seguro_poliza, seguro_vence, asignacion_km FROM vehiculos WHERE id=?', (vid,)).fetchone()
    datos = dict(zip(['numero', 'marca', 'modelo', 'anio', 'placas', 'numero_serie', 'seguro_compania', 'seguro_poliza', 'seguro_vence', 'km'], v))
    if a[0] == 'Persona': fir = con.execute('SELECT id, nombre, puesto, NULL FROM tecnicos WHERE id=?', (a[2],)).fetchall()
    else: fir = con.execute("SELECT id, nombre, puesto, rol FROM tecnicos WHERE cuadrilla_id=? AND COALESCE(activo,1)=1 ORDER BY rol='líder' DESC, nombre", (a[1],)).fetchall()
    rid = con.execute('INSERT INTO vehiculo_responsivas(vehiculo_id,asignacion_id,tipo,cuadrilla_id,personal_id,asignado,fecha_asignacion,km,datos,creada,creada_por) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                      (vid, aid, a[0], a[1], a[2], a[3], a[4], datos['km'], json.dumps(datos, ensure_ascii=False), ahora(), a[5])).lastrowid
    con.executemany('INSERT INTO responsiva_firmas(responsiva_id,personal_id,nombre,puesto,rol) VALUES(?,?,?,?,?)', [(rid,) + tuple(f) for f in fir])
    return rid

def demo(c, up, static_dir):
    """Solo datos de EJEMPLO (BD con órdenes ejemplo=1 y sin historial de asignaciones): asignación vigente desde hace 30 días,
    el Vehículo 18 asignado a una persona y cartas responsivas ya firmadas (firmas ficticias) salvo las de los vehículos 01 y 18,
    que quedan pendientes para mostrar el flujo de firma."""
    if not up or not c.execute('SELECT 1 FROM ordenes WHERE ejemplo=1 LIMIT 1').fetchone() or c.execute('SELECT 1 FROM vehiculo_asignaciones LIMIT 1').fetchone(): return
    import sqlite3
    from PIL import Image, ImageDraw
    import vehiculo_adj as VA
    rf = c.row_factory; c.row_factory = sqlite3.Row
    try:
        f30 = (dt.date.today() - dt.timedelta(days=30)).isoformat()
        c.execute("UPDATE vehiculos SET asignacion_tipo='Cuadrilla' WHERE cuadrilla_id IS NOT NULL AND COALESCE(asignacion_tipo,'Sin asignar')<>'Persona'")
        v18 = c.execute("SELECT id, cuadrilla_id FROM vehiculos WHERE numero='18'").fetchone()
        if v18:
            p = c.execute("SELECT id FROM tecnicos WHERE ejemplo=1 AND cuadrilla_id=? AND rol<>'líder' ORDER BY id LIMIT 1", (v18['cuadrilla_id'],)).fetchone()
            if p: c.execute("UPDATE vehiculos SET asignacion_tipo='Persona', personal_id=?, cuadrilla_id=NULL WHERE id=?", (p['id'], v18['id']))
        carpeta = os.path.join(up, SUB); os.makedirs(carpeta, exist_ok=True)
        rnd = __import__('random').Random(11)
        for v in c.execute("SELECT id, numero, asignacion_tipo, cuadrilla_id, personal_id FROM vehiculos WHERE asignacion_tipo IN ('Cuadrilla','Persona') ORDER BY numero").fetchall():
            km = rnd.randint(15000, 90000)
            uk = VA.ultimo_km(v['id'], c)
            if uk: km = max(uk - rnd.randint(1500, 3000), 0)   # coherente con los checklists de ejemplo
            c.execute('UPDATE vehiculos SET asignacion_fecha=?, asignacion_km=COALESCE(asignacion_km,?) WHERE id=?', (f30, km, v['id']))
            d = {'asignacion_tipo': v['asignacion_tipo'], 'cuadrilla_id': v['cuadrilla_id'], 'personal_id': v['personal_id'], 'asignacion_fecha': f30}
            VA.historial(c, v['id'], d)
            if v['numero'] in ('01', '18'): continue
            rid = c.execute("SELECT id FROM vehiculo_responsivas WHERE vehiculo_id=? AND estado='pendiente'", (v['id'],)).fetchone()
            if not rid: continue
            rid = rid[0]; cuando = f'{f30} 09:{rnd.randint(10, 59):02d}'
            for f in c.execute('SELECT id, nombre FROM responsiva_firmas WHERE responsiva_id=?', (rid,)).fetchall():
                im = Image.new('RGBA', (600, 200), (255, 255, 255, 0)); dr = ImageDraw.Draw(im)
                x, y = 40, 110
                for _ in range(14):   # trazo ficticio
                    nx, ny = x + rnd.randint(18, 40), 60 + rnd.randint(0, 90); dr.line([(x, y), (nx, ny)], fill=(11, 31, 77, 255), width=4); x, y = nx, ny
                n = f'ejemplo_firma_{f["id"]}.png'; im.save(os.path.join(carpeta, n))
                c.execute('UPDATE responsiva_firmas SET firma=?, fecha=?, en_persona=0 WHERE id=?', (n, cuando, f['id']))
            c.execute("UPDATE vehiculo_responsivas SET estado='firmada', firmada=? WHERE id=?", (cuando, rid))
            try: c.execute('UPDATE vehiculo_responsivas SET pdf=? WHERE id=?', (generar_pdf(c, rid, up, static_dir), rid))
            except Exception: pass   # sin reportlab: queda firmada sin PDF
    finally:
        c.row_factory = rf

# ---------- acceso ----------
def _u(): return getattr(g, 'user', None)

def en_alcance(q, r):
    """¿La responsiva está dentro del alcance del perfil? (todas / su equipo / solo propias)."""
    if PERM.es_su() or PERM.alcance()[0] in ('todas', 'tipo'): return True
    u = _u()
    if not u: return False
    if q('SELECT 1 FROM responsiva_firmas WHERE responsiva_id=? AND personal_id=?', (r['id'], u['id']), one=True): return True
    if PERM.alcance()[0] != 'equipo': return False
    cuads = [x['id'] for x in q('SELECT id FROM cuadrillas WHERE id=? OR supervisor_id=?', (u['cuadrilla_id'], u['id']))]
    if r['cuadrilla_id'] in cuads: return True
    return bool(q(f"SELECT 1 FROM responsiva_firmas f JOIN tecnicos t ON t.id=f.personal_id WHERE f.responsiva_id=? AND t.cuadrilla_id IN ({','.join('?'*len(cuads)) or 'NULL'})", [r['id']] + cuads, one=True))

def es_firmante(q, r):
    u = _u()
    return bool(u and q('SELECT 1 FROM responsiva_firmas WHERE responsiva_id=? AND personal_id=?', (r['id'], u['id']), one=True))

def puede_ver(q, r):
    return es_firmante(q, r) or (PERM.can('responsivas.ver', 'config.vehiculos', 'responsivas.firmar_presencial') and en_alcance(q, r))

def puede_firmar(q, r, f):
    """El propio firmante, o quien captura en persona (permiso) dentro de su alcance."""
    if r['estado'] != 'pendiente' or f['firma']: return False
    u = _u()
    if u and f['personal_id'] == u['id']: return True
    return PERM.can('responsivas.firmar_presencial') and en_alcance(q, r)

# ---------- firma ----------
def guardar_firma(data, carpeta):
    """dataURL PNG del canvas -> archivo PNG. Rechaza firmas vacías o archivos que no son imagen."""
    from PIL import Image
    if not data or not data.startswith('data:image/png;base64,'): return None, 'Firma vacía'
    try:
        raw = base64.b64decode(data.split(',', 1)[1], validate=True)
        if len(raw) > 1_500_000: return None, 'Firma demasiado grande'
        im = Image.open(io.BytesIO(raw)); im.load(); im = im.convert('RGBA')
    except Exception:
        return None, 'Firma inválida'
    bb = im.getchannel('A').getbbox()
    if not bb or (bb[2] - bb[0]) < 15 or (bb[3] - bb[1]) < 8: return None, 'Dibuja tu firma en el recuadro'
    pad = 8; im = im.crop((max(0, bb[0] - pad), max(0, bb[1] - pad), min(im.width, bb[2] + pad), min(im.height, bb[3] + pad)))
    nombre = 'firma_' + uuid.uuid4().hex + '.png'; im.save(os.path.join(carpeta, nombre), 'PNG', optimize=True)
    return nombre, None

# ---------- PDF ----------
def generar_pdf(con, rid, up, static_dir):
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage, KeepTogether
    r = con.execute('SELECT * FROM vehiculo_responsivas WHERE id=?', (rid,)).fetchone()
    fs = con.execute('SELECT * FROM responsiva_firmas WHERE responsiva_id=? ORDER BY id', (rid,)).fetchall()
    d = json.loads(r['datos'] or '{}'); cuad = r['tipo'] == 'Cuadrilla'
    carpeta = os.path.join(up, SUB); nombre = f'responsiva_{rid}_{uuid.uuid4().hex[:10]}.pdf'
    st = getSampleStyleSheet(); n = ParagraphStyle('n', parent=st['Normal'], fontName='Helvetica', fontSize=9.5, leading=13)
    b = ParagraphStyle('b', parent=n, fontName='Helvetica-Bold'); h = ParagraphStyle('h', parent=n, fontName='Helvetica-Bold', fontSize=14, leading=18, alignment=1)
    sm = ParagraphStyle('sm', parent=n, fontSize=8, leading=10, textColor=colors.HexColor('#555555'))
    doc = SimpleDocTemplate(os.path.join(carpeta, nombre), pagesize=letter, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.4 * cm, bottomMargin=1.6 * cm,
                            title=f'Carta responsiva · Vehículo {d.get("numero")}', author=EMPRESA)
    E = []
    logo = os.path.join(static_dir, 'logo-spectro.png')
    cab = [RLImage(logo, width=4.2 * cm, height=4.2 * cm * 0.32, kind='proportional') if os.path.exists(logo) else Paragraph(f'<b>{EMPRESA}</b>', b),
           Paragraph(f'<b>{EMPRESA}</b><br/>Control de Operaciones · Flotilla', ParagraphStyle('r', parent=sm, alignment=2))]
    t = Table([cab], colWidths=[9 * cm, 8.6 * cm]); t.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('LINEBELOW', (0, 0), (-1, 0), 1.2, colors.HexColor('#111111')), ('BOTTOMPADDING', (0, 0), (-1, -1), 8)]))
    E += [t, Spacer(1, 10), Paragraph('CARTA RESPONSIVA DE VEHÍCULO', h), Spacer(1, 4),
          Paragraph(f'Folio RV-{rid:05d} · Fecha de asignación: {r["fecha_asignacion"] or "—"} · Fecha de firma: {(r["firmada"] or "—")}', ParagraphStyle('c', parent=sm, alignment=1)), Spacer(1, 10)]
    def fila(k, v): return [Paragraph(k, b), Paragraph(str(v) if v not in (None, '') else '—', n)]
    veh = [fila('Vehículo', f'Vehículo {d.get("numero")}'), fila('Marca / modelo / año', ' '.join(str(x) for x in (d.get('marca'), d.get('modelo'), d.get('anio')) if x) or None),
           fila('Placas', d.get('placas')), fila('Número de serie (VIN)', d.get('numero_serie')),
           fila('Kilometraje al asignar', f'{d["km"]:,} km' if d.get('km') is not None else 'No registrado'),
           fila('Póliza de seguro', ' · '.join(x for x in (d.get('seguro_compania'), ('Póliza ' + d['seguro_poliza']) if d.get('seguro_poliza') else None, ('vence ' + d['seguro_vence']) if d.get('seguro_vence') else None) if x) or None),
           fila('Asignado a', (f'Cuadrilla: {r["asignado"]}' if cuad else r['asignado']))]
    t = Table(veh, colWidths=[5 * cm, 12.6 * cm]); t.setStyle(TableStyle([('GRID', (0, 0), (-1, -1), .4, colors.HexColor('#cccccc')), ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f2f2f5')), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')]))
    E += [t, Spacer(1, 10)]
    quienes = ', '.join(f'{f["nombre"]} ({f["puesto"] or "—"})' for f in fs)
    E.append(Paragraph(('Los suscritos, integrantes de la cuadrilla ' + (r['asignado'] or '') + f': {quienes}, ' if cuad else f'El suscrito, {quienes}, ') +
                       f'declaro{"amos" if cuad else ""} bajo protesta de decir verdad que recib{"imos" if cuad else "o"} de {EMPRESA} el vehículo descrito y acept{"amos" if cuad else "o"} las siguientes condiciones:', n))
    E.append(Spacer(1, 6))
    for i, (tit, txt) in enumerate(clausulas(cuad), 1): E += [Paragraph(f'<b>{i}. {tit}.</b> {txt}', n), Spacer(1, 3)]
    E.append(Spacer(1, 12))
    celdas = []
    for f in fs:
        img = RLImage(os.path.join(carpeta, f['firma']), width=5.5 * cm, height=2.0 * cm, kind='proportional') if f['firma'] and os.path.exists(os.path.join(carpeta, f['firma'])) else Paragraph('(sin firma)', sm)
        pie = f'<b>{f["nombre"]}</b><br/>{f["puesto"] or ""}{(" · " + f["rol"]) if f["rol"] else ""}<br/>Firmó: {f["fecha"] or "—"}' + (f'<br/>Firma capturada en persona por {f["capturada_por"]}' if f['en_persona'] else '')
        celdas.append([img, Paragraph(pie, ParagraphStyle('f', parent=sm, alignment=1))])
    filas = []
    for i in range(0, len(celdas), 2):
        par = celdas[i:i + 2] + ([['', '']] if len(celdas[i:i + 2]) == 1 else [])
        filas += [[par[0][0], par[1][0]], [par[0][1], par[1][1]]]
    if filas:
        t = Table(filas, colWidths=[8.8 * cm, 8.8 * cm])
        sty = [('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('VALIGN', (0, 0), (-1, -1), 'BOTTOM')]
        for i in range(0, len(filas), 2):
            for j in range(2):
                if filas[i + 1][j] != '': sty.append(('LINEABOVE', (j, i + 1), (j, i + 1), .8, colors.HexColor('#111111')))
        t.setStyle(TableStyle(sty)); E.append(KeepTogether([Paragraph('<b>Firma(s) de conformidad</b>', n), Spacer(1, 6), t]))
    E += [Spacer(1, 14), Paragraph(f'Entrega por {EMPRESA}: {r["creada_por"] or "Administración"} · Documento generado electrónicamente el {ahora()} · Folio RV-{rid:05d}', sm)]
    doc.build(E)
    return nombre

def registrar(app, q, db, UP):
    global UP_DIR; UP_DIR = UP
    carpeta = os.path.join(UP, SUB); os.makedirs(carpeta, exist_ok=True)
    app.jinja_env.globals.update(RESP_ESTADOS=ESTADOS)

    def pendientes_mias():
        u = _u()
        if not u: return []
        return q("""SELECT r.id, v.numero FROM responsiva_firmas f JOIN vehiculo_responsivas r ON r.id=f.responsiva_id JOIN vehiculos v ON v.id=r.vehiculo_id
                    WHERE f.personal_id=? AND f.firma IS NULL AND r.estado='pendiente' ORDER BY r.id""", (u['id'],))
    @app.context_processor
    def _resp_ctx():
        try: return dict(RESP_PEND=pendientes_mias())
        except Exception: return dict(RESP_PEND=[])
    app.jinja_env.globals['responsivas_de'] = lambda vid: q('''SELECT r.*, (SELECT COUNT(*) FROM responsiva_firmas f WHERE f.responsiva_id=r.id) nf,
        (SELECT COUNT(*) FROM responsiva_firmas f WHERE f.responsiva_id=r.id AND f.firma IS NOT NULL) nfir FROM vehiculo_responsivas r WHERE r.vehiculo_id=? ORDER BY r.id DESC''', (vid,))
    app.jinja_env.globals['asignaciones_de'] = lambda vid: q('''SELECT a.*, r.id rid, r.estado restado, r.firmada FROM vehiculo_asignaciones a LEFT JOIN vehiculo_responsivas r ON r.asignacion_id=a.id
        WHERE a.vehiculo_id=? ORDER BY a.id DESC LIMIT 30''', (vid,))

    def cargar(rid):
        r = q('SELECT r.*, v.numero vnum FROM vehiculo_responsivas r JOIN vehiculos v ON v.id=r.vehiculo_id WHERE r.id=?', (rid,), one=True) or abort(404)
        if not puede_ver(q, r): abort(403)
        return r

    @app.route('/responsivas/<int:rid>')
    def responsiva(rid):
        r = cargar(rid)
        fs = q('SELECT * FROM responsiva_firmas WHERE responsiva_id=? ORDER BY id', (rid,))
        return render_template('responsiva.html', r=r, d=json.loads(r['datos'] or '{}'), fs=fs, firmables={f['id'] for f in fs if puede_firmar(q, r, f)},
                               yo=(_u()['id'] if _u() else None), clausulas=clausulas(r['tipo'] == 'Cuadrilla'), msg=request.args.get('msg'), EMPRESA=EMPRESA)

    @app.route('/responsivas/<int:rid>/firmar', methods=['POST'])
    def responsiva_firmar(rid):
        r = cargar(rid)
        f = q('SELECT * FROM responsiva_firmas WHERE id=? AND responsiva_id=?', (request.form.get('firma_id', type=int), rid), one=True) or abort(404)
        if not puede_firmar(q, r, f): abort(403)
        u = _u(); propio = bool(u and f['personal_id'] == u['id'])
        if not propio and not request.form.get('confirmo'):
            return redirect(f'/responsivas/{rid}?msg=Confirma que {f["nombre"]} firma en persona en este dispositivo#f{f["id"]}')
        arch, err = guardar_firma(request.form.get('firma'), carpeta)
        if err: return redirect(f'/responsivas/{rid}?msg={err}#f{f["id"]}')
        import auth_mod as AU
        con = db(); con.execute('UPDATE responsiva_firmas SET firma=?, fecha=?, capturada_por=?, en_persona=? WHERE id=?', (arch, ahora(), None if propio else AU.nombre_actual(), 0 if propio else 1, f['id']))
        if not con.execute('SELECT 1 FROM responsiva_firmas WHERE responsiva_id=? AND firma IS NULL', (rid,)).fetchone():
            con.execute("UPDATE vehiculo_responsivas SET estado='firmada', firmada=? WHERE id=?", (ahora(), rid)); con.commit()
            pdf = generar_pdf(con, rid, UP, app.static_folder)
            con.execute('UPDATE vehiculo_responsivas SET pdf=? WHERE id=?', (pdf, rid)); con.commit()
            return redirect(f'/responsivas/{rid}?msg=Responsiva firmada; PDF generado')
        con.commit()
        return redirect(f'/responsivas/{rid}?msg=Firma de {f["nombre"]} guardada')

    @app.route('/responsivas/<int:rid>/firma/<int:fid>')
    def responsiva_firma_img(rid, fid):
        cargar(rid)
        f = q('SELECT firma FROM responsiva_firmas WHERE id=? AND responsiva_id=?', (fid, rid), one=True)
        if not f or not f['firma'] or not os.path.exists(os.path.join(carpeta, f['firma'])): abort(404)
        return send_file(os.path.join(carpeta, f['firma']), mimetype='image/png')

    @app.route('/responsivas/<int:rid>/pdf')
    def responsiva_pdf(rid):
        r = cargar(rid)
        if not r['pdf'] or not os.path.exists(os.path.join(carpeta, r['pdf'])): abort(404)
        return send_file(os.path.join(carpeta, r['pdf']), mimetype='application/pdf', download_name=f'responsiva_vehiculo_{r["vnum"]}_RV-{rid:05d}.pdf')

    @app.route('/responsivas/generar/<int:vid>', methods=['POST'])
    def responsiva_generar(vid):
        """Para asignaciones anteriores a esta función (o si cambiaron los integrantes): nueva responsiva de la asignación actual."""
        import vehiculo_adj as VA
        v = q('SELECT * FROM vehiculos WHERE id=?', (vid,), one=True) or abort(404)
        if (v['asignacion_tipo'] or 'Sin asignar') == 'Sin asignar': return redirect(f'/configuracion/vehiculos/{vid}/editar?msg=El vehículo no está asignado#asignacion')
        d = {'asignacion_tipo': v['asignacion_tipo'], 'cuadrilla_id': v['cuadrilla_id'], 'personal_id': v['personal_id'], 'asignacion_fecha': v['asignacion_fecha'] or VA.hoy_mx()}
        VA.historial(db(), vid, d); db().commit()
        return redirect(f'/configuracion/vehiculos/{vid}/editar?msg=Responsiva generada; pendiente de firma#asignacion')

    @app.route('/responsivas')
    def responsivas():
        mias = pendientes_mias()
        todas = []
        if PERM.can('responsivas.ver', 'config.vehiculos', 'responsivas.firmar_presencial'):
            est = request.args.get('estado', 'pendiente')
            todas = [r for r in q("""SELECT r.*, v.numero vnum, (SELECT COUNT(*) FROM responsiva_firmas f WHERE f.responsiva_id=r.id) nf,
                (SELECT COUNT(*) FROM responsiva_firmas f WHERE f.responsiva_id=r.id AND f.firma IS NOT NULL) nfir FROM vehiculo_responsivas r JOIN vehiculos v ON v.id=r.vehiculo_id
                WHERE (?='' OR r.estado=?) ORDER BY r.id DESC LIMIT 300""", (est if est in ESTADOS else '', est if est in ESTADOS else '')) if en_alcance(q, r)]
        return render_template('responsivas.html', mias=mias, todas=todas, estado=request.args.get('estado', 'pendiente'))
