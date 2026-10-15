"""Carga datos de EJEMPLO: 10 cuadrillas x 2, ~150 órdenes en un mes. Uso: python3 seed.py  (borra y recrea ops.db)"""
import os, sys, random, sqlite3, datetime as dt, json
random.seed(7)
B = os.path.dirname(os.path.abspath(__file__)); DB = os.environ.get('DB_PATH') or os.path.join(B, 'ops.db')
if '--if-missing' in sys.argv and os.path.exists(DB):
    print('DB existente, no se recarga:', DB); sys.exit(0)
if os.path.exists(DB): os.remove(DB)
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
CLI = [('Ejemplo Hotel Plaza','Empresa'),('Ejemplo Municipio San Pedro','Gobierno'),('Ejemplo Farmacias del Valle','PYME'),('Ejemplo Escuela Técnica 12','Gobierno'),
       ('Ejemplo Residencial Los Pinos','Residencial'),('Ejemplo Logística Nova','Empresa'),('Ejemplo Clínica Santa Fe','PYME'),('Ejemplo Agroindustrias Delta','Empresa'),
       ('Red propia (backbone)','Empresa'),('Ejemplo Gasolinera Ruta 45','PYME')]
CIU = [('Monterrey','Nuevo León'),('Guadalajara','Jalisco'),('Querétaro','Querétaro'),('Puebla','Puebla'),('León','Guanajuato')]
SITIOS = ['Nodo Centro','Torre Cerro Alto','POP Industrial','Sitio Repetidor Km 32','Edificio corporativo','Sucursal 4','Caseta norte','Azotea bodega','Site principal','Poste P-118']
ESPC = {'Fibra Óptica':['EJ-FO','INST'],'Microondas':['EJ-MO','INST'],'Instalaciones a cliente':['INST'],'Redes / Wi-Fi':['INST'],'Satelital':['INST'],'Mixta':['EJ-FO','EJ-MO','INST']}
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
    pref = {'EJ-FO':'FO','EJ-MO':'MO','INST':'IC'}[cat] + d.strftime('%y%m'); cnt[pref] = cnt.get(pref, 0) + 1
    cli, tcli = random.choice(CLI) if cat == 'INST' else ('Red propia (backbone)','Empresa')
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
            c.execute('INSERT INTO orden_materiales(orden_id,seccion,concepto,tipo,cantidad,unidad) VALUES(?,?,?,?,?,?)', (oid, m['seccion'], m['concepto'], random.choice(tipos), q, m['unidad']))
c.commit(); print('órdenes', c.execute('SELECT estado,COUNT(*) FROM ordenes GROUP BY estado').fetchall())
