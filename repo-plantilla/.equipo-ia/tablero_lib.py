"""Acceso al GitHub Project (v2) del equipo mediante `gh api graphql`.

Lo usan el coordinador local y los workflows de GitHub Actions. Solo biblioteca estándar.
El campo `Estado` es la fuente de verdad; `Prioridad` ordena; `Bloqueo` (texto) guarda la causa visible;
`Siguiente` (texto) dice qué hacer con cada tarjeta (lo calcula `recomendar`); `Agente` (single select con los
agentes activos) refleja la etiqueta `agent:*` y permite cambiarla desde el tablero (lo decide `plan_agentes`).
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
import shutil

BACKLOG, PLANNING, TODO, DOING, REVIEW, DONE, PRO = (
    "Backlog", "Planning", "To Do", "Doing", "Testing / Review", "Done", "PRO")
ESTADOS = [BACKLOG, PLANNING, TODO, DOING, REVIEW, DONE, PRO]
PRIORIDADES = ["P0 urgente", "P1 alta", "P2 normal", "P3 baja"]
CAMPO_ESTADO, CAMPO_PRIORIDAD, CAMPO_BLOQUEO, CAMPO_SIGUIENTE = "Estado", "Prioridad", "Bloqueo", "Siguiente"
CAMPOS_TEXTO = (CAMPO_BLOQUEO, CAMPO_SIGUIENTE)
CAMPO_AGENTE = "Agente"
AGENTE_EDITABLE = (BACKLOG, PLANNING, TODO)  # columnas en las que el agente de una tarjeta se puede cambiar
NOMBRE_AGENTE_OK = re.compile(r"^[a-z0-9][a-z0-9._-]{0,39}$")


def rango_prioridad(valor: str | None) -> int:
    """P0 → 0 … P3 → 3; sin prioridad, después de P3."""
    if valor and len(valor) >= 2 and valor[0] == "P" and valor[1].isdigit():
        return int(valor[1])
    return 9


def prioridad_por_codigo(codigo: str) -> str:
    for p in PRIORIDADES:
        if p.startswith(codigo):
            return p
    return "P2 normal"


class ErrorTablero(RuntimeError):
    pass


VISTA_TABLERO = "Tablero"
ARREGLO_AGRUPACION = f"Vista {VISTA_TABLERO} → Column by → {CAMPO_ESTADO} → Save"


def agrupacion_vista(vista: dict) -> list[str]:
    """Campos por los que una vista agrupa en columnas (ProjectV2View.verticalGroupByFields)."""
    nodos = ((vista or {}).get("verticalGroupByFields") or {}).get("nodes") or []
    return [n["name"] for n in nodos if n and n.get("name")]


def aviso_agrupacion(info: dict) -> str | None:
    """Aviso si la vista «Tablero» (Board) no agrupa sus columnas por Estado; None si está bien o no existe."""
    vista = next((v for v in (info.get("views") or {}).get("nodes") or []
                  if v and v.get("name") == VISTA_TABLERO), None)
    if not vista:
        return None
    if vista.get("layout") != "BOARD_LAYOUT":
        return (f"La vista «{VISTA_TABLERO}» no es de tipo Board ({vista.get('layout')}): cámbiala a Board y "
                f"después {ARREGLO_AGRUPACION}")
    campos = agrupacion_vista(vista)
    if campos == [CAMPO_ESTADO]:
        return None
    actual = ", ".join(campos) or "ningún campo"
    return f"La vista «{VISTA_TABLERO}» agrupa las columnas por {actual}, no por {CAMPO_ESTADO}: {ARREGLO_AGRUPACION}"


class Tablero:
    def __init__(self, owner: str, numero: int, owner_tipo: str = "user", gh_bin: list[str] | None = None,
                 env: dict | None = None):
        self.owner, self.numero, self.owner_tipo = owner, int(numero), owner_tipo
        gh_bin = gh_bin or ["gh"]
        exe = shutil.which(gh_bin[0])
        self.gh_bin = ([exe] if exe else [gh_bin[0]]) + list(gh_bin[1:])
        self.env = env
        self._id = None
        self._campos = None

    # ------------------------------------------------------------------ bajo nivel
    def graphql(self, query: str, **variables) -> dict:
        args = self.gh_bin + ["api", "graphql", "-f", f"query={query}"]
        for k, v in variables.items():
            if v is None:
                continue
            args += (["-F", f"{k}={v}"] if isinstance(v, int) and not isinstance(v, bool) else ["-f", f"{k}={v}"])
        r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env=self.env or os.environ.copy(), timeout=120)
        if r.returncode != 0:
            raise ErrorTablero(f"GraphQL falló: {(r.stderr or r.stdout).strip()[:800]}")
        datos = json.loads(r.stdout)
        if datos.get("errors"):
            raise ErrorTablero(f"GraphQL errores: {json.dumps(datos['errors'], ensure_ascii=False)[:800]}")
        return datos["data"]

    @property
    def id(self) -> str:
        if not self._id:
            raiz = "organization" if self.owner_tipo == "org" else "user"
            q = f"query($owner:String!,$numero:Int!){{ {raiz}(login:$owner){{ projectV2(number:$numero){{ id }} }} }}"
            d = self.graphql(q, owner=self.owner, numero=self.numero)
            proyecto = (d.get(raiz) or {}).get("projectV2")
            if not proyecto:
                raise ErrorTablero(f"No encuentro el proyecto {self.owner}#{self.numero} (¿falta el scope 'project'?)")
            self._id = proyecto["id"]
        return self._id

    def info(self) -> dict:
        q = """query($id:ID!){ node(id:$id){ ... on ProjectV2 { title url public
          fields(first:50){ nodes{ ... on ProjectV2FieldCommon{ id name dataType }
                                   ... on ProjectV2SingleSelectField{ id name dataType options{ id name } } } }
          views(first:20){ nodes{ name layout
            verticalGroupByFields(first:5){ nodes{ ... on ProjectV2FieldCommon{ name } } } } } } } }"""
        return self.graphql(q, id=self.id)["node"]

    @property
    def campos(self) -> dict:
        if self._campos is None:
            self._campos = {f["name"]: f for f in self.info()["fields"]["nodes"] if f}
        return self._campos

    def _opcion(self, campo: str, nombre: str) -> tuple[str, str]:
        f = self.campos.get(campo)
        if not f:
            raise ErrorTablero(f"El proyecto no tiene el campo {campo!r}")
        for o in f.get("options", []):
            if o["name"] == nombre:
                return f["id"], o["id"]
        raise ErrorTablero(f"El campo {campo!r} no tiene la opción {nombre!r}")

    # ------------------------------------------------------------------ lectura
    def items(self) -> list[dict]:
        """Tarjetas del proyecto que son issues: {item_id, numero, repo, titulo, ..., campos}."""
        q = """query($id:ID!,$cursor:String){ node(id:$id){ ... on ProjectV2 {
          items(first:100, after:$cursor){ pageInfo{ hasNextPage endCursor } nodes{ id
            fieldValues(first:30){ nodes{
              ... on ProjectV2ItemFieldSingleSelectValue{ name field{ ... on ProjectV2FieldCommon{ name } } }
              ... on ProjectV2ItemFieldTextValue{ text field{ ... on ProjectV2FieldCommon{ name } } } } }
            content{ ... on Issue{ id number title body createdAt state url author{ login }
                                   repository{ nameWithOwner } labels(first:30){ nodes{ name } } } } } } } } }"""
        salida, cursor = [], None
        while True:
            d = self.graphql(q, id=self.id, cursor=cursor)["node"]["items"]
            for n in d["nodes"]:
                c = n.get("content") or {}
                if "number" not in c:
                    continue
                campos = {}
                for fv in n["fieldValues"]["nodes"]:
                    if fv and fv.get("field"):
                        campos[fv["field"]["name"]] = fv.get("name", fv.get("text"))
                salida.append({
                    "item_id": n["id"], "issue_id": c["id"], "numero": c["number"], "titulo": c["title"],
                    "cuerpo": c.get("body") or "", "creada": c["createdAt"], "abierta": c["state"] == "OPEN",
                    "url": c["url"], "autor": (c.get("author") or {}).get("login", ""),
                    "repo": c["repository"]["nameWithOwner"],
                    "etiquetas": [l["name"] for l in c["labels"]["nodes"]],
                    "estado": campos.get(CAMPO_ESTADO), "prioridad": campos.get(CAMPO_PRIORIDAD),
                    "bloqueo": (campos.get(CAMPO_BLOQUEO) or "").strip(),
                    "siguiente": (campos.get(CAMPO_SIGUIENTE) or "").strip(),
                    "agente_campo": (campos.get(CAMPO_AGENTE) or "").strip(),
                })
            if not d["pageInfo"]["hasNextPage"]:
                return salida
            cursor = d["pageInfo"]["endCursor"]

    def item_de_issue(self, repo: str, numero: int) -> dict | None:
        for it in self.items():
            if it["repo"].lower() == repo.lower() and it["numero"] == numero:
                return it
        return None

    # ------------------------------------------------------------------ escritura
    def poner_opcion(self, item_id: str, campo: str, nombre: str) -> None:
        fid, oid = self._opcion(campo, nombre)
        q = """mutation($p:ID!,$i:ID!,$f:ID!,$o:String!){ updateProjectV2ItemFieldValue(input:{
               projectId:$p, itemId:$i, fieldId:$f, value:{ singleSelectOptionId:$o } }){ projectV2Item{ id } } }"""
        self.graphql(q, p=self.id, i=item_id, f=fid, o=oid)

    def poner_texto(self, item_id: str, campo: str, texto: str) -> None:
        f = self.campos.get(campo)
        if not f:
            raise ErrorTablero(f"El proyecto no tiene el campo {campo!r}")
        if not texto:
            q = """mutation($p:ID!,$i:ID!,$f:ID!){ clearProjectV2ItemFieldValue(input:{
                   projectId:$p, itemId:$i, fieldId:$f }){ projectV2Item{ id } } }"""
            self.graphql(q, p=self.id, i=item_id, f=f["id"])
            return
        q = """mutation($p:ID!,$i:ID!,$f:ID!,$t:String!){ updateProjectV2ItemFieldValue(input:{
               projectId:$p, itemId:$i, fieldId:$f, value:{ text:$t } }){ projectV2Item{ id } } }"""
        self.graphql(q, p=self.id, i=item_id, f=f["id"], t=texto[:1000])

    def asegurar_opciones(self, campo: str, opciones: list[str]) -> str | None:
        """Campo single select `campo` con exactamente `opciones` (en ese orden): lo crea si falta y, si sus opciones
        no coinciden, las sustituye. Devuelve «creado», «opciones» o None (ya estaba al día)."""
        malos = [o for o in opciones if not NOMBRE_AGENTE_OK.match(o)]
        if malos or not opciones:
            raise ErrorTablero(f"Opciones no válidas para {campo!r}: {malos or 'ninguna'}")
        lista = ", ".join(f'{{name:{json.dumps(o)}, color:GRAY, description:""}}' for o in opciones)
        f = self.campos.get(campo)
        if not f:
            q = (f"mutation($p:ID!,$n:String!){{ createProjectV2Field(input:{{ projectId:$p, dataType:SINGLE_SELECT, "
                 f"name:$n, singleSelectOptions:[{lista}] }}){{ projectV2Field{{ ... on ProjectV2FieldCommon{{ id }} }} }} }}")
            self.graphql(q, p=self.id, n=campo)
            self._campos = None
            return "creado"
        if [o["name"] for o in f.get("options") or []] == list(opciones):
            return None
        q = (f"mutation($f:ID!){{ updateProjectV2Field(input:{{ fieldId:$f, singleSelectOptions:[{lista}] }}){{ "
             f"projectV2Field{{ ... on ProjectV2FieldCommon{{ id }} }} }} }}")
        self.graphql(q, f=f["id"])
        self._campos = None
        return "opciones"

    def anadir(self, issue_node_id: str) -> str:
        q = """mutation($p:ID!,$c:ID!){ addProjectV2ItemById(input:{ projectId:$p, contentId:$c }){ item{ id } } }"""
        return self.graphql(q, p=self.id, c=issue_node_id)["addProjectV2ItemById"]["item"]["id"]

    def mover(self, item_id: str, estado: str) -> None:
        if estado not in ESTADOS:
            raise ErrorTablero(f"Estado desconocido {estado!r}")
        self.poner_opcion(item_id, CAMPO_ESTADO, estado)

    def sonda_escritura(self) -> None:
        """Crea y borra un borrador en el tablero: prueba de escritura sin tocar tarjetas reales."""
        q = """mutation($p:ID!){ addProjectV2DraftIssue(input:{ projectId:$p, title:"sonda de acceso (se borra sola)" }){
               projectItem{ id } } }"""
        item = self.graphql(q, p=self.id)["addProjectV2DraftIssue"]["projectItem"]["id"]
        q = """mutation($p:ID!,$i:ID!){ deleteProjectV2Item(input:{ projectId:$p, itemId:$i }){ deletedItemId } }"""
        self.graphql(q, p=self.id, i=item)

    # ------------------------------------------------------------------ siguiente paso
    def siguiente(self, repos: list[str], escribir: bool = False, items: list[dict] | None = None) -> dict:
        """Calcula el siguiente paso (`recomendar`) con las PR abiertas de `repos` y, con `escribir`, rellena o
        vacía el campo Siguiente solo en las tarjetas cuyo valor cambia. Devuelve la recomendación con
        `escritas` (número de escrituras; None si no se escribió) y `error_prs` si no se pudieron leer las PR."""
        items = self.items() if items is None else items
        prs, error = {}, None
        for repo in repos:
            try:
                for n, info in prs_abiertas(repo, self.gh_bin, self.env).items():
                    prs[(repo.lower(), n)] = info
            except ErrorTablero as e:
                error = str(e)
        rec = recomendar(items, prs)
        rec["error_prs"], rec["escritas"] = error, None
        if escribir and not error:  # sin las PR, la recomendación de Review sería falsa: no se publica
            rec["escritas"] = escribir_siguiente(self, items, rec)
        return rec


# --------------------------------------------------------------------------- siguiente paso recomendado

VACIOS = ("", "_No response_", "-", "ninguna", "ninguno", "Ninguna", "Ninguno")
CONCLUSIONES_ROJAS = {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"}
CONCLUSIONES_VERDES = {"SUCCESS", "NEUTRAL", "SKIPPED"}


def datos_cuerpo(cuerpo: str) -> dict:
    """Agente, archivos permitidos, dependencias y prueba de una issue con el formato de la plantilla."""
    secciones: dict[str, str] = {}
    actual = None
    for linea in (cuerpo or "").replace("\r\n", "\n").split("\n"):
        m = re.match(r"^#{2,4}\s+(.+?)\s*$", linea)
        if m:
            actual = m.group(1).strip().lower()
            secciones[actual] = ""
        elif actual is not None:
            secciones[actual] += linea + "\n"

    def v(titulo):
        x = secciones.get(titulo, "").strip()
        return "" if x in VACIOS else x
    return {"agente": v("agente").lower(),
            "archivos": [l.strip().strip("`").lstrip("-* ").strip().strip("`")
                         for l in v("archivos permitidos").splitlines() if l.strip()],
            "dependencias": [int(n) for n in re.findall(r"#(\d+)", v("dependencias"))],
            "prueba": v("comando de prueba").strip("`")}


def solape_inofensivo(ruta: str) -> bool:
    """README, docs y ensayos los tocan casi todas las tareas y se reconcilian sin problema: no hacen esperar."""
    r = ruta.strip().lstrip("./").lower()
    base = r.rsplit("/", 1)[-1]
    return base.startswith("readme") or r.startswith("docs/") or "/docs/" in r or "ensayo" in base


def archivos_compartidos(a: list[str], b: list[str]) -> list[str]:
    """Archivos (o patrones) que comparten dos listas, sin contar los de solape inofensivo."""
    comunes = set()
    for x in a:
        for y in b:
            if x == y or fnmatch.fnmatchcase(x, y) or fnmatch.fnmatchcase(y, x):
                concreto = y if any(c in x for c in "*?[") else x
                if not (solape_inofensivo(x) or solape_inofensivo(y)):
                    comunes.add(concreto)
    return sorted(comunes)


def resumen_ci(rollup: list[dict] | None) -> str:
    """statusCheckRollup → «verde», «rojo», «pendiente» o «sin_ci» (la PR no tiene checks)."""
    if not rollup:
        return "sin_ci"
    pendiente = False
    for c in rollup:
        concl = (c.get("conclusion") or c.get("state") or "").upper()
        if concl in CONCLUSIONES_ROJAS:
            return "rojo"
        estado = (c.get("status") or "COMPLETED").upper()
        if estado != "COMPLETED" or concl not in CONCLUSIONES_VERDES:
            pendiente = True
    return "pendiente" if pendiente else "verde"


def prs_abiertas(repo: str, gh_bin: list[str] | None = None, env: dict | None = None) -> dict[int, dict]:
    """PR abiertas de `repo` por número de issue (rama …/issue-N o «Closes #N»): CI, conflicto y archivos."""
    r = _gh(gh_bin or ["gh"], "pr", "list", "--repo", repo, "--state", "open", "--limit", "100", "--json",
            "number,url,headRefName,body,isDraft,mergeable,statusCheckRollup,files", env=env)
    if r.returncode != 0:
        raise ErrorTablero(f"gh pr list {repo} falló: {(r.stderr or r.stdout).strip()[:300]}")
    salida: dict[int, dict] = {}
    for p in json.loads(r.stdout or "[]"):
        m = re.search(r"issue-(\d+)$", p.get("headRefName") or "")
        nums = [int(m.group(1))] if m else \
            [int(n) for n in re.findall(r"(?i)\b(?:closes|fixes|resolves)\s+#(\d+)", p.get("body") or "")]
        info = {"pr": p["number"], "url": p.get("url"), "ci": resumen_ci(p.get("statusCheckRollup")),
                "borrador": bool(p.get("isDraft")), "conflicto": p.get("mergeable") == "CONFLICTING",
                "archivos": [f["path"] for f in p.get("files") or [] if f and f.get("path")]}
        for n in nums:
            salida.setdefault(n, info)
    return salida


def _clave(it: dict) -> tuple[str, int]:
    return (it["repo"].lower(), it["numero"])


def recomendar(items: list[dict], prs: dict[tuple[str, int], dict]) -> dict:
    """Siguiente paso para Óscar a partir de las tarjetas (`Tablero.items()`) y sus PR abiertas.

    Orden de las acciones: 1) integrar las PR en Review con CI verde (las de una cadena, dependencia primero);
    2) arreglar PR con conflictos o CI en rojo; 3) reanudar tarjetas bloqueadas; 4) pasar a To Do las de Planning
    que pueden empezar ya. Una de Planning espera («⏸») si su dependencia no está integrada o si comparte
    archivos (salvo README/docs/ensayos) con una PR abierta, una tarea en curso o en cola, u otra recomendada antes.
    Devuelve {"acciones": [...], "esperas": [...], "tarjetas": {(repo, n): texto del campo Siguiente}, "resumen"}.
    """
    por_clave = {_clave(it): it for it in items}
    datos = {_clave(it): datos_cuerpo(it.get("cuerpo") or "") for it in items}
    orden = lambda it: (rango_prioridad(it.get("prioridad")), it.get("creada") or "", it["numero"])  # noqa: E731
    activas = sorted((it for it in items if it["abierta"] and it["estado"] in (PLANNING, TODO, DOING, REVIEW)),
                     key=orden)
    textos: dict[tuple[str, int], str] = {}
    acciones: list[dict] = []
    esperas: list[dict] = []

    def agente(it):
        return next((e.split(":", 1)[1] for e in it["etiquetas"] if e.startswith("agent:")), None) \
            or datos[_clave(it)]["agente"] or None

    def accion(it, tipo, texto, comando=None):
        acciones.append({"tipo": tipo, "numero": it["numero"], "repo": it["repo"], "texto": texto,
                         "comando": comando, "url": (prs.get(_clave(it)) or {}).get("url") or it.get("url")})
        textos[_clave(it)] = (len(acciones), texto)

    def espera(it, motivo):
        esperas.append({"numero": it["numero"], "repo": it["repo"], "texto": motivo, "url": it.get("url")})
        textos[_clave(it)] = f"⏸ {motivo}"

    def deps_sin_integrar(it):
        """(#dep, dónde está) de las dependencias que aún no están integradas (Done/PRO o cerradas)."""
        faltan = []
        for d in datos[_clave(it)]["dependencias"]:
            dep = por_clave.get((it["repo"].lower(), d))
            if dep and dep["abierta"] and dep["estado"] not in (DONE, PRO):
                faltan.append((d, "en review, sin integrar" if dep["estado"] == REVIEW else f"en {dep['estado'] or 'sin estado'}"))
        return faltan

    def titulo(it):
        t = it.get("titulo") or ""
        return t if len(t) <= 60 else t[:59] + "…"

    # Trabajo ya autorizado (To Do, también bloqueado: se reanudará), en curso o en Review: sus archivos (los de
    # la PR si se conocen; si no, los permitidos) están ocupados.
    ocupados = []  # (tarjeta, archivos, descripción)
    for it in activas:
        if it["estado"] in (TODO, DOING, REVIEW):
            pr = prs.get(_clave(it))
            archivos = (pr or {}).get("archivos") or datos[_clave(it)]["archivos"]
            donde = "en curso" if it["estado"] == DOING else "bloqueada" if it["bloqueo"] else \
                "en cola" if it["estado"] == TODO else it["estado"]
            desc = f"la PR #{pr['pr']} (#{it['numero']})" if pr else f"#{it['numero']} ({donde})"
            ocupados.append((it, archivos, desc))

    # 1-2) Testing / Review: integrar en orden de cadena, o arreglar la PR.
    review = [it for it in activas if it["estado"] == REVIEW]
    pendientes_review = {it["numero"] for it in review}
    ordenadas = []
    while review:  # dependencias primero; a igualdad, prioridad y antigüedad
        sig = next((it for it in review if not any(d in pendientes_review for d, _ in deps_sin_integrar(it))),
                   review[0])
        review.remove(sig)
        pendientes_review.discard(sig["numero"])
        ordenadas.append(sig)
    arreglos, a_integrar = [], set()
    for it in ordenadas:
        pr = prs.get(_clave(it))
        n = it["numero"]
        if not pr:
            textos[_clave(it)] = "🔍 revisar en GitHub: no encuentro su PR abierta"
            continue
        if pr["conflicto"]:
            arreglos.append((it, f"PR #{pr['pr']} con conflictos: reanudar {n} --desde agente", f"reanudar {n} --desde agente"))
        elif pr["ci"] == "rojo":
            arreglos.append((it, f"CI en rojo en la PR #{pr['pr']}: reanudar {n} --desde agente", f"reanudar {n} --desde agente"))
        elif pr["ci"] == "pendiente" or pr["borrador"]:
            textos[_clave(it)] = f"⏳ espera la CI de la PR #{pr['pr']}"
        else:
            bloquea = [(d, donde) for d, donde in deps_sin_integrar(it) if (it["repo"].lower(), d) not in a_integrar]
            if bloquea:
                espera(it, f"espera dependencia #{bloquea[0][0]} ({bloquea[0][1]}) antes de integrar")
            else:
                a_integrar.add(_clave(it))
                accion(it, "integrar", f"integrar la PR #{pr['pr']} (#{n} {titulo(it)})")
    for it, texto, comando in arreglos:
        accion(it, "arreglar", texto, comando)

    # 3) Bloqueadas en To Do / Doing: reanudar.
    for it in activas:
        if it["estado"] in (TODO, DOING) and it["bloqueo"]:
            accion(it, "reanudar", f"reanudar {it['numero']} (#{it['numero']} {titulo(it)})", f"reanudar {it['numero']}")
        elif it["estado"] == DOING:
            textos[_clave(it)] = f"⚙ en curso ({agente(it) or '?'})"
        elif it["estado"] == TODO:
            faltan = deps_sin_integrar(it)
            nota = f"; ojo: #{faltan[0][0]} está {faltan[0][1]}" if faltan else ""
            textos[_clave(it)] = f"⏳ en cola: la cogerá {agente(it) or 'el equipo'}{nota}"

    # 4) Planning: pasar a To Do lo que puede empezar ya; el resto espera con su motivo.
    recomendadas = []  # (tarjeta, archivos)
    for it in activas:
        if it["estado"] != PLANNING:
            continue
        d = datos[_clave(it)]
        falta = [n for n, v in (("agente", agente(it)), ("archivos permitidos", d["archivos"]),
                                ("comando de prueba", d["prueba"])) if not v]
        if falta:
            textos[_clave(it)] = f"✎ completar la issue: falta {', '.join(falta)}"
            continue
        deps = deps_sin_integrar(it)
        if deps:
            espera(it, f"espera dependencia #{deps[0][0]} ({deps[0][1]})")
            continue
        choque = next(((desc, c) for otra, archivos, desc in ocupados if otra is not it
                       for c in [archivos_compartidos(d["archivos"], archivos)] if c), None)
        if choque:
            espera(it, f"espera: comparte {', '.join(choque[1][:3])} con {choque[0]}")
            continue
        previa = next(((otra, c) for otra, archivos in recomendadas
                       for c in [archivos_compartidos(d["archivos"], archivos)] if c), None)
        if previa:
            espera(it, f"espera a #{previa[0]['numero']}: comparte {', '.join(previa[1][:3])}")
            continue
        recomendadas.append((it, d["archivos"]))
        if it["bloqueo"]:  # Bloqueo antiguo: pasarla a To Do no basta (la cola la salta); reanudar lo retira
            accion(it, "reanudar", f"reanudar {it['numero']} (#{it['numero']} {titulo(it)}, tiene un Bloqueo antiguo)",
                   f"reanudar {it['numero']}")
        else:
            accion(it, "todo", f"pasar #{it['numero']} a To Do ({titulo(it)})")

    tarjetas = {}
    for it in items:
        t = textos.get(_clave(it), "")
        if isinstance(t, tuple):
            t = f"▶ {t[0]} · {t[1]}"
        tarjetas[_clave(it)] = t
    if acciones:
        resumen = f"Siguiente paso: {acciones[0]['texto']}"
    elif any(it["estado"] == DOING for it in activas):
        resumen = "Nada que hacer ahora: el equipo está trabajando"
    elif any(it["estado"] == TODO for it in activas):
        resumen = "Nada que hacer ahora: hay tareas en To Do (arranca el equipo si está parado)"
    elif esperas:
        resumen = "Nada que hacer ahora: todo lo de Planning está esperando (mira el motivo de cada tarjeta)"
    else:
        resumen = "Nada pendiente: crea tareas o pasa propuestas de Backlog a Planning"
    return {"acciones": acciones, "esperas": esperas, "tarjetas": tarjetas, "resumen": resumen}


def escribir_siguiente(t: Tablero, items: list[dict], rec: dict) -> int:
    """Rellena o vacía el campo Siguiente de cada tarjeta solo si cambia. Devuelve el número de escrituras."""
    if CAMPO_SIGUIENTE not in t.campos:
        raise ErrorTablero(f"El tablero no tiene el campo {CAMPO_SIGUIENTE!r}: python3 tablero.py siguiente lo crea")
    escritas = 0
    for it in items:
        nuevo = rec["tarjetas"].get(_clave(it), "")
        if (it.get("siguiente") or "").strip() != nuevo.strip():
            t.poner_texto(it["item_id"], CAMPO_SIGUIENTE, nuevo)
            it["siguiente"] = nuevo
            escritas += 1
    return escritas


# --------------------------------------------------------------------------- agente asignado (campo Agente)

def clave_tarjeta(it: dict) -> str:
    """Clave de una tarjeta en el recuerdo de la sincronización del campo Agente: «owner/repo#N»."""
    return f"{it['repo'].lower()}#{it['numero']}"


def agente_por_etiquetas(etiquetas, etiqueta_de: dict[str, str]) -> str | None:
    """Agente cuya etiqueta lleva la tarjeta (`etiqueta_de`: agente → etiqueta). None si no hay una sola."""
    c = [n for n, e in etiqueta_de.items() if e in set(etiquetas or [])]
    return c[0] if len(c) == 1 else None


def plan_agentes(items: list[dict], etiqueta_de: dict[str, str], activos: list[str],
                 recuerdo: dict[str, str]) -> list[dict]:
    """Qué hacer con el campo Agente de cada tarjeta. La etiqueta `agent:*` es la fuente de verdad.

    `recuerdo` guarda el valor del campo que dejó la última sincronización («» = vacío): si el campo ha cambiado desde
    entonces y la etiqueta no, alguien ha elegido otro agente en el tablero. Ese cambio se aplica (etiqueta, campo
    Agente del cuerpo y comentario) si la tarjeta está abierta en Backlog, Planning o To Do y el agente está activo; si
    no, se revierte con un comentario. En cualquier otro caso gana la etiqueta (también si cambian las dos a la vez):
    el campo se rellena con su agente, o se vacía si no tiene una sola etiqueta de agente activo.

    Devuelve una acción por tarjeta: {"tipo": "al_dia"|"rellenar"|"aplicar"|"revertir", "it", "agente" (valor final
    del campo, «» = vacío), "etiqueta" (agente de la etiqueta o None), "pedido" (lo elegido en el campo), "motivo"}.
    """
    acciones = []
    for it in items:
        etq = agente_por_etiquetas(it.get("etiquetas"), etiqueta_de)
        objetivo = etq if etq in activos else ""
        campo = (it.get("agente_campo") or "").strip()
        previo = recuerdo.get(clave_tarjeta(it))
        base = {"it": it, "etiqueta": etq, "pedido": campo, "motivo": ""}
        if campo == objetivo:
            acciones.append({**base, "tipo": "al_dia", "agente": campo})
            continue
        cambio_campo = previo is not None and campo != previo and campo != ""
        cambio_etiqueta = previo is not None and objetivo != previo
        if not cambio_campo or cambio_etiqueta:
            acciones.append({**base, "tipo": "rellenar", "agente": objetivo})
            continue
        if not it.get("abierta", True):
            motivo = "la issue está cerrada"
        elif it.get("estado") not in AGENTE_EDITABLE:
            motivo = (f"el agente solo se cambia en {', '.join(AGENTE_EDITABLE[:-1])} o {AGENTE_EDITABLE[-1]} "
                      f"(la tarjeta está en {it.get('estado') or 'sin estado'})")
        elif campo not in activos or campo not in etiqueta_de:
            motivo = f"`{campo}` no es un agente activo de este proyecto"
        else:
            acciones.append({**base, "tipo": "aplicar", "agente": campo})
            continue
        acciones.append({**base, "tipo": "revertir", "agente": objetivo, "motivo": motivo})
    return acciones


def _gh(gh_bin: list[str], *args, env=None) -> subprocess.CompletedProcess:
    exe = shutil.which(gh_bin[0])
    return subprocess.run(([exe] if exe else [gh_bin[0]]) + list(gh_bin[1:]) + list(args), capture_output=True,
                          text=True, encoding="utf-8", errors="replace", env=env or os.environ.copy(), timeout=120)


def comprobar_acceso(repo: str, owner: str, numero: int | None, owner_tipo: str = "user",
                     gh_bin: list[str] | None = None, env: dict | None = None, identidad: str = "") -> list[dict]:
    """Prueba cada permiso con la identidad real (el token que tenga `gh` en este proceso)."""
    gh_bin = gh_bin or ["gh"]
    res = []

    def anotar(recurso, ok, detalle, minimo, como):
        res.append({"recurso": recurso, "ok": ok, "detalle": detalle.strip()[:300], "permiso_minimo": minimo,
                    "comprobar": como, "identidad": identidad})

    r = _gh(gh_bin, "api", "user", "--jq", ".login", env=env)
    quien = r.stdout.strip() or "(token sin acceso a /user: típico de GITHUB_TOKEN)"
    identidad = identidad or quien
    r = _gh(gh_bin, "issue", "list", "--repo", repo, "--state", "all", "--limit", "1", "--json", "number", env=env)
    anotar(f"Issues de {repo} (lectura)", r.returncode == 0, r.stderr or "OK",
           "classic: repo · fine-grained: Issues read · GITHUB_TOKEN: issues: read",
           f"gh issue list --repo {repo} --limit 1")
    r = _gh(gh_bin, "api", f"repos/{repo}/dependabot/alerts?per_page=1&state=open", env=env)
    detalle = "OK" if r.returncode == 0 else (r.stderr or r.stdout)
    if "disabled" in detalle.lower():
        detalle = "Dependabot alerts desactivado en el repo: " + detalle
    anotar(f"Avisos Dependabot de {repo} (lectura)", r.returncode == 0, detalle,
           "classic: repo (incluye security_events) · fine-grained: Dependabot alerts read",
           f"gh api 'repos/{repo}/dependabot/alerts?per_page=1'")
    if numero:
        t = Tablero(owner, numero, owner_tipo, gh_bin, env)
        try:
            t.items()
            anotar(f"Tablero {owner}#{numero} (lectura)", True, "OK", "classic: read:project (o project)",
                   "python tablero.py verificar")
            try:
                t.sonda_escritura()
                anotar(f"Tablero {owner}#{numero} (escritura)", True, "OK (borrador creado y borrado)",
                       "classic: project", "python tablero.py verificar")
            except ErrorTablero as e:
                anotar(f"Tablero {owner}#{numero} (escritura)", False, str(e), "classic: project",
                       "gh auth refresh -s project && python tablero.py verificar")
        except ErrorTablero as e:
            anotar(f"Tablero {owner}#{numero} (lectura)", False, str(e), "classic: read:project (o project)",
                   "gh auth refresh -s project && python tablero.py verificar")
    return res
