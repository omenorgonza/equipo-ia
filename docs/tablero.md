# Tablero

[← Índice de la documentación](README.md)

Cada proyecto tiene un GitHub Project privado («Equipo IA · <proyecto>») que hace de cola de trabajo.
Comandos: `python3 equipo.py <proyecto> tablero ver|nueva|verificar|siguiente|rehacer` (o `python3 tablero.py …`
en una instalación de un solo proyecto).

## Columnas

Backlog → Planning → To Do → Doing → Testing / Review → Done → PRO. Solo las tarjetas de **To Do** entran en la
cola del coordinador; cómo se ordenan está en [Guía de uso](guia-uso.md#cola-y-prioridades).

## Quién mueve cada tarjeta

Un único sitio por transición:

| Estado | Lo mueve | Cuándo |
|---|---|---|
| Backlog | Óscar | captura una idea (`python3 tablero.py nueva "título"` o desde la web) |
| Planning | TL o `mantenimiento.yml` | propuesta con evidencia |
| Planning (o Backlog / To Do) | `tablero-issue.yml` | issue abierta sin pasar por el tablero (móvil, otra sesión): la añade en Planning, o en el estado de una etiqueta `estado:backlog\|planning\|todo`, con la prioridad de `prioridad:p0..p3`. Si quien la creó ya la colocó, no la toca. Solo actúa con issues abiertas por el dueño del repo (en un repo público, cualquiera puede abrir issues) |
| To Do | **Óscar** | autoriza; la tarjeta tiene agente (`agent:*`), alcance y criterios |
| Doing | coordinador local | tras reservar y volver a comprobar la elegibilidad, antes de invocar al agente |
| Testing / Review | coordinador local | PR creada y vinculada (`Closes #N`) |
| Done | `tablero-pr.yml` | PR integrada en la rama objetivo con el check `pruebas` verde |
| PRO | `despliegue.yml` / `mantenimiento.yml` | el último despliegue **correcto** contiene el commit |

- Cola: To Do + repo permitido + autor autorizado + agente activo + dependencias en Review/Done/PRO + sin
  Bloqueo, ordenada por P0→P3 y antigüedad. Un trabajador por proveedor, máximo 5.
- Bloqueo: el campo de texto **Bloqueo** muestra causa y recuperación; la tarjeta vuelve a To Do.
  Para reintentar basta con **vaciar Bloqueo** (o `python coordinador.py reanudar N`).
- Si la escritura de Doing falla, la reserva se deshace y no se lanza trabajo.
- Arrastrar una tarjeta a PRO no despliega nada; la siguiente reconciliación la devuelve a Done (si su PR está
  integrada) o a Testing / Review (si no), con una nota.
  Una reversión (despliegue correcto de un SHA anterior) también devuelve a Done las afectadas.

## Campos

- **Estado**: la columna (single select). Las vistas agrupan por este campo, no por Status.
- **Prioridad**: P0…P3 (P2 normal por defecto en `tablero.py nueva`).
- **Bloqueo**: texto con la causa y cómo seguir; vacío = sin bloqueo.
- **Siguiente**: texto con el siguiente paso recomendado (ver [Guía de uso](guia-uso.md#qué-hago-ahora)).
- **Agente**: single select con una opción por agente activo; refleja la etiqueta `agent:*` y sirve para
  cambiarla (ver [Cambiar el agente de una tarea](#cambiar-el-agente-de-una-tarea)).

## Cambiar el agente de una tarea

La etiqueta `agent:*` de la issue manda; el campo **Agente** del tablero la refleja en cada tarjeta (también en
el móvil) y se rellena solo. Para pasar una tarea, p. ej., de `local` a `claude` mientras está en **Backlog,
Planning o To Do**, hay tres maneras:

1. **Tablero** (web o móvil): cambia el campo Agente de la tarjeta. En el siguiente ciclo del equipo (o del
   panel, si el equipo está parado) se cambian la etiqueta y el campo «Agente» del cuerpo, con un comentario.
2. **Panel**: el desplegable de agente de la tarjeta ([Agente de cada tarjeta](panel.md#agente-de-cada-tarjeta)),
   o en la terminal `python3 equipo.py <proyecto> agente N claude`.
3. **Etiqueta**: cambia `agent:local` por `agent:claude` en la issue. Gana la etiqueta: el campo del tablero se
   actualiza solo y, en Backlog, Planning o To Do, también el campo «Agente» del cuerpo.

Así, al pasar a To Do la tarea la hace el agente nuevo sin Bloqueo por desajuste entre el campo y la etiqueta.
Un cambio del campo en **Doing** o después, o a un agente **inactivo**, se deshace con un comentario que explica
por qué. Si cambian a la vez el campo y la etiqueta, gana la etiqueta. Las opciones del campo son los agentes
activos: `python3 equipo.py <proyecto> agente` (sin argumentos) o `preparar` crean el campo o ajustan sus opciones
y sincronizan todas las tarjetas; el coordinador lo hace también al empezar cada ciclo, y solo escribe lo que
cambia. Para saber quién cambió qué, guarda el valor sincronizado en `proyectos/<p>/estado/agentes-tablero.json`.

Detalles que evitan sorpresas:

- **Sin carreras con el coordinador**: el coordinador, el panel y `agente` comparten un cerrojo
  (`estado/agentes-tablero.lock`). El coordinador lo mantiene desde la sincronización del ciclo hasta mover a Doing
  las tareas que elige, y el panel lee y valida la tarjeta con el cerrojo puesto: un cambio iniciado en To Do no
  puede tocar una tarea que el coordinador ya ha pasado a Doing (el panel espera un momento o avisa de que lo
  intentes otra vez).
- **El comentario no se pierde**: se anota en `estado/agentes-tablero-comentarios.json` antes de escribir nada; si
  GitHub falla al publicarlo, el ciclo siguiente lo publica (una vez) mientras la etiqueta siga diciendo ese agente.
- **Sin agentes activos**: el campo se queda con una sola opción, `sin-agente-activo` (GitHub no admite un campo de
  selección vacío), se vacía en todas las tarjetas y lo que se elija se deshace con un comentario.

## Plantilla del tablero

Los tableros nuevos se **copian del tablero de ensayo** (vistas «Tablero» y «Planning», campos Estado,
Prioridad, Bloqueo y Siguiente, y workflows desactivados); `crear` añade el campo Agente con los agentes activos. Para otra plantilla: `plantilla_tablero` en
`equipo.json`. Un tablero creado sin plantilla y aún vacío se sustituye con
`python3 equipo.py <proyecto> tablero rehacer` (el antiguo no se borra; elimínalo tú en Settings → Delete project).

## Vistas y agrupación por Estado

Dos vistas: «Tablero» (Board, columnas por Estado) y «Planning» (Table, filtro Estado:Planning, orden
Prioridad ↑). Si el tablero no viene de la plantilla, créalas en la web (1 min).

`verificar` (y el panel) leen con GraphQL por qué campo agrupa sus columnas la vista «Tablero»
(`verticalGroupByFields`). Si no es **Estado** (por ejemplo, Status, el campo por defecto de GitHub), lo
marcan como pendiente: Vista Tablero → Column by → Estado → Save. En el ensayo, el doble `fake_gh.py` lo simula
con la clave `agrupar` de cada vista (`{"name": "Tablero", "layout": "BOARD_LAYOUT", "agrupar": ["Estado"]}`).

## Etiquetas estado y prioridad

Una issue abierta en el repo sin pasar por el tablero entra sola gracias a `tablero-issue.yml`:

- `estado:backlog`, `estado:planning` o `estado:todo` → la coloca en esa columna (sin etiqueta, en Planning).
- `prioridad:p0` … `prioridad:p3` → le pone esa prioridad.

Las etiquetas antiguas de estado del piloto (`ready`, `running`, `review`, `blocked`) se migran al tablero con
`tablero.py migrar` (ver [Instalación](instalacion.md#token-y-secretos-tablero-y-actions)).

## Crear una tarea

Desde la terminal:

```bash
python3 tablero.py nueva "Añadir media de puntos" --agente local \
  --archivo src/puntos.py --archivo tests/test_puntos.py \
  --criterio "media([2, 4]) == 3" --criterio "lista vacía → ValueError" \
  --prueba unit --prioridad P2 --todo
```

`--agente` admite cualquier agente activo del proyecto. Sin `--todo` queda en Backlog. Si faltan agente, archivos, criterios o prueba, se crea en Backlog con los
huecos marcados (y `--todo` se rechaza). `--dep N` añade una dependencia (sección y relación «Blocked by»: ver
[Guía de uso](guia-uso.md#dependencias)). En la web: New issue → «Tarea para agente», añadirla al proyecto
Equipo IA y moverla a To Do. Desde el panel: [Nueva tarea](panel.md#nueva-tarea).

## Qué depende del PC y qué no

| Sigue funcionando con el PC apagado (GitHub) | Necesita el PC encendido |
|---|---|
| Mantenimiento semanal/manual y propuestas en Planning | Coordinador (`vigilar`) que ejecuta To Do |
| Avisos de Dependabot y PR de Dependabot | Claude Code (sesión Pro) y OpenCode + Ollama |
| Done al integrar PR; PRO al desplegar; reversiones | Worktrees, registro local y lecciones |
| Capturar, priorizar y autorizar tarjetas en la web/móvil | — |
