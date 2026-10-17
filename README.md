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

## Proveedor SYSCOM (números de parte y fotos)

Página: **/proveedores/syscom** (menú "Syscom"). Cliente: `syscom_client.py` (OAuth2 `client_credentials` contra `https://developers.syscom.mx/api/v1/oauth/token`).

Credenciales (nunca en la base de datos ni en git):
- **Render:** Environment → agregar `SYSCOM_CLIENT_ID` y `SYSCOM_CLIENT_SECRET` → redesplegar. (Tienen prioridad.)
- **Local / servidor propio:** pegarlas en el formulario de /proveedores/syscom; se guardan en `.env` (gitignored, permisos 600).
- Opcional: `SYSCOM_API_URL`, `SYSCOM_STATE_PATH` (token y última sync; por defecto `syscom_estado.json`, gitignored).

Flujo: **Guardar y probar** → **Probar conexión** → **Sincronizar catálogo** (se habilita solo cuando la conexión funciona).
La sync busca cada material por ID Syscom → número de parte/modelo → SKU; llena `numero_parte`, `syscom_id`, `marca`, `precio_syscom`, `imagen_url` y descarga la foto a `uploads/productos/`. No toca existencias. Puede dar de alta modelos nuevos (uno por línea).
Búsqueda: `GET /api/syscom/buscar?q=texto`. Las miniaturas en `static/productos/ejemplo-*.svg` son **de ejemplo** (marcadas `imagen_ejemplo=1`).


## Usuarios y permisos
- **Superadmin**: `ADMIN_USER` / `ADMIN_PASSWORD` (variables de entorno). Siempre puede entrar y tiene todos los permisos; úsalo para crear los usuarios reales.
- **Usuarios por persona**: Configuración › **Usuarios** (solo el superadmin de entorno; cualquier otro perfil recibe 403): alta (persona de Personal sin usuario o persona nueva), cambios (usuario, perfil, acceso), restablecer contraseña (hash werkzeug, mín. 8) y baja suave del acceso. Baja o cambio de contraseña cierran las sesiones abiertas. Cada movimiento queda en la bitácora (quién y cuándo).
- **Perfiles y permisos**: Configuración › Usuarios › **Perfiles y permisos** (solo superadmin). Matriz de casillas (filas = módulo/acción, columnas = perfil), con **alcance** por perfil (todas / por tipo de trabajo / su equipo / solo propias) y **categorías** visibles (Infraestructura, Clientes, Prospectos). Los cambios se aplican de inmediato y quedan en la bitácora. «Restaurar valores predeterminados» por perfil; se pueden crear perfiles personalizados (copia de uno base) y eliminarlos si no tienen usuarios.
- **Perfiles predeterminados**: Administrador (superadmin de entorno, todo, no editable) · Director (todo, autoriza, Configuración) · Gerente de administración (ve todo, autoriza, Configuración, inventario, proveedores) · Gerente de operaciones (órdenes de infraestructura y clientes, asigna/cierra, cuadrillas, vehículos, inventario; no autoriza) · Gerente de ventas (clientes, prospectos y sus órdenes de todo el equipo) · Gerente de soporte/atención (órdenes de clientes de mantenimiento correctivo/preventivo y seguimiento) · Ejecutivo comercial (solo sus clientes, prospectos y órdenes) · Supervisor (órdenes de sus cuadrillas) · Técnico (solo órdenes asignadas: evidencias, materiales, estado) · Almacenista (inventario; órdenes solo lectura).
- Cada persona toma el perfil de su **puesto** (catálogo de Personal: Director, Gerente de administración/operaciones/ventas/soporte, Ejecutivo comercial, Supervisor, Técnico Instalador, Almacenista, Proveedor Externo); en Usuarios se puede asignar otro perfil. Clientes y órdenes tienen **Ejecutivo / propietario** (por omisión quien los crea) y las cuadrillas un **Supervisor**; con eso se calcula el alcance «propias» y «equipo». Los permisos se validan en el servidor (403), en menús/botones y en los listados.
- Las órdenes de **Clientes › Instalación nueva** se crean «Pendiente de autorización» y no pueden asignarse, iniciarse ni cerrarse hasta autorizarse.
- Datos de EJEMPLO (seed): se crean los usuarios `director`, `administracion` y `tecnico`. Solo tienen contraseña si defines la variable de entorno `DEMO_USERS_PASSWORD` (la misma para los tres, mín. 8 caracteres); si no está definida existen como Personal **sin acceso**. Nunca pongas su valor en el repositorio; en Render configúrala como secreto (opcional).
