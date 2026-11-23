"""Acceso al GitHub Project (v2) del equipo mediante `gh api graphql`.

Lo usan el coordinador local y los workflows de GitHub Actions. Solo biblioteca estándar.
El campo `Estado` es la fuente de verdad; `Prioridad` ordena; `Bloqueo` (texto) guarda la causa visible.
"""
from __future__ import annotations

import json
import os
import subprocess
import shutil

BACKLOG, PLANNING, TODO, DOING, REVIEW, DONE, PRO = (
    "Backlog", "Planning", "To Do", "Doing", "Testing / Review", "Done", "PRO")
ESTADOS = [BACKLOG, PLANNING, TODO, DOING, REVIEW, DONE, PRO]
PRIORIDADES = ["P0 urgente", "P1 alta", "P2 normal", "P3 baja"]
CAMPO_ESTADO, CAMPO_PRIORIDAD, CAMPO_BLOQUEO = "Estado", "Prioridad", "Bloqueo"


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
