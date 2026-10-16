"""Cliente de la API de SYSCOM (https://developers.syscom.mx/api/v1).

Autenticación OAuth2 client_credentials: POST /oauth/token -> Bearer (válido ~365 días).
Las credenciales NUNCA se guardan en la base de datos ni en el repositorio: se leen de
las variables de entorno SYSCOM_CLIENT_ID / SYSCOM_CLIENT_SECRET (o del archivo .env, ignorado por git).
El token y la fecha de última sincronización se guardan en syscom_estado.json (también ignorado por git).
"""
import os, json, time, datetime as dt, urllib.request, urllib.parse, urllib.error

API = os.environ.get('SYSCOM_API_URL', 'https://developers.syscom.mx/api/v1')
BASE = os.path.dirname(os.path.abspath(__file__))
ENVF = os.path.join(BASE, '.env')
ESTADO = os.environ.get('SYSCOM_STATE_PATH') or os.path.join(BASE, 'syscom_estado.json')
UA = 'ControlOperaciones/1.0'

class SyscomError(Exception): pass

def _leer_env():
    if not os.path.exists(ENVF): return {}
    return dict(l.strip().split('=', 1) for l in open(ENVF, encoding='utf-8') if '=' in l and not l.lstrip().startswith('#'))

def credenciales():
    f = _leer_env()
    cid = os.environ.get('SYSCOM_CLIENT_ID') or f.get('SYSCOM_CLIENT_ID')
    sec = os.environ.get('SYSCOM_CLIENT_SECRET') or f.get('SYSCOM_CLIENT_SECRET')
    return (cid or None), (sec or None)

def origen_credenciales():
    if os.environ.get('SYSCOM_CLIENT_ID'): return 'variables de entorno'
    if _leer_env().get('SYSCOM_CLIENT_ID'): return 'archivo .env'
    return None

def guardar_credenciales(cid, sec):
    """Escribe/actualiza SYSCOM_CLIENT_ID/SECRET en .env (gitignored, permisos 600)."""
    lines = open(ENVF, encoding='utf-8').read().splitlines() if os.path.exists(ENVF) else []
    lines = [l for l in lines if not l.startswith(('SYSCOM_CLIENT_ID=', 'SYSCOM_CLIENT_SECRET='))]
    lines += [f'SYSCOM_CLIENT_ID={cid.strip()}', f'SYSCOM_CLIENT_SECRET={sec.strip()}']
    with open(ENVF, 'w', encoding='utf-8') as fh: fh.write('\n'.join(lines) + '\n')
    os.chmod(ENVF, 0o600)
    est = estado(); est.pop('token', None); est.pop('token_exp', None); est['conexion_ok'] = False; _guardar_estado(est)

def estado():
    try: return json.load(open(ESTADO, encoding='utf-8'))
    except Exception: return {}
def _guardar_estado(e):
    with open(ESTADO, 'w', encoding='utf-8') as fh: json.dump(e, fh, ensure_ascii=False, indent=1)
    try: os.chmod(ESTADO, 0o600)
    except OSError: pass

def _http(method, url, data=None, headers=None, timeout=30):
    req = urllib.request.Request(url, data=data, method=method, headers={'User-Agent': UA, 'Accept': 'application/json', **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: return r.status, r.read()
    except urllib.error.HTTPError as e: return e.code, e.read()
    except urllib.error.URLError as e: raise SyscomError(f'No se pudo conectar con SYSCOM: {e.reason}')

def obtener_token(forzar=False):
    est = estado()
    if not forzar and est.get('token') and est.get('token_exp', 0) > time.time() + 3600: return est['token']
    cid, sec = credenciales()
    if not cid or not sec: raise SyscomError('Sin credenciales: configura SYSCOM_CLIENT_ID y SYSCOM_CLIENT_SECRET')
    body = urllib.parse.urlencode({'grant_type': 'client_credentials', 'client_id': cid, 'client_secret': sec}).encode()
    st, raw = _http('POST', API + '/oauth/token', body, {'Content-Type': 'application/x-www-form-urlencoded'})
    if st != 200:
        msg = {400: 'Datos incompletos o inválidos', 401: 'Credenciales inválidas o cuenta sin acceso a la API', 429: 'Demasiadas solicitudes de token; intenta más tarde'}.get(st, f'Error {st}')
        raise SyscomError(f'SYSCOM rechazó el token: {msg}')
    j = json.loads(raw)
    est.update(token=j['access_token'], token_exp=time.time() + int(j.get('expires_in', 31536000))); _guardar_estado(est)
    return j['access_token']

def get(path, params=None, _retry=True):
    url = API + path + ('?' + urllib.parse.urlencode(params) if params else '')
    st, raw = _http('GET', url, headers={'Authorization': 'Bearer ' + obtener_token()})
    if st == 401 and _retry:
        obtener_token(forzar=True); return get(path, params, False)
    if st == 404: return None
    if st != 200: raise SyscomError(f'SYSCOM respondió {st} en {path}')
    return json.loads(raw)

def probar_conexion():
    """Pide token y hace una consulta mínima. Devuelve (ok, mensaje)."""
    est = estado()
    try:
        obtener_token(forzar=True); get('/marcas')
        est = estado(); est.update(conexion_ok=True, ultima_prueba=_ahora(), ultimo_error=None); _guardar_estado(est)
        return True, 'Conexión correcta con SYSCOM'
    except SyscomError as e:
        est = estado(); est.update(conexion_ok=False, ultima_prueba=_ahora(), ultimo_error=str(e)); _guardar_estado(est)
        return False, str(e)

def buscar_productos(texto, limit=20):
    r = get('/productos', {'busqueda': texto[:120], 'limit': max(10, limit)}) or {}
    return [mapear(p) for p in r.get('productos', [])][:limit]

def producto_por_modelo(modelo):
    r = get('/productos', {'modelo': modelo, 'moneda': 'mxn'})
    if not r: return None
    if isinstance(r, dict) and 'productos' in r: r = r['productos']
    if isinstance(r, list): r = next((p for p in r if str(p.get('modelo','')).upper() == modelo.upper()), r[0] if r else None)
    return mapear(r) if r else None

def producto_por_id(pid):
    r = get(f'/productos/{pid}', {'moneda': 'mxn'})
    if isinstance(r, list): r = r[0] if r else None
    return mapear(r) if r else None

def mapear(p):
    """Normaliza un producto de SYSCOM a los campos que usamos en materiales."""
    precios = p.get('precios') if isinstance(p.get('precios'), dict) else {}
    img = p.get('img_portada')
    if not img and p.get('imagenes'):
        i0 = p['imagenes'][0]; img = i0.get('imagen') if isinstance(i0, dict) else i0
    precio = precios.get('precio_descuento') or precios.get('precio_especial') or precios.get('precio_1')
    return {'syscom_id': str(p.get('producto_id') or p.get('id') or ''), 'modelo': p.get('modelo'), 'titulo': p.get('titulo'),
            'marca': p.get('marca'), 'imagen': img, 'precio': float(precio) if precio else None,
            'precio_lista': float(precios['precio_lista']) if precios.get('precio_lista') else None,
            'existencia': p.get('total_existencia'), 'link': ('https://www.syscom.mx' + p['link']) if str(p.get('link','')).startswith('/') else p.get('link')}

def descargar_miniatura(url, destino_dir, nombre):
    """Descarga la imagen (las de SYSCOM ya son pequeñas). Devuelve ruta relativa 'productos/xxx.ext' o None."""
    if not url: return None
    try:
        st, raw = _http('GET', url, timeout=20)
        if st != 200 or len(raw) > 3_000_000: return None
        ext = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower()
        if ext not in ('.jpg', '.jpeg', '.png', '.webp', '.gif'): ext = '.jpg'
        os.makedirs(destino_dir, exist_ok=True)
        fn = ''.join(ch if ch.isalnum() or ch in '-_' else '_' for ch in nombre) + ext
        with open(os.path.join(destino_dir, fn), 'wb') as fh: fh.write(raw)
        try:  # reducir a 200px si Pillow está disponible
            from PIL import Image
            im = Image.open(os.path.join(destino_dir, fn)); im.thumbnail((200, 200)); im.save(os.path.join(destino_dir, fn))
        except Exception: pass
        return 'productos/' + fn
    except Exception: return None

def sincronizar(conn, upload_dir, descargar_imagenes=True, crear_nuevos=False, consultas=None):
    """Recorre los materiales y los enriquece con datos de SYSCOM.
    Coincide por syscom_id, luego por numero_parte (modelo), luego por SKU. Actualiza numero_parte, syscom_id,
    marca, imagen, precio. Si crear_nuevos y se pasan consultas (modelos), da de alta los que no existan.
    Devuelve resumen dict."""
    res = {'revisados': 0, 'actualizados': 0, 'sin_coincidencia': 0, 'creados': 0, 'imagenes': 0, 'errores': []}
    rows = conn.execute('SELECT id, sku, numero_parte, syscom_id FROM materiales WHERE activo=1').fetchall()
    for mid, sku, np_, sid in rows:
        res['revisados'] += 1
        try:
            p = (producto_por_id(sid) if sid else None) or (producto_por_modelo(np_) if np_ else None) or producto_por_modelo(sku)
        except SyscomError as e:
            res['errores'].append(f'{sku}: {e}'); continue
        if not p or not p['modelo']: res['sin_coincidencia'] += 1; continue
        _aplicar(conn, mid, p, upload_dir, descargar_imagenes, res)
    for modelo in (consultas or []) if crear_nuevos else []:
        p = producto_por_modelo(modelo)
        if not p: continue
        if conn.execute('SELECT 1 FROM materiales WHERE numero_parte=? OR sku=?', (p['modelo'], p['modelo'])).fetchone(): continue
        mid = conn.execute("INSERT INTO materiales(sku,nombre,categoria,unidad) VALUES(?,?,'OTROS','pza')", (p['modelo'], (p['titulo'] or p['modelo'])[:200])).lastrowid
        _aplicar(conn, mid, p, upload_dir, descargar_imagenes, res); res['creados'] += 1
    conn.commit()
    est = estado(); est.update(ultima_sync=_ahora(), ultimo_resumen={k: (v if k != 'errores' else v[:20]) for k, v in res.items()}); _guardar_estado(est)
    return res

def _aplicar(conn, mid, p, upload_dir, descargar_imagenes, res):
    img_local = descargar_miniatura(p['imagen'], os.path.join(upload_dir, 'productos'), p['modelo']) if descargar_imagenes else None
    if img_local: res['imagenes'] += 1
    conn.execute('''UPDATE materiales SET numero_parte=?, syscom_id=?, marca=COALESCE(?,marca), imagen_url=COALESCE(?,imagen_url),
        imagen_local=COALESCE(?,imagen_local), precio_syscom=?, syscom_link=?, syscom_sync=?, proveedor_id=COALESCE(proveedor_id,(SELECT id FROM proveedores WHERE codigo='SYSCOM')) WHERE id=?''',
        (p['modelo'], p['syscom_id'], p['marca'], p['imagen'], img_local, p['precio'], p['link'], _ahora(), mid))
    res['actualizados'] += 1

def _ahora(): return dt.datetime.now().strftime('%Y-%m-%d %H:%M')
