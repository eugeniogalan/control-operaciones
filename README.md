# Control de Operaciones (Flask + SQLite)

## Local
    pip install -r requirements.txt
    cp .env.example .env   # y pon una contraseña y SECRET_KEY
    python seed.py         # datos de EJEMPLO (borra y recrea la BD)
    python app.py          # http://localhost:8080  (o: gunicorn app:app --bind 0.0.0.0:8080)

## Render (plan gratuito)
Blueprint `render.yaml`. Variables: ADMIN_USER, ADMIN_PASSWORD, SECRET_KEY (autogenerada), DB_PATH, UPLOAD_DIR.
Nota: el disco del plan gratuito es efímero; al reiniciar/redeploy la base vuelve a los datos de ejemplo y se pierden fotos subidas.
El servicio se duerme tras ~15 min sin uso (primer acceso tarda ~1 min).

## Inventario de materiales
- **Almacenes (20)**: Torrelit, Autosound y Vehículo 01–18 (almacenes móviles). Cada vehículo se asigna a una cuadrilla en **/vehiculos** (reasignable; una cuadrilla puede tener varios vehículos; puede quedar sin asignar).
- **Tablas**: `materiales` (sku, nombre, categoria, variantes, unidad, stock_actual = total, stock_minimo, ubicacion, activo, notas), `almacenes`, `existencias` (stock por material y almacén), `movimientos` (entrada / salida / ajuste / devolución / transferencia, con fecha, cantidad con signo, stock resultante, motivo, referencia, orden_id, usuario).
- **Páginas**: /inventario (búsqueda, filtro por tipo y almacén, bajo mínimo en rojo, alta/edición), /inventario/movimiento?tipo=entrada|salida|ajuste|transferencia, /inventario/movimientos (historial filtrable), /vehiculos.
- **Órdenes**: en "Capturar materiales" se elige el almacén de salida (se sugieren los vehículos de la cuadrilla). Al guardar se genera una salida ligada a la orden; si se corrige la cantidad o el almacén, la diferencia se devuelve. Sin existencia suficiente se pide confirmar "Permitir stock negativo".
- **Mínimos**: `stock_minimo` global (suma) + `existencias.minimo` por almacén (se edita en la ficha del material). Alerta cuando la existencia queda en o por debajo; el panel muestra conteos por almacén y /inventario?almacen=ID&bajo=1 filtra.
- `seed.py` crea 89 materiales (de plantillas.json) con existencias **de EJEMPLO**.
