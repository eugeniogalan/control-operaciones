"""Rutas de datos. Con DATA_DIR (p. ej. el disco persistente de Render en /var/data) la base y las fotos/documentos
viven ahí: DATA_DIR/ops.db y DATA_DIR/uploads. Sin DATA_DIR se usan las rutas locales de siempre (junto al código).
DB_PATH y UPLOAD_DIR, si se definen, siguen teniendo prioridad."""
import os
BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = (os.environ.get('DATA_DIR') or '').strip() or None
if DATA_DIR: os.makedirs(DATA_DIR, exist_ok=True)
DB = os.environ.get('DB_PATH') or os.path.join(DATA_DIR or BASE, 'ops.db')
UP = os.environ.get('UPLOAD_DIR') or os.path.join(DATA_DIR or BASE, 'uploads')

def bd_con_datos(path=None):
    """True si la base existe y ya tiene datos (personal, órdenes o materiales). Una base vacía o inexistente -> False."""
    import sqlite3
    path = path or DB
    if not os.path.exists(path) or os.path.getsize(path) == 0: return False
    try:
        c = sqlite3.connect(path)
        try:
            tablas = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            return any(t in tablas and c.execute(f'SELECT 1 FROM {t} LIMIT 1').fetchone() for t in ('tecnicos', 'ordenes', 'materiales', 'clientes'))
        finally: c.close()
    except Exception:
        return True   # ante la duda, nunca se borra
