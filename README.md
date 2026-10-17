# Control de Operaciones (Flask + SQLite)

## Local
    pip install -r requirements.txt
    cp .env.example .env   # y pon una contraseña y SECRET_KEY
    python seed.py         # datos de EJEMPLO, solo si la BD no existe o está vacía (--force la borra y recrea)
    python app.py          # http://localhost:8080  (o: gunicorn app:app --bind 0.0.0.0:8080)

### Dónde se guardan los datos (`DATA_DIR`)
- Sin `DATA_DIR`: `ops.db` y `uploads/` junto al código (como siempre).
- Con `DATA_DIR=/ruta`: se crea la carpeta y se usan `/ruta/ops.db` y `/ruta/uploads/` (fotos, PDFs, firmas, cartas responsivas).
- `DB_PATH` / `UPLOAD_DIR` siguen existiendo y, si están definidas, **tienen prioridad** sobre `DATA_DIR`.
- La siembra de datos de ejemplo (`seed.py`) solo corre si la base no existe o no tiene datos (personal, órdenes, materiales o clientes); nunca sobrescribe datos reales.

## Render (plan Starter + disco persistente)
Blueprint `render.yaml` (plan `starter`, disco `data` montado en `/var/data`, 1 GB, `DATA_DIR=/var/data`).

Si el servicio ya existe y se configura a mano en el dashboard:
1. **Settings › Instance type**: Starter (o superior; los discos no están disponibles en Free).
2. **Disks › Add disk**: Name `data`, Mount path `/var/data`, Size `1` GB.
3. **Environment**: agrega `DATA_DIR` = `/var/data`. **Elimina `DB_PATH` y `UPLOAD_DIR`** si existen (apuntaban a `/tmp/ops-data`, que es efímero, y tendrían prioridad sobre `DATA_DIR`).
   Conserva `ADMIN_USER`, `ADMIN_PASSWORD`, `DEMO_USERS_PASSWORD`, `SECRET_KEY`, `PYTHON_VERSION`.
4. **Start command**: `python seed.py --if-missing && gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 60`.
5. Deploy. En el primer arranque el disco está vacío, así que se siembran los datos de ejemplo una sola vez; a partir de ahí la base y los archivos sobreviven reinicios y redeploys.

Notas: un servicio con disco no admite escalar a varias instancias y el deploy tiene unos segundos de corte (Render detiene la instancia anterior antes de montar el disco en la nueva).
Respaldo: Render toma snapshots diarios del disco; para una copia propia, `python -c "import sqlite3;s=sqlite3.connect('/var/data/ops.db');d=sqlite3.connect('/var/data/respaldo.db');s.backup(d)"` desde el Shell del servicio.

## Inventario de materiales
- **Almacenes (20)**: Torrelit, Autosound y Vehículo 01–18 (almacenes móviles). Cada vehículo se asigna a una cuadrilla en **/vehiculos** (reasignable; una cuadrilla puede tener varios vehículos; puede quedar sin asignar).
- **Tablas**: `materiales` (sku, nombre, categoria, variantes, unidad, stock_actual = total, stock_minimo, ubicacion, activo, notas), `almacenes`, `existencias` (stock por material y almacén), `movimientos` (entrada / salida / ajuste / devolución / transferencia, con fecha, cantidad con signo, stock resultante, motivo, referencia, orden_id, usuario).
- **Páginas**: /inventario (búsqueda, filtro por tipo y almacén, bajo mínimo en rojo, alta/edición), /inventario/movimiento?tipo=entrada|salida|ajuste|transferencia, /inventario/movimientos (historial filtrable), /vehiculos.
- **Órdenes**: en "Capturar materiales" se elige el almacén de salida (se sugieren los vehículos de la cuadrilla). Al guardar se genera una salida ligada a la orden; si se corrige la cantidad o el almacén, la diferencia se devuelve. Sin existencia suficiente se pide confirmar "Permitir stock negativo".
- **Mínimos**: `stock_minimo` global (suma) + `existencias.minimo` por almacén (se edita en la ficha del material). Alerta cuando la existencia queda en o por debajo; el panel muestra conteos por almacén y /inventario?almacen=ID&bajo=1 filtra.
- `seed.py` crea 89 materiales (de plantillas.json) con existencias **de EJEMPLO**.

## Vehículos (Configuración › Vehículos)
- **Fotografías**: Frente del vehículo, Trasero del vehículo, Costado derecho y Costado izquierdo (cámara o galería, con vista previa). Se capturan en el mismo formulario y se suben al guardar, también en el alta. Se comprimen igual que las de Sites (uploads/vehiculos).
- **Documentos (solo PDF, hasta 15 MB)**: Tarjeta de circulación y Póliza de seguro. Se valida que el archivo sea PDF; ver, descargar, reemplazar (el nuevo sustituye al anterior) o eliminar.
- **Seguro**: compañía, número de póliza y vencimiento. Estado: 🟢 Vigente, 🟠 Próxima a vencer (30 días o menos), 🔴 Vencida. Se muestra en la lista (con filtro por estado), en el formulario, en /vehiculos y en el panel («Seguros de vehículos») para los perfiles con permiso de vehículos.
- Permisos: alta, cambios y adjuntos requieren «Configuración › Vehículos»; las fotos y PDFs solo los ven perfiles con «Vehículos: ver» o «Configuración › Vehículos».

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

## Checklist diario de técnicos
Todo usuario cuyo perfil tiene `checklist.realizar` (perfil Técnico) debe completar, la primera vez que entra cada día (fecha de America/Mexico_City), la **Rutina 1 – Vehículo** (vehículo, kilometraje, foto de odómetro, nivel de combustible + foto, puntos de revisión) y después la **Rutina 2 – Seguridad** (EPP + foto de la cuadrilla). Mientras no termina, cualquier otra pantalla redirige a `/checklist`.
Los puntos sin cumplir se permiten pero exigen comentario y quedan marcados como incumplimiento. Revisión en **Checklists diarios** (permiso `checklist.ver`). Los puntos se editan en Configuración › Checklist diario (puntos).

## Asignación de vehículos y cartas responsivas
Cada vehículo se asigna a una **Cuadrilla**, a una **Persona** (de Configuración › Personal) o queda **Sin asignar**, con fecha de asignación e historial.
Cada nueva asignación genera una **carta responsiva** (Pendiente de firma → Firmada) que el asignado firma en pantalla (en cuadrilla, cada integrante), o que un supervisor/admin captura en persona (`responsivas.firmar_presencial`). Al completarse se genera el PDF (reportlab) en `uploads/responsivas/`.

## Combustible, rendimiento y mantenimiento (flotilla)
- **Vehículos**: campo *Capacidad del tanque (litros)*.
- **Cargas de combustible** (`/combustible`, permiso `combustible.registrar`, activo en todos los perfiles): vehículo (pre-llenado: asignado a la persona, luego a su cuadrilla), fecha/hora, litros, monto, precio por litro calculado, kilometraje, tipo (Magna / Premium / Diésel), ¿tanque lleno?, foto del ticket y estación. Litros mayores al tanque o km menor al último registrado piden confirmación y la carga queda marcada. Cada quien ve su historial; `combustible.ver_todo` ve y administra todas.
- **Rendimiento**: km/l por tramo con el método tanque lleno → tanque lleno (si el vehículo tiene ≥ 2 cargas «tanque lleno»), si no distancia entre cargas / litros. Promedio, l/100 km, costo por km, gasto mensual. Un tramo > 20 % abajo del promedio del vehículo se marca como posible mal uso. El kilometraje actual usa la lectura más reciente de cargas, checklists diarios y mantenimientos.
- **Bitácora de mantenimiento** (`/mantenimiento`, `mantenimiento.ver` / `mantenimiento.registrar`): fecha, km, Preventivo/Correctivo, categoría, descripción, taller, costo, factura/fotos (PDF o imagen) y próximo servicio por km y/o fecha.
- **Próximos servicios** (ficha del vehículo, bitácora, dashboard): por categoría, próximo km/fecha, km y días restantes y estado *Al día / Próximo (≤ 1,000 km o ≤ 15 días) / Vencido*. Intervalos configurables (`/mantenimiento/intervalos`, generales y por vehículo; p. ej. aceite 5,000 km o 6 meses, afinación 20,000 km o 12 meses) que pre-llenan el próximo servicio; si se deja vacío se calcula con el intervalo.
- **Dashboard de vehículos** (`/vehiculos/dashboard`, `vehiculos.dashboard`): KPIs del mes, lista de servicios vencidos/próximos por urgencia, gráficas SVG (gasto mensual, rendimiento), tarjetas por vehículo, anomalías, pólizas e incumplimientos de checklist.
- Datos de ejemplo de flotilla solo en una BD recién creada por `seed.py`; una BD existente nunca recibe datos de ejemplo.
