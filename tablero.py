#!/usr/bin/env python3
"""Tablero del equipo (GitHub Project privado).

  crear        Crea o reutiliza el proyecto, sus campos (Estado, Prioridad, Bloqueo, Siguiente) y lo enlaza al repo.
  verificar    Comprueba campos, vistas, privacidad y cada permiso con tu identidad local.
  migrar       Ensayo de migración desde las etiquetas de estado (solo lectura por defecto; --aplicar escribe).
  ver          Lista las tarjetas por Estado con prioridad, bloqueo y siguiente paso.
  nueva        Crea una tarea (issue + tarjeta) en Backlog o en To Do.
  siguiente    ¿Qué hago ahora? Calcula el siguiente paso y rellena el campo Siguiente (--ver: sin escribir).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parent
sys.path.insert(0, str(LAB / "repo-plantilla" / ".equipo-ia"))
import tablero_lib as T  # noqa: E402
import coordinador as C  # noqa: E402

OPCIONES_ESTADO = ",".join(T.ESTADOS)
OPCIONES_PRIORIDAD = ",".join(T.PRIORIDADES)
VISTAS = {
    "Tablero": "Disposición Board · agrupar (Column field) por Estado · ocultar el campo Status por defecto",
    "Planning": "Disposición Table · filtro `Estado:Planning` · ordenar por Prioridad ascendente, después Created",
}
ETIQUETA_A_ESTADO = {"ready": T.TODO, "running": T.DOING, "review": T.REVIEW}


def cfg_tablero(cfg: dict) -> T.Tablero:
    tb = cfg.get("tablero") or {}
    if not tb.get("numero"):
        sys.exit("config.json no tiene tablero.numero. Ejecuta: python tablero.py crear")
    return T.Tablero(tb["owner"], tb["numero"], tb.get("owner_tipo", "user"), cfg["gh_bin"])


def gh(cfg, *args, stdin_text=None, comprobar=True) -> str:
    r = C.ejecutar(cfg["gh_bin"] + list(args), cwd=LAB, timeout=120, stdin_text=stdin_text)
    if comprobar and r.returncode != 0:
        sys.exit(f"gh {' '.join(args[:3])} falló: {(r.stderr or r.stdout).strip()}")
    return r.stdout


def guardar_cfg(cambios: dict) -> None:
    p = C.PD / "config.json"
    cfg = json.loads(p.read_text(encoding="utf-8"))
    cfg.update(cambios)
    p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def plantilla_de(cfg: dict, a) -> tuple[str, int] | None:
    """Tablero que se copia (vistas, campos y workflows) al crear uno nuevo: --plantilla o config plantilla_tablero."""
    if getattr(a, "plantilla", None):
        owner, numero = a.plantilla.split("/")
        return owner, int(numero)
    p = cfg.get("plantilla_tablero") or {}
    ensayo = LAB / "proyectos" / "ensayo" / "config.json"
    if not p.get("numero") and ensayo.exists() and C.PROYECTO != "ensayo":
        p = json.loads(ensayo.read_text(encoding="utf-8")).get("tablero") or {}
    return (p["owner"], int(p["numero"])) if p.get("numero") else None


def copiar_plantilla(cfg: dict, plantilla: tuple[str, int], owner: str, titulo: str) -> dict | None:
    r = C.ejecutar(cfg["gh_bin"] + ["project", "copy", str(plantilla[1]), "--source-owner", plantilla[0],
                                    "--target-owner", owner, "--title", titulo, "--format", "json"], cwd=LAB, timeout=120)
    if r.returncode != 0:
        print(f"No pude copiar la plantilla {plantilla[0]}#{plantilla[1]}: {(r.stderr or r.stdout).strip()[:200]}")
        return None
    proyecto = json.loads(r.stdout)
    print(f"Copiado de la plantilla {plantilla[0]}#{plantilla[1]} (vistas, campos y workflows): "
          f"#{proyecto['number']} {proyecto.get('url')}")
    return proyecto


def enlazar_repos(cfg: dict, owner: str, numero: int) -> None:
    for repo in cfg.get("repos") or [cfg["repo"]]:
        gh(cfg, "project", "link", str(numero), "--owner", owner, "--repo", repo, comprobar=False)


def campo_agente(cfg: dict, t: T.Tablero) -> None:
    """Campo Agente (single select): una opción por agente activo. Se cambia en el tablero o en el panel."""
    activos = C.agentes_activos(cfg.get("agentes"))
    if not activos:
        print(f"Campo {T.CAMPO_AGENTE}: no hay agentes activos; no lo creo")
        return
    try:
        hecho = t.asegurar_opciones(T.CAMPO_AGENTE, activos)
    except T.ErrorTablero as e:
        print(f"Campo {T.CAMPO_AGENTE}: no pude crearlo ({str(e)[:200]}); el coordinador lo reintenta en cada ciclo")
        return
    print(f"Campo {T.CAMPO_AGENTE}: {'creado' if hecho == 'creado' else 'opciones al día' if hecho else 'ya existe'} "
          f"({', '.join(activos)})")


def cmd_crear(a) -> None:
    cfg = C.cargar_config()
    owner = a.owner or cfg["repo"].split("/")[0]
    titulo = a.titulo or f"Equipo IA · {cfg['repo'].split('/')[1]}"
    lista = json.loads(gh(cfg, "project", "list", "--owner", owner, "--format", "json", "--limit", "100") or "{}")
    proyecto = next((p for p in lista.get("projects", []) if p["title"] == titulo), None)
    if proyecto:
        print(f"Reutilizo el proyecto existente #{proyecto['number']}: {proyecto.get('url')}")
    else:
        plantilla = plantilla_de(cfg, a)
        proyecto = copiar_plantilla(cfg, plantilla, owner, titulo) if plantilla else None
        if not proyecto:
            proyecto = json.loads(gh(cfg, "project", "create", "--owner", owner, "--title", titulo, "--format", "json"))
            print(f"Creado el proyecto #{proyecto['number']} sin plantilla: {proyecto.get('url')}")
    numero = proyecto["number"]
    guardar_cfg({"tablero": {"owner": owner, "numero": numero, "owner_tipo": a.owner_tipo,
                             "url": proyecto.get("url")}})
    cfg = C.cargar_config()
    t = cfg_tablero(cfg)
    existentes = t.campos
    for nombre, tipo, opciones in [(T.CAMPO_ESTADO, "SINGLE_SELECT", OPCIONES_ESTADO),
                                   (T.CAMPO_PRIORIDAD, "SINGLE_SELECT", OPCIONES_PRIORIDAD),
                                   (T.CAMPO_BLOQUEO, "TEXT", None),
                                   (T.CAMPO_SIGUIENTE, "TEXT", None)]:
        if nombre in existentes:
            print(f"Campo {nombre}: ya existe")
            continue
        args = ["project", "field-create", str(numero), "--owner", owner, "--name", nombre, "--data-type", tipo]
        if opciones:
            args += ["--single-select-options", opciones]
        gh(cfg, *args)
        print(f"Campo {nombre}: creado")
    t._campos = None
    campo_agente(cfg, t)
    enlazar_repos(cfg, owner, numero)
    t._campos = None
    cmd_verificar(a)


def cmd_rehacer(a) -> None:
    """Sustituye un tablero recién creado (sin tarjetas) por una copia de la plantilla. No borra el anterior."""
    cfg = C.cargar_config()
    plantilla = plantilla_de(cfg, a)
    if not plantilla:
        sys.exit("No hay plantilla: usa --plantilla owner/numero (p. ej. el tablero de ensayo).")
    t = cfg_tablero(cfg)
    tarjetas = [i for i in t.items()]
    if tarjetas and not a.forzar:
        sys.exit(f"El tablero actual tiene {len(tarjetas)} tarjeta(s); no lo sustituyo. "
                 "Crea las vistas a mano o repite con --forzar (las tarjetas no se copian).")
    viejo = cfg["tablero"]
    titulo = t.info()["title"]
    nuevo = copiar_plantilla(cfg, plantilla, viejo["owner"], titulo)
    if not nuevo:
        sys.exit(1)
    guardar_cfg({"tablero": {"owner": viejo["owner"], "numero": nuevo["number"],
                             "owner_tipo": viejo.get("owner_tipo", "user"), "url": nuevo.get("url")}})
    cfg = C.cargar_config()
    enlazar_repos(cfg, viejo["owner"], nuevo["number"])
    for repo in cfg.get("repos") or [cfg["repo"]]:
        gh(cfg, "variable", "set", "TABLERO_NUMERO", "--repo", repo, "--body", str(nuevo["number"]), comprobar=False)
    print(f"Tablero sustituido: {nuevo.get('url')}\nEl anterior ({viejo.get('url')}) sigue existiendo: "
          "bórralo tú en su Settings → Delete project cuando compruebes el nuevo.")
    cmd_verificar(a)


def cmd_verificar(_a) -> None:
    cfg = C.cargar_config()
    t = cfg_tablero(cfg)
    info = t.info()
    problemas = []
    print(f"Tablero: {info['title']} — {info['url']} — {'PÚBLICO' if info.get('public') else 'privado'}")
    if info.get("public"):
        problemas.append("El proyecto es público: Settings del proyecto → Visibility → Private")
    campos = {f["name"]: f for f in info["fields"]["nodes"] if f}
    for nombre, esperadas in [(T.CAMPO_ESTADO, T.ESTADOS), (T.CAMPO_PRIORIDAD, T.PRIORIDADES)]:
        tiene = [o["name"] for o in campos.get(nombre, {}).get("options", [])]
        faltan = [e for e in esperadas if e not in tiene]
        print(f"  {nombre}: {tiene or 'NO EXISTE'}")
        if faltan:
            problemas.append(f"Faltan opciones en {nombre}: {faltan}")
    for nombre in T.CAMPOS_TEXTO:
        print(f"  {nombre}: {'texto' if nombre in campos else 'NO EXISTE'}")
    if T.CAMPO_SIGUIENTE not in campos:
        problemas.append(f"Falta el campo {T.CAMPO_SIGUIENTE}: python3 tablero.py siguiente lo crea y lo rellena")
    opciones = [o["name"] for o in campos.get(T.CAMPO_AGENTE, {}).get("options", [])]
    activos = C.agentes_activos(cfg.get("agentes"))
    print(f"  {T.CAMPO_AGENTE}: {opciones if T.CAMPO_AGENTE in campos else 'NO EXISTE'}")
    if opciones != activos:
        problemas.append(f"El campo {T.CAMPO_AGENTE} no tiene como opciones los agentes activos ({', '.join(activos)}): "
                         "python3 coordinador.py agente (o el siguiente ciclo del equipo) lo crea o lo ajusta")
    vistas = {v["name"]: v["layout"] for v in info["views"]["nodes"]}
    print(f"  Vistas: {vistas}")
    for v in info["views"]["nodes"]:
        if v["name"] == T.VISTA_TABLERO:
            print(f"  Columnas de «{T.VISTA_TABLERO}»: {T.agrupacion_vista(v) or 'sin agrupar'}")
    for nombre, como in VISTAS.items():
        if nombre not in vistas:
            problemas.append(f"Falta la vista «{nombre}» (manual, 1 min): {como}")
    aviso = T.aviso_agrupacion(info)
    if aviso:
        problemas.append(aviso)
    print("\nAcceso con tu identidad local:")
    for r in T.comprobar_acceso(cfg["repo"], t.owner, t.numero, t.owner_tipo, cfg["gh_bin"]):
        print(f"  {'OK   ' if r['ok'] else 'FALTA'} {r['recurso']} [{r['identidad']}]: {r['detalle']}")
        if not r["ok"]:
            problemas.append(f"{r['recurso']}: necesita {r['permiso_minimo']}. Comprobar con: {r['comprobar']}")
    print("\n" + ("Todo correcto." if not problemas else "Pendiente:\n  - " + "\n  - ".join(problemas)))


def cmd_migrar(a) -> None:
    """Etiquetas de estado + registro local → Estado del tablero. Solo lectura salvo --aplicar."""
    cfg = C.cargar_config()
    t = cfg_tablero(cfg)
    issues = json.loads(gh(cfg, "issue", "list", "--repo", cfg["repo"], "--state", "all", "--limit", "500",
                           "--json", "id,number,title,state,labels"))
    items = {it["numero"]: it for it in t.items() if it["repo"].lower() == cfg["repo"].lower()}
    con = C.db()
    plan, discrepancias = [], []
    for i in issues:
        n = i["number"]
        etq = {l["name"] for l in i["labels"]}
        f = C.obtener(con, cfg["repo"], n)
        bloqueo = ""
        if i["state"] == "CLOSED":
            destino = T.DONE
        elif "blocked" in etq:
            destino = T.TODO
            bloqueo = (f["causa"] if f and f["causa"] else "bloqueada antes de migrar") + \
                (f" · {f['recuperacion']}" if f and f["recuperacion"] else "")
        else:
            destino = next((ETIQUETA_A_ESTADO[e] for e in ("review", "running", "ready") if e in etq), T.BACKLOG)
        if f:
            esperado_db = {"revision": T.REVIEW, "en_curso": T.DOING, "bloqueada": T.TODO, "pendiente": T.TODO}[f["estado"]]
            if i["state"] != "CLOSED" and esperado_db != destino:
                discrepancias.append(f"#{n}: etiquetas → {destino}, registro local ({f['estado']}) → {esperado_db}")
        actual = items.get(n)
        if actual and actual["estado"] and actual["estado"] != destino:
            discrepancias.append(f"#{n}: el tablero ya dice {actual['estado']}, la migración propone {destino} (se conserva el tablero)")
            destino = actual["estado"]
        quitar = sorted(etq & {"ready", "running", "review", "blocked"})
        plan.append((i, destino, bloqueo, quitar, actual))
    print(f"{'#':>4}  {'destino':18} {'bloqueo':40} etiquetas a retirar")
    for i, destino, bloqueo, quitar, _ in plan:
        print(f"{i['number']:>4}  {destino:18} {bloqueo[:40]:40} {quitar}")
    print("\nDiscrepancias:\n  " + ("\n  ".join(discrepancias) if discrepancias else "ninguna"))
    if not a.aplicar:
        print("\nSolo lectura: no se ha cambiado nada. Repite con --aplicar para migrar.")
        return
    for i, destino, bloqueo, quitar, actual in plan:
        item_id = actual["item_id"] if actual else t.anadir(i["id"])
        if not (actual and actual["estado"]):
            t.mover(item_id, destino)
        if bloqueo and not (actual and actual["bloqueo"]):
            t.poner_texto(item_id, T.CAMPO_BLOQUEO, bloqueo)
        if quitar:
            args = ["issue", "edit", str(i["number"]), "--repo", cfg["repo"]]
            for q in quitar:
                args += ["--remove-label", q]
            gh(cfg, *args)
    guardar_cfg({"fuente_cola": "tablero"})
    print("\nMigración aplicada. La cola lee ya del tablero (config.json → fuente_cola = tablero).")


def cmd_ver(_a) -> None:
    cfg = C.cargar_config()
    items = cfg_tablero(cfg).items()
    for estado in T.ESTADOS + [None]:
        grupo = sorted([i for i in items if i["estado"] == estado],
                       key=lambda i: (T.rango_prioridad(i["prioridad"]), i["creada"]))
        if not grupo:
            continue
        print(f"\n== {estado or '(sin estado)'} ==")
        for i in grupo:
            agente = ",".join(e for e in i["etiquetas"] if e.startswith("agent:")) or "-"
            print(f"  #{i['numero']:<4} {(i['prioridad'] or '--')[:2]}  {agente:13} {i['titulo'][:60]}"
                  + (f"\n         ⛔ {i['bloqueo']}" if i["bloqueo"] else "")
                  + (f"\n         → {i['siguiente']}" if i.get("siguiente") else ""))


def cmd_siguiente(a) -> None:
    """¿Qué hago ahora?: acciones en orden, esperas con su motivo y el campo Siguiente de cada tarjeta."""
    cfg = C.cargar_config()
    t = cfg_tablero(cfg)
    escribir = not a.ver
    if escribir and T.CAMPO_SIGUIENTE not in t.campos:
        gh(cfg, "project", "field-create", str(t.numero), "--owner", t.owner, "--name", T.CAMPO_SIGUIENTE,
           "--data-type", "TEXT")
        print(f"Campo {T.CAMPO_SIGUIENTE}: creado")
        t._campos = None
    rec = t.siguiente(cfg.get("repos") or [cfg["repo"]], escribir=escribir)
    print(rec["resumen"])
    for i, ac in enumerate(rec["acciones"], 1):
        print(f"  {i}. {ac['texto']}" + (f"   → python3 equipo.py {C.PROYECTO} {ac['comando']}"
                                         if ac.get("comando") and C.PROYECTO else ""))
    if rec["esperas"]:
        print("En espera:")
        for e in rec["esperas"]:
            print(f"  #{e['numero']}: {e['texto']}")
    if rec.get("error_prs"):
        print(f"Aviso: no pude leer las PR abiertas ({rec['error_prs'][:200]}); el campo no se ha tocado.")
    elif escribir:
        print(f"Campo {T.CAMPO_SIGUIENTE}: {rec['escritas']} tarjeta(s) actualizada(s)")


def cuerpo_tarea(objetivo, agente, base, archivos, criterios, prueba, deps) -> str:
    """Mismo formato que el formulario «Tarea para agente» y que lee el coordinador."""
    falta = "_No response_"
    return (f"### Objetivo\n\n{objetivo or falta}\n\n### Agente\n\n{agente or falta}\n\n### Rama base\n\n{base}\n\n"
            f"### Commit base\n\n{falta}\n\n### Archivos permitidos\n\n" + ("\n".join(archivos) or falta) +
            "\n\n### Criterios de aceptación\n\n" + ("\n".join(f"- {c}" for c in criterios) or falta) +
            f"\n\n### Comando de prueba\n\n{prueba or falta}\n\n### Dependencias\n\n" +
            (" ".join(f"#{d}" for d in deps) or "ninguna") + "\n")


def crear_bloqueo(cfg: dict, numero: int, dep: int) -> str | None:
    """Relación nativa «Blocked by» (#numero bloqueada por #dep). Devuelve el error o None; nunca aborta."""
    repo = cfg["repo"]
    r = C.ejecutar(cfg["gh_bin"] + ["api", f"repos/{repo}/issues/{dep}", "--jq", ".id"], cwd=LAB, timeout=60)
    issue_id = (r.stdout or "").strip()
    if r.returncode != 0 or not issue_id.isdigit():
        return f"no encuentro el id de #{dep}: {(r.stderr or r.stdout or '').strip()[:160]}"
    r = C.ejecutar(cfg["gh_bin"] + ["api", "-X", "POST", f"repos/{repo}/issues/{numero}/dependencies/blocked_by",
                                    "-F", f"issue_id={issue_id}"], cwd=LAB, timeout=60)
    if r.returncode != 0:
        return (r.stderr or r.stdout or "").strip()[:200] or f"código {r.returncode}"
    return None


def cmd_nueva(a) -> None:
    """Captura desde la terminal. Completa → puede ir a To Do; incompleta → Backlog con los huecos marcados."""
    cfg = C.cargar_config()
    t = cfg_tablero(cfg)
    if a.prueba == "ci" and not (cfg.get("ci") or {}).get("checks"):
        sys.exit("Este proyecto no tiene CI configurada como juez (ci.checks en su config.json).")
    activos = C.agentes_activos(cfg.get("agentes"))
    if a.agente and a.agente not in activos:
        sys.exit(f"--agente debe ser un agente activo del proyecto: {', '.join(activos) or 'no hay ninguno'}")
    if a.prueba and a.prueba != "ci" and a.prueba not in cfg["pruebas"]:
        sys.exit(f"--prueba debe ser una clave de config.json → pruebas: {', '.join(cfg['pruebas'])}")
    completa = bool(a.agente and a.archivo and a.criterio and a.prueba)
    if a.todo and not completa:
        sys.exit("Para --todo hacen falta --agente, --archivo, --criterio y --prueba (si no, se bloquearía).")
    base = C.Git(cfg).rama_por_defecto()
    cuerpo = Path(a.cuerpo).read_text(encoding="utf-8") if a.cuerpo else \
        cuerpo_tarea(a.objetivo or a.titulo, a.agente, base, a.archivo or [], a.criterio or [], a.prueba, a.dep or [])
    args = ["issue", "create", "--repo", cfg["repo"], "--title", a.titulo, "--body-file", "-"]
    if a.agente:
        args += ["--label", cfg["agentes"][a.agente]["etiqueta"]]
    url = gh(cfg, *args, stdin_text=cuerpo).strip()
    numero = int(url.rstrip("/").split("/")[-1])
    nodo = json.loads(gh(cfg, "issue", "view", str(numero), "--repo", cfg["repo"], "--json", "id"))["id"]
    item = t.anadir(nodo)
    destino = T.TODO if a.todo else T.BACKLOG
    t.mover(item, destino)
    t.poner_opcion(item, T.CAMPO_PRIORIDAD, T.prioridad_por_codigo(a.prioridad))
    print(f"#{numero} creada en {destino} con {a.prioridad}: {url}")
    for d in dict.fromkeys(a.dep or []):
        error = crear_bloqueo(cfg, numero, d)
        print(f"  Blocked by #{d}: relación creada en GitHub" if not error else
              f"  Aviso: no pude crear la relación «blocked by» #{d} ({error}); la sección Dependencias sí la recoge")
    if not completa and not a.cuerpo:
        print("  Incompleta para ejecutarse: completa Agente, Archivos permitidos, Criterios y Comando de prueba "
              "en la issue antes de moverla a To Do.")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)
    x = sp.add_parser("crear")
    x.add_argument("--plantilla", help="Tablero a copiar, owner/numero (p. ej. omenorgonza/2)")
    x.add_argument("--owner")
    x.add_argument("--owner-tipo", choices=["user", "org"], default="user")
    x.add_argument("--titulo")
    x.set_defaults(f=cmd_crear)
    sp.add_parser("verificar").set_defaults(f=cmd_verificar)
    x = sp.add_parser("rehacer", help="Sustituir un tablero vacío por una copia de la plantilla")
    x.add_argument("--plantilla", help="owner/numero")
    x.add_argument("--forzar", action="store_true")
    x.set_defaults(f=cmd_rehacer)
    x = sp.add_parser("migrar")
    x.add_argument("--aplicar", action="store_true")
    x.set_defaults(f=cmd_migrar)
    sp.add_parser("ver").set_defaults(f=cmd_ver)
    x = sp.add_parser("siguiente", help="¿Qué hago ahora? Siguiente paso y campo Siguiente del tablero")
    x.add_argument("--ver", action="store_true", help="Solo mostrar; no escribir en el tablero")
    x.set_defaults(f=cmd_siguiente)
    x = sp.add_parser("nueva", description="Ejemplo: python3 tablero.py nueva \"Añadir media de puntos\" "
                      "--agente local --archivo src/puntos.py --archivo tests/test_puntos.py "
                      "--criterio \"media([2,4]) == 3\" --criterio \"lista vacía → ValueError\" --prueba unit --prioridad P2 --todo")
    x.add_argument("titulo")
    x.add_argument("--objetivo", help="Descripción (por defecto, el título)")
    x.add_argument("--agente", help="Agente activo del proyecto (claude, local, codex, local-plus…)")
    x.add_argument("--archivo", action="append", help="Patrón de archivo permitido (repetible)")
    x.add_argument("--criterio", action="append", help="Criterio de aceptación (repetible)")
    x.add_argument("--prueba", help="Clave de config.json → pruebas (p. ej. unit) o «ci» para usar la CI del proyecto")
    x.add_argument("--dep", action="append", type=int, help="Issue de la que depende (repetible): sección Dependencias + relación «Blocked by» de GitHub")
    x.add_argument("--prioridad", default="P2", choices=["P0", "P1", "P2", "P3"])
    x.add_argument("--cuerpo", help="Archivo .md con el cuerpo completo en formato de la plantilla")
    x.add_argument("--todo", action="store_true", help="Autorizar ya (To Do) en vez de Backlog")
    x.set_defaults(f=cmd_nueva)
    a = p.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    a.f(a)


if __name__ == "__main__":
    main()
