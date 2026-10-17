"""Flotilla: cargas de combustible, rendimiento (km/l), bitácora de mantenimiento, próximos servicios y Dashboard de vehículos.
- /combustible            historial (propio; «Todas» con combustible.ver_todo) · /combustible/nueva registro
- /mantenimiento          bitácora por vehículo (mantenimiento.ver) · alta/edición (mantenimiento.registrar) · /mantenimiento/intervalos
- /vehiculos/dashboard    tablero de flotilla (vehiculos.dashboard) · /vehiculos/dashboard/<id> detalle de un vehículo
Rendimiento: método tanque lleno → tanque lleno cuando el vehículo tiene ≥2 cargas «tanque lleno»; si no, distancia entre cargas
consecutivas / litros de la carga. Kilometraje actual = lectura más reciente entre cargas, checklists diarios y mantenimientos."""
import os, json, uuid, datetime as dt
from markupsafe import Markup, escape
from flask import request, redirect, abort, render_template, g, url_for
import perm_mod as PERM

TIPOS_COMB = ['Gasolina Magna', 'Gasolina Premium', 'Diésel']
TIPOS_MANT = ['Preventivo', 'Correctivo']
CATS_MANT = ['Cambio de aceite', 'Filtros', 'Llantas', 'Frenos', 'Afinación', 'Batería', 'Suspensión', 'Eléctrico', 'Carrocería', 'Verificación', 'Otro']
# intervalos predeterminados (km, meses); editables en /mantenimiento/intervalos (globales y por vehículo)
INTERVALOS_DEF = {'Cambio de aceite': (5000, 6), 'Filtros': (10000, 12), 'Llantas': (10000, 12), 'Frenos': (20000, 12), 'Afinación': (20000, 12),
                  'Batería': (None, 24), 'Suspensión': (30000, 24), 'Verificación': (None, 6)}
PROX_KM, PROX_DIAS = 1000, 15          # «Próximo» si faltan ≤ 1,000 km o ≤ 15 días
ANOMALIA = 0.20                        # caída de rendimiento > 20 % vs. promedio del vehículo
SUB_C, SUB_M = 'combustible', 'mantenimiento'
EST_SERV = {'vencido': ('Vencido', 'background:#fdecec;color:#c62828;border:1px solid #f3c4c4', 0),
            'proximo': ('Próximo', 'background:#fdf6e3;color:#a16207;border:1px solid #ecd59a', 1),
            'aldia': ('Al día', 'background:#e7f6ec;color:#15803d;border:1px solid #b9e3c6', 2),
            'sin': ('Sin historial', 'background:#f2f2f5;color:#6b6b70;border:1px solid #e0e0e5', 3)}
MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']

def ahora_mx():
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo('America/Mexico_City')).replace(tzinfo=None)
    except Exception:
        return dt.datetime.utcnow() - dt.timedelta(hours=6)
def hoy(): return ahora_mx().date()

def _cols(c, t): return [r[1] for r in c.execute(f'PRAGMA table_info({t})')]

# ---------- migración (solo CREATE / ADD COLUMN: nunca borra datos) ----------
def migrar(c):
    c.execute('CREATE TABLE IF NOT EXISTS app_meta(k TEXT PRIMARY KEY, v TEXT)')
    if 'tanque_litros' not in _cols(c, 'vehiculos'): c.execute('ALTER TABLE vehiculos ADD COLUMN tanque_litros REAL')
    c.execute('''CREATE TABLE IF NOT EXISTS cargas_combustible(id INTEGER PRIMARY KEY, vehiculo_id INTEGER NOT NULL REFERENCES vehiculos(id) ON DELETE CASCADE,
        personal_id INTEGER REFERENCES tecnicos(id) ON DELETE SET NULL, usuario TEXT, fecha TEXT NOT NULL, litros REAL NOT NULL, km INTEGER NOT NULL, monto REAL NOT NULL,
        precio_litro REAL, tipo TEXT, tanque_lleno INTEGER DEFAULT 0, foto_ticket TEXT, estacion TEXT, notas TEXT, km_anterior INTEGER, km_alerta INTEGER DEFAULT 0,
        litros_alerta INTEGER DEFAULT 0, creado TEXT DEFAULT (datetime('now','localtime')), ejemplo INTEGER DEFAULT 0)''')
    c.execute('CREATE INDEX IF NOT EXISTS ix_carga_veh ON cargas_combustible(vehiculo_id, fecha)')
    c.execute('CREATE INDEX IF NOT EXISTS ix_carga_pers ON cargas_combustible(personal_id, fecha)')
    c.execute('''CREATE TABLE IF NOT EXISTS mantenimientos(id INTEGER PRIMARY KEY, vehiculo_id INTEGER NOT NULL REFERENCES vehiculos(id) ON DELETE CASCADE,
        fecha TEXT NOT NULL, km INTEGER, tipo TEXT, categoria TEXT NOT NULL, descripcion TEXT, taller TEXT, costo REAL, prox_km INTEGER, prox_fecha TEXT,
        registrado_por TEXT, creado TEXT DEFAULT (datetime('now','localtime')), ejemplo INTEGER DEFAULT 0)''')
    c.execute('CREATE INDEX IF NOT EXISTS ix_mant_veh ON mantenimientos(vehiculo_id, categoria, fecha)')
    c.execute('''CREATE TABLE IF NOT EXISTS mantenimiento_adjuntos(id INTEGER PRIMARY KEY, mantenimiento_id INTEGER NOT NULL REFERENCES mantenimientos(id) ON DELETE CASCADE,
        archivo TEXT NOT NULL, nombre TEXT, es_pdf INTEGER DEFAULT 0, creado TEXT DEFAULT (datetime('now','localtime')))''')
    c.execute('CREATE TABLE IF NOT EXISTS servicio_intervalos(categoria TEXT PRIMARY KEY, km INTEGER, meses INTEGER)')
    c.execute('''CREATE TABLE IF NOT EXISTS vehiculo_intervalos(vehiculo_id INTEGER NOT NULL REFERENCES vehiculos(id) ON DELETE CASCADE, categoria TEXT NOT NULL,
        km INTEGER, meses INTEGER, PRIMARY KEY(vehiculo_id, categoria))''')
    if not c.execute('SELECT 1 FROM servicio_intervalos LIMIT 1').fetchone():
        c.executemany('INSERT OR IGNORE INTO servicio_intervalos VALUES(?,?,?)', [(k, a, b) for k, (a, b) in INTERVALOS_DEF.items()])

# ---------- cálculos ----------
def _f(s):
    try: return dt.date.fromisoformat((s or '')[:10])
    except ValueError: return None

def add_meses(d, m):
    y, mo = divmod(d.month - 1 + m, 12); y += d.year; mo += 1
    import calendar
    return d.replace(year=y, month=mo, day=min(d.day, calendar.monthrange(y, mo)[1]))

def lecturas(con, vid):
    """Lecturas de odómetro (fecha ISO, km, fuente) de cargas, checklists diarios y mantenimientos."""
    L = [(r[0], r[1], 'Carga') for r in con.execute('SELECT fecha, km FROM cargas_combustible WHERE vehiculo_id=? AND km IS NOT NULL', (vid,))]
    L += [(r[0] + 'T' + ((r[2] or 'T07:00').split('T')[-1] if r[2] else '07:00'), r[1], 'Checklist') for r in con.execute('SELECT fecha, km, veh_fin FROM checklists WHERE vehiculo_id=? AND km IS NOT NULL', (vid,))]
    L += [(r[0] + 'T12:00' if len(r[0]) == 10 else r[0], r[1], 'Mantenimiento') for r in con.execute('SELECT fecha, km FROM mantenimientos WHERE vehiculo_id=? AND km IS NOT NULL', (vid,))]
    return sorted(L, key=lambda x: (x[0], x[1]))

def km_actual(con, vid, L=None):
    L = lecturas(con, vid) if L is None else L
    return L[-1] if L else None

def segmentos(cargas):
    """Tramos de rendimiento a partir de cargas ordenadas por fecha/km -> [{fin(id), fecha, dist, litros, monto, kml, metodo}]."""
    cs = [c for c in cargas if c['km'] is not None and c['litros']]
    llenos = [i for i, c in enumerate(cs) if c['tanque_lleno']]
    out = []
    if len(llenos) >= 2:
        for a, b in zip(llenos, llenos[1:]):
            dist = cs[b]['km'] - cs[a]['km']; lit = sum(c['litros'] for c in cs[a + 1:b + 1]); mon = sum(c['monto'] or 0 for c in cs[a + 1:b + 1])
            if dist > 0 and lit > 0: out.append(dict(fin=cs[b]['id'], fecha=cs[b]['fecha'], dist=dist, litros=lit, monto=mon, kml=dist / lit, metodo='Tanque lleno'))
    else:
        for a, b in zip(cs, cs[1:]):
            dist = b['km'] - a['km']
            if dist > 0 and b['litros'] > 0: out.append(dict(fin=b['id'], fecha=b['fecha'], dist=dist, litros=b['litros'], monto=b['monto'] or 0, kml=dist / b['litros'], metodo='Entre cargas'))
    td, tl = sum(s['dist'] for s in out), sum(s['litros'] for s in out)
    for s in out:   # anomalía: rendimiento > 20 % abajo del promedio del resto de los tramos del vehículo
        od, ol = td - s['dist'], tl - s['litros']
        s['ref'] = od / ol if len(out) >= 3 and ol > 0 else None
        s['anomalia'] = bool(s['ref'] and s['kml'] < (1 - ANOMALIA) * s['ref'])
        s['caida'] = (1 - s['kml'] / s['ref']) * 100 if s['ref'] else None
    return out

def intervalos(con, vid=None):
    I = {r[0]: (r[1], r[2]) for r in con.execute('SELECT categoria, km, meses FROM servicio_intervalos')}
    if vid:
        for r in con.execute('SELECT categoria, km, meses FROM vehiculo_intervalos WHERE vehiculo_id=?', (vid,)): I[r[0]] = (r[1], r[2])
    return {k: v for k, v in I.items() if v[0] or v[1]}

def estado_serv(km_rest, dias):
    if (km_rest is not None and km_rest < 0) or (dias is not None and dias < 0): return 'vencido'
    if (km_rest is not None and km_rest <= PROX_KM) or (dias is not None and dias <= PROX_DIAS): return 'proximo'
    return 'aldia'

def servicios(con, vid, kmact=None):
    """Próximos servicios por categoría: último servicio, próximo km/fecha (capturado o calculado con el intervalo), faltantes y estado."""
    I = intervalos(con, vid); h = hoy(); out = []
    ult = {}
    for r in con.execute('SELECT * FROM mantenimientos WHERE vehiculo_id=? ORDER BY fecha, id', (vid,)): ult[r['categoria']] = r
    for cat in [c for c in CATS_MANT if c in ult or c in I]:
        r = ult.get(cat); iv = I.get(cat, (None, None))
        pk, pf, origen = (r['prox_km'], _f(r['prox_fecha']), 'capturado') if r else (None, None, None)
        if r and pk is None and pf is None and (iv[0] or iv[1]):   # sin próximo capturado: se calcula con el intervalo
            pk = (r['km'] + iv[0]) if (iv[0] and r['km'] is not None) else None
            pf = add_meses(_f(r['fecha']), iv[1]) if (iv[1] and _f(r['fecha'])) else None; origen = 'intervalo'
        if not r:
            out.append(dict(categoria=cat, ultimo=None, prox_km=None, prox_fecha=None, km_rest=None, dias=None, estado='sin', intervalo=iv, origen=None)); continue
        if pk is None and pf is None: continue   # servicio sin programación (p. ej. correctivo de carrocería)
        kr = (pk - kmact) if (pk is not None and kmact is not None) else None
        dd = (pf - h).days if pf else None
        out.append(dict(categoria=cat, ultimo=r, prox_km=pk, prox_fecha=pf.isoformat() if pf else None, km_rest=kr, dias=dd, estado=estado_serv(kr, dd), intervalo=iv, origen=origen))
    return sorted(out, key=urgencia)

def urgencia(s):
    e = EST_SERV[s['estado']][2]
    r = min([x for x in ((s['km_rest'] / PROX_KM) if s['km_rest'] is not None else None, (s['dias'] / PROX_DIAS) if s['dias'] is not None else None) if x is not None] or [99])
    return (e, r)

def mes_actual(): return ahora_mx().strftime('%Y-%m')
def ultimos_meses(n=6):
    d = hoy().replace(day=1); out = []
    for i in range(n - 1, -1, -1): out.append(add_meses(d, -i).strftime('%Y-%m'))
    return out
def etq_mes(m): return MESES[int(m[5:7]) - 1] + ' ' + m[2:4]

def resumen_vehiculo(con, v, mes=None):
    mes = mes or mes_actual(); vid = v['id']
    cargas = con.execute('SELECT * FROM cargas_combustible WHERE vehiculo_id=? ORDER BY fecha, km, id', (vid,)).fetchall()
    segs = segmentos(cargas); L = lecturas(con, vid); ka = km_actual(con, vid, L)
    td, tl, tm = sum(s['dist'] for s in segs), sum(s['litros'] for s in segs), sum(s['monto'] for s in segs)
    kml = td / tl if tl else None
    enmes = [x for x in L if x[0][:7] == mes]; antes = [x for x in L if x[0][:7] < mes]
    km_mes = (max(x[1] for x in enmes) - (antes[-1][1] if antes else min(x[1] for x in enmes))) if enmes else 0
    gasto = {}
    for c in cargas: gasto[c['fecha'][:7]] = gasto.get(c['fecha'][:7], 0) + (c['monto'] or 0)
    mant_mes = con.execute("SELECT COALESCE(SUM(costo),0) FROM mantenimientos WHERE vehiculo_id=? AND substr(fecha,1,7)=?", (vid, mes)).fetchone()[0]
    serv = servicios(con, vid, ka[1] if ka else None)
    return dict(v=v, cargas=cargas, segs=segs, kml=kml, l100=(100 / kml) if kml else None, costo_km=(tm / td) if td else None, km_actual=ka,
                km_mes=max(km_mes, 0), gasto_mes=gasto.get(mes, 0), litros_mes=sum(c['litros'] for c in cargas if c['fecha'][:7] == mes), gasto=gasto,
                mant_mes=mant_mes, anomalias=[s for s in segs if s['anomalia']], servicios=serv,
                alertas=sum(1 for c in cargas if c['km_alerta'] or c['litros_alerta']), nserv={k: sum(1 for s in serv if s['estado'] == k) for k in EST_SERV})

# ---------- SVG ligero ----------
def svg_barras(etqs, vals, alto=150, color='#111', fmt='${:,.0f}'):
    w, pad, n = 340, 26, max(len(vals), 1); mx = max([x for x in vals if x] or [1]); bw = (w - 10) / n
    p = [f'<svg viewBox="0 0 {w} {alto + pad + 14}" width="100%" role="img" style="display:block;max-width:560px">']
    for i, (e, x) in enumerate(zip(etqs, vals)):
        hgt = (x or 0) / mx * alto; xx = 5 + i * bw + bw * .18; ww = bw * .64
        p.append(f'<rect x="{xx:.1f}" y="{14 + alto - hgt:.1f}" width="{ww:.1f}" height="{max(hgt, 1):.1f}" rx="5" fill="{color if i == n - 1 else "#c7c7cc"}"/>')
        p.append(f'<text x="{xx + ww / 2:.1f}" y="{10 + alto - hgt:.1f}" font-size="9.5" text-anchor="middle" fill="#3a3a3c">{escape(fmt.format(x or 0))}</text>')
        p.append(f'<text x="{xx + ww / 2:.1f}" y="{alto + pad + 6}" font-size="10" text-anchor="middle" fill="#8e8e93">{escape(e)}</text>')
    return Markup(''.join(p) + '</svg>')

def svg_linea(etqs, vals, alto=140, color='#2563eb', marcas=None, fmt='{:.1f}'):
    pts = [(i, x) for i, x in enumerate(vals) if x is not None]
    w = 340
    if len(pts) < 2: return Markup('<p class="muted" style="margin:6px 0">Aún no hay suficientes cargas para la gráfica.</p>')
    lo, hi = min(x for _, x in pts), max(x for _, x in pts); lo, hi = lo - (hi - lo) * .15 - .5, hi + (hi - lo) * .15 + .5
    n = len(vals); X = lambda i: 14 + i * (w - 28) / max(n - 1, 1); Y = lambda x: 12 + (hi - x) / (hi - lo) * alto
    p = [f'<svg viewBox="0 0 {w} {alto + 40}" width="100%" role="img" style="display:block;max-width:560px">']
    for k in range(3):
        yv = lo + (hi - lo) * (k + .5) / 3; p.append(f'<line x1="10" x2="{w - 6}" y1="{Y(yv):.1f}" y2="{Y(yv):.1f}" stroke="#ececf0"/><text x="{w - 6}" y="{Y(yv) - 3:.1f}" font-size="9" text-anchor="end" fill="#aeaeb2">{escape(fmt.format(yv))}</text>')
    p.append('<polyline fill="none" stroke="%s" stroke-width="2.2" stroke-linejoin="round" points="%s"/>' % (color, ' '.join(f'{X(i):.1f},{Y(x):.1f}' for i, x in pts)))
    for i, x in pts:
        an = marcas and marcas[i]
        p.append(f'<circle cx="{X(i):.1f}" cy="{Y(x):.1f}" r="{4.5 if an else 2.6}" fill="{"#c62828" if an else color}"/>')
    step = max(1, n // 6)
    for i, e in enumerate(etqs):
        if i % step == 0 or i == n - 1: p.append(f'<text x="{X(i):.1f}" y="{alto + 32}" font-size="9.5" text-anchor="middle" fill="#8e8e93">{escape(e)}</text>')
    return Markup(''.join(p) + '</svg>')

def svg_spark(vals, marcas=None, color='#2563eb'):
    pts = [(i, x) for i, x in enumerate(vals) if x is not None]
    if len(pts) < 2: return Markup('')
    w, h = 120, 30; lo, hi = min(x for _, x in pts), max(x for _, x in pts); hi = hi if hi > lo else lo + 1
    X = lambda i: 2 + i * (w - 4) / max(len(vals) - 1, 1); Y = lambda x: 3 + (hi - x) / (hi - lo) * (h - 6)
    s = f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" style="display:block"><polyline fill="none" stroke="{color}" stroke-width="1.8" points="' + ' '.join(f'{X(i):.1f},{Y(x):.1f}' for i, x in pts) + '"/>'
    for i, x in pts:
        if marcas and marcas[i]: s += f'<circle cx="{X(i):.1f}" cy="{Y(x):.1f}" r="3" fill="#c62828"/>'
    return Markup(s + '</svg>')

# ---------- demo ----------
def demo(c, up):
    """Solo datos de EJEMPLO (BD recién sembrada): capacidades de tanque, ~2 meses de cargas en 6 vehículos
    (una con rendimiento anómalo), mantenimientos con próximos servicios vencidos / próximos / al día."""
    # solo en una BD recién creada por seed.py (marca app_meta.demo_flota='pendiente'): nunca en una BD existente con datos reales
    m = c.execute("SELECT v FROM app_meta WHERE k='demo_flota'").fetchone()
    if not m or m[0] != 'pendiente' or not c.execute('SELECT 1 FROM ordenes WHERE ejemplo=1 LIMIT 1').fetchone(): return
    c.execute("UPDATE app_meta SET v='hecho' WHERE k='demo_flota'")
    if c.execute('SELECT 1 FROM cargas_combustible LIMIT 1').fetchone(): return
    import random
    rnd = random.Random(23); h = hoy()
    vs = c.execute('SELECT id, numero, cuadrilla_id, personal_id FROM vehiculos ORDER BY numero').fetchall()
    for i, v in enumerate(vs):
        c.execute('UPDATE vehiculos SET tanque_litros=COALESCE(tanque_litros, ?) WHERE id=?', ([60, 70, 80, 55, 65][i % 5], v[0]))
    precios = {'Gasolina Magna': 23.9, 'Gasolina Premium': 25.6, 'Diésel': 25.1}
    for v in vs[:6]:
        vid, num = v[0], v[1]
        tanque = c.execute('SELECT tanque_litros FROM vehiculos WHERE id=?', (vid,)).fetchone()[0]
        tipo = 'Diésel' if num in ('04', '06') else ('Gasolina Premium' if num == '05' else 'Gasolina Magna')
        kml = {'01': 10.5, '02': 9.2, '03': 11.0, '04': 8.4, '05': 12.1, '06': 8.9}.get(num, 10)
        chk = c.execute('SELECT MIN(fecha), MIN(km) FROM checklists WHERE vehiculo_id=? AND km IS NOT NULL', (vid,)).fetchone()
        fin_f = _f(chk[0]) - dt.timedelta(days=1) if chk and chk[0] else h - dt.timedelta(days=1)
        fin_km = (chk[1] - rnd.randint(60, 160)) if chk and chk[1] else rnd.randint(30000, 90000)
        # se arma hacia atrás: ~60 días, carga cada 3–5 días
        fechas, d = [], fin_f
        while d > h - dt.timedelta(days=62): fechas.append(d); d -= dt.timedelta(days=rnd.randint(3, 5))
        fechas.reverse()
        dist = [rnd.randint(260, 420) for _ in fechas]; km = fin_km - sum(dist[1:])
        quien = c.execute('SELECT id, nombre FROM tecnicos WHERE (cuadrilla_id=? OR id=?) AND ejemplo=1 ORDER BY id', (v[2], v[3])).fetchall() or [(None, 'Ejemplo')]
        for j, f in enumerate(fechas):
            if j: km += dist[j]
            rend = kml * rnd.uniform(.93, 1.07)
            if num == '03' and j == len(fechas) - 3: rend = kml * .62   # anomalía de ejemplo: ~38 % menos rendimiento
            lit = round(min(dist[j] / rend, tanque * .95), 2) if j else round(tanque * .6, 2)
            lleno = 0 if (j and rnd.random() < .15 and not (num == '03' and j >= len(fechas) - 4)) else 1
            pr = round(precios[tipo] + rnd.uniform(-.4, .4), 2); p = quien[j % len(quien)]
            c.execute('''INSERT INTO cargas_combustible(vehiculo_id,personal_id,usuario,fecha,litros,km,monto,precio_litro,tipo,tanque_lleno,estacion,ejemplo)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,1)''', (vid, p[0], p[1], f.isoformat() + 'T%02d:%02d' % (rnd.randint(7, 19), rnd.randint(0, 59)), lit, km, round(lit * pr, 2), pr, tipo, lleno,
                                                     rnd.choice(['Pemex Ejemplo Norte', 'G500 Ejemplo', 'BP Ejemplo Centro', 'Oxxo Gas Ejemplo'])))
        ult = c.execute('SELECT fecha, km FROM checklists WHERE vehiculo_id=? AND km IS NOT NULL ORDER BY fecha DESC, id DESC LIMIT 1', (vid,)).fetchone()
        if ult and ult[1] > km:   # última carga coherente con el odómetro del checklist más reciente
            k2 = ult[1] + rnd.randint(20, 60); lit = round(min((k2 - km) / (kml * rnd.uniform(.95, 1.05)), tanque * .95), 2); pr = round(precios[tipo] + rnd.uniform(-.3, .3), 2)
            c.execute('''INSERT INTO cargas_combustible(vehiculo_id,personal_id,usuario,fecha,litros,km,monto,precio_litro,tipo,tanque_lleno,estacion,ejemplo)
                VALUES(?,?,?,?,?,?,?,?,?,1,?,1)''', (vid, quien[0][0], quien[0][1], ult[0] + 'T18:%02d' % rnd.randint(0, 59), lit, k2, round(lit * pr, 2), pr, tipo, 'Pemex Ejemplo Norte'))
    # mantenimientos (km relativos al kilometraje actual)
    def kmv(vid):
        r = c.execute('SELECT MAX(km) FROM (SELECT km FROM cargas_combustible WHERE vehiculo_id=? UNION ALL SELECT km FROM checklists WHERE vehiculo_id=?)', (vid, vid)).fetchone()[0]
        return r or 40000
    M = [  # (vehículo, días atrás, km atrás, tipo, categoría, descripción, taller, costo, intervalo->próximo)
        ('01', 120, 4400, 'Preventivo', 'Cambio de aceite', 'Aceite sintético 5W-30 y filtro de aceite', 'Taller Ejemplo Norte', 1450, True),
        ('01', 200, 15000, 'Preventivo', 'Afinación', 'Bujías, filtro de aire y de gasolina, limpieza de inyectores', 'Taller Ejemplo Norte', 3900, True),
        ('02', 150, 6100, 'Preventivo', 'Cambio de aceite', 'Aceite 5W-30 y filtro', 'Lubricentro Ejemplo', 1290, True),
        ('02', 390, 21500, 'Preventivo', 'Afinación', 'Afinación mayor', 'Taller Ejemplo Sur', 4200, True),
        ('03', 40, 1800, 'Preventivo', 'Cambio de aceite', 'Aceite 5W-30 y filtro', 'Lubricentro Ejemplo', 1290, True),
        ('03', 25, 900, 'Correctivo', 'Frenos', 'Cambio de balatas delanteras por desgaste', 'Frenos Ejemplo', 2350, True),
        ('04', 170, 9300, 'Preventivo', 'Filtros', 'Filtro de aire, combustible y cabina (diésel)', 'Diesel Ejemplo', 1850, True),
        ('04', 60, 2500, 'Correctivo', 'Eléctrico', 'Reparación de alternador', 'Electro Ejemplo', 2800, False),
        ('05', 175, 3000, 'Preventivo', 'Verificación', 'Verificación vehicular semestral', 'Verificentro Ejemplo', 650, True),
        ('05', 6, 180, 'Correctivo', 'Llantas', 'Reparación de ponchadura y balanceo de las 4 llantas', 'Llantera Ejemplo', 480, False),
        ('06', 80, 3900, 'Preventivo', 'Cambio de aceite', 'Aceite 15W-40 diésel y filtro', 'Diesel Ejemplo', 1980, True),
        ('06', 700, 30000, 'Preventivo', 'Batería', 'Batería nueva 24 meses', 'Baterías Ejemplo', 2600, True),
    ]
    I = intervalos(c)
    for num, dias, kma, tipo, cat, des, taller, costo, prox in M:
        r = c.execute('SELECT id FROM vehiculos WHERE numero=?', (num,)).fetchone()
        if not r: continue
        f = h - dt.timedelta(days=dias); k = kmv(r[0]) - kma; iv = I.get(cat, (None, None))
        pk = k + iv[0] if prox and iv[0] else None; pf = add_meses(f, iv[1]).isoformat() if prox and iv[1] else None
        c.execute('INSERT INTO mantenimientos(vehiculo_id,fecha,km,tipo,categoria,descripcion,taller,costo,prox_km,prox_fecha,registrado_por,ejemplo) VALUES(?,?,?,?,?,?,?,?,?,?,?,1)',
                  (r[0], f.isoformat(), k, tipo, cat, 'EJEMPLO: ' + des, taller, costo, pk, pf, 'Datos de ejemplo'))

# ---------- rutas ----------
def registrar(app, q, db, UP):
    cc = os.path.join(UP, SUB_C); cm = os.path.join(UP, SUB_M)
    for x in (cc, cm): os.makedirs(x, exist_ok=True)
    app.jinja_env.globals.update(EST_SERV=EST_SERV, FL_TIPOS=TIPOS_COMB, FL_CATS=CATS_MANT, FL_TMANT=TIPOS_MANT, PROX_KM=PROX_KM, PROX_DIAS=PROX_DIAS)
    app.jinja_env.globals['fl_servicios'] = lambda vid: servicios(db(), vid, (km_actual(db(), vid) or (None, None))[1])
    app.jinja_env.globals['fl_km_actual'] = lambda vid: km_actual(db(), vid)
    import auth_mod as AU, sitio_fotos as SF

    def yo(): return getattr(g, 'user', None)
    def ver_todo(): return PERM.can('combustible.ver_todo')
    def vehiculos_act(): return q(f"SELECT v.*, {__import__('vehiculo_adj').asignado_sql('v.')} asignado FROM vehiculos v WHERE COALESCE(v.activo,1)=1 ORDER BY v.numero")
    def asignado_a_mi(vs):
        u = yo()
        if not u: return None, None
        p = next((v['id'] for v in vs if v['asignacion_tipo'] == 'Persona' and v['personal_id'] == u['id']), None)
        cu = next((v['id'] for v in vs if u['cuadrilla_id'] and v['asignacion_tipo'] != 'Persona' and v['cuadrilla_id'] == u['cuadrilla_id']), None)
        return p, cu
    def ult_lectura(vid):
        k = km_actual(db(), vid); return dict(km=k[1], fecha=k[0][:10], fuente=k[2]) if k else None
    def num(s, ent=False):
        s = (s or '').replace(',', '').replace('$', '').strip()
        if not s: return None
        try: v = int(s) if ent else float(s)
        except ValueError: return 'x'
        return v if v >= 0 else 'x'

    # ---- Cargas de combustible ----
    @app.route('/combustible')
    def combustible():
        u = yo(); todas = ver_todo() and (request.args.get('ver') == 'todas' or not u)
        w, a = [], []
        if not todas: w.append('c.personal_id=?'); a.append(u['id'] if u else -1)
        vf = request.args.get('vehiculo', type=int); de, ha = request.args.get('desde') or '', request.args.get('hasta') or ''
        if vf: w.append('c.vehiculo_id=?'); a.append(vf)
        if de: w.append('substr(c.fecha,1,10)>=?'); a.append(de)
        if ha: w.append('substr(c.fecha,1,10)<=?'); a.append(ha)
        if request.args.get('alertas'): w.append('(c.km_alerta=1 OR c.litros_alerta=1)')
        rows = q(f"""SELECT c.*, v.numero, v.tanque_litros FROM cargas_combustible c JOIN vehiculos v ON v.id=c.vehiculo_id WHERE {' AND '.join(w) or '1=1'}
                    ORDER BY c.fecha DESC, c.id DESC LIMIT 400""", a)
        # rendimiento por carga (tramo que termina en esa carga) y anomalías
        seg = {}
        for vid in {r['vehiculo_id'] for r in rows}:
            for s in segmentos(q('SELECT * FROM cargas_combustible WHERE vehiculo_id=? ORDER BY fecha, km, id', (vid,))): seg[s['fin']] = s
        mes = mes_actual(); m_rows = [r for r in rows if r['fecha'][:7] == mes]
        tot = dict(n=len(rows), litros=sum(r['litros'] for r in rows), monto=sum(r['monto'] for r in rows), mes_monto=sum(r['monto'] for r in m_rows), mes_litros=sum(r['litros'] for r in m_rows))
        return render_template('combustible.html', rows=rows, seg=seg, todas=todas, tot=tot, vs=vehiculos_act(), vf=vf, de=de, ha=ha, msg=request.args.get('msg'),
                               alertas=request.args.get('alertas'), puede_todo=ver_todo(), yo_id=u['id'] if u else None, hoy=hoy().isoformat())

    def form_carga(err=None, avisos=None):
        vs = vehiculos_act(); p, cu = asignado_a_mi(vs)
        F = request.form if request.method == 'POST' else {}
        sel = request.form.get('vehiculo_id', type=int) or request.args.get('vehiculo', type=int) or p or cu
        info = {v['id']: dict(tanque=v['tanque_litros'], ult=ult_lectura(v['id']),
                              tipo=(q('SELECT tipo FROM cargas_combustible WHERE vehiculo_id=? ORDER BY fecha DESC, id DESC LIMIT 1', (v['id'],), one=True) or {'tipo': None})['tipo']) for v in vs}
        return render_template('combustible_form.html', vs=vs, sel=sel, propio=p, cuad=cu, info=info, F=F, err=err, avisos=avisos or [], ahora=ahora_mx().strftime('%Y-%m-%dT%H:%M'))

    @app.route('/combustible/nueva', methods=['GET', 'POST'])
    def combustible_nueva():
        if request.method == 'GET': return form_carga()
        F = request.form; err, avisos = [], []
        vid = F.get('vehiculo_id', type=int); v = q('SELECT * FROM vehiculos WHERE id=? AND COALESCE(activo,1)=1', (vid,), one=True) if vid else None
        if not v: err.append('Selecciona el vehículo')
        lit, km, monto = num(F.get('litros')), num(F.get('km'), True), num(F.get('monto'))
        if lit in (None, 'x') or lit <= 0 or lit > 500: err.append('Captura los litros (número mayor a 0)'); lit = None
        if km in (None, 'x') or km > 9_999_999: err.append('Captura el kilometraje (número entero)'); km = None
        if monto in (None, 'x') or monto <= 0: err.append('Captura el monto en pesos'); monto = None
        tipo = F.get('tipo') if F.get('tipo') in TIPOS_COMB else None
        if not tipo: err.append('Selecciona el tipo de combustible')
        try: fecha = dt.datetime.strptime((F.get('fecha') or '')[:16], '%Y-%m-%dT%H:%M')
        except ValueError: fecha = None; err.append('Fecha y hora inválidas')
        if fecha and fecha > ahora_mx() + dt.timedelta(minutes=10): err.append('La fecha no puede ser futura')
        la, ka = 0, 0; ult = ult_lectura(vid) if v else None
        if v and lit and v['tanque_litros'] and lit > v['tanque_litros']:
            la = 1
            if not F.get('confirma_litros'): avisos.append(('litros', f'Los litros ({lit:g}) superan la capacidad del tanque del vehículo {v["numero"]} ({v["tanque_litros"]:g} L).'))
        if v and km is not None and ult and km < ult['km']:
            ka = 1
            if not F.get('confirma_km'): avisos.append(('km', f'El kilometraje es menor al último registrado ({ult["km"]:,} km el {ult["fecha"]}, {ult["fuente"].lower()}).'))
        foto = request.files.get('foto_ticket'); fname = None
        if err or avisos: return form_carga(err, avisos)
        if foto and foto.filename:
            try: fname = SF.guardar_imagen(foto, cc)
            except Exception: return form_carga(['La foto del ticket no es una imagen válida'])
        u = yo()
        db().execute('''INSERT INTO cargas_combustible(vehiculo_id,personal_id,usuario,fecha,litros,km,monto,precio_litro,tipo,tanque_lleno,foto_ticket,estacion,notas,km_anterior,km_alerta,litros_alerta)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (vid, u['id'] if u else None, AU.nombre_actual(), fecha.strftime('%Y-%m-%dT%H:%M'), lit, km, round(monto, 2), round(monto / lit, 3), tipo,
                                                     1 if F.get('tanque_lleno') else 0, fname, (F.get('estacion') or '').strip()[:120] or None, (F.get('notas') or '').strip()[:500] or None,
                                                     ult['km'] if ult else None, ka, la))
        db().commit()
        m = f'Carga registrada: {lit:g} L · ${monto:,.2f} · ${monto / lit:,.2f}/L' + (' · marcada para revisión' if (ka or la) else '')
        return redirect(url_for('combustible', msg=m))

    @app.route('/combustible/<int:cid>/borrar', methods=['POST'])
    def combustible_borrar(cid):
        r = q('SELECT * FROM cargas_combustible WHERE id=?', (cid,), one=True) or abort(404)
        u = yo(); propia_hoy = u and r['personal_id'] == u['id'] and not r['ejemplo'] and (r['creado'] or '')[:10] == hoy().isoformat()
        if not (ver_todo() or propia_hoy): abort(403)
        if r['foto_ticket']: SF_borrar(cc, r['foto_ticket'])
        db().execute('DELETE FROM cargas_combustible WHERE id=?', (cid,)); db().commit()
        return redirect(url_for('combustible', msg='Carga eliminada', ver=request.args.get('ver')))

    def SF_borrar(carpeta, n):
        for x in (n, 't_' + n):
            try: os.remove(os.path.join(carpeta, x))
            except OSError: pass

    # ---- Bitácora de mantenimiento ----
    @app.route('/mantenimiento')
    def mantenimiento():
        vf = request.args.get('vehiculo', type=int); cat = request.args.get('categoria') or ''
        w, a = [], []
        if vf: w.append('m.vehiculo_id=?'); a.append(vf)
        if cat in CATS_MANT: w.append('m.categoria=?'); a.append(cat)
        rows = q(f"""SELECT m.*, v.numero, (SELECT COUNT(*) FROM mantenimiento_adjuntos x WHERE x.mantenimiento_id=m.id) nadj FROM mantenimientos m JOIN vehiculos v ON v.id=m.vehiculo_id
                    WHERE {' AND '.join(w) or '1=1'} ORDER BY m.fecha DESC, m.id DESC LIMIT 400""", a)
        adj = {}
        for x in q(f"SELECT * FROM mantenimiento_adjuntos WHERE mantenimiento_id IN ({','.join(str(r['id']) for r in rows) or 'NULL'}) ORDER BY id"): adj.setdefault(x['mantenimiento_id'], []).append(x)
        v = q('SELECT * FROM vehiculos WHERE id=?', (vf,), one=True) if vf else None
        ka = km_actual(db(), vf) if vf else None
        return render_template('mantenimiento.html', rows=rows, adj=adj, vs=vehiculos_act(), vf=vf, v=v, cat=cat, ka=ka,
                               serv=servicios(db(), vf, ka[1] if ka else None) if vf else None, total=sum(r['costo'] or 0 for r in rows), msg=request.args.get('msg'))

    def form_mant(r, err=None):
        vs = vehiculos_act()
        iv = {v['id']: intervalos(db(), v['id']) for v in vs}
        kmact = {v['id']: (km_actual(db(), v['id']) or (None, None))[1] for v in vs}
        return render_template('mantenimiento_form.html', r=r, vs=vs, iv=iv, kmact=kmact, err=err,
                               adj=q('SELECT * FROM mantenimiento_adjuntos WHERE mantenimiento_id=? ORDER BY id', (r['id'],)) if r.get('id') else [])

    def guardar_adjuntos(mid):
        malos = []
        for fs in request.files.getlist('adjuntos'):
            if not fs or not fs.filename: continue
            cab = fs.stream.read(5); fs.stream.seek(0)
            if cab == b'%PDF-':
                n = uuid.uuid4().hex + '.pdf'; fs.save(os.path.join(cm, n)); es = 1
            else:
                try: n = SF.guardar_imagen(fs, cm); es = 0
                except Exception: malos.append(fs.filename); continue
            db().execute('INSERT INTO mantenimiento_adjuntos(mantenimiento_id,archivo,nombre,es_pdf) VALUES(?,?,?,?)', (mid, n, os.path.basename(fs.filename)[:120], es))
        return malos

    @app.route('/mantenimiento/nuevo', methods=['GET', 'POST'])
    @app.route('/mantenimiento/<int:mid>/editar', methods=['GET', 'POST'])
    def mantenimiento_form(mid=None):
        r = dict(q('SELECT * FROM mantenimientos WHERE id=?', (mid,), one=True) or abort(404)) if mid else \
            {'vehiculo_id': request.args.get('vehiculo', type=int), 'fecha': hoy().isoformat(), 'tipo': 'Preventivo', 'categoria': request.args.get('categoria') or ''}
        if request.method == 'GET': return form_mant(r)
        F = request.form; err = []
        d = dict(vehiculo_id=F.get('vehiculo_id', type=int), fecha=(F.get('fecha') or '')[:10], km=num(F.get('km'), True), tipo=F.get('tipo'), categoria=F.get('categoria'),
                 descripcion=(F.get('descripcion') or '').strip()[:2000] or None, taller=(F.get('taller') or '').strip()[:160] or None, costo=num(F.get('costo')),
                 prox_km=num(F.get('prox_km'), True), prox_fecha=(F.get('prox_fecha') or '')[:10] or None)
        if not d['vehiculo_id'] or not q('SELECT 1 FROM vehiculos WHERE id=?', (d['vehiculo_id'],), one=True): err.append('Selecciona el vehículo')
        if not _f(d['fecha']): err.append('Captura la fecha')
        elif _f(d['fecha']) > hoy(): err.append('La fecha del servicio no puede ser futura')
        if d['tipo'] not in TIPOS_MANT: err.append('Selecciona el tipo (Preventivo / Correctivo)')
        if d['categoria'] not in CATS_MANT: err.append('Selecciona la categoría')
        for k, l in (('km', 'Kilometraje'), ('costo', 'Costo'), ('prox_km', 'Próximo servicio (km)')):
            if d[k] == 'x': err.append(f'{l}: número inválido'); d[k] = None
        if d['prox_fecha'] and not _f(d['prox_fecha']): err.append('Próximo servicio (fecha) inválida')
        if d['prox_km'] is not None and d['km'] is not None and d['prox_km'] <= d['km']: err.append('El próximo servicio (km) debe ser mayor al kilometraje del servicio')
        if d['prox_fecha'] and _f(d['fecha']) and _f(d['prox_fecha']) and _f(d['prox_fecha']) <= _f(d['fecha']): err.append('La fecha del próximo servicio debe ser posterior a la del servicio')
        if err: r.update(d); return form_mant(r, err)
        con = db()
        if mid: con.execute(f"UPDATE mantenimientos SET {', '.join(k + '=?' for k in d)} WHERE id=?", list(d.values()) + [mid])
        else: mid = con.execute(f"INSERT INTO mantenimientos({','.join(d)}, registrado_por) VALUES({','.join('?' * len(d))},?)", list(d.values()) + [AU.nombre_actual()]).lastrowid
        malos = guardar_adjuntos(mid); con.commit()
        return redirect(url_for('mantenimiento', vehiculo=d['vehiculo_id'], msg='Servicio guardado' + ('; adjuntos rechazados (solo PDF o imagen): ' + ', '.join(malos) if malos else '')))

    @app.route('/mantenimiento/<int:mid>/borrar', methods=['POST'])
    def mantenimiento_borrar(mid):
        r = q('SELECT * FROM mantenimientos WHERE id=?', (mid,), one=True) or abort(404)
        for x in q('SELECT archivo FROM mantenimiento_adjuntos WHERE mantenimiento_id=?', (mid,)): SF_borrar(cm, x['archivo'])
        db().execute('DELETE FROM mantenimientos WHERE id=?', (mid,)); db().commit()
        return redirect(url_for('mantenimiento', vehiculo=r['vehiculo_id'], msg='Servicio eliminado'))

    @app.route('/mantenimiento/adjuntos/<int:aid>/borrar', methods=['POST'])
    def mantenimiento_adj_borrar(aid):
        x = q('SELECT * FROM mantenimiento_adjuntos WHERE id=?', (aid,), one=True) or abort(404)
        SF_borrar(cm, x['archivo']); db().execute('DELETE FROM mantenimiento_adjuntos WHERE id=?', (aid,)); db().commit()
        return redirect(f'/mantenimiento/{x["mantenimiento_id"]}/editar')

    @app.route('/mantenimiento/intervalos', methods=['GET', 'POST'])
    def mantenimiento_intervalos():
        vf = request.values.get('vehiculo', type=int)
        if request.method == 'POST':
            con = db()
            for cat in CATS_MANT:
                k, m = num(request.form.get('km_' + cat), True), num(request.form.get('me_' + cat), True)
                k = None if k in ('x', 0) else k; m = None if m in ('x', 0) else m
                if vf:
                    con.execute('DELETE FROM vehiculo_intervalos WHERE vehiculo_id=? AND categoria=?', (vf, cat))
                    if request.form.get('propio_' + cat): con.execute('INSERT INTO vehiculo_intervalos VALUES(?,?,?,?)', (vf, cat, k, m))
                else: con.execute('INSERT OR REPLACE INTO servicio_intervalos VALUES(?,?,?)', (cat, k, m))
            con.commit()
            return redirect(url_for('mantenimiento_intervalos', vehiculo=vf or None, msg='Intervalos guardados'))
        glob = {r['categoria']: r for r in q('SELECT * FROM servicio_intervalos')}
        prop = {r['categoria']: r for r in q('SELECT * FROM vehiculo_intervalos WHERE vehiculo_id=?', (vf,))} if vf else {}
        return render_template('mantenimiento_intervalos.html', glob=glob, prop=prop, vs=vehiculos_act(), vf=vf, msg=request.args.get('msg'))

    # ---- Dashboard de vehículos ----
    @app.route('/vehiculos/dashboard')
    def vehiculos_dashboard():
        import vehiculo_adj as VA
        con = db(); mes = mes_actual(); meses = ultimos_meses(6)
        vs = q(f"SELECT v.*, {VA.asignado_sql('v.')} asignado, {VA.seg_sql('v.')} seguro_estado FROM vehiculos v WHERE COALESCE(v.activo,1)=1 ORDER BY v.numero")
        R = [resumen_vehiculo(con, v, mes) for v in vs]
        serv = sorted([dict(s, v=r['v'], km_act=r['km_actual']) for r in R for s in r['servicios'] if s['estado'] in ('vencido', 'proximo')], key=urgencia)
        gasto_m = [sum(r['gasto'].get(m, 0) for r in R) for m in meses]
        rend_m = []
        for m in meses:
            ss = [s for r in R for s in r['segs'] if s['fecha'][:7] == m]; tl = sum(s['litros'] for s in ss)
            rend_m.append(sum(s['dist'] for s in ss) / tl if tl else None)
        td = sum(s['dist'] for r in R for s in r['segs']); tl = sum(s['litros'] for r in R for s in r['segs'])
        anom = sorted([dict(s, v=r['v']) for r in R for s in r['anomalias']], key=lambda s: s['fecha'], reverse=True)
        desde = (hoy() - dt.timedelta(days=14)).isoformat()
        inc = q('''SELECT c.id, c.fecha, v.numero, t.nombre, r.rutina, r.item, r.comentario FROM checklist_respuestas r JOIN checklists c ON c.id=r.checklist_id
                   LEFT JOIN vehiculos v ON v.id=c.vehiculo_id LEFT JOIN tecnicos t ON t.id=c.personal_id WHERE r.cumple=0 AND c.fecha>=? ORDER BY c.fecha DESC, c.id DESC LIMIT 30''', (desde,))
        kpi = dict(gasto_mes=sum(r['gasto_mes'] for r in R), litros_mes=sum(r['litros_mes'] for r in R), km_mes=sum(r['km_mes'] for r in R), mant_mes=sum(r['mant_mes'] for r in R),
                   kml=td / tl if tl else None, vencidos=sum(1 for s in serv if s['estado'] == 'vencido'), proximos=sum(1 for s in serv if s['estado'] == 'proximo'),
                   seguros=sum(1 for v in vs if v['seguro_estado'] in ('proxima', 'vencida')), anomalias=len(anom))
        spark = {r['v']['id']: svg_spark([s['kml'] for s in r['segs'][-10:]], [s['anomalia'] for s in r['segs'][-10:]]) for r in R}
        return render_template('vehiculos_dashboard.html', R=R, serv=serv, kpi=kpi, anom=anom[:12], inc=inc, spark=spark, mes=etq_mes(mes),
                               seguros=[v for v in vs if v['seguro_estado'] in ('proxima', 'vencida')],
                               g_gasto=svg_barras([etq_mes(m) for m in meses], gasto_m), g_rend=svg_linea([etq_mes(m) for m in meses], rend_m, fmt='{:.1f}'))

    @app.route('/vehiculos/dashboard/<int:vid>')
    def vehiculo_flota(vid):
        import vehiculo_adj as VA
        v = q(f"SELECT v.*, {VA.asignado_sql('v.')} asignado, {VA.seg_sql('v.')} seguro_estado FROM vehiculos v WHERE v.id=?", (vid,), one=True) or abort(404)
        r = resumen_vehiculo(db(), v); meses = ultimos_meses(6); segs = r['segs'][-16:]
        mant = q('SELECT * FROM mantenimientos WHERE vehiculo_id=? ORDER BY fecha DESC, id DESC LIMIT 8', (vid,))
        return render_template('vehiculo_flota.html', r=r, v=v, mant=mant, seg={s['fin']: s for s in r['segs']},
                               g_rend=svg_linea([s['fecha'][8:10] + '/' + s['fecha'][5:7] for s in segs], [s['kml'] for s in segs], marcas=[s['anomalia'] for s in segs]),
                               g_gasto=svg_barras([etq_mes(m) for m in meses], [r['gasto'].get(m, 0) for m in meses]))
