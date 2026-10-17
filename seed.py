"""Carga datos de EJEMPLO: 10 cuadrillas x 2, ~150 órdenes en un mes, inventario (89 materiales, 20 almacenes).
Uso: python3 seed.py [--if-missing]. SOLO siembra si la base no existe o está vacía: nunca borra ni sobrescribe datos reales.
Para recrear a propósito una base que ya tiene datos: python3 seed.py --force (borra la base)."""
import os, sys, random, sqlite3, datetime as dt, json
random.seed(7)
import rutas
B = rutas.BASE; DB = rutas.DB
if rutas.bd_con_datos(DB) and '--force' not in sys.argv:
    print('La base ya tiene datos; no se siembra nada:', DB); sys.exit(0)
if os.path.exists(DB): os.remove(DB)   # inexistente, vacía o --force
import app as A
c = sqlite3.connect(DB)
CU = [('Cuadrilla 01','Fibra Óptica','Norte'),('Cuadrilla 02','Fibra Óptica','Sur'),('Cuadrilla 03','Fibra Óptica','Centro'),('Cuadrilla 04','Microondas','Norte'),
      ('Cuadrilla 05','Microondas','Sur'),('Cuadrilla 06','Instalaciones a cliente','Centro'),('Cuadrilla 07','Instalaciones a cliente','Oriente'),
      ('Cuadrilla 08','Redes / Wi-Fi','Poniente'),('Cuadrilla 09','Satelital','Foránea'),('Cuadrilla 10','Mixta','Centro')]
NOM = ['Juan','Luis','Carlos','Miguel','José','Pedro','Jorge','Raúl','Arturo','Fernando','Ricardo','Héctor','Óscar','Alejandro','Sergio','Daniel','Iván','Mario','Andrés','Rubén']
AP = ['Ramírez','López','Hernández','García','Martínez','Torres','Flores','Vargas','Castillo','Mendoza','Ortiz','Reyes','Morales','Cruz','Jiménez','Ruiz','Navarro','Silva','Rojas','Aguilar']
for i,(n,e,z) in enumerate(CU):
    cid = c.execute('INSERT INTO cuadrillas(nombre,especialidad,zona,ejemplo) VALUES(?,?,?,1)', (n,e,z)).lastrowid
    for j,rol in enumerate(('líder','técnico')):
        k = i*2+j
        c.execute('INSERT INTO tecnicos(cuadrilla_id,rol,nombre,telefono,especialidad,puesto,ejemplo) VALUES(?,?,?,?,?,?,1)',
          (cid, rol, f'{NOM[k]} {AP[k]} (ejemplo)', f'55-0000-{k:04d}', e, 'Supervisor' if rol=='líder' else 'Técnico Instalador'))
A.CM.migrar_puestos(c)   # Director, Gerente, Vendedor y Supervisor de ejemplo (pueden ordenar)
today = dt.date.today()
# ---- Inventario: catálogo desde plantillas.json + 20 almacenes (Torrelit, Autosound, Vehículo 01..18) ----
A.asegurar_vehiculos(c)
# Asignación de ejemplo: Vehículo NN → Cuadrilla NN (01-10); 11-18 → cuadrillas 01-08 (segundo vehículo)
for i in range(1, 19):
    c.execute('UPDATE almacenes SET cuadrilla_id=? WHERE nombre=?', ((i - 1) % 10 + 1, f'Vehículo {i:02d}'))
c.execute('UPDATE vehiculos SET cuadrilla_id=(SELECT a.cuadrilla_id FROM almacenes a WHERE a.id=vehiculos.almacen_id) WHERE almacen_id IS NOT NULL')   # misma cuadrilla en el catálogo de vehículos
ALM = {n: i for i, n in c.execute('SELECT id, nombre FROM almacenes')}
VEH = {cid: i for i, cid in c.execute("SELECT MIN(id), cuadrilla_id FROM almacenes WHERE tipo='vehiculo' AND cuadrilla_id IS NOT NULL GROUP BY cuadrilla_id")}
PREF = {'FIBRA PLANTA EXTERNA':'FPE','FIBRA PLANTA INTERNA':'FPI','PLANTA EXTERNA':'PE','PLANTA INTERNA':'PI','EQUIPOS':'EQ','EQUIPOS DE RED':'RED',
        'GABINETES, RACKS, ACCESORIOS':'RCK','EQUIPO ELÉCTRICO':'ELE','MATERIALES CONSUMIBLES':'CON'}
vistos, nsku = {}, {}
for pl in A.PLANT.values():
    for m in pl['materiales']:
        k = (m['seccion'], m['concepto'])
        if k in vistos: continue
        pr = PREF.get(m['seccion'], 'OTR'); nsku[pr] = nsku.get(pr, 0) + 1
        u = A.norm_unidad(m['unidad'])
        vistos[k] = c.execute('INSERT INTO materiales(sku,nombre,categoria,variantes,unidad,stock_minimo,ubicacion,notas,ejemplo) VALUES(?,?,?,?,?,?,?,?,1)',
            (f'{pr}-{nsku[pr]:03d}', m['concepto'], m['seccion'], m['tipos'] if m['tipos'] and m['tipos'] != '(Tipos)' else None, u,
             random.choice([500,1000,2000]) if u == 'm' else random.choice([5,10,20]), f'Anaquel {random.choice("ABCDE")}{random.randint(1,9)}',
             'Cantidades de EJEMPLO')).lastrowid
inicio = f'{today - dt.timedelta(days=25)}T08:00'
for mid in vistos.values():
    mn = c.execute('SELECT stock_minimo FROM materiales WHERE id=?', (mid,)).fetchone()[0]
    f = random.choice([1.5, 3, 4, 5, 6, 8])  # algunos quedarán bajo mínimo
    for alm, part in (('Torrelit', .65), ('Autosound', .35)):
        A.mover(c, mid, ALM[alm], 'entrada', round(mn * f * part * random.uniform(.8, 1.2)) or 1, 'Inventario inicial (EJEMPLO)', 'EJEMPLO', fecha=inicio)
# Carga de ejemplo a 6 vehículos (transferencias desde Torrelit/Autosound)
for vn in ('Vehículo 01', 'Vehículo 02', 'Vehículo 04', 'Vehículo 06', 'Vehículo 12', 'Vehículo 15'):
    for mid in random.sample(list(vistos.values()), 12):
        un = c.execute('SELECT unidad FROM materiales WHERE id=?', (mid,)).fetchone()[0]
        qn = random.choice([100, 200]) if un == 'm' else random.choice([2, 3])
        org = random.choice(['Torrelit', 'Autosound']); fch = f'{today - dt.timedelta(days=22)}T09:00'
        A.mover(c, mid, ALM[org], 'transferencia', -qn, f'Transferencia a {vn} (EJEMPLO)', f'{org} → {vn}', permitir_negativo=True, fecha=fch)
        A.mover(c, mid, ALM[vn], 'transferencia', qn, f'Transferencia desde {org} (EJEMPLO)', f'{org} → {vn}', fecha=fch)
# Mínimos de EJEMPLO por almacén: bodegas reparten el mínimo global (60/40); vehículos cargados, mínimo pequeño
for mid, mn, un in c.execute('SELECT id, stock_minimo, unidad FROM materiales').fetchall():
    c.execute('UPDATE existencias SET minimo=? WHERE material_id=? AND almacen_id=?', (round(mn*.6), mid, ALM['Torrelit']))
    c.execute('UPDATE existencias SET minimo=? WHERE material_id=? AND almacen_id=?', (round(mn*.4), mid, ALM['Autosound']))
c.execute("UPDATE existencias SET minimo=CASE WHEN (SELECT unidad FROM materiales WHERE id=material_id)='m' THEN 50 ELSE 1 END WHERE almacen_id IN (SELECT id FROM almacenes WHERE tipo='vehiculo')")
CLI = [('Ejemplo Hotel Plaza','Empresa'),('Ejemplo Municipio San Pedro','Gobierno'),('Ejemplo Farmacias del Valle','PYME'),('Ejemplo Escuela Técnica 12','Gobierno'),
       ('Ejemplo Residencial Los Pinos','Residencial'),('Ejemplo Logística Nova','Empresa'),('Ejemplo Clínica Santa Fe','PYME'),('Ejemplo Agroindustrias Delta','Empresa'),
       ('Red propia (backbone)','Empresa'),('Ejemplo Gasolinera Ruta 45','PYME')]
CIU = [('Monterrey','Nuevo León'),('Guadalajara','Jalisco'),('Querétaro','Querétaro'),('Puebla','Puebla'),('León','Guanajuato')]
SITIOS = ['Nodo Centro','Torre Cerro Alto','POP Industrial','Sitio Repetidor Km 32','Edificio corporativo','Sucursal 4','Caseta norte','Azotea bodega','Site principal','Poste P-118']
ESPC = {'Fibra Óptica':['EJ-FO','INST'],'Microondas':['EJ-MO','EJ-EQ','INST'],'Instalaciones a cliente':['INST'],'Redes / Wi-Fi':['INST'],'Satelital':['INST'],'Mixta':['EJ-FO','EJ-MO','EJ-EQ','INST']}
INSTP = {'Fibra Óptica':['Enlace a Internet vía Fibra Optica','Enlace Punto-Punto vía Fibra Optica'],'Microondas':['Enlace a Internet vía Microondas','Enlace Punto-Punto vía Microondas'],
  'Redes / Wi-Fi':['Red Inalámbrica (Wi-Fi)','Router/Firewall/Switch','Cableado Estructurado','Sistema de Video-vigilancia (CCTV)'],'Satelital':['Enlace a Internet vía Satelital'],
  'Instalaciones a cliente':['Enlace a Internet vía Fibra Optica','Enlace a Internet vía Microondas','Red Inalámbrica (Wi-Fi)','Sistema de Telefonia IP','Control de Acceso (Humanos)'],
  'Mixta':A.TIPOS['INST']['Tipo de instalación'][:-1]}
today = dt.date.today(); start = today - dt.timedelta(days=20)
cuads = c.execute('SELECT id, especialidad FROM cuadrillas').fetchall()
cnt = {}
for n in range(150):
    cid, esp = cuads[n % 10]
    cat = random.choice(ESPC[esp])
    if cat == 'INST': grp, tipo = 'Tipo de instalación', random.choice(INSTP[esp])
    else: grp = random.choice(list(A.TIPOS[cat])); tipo = random.choice(A.TIPOS[cat][grp])
    d = start + dt.timedelta(days=random.randint(0, 29))
    if n % 10 < 4 and n < 40: d = today  # varias órdenes hoy
    if d < today: estado = random.choices(['completada','en curso','asignada','cancelada'], [78,8,9,5])[0]
    elif d == today: estado = random.choice(['asignada','asignada','en curso','completada'])
    else: estado = random.choice(['asignada','asignada','pendiente'])
    if estado == 'pendiente' and random.random() < .5: cid_ = None
    else: cid_ = cid
    pref = {'EJ-FO':'FO','EJ-MO':'MO','EJ-EQ':'EQ','INST':'IC'}[cat] + d.strftime('%y%m'); cnt[pref] = cnt.get(pref, 0) + 1
    cli, tcli = random.choice(CLI) if cat == 'INST' else (None, None)
    ciu, edo = random.choice(CIU)
    ini = fin = None
    if estado in ('en curso','completada'): ini = f'{d}T{random.randint(8,11):02d}:{random.choice(["00","15","30","45"])}'
    if estado == 'completada': fin = f'{d}T{random.randint(13,18):02d}:{random.choice(["00","20","40"])}'
    aud = random.random() < .6 and estado == 'completada'
    oid = c.execute('''INSERT INTO ordenes(folio,categoria,tipo_grupo,tipo_orden,prioridad,estado,fecha_emision,fecha_programada,fecha_inicio,fecha_cierre,ordena_nombre,ordena_puesto,
      cliente,tipo_cliente,calle,ciudad,estado_geo,contacto,telefono,coordenadas,coordenadas_b,sitio,descripcion,cuadrilla_id,ejecuto_puesto,folio_evidencias,audito_nombre,audito_puesto,fecha_auditoria,aprobacion,ejemplo)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)''',
      (f'{pref}{cnt[pref]:04d}', cat, grp, tipo, random.choices(A.PRIORIDADES, [2,5,3,1])[0], estado, str(d - dt.timedelta(days=random.randint(1,7))), str(d), ini, fin,
       'Supervisor Ejemplo', 'Vendedor' if cat=='INST' and random.random()<.5 else 'Supervisor', cli, tcli, f'Calle Ejemplo {random.randint(1,999)}', ciu, edo,
       'Contacto Ejemplo' if cat=='INST' else None, '55-0000-9999' if cat=='INST' else None, f'{19+random.random()*6:.5f},{-103+random.random()*5:.5f}',
       f'{19+random.random()*6:.5f},{-103+random.random()*5:.5f}' if 'Punto-Punto' in tipo else None,
       random.choice(SITIOS), f'EJEMPLO: {tipo.lower()} en {ciu}.', cid_, 'Técnico Instalador' if cid_ else None,
       f'EV-{pref}{cnt[pref]:04d}' if estado=='completada' and cat=='INST' else None, 'Gerente Ejemplo' if aud else None, 'Gerente' if aud else None,
       str(d + dt.timedelta(days=1)) if aud else None, random.choice(['POSITIVA']*9+['NEGATIVA']) if aud else None)).lastrowid
    c.execute('INSERT INTO bitacora(orden_id,fecha,texto) VALUES(?,?,?)', (oid, f'{d}T07:00', 'Orden creada (ejemplo)'))
    p = A.plantilla_de({'categoria': cat, 'tipo_orden': tipo})
    if estado == 'completada' and p:
        for m in random.sample(A.PLANT[p]['materiales'], 5):
            tipos = [x.strip() for x in m['tipos'].split(',')] if m['tipos'] and m['tipos'] != '(Tipos)' else ['']
            q = random.choice([1,2,4]) if m['unidad'] != 'metros' else random.choice([15,30,50,120])
            mid = vistos[(m['seccion'], m['concepto'])]; un = A.norm_unidad(m['unidad'])
            # Sale del vehículo ligado a la cuadrilla si alcanza; si no, de Torrelit o Autosound
            alm = VEH.get(cid_); r = c.execute('SELECT stock FROM existencias WHERE material_id=? AND almacen_id=?', (mid, alm)).fetchone() if alm else None
            if not r or r[0] < q: alm = max([ALM['Torrelit'], ALM['Autosound']], key=lambda a: (c.execute('SELECT stock FROM existencias WHERE material_id=? AND almacen_id=?', (mid, a)).fetchone() or [0])[0])
            c.execute('INSERT INTO orden_materiales(orden_id,material_id,almacen_id,seccion,concepto,tipo,cantidad,unidad) VALUES(?,?,?,?,?,?,?,?)', (oid, mid, alm, m['seccion'], m['concepto'], random.choice(tipos), q, un))
            A.mover(c, mid, alm, 'salida', q, 'Consumo en orden', f'{pref}{cnt[pref]:04d}', oid, permitir_negativo=True, fecha=fin)
A.migrar_ordenes(c)
A.PERM.demo(c)   # la ejecutiva comercial de ejemplo es propietaria de algunos clientes
print('usuarios demo:', ', '.join(f"{u[0]} ({'con acceso' if u[4] else 'sin acceso'})" for u in A.AU.demo_usuarios(c)) or 'ninguno')
# autorización de ejemplo: algunas instalaciones nuevas aún sin iniciar quedan pendientes / una rechazada
_pend = [r[0] for r in c.execute("SELECT id FROM ordenes WHERE clase='cliente' AND trabajo='Instalación nueva' AND estado IN ('pendiente','asignada') AND fecha_inicio IS NULL ORDER BY fecha_programada DESC LIMIT 5")]
for i, oid in enumerate(_pend):
    if i == 0: c.execute("UPDATE ordenes SET autorizacion='rechazada', estado='pendiente', aut_por_nombre='Roberto Íñiguez (ejemplo)', aut_fecha=fecha_emision||'T10:15', aut_motivo='EJEMPLO: falta confirmar domicilio y contacto del cliente' WHERE id=?", (oid,))
    else: c.execute("UPDATE ordenes SET autorizacion='pendiente', estado='pendiente', aut_por_nombre=NULL, aut_fecha=NULL, aut_solicitada=fecha_emision||'T09:00', aut_solicito='Supervisor Ejemplo' WHERE id=?", (oid,))
_sts = c.execute('SELECT id, codigo, nombre FROM sitios WHERE activo=1').fetchall()
for (oid,) in c.execute("SELECT id FROM ordenes WHERE clase='infra' AND ejemplo=1 AND NOT EXISTS(SELECT 1 FROM orden_sitios WHERE orden_id=ordenes.id)").fetchall():
    if not _sts: break
    if random.random() < .5 or c.execute("SELECT red FROM ordenes WHERE id=?", (oid,)).fetchone()[0] == 'equipo':   # equipo activo y sitios siempre con site
        st = random.choice(_sts); c.execute('INSERT OR IGNORE INTO orden_sitios VALUES(?,?)', (oid, st[0])); c.execute('UPDATE ordenes SET site_id=?, sitio=? WHERE id=?', (st[0], f'{st[1]} · {st[2]}', oid))
c.commit(); print('materiales', c.execute('SELECT COUNT(*) FROM materiales').fetchone()[0], '· almacenes', c.execute('SELECT COUNT(*) FROM almacenes').fetchone()[0],
  '· movimientos', c.execute('SELECT tipo,COUNT(*) FROM movimientos GROUP BY tipo').fetchall(), '· bajo mínimo (global)', c.execute('SELECT COUNT(*) FROM materiales WHERE stock_actual<=stock_minimo').fetchone()[0], '· alertas por almacén', c.execute('SELECT COUNT(*) FROM existencias WHERE minimo>0 AND stock<=minimo').fetchone()[0],
  '· existencias negativas', c.execute('SELECT COUNT(*) FROM existencias WHERE stock<0').fetchone()[0])
print('órdenes', c.execute('SELECT estado,COUNT(*) FROM ordenes GROUP BY estado').fetchall())
# los datos de ejemplo de módulos posteriores (flotilla: combustible y mantenimiento) solo se cargan en una BD recién sembrada
c.execute('CREATE TABLE IF NOT EXISTS app_meta(k TEXT PRIMARY KEY, v TEXT)')
c.execute("INSERT OR REPLACE INTO app_meta VALUES('demo_flota','pendiente')"); c.commit()
