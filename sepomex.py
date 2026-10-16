"""Catálogo local de códigos postales (SEPOMEX) y estados/municipios (claves INEGI). Funciona sin internet.
Datos: data/sepomex.json.gz  ->  {estados:[...], municipios:[[...] por estado], cp:{"44100":[i_estado, i_municipio, [colonias]]}}"""
import os, gzip, json, threading
from flask import jsonify
_RUTA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'sepomex.json.gz')
_D = None; _L = threading.Lock()

def datos():
    global _D
    if _D is None:
        with _L:
            if _D is None:
                with gzip.open(_RUTA, 'rt', encoding='utf-8') as f: _D = json.load(f)
    return _D

def estados(): return datos()['estados']

def municipios(estado):
    d = datos()
    return d['municipios'][d['estados'].index(estado)] if estado in d['estados'] else []

def buscar_cp(cp):
    d = datos(); r = d['cp'].get((cp or '').strip())
    if not r: return None
    e, m, cols = r
    return {'cp': cp, 'estado': d['estados'][e], 'municipio': d['municipios'][e][m], 'colonias': cols}

def registrar(app):
    @app.route('/api/cp/<cp>')
    def api_cp(cp):
        r = buscar_cp(cp) if cp.isdigit() and len(cp) == 5 else None
        return (jsonify(r), 200) if r else (jsonify(error='Código postal no encontrado', cp=cp), 404)

    @app.route('/api/municipios/<path:estado>')
    def api_municipios(estado):
        return jsonify(estado=estado, municipios=municipios(estado))

    @app.route('/api/estados')
    def api_estados():
        return jsonify(estados=estados())
