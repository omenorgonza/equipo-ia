#!/usr/bin/env python3
"""Revisión de mantenimiento: detecta hallazgos con reglas y fuentes verificables y crea o actualiza
UNA propuesta (issue + tarjeta en Planning) por hallazgo. Pensado para GitHub Actions (PC apagado).

Uso:  python .equipo-ia/mantenimiento.py [--simulacion aviso|aviso-modificado] [--seco]
Entorno: GH_TOKEN (token con repo + project), GITHUB_REPOSITORY, opcional GITHUB_RUN_ID/GITHUB_SERVER_URL.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
import tablero_lib as T  # noqa: E402

RAIZ = AQUI.parent
CONFIG = json.loads((AQUI / "mantenimiento.json").read_text(encoding="utf-8"))
GH = json.loads(os.environ.get("EQUIPO_IA_GH_BIN", '["gh"]'))
REPO = os.environ.get("GITHUB_REPOSITORY") or CONFIG["repo"]
HOY = dt.date.fromisoformat(os.environ["EQUIPO_IA_HOY"]) if os.environ.get("EQUIPO_IA_HOY") else dt.date.today()
RUN_URL = (f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{REPO}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
           if os.environ.get("GITHUB_RUN_ID") else "(ejecución local)")
SEVERIDAD_A_PRIORIDAD = {"critical": "P0", "high": "P1", "medium": "P2", "moderate": "P2", "low": "P3"}
PENDIENTE_PRO = "exposición en producción pendiente de confirmar"


def gh(*args, stdin_text=None, comprobar=True) -> str:
    r = subprocess.run(GH + list(args), capture_output=True, text=True, encoding="utf-8", errors="replace",
                       input=stdin_text, timeout=120)
    if comprobar and r.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])}: {(r.stderr or r.stdout).strip()[:500]}")
    return r.stdout


def http_json(url: str, timeout=30):
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "equipo-ia-mantenimiento"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def git(*args) -> str:
    r = subprocess.run(["git", *args], cwd=RAIZ, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


# --------------------------------------------------------------------------- producción

def sha_produccion() -> tuple[str | None, str]:
    """SHA del último despliegue correcto del entorno configurado (Deployments API)."""
    entorno = CONFIG.get("produccion", {}).get("entorno")
    if not entorno:
        return None, "sin entorno de producción configurado"
    try:
        deps = json.loads(gh("api", f"repos/{REPO}/deployments?environment={entorno}&per_page=30"))
        for d in deps:
            estados = json.loads(gh("api", f"repos/{REPO}/deployments/{d['id']}/statuses?per_page=10"))
            if estados and estados[0]["state"] == "success":
                return d["sha"], f"despliegue {d['id']} en {entorno}" + (" [SIMULADO]" if "SIMULADO" in (d.get("description") or "") else "")
        return None, f"ningún despliegue correcto en {entorno}"
    except Exception as e:  # noqa: BLE001
        return None, f"no se pudo leer despliegues: {e}"


def archivo_en(sha: str | None, ruta: str) -> str | None:
    if sha:
        return git("show", f"{sha}:{ruta}") or None
    p = RAIZ / ruta
    return p.read_text(encoding="utf-8") if p.exists() else None


# --------------------------------------------------------------------------- lectores de versiones

def versiones_bloqueo(sha: str | None = None) -> dict[str, tuple[str, str]]:
    """{paquete: (version, archivo)} leído de archivos de bloqueo y de versión de runtime."""
    v: dict[str, tuple[str, str]] = {}
    for ruta in CONFIG.get("versiones", {}).get("archivos", []):
        texto = archivo_en(sha, ruta)
        if not texto:
            continue
        nombre = Path(ruta).name
        if nombre == ".python-version":
            v["python"] = (texto.strip().splitlines()[0], ruta)
        elif nombre.startswith("requirements") and nombre.endswith(".txt"):
            for l in texto.splitlines():
                m = re.match(r"^\s*([A-Za-z0-9_.\-]+)\s*==\s*([^\s;#]+)", l)
                if m:
                    v[m.group(1).lower()] = (m.group(2), ruta)
        elif nombre == "composer.lock":
            for pk in json.loads(texto).get("packages", []):
                v[pk["name"].lower()] = (pk["version"].lstrip("v"), ruta)
        elif nombre == "package-lock.json":
            for k, pk in json.loads(texto).get("packages", {}).items():
                if k.startswith("node_modules/") and "version" in pk:
                    v[k.split("node_modules/")[-1].lower()] = (pk["version"], ruta)
    return v


def ciclo_de(producto_ciclos: list[dict], version: str) -> dict | None:
    mejores = [c for c in producto_ciclos if version == str(c["cycle"]) or version.startswith(str(c["cycle"]) + ".")]
    return max(mejores, key=lambda c: len(str(c["cycle"])), default=None)


# --------------------------------------------------------------------------- fuentes

def fuente_versiones(prod_sha) -> list[dict]:
    cfg = CONFIG.get("versiones", {})
    repo_v, pro_v = versiones_bloqueo(None), versiones_bloqueo(prod_sha) if prod_sha else {}
    salida = []
    for paquete, producto in cfg.get("productos", {}).items():
        if paquete not in repo_v:
            continue
        version, archivo = repo_v[paquete]
        ciclos = http_json(f"https://endoflife.date/api/{producto}.json")
        c = ciclo_de(ciclos, version)
        if not c:
            continue
        eol = c.get("eol")
        if eol is True:
            fecha_eol = None
            vencido = True
        elif eol in (False, None):
            continue
        else:
            fecha_eol = dt.date.fromisoformat(str(eol))
            vencido = fecha_eol <= HOY
        dias = (fecha_eol - HOY).days if fecha_eol else 0
        if not vencido and dias > cfg.get("dias_aviso_eol", 180):
            continue
        mas_reciente = str(ciclos[0]["cycle"])
        salida.append({
            "clave": f"versiones:{REPO}:{producto}:{c['cycle']}",
            "titulo": f"{'Fin de soporte' if vencido else 'Fin de soporte próximo'}: {producto} {c['cycle']}",
            "categoria": "Versiones y migraciones", "componente": f"{producto} ({archivo})",
            "version_repo": version,
            "version_pro": (pro_v.get(paquete, ("?",))[0] if prod_sha else PENDIENTE_PRO),
            "evidencia": f"endoflife.date: ciclo {c['cycle']} eol={eol}; último ciclo {mas_reciente}",
            "enlace": f"https://endoflife.date/{producto}",
            "impacto": "Sin parches de seguridad del fabricante" if vencido else f"El soporte termina el {fecha_eol}",
            "accion": f"Migrar {producto} {c['cycle']} → {mas_reciente} (o el ciclo soportado más reciente compatible)",
            "esfuerzo": "M", "prioridad": "P1" if vencido else "P2",
            "plazo": str(fecha_eol) if fecha_eol else "vencido",
            "cierre": f"{archivo} usa un ciclo de {producto} con soporte y las pruebas pasan",
        })
    return salida


def fuente_seguridad(prod_sha) -> list[dict]:
    alertas = json.loads(gh("api", f"repos/{REPO}/dependabot/alerts?state=open&per_page=100"))
    repo_v, pro_v = versiones_bloqueo(None), versiones_bloqueo(prod_sha) if prod_sha else {}
    salida = []
    for a in alertas:
        dep, adv, vul = a["dependency"], a["security_advisory"], a.get("security_vulnerability") or {}
        paquete = dep["package"]["name"]
        sev = (adv.get("severity") or "medium").lower()
        parche = (vul.get("first_patched_version") or {}).get("identifier") or "sin versión corregida publicada"
        salida.append({
            "clave": f"seguridad:{REPO}:{dep['package']['ecosystem']}:{paquete}:{adv['ghsa_id']}",
            "titulo": f"Seguridad ({sev}): {paquete} — {adv['summary'][:70]}",
            "categoria": "Parches de seguridad", "componente": f"{paquete} ({dep.get('manifest_path')})",
            "version_repo": repo_v.get(paquete.lower(), (vul.get("vulnerable_version_range", "?"),))[0],
            "version_pro": (pro_v.get(paquete.lower(), ("?",))[0] if prod_sha else PENDIENTE_PRO),
            "evidencia": f"Dependabot #{a['number']} · {adv['ghsa_id']}{' / ' + adv['cve_id'] if adv.get('cve_id') else ''} · "
                         f"rango vulnerable {vul.get('vulnerable_version_range', '?')} · corregida en {parche}",
            "enlace": a["html_url"],
            "impacto": f"Vulnerabilidad {sev} abierta mientras no se actualice",
            "accion": f"Actualizar {paquete} a {parche} o superior (revisar la PR de Dependabot si existe)",
            "esfuerzo": "S", "prioridad": SEVERIDAD_A_PRIORIDAD.get(sev, "P2"), "plazo": "lo antes posible" if sev in ("critical", "high") else "próximo ciclo",
            "cierre": f"La alerta Dependabot #{a['number']} queda cerrada como corregida",
        })
    return salida


def _normalizar(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")


def _items_boe(nodo):
    if isinstance(nodo, dict):
        if "identificador" in nodo and "titulo" in nodo:
            yield nodo
        for v in nodo.values():
            yield from _items_boe(v)
    elif isinstance(nodo, list):
        for v in nodo:
            yield from _items_boe(v)


def palabras_normativa(base: list[str], extra: str | None = None) -> list[str]:
    """Palabras de mantenimiento.json + las de NORMATIVA_PALABRAS (separadas por comas), sin duplicados.

    Sin la variable (o vacía) devuelve exactamente `base`. Los duplicados se comparan sin mayúsculas ni tildes.
    """
    if extra is None:
        extra = os.environ.get("NORMATIVA_PALABRAS", "")
    salida = list(base)
    vistas = {_normalizar(p.strip()) for p in base}
    for p in extra.split(","):
        p = " ".join(p.split())
        if p and _normalizar(p) not in vistas:
            vistas.add(_normalizar(p))
            salida.append(p)
    return salida


def fuente_normativa(_prod_sha) -> list[dict]:
    salida = []
    for f in CONFIG.get("normativa", {}).get("fuentes", []):
        if not f.get("activa", True):
            continue
        if f["tipo"] != "boe-sumario":
            raise RuntimeError(f"Tipo de fuente no implementado: {f['tipo']} ({f['nombre']})")
        palabras = [(_normalizar(p), p) for p in palabras_normativa(f.get("palabras", []))]
        for d in range(f.get("dias", 7)):
            fecha = HOY - dt.timedelta(days=d)
            try:
                datos = http_json(f"https://boe.es/datosabiertos/api/boe/sumario/{fecha:%Y%m%d}")
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    continue  # día sin BOE (domingos)
                raise
            for it in _items_boe(datos):
                titulo = it["titulo"]
                t = _normalizar(titulo)
                hits = [orig for norm, orig in palabras if norm in t]
                if not hits:
                    continue
                url = it.get("url_html") or f"https://www.boe.es/buscar/doc.php?id={it['identificador']}"
                if isinstance(url, dict):
                    url = url.get("texto", "")
                vigor = re.search(r"entrar[áa] en vigor[^.]*", titulo, re.I)
                salida.append({
                    "clave": f"normativa:{REPO}:BOE:{it['identificador']}",
                    "titulo": f"Normativa (BOE {fecha:%d/%m/%Y}): {titulo[:80]}",
                    "categoria": "Normativa", "componente": f"función: {f.get('funcion', 'por determinar')}",
                    "version_repo": "n/a", "version_pro": "n/a",
                    "evidencia": f"{it['identificador']} publicado el {fecha:%Y-%m-%d}; coincide con: {', '.join(hits)}. "
                                 f"Fecha de aplicación: {vigor.group(0) if vigor else 'no consta en el sumario'}. "
                                 "Aplicabilidad pendiente de validación humana.",
                    "enlace": url, "impacto": "Posible obligación nueva o cambio de requisitos (por validar)",
                    "accion": "Leer la disposición y decidir si afecta; si afecta, el TL define la tarea",
                    "esfuerzo": "?", "prioridad": f.get("prioridad", "P3"), "plazo": "según la disposición",
                    "cierre": "Óscar o el TL registran en Notas si aplica y, si aplica, existe la tarea derivada",
                })
    return salida


def fuente_deuda(_prod_sha) -> list[dict]:
    cfg = CONFIG.get("deuda", {})
    salida = []
    desde = (HOY - dt.timedelta(days=cfg.get("dias", 14))).isoformat()
    wf = cfg.get("workflow_pruebas", "pruebas.yml")
    runs = json.loads(gh("api", f"repos/{REPO}/actions/workflows/{wf}/runs?per_page=100&created=>={desde}")).get("workflow_runs", [])
    por_sha: dict[str, list[dict]] = {}
    for r in runs:
        if r.get("conclusion") in ("success", "failure"):
            por_sha.setdefault(r["head_sha"], []).append(r)
    inestables = {s: rs for s, rs in por_sha.items() if {r["conclusion"] for r in rs} == {"success", "failure"}}
    if inestables:
        enlaces = [r["html_url"] for rs in inestables.values() for r in rs][:6]
        salida.append({
            "clave": f"deuda:{REPO}:test-inestable:{wf}",
            "titulo": f"Deuda técnica: pruebas inestables en {wf}",
            "categoria": "Deuda técnica", "componente": wf, "version_repo": "n/a", "version_pro": "n/a",
            "evidencia": f"{len(inestables)} commit(s) con éxito y fallo en el mismo SHA en {cfg.get('dias', 14)} días: "
                         + " ".join(enlaces),
            "enlace": enlaces[0], "impacto": "Las PR se validan con ruido; se reintenta a ciegas y se ocultan fallos reales",
            "accion": "Localizar el test no determinista (ver logs enlazados) y hacerlo determinista o aislarlo",
            "esfuerzo": "S", "prioridad": "P2", "plazo": "—",
            "cierre": f"Sin éxito/fallo en el mismo SHA durante {cfg.get('dias', 14)} días",
        })
    prs = json.loads(gh("pr", "list", "--repo", REPO, "--author", "app/dependabot", "--state", "open",
                        "--json", "number,title,url,createdAt,statusCheckRollup"))
    for p in prs:
        antig = (HOY - dt.date.fromisoformat(p["createdAt"][:10])).days
        fallos = [c for c in p.get("statusCheckRollup") or [] if c.get("conclusion") == "FAILURE"]
        if fallos and antig >= cfg.get("dias_pr_bloqueada", 7):
            m = re.search(r"[Bb]ump (\S+)", p["title"])
            paquete = m.group(1) if m else f"pr{p['number']}"
            salida.append({
                "clave": f"deuda:{REPO}:actualizacion-bloqueada:{paquete}",
                "titulo": f"Deuda técnica: la actualización de {paquete} no pasa las pruebas",
                "categoria": "Deuda técnica", "componente": paquete, "version_repo": "ver PR", "version_pro": "n/a",
                "evidencia": f"PR #{p['number']} abierta hace {antig} días con comprobaciones fallidas: "
                             + ", ".join(c.get("name", "?") for c in fallos),
                "enlace": p["url"], "impacto": "La dependencia queda congelada y acumula versiones (y posibles parches)",
                "accion": "Adaptar el código a la nueva versión o fijar el motivo del bloqueo",
                "esfuerzo": "M", "prioridad": "P2", "plazo": "—", "cierre": f"PR #{p['number']} integrada o sustituida",
            })
    return salida


def simulados(modo: str) -> list[dict]:
    """Avisos simulados, identificados como tales, para ensayar el recorrido."""
    parche = "1.0.1" if modo == "aviso" else "1.0.2"
    return [{
        "clave": f"seguridad:{REPO}:pip:paquete-simulado:GHSA-SIMU-0000-0001",
        "titulo": "[SIMULADO] Seguridad (critical): paquete-simulado — ejecución remota de código",
        "categoria": "Parches de seguridad", "componente": "paquete-simulado (requirements.txt)",
        "version_repo": "1.0.0", "version_pro": PENDIENTE_PRO,
        "evidencia": f"AVISO SIMULADO para el ensayo · GHSA-SIMU-0000-0001 · rango vulnerable < {parche} · corregida en {parche}",
        "enlace": "https://github.com/advisories (simulado: no existe)",
        "impacto": "Ensayo: ninguno real", "accion": f"Ensayo: actualizar a {parche}", "esfuerzo": "S",
        "prioridad": "P0", "plazo": "ensayo", "cierre": "Cerrar a mano al terminar el ensayo", "simulado": True,
    }]


FUENTES = {"versiones": fuente_versiones, "seguridad": fuente_seguridad,
           "normativa": fuente_normativa, "deuda": fuente_deuda}


# --------------------------------------------------------------------------- propuestas

CAMPOS_HUELLA = ("titulo", "componente", "version_repo", "version_pro", "evidencia", "enlace", "impacto",
                 "accion", "prioridad", "plazo", "cierre")


def huella(h: dict) -> str:
    return hashlib.sha256(json.dumps({k: h.get(k) for k in CAMPOS_HUELLA}, sort_keys=True).encode()).hexdigest()[:16]


def bloque_auto(h: dict) -> str:
    filas = [("Categoría", h["categoria"]), ("Componente", h["componente"]),
             ("Versión en el repositorio", h["version_repo"]), ("Versión desplegada", h["version_pro"]),
             ("Evidencia", f"{h['evidencia']} — [enlace]({h['enlace']})" if h["enlace"].startswith("http") else h["evidencia"]),
             ("Impacto de aplazar", h["impacto"]), ("Acción sugerida", h["accion"]),
             ("Esfuerzo aproximado", h["esfuerzo"]), ("Prioridad sugerida", h["prioridad"]),
             ("Plazo conocido", h["plazo"]), ("Criterio de cierre", h["cierre"]),
             ("Última actualización automática", f"{HOY} · {RUN_URL}")]
    tabla = "\n".join(f"| {k} | {str(v).replace('|', '/')} |" for k, v in filas)
    return (f"<!-- auto:inicio -->\n## Propuesta de mantenimiento{' (SIMULADA)' if h.get('simulado') else ''}\n\n"
            f"| Campo | Valor |\n|---|---|\n{tabla}\n\n"
            "_Esta sección la actualiza el proceso de mantenimiento. Escribe tus notas debajo._\n<!-- auto:fin -->")


PARTE_EDITABLE = """

## Notas de Óscar

_(se conservan en cada actualización)_

## Para pasar a To Do (lo completa el TL)

### Objetivo

_A completar por el TL._

### Agente

_No response_

### Rama base

main

### Archivos permitidos

_No response_

### Criterios de aceptación

_No response_

### Comando de prueba

_No response_

### Dependencias

ninguna
"""


def marcadores(clave: str, hue: str) -> str:
    return f"<!-- equipo-ia:clave={clave} -->\n<!-- equipo-ia:huella={hue} -->\n"


def propuestas_existentes() -> dict[str, dict]:
    issues = json.loads(gh("issue", "list", "--repo", REPO, "--label", "mantenimiento", "--state", "all",
                           "--limit", "1000", "--json", "number,body,state,title,id"))
    salida = {}
    for i in issues:
        m = re.search(r"<!-- equipo-ia:clave=(.+?) -->", i["body"] or "")
        if m:
            h = re.search(r"<!-- equipo-ia:huella=(\w+) -->", i["body"])
            salida[m.group(1)] = {**i, "huella": h.group(1) if h else ""}
    return salida


def asegurar_etiquetas() -> None:
    for nombre, color in [("mantenimiento", "5319E7"), ("simulado", "C5DEF5"), ("registro-mantenimiento", "BFDADC")]:
        gh("label", "create", nombre, "--repo", REPO, "--color", color, "--force", comprobar=False)


def aplicar(hallazgos: list[dict], tablero: T.Tablero | None, seco: bool) -> dict:
    existentes = propuestas_existentes()
    res = {"creadas": [], "actualizadas": [], "sin_cambios": [], "tratadas_con_cambios": []}
    for h in hallazgos:
        hue = huella(h)
        e = existentes.get(h["clave"])
        if e and e["huella"] == hue:
            res["sin_cambios"].append(e["number"])
            continue
        if seco:
            res["creadas" if not e else "actualizadas"].append(h["clave"])
            continue
        if e is None:
            cuerpo = marcadores(h["clave"], hue) + bloque_auto(h) + PARTE_EDITABLE
            etiquetas = ["mantenimiento"] + (["simulado"] if h.get("simulado") else [])
            args = ["issue", "create", "--repo", REPO, "--title", h["titulo"], "--body-file", "-"]
            for etq in etiquetas:
                args += ["--label", etq]
            url = gh(*args, stdin_text=cuerpo).strip()
            numero = int(url.rstrip("/").split("/")[-1])
            if tablero:
                nodo = json.loads(gh("issue", "view", str(numero), "--repo", REPO, "--json", "id"))["id"]
                item = tablero.anadir(nodo)
                tablero.mover(item, T.PLANNING)
                tablero.poner_opcion(item, T.CAMPO_PRIORIDAD, T.prioridad_por_codigo(h["prioridad"]))
            res["creadas"].append(numero)
            continue
        # Existe con evidencia distinta: se sustituye solo la sección automática; notas, Estado y Prioridad se conservan.
        cuerpo = e["body"]
        cuerpo = re.sub(r"<!-- equipo-ia:huella=\w+ -->", f"<!-- equipo-ia:huella={hue} -->", cuerpo)
        cuerpo = re.sub(r"<!-- auto:inicio -->.*?<!-- auto:fin -->", lambda _m: bloque_auto(h), cuerpo, flags=re.S)
        gh("issue", "edit", str(e["number"]), "--repo", REPO, "--body-file", "-", stdin_text=cuerpo)
        nota = (f"🔄 La evidencia ha cambiado ({HOY}): {h['evidencia']}\n\nPrioridad sugerida ahora: {h['prioridad']}. "
                f"Estado y prioridad del tablero no se han tocado. Ejecución: {RUN_URL}")
        gh("issue", "comment", str(e["number"]), "--repo", REPO, "--body-file", "-", stdin_text=nota)
        res["actualizadas" if e["state"] == "OPEN" else "tratadas_con_cambios"].append(e["number"])
    return res


def actualizar_registro(resumen: dict) -> None:
    issues = json.loads(gh("issue", "list", "--repo", REPO, "--label", "registro-mantenimiento", "--state", "all",
                           "--limit", "5", "--json", "number,body"))
    previo = {}
    if issues:
        m = re.search(r"```json\n(.*?)\n```", issues[0]["body"] or "", re.S)
        previo = json.loads(m.group(1)) if m else {}
    estado = {"ultima_ejecucion": {"fecha": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                                   "enlace": RUN_URL, "parcial": resumen["parcial"], "errores": resumen["errores"],
                                   "resultado": resumen["resultado"]},
              "ultima_correcta": previo.get("ultima_correcta")}
    if not resumen["parcial"]:
        estado["ultima_correcta"] = {"fecha": estado["ultima_ejecucion"]["fecha"], "enlace": RUN_URL}
    cuerpo = ("Registro del proceso de mantenimiento (lo actualiza el workflow; no hace falta tocarlo).\n\n"
              f"- Última ejecución: {estado['ultima_ejecucion']['fecha']} — {'PARCIAL' if resumen['parcial'] else 'completa'} — {RUN_URL}\n"
              f"- Última ejecución correcta: {(estado['ultima_correcta'] or {}).get('fecha', 'ninguna')} — "
              f"{(estado['ultima_correcta'] or {}).get('enlace', '')}\n\n```json\n{json.dumps(estado, indent=2, ensure_ascii=False)}\n```\n")
    if issues:
        gh("issue", "edit", str(issues[0]["number"]), "--repo", REPO, "--body-file", "-", stdin_text=cuerpo)
    else:
        gh("issue", "create", "--repo", REPO, "--title", "Registro de mantenimiento", "--label",
           "registro-mantenimiento", "--body-file", "-", stdin_text=cuerpo)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--simulacion", choices=["ninguna", "aviso", "aviso-modificado"], default="ninguna")
    ap.add_argument("--seco", action="store_true", help="No escribe en GitHub")
    a = ap.parse_args()
    prod_sha, prod_desc = sha_produccion()
    print(f"Producción: {prod_sha or PENDIENTE_PRO} ({prod_desc})")
    hallazgos, errores = [], {}
    for nombre, fn in FUENTES.items():
        if not CONFIG.get("categorias", {}).get(nombre, True):
            continue
        try:
            nuevos = fn(prod_sha)
            print(f"  {nombre}: {len(nuevos)} hallazgo(s)")
            hallazgos += nuevos
        except Exception as e:  # noqa: BLE001 — una fuente caída no detiene las demás
            errores[nombre] = str(e)[:300]
            print(f"  {nombre}: ERROR {e}")
    if a.simulacion != "ninguna":
        hallazgos += simulados(a.simulacion)
    tablero = None
    tb = CONFIG.get("tablero", {})
    owner = os.environ.get("TABLERO_OWNER") or tb.get("owner")
    numero = os.environ.get("TABLERO_NUMERO") or tb.get("numero")
    if owner and numero:
        tablero = T.Tablero(owner, int(numero), tb.get("owner_tipo", "user"), GH)
    elif not a.seco:
        errores["tablero"] = "TABLERO_OWNER/TABLERO_NUMERO sin configurar: las propuestas no se añaden al tablero"
    if not a.seco:
        asegurar_etiquetas()
    resultado = aplicar(hallazgos, tablero, a.seco)
    resumen = {"parcial": bool(errores), "errores": errores, "resultado": resultado,
               "produccion": {"sha": prod_sha, "detalle": prod_desc}, "hallazgos": [h["clave"] for h in hallazgos]}
    if not a.seco:
        actualizar_registro(resumen)
    Path(os.environ.get("EQUIPO_IA_SALIDA", "resumen-mantenimiento.json")).write_text(
        json.dumps(resumen, indent=2, ensure_ascii=False), encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(f"## Mantenimiento {'PARCIAL' if errores else 'completo'}\n\n```json\n"
                     f"{json.dumps(resumen, indent=2, ensure_ascii=False)}\n```\n")
    print(json.dumps(resumen, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
