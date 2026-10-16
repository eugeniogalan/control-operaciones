"""Menú Configuración: altas, bajas y cambios de catálogos (Materiales, Personal, Vehículos, Cuadrillas, Sites, Almacenes, Herramientas y Equipo)."""
from flask import render_template, request, redirect, url_for, abort

SCHEMA_CFG = '''
CREATE TABLE IF NOT EXISTS sitios(id INTEGER PRIMARY KEY, codigo TEXT UNIQUE, nombre TEXT NOT NULL, cliente TEXT, direccion TEXT, ciudad TEXT, estado TEXT,
 lat REAL, lng REAL, tipo TEXT, contacto TEXT, notas TEXT, activo INTEGER DEFAULT 1, ejemplo INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS clientes(id INTEGER PRIMARY KEY, nombre TEXT UNIQUE NOT NULL, tipo_cliente TEXT, rfc TEXT, contacto TEXT, telefono TEXT, email TEXT,
 calle TEXT, ciudad TEXT, estado TEXT, notas TEXT, activo INTEGER DEFAULT 1, ejemplo INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS proveedores(id INTEGER PRIMARY KEY, codigo TEXT, razon_social TEXT UNIQUE NOT NULL, rfc TEXT, contacto TEXT, telefono TEXT, email TEXT,
 sitio_web TEXT, categoria TEXT, condiciones_pago TEXT, notas TEXT, activo INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS vehiculos(id INTEGER PRIMARY KEY, numero TEXT UNIQUE NOT NULL, placas TEXT, marca TEXT, modelo TEXT, anio INTEGER,
 cuadrilla_id INTEGER REFERENCES cuadrillas(id) ON DELETE SET NULL, almacen_id INTEGER REFERENCES almacenes(id) ON DELETE SET NULL, activo INTEGER DEFAULT 1, notas TEXT);
CREATE TABLE IF NOT EXISTS herramientas(id INTEGER PRIMARY KEY, codigo TEXT, numero_serie TEXT, nombre TEXT NOT NULL, tipo TEXT, marca TEXT, modelo TEXT,
 estado TEXT DEFAULT 'disponible', cuadrilla_id INTEGER REFERENCES cuadrillas(id) ON DELETE SET NULL, personal_id INTEGER REFERENCES tecnicos(id) ON DELETE SET NULL,
 almacen_id INTEGER REFERENCES almacenes(id) ON DELETE SET NULL, fecha_calibracion TEXT, notas TEXT, activo INTEGER DEFAULT 1, ejemplo INTEGER DEFAULT 0);
'''
TIPOS_SITIO = ['Site','Site + Torre','Gabinete para exteriores','Gabinete para exteriores + Torre','Torre']  # solo sitios propios de Spectro Networks
ENERGIAS = ['CFE','Solar','Generador']
VOLTAJES = ['110V','220V','440V']
VOLT_SPN = {'SPN-TR-001':'110V,220V','SPN-POP-01':'110V,220V,440V','SPN-CS-003':'110V','SPN-TR-005':'220V'}
TIPOS_TORRE = ['TZ30','TZ45','T60','Autosoportada']
ENERGIA_SPN = [('SPN-TR-001',30,'CFE,Generador','TZ30'),('SPN-POP-01',None,'CFE,Generador',None),('SPN-CS-003',None,'CFE',None),
    ('SPN-RP-004',18,'Solar,Generador','Autosoportada'),('SPN-TR-005',42,'CFE,Solar','TZ45')]
def sitio_valid(d, rid):
    if 'CFE' not in (d.get('energia') or '').split(','): d['voltaje_cfe'] = None
    if 'Torre' in (d.get('tipo') or ''):
        if d.get('altura_torre') is None: return 'Altura de torre (m) es obligatoria cuando el tipo incluye Torre'
        if d['altura_torre'] <= 0: return 'Altura de torre debe ser mayor a 0'
    else: d['altura_torre'] = None; d['tipo_torre'] = None
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
    if 'cliente_id' not in [r[1] for r in c.execute('PRAGMA table_info(ordenes)')]:
        c.execute('ALTER TABLE ordenes ADD COLUMN cliente_id INTEGER REFERENCES clientes(id) ON DELETE SET NULL')
    if 'cliente_id' not in [r[1] for r in c.execute('PRAGMA table_info(sitios)')]:
        c.execute('ALTER TABLE sitios ADD COLUMN cliente_id INTEGER REFERENCES clientes(id) ON DELETE SET NULL')
    sc = [r[1] for r in c.execute('PRAGMA table_info(sitios)')]
    for col, typ in (('altura_torre','REAL'), ('energia','TEXT'), ('tipo_torre','TEXT'), ('voltaje_cfe','TEXT')):
        if col not in sc: c.execute(f'ALTER TABLE sitios ADD COLUMN {col} {typ}')
    _sembrar_sitios(c)
    for cod, vv in VOLT_SPN.items():
        c.execute("UPDATE sitios SET voltaje_cfe=? WHERE codigo=? AND ejemplo=1 AND voltaje_cfe IS NULL AND ','||COALESCE(energia,'CFE')||',' LIKE '%,CFE,%'", (vv, cod))
    for cod, alt, en, tt in ENERGIA_SPN:
        c.execute("UPDATE sitios SET altura_torre=COALESCE(altura_torre,?), energia=COALESCE(energia,?), tipo_torre=COALESCE(tipo_torre,?) WHERE codigo=? AND ejemplo=1", (alt, en, tt, cod))
    for t in ('materiales','herramientas'):
        if 'proveedor_id' not in [r[1] for r in c.execute(f'PRAGMA table_info({t})')]:
            c.execute(f'ALTER TABLE {t} ADD COLUMN proveedor_id INTEGER REFERENCES proveedores(id) ON DELETE SET NULL')
    if not c.execute("SELECT 1 FROM proveedores WHERE razon_social LIKE 'Syscom%' OR codigo='SYSCOM'").fetchone():
        c.execute("INSERT INTO proveedores(codigo,razon_social,sitio_web,categoria,notas) VALUES('SYSCOM','Syscom','https://www.syscom.mx','materiales','Distribuidor de seguridad, redes y telecom. Integración API en Proveedores › Syscom.')")
    c.execute("UPDATE materiales SET proveedor_id=(SELECT id FROM proveedores WHERE codigo='SYSCOM') WHERE proveedor_id IS NULL AND (syscom_id IS NOT NULL OR syscom_sync IS NOT NULL)")
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
    # Clientes: se crean a partir de los nombres ya capturados en órdenes y sites (sin perder el texto original)
    if not c.execute('SELECT 1 FROM clientes LIMIT 1').fetchone():
        for (n, tc, ca, ci, es, co, te) in c.execute('''SELECT TRIM(cliente), MAX(tipo_cliente), MAX(calle), MAX(ciudad), MAX(estado_geo), MAX(contacto), MAX(telefono)
                FROM ordenes WHERE TRIM(COALESCE(cliente,''))<>'' GROUP BY TRIM(cliente)''').fetchall():
            c.execute('INSERT OR IGNORE INTO clientes(nombre,tipo_cliente,calle,ciudad,estado,contacto,telefono) VALUES(?,?,?,?,?,?,?)', (n, tc, ca, ci, es, co, te))
    c.execute("UPDATE ordenes SET cliente_id=(SELECT id FROM clientes WHERE nombre=TRIM(ordenes.cliente)) WHERE cliente_id IS NULL AND TRIM(COALESCE(cliente,''))<>''")
    _limpiar_sitios_cliente(c)
    c.execute("""UPDATE sitios SET tipo=CASE WHEN LOWER(tipo) IN ('torre','repetidor') THEN 'Torre' ELSE 'Site' END
        WHERE tipo IS NULL OR tipo NOT IN ('Site','Site + Torre','Gabinete para exteriores','Gabinete para exteriores + Torre','Torre')""")
    # vehículos: uno por cada almacén "Vehículo NN" existente
    if not c.execute('SELECT 1 FROM vehiculos LIMIT 1').fetchone():
        for aid, nom, cid, act in c.execute("SELECT id,nombre,cuadrilla_id,activo FROM almacenes WHERE tipo='vehiculo' ORDER BY nombre").fetchall():
            num = nom.replace('Vehículo','').strip() or str(aid)
            c.execute('INSERT OR IGNORE INTO vehiculos(numero,cuadrilla_id,almacen_id,activo) VALUES(?,?,?,?)', (num, cid, aid, act))

SITIOS_SPN = [('SPN-TR-001','Torre Cerro del Cuatro','Cerro del Cuatro s/n','Tlaquepaque','Jalisco',20.5952,-103.3640,'Site + Torre','NOC Spectro'),
    ('SPN-POP-01','POP Guadalajara Centro','Av. Juárez 120','Guadalajara','Jalisco',20.6748,-103.3470,'Site','NOC Spectro'),
    ('SPN-CS-003','Caseta Zapopan Norte','Av. Patria 2000','Zapopan','Jalisco',20.7270,-103.4060,'Gabinete para exteriores',''),
    ('SPN-RP-004','Repetidor Tapalpa','Cerro La Cruz','Tapalpa','Jalisco',19.9440,-103.7590,'Gabinete para exteriores + Torre',''),
    ('SPN-TR-005','Torre Cerro de la Reina','Cerro de la Reina','Tonalá','Jalisco',20.6170,-103.2330,'Torre','')]
def _sembrar_sitios(c):
    if not c.execute("SELECT 1 FROM sitios WHERE codigo LIKE 'SPN-%' LIMIT 1").fetchone():
        for s in SITIOS_SPN:
            c.execute('INSERT OR IGNORE INTO sitios(codigo,nombre,direccion,ciudad,estado,lat,lng,tipo,contacto,notas,ejemplo) VALUES(?,?,?,?,?,?,?,?,?,?,1)', s+('EJEMPLO',))

def _limpiar_sitios_cliente(c):
    """Sites = solo infraestructura propia de Spectro Networks. Quita los ejemplos de nodo/cliente y la liga a clientes."""
    viejos = ('TR-001','ND-010','ND-011','RP-003','CL-101','CL-102')
    nombres = [r[0] for r in c.execute(f"SELECT DISTINCT cliente FROM sitios WHERE ejemplo=1 AND codigo IN ({','.join('?'*len(viejos))}) AND cliente IS NOT NULL", viejos)]
    for (sid, usado) in c.execute(f"SELECT id, EXISTS(SELECT 1 FROM ordenes WHERE site_id=sitios.id) FROM sitios WHERE ejemplo=1 AND codigo IN ({','.join('?'*len(viejos))})", viejos).fetchall():
        if usado: c.execute('UPDATE sitios SET activo=0 WHERE id=?', (sid,))
        else: c.execute('DELETE FROM sitios WHERE id=?', (sid,))
    c.execute('UPDATE sitios SET cliente_id=NULL, cliente=NULL WHERE cliente_id IS NOT NULL OR cliente IS NOT NULL')
    for n in nombres:   # clientes creados solo a partir de esos sites de ejemplo
        c.execute("DELETE FROM clientes WHERE nombre=? AND NOT EXISTS(SELECT 1 FROM ordenes o WHERE o.cliente_id=clientes.id OR TRIM(o.cliente)=clientes.nombre)", (n,))

def registrar(app, q, db):
    def opts(sql): return lambda: [(r[0], r[1]) for r in q(sql)]
    CUAD = opts("SELECT id, nombre FROM cuadrillas WHERE activa=1 OR activa IS NULL ORDER BY id")
    PERS = opts("SELECT id, nombre FROM tecnicos WHERE COALESCE(activo,1)=1 ORDER BY nombre")
    ALM = opts("SELECT id, nombre FROM almacenes WHERE activo=1 ORDER BY tipo, nombre")
    CLI = opts("SELECT id, nombre FROM clientes WHERE activo=1 ORDER BY nombre")
    PROV = opts("SELECT id, razon_social FROM proveedores WHERE activo=1 ORDER BY razon_social")
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
        sql='SELECT m.*, p.razon_social proveedor FROM materiales m LEFT JOIN proveedores p ON p.id=m.proveedor_id',
        cols=[('sku','SKU'),('nombre','Nombre'),('proveedor','Proveedor'),('categoria','Categoría'),('codigo_barras','Código de barras'),('numero_parte','No. parte'),('marca','Marca'),('unidad','Unidad'),('stock_actual','Stock')],
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
     'proveedores': dict(titulo='Proveedores', icono='🚛', tabla='proveedores', act='activo', orden='razon_social', desc='Proveedores de materiales, herramientas y servicios (incluye Syscom).',
        buscar=['codigo','razon_social','rfc','contacto','categoria'],
        cols=[('codigo','Código'),('razon_social','Razón social'),('rfc','RFC'),('categoria','Categoría'),('contacto','Contacto'),('telefono','Teléfono'),('sitio_web','Sitio web')],
        campos=[('codigo','Código','text'),('razon_social','Razón social','text',True),('rfc','RFC','text'),('contacto','Contacto','text'),('telefono','Teléfono','tel'),('email','Email','email'),
                ('sitio_web','Sitio web','url'),('categoria','Categoría','select',['materiales','herramientas','servicios','otros']),('condiciones_pago','Condiciones de pago','text'),('notas','Notas','textarea')],
        hist=lambda i: existe('SELECT 1 FROM materiales WHERE proveedor_id=?', (i,)) or existe('SELECT 1 FROM herramientas WHERE proveedor_id=?', (i,)),
        unico=[('razon_social','Ese proveedor ya existe')]),
     'clientes': dict(titulo='Clientes', icono='🏢', tabla='clientes', act='activo', orden='nombre', desc='Catálogo de clientes; se eligen en las órdenes de trabajo.',
        buscar=['nombre','rfc','contacto','ciudad','tipo_cliente'],
        cols=[('nombre','Nombre'),('tipo_cliente','Tipo'),('rfc','RFC'),('contacto','Contacto'),('telefono','Teléfono'),('ciudad','Ciudad')],
        campos=[('nombre','Nombre / razón social','text',True),('tipo_cliente','Tipo de cliente','select',['Empresa','PYME','Residencial','Gobierno']),('rfc','RFC','text'),
                ('contacto','Persona de contacto','text'),('telefono','Teléfono','tel'),('email','Email','email'),('calle','Calle y No.','text'),('ciudad','Ciudad','text'),
                ('estado','Estado','text'),('notas','Notas','textarea')],
        hist=lambda i: existe('SELECT 1 FROM ordenes WHERE cliente_id=? LIMIT 1', (i,)),
        unico=[('nombre','Ese cliente ya existe')]),
     'sites': dict(titulo='Sites', icono='📍', tabla='sitios', act='activo', orden='codigo', desc='Sitios propios de Spectro Networks (torres, casetas, POPs, repetidores) con coordenadas.',
        buscar=['codigo','nombre','ciudad','tipo'],
        cols=[('codigo','Código'),('nombre','Nombre'),('tipo','Tipo'),('tipo_torre','Tipo torre'),('altura_torre','Altura torre (m)'),('energia','Energía'),('voltaje_cfe','Voltaje CFE'),('ciudad','Ciudad'),('estado','Estado'),('lat','Lat'),('lng','Lng')],
        campos=[('codigo','Código','text',True),('nombre','Nombre','text',True),('tipo','Tipo','select',TIPOS_SITIO),('tipo_torre','Tipo de torre','datalist',TIPOS_TORRE),('altura_torre','Altura de torre (m)','decimal'),('energia','Tipo de energía','checks',ENERGIAS),('voltaje_cfe','Voltaje CFE disponible','checks',VOLTAJES),('direccion','Dirección','text'),
                ('ciudad','Ciudad','text'),('estado','Estado','text'),('lat','Latitud','coord'),('lng','Longitud','coord'),('contacto','Contacto','text'),('notas','Notas','textarea')],
        hist=lambda i: existe('SELECT 1 FROM ordenes WHERE site_id=? LIMIT 1', (i,)), unico=[('codigo','Ese código de site ya existe')], valid=sitio_valid,
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
                ('almacen_id','Ubicado en almacén / vehículo','fk',ALM),('fecha_calibracion','Próxima calibración','date'),('proveedor_id','Proveedor','fk',PROV),('notas','Notas','textarea')],
        valid=herr_valid, hist=lambda i: True, soft=lambda i: db().execute("UPDATE herramientas SET estado='baja' WHERE id=?", (i,))),
    }
    SQLCOL = {'materiales':'m','personal':'t','vehiculos':'v','cuadrillas':'c','almacenes':'a','herramientas':'h'}

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
        if not rid:
            for f in e['campos']:
                if request.args.get(f[0]): r[f[0]] = int(request.args[f[0]]) if f[2] == 'fk' and request.args[f[0]].isdigit() else request.args[f[0]]
        err = None
        if request.method == 'POST':
            F = request.form; d = {}
            for f in e['campos']:
                col, typ = f[0], f[2]
                if typ.endswith('*'): continue
                v = (F.get(col) or '').strip() or None
                if v is not None and typ in ('fk','number'): v = int(v)
                if typ == 'checks':
                    sel = F.getlist(col); v = ','.join(o for o in f[3] if o in sel) or None
                if v is not None and typ == 'decimal':
                    try: v = float(v)
                    except ValueError: err = f'{f[1]} debe ser numérica'; v = None
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
