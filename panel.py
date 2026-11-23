"""Panel local del Equipo IA: http://127.0.0.1:8765 (solo en tu PC).

Muestra todos los proyectos, lo que requiere tu atención, el estado de cada tablero y un resumen del
README; permite arrancar/parar el equipo de un proyecto, reintentar tareas y dar de alta proyectos.
"""
from __future__ import annotations

import base64
import json
import re
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import equipo as E

T, C = E.T, E.C
TOKEN = secrets.token_urlsafe(24)
_cache: dict = {}
_cache_lock = threading.Lock()
TRABAJOS: dict[str, dict] = {}


def cacheado(clave: str, ttl: int, fn, forzar=False):
    with _cache_lock:
        v = _cache.get(clave)
        if v and not forzar and time.time() - v[0] < ttl:
            return v[1]
    try:
        valor = fn()
    except Exception as e:  # noqa: BLE001 — el panel nunca se cae por una consulta
        valor = {"error": str(e)[:300]}
    with _cache_lock:
        _cache[clave] = (time.time(), valor)
    return valor


def gh_json(*args):
    out = E.gh(*args, comprobar=False)
    return json.loads(out) if out.strip().startswith(("{", "[")) else None


# --------------------------------------------------------------------------- datos por repo

def resumen_readme(repo: str) -> dict:
    datos = gh_json("api", f"repos/{repo}/readme")
    if not datos or "content" not in datos:
        return {"resumen": "", "estado": "", "url": f"https://github.com/{repo}"}
    texto = base64.b64decode(datos["content"]).decode("utf-8", errors="replace")
    estado = ""
    m = re.search(r"^>?\s*\**Estado[^:]*:?\**\s*:?\s*(.+)$", texto, re.M | re.I)
    if m:
        estado = re.sub(r"[*_`]", "", m.group(1)).strip()[:200]
    parrafos, actual = [], []
    for linea in texto.splitlines():
        l = linea.strip()
        if not l:
            if actual:
                parrafos.append(" ".join(actual))
                actual = []
            continue
        if l.startswith(("#", "![", "[!", "```", "|", "<", ">", "-", "*")) or re.match(r"^\d+\.", l):
            if actual:
                parrafos.append(" ".join(actual))
                actual = []
            continue
        actual.append(l)
    if actual:
        parrafos.append(" ".join(actual))
    resumen = next((p for p in parrafos if len(p) > 40), parrafos[0] if parrafos else "")
    resumen = re.sub(r"\*\*|__|`", "", resumen)
    return {"resumen": resumen[:400], "estado": estado, "url": datos.get("html_url") or f"https://github.com/{repo}"}


def datos_repo(repo: str) -> dict:
    info = cacheado(f"info:{repo}", 3600, lambda: gh_json("api", f"repos/{repo}") or {})
    rama = info.get("default_branch", "main") if isinstance(info, dict) else "main"

    def alertas():
        r = E.C.ejecutar(E.gh_bin() + ["api", f"repos/{repo}/dependabot/alerts?state=open&per_page=100"], timeout=60)
        if r.returncode != 0:
            return {"desactivado": "disabled" in (r.stderr or "").lower(), "error": (r.stderr or "")[:120]}
        sev: dict[str, int] = {}
        for a in json.loads(r.stdout or "[]"):
            s = (a.get("security_advisory") or {}).get("severity", "?")
            sev[s] = sev.get(s, 0) + 1
        return {"por_severidad": sev, "total": sum(sev.values())}

    def ci():
        runs = (gh_json("api", f"repos/{repo}/actions/runs?branch={rama}&per_page=15") or {}).get("workflow_runs", [])
        for r in runs:
            if Path(r.get("path", "")).name in E.NUESTROS_WORKFLOWS or r.get("status") != "completed":
                continue
            return {"conclusion": r.get("conclusion"), "nombre": r.get("name"), "url": r.get("html_url"),
                    "fecha": r.get("updated_at")}
        return {"conclusion": None}

    def secreto():
        nombres = E.gh("api", f"repos/{repo}/actions/secrets", "--jq", ".secrets[].name", comprobar=False).split()
        return "TABLERO_TOKEN" in nombres

    return {"repo": repo, "url": f"https://github.com/{repo}", "rama": rama,
            "readme": cacheado(f"readme:{repo}", 3600, lambda: resumen_readme(repo)),
            "alertas": cacheado(f"alertas:{repo}", 300, alertas),
            "ci": cacheado(f"ci:{repo}", 120, ci),
            "secreto": cacheado(f"secreto:{repo}", 600, secreto)}


# --------------------------------------------------------------------------- datos por proyecto

def prs_registro(nombre: str) -> dict[int, str]:
    db = E.PROYECTOS / nombre / "estado" / "registro.db"
    if not db.exists():
        return {}
    con = sqlite3.connect(str(db))
    try:
        return {n: u for n, u in con.execute("SELECT issue, pr_url FROM tareas WHERE pr_url IS NOT NULL")}
    finally:
        con.close()


def estado_proyecto(nombre: str, forzar=False) -> dict:
    cfg = E.cfg_proyecto(nombre)
    repos = cfg.get("repos") or [cfg.get("repo")]
    tb = cfg.get("tablero") or {}
    salida = {"nombre": nombre, "descripcion": cfg.get("descripcion", ""), "repos": [], "tablero": tb.get("url"),
              "activo": E.coordinador_activo(nombre), "columnas": {e: 0 for e in T.ESTADOS}, "atencion": [],
              "tarjetas": {}, "error": None}

    def items():
        t = T.Tablero(tb["owner"], tb["numero"], tb.get("owner_tipo", "user"), E.gh_bin())
        return t.items()

    def vistas():
        t = T.Tablero(tb["owner"], tb["numero"], tb.get("owner_tipo", "user"), E.gh_bin())
        return [v["name"] for v in t.info()["views"]["nodes"]]

    if tb.get("numero"):
        its = cacheado(f"items:{nombre}", 60, items, forzar)
        if isinstance(its, dict) and its.get("error"):
            salida["error"] = its["error"]
            its = []
        prs = prs_registro(nombre)
        grupos: dict[str, list] = {}
        for it in its:
            if not it["abierta"] and it["estado"] not in (T.DONE, T.PRO):
                continue
            e = it["estado"] or "(sin estado)"
            if e in salida["columnas"]:
                salida["columnas"][e] += 1
            tarjeta = {"numero": it["numero"], "titulo": it["titulo"], "url": it["url"], "prioridad": it["prioridad"],
                       "bloqueo": it["bloqueo"], "pr": prs.get(it["numero"]), "repo": it["repo"],
                       "agente": next((x.split(":")[1] for x in it["etiquetas"] if x.startswith("agent:")), None)}
            grupos.setdefault(e, []).append(tarjeta)
            if it["bloqueo"]:
                salida["atencion"].append({"nivel": "alta", "tipo": "bloqueo", "numero": it["numero"],
                                           "texto": f"#{it['numero']} bloqueada: {it['bloqueo'][:160]}",
                                           "url": it["url"], "reintentar": "CI en rojo" in it["bloqueo"]
                                           or "sin modificar" in it["bloqueo"] or "Pruebas fallidas" in it["bloqueo"]})
            elif e == T.REVIEW:
                salida["atencion"].append({"nivel": "alta", "tipo": "revision",
                                           "texto": f"PR para revisar: #{it['numero']} {it['titulo'][:70]}",
                                           "url": prs.get(it["numero"]) or it["url"]})
            elif e == T.PLANNING:
                salida["atencion"].append({"nivel": "media", "tipo": "planning",
                                           "texto": f"Propuesta en Planning: #{it['numero']} {it['titulo'][:70]}",
                                           "url": it["url"]})
        for g in grupos.values():
            g.sort(key=lambda x: (T.rango_prioridad(x["prioridad"]), x["numero"]))
        salida["tarjetas"] = grupos
        vs = cacheado(f"vistas:{nombre}", 600, vistas, forzar)
        if isinstance(vs, list):
            faltan = [v for v in ("Tablero", "Planning") if v not in vs]
            if faltan:
                salida["atencion"].append({"nivel": "media", "tipo": "instalacion", "url": tb.get("url"),
                                           "texto": f"Crear las vistas del tablero: {', '.join(faltan)}"})
    else:
        salida["atencion"].append({"nivel": "media", "tipo": "instalacion", "texto": "El proyecto aún no tiene tablero",
                                   "url": None})

    with ThreadPoolExecutor(max_workers=4) as ex:
        salida["repos"] = list(ex.map(datos_repo, repos))
    for r in salida["repos"]:
        sev = (r["alertas"] or {}).get("por_severidad") or {}
        graves = sev.get("critical", 0) + sev.get("high", 0)
        if graves:
            salida["atencion"].append({"nivel": "alta", "tipo": "seguridad", "url": f"{r['url']}/security/dependabot",
                                       "texto": f"{r['repo']}: {graves} aviso(s) de seguridad crítico/alto"})
        if (r["ci"] or {}).get("conclusion") == "failure":
            salida["atencion"].append({"nivel": "alta", "tipo": "ci", "url": r["ci"].get("url"),
                                       "texto": f"{r['repo']}: CI en rojo en {r['rama']} ({r['ci'].get('nombre')})"})
        if r["secreto"] is False:
            salida["atencion"].append({"nivel": "media", "tipo": "instalacion", "url": f"{r['url']}/settings/secrets/actions",
                                       "texto": f"{r['repo']}: falta el secreto TABLERO_TOKEN (mantenimiento y Done/PRO no funcionarán)"})
    for url in (cfg.get("instalacion") or {}).get("prs", []):
        st = cacheado(f"pr:{url}", 300, lambda u=url: gh_json("pr", "view", u, "--json", "state") or {}, forzar)
        if isinstance(st, dict) and st.get("state") == "OPEN":
            salida["atencion"].append({"nivel": "media", "tipo": "instalacion", "url": url,
                                       "texto": "PR de instalación del Equipo IA pendiente de integrar"})
    orden = {"alta": 0, "media": 1, "info": 2}
    salida["atencion"].sort(key=lambda a: orden[a["nivel"]])
    return salida


def estado_general(forzar=False) -> dict:
    lista = E.proyectos()
    with ThreadPoolExecutor(max_workers=4) as ex:
        datos = list(ex.map(lambda p: estado_proyecto(p, forzar), lista))
    return {"proyectos": datos, "generado": C.ahora(), "trabajos": [
        {"id": k, "titulo": v["titulo"], "estado": v["estado"]} for k, v in TRABAJOS.items()]}


# --------------------------------------------------------------------------- acciones

def lanzar_trabajo(titulo: str, fn) -> str:
    tid = uuid.uuid4().hex[:8]
    t = {"titulo": titulo, "estado": "en curso", "lineas": [], "resultado": None}
    TRABAJOS[tid] = t

    def log(msg):
        t["lineas"].append(f"[{time.strftime('%H:%M:%S')}] {msg}")

    def correr():
        try:
            t["resultado"] = fn(log)
            t["estado"] = "hecho"
        except Exception as e:  # noqa: BLE001
            log(f"ERROR: {e}")
            t["estado"] = "error"
        with _cache_lock:
            _cache.clear()
    threading.Thread(target=correr, daemon=True).start()
    return tid


def arrancar(nombre: str) -> dict:
    if E.coordinador_activo(nombre):
        return {"ok": True, "mensaje": "Ya estaba en marcha"}
    logf = E.PROYECTOS / nombre / "estado" / "vigilar.log"
    logf.parent.mkdir(parents=True, exist_ok=True)
    fh = open(logf, "a", encoding="utf-8")
    subprocess.Popen([sys.executable, str(E.LAB / "coordinador.py"), "vigilar"], cwd=E.LAB,
                     env=E.env_proyecto(nombre), stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                     start_new_session=True)
    for _ in range(20):
        time.sleep(0.25)
        if E.coordinador_activo(nombre):
            return {"ok": True, "mensaje": "Equipo en marcha"}
    return {"ok": False, "mensaje": "No arrancó; mira el log"}


def parar(nombre: str) -> dict:
    r = E.script(nombre, "coordinador.py", "parar", capturar=True, timeout=30)
    return {"ok": r.returncode == 0, "mensaje": "Se detendrá al terminar la tarea en curso"}


def reintentar(nombre: str, numero: int) -> dict:
    r = E.script(nombre, "coordinador.py", "reanudar", str(numero), "--desde", "agente", capturar=True, timeout=60)
    return {"ok": r.returncode == 0, "mensaje": (r.stdout or r.stderr).strip()[-300:]}


def guardar_secreto(nombre: str, token) -> dict:
    """POST /api/proyecto/<n>/secreto: el token llega en el cuerpo y no se guarda ni se devuelve."""
    if not isinstance(token, str) or not token.strip():
        return {"ok": False, "mensaje": "Pega el token en el campo.", "guardados": [], "fallidos": []}
    try:
        res = E.guardar_secreto_tablero(nombre, token)
    except Exception as e:  # noqa: BLE001
        res = {"ok": False, "mensaje": f"Error: {E._sin_token(str(e), token.strip())[:200]}", "guardados": [], "fallidos": []}
    with _cache_lock:
        for k in [k for k in _cache if k.startswith("secreto:")]:
            _cache.pop(k, None)
    return res


def log_proyecto(nombre: str) -> str:
    p = E.PROYECTOS / nombre / "estado" / "vigilar.log"
    if not p.exists():
        return "(sin log todavía)"
    return "\n".join(p.read_text(encoding="utf-8", errors="replace").splitlines()[-60:])


def repos_disponibles() -> list[dict]:
    usados = {r.lower() for p in E.proyectos() for r in (E.cfg_proyecto(p).get("repos") or [])}
    lista = gh_json("repo", "list", "--limit", "200", "--json", "nameWithOwner,description,isPrivate,pushedAt") or []
    return [r for r in lista if r["nameWithOwner"].lower() not in usados]


# --------------------------------------------------------------------------- HTTP

class Manejador(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, datos, codigo=200):
        b = json.dumps(datos, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def do_GET(self):
        if not self._host_ok():
            return self._json({"error": "host no permitido"}, 403)
        ruta = self.path.split("?")[0]
        if ruta == "/":
            b = PAGINA.replace("__TOKEN__", TOKEN).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            return self.wfile.write(b)
        if ruta == "/api/estado":
            return self._json(estado_general(forzar="refrescar" in self.path))
        if ruta == "/api/repos":
            return self._json(repos_disponibles())
        m = re.match(r"^/api/trabajos/(\w+)$", ruta)
        if m and m.group(1) in TRABAJOS:
            return self._json(TRABAJOS[m.group(1)])
        m = re.match(r"^/api/proyecto/([a-z0-9-]+)/log$", ruta)
        if m and m.group(1) in E.proyectos():
            return self._json({"log": log_proyecto(m.group(1))})
        self._json({"error": "no encontrado"}, 404)

    def do_POST(self):
        largo = min(int(self.headers.get("Content-Length") or 0), 1_000_000)
        crudo = self.rfile.read(largo) if largo else b""  # se lee siempre: rechazar sin leer puede cortar la conexión
        if not self._host_ok() or not secrets.compare_digest((self.headers.get("X-Token") or "").encode("utf-8", "replace"),
                                                             TOKEN.encode()):
            return self._json({"error": "no autorizado"}, 403)
        try:
            cuerpo = json.loads(crudo or b"{}")
        except ValueError:
            return self._json({"error": "cuerpo no válido"}, 400)
        if not isinstance(cuerpo, dict):
            return self._json({"error": "cuerpo no válido"}, 400)
        ruta = self.path
        m = re.match(r"^/api/proyecto/([a-z0-9-]+)/(arrancar|parar|reintentar)$", ruta)
        if m:
            nombre, accion = m.groups()
            if nombre not in E.proyectos():
                return self._json({"error": "proyecto desconocido"}, 404)
            if accion == "arrancar":
                return self._json(arrancar(nombre))
            if accion == "parar":
                return self._json(parar(nombre))
            return self._json(reintentar(nombre, int(cuerpo.get("numero", 0))))
        m = re.match(r"^/api/proyecto/([a-z0-9-]+)/secreto$", ruta)
        if m:
            nombre = m.group(1)
            if nombre not in E.proyectos():
                return self._json({"error": "proyecto desconocido"}, 404)
            return self._json(guardar_secreto(nombre, cuerpo.pop("token", "")))
        if ruta in ("/api/proyectos/importar", "/api/proyectos/nuevo"):
            nuevo = ruta.endswith("nuevo")
            nombre = (cuerpo.get("nombre") or "").strip()
            repos = [r.strip() for r in cuerpo.get("repos", []) if r.strip()]
            stack = cuerpo.get("stack") or "vacio"
            desc = (cuerpo.get("descripcion") or "").strip()
            if not E.NOMBRE_OK.match(nombre) or not repos:
                return self._json({"error": "Nombre (minúsculas, números, guiones) y al menos un repo"}, 400)
            tid = lanzar_trabajo(f"{'Nuevo' if nuevo else 'Importar'} {nombre}",
                                 lambda log: E.crear_proyecto(nombre, repos, nuevo, stack, desc, log))
            return self._json({"trabajo": tid})
        self._json({"error": "no encontrado"}, 404)


def servir(puerto: int = 8765, abrir: bool = True) -> None:
    srv = ThreadingHTTPServer(("127.0.0.1", puerto), Manejador)
    url = f"http://127.0.0.1:{puerto}"
    print(f"Panel del Equipo IA en {url}  (Ctrl+C para cerrarlo; los equipos arrancados siguen en marcha)")
    if abrir:
        for cmd in (["explorer.exe", url], ["wslview", url], ["xdg-open", url]):
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                break
            except FileNotFoundError:
                continue
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("Panel cerrado.")


PAGINA = (Path(__file__).resolve().parent / "panel.html").read_text(encoding="utf-8") \
    if (Path(__file__).resolve().parent / "panel.html").exists() else "<p>Falta panel.html</p>"
