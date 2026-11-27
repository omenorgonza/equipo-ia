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


UMBRAL_ATASCO_S = 300   # sin actividad del agente (o de la CI) durante más de esto → «posible atasco»
LINEAS_PROGRESO = 60


def leer_progreso(nombre: str) -> dict[str, dict]:
    """Entradas de estado/progreso.json escritas por un coordinador vivo (las de un proceso caído no cuentan)."""
    p = E.PROYECTOS / nombre / "estado" / "progreso.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(d, dict) or not C.pid_vivo(int(d.get("pid") or 0)):
        return {}
    return {k: v for k, v in (d.get("tareas") or {}).items() if isinstance(v, dict)}


def tiempos_pasos(nombre: str) -> dict[str, list[tuple[int, float]]]:
    """Duración (s) de cada paso en las tareas registradas, de `tiempos` en registro.db."""
    db = E.PROYECTOS / nombre / "estado" / "registro.db"
    if not db.exists():
        return {}
    con = sqlite3.connect(str(db))
    salida: dict[str, list[tuple[int, float]]] = {}
    try:
        for issue, tiempos in con.execute("SELECT issue, tiempos FROM tareas"):
            try:
                t = json.loads(tiempos or "{}")
            except ValueError:
                continue
            for paso, v in t.items():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    salida.setdefault(paso, []).append((issue, float(v)))
    except sqlite3.Error:
        return {}
    finally:
        con.close()
    return salida


def archivos_cambiados(worktree: str | None) -> int | None:
    if not worktree or not Path(worktree).is_dir():
        return None
    try:
        # --no-optional-locks: solo mirar, sin coger index.lock (si no, choca con el git add del coordinador).
        out = E.git("--no-optional-locks", "status", "--porcelain", cwd=Path(worktree), comprobar=False)
    except Exception:  # noqa: BLE001
        return None
    return len([l for l in out.splitlines() if l.strip()])


def progreso_tareas(nombre: str, cfg: dict) -> dict[int, dict]:
    """Progreso en directo de cada tarea en curso: paso, minutos, límite, última actividad y archivos cambiados."""
    tareas = leer_progreso(nombre)
    if not tareas:
        return {}
    umbral = float(cfg.get("umbral_atasco_s") or UMBRAL_ATASCO_S)
    ahora = time.time()
    tiempos = tiempos_pasos(nombre)
    salida = {}
    for e in tareas.values():
        try:
            n = int(e["issue"])
        except (KeyError, TypeError, ValueError):
            continue
        paso = e.get("paso") or "?"
        inactivo = max(0.0, ahora - float(e.get("ultima_actividad_ts") or ahora))
        limite = e.get("limite_s")
        previos = [s for i, s in tiempos.get(paso, []) if i != n]
        salida[n] = {
            "numero": n, "agente": e.get("agente"), "paso": paso,
            "minutos": int((ahora - float(e.get("inicio_paso_ts") or ahora)) // 60),
            "minutos_tarea": int((ahora - float(e.get("inicio_tarea_ts") or ahora)) // 60),
            "limite_s": limite, "limite_min": round(limite / 60) if limite else None,
            "inicio_tarea": e.get("inicio_tarea"), "inicio_paso": e.get("inicio_paso"),
            "ultima_actividad": e.get("ultima_actividad"), "inactivo_s": int(inactivo),
            "ultima_linea": C.redactar(str(e.get("ultima_linea") or ""))[:300],
            "pensando_s": e["pensando_s"] if isinstance(e.get("pensando_s"), int) else None,
            "archivos_cambiados": archivos_cambiados(e.get("worktree")),
            "estimado_min": round(sum(previos) / len(previos) / 60, 1) if previos else None,
            "atasco": inactivo > umbral, "umbral_atasco_s": int(umbral)}
    return salida


def log_progreso(nombre: str, numero: int) -> dict:
    """Últimas líneas de estado/agentes/issue-N.log (vuelven a filtrarse por si acaso) y el progreso actual."""
    p = E.PROYECTOS / nombre / "estado" / "agentes" / f"issue-{numero}.log"
    if p.exists():
        lineas = p.read_text(encoding="utf-8", errors="replace").splitlines()[-LINEAS_PROGRESO:]
        texto = C.redactar("\n".join(lineas))
    else:
        texto = "(sin salida del agente todavía)"
    prog = progreso_tareas(nombre, E.cfg_proyecto(nombre)).get(numero)
    viva = prog["ultima_linea"] if prog and prog.get("pensando_s") else None
    if viva:  # «pensando… N s» aún no está en issue-N.log (solo se escribe al terminar): va al final, en vivo
        hora = str(prog.get("ultima_actividad") or "")[11:19]
        texto = (texto + "\n" if p.exists() else "") + (f"[{hora}] " if hora else "") + viva
    return {"numero": numero, "log": texto, "progreso": prog, "en_curso": prog is not None, "linea_viva": viva}


def siguiente_json(rec: dict) -> dict:
    """Recomendación de T.recomendar → JSON para el banner «¿Qué hago ahora?» (sin las claves tupla)."""
    if not rec:
        return {"resumen": "", "acciones": [], "esperas": [], "error": None}
    return {"resumen": rec.get("resumen", ""), "acciones": rec.get("acciones", []), "esperas": rec.get("esperas", []),
            "error": rec.get("error") or rec.get("error_prs"), "escritas": rec.get("escritas")}


LISTAS_PARA_DEPENDER = (T.REVIEW, T.DONE, T.PRO)   # misma regla que el coordinador: en review o cerrada
VIVAS = (T.TODO, T.DOING, T.REVIEW)                 # una dependencia en otro sitio deja la tarea esperando siempre


def dependencias_pendientes(it: dict, indice: dict, forzar=False) -> list[dict]:
    """Dependencias aún no listas de una tarjeta: sección «Dependencias» + relaciones «Blocked by» de GitHub."""
    repo, n = it["repo"], it["numero"]
    deps: dict[tuple[str, int], dict] = {}
    for d in T.datos_cuerpo(it.get("cuerpo") or "")["dependencias"]:
        deps[(repo.lower(), d)] = {"repo": repo, "numero": d}
    rel = cacheado(f"bloqueo:{repo}#{n}", 120, lambda: C.relaciones_bloqueo(
        gh_json("api", f"repos/{repo}/issues/{n}/dependencies/blocked_by?per_page=100") or [], repo), forzar)
    for r in rel if isinstance(rel, list) else []:
        deps[(r["repo"].lower(), r["numero"])] = r
    pendientes = []
    for clave, d in deps.items():
        otro = indice.get(clave)
        if otro:
            estado, abierta, url = otro["estado"], otro["abierta"], otro["url"]
        elif "abierta" in d:
            estado, abierta, url = None, d["abierta"], d["url"]
        else:
            st = cacheado(f"estado-issue:{d['repo']}#{d['numero']}", 300, lambda d=d: gh_json(
                "issue", "view", str(d["numero"]), "--repo", d["repo"], "--json", "state,url") or {}, forzar)
            st = st if isinstance(st, dict) else {}
            estado, abierta = None, st.get("state") != "CLOSED"
            url = st.get("url") or f"https://github.com/{d['repo']}/issues/{d['numero']}"
        if abierta and estado not in LISTAS_PARA_DEPENDER:
            pendientes.append({"numero": d["numero"], "repo": d["repo"], "url": url, "estado": estado,
                               "texto": f"#{d['numero']}" if d["repo"].lower() == repo.lower()
                               else f"{d['repo']}#{d['numero']}"})
    return pendientes


def estado_proyecto(nombre: str, forzar=False) -> dict:
    cfg = E.cfg_proyecto(nombre)
    repos = cfg.get("repos") or [cfg.get("repo")]
    tb = cfg.get("tablero") or {}
    salida = {"nombre": nombre, "descripcion": cfg.get("descripcion", ""), "color": E.color_proyecto(nombre),
              "repos": [], "tablero": tb.get("url"),
              "activo": E.coordinador_activo(nombre), "columnas": {e: 0 for e in T.ESTADOS}, "atencion": [],
              "tarjetas": {}, "error": None, "pruebas": pruebas_proyecto(cfg), "progreso": [],
              "siguiente": siguiente_json({})}
    try:
        prog = progreso_tareas(nombre, cfg)
    except Exception:  # noqa: BLE001 — el panel nunca se cae por el progreso
        prog = {}
    repo_cola = (cfg.get("repo") or "").lower()
    vistos: set[int] = set()

    def items():
        """Tarjetas y siguiente paso de la misma lectura. Con el equipo parado, el panel mantiene al día el campo
        Siguiente del tablero (solo escribe lo que cambia); con el equipo en marcha lo hace el coordinador."""
        t = T.Tablero(tb["owner"], tb["numero"], tb.get("owner_tipo", "user"), E.gh_bin())
        its = t.items()
        try:
            escribir = not E.coordinador_activo(nombre) and T.CAMPO_SIGUIENTE in t.campos
            rec = t.siguiente(repos, escribir=escribir, items=its)
        except Exception as e:  # noqa: BLE001 — sin recomendación, el resto del panel sigue
            rec = {"error": str(e)[:300]}
        return {"items": its, "siguiente": rec}

    def vistas():
        t = T.Tablero(tb["owner"], tb["numero"], tb.get("owner_tipo", "user"), E.gh_bin())
        info = t.info()
        return {"nombres": [v["name"] for v in info["views"]["nodes"]], "agrupacion": T.aviso_agrupacion(info),
                "sin_siguiente": T.CAMPO_SIGUIENTE not in {f["name"] for f in info["fields"]["nodes"] if f}}

    if tb.get("numero"):
        lectura = cacheado(f"items:{nombre}", 60, items, forzar)
        if isinstance(lectura, dict) and lectura.get("error"):
            salida["error"] = lectura["error"]
            lectura = {"items": [], "siguiente": {}}
        its, rec = lectura["items"], lectura.get("siguiente") or {}
        salida["siguiente"] = siguiente_json(rec)
        prs = prs_registro(nombre)
        indice = {((x["repo"] or "").lower(), x["numero"]): x for x in its}
        grupos: dict[str, list] = {}
        for it in its:
            if not it["abierta"] and it["estado"] not in (T.DONE, T.PRO):
                continue
            e = it["estado"] or "(sin estado)"
            if e in salida["columnas"]:
                salida["columnas"][e] += 1
            tarjeta = {"numero": it["numero"], "titulo": it["titulo"], "url": it["url"], "prioridad": it["prioridad"],
                       "bloqueo": it["bloqueo"], "pr": prs.get(it["numero"]), "repo": it["repo"],
                       "siguiente": (rec.get("tarjetas") or {}).get((it["repo"].lower(), it["numero"]), ""),
                       "agente": next((x.split(":")[1] for x in it["etiquetas"] if x.startswith("agent:")), None)}
            pg = prog.get(it["numero"]) if (not repo_cola or (it["repo"] or "").lower() == repo_cola) else None
            if pg is not None:
                vistos.add(it["numero"])
                # To Do: la caché del tablero (60 s) aún no ha visto el paso a Doing. Fuera de Doing, no se muestra.
                if e in (T.DOING, T.TODO):
                    pg = {**pg, "titulo": it["titulo"], "url": it["url"]}
                    tarjeta["progreso"] = pg
                    salida["progreso"].append(pg)
            grupos.setdefault(e, []).append(tarjeta)
            if e == T.TODO and it["abierta"]:
                tarjeta["espera"] = dependencias_pendientes(it, indice, forzar)
                for d in tarjeta["espera"]:
                    if d["estado"] in VIVAS:
                        continue
                    donde = f"en {d['estado']}" if d["estado"] else "fuera del tablero"
                    salida["atencion"].append({
                        "nivel": "alta", "tipo": "dependencia", "numero": it["numero"], "url": d["url"],
                        "texto": f"#{it['numero']} espera a {d['texto']}, que está {donde}: se quedaría esperando "
                                 f"para siempre (mueve {d['texto']} a To Do o saca #{it['numero']} de To Do)"})
            if it["bloqueo"]:
                salida["atencion"].append({"nivel": "alta", "tipo": "bloqueo", "numero": it["numero"],
                                           "texto": f"#{it['numero']} bloqueada: {it['bloqueo'][:160]}",
                                           "url": it["url"], "reintentar": "CI en rojo" in it["bloqueo"]
                                           or "sin modificar" in it["bloqueo"] or "Pruebas fallidas" in it["bloqueo"],
                                           "reanudar": True})
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
        if isinstance(vs, dict) and vs.get("sin_siguiente"):
            salida["atencion"].append({"nivel": "media", "tipo": "instalacion", "url": tb.get("url"),
                                       "texto": f"Falta el campo «{T.CAMPO_SIGUIENTE}» del tablero: "
                                                f"python3 equipo.py {nombre} tablero siguiente lo crea y lo rellena"})
        if isinstance(vs, dict) and "nombres" in vs:
            faltan = [v for v in (T.VISTA_TABLERO, "Planning") if v not in vs["nombres"]]
            if faltan:
                salida["atencion"].append({"nivel": "media", "tipo": "instalacion", "url": tb.get("url"),
                                           "texto": f"Crear las vistas del tablero: {', '.join(faltan)}"})
            if vs.get("agrupacion"):
                salida["atencion"].append({"nivel": "media", "tipo": "instalacion", "url": tb.get("url"),
                                           "texto": vs["agrupacion"]})
    else:
        salida["atencion"].append({"nivel": "media", "tipo": "instalacion", "texto": "El proyecto aún no tiene tablero",
                                   "url": None})
    for n, pg in prog.items():  # en curso pero la tarjeta aún no está en la caché del tablero
        if n not in vistos:
            salida["progreso"].append({**pg, "titulo": "", "url": None})
    salida["progreso"].sort(key=lambda x: x["numero"])
    for pg in salida["progreso"]:
        if pg["atasco"]:
            mins = pg["inactivo_s"] // 60
            hace = f"{mins} min" if mins else f"{pg['inactivo_s']} s"
            salida["atencion"].append({"nivel": "alta", "tipo": "atasco", "numero": pg["numero"], "url": pg["url"],
                                       "progreso": True,
                                       "texto": f"#{pg['numero']} posible atasco: sin actividad desde hace {hace} "
                                                f"(paso {pg['paso']}, {pg['agente']})"})

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


AGENTES_TAREA = ("claude", "local")
PRIORIDADES_TAREA = ("P0", "P1", "P2", "P3")


def _lineas(valor) -> list[str]:
    """Lista desde un array JSON o un texto con una entrada por línea; descarta vacíos."""
    if isinstance(valor, str):
        valor = valor.splitlines()
    return [str(x).strip() for x in (valor or []) if str(x).strip()]


def pruebas_proyecto(cfg: dict) -> list[str]:
    """Valores aceptados por `tablero.py nueva --prueba`: claves de pruebas y «ci» solo si hay ci.checks."""
    return list(cfg.get("pruebas") or {}) + (["ci"] if (cfg.get("ci") or {}).get("checks") else [])


def crear_tarea(nombre: str, d: dict) -> tuple[dict, int]:
    """Crea la tarjeta reutilizando `tablero.py nueva` (sus validaciones). Sin «todo» la deja en Planning."""
    titulo = (d.get("titulo") or "").strip()
    if not titulo:
        return {"error": "El título es obligatorio"}, 400
    if titulo.startswith("-"):
        return {"error": "El título no puede empezar por «-»"}, 400
    agente = (d.get("agente") or "").strip()
    if agente and agente not in AGENTES_TAREA:
        return {"error": f"Agente desconocido: {agente} (usa {', '.join(AGENTES_TAREA)})"}, 400
    prioridad = (d.get("prioridad") or "P2").strip()
    if prioridad not in PRIORIDADES_TAREA:
        return {"error": f"Prioridad no válida: {prioridad}"}, 400
    deps_txt = d.get("dependencias") or []
    if isinstance(deps_txt, str):
        deps_txt = re.split(r"[\s,]+", deps_txt)
    deps = []
    for x in deps_txt:
        x = str(x).strip().lstrip("#")
        if not x:
            continue
        if not x.isdigit():
            return {"error": f"Dependencia no válida: {x} (números de issue, p. ej. 12 o #12)"}, 400
        deps.append(x)
    todo = bool(d.get("todo"))
    # Forma --opcion=valor: valores que empiecen por «-» no se confunden con opciones.
    args = ["nueva", titulo, f"--prioridad={prioridad}"]
    if (d.get("objetivo") or "").strip():
        args.append(f"--objetivo={d['objetivo'].strip()}")
    if agente:
        args.append(f"--agente={agente}")
    args += [f"--archivo={a}" for a in _lineas(d.get("archivos"))]
    args += [f"--criterio={c}" for c in _lineas(d.get("criterios"))]
    if (d.get("prueba") or "").strip():
        args.append(f"--prueba={d['prueba'].strip()}")
    args += [f"--dep={n}" for n in deps]
    if todo:
        args.append("--todo")
    r = E.script(nombre, "tablero.py", *args, capturar=True, timeout=180)
    salida = (r.stdout or "").strip()
    if r.returncode != 0:
        error = (r.stderr or r.stdout or "").strip().splitlines()
        return {"error": error[-1] if error else "tablero.py nueva falló"}, 400
    m = re.search(r"^#(\d+) creada", salida, re.M)
    if not m:
        return {"error": f"Respuesta inesperada de tablero.py nueva: {salida[-300:]}"}, 500
    numero = int(m.group(1))
    estado = T.TODO if todo else T.BACKLOG
    if not todo:
        cfg = E.cfg_proyecto(nombre)
        tb = cfg["tablero"]
        try:
            t = T.Tablero(tb["owner"], tb["numero"], tb.get("owner_tipo", "user"), E.gh_bin())
            it = t.item_de_issue(cfg["repo"], numero)
            if not it:
                raise RuntimeError("no encuentro la tarjeta en el tablero")
            t.mover(it["item_id"], T.PLANNING)
            estado = T.PLANNING
        except Exception as e:  # noqa: BLE001 — la issue ya existe; se informa sin ocultarlo
            with _cache_lock:
                _cache.clear()
            return {"ok": True, "numero": numero, "estado": estado,
                    "mensaje": f"#{numero} creada en {estado}, pero no pude moverla a Planning: {str(e)[:200]}"}, 200
    with _cache_lock:
        _cache.clear()
    url = salida.splitlines()[0].rsplit(": ", 1)[-1] if ": " in salida else None
    return {"ok": True, "numero": numero, "estado": estado, "url": url,
            "mensaje": f"#{numero} creada en {estado}"}, 200


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


def cambiar_color(nombre: str, color) -> tuple[dict, int]:
    if color not in E.PALETA:
        return {"ok": False, "error": f"Color no válido; usa uno de: {', '.join(E.PALETA)}"}, 400
    E.guardar_cfg_proyecto(nombre, {"color": color})
    return {"ok": True, "color": color, "mensaje": f"Color de {nombre}: {color}"}, 200


def reanudar(nombre: str, numero: int) -> dict:
    """Continúa una tarea bloqueada desde su paso pendiente (sin --desde: no repite el trabajo del agente)."""
    r = E.script(nombre, "coordinador.py", "reanudar", str(numero), capturar=True, timeout=60)
    return {"ok": r.returncode == 0, "mensaje": (r.stdout or r.stderr).strip()[-300:]}


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
        m = re.match(r"^/api/proyecto/([a-z0-9-]+)/progreso/(\d{1,9})$", ruta)
        if m and m.group(1) in E.proyectos():
            return self._json(log_progreso(m.group(1), int(m.group(2))))
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
        m = re.match(r"^/api/proyecto/([a-z0-9-]+)/(arrancar|parar|reintentar|reanudar|color)$", ruta)
        if m:
            nombre, accion = m.groups()
            if nombre not in E.proyectos():
                return self._json({"error": "proyecto desconocido"}, 404)
            if accion == "color":
                return self._json(*cambiar_color(nombre, cuerpo.get("color")))
            if accion == "arrancar":
                return self._json(arrancar(nombre))
            if accion == "parar":
                return self._json(parar(nombre))
            if accion == "reanudar":
                return self._json(reanudar(nombre, int(cuerpo.get("numero", 0))))
            return self._json(reintentar(nombre, int(cuerpo.get("numero", 0))))
        m = re.match(r"^/api/proyecto/([a-z0-9-]+)/tarea$", ruta)
        if m:
            if m.group(1) not in E.proyectos():
                return self._json({"error": "proyecto desconocido"}, 404)
            return self._json(*crear_tarea(m.group(1), cuerpo))


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
