"""Menú Configuración: altas, bajas y cambios de catálogos (Materiales, Personal, Vehículos, Cuadrillas, Sites, Almacenes, Herramientas y Equipo)."""
from flask import render_template, request, redirect, url_for, abort

SCHEMA_CFG = '''
CREATE TABLE IF NOT EXISTS sitios(id INTEGER PRIMARY KEY, codigo TEXT UNIQUE, nombre TEXT NOT NULL, cliente TEXT, direccion TEXT, ciudad TEXT, estado TEXT,
 lat REAL, lng REAL, tipo TEXT, contacto TEXT, notas TEXT, activo INTEGER DEFAULT 1, ejemplo INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS vehiculos(id INTEGER PRIMARY KEY, numero TEXT UNIQUE NOT NULL, placas TEXT, marca TEXT, modelo TEXT, anio INTEGER,
 cuadrilla_id INTEGER REFERENCES cuadrillas(id) ON DELETE SET NULL, almacen_id INTEGER REFERENCES almacenes(id) ON DELETE SET NULL, activo INTEGER DEFAULT 1, notas TEXT);
CREATE TABLE IF NOT EXISTS herramientas(id INTEGER PRIMARY KEY, codigo TEXT, numero_serie TEXT, nombre TEXT NOT NULL, tipo TEXT, marca TEXT, modelo TEXT,
 estado TEXT DEFAULT 'disponible', cuadrilla_id INTEGER REFERENCES cuadrillas(id) ON DELETE SET NULL, personal_id INTEGER REFERENCES tecnicos(id) ON DELETE SET NULL,
 almacen_id INTEGER REFERENCES almacenes(id) ON DELETE SET NULL, fecha_calibracion TEXT, notas TEXT, activo INTEGER DEFAULT 1, ejemplo INTEGER DEFAULT 0);
'''
TIPOS_SITIO = ['Torre','Nodo','Cliente','Repetidor','Oficina','Data center','Otro']
TIPOS_HERR = ['Herramienta','Equipo de medición','EPP','Equipo de fusión','Escalera / altura','Vehículo / remolque','Otro']
ESTADOS_HERR = ['disponible','asignado','en reparación','baja']
PUESTOS = ['Director','Gerente','Supervisor','Técnico Instalador','Vendedor','Almacenista','Proveedor Externo']
ESPEC = ['Fibra Óptica','Microondas','Redes / Wi-Fi','Satelital','Instalaciones a cliente','Mixta']

def migrar(c, N_VEH=18):
    c.executescript(SCHEMA_CFG)
    tc = [r[1] for r in c.execute('PRAGMA table_info(tecnicos)')]
    for col, typ in (('email','TEXT'), ('activo','INTEGER DEFAULT 1')):
        if col not in tc: c.execute(f'ALTER TABLE tecnicos ADD COLUMN {col} {typ}')
    if 'site_id' not in [r[1] for r in c.execute('PRAGMA table_info(ordenes)')]:
        c.execute('ALTER TABLE ordenes ADD COLUMN site_id INTEGER REFERENCES sitios(id) ON DELETE SET NULL')
    # vehículos: uno por cada almacén "Vehículo NN" existente
    if not c.execute('SELECT 1 FROM vehiculos LIMIT 1').fetchone():
        for aid, nom, cid, act in c.execute("SELECT id,nombre,cuadrilla_id,activo FROM almacenes WHERE tipo='vehiculo' ORDER BY nombre").fetchall():
            num = nom.replace('Vehículo','').strip() or str(aid)
            c.execute('INSERT OR IGNORE INTO vehiculos(numero,cuadrilla_id,almacen_id,activo) VALUES(?,?,?,?)', (num, cid, aid, act))
    if not c.execute('SELECT 1 FROM sitios LIMIT 1').fetchone():
        for s in [('TR-001','Torre Cerro del Cuatro','Torrelit','Cerro del Cuatro s/n','Tlaquepaque','Jalisco',20.5952,-103.3640,'Torre','Ing. Ramírez 33 1111 2222'),
                  ('ND-010','Nodo Centro','Torrelit','Av. Juárez 120','Guadalajara','Jalisco',20.6748,-103.3470,'Nodo','NOC 33 3000 0000'),
                  ('ND-011','Nodo Zapopan Norte','Torrelit','Av. Patria 2000','Zapopan','Jalisco',20.7270,-103.4060,'Nodo',''),
                  ('RP-003','Repetidor Tapalpa','Torrelit','Cerro La Cruz','Tapalpa','Jalisco',19.9440,-103.7590,'Repetidor',''),
                  ('CL-101','Plaza Andares (cliente)','Grupo DMI','Blvd. Puerta de Hierro 4965','Zapopan','Jalisco',20.7106,-103.4110,'Cliente','Lic. Torres 33 4444 5555'),
                  ('CL-102','Hospital San Javier (cliente)','Hospital San Javier','Av. Pablo Casals 640','Guadalajara','Jalisco',20.6890,-103.3950,'Cliente','')]:
            c.execute('INSERT INTO sitios(codigo,nombre,cliente,direccion,ciudad,estado,lat,lng,tipo,contacto,notas,ejemplo) VALUES(?,?,?,?,?,?,?,?,?,?,?,1)', s+('EJEMPLO',))
    if not c.execute('SELECT 1 FROM herramientas LIMIT 1').fetchone():
        alm = {n: i for i, n in c.execute('SELECT id,nombre FROM almacenes')}
        cu = [r[0] for r in c.execute('SELECT id FROM cuadrillas ORDER BY id LIMIT 3')] + [None]*3
        pe = [r[0] for r in c.execute('SELECT id FROM tecnicos ORDER BY id LIMIT 2')] + [None]*2
        for h in [('HE-001','FS-77821','Empalmadora de fusión','Equipo de fusión','Fujikura','70S+','asignado',cu[0],None,None,'2026-03-10'),
                  ('HE-002','OT-55102','OTDR','Equipo de medición','EXFO','MAX-715B','asignado',cu[1],None,None,'2026-05-02'),
                  ('HE-003','PM-1209','Medidor de potencia óptica','Equipo de medición','Grandway','FHP12','disponible',None,None,alm.get('Torrelit'),'2026-01-20'),
                  ('HE-004','CL-3301','Cortadora de precisión','Herramienta','Fujikura','CT-50','asignado',None,pe[0],None,None),
                  ('HE-005','','Escalera de extensión 32 pies','Escalera / altura','Werner','D1532-2','disponible',None,None,alm.get('Autosound'),None),
                  ('HE-006','AL-0098','Alineador de antenas','Equipo de medición','Ubiquiti','AirMax','en reparación',None,None,None,None),
                  ('EPP-001','','Arnés de cuerpo completo','EPP','3M','DBI-Sala','asignado',None,pe[1],None,None),
                  ('HE-007','','Kit de herramienta de red (ponchadora, probador)','Herramienta','Klein Tools','VDV001','asignado',cu[2],None,None,None)]:
            c.execute('INSERT INTO herramientas(codigo,numero_serie,nombre,tipo,marca,modelo,estado,cuadrilla_id,personal_id,almacen_id,fecha_calibracion,notas,ejemplo) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1)', h+('EJEMPLO',))

def registrar(app, q, db):
    def opts(sql): return lambda: [(r[0], r[1]) for r in q(sql)]
    CUAD = opts("SELECT id, nombre FROM cuadrillas WHERE activa=1 OR activa IS NULL ORDER BY id")
    PERS = opts("SELECT id, nombre FROM tecnicos WHERE COALESCE(activo,1)=1 ORDER BY nombre")
    ALM = opts("SELECT id, nombre FROM almacenes WHERE activo=1 ORDER BY tipo, nombre")
    VEH = opts("SELECT id, 'Vehículo '||numero FROM vehiculos WHERE activo=1 ORDER BY numero")
    def existe(sql, a): return bool(q(sql, a, one=True))

    # ---- hooks ----
    def veh_post(vid, d):
        con = db(); num = d['numero']; nom = f'Vehículo {num}'
        v = q('SELECT * FROM vehiculos WHERE id=?', (vid,), one=True)
        if v['almacen_id'] and q('SELECT 1 FROM almacenes WHERE id=?', (v['almacen_id'],), one=True):
            con.execute('UPDATE almacenes SET nombre=?, tipo=?, cuadrilla_id=?, activo=? WHERE id=?', (nom, 'vehiculo', d['cuadrilla_id'], d['activo'], v['almacen_id']))
        else:
            a = q('SELECT id FROM almacenes WHERE nombre=?', (nom,), one=True)
            aid = a['id'] if a else con.execute("INSERT INTO almacenes(nombre,tipo) VALUES(?,'vehiculo')", (nom,)).lastrowid
            con.execute('UPDATE almacenes SET tipo=?, cuadrilla_id=?, activo=? WHERE id=?', ('vehiculo', d['cuadrilla_id'], d['activo'], aid))
            con.execute('UPDATE vehiculos SET almacen_id=? WHERE id=?', (aid, vid))
    def veh_valid(d, rid):
        n = (d['numero'] or '').strip()
        if n.isdigit(): d['numero'] = f'{int(n):02d}'
        v = q('SELECT almacen_id FROM vehiculos WHERE id=?', (rid,), one=True) if rid else None
        a = q('SELECT id FROM almacenes WHERE nombre=?', (f"Vehículo {d['numero']}",), one=True)
        if a and (not v or v['almacen_id'] != a['id']) and q('SELECT 1 FROM vehiculos WHERE almacen_id=?', (a['id'],), one=True):
            return 'Ya existe un almacén con ese nombre ligado a otro vehículo'
    def alm_post(aid, d):
        db().execute('UPDATE vehiculos SET cuadrilla_id=?, activo=? WHERE almacen_id=?', (d['cuadrilla_id'], d['activo'], aid))
    def alm_hist(aid):
        return (existe('SELECT 1 FROM movimientos WHERE almacen_id=? LIMIT 1', (aid,)) or existe('SELECT 1 FROM existencias WHERE almacen_id=? AND stock<>0', (aid,))
                or existe('SELECT 1 FROM orden_materiales WHERE almacen_id=? LIMIT 1', (aid,)) or existe('SELECT 1 FROM herramientas WHERE almacen_id=?', (aid,)))
    def alm_del(aid):
        db().execute('DELETE FROM existencias WHERE almacen_id=?', (aid,)); db().execute('UPDATE vehiculos SET almacen_id=NULL WHERE almacen_id=?', (aid,))
    def veh_baja_soft(vid):
        db().execute('UPDATE almacenes SET activo=0 WHERE id=(SELECT almacen_id FROM vehiculos WHERE id=?)', (vid,))
    def veh_hist(vid):
        v = q('SELECT almacen_id FROM vehiculos WHERE id=?', (vid,), one=True); return bool(v and v['almacen_id'] and alm_hist(v['almacen_id']))
    def veh_del(vid):
        v = q('SELECT almacen_id FROM vehiculos WHERE id=?', (vid,), one=True)
        if v and v['almacen_id']:
            db().execute('UPDATE vehiculos SET almacen_id=NULL WHERE id=?', (vid,)); alm_del(v['almacen_id']); db().execute('DELETE FROM almacenes WHERE id=?', (v['almacen_id'],))
    def cuad_extra(rid):
        m = {r['rol']: r['id'] for r in q('SELECT id, rol FROM tecnicos WHERE cuadrilla_id=? AND rol IS NOT NULL', (rid,))} if rid else {}
        return {'lider_id': m.get('líder'), 'tecnico_id': m.get('técnico'), 'vehiculos': [r['id'] for r in q('SELECT id FROM vehiculos WHERE cuadrilla_id=?', (rid,))] if rid else []}
    def cuad_post(cid, d):
        con = db(); F = request.form
        for rol, k in (('líder','lider_id'), ('técnico','tecnico_id')):
            pid = F.get(k)
            con.execute('UPDATE tecnicos SET rol=NULL WHERE cuadrilla_id=? AND rol=? AND id IS NOT ?', (cid, rol, int(pid) if pid else None))
            if pid: con.execute('UPDATE tecnicos SET cuadrilla_id=?, rol=? WHERE id=?', (cid, rol, int(pid)))
        sel = [int(x) for x in F.getlist('vehiculos')]
        con.execute(f"UPDATE vehiculos SET cuadrilla_id=NULL WHERE cuadrilla_id=? AND id NOT IN ({','.join('?'*len(sel)) or 'NULL'})", [cid]+sel)
        for v in sel: con.execute('UPDATE vehiculos SET cuadrilla_id=? WHERE id=?', (cid, v))
        con.execute('UPDATE almacenes SET cuadrilla_id=(SELECT cuadrilla_id FROM vehiculos v WHERE v.almacen_id=almacenes.id) WHERE id IN (SELECT almacen_id FROM vehiculos WHERE almacen_id IS NOT NULL)')
    def cuad_del(cid):
        con = db(); con.execute('UPDATE tecnicos SET cuadrilla_id=NULL, rol=NULL WHERE cuadrilla_id=?', (cid,))
        con.execute('UPDATE vehiculos SET cuadrilla_id=NULL WHERE cuadrilla_id=?', (cid,)); con.execute('UPDATE almacenes SET cuadrilla_id=NULL WHERE cuadrilla_id=?', (cid,))
        con.execute('UPDATE herramientas SET cuadrilla_id=NULL WHERE cuadrilla_id=?', (cid,))
    def pers_valid(d, rid):
        if d.get('rol') and d.get('cuadrilla_id'):
            o = q('SELECT nombre FROM tecnicos WHERE cuadrilla_id=? AND rol=? AND id IS NOT ?', (d['cuadrilla_id'], d['rol'], rid), one=True)
            if o: db().execute('UPDATE tecnicos SET rol=NULL WHERE cuadrilla_id=? AND rol=? AND id IS NOT ?', (d['cuadrilla_id'], d['rol'], rid))
        if not d.get('cuadrilla_id'): d['rol'] = None
    def herr_valid(d, rid):
        if d['estado'] == 'baja': d['activo'] = 0
        if d['estado'] == 'disponible' and (d['cuadrilla_id'] or d['personal_id']): d['estado'] = 'asignado'
    def mat_hist(mid):
        return existe('SELECT 1 FROM movimientos WHERE material_id=? LIMIT 1', (mid,)) or existe('SELECT 1 FROM orden_materiales WHERE material_id=? LIMIT 1', (mid,))

    E = {
     'materiales': dict(titulo='Materiales', icono='📦', tabla='materiales', act='activo', orden='categoria, nombre', desc='Catálogo con SKU, código de barras, número de parte Syscom, mínimos y foto.',
        buscar=['sku','nombre','codigo_barras','numero_parte','marca','categoria'],
        cols=[('sku','SKU'),('nombre','Nombre'),('categoria','Categoría'),('codigo_barras','Código de barras'),('numero_parte','No. parte'),('marca','Marca'),('unidad','Unidad'),('stock_actual','Stock')],
        alta_url='/inventario/nuevo', editar_url='/inventario/{id}/editar', ver_url='/inventario/{id}', hist=mat_hist, campos=[]),
     'personal': dict(titulo='Personal', icono='👷', tabla='tecnicos', act='activo', orden='nombre', desc='Empleados y técnicos; asignación a cuadrilla como líder o técnico.',
        buscar=['nombre','puesto','telefono','email','especialidad'],
        sql='SELECT t.*, c.nombre cuadrilla FROM tecnicos t LEFT JOIN cuadrillas c ON c.id=t.cuadrilla_id',
        cols=[('nombre','Nombre'),('puesto','Puesto'),('telefono','Teléfono'),('email','Email'),('especialidad','Especialidad'),('cuadrilla','Cuadrilla'),('rol','Rol')],
        campos=[('nombre','Nombre','text',True),('puesto','Puesto','select',PUESTOS),('telefono','Teléfono','tel'),('email','Email','email'),('especialidad','Especialidad','select',ESPEC),
                ('cuadrilla_id','Cuadrilla','fk',CUAD),('rol','Rol en la cuadrilla','select',['líder','técnico'])],
        hist=lambda i: existe('SELECT 1 FROM herramientas WHERE personal_id=?', (i,)) or existe("SELECT 1 FROM tecnicos t JOIN ordenes o ON o.cuadrilla_id=t.cuadrilla_id WHERE t.id=?", (i,)),
        valid=pers_valid),
     'vehiculos': dict(titulo='Vehículos', icono='🚚', tabla='vehiculos', act='activo', orden='numero', desc='Vehículos 01–18 (cada uno es un almacén móvil); varios por cuadrilla.',
        buscar=['numero','placas','marca','modelo'],
        sql="SELECT v.*, c.nombre cuadrilla, a.nombre almacen FROM vehiculos v LEFT JOIN cuadrillas c ON c.id=v.cuadrilla_id LEFT JOIN almacenes a ON a.id=v.almacen_id",
        cols=[('numero','Número'),('placas','Placas'),('marca','Marca'),('modelo','Modelo'),('anio','Año'),('cuadrilla','Cuadrilla'),('almacen','Almacén')],
        campos=[('numero','Número (01–18)','text',True),('placas','Placas','text'),('marca','Marca','text'),('modelo','Modelo','text'),('anio','Año','number'),
                ('cuadrilla_id','Cuadrilla asignada','fk',CUAD),('notas','Notas','textarea')],
        valid=veh_valid, post=veh_post, hist=veh_hist, soft=veh_baja_soft, pre_del=veh_del, unico=[('numero','Ese número de vehículo ya existe')]),
     'cuadrillas': dict(titulo='Cuadrillas', icono='👥', tabla='cuadrillas', act='activa', orden='id', desc='Líder y técnico (desde Personal), especialidad, zona y vehículos.',
        buscar=['nombre','especialidad','zona'],
        sql="""SELECT c.*, (SELECT nombre FROM tecnicos WHERE cuadrilla_id=c.id AND rol='líder') lider, (SELECT nombre FROM tecnicos WHERE cuadrilla_id=c.id AND rol='técnico') tecnico,
               (SELECT group_concat(numero, ', ') FROM vehiculos WHERE cuadrilla_id=c.id) vehs FROM cuadrillas c""",
        cols=[('nombre','Nombre'),('especialidad','Especialidad'),('zona','Zona'),('lider','Líder'),('tecnico','Técnico'),('vehs','Vehículos')],
        campos=[('nombre','Nombre','text',True),('especialidad','Especialidad','select',ESPEC),('zona','Zona','text'),
                ('lider_id','Líder','fk*',PERS),('tecnico_id','Técnico','fk*',PERS),('vehiculos','Vehículos','multi*',VEH)],
        extra=cuad_extra, post=cuad_post, hist=lambda i: existe('SELECT 1 FROM ordenes WHERE cuadrilla_id=? LIMIT 1', (i,)), pre_del=cuad_del),
     'sites': dict(titulo='Sites', icono='📍', tabla='sitios', act='activo', orden='codigo', desc='Torres, nodos y sitios de cliente con coordenadas; se eligen en las órdenes.',
        buscar=['codigo','nombre','cliente','ciudad','tipo'],
        cols=[('codigo','Código'),('nombre','Nombre'),('tipo','Tipo'),('cliente','Cliente'),('ciudad','Ciudad'),('estado','Estado'),('lat','Lat'),('lng','Lng')],
        campos=[('codigo','Código','text',True),('nombre','Nombre','text',True),('tipo','Tipo','select',TIPOS_SITIO),('cliente','Cliente','text'),('direccion','Dirección','text'),
                ('ciudad','Ciudad','text'),('estado','Estado','text'),('lat','Latitud','coord'),('lng','Longitud','coord'),('contacto','Contacto','text'),('notas','Notas','textarea')],
        hist=lambda i: existe('SELECT 1 FROM ordenes WHERE site_id=? LIMIT 1', (i,)), unico=[('codigo','Ese código de site ya existe')],
        pre_del=lambda i: None),
     'almacenes': dict(titulo='Almacenes', icono='🏬', tabla='almacenes', act='activo', orden="tipo, nombre", desc='Bodegas (Torrelit, Autosound) y vehículos 01–18.',
        buscar=['nombre','tipo'],
        sql="SELECT a.*, c.nombre cuadrilla, (SELECT COUNT(*) FROM existencias e WHERE e.almacen_id=a.id AND e.stock>0) nmat FROM almacenes a LEFT JOIN cuadrillas c ON c.id=a.cuadrilla_id",
        cols=[('nombre','Nombre'),('tipo','Tipo'),('cuadrilla','Cuadrilla'),('nmat','Materiales con stock')],
        campos=[('nombre','Nombre','text',True),('tipo','Tipo','select',['bodega','vehiculo'],True),('cuadrilla_id','Cuadrilla (vehículos)','fk',CUAD)],
        post=alm_post, hist=alm_hist, pre_del=alm_del, unico=[('nombre','Ya existe un almacén con ese nombre')], ver_url='/inventario?almacen={id}'),
     'herramientas': dict(titulo='Herramientas y Equipo', icono='🛠', tabla='herramientas', act='activo', orden='codigo', desc='Herramienta, equipo de medición y EPP; asignación y calibración.',
        buscar=['codigo','numero_serie','nombre','tipo','marca','modelo','estado'],
        sql="""SELECT h.*, c.nombre cuadrilla, t.nombre persona, a.nombre almacen,
               TRIM(COALESCE(c.nombre,'')||' '||COALESCE(t.nombre,'')||' '||COALESCE(a.nombre,'')) asignado FROM herramientas h
               LEFT JOIN cuadrillas c ON c.id=h.cuadrilla_id LEFT JOIN tecnicos t ON t.id=h.personal_id LEFT JOIN almacenes a ON a.id=h.almacen_id""",
        cols=[('codigo','Código'),('numero_serie','No. serie'),('nombre','Nombre'),('tipo','Tipo'),('marca','Marca'),('estado','Estado'),('asignado','Asignado a'),('fecha_calibracion','Calibración')],
        campos=[('codigo','Código','text'),('numero_serie','Número de serie','text'),('nombre','Nombre','text',True),('tipo','Tipo','select',TIPOS_HERR),('marca','Marca','text'),
                ('modelo','Modelo','text'),('estado','Estado','select',ESTADOS_HERR,True),('cuadrilla_id','Asignado a cuadrilla','fk',CUAD),('personal_id','Asignado a persona','fk',PERS),
                ('almacen_id','Ubicado en almacén / vehículo','fk',ALM),('fecha_calibracion','Próxima calibración','date'),('notas','Notas','textarea')],
        valid=herr_valid, hist=lambda i: True, soft=lambda i: db().execute("UPDATE herramientas SET estado='baja' WHERE id=?", (i,))),
    }
    SQLCOL = {'personal':'t','vehiculos':'v','cuadrillas':'c','almacenes':'a','herramientas':'h'}

    @app.route('/configuracion')
    def configuracion():
        cnt = {k: q(f"SELECT COUNT(*) n, SUM({e['act']}=1) a FROM {e['tabla']}", one=True) for k, e in E.items()}
        return render_template('config_inicio.html', E=E, cnt=cnt)

    def ent(k): return E.get(k) or abort(404)

    @app.route('/configuracion/<k>')
    def cfg_lista(k):
        e = ent(k); s = (request.args.get('q') or '').strip(); ver = request.args.get('ver', 'activos')
        p = SQLCOL.get(k); pre = p + '.' if p else ''
        sql = e.get('sql') or f"SELECT * FROM {e['tabla']}"; w, a = [], []
        if s: w.append('(' + ' OR '.join(f"{pre}{c} LIKE ?" for c in e['buscar']) + ')'); a += ['%'+s+'%']*len(e['buscar'])
        if ver == 'activos': w.append(f"COALESCE({pre}{e['act']},1)=1")
        elif ver == 'inactivos': w.append(f"COALESCE({pre}{e['act']},1)=0")
        orden = ', '.join(pre + o.strip() for o in e['orden'].split(','))
        rows = q(f"{sql} {'WHERE '+' AND '.join(w) if w else ''} ORDER BY {orden} LIMIT 500", a)
        return render_template('config_lista.html', k=k, e=e, rows=rows, s=s, ver=ver, msg=request.args.get('msg'))

    @app.route('/configuracion/<k>/nuevo', methods=['GET','POST'])
    @app.route('/configuracion/<k>/<int:rid>/editar', methods=['GET','POST'])
    def cfg_form(k, rid=None):
        e = ent(k)
        if k == 'materiales': return redirect(e['editar_url'].format(id=rid) if rid else e['alta_url'])
        r = dict(q(f"SELECT * FROM {e['tabla']} WHERE id=?", (rid,), one=True) or abort(404)) if rid else {e['act']: 1}
        if e.get('extra'): r.update(e['extra'](rid))
        err = None
        if request.method == 'POST':
            F = request.form; d = {}
            for f in e['campos']:
                col, typ = f[0], f[2]
                if typ.endswith('*'): continue
                v = (F.get(col) or '').strip() or None
                if v is not None and typ in ('fk','number'): v = int(v)
                if v is not None and typ == 'coord':
                    try: v = float(v)
                    except ValueError: err = f'{f[1]} debe ser numérica'
                d[col] = v
            d[e['act']] = 1 if F.get('activo') else 0
            req = [f[1] for f in e['campos'] if len(f) > 3 and f[3] is True and not f[2].endswith('*') and not d.get(f[0])]
            if req: err = 'Obligatorio: ' + ', '.join(req)
            if not err and e.get('valid'): err = e['valid'](d, rid)
            for col, m in e.get('unico', []):
                if not err and d.get(col) and q(f"SELECT 1 FROM {e['tabla']} WHERE {col}=? AND id IS NOT ?", (d[col], rid), one=True): err = m
            if not err:
                ks = list(d)
                if rid: db().execute(f"UPDATE {e['tabla']} SET {', '.join(c+'=?' for c in ks)} WHERE id=?", [d[c] for c in ks]+[rid])
                else: rid = db().execute(f"INSERT INTO {e['tabla']}({','.join(ks)}) VALUES({','.join('?'*len(ks))})", [d[c] for c in ks]).lastrowid
                if e.get('post'): e['post'](rid, d)
                db().commit(); return redirect(url_for('cfg_lista', k=k, msg='Guardado'))
            db().rollback(); r.update(d)
            for f in e['campos']:
                if f[2] == 'multi*': r[f[0]] = [int(x) for x in F.getlist(f[0])]
                elif f[2] == 'fk*': r[f[0]] = int(F[f[0]]) if F.get(f[0]) else None
        campos = [(f[0], f[1], f[2].rstrip('*'), (f[3]() if callable(f[3]) else f[3]) if len(f) > 3 and not isinstance(f[3], bool) else None,
                   any(x is True for x in f[3:])) for f in e['campos']]
        return render_template('config_form.html', k=k, e=e, r=r, rid=rid, campos=campos, err=err)

    @app.route('/configuracion/<k>/<int:rid>/baja', methods=['POST'])
    def cfg_baja(k, rid):
        e = ent(k); q(f"SELECT 1 FROM {e['tabla']} WHERE id=?", (rid,), one=True) or abort(404)
        if e['hist'](rid):
            db().execute(f"UPDATE {e['tabla']} SET {e['act']}=0 WHERE id=?", (rid,))
            if e.get('soft'): e['soft'](rid)
            msg = 'Dado de baja (desactivado; tiene historial)'
        else:
            if e.get('pre_del'): e['pre_del'](rid)
            db().execute(f"DELETE FROM {e['tabla']} WHERE id=?", (rid,)); msg = 'Eliminado (no tenía historial)'
        db().commit(); return redirect(url_for('cfg_lista', k=k, msg=msg))

    @app.route('/configuracion/<k>/<int:rid>/reactivar', methods=['POST'])
    def cfg_reactivar(k, rid):
        e = ent(k); db().execute(f"UPDATE {e['tabla']} SET {e['act']}=1 WHERE id=?", (rid,))
        if k == 'vehiculos': db().execute('UPDATE almacenes SET activo=1 WHERE id=(SELECT almacen_id FROM vehiculos WHERE id=?)', (rid,))
        if k == 'almacenes': db().execute('UPDATE vehiculos SET activo=1 WHERE almacen_id=?', (rid,))
        if k == 'herramientas': db().execute("UPDATE herramientas SET estado='disponible' WHERE id=? AND estado='baja'", (rid,))
        db().commit(); return redirect(url_for('cfg_lista', k=k, ver='todos', msg='Reactivado'))
    return E
