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
