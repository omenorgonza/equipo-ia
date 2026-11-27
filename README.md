# equipo-ia-lab

## Versión 4 — varios proyectos y panel local

Un solo equipo instalado y varios proyectos configurados; arrancas el que te interese.

```
equipo-ia-lab/
  equipo.py · panel.py · panel.html     ← gestión de proyectos y panel web local
  equipo.json                            ← compartido: agentes, modelo local, límites
  lecciones/                             ← compartidas: lo que aprende el agente local sirve en todos
  proyectos/<nombre>/                    ← por proyecto: config.json, estado/, worktrees/, repo/
```

### Uso

```bash
python3 equipo.py panel                       # http://127.0.0.1:8765 (se abre en tu navegador de Windows)
python3 equipo.py proyectos                   # lista y estado
python3 equipo.py family-finance vigilar      # arrancar el equipo en un proyecto (o el botón del panel)
python3 equipo.py family-finance parar
python3 equipo.py family-finance estado
python3 equipo.py family-finance tablero ver
python3 equipo.py family-finance reanudar 7 --desde agente
python3 equipo.py importar family-finance --repo omenorgonza/family-finance --descripcion "…"
python3 equipo.py nuevo contestspy --repo contestspy --stack vacio --descripcion "…"
```

### Guía de uso: cómo trabajar con el equipo

**El día a día**
1. Apunta ideas en **Backlog** (web, móvil o el formulario «Nueva tarea» del panel). Una issue abierta en el
   repo entra sola en **Planning** (`tablero-issue.yml`); con la etiqueta `estado:backlog` o `estado:todo` cae en
   esa columna, y con `prioridad:p0`…`p3`, con esa prioridad.
2. Cuando una tarjeta tiene agente, archivos, criterios y prueba, **arrástrala a To Do**: eso la autoriza.
3. Pulsa **Arrancar** en el panel. El equipo toma las tarjetas de To Do y, al terminar, la PR queda en
   **Testing / Review** con la CI en verde.
4. Revisa la PR en GitHub e **intégrala**. La tarjeta pasa sola a **Done**.

**Qué tarjeta coge primero.** Solo las de **To Do**, por prioridad (P0 → P3; sin prioridad, al final) y, a
igual prioridad, la más antigua. Se salta las que tienen Bloqueo o esperan una dependencia. Hay **un trabajador
por agente**: Claude y el local trabajan en paralelo, pero cada uno con una sola tarea a la vez. Una P0 no
interrumpe la tarea en curso del mismo agente: espera a que termine.

**Dependencias.** Se escriben en la sección «Dependencias» de la issue (`#12`) **o** con la relación nativa
**«Blocked by»** de GitHub (en la propia tarjeta: *Relationships → Mark as blocked by*). El coordinador usa la
unión de las dos: la sección y las relaciones «blocked by» abiertas, que lee por REST
(`GET repos/<repo>/issues/<n>/dependencies/blocked_by`; si esa API falla, solo cuenta la sección). Una
«blocked by» de otro repo hace esperar mientras siga abierta. `tablero.py nueva --dep N` (y el campo
Dependencias de «Nueva tarea» en el panel) escribe la sección y además crea la relación
(`POST …/dependencies/blocked_by` con el id numérico de #N); si la API falla, avisa y la tarea se crea igual.
Una dependencia cuenta como lista cuando está en **Testing / Review** o más allá, aunque no esté integrada. La tarea dependiente parte de
`main`, sin los cambios de la anterior, así que si las dos tocan los mismos archivos, integra antes la primera.
Si la dependencia sigue en Backlog o Planning, la dependiente espera indefinidamente: muévelas juntas o deja la
dependiente fuera de To Do (el panel lo avisa en «Requiere tu atención»). El log lo muestra como `esperando_dependencias: [N]`.

**Integrar varias PR seguidas.** Hazlo de una en una y en el orden de la cadena. Después de cada integración,
abre la siguiente: si GitHub muestra **Update branch**, púlsalo y espera a que la CI vuelva a salir en verde.
Si dice que hay **conflictos**, no lo resuelvas a mano: pídeselo al TL o usa «Reintentar con el agente». Con
conflictos, GitHub no lanza la CI y la tarea se queda esperando.

**Parar el equipo.** «Parar» es suave: termina la tarea en curso y luego se detiene. Si esa tarea está esperando
algo que no llega (por ejemplo, una CI que no se lanzó), córtalo a mano:
```bash
python3 equipo.py proyectos          # equipo-ia … ● en marcha (PID 12345)
kill 12345
python3 equipo.py equipo-ia reanudar N --desde ci   # o el paso que toque; la tarjeta vuelve a To Do
```

**Tarjetas bloqueadas.** El campo **Bloqueo** dice la causa y cómo seguir. En el panel: **Reanudar** continúa
desde el paso pendiente sin volver a llamar al agente; **Reintentar con el agente** le pasa el fallo (por ejemplo,
el log de la CI) para que lo corrija.

**Done y PRO.** Done = integrado en `main` con la CI en verde. PRO = funcionando en producción: lo pone solo
`despliegue.yml`/`mantenimiento.yml` cuando un despliegue **correcto** incluye el cambio. No se arrastra a mano
(el sistema lo devuelve a Done). En `equipo-ia` no hay despliegue: **Done es el final**. En los proyectos sin
servidor todavía, el despliegue es simulado.

**Actualizar tu instalación** cuando se integran mejoras del propio equipo:
```bash
cd "/mnt/c/Users/neo_s/Documents/30 Proyectos/equipo-ia-lab"
python3 equipo.py equipo-ia parar    # o kill <PID> si está esperando
git pull --ff-only
python3 equipo.py panel              # reinicia el panel (cierra antes el anterior con Ctrl+C)
```

### ¿Qué hago ahora?

No hace falta deducirlo mirando el tablero: el equipo calcula **el siguiente paso** y lo enseña en dos sitios.

- **En el panel**, el bloque «¿Qué hago ahora?» (arriba del todo) muestra por proyecto la primera acción en
  negrita («Siguiente paso: integrar la PR #33 (#24 …)»), las siguientes («Después: 2. … · 3. …») y las tarjetas
  que conviene esperar con su motivo. Si la acción es reanudar o reintentar, el botón está ahí mismo; si es
  integrar una PR, el enlace la abre. En la lista de tareas de cada proyecto, cada tarjeta lleva debajo su texto.
- **En el tablero de GitHub** (también desde el móvil), el campo de texto **Siguiente** de cada tarjeta dice lo
  mismo. Añádelo como columna en la vista «Planning» (Table → `+` → Siguiente) y, si quieres, muéstralo en las
  tarjetas de la vista «Tablero» (Board → View → Fields → Siguiente).

El orden de las acciones es siempre el mismo:
1. **Integrar** las PR de **Testing / Review** con la CI en verde (o sin CI). En una cadena, la dependencia primero.
2. **Arreglar** las PR con conflictos o con la CI en rojo: `reanudar N --desde agente` («Reintentar con el agente»).
3. **Reanudar** las tarjetas con Bloqueo: `reanudar N`.
4. **Pasar a To Do** las de **Planning** que pueden empezar ya. Una de Planning con un Bloqueo antiguo se
   recomienda como `reanudar N` (retira el Bloqueo y la deja en To Do; moverla sin más no basta, la cola la salta).

Qué significa cada texto del campo Siguiente:

| Texto | Qué hacer |
|---|---|
| `▶ 1 · integrar la PR #33 (#24 …)` | La acción número 1 (la de arriba del banner). Hazla en ese orden. |
| `⏸ espera: comparte coordinador.py con la PR #33 (#24)` | No la pases a To Do hasta integrar esa PR: chocarían. |
| `⏸ espera a #21: comparte panel.py` | Otra tarjeta de Planning recomendada antes toca lo mismo: primero esa. |
| `⏸ espera dependencia #24 (en review, sin integrar)` | La dependencia aún no está en `main`: intégrala antes. |
| `⏳ espera la CI de la PR #33` · `⏳ en cola: la cogerá claude` · `⚙ en curso (local)` | Nada: el equipo sigue solo. |
| `✎ completar la issue: falta agente, comando de prueba` | Rellena esos campos de la issue antes de autorizarla. |

Las esperas por **archivos compartidos** comparan los archivos permitidos de la tarjeta con los de las PR abiertas
(los archivos cambiados de verdad) y con los de las tareas en To Do, Doing o Review. README, `docs/` y los
ensayos no cuentan: casi todas las tareas los tocan y se reconcilian sin problema.

**Quién lo escribe.** El coordinador lo recalcula en cada ciclo (al elegir tareas y al terminarlas) y el panel,
cuando el equipo está parado, al refrescar el tablero. Solo se escriben las tarjetas cuyo texto cambia (sin
escrituras repetidas) y el campo se **vacía** cuando la tarjeta ya no necesita nada (Done, PRO, Backlog). Sin
poder leer las PR abiertas no se escribe nada, para no publicar una recomendación falsa. A mano:
```bash
python3 equipo.py equipo-ia tablero siguiente        # muestra la lista y actualiza el campo (lo crea si falta)
python3 equipo.py equipo-ia tablero siguiente --ver  # solo mostrar
```
Los tableros nuevos traen el campo (`tablero.py crear`); en uno antiguo, `tablero siguiente` lo crea y el panel
avisa en «Puesta a punto pendiente» mientras falte.

### Qué hace el panel

- **¿Qué hago ahora?**: el siguiente paso de cada proyecto (ver la sección anterior).
- **Requiere tu atención**: PR por revisar, tarjetas bloqueadas, avisos de
  seguridad críticos/altos y CI en rojo en la rama principal, de todos los proyectos a la vez. También avisa
  cuando una tarea de To Do espera a otra que no está ni en To Do, ni en curso, ni en review (Backlog, Planning
  o fuera del tablero): se quedaría esperando para siempre.
  Toda tarjeta bloqueada tiene **Reanudar** (`coordinador.py reanudar N`: sigue desde el paso pendiente,
  sin volver a llamar al agente si su trabajo ya está hecho); las que fallaron por CI, pruebas o falta de
  cambios tienen además «Reintentar con el agente» (`reanudar N --desde agente`).
- **Puesta a punto pendiente** (plegable): vistas del tablero, vista «Tablero» con columnas por otro campo
  que no es Estado (p. ej. Status), secreto TABLERO_TOKEN, PR de instalación.
- **Una tarjeta por proyecto**: estado del README, resumen, contadores por columna, repos con su CI, tareas en
  curso, enlaces al tablero y botones Arrancar/Parar/Ver log. Las tareas de To Do que esperan una dependencia
  (sección o «Blocked by») muestran «espera a #N» con enlace a la dependencia.
- **Guardar TABLERO_TOKEN** (botón en cada tarjeta): pegas un token clásico en un campo de contraseña; el panel
  comprueba con GitHub que es de tu usuario y que tiene los scopes `repo` y `project`, y solo entonces lo guarda
  con `gh secret set TABLERO_TOKEN` (por stdin) en **todos** los repos del proyecto, indicando en cuáles. El token
  no se escribe en disco, en logs, en la URL ni en las respuestas; la acción es un POST que exige el token del panel.
- **Color propio por proyecto**: la tarjeta lleva una franja superior y un fondo suave del color del proyecto, y
  su etiqueta en «Requiere tu atención» usa el mismo color. Se cambia con las 8 muestras de la tarjeta (azul,
  verde, naranja, violeta, turquesa, rosa, ámbar, rojo; legibles en modo claro y oscuro) y se guarda en
  `proyectos/<p>/config.json` (clave `color`). `nuevo`/`importar`/`migrar` asignan el primero libre de la paleta.
- **Nuevo proyecto**: crea uno o varios repos privados con andamiaje (vacío o Python), el tablero, los
  workflows y la configuración. **Añadir proyecto existente**: no toca tu código; detecta la CI y abre una PR
  con la instalación.
- **Nueva tarea** (botón en la tarjeta del proyecto): formulario con título, objetivo, agente, archivos
  permitidos, criterios, prueba, dependencias y prioridad. Por defecto la tarjeta va a **Planning**; con
  «Directa a To Do» queda autorizada. Usa `tablero.py nueva` por debajo, así que aplica las mismas
  validaciones (To Do exige agente, archivos, criterios y prueba; `ci` solo si el proyecto tiene `ci.checks`)
  y sus errores se muestran en el formulario sin crear nada. API: `POST /api/proyecto/<nombre>/tarea` con
  la cabecera `X-Token`.
- **Progreso en directo de las tareas en Doing**: en la tarjeta del proyecto, cada tarea en curso muestra
  «#23 · claude · paso agente · 7 min (límite 30) · última actividad hace 20 s · 3 archivos cambiados», más la
  última línea del agente y, si hay tareas anteriores, el tiempo medio de ese paso («estimado ~N min», de
  `tiempos` en `registro.db`). Los archivos salen de `git status --porcelain` en el worktree. Sin actividad
  durante más de 5 minutos (`umbral_atasco_s` en el `config.json` del proyecto) la tarea se marca en ámbar como
  **posible atasco** y sale en «Requiere tu atención». **Ver progreso** muestra las últimas 60 líneas de
  `estado/agentes/issue-N.log` y se refresca cada 5 s mientras está abierto; con tareas en curso, el panel
  refresca el progreso cada 10 s. API: `GET /api/estado` (campo `progreso` del proyecto y de cada tarjeta) y
  `GET /api/proyecto/<nombre>/progreso/<N>`.
  - El coordinador guarda en `estado/progreso.json`, por tarea en curso: paso (de `PASOS`), inicio de la tarea
    y del paso, agente, límite de tiempo del paso y última actividad. La entrada desaparece al salir de Doing
    (revisión, bloqueo o parada); las de un coordinador que ya no está vivo no se muestran.
  - La salida del agente se escribe **mientras se ejecuta** en `estado/agentes/issue-N.log`. Claude Code se
    lanza con `--output-format stream-json --verbose` (se fuerza aunque `config.json` diga `json`) y cada evento
    se resume en una línea legible (herramienta usada, archivo leído o editado, texto, resultado); OpenCode se
    registra tal cual. En la espera de la CI, cada consulta cuenta como actividad y queda en el mismo log.
  - Mientras Claude piensa, stream-json manda un evento `system`/`thinking_tokens` por segundo. No se escribe
    una línea por evento: la línea viva «pensando… N s» va en `progreso.json` (`ultima_linea` y `pensando_s`),
    y «Ver progreso» y la tarjeta de Doing la muestran al final del log, sumando segundos en cada refresco. Al
    llegar otro evento, `issue-N.log` recibe una sola línea «pensó N s». `init` se muestra como «sesión iniciada
    · modelo X»; los demás eventos de sistema cuentan como actividad (no hay aviso de atasco), sin escribir líneas.
  - Los tokens (`sk-ant-…`, `ghp_…`, `github_pat_…`, `Bearer …`) se filtran antes de escribir el log, igual que en
    el resto de logs del coordinador.

Solo escucha en 127.0.0.1 y las acciones exigen un token que cambia en cada arranque.

### Tablero estándar en cada proyecto

Los tableros nuevos se **copian del tablero de ensayo** (vistas «Tablero» y «Planning», campos Estado,
Prioridad, Bloqueo y Siguiente, y workflows desactivados). Para otra plantilla: `plantilla_tablero` en `equipo.json`.
Un tablero creado sin plantilla y aún vacío se sustituye con `python3 equipo.py <proyecto> tablero rehacer`
(el antiguo no se borra; elimínalo tú en Settings → Delete project).

### La CI del proyecto como juez (`--prueba ci`)

En proyectos con CI propia (family-finance: job `tests`), el coordinador no ejecuta pruebas en tu PC:
sube la rama, abre la PR como **borrador** y espera a la CI. Verde → revisión entre agentes → PR lista y tarjeta
en Testing / Review.
Rojo → Bloqueo con el log; «Reintentar con el agente» le pasa el extracto del log del fallo.

- **PR con conflictos con la base**: GitHub no lanza la CI, así que no se espera en vano. En cuanto la API REST
  da `mergeable: false` (`mergeable_state: dirty`) la tarea se bloquea con «PR con conflictos con <base>» y los
  archivos en conflicto. `reanudar N --desde agente` rehace la rama sobre la base actualizada (los cambios
  anteriores quedan en el log y en el prompt, junto con los archivos en conflicto) y la sube con
  `--force-with-lease`.
- **Commits ajenos en la rama** (p. ej. el TL resolviendo conflictos): cuenta la CI del HEAD remoto de la PR
  (`headRefOid`) siempre que descienda del commit del agente. `reanudar N --desde ci` hace antes
  `git pull --ff-only` de la rama remota en el worktree.

### Revisión entre agentes (paso `revision-agentes`)

Antes de que una PR llegue a **Testing / Review**, otro agente la revisa en **dos rondas como mínimo**. La PR sigue en
borrador (proyectos con `--prueba ci`) hasta que la revisión la aprueba. Configuración en `equipo.json` (o en el
`config.json` del proyecto; sin nada escrito se aplican estos valores):

```json
"revision": {"rondas_minimas": 2, "rondas_maximas": 3, "revisores": {"local": "claude", "claude": "claude"}, "senior": "claude"}
```

- **Revisor**: el que diga `revisores` para ese autor; si no hay, otro agente activo distinto del autor. Con
  `claude → claude` es una sesión nueva. Arranca sin la conversación del autor: recibe objetivo, criterios, diff,
  resultado de la CI o de las pruebas, lecciones del autor y hallazgos anteriores. Va en **solo lectura**; si
  modifica archivos o lo intenta, o su veredicto no es un JSON válido, la ronda no cuenta (se descarta lo que haya
  escrito y se repite una vez; a la segunda, Bloqueo). Los revisores respetan `max_por_proveedor`.
- **Rondas**: cada una se publica en la PR («Revisión 1/2 · revisor: claude»). Con hallazgos **bloqueantes**, el autor
  los recibe y corrige, se repiten las pruebas y la CI, y va la siguiente ronda. Los **menores** se anotan y no frenan.
  La ronda 2 se hace siempre. Si entran commits nuevos tras aprobarse, hay rondas nuevas.
- **Escalado**: si tras la ronda 2 quedan bloqueantes y el autor no es el `senior`, la etiqueta cambia a la del senior,
  se explica en la issue y el senior sigue en la misma rama con el historial. Puede delegar hasta 3 subtareas en el
  junior: issues hijas, sin autorizar hasta que Óscar las pase a To Do.
- **Rondas agotadas** (`rondas_maximas`) → Bloqueo con los hallazgos pendientes. `reanudar N --desde agente` se los pasa
  al agente; si los corriges tú en el worktree, `reanudar N`. `reanudar N --desde revision-agentes` pide rondas nuevas.
- **Lecciones**: cada hallazgo bloqueante corregido (la ronda siguiente ya no marca ese archivo) se añade a
  `lecciones/<autor>.md` y a su skill.
- La descripción de la PR lleva la sección «Revisión entre agentes» con rondas, revisores y resultado.

**Revisión previa obligatoria (p. ej. AcademIA)**, en el `config.json` del proyecto:

```json
"revision": {"antes_de_pr": true, "pruebas_locales": ["phpunit", "vitest"], "intensiva_cada": 3}
```

- Las rondas van **antes de subir la rama y abrir la PR**, sobre el diff local y con las pruebas en el worktree: en la
  ronda 1, la de la issue; desde la 2, además todas las de `pruebas_locales` (claves de `pruebas`). Una prueba en rojo
  es un hallazgo bloqueante. Si alguna no se puede ejecutar, o no hay ninguna, **no se abre la PR**: Bloqueo.
- La descripción incluye las rondas, comandos ejecutados, resultados y riesgos residuales.
- `intensiva_cada: 3` añade una ronda intensiva (arquitectura, seguridad, deuda) antes de la 3.ª, 6.ª, 9.ª… PR.

### Reintento y escalado automáticos cuando el junior falla

Si el agente junior (cualquiera que no sea `revision.senior`, normalmente `local`) falla la tarea **por su culpa**, el
equipo no se para a la primera ni hace falta tocar etiquetas, worktrees ni el registro:

1. **Reintento**: se descarta lo que dejó el intento (los cambios sin confirmar del worktree, incluidos los archivos
   fuera de alcance, que nunca llegan al commit) y el junior lo intenta otra vez. Su prompt lleva la causa del fallo.
2. **Escalado**: si vuelve a fallar, la tarea pasa al `senior` (claude): cambia la etiqueta (`agent:claude`), el campo
   **Agente** de la issue y se comenta en ella con los intentos. El senior parte de un worktree limpio en la misma rama.
3. **Si también falla el senior** → Bloqueo como siempre, con el historial de los intentos en el campo Bloqueo, el
   comentario y el log `bloqueo`.

Cuenta como culpa del agente: terminar con código ≠ 0 o por tiempo máximo, no modificar nada, el diff fuera de
«Archivos permitidos» y las pruebas de la issue en rojo. **No** se reintenta ni se escala (Bloqueo como hasta ahora):
cuota agotada, Ollama caído, ejecutable no encontrado, permisos, red, pruebas que no llegan a ejecutarse (código
126/127, tiempo de pruebas agotado o clave no declarada) o fallos de la revisión entre agentes (que tiene
su propio escalado). Cada fallo del junior anota una lección pendiente en `estado/lecciones-pendientes.md`. Si el
senior no está activo, tras el segundo fallo del junior queda en Bloqueo.

Para desactivarlo (un fallo → Bloqueo, como antes), en `equipo.json` o en el `config.json` del proyecto:

```json
"escalar_fallos": false
```

### El propio equipo como proyecto (`omenorgonza/equipo-ia`)

El código del equipo vive en su propio repositorio y se gestiona como cualquier otro proyecto: tarjetas en
su tablero, agentes que trabajan sobre una copia en `proyectos/equipo-ia/` y CI (`ci-equipo.yml`, job
`ensayos`) que ejecuta `pruebas-dobles/ensayo_completo.sh` contra el GitHub simulado. Para actualizar tu
instalación tras integrar una mejora: `git pull` en esta carpeta. `.gitignore` deja fuera tu configuración,
los tokens y las carpetas de cada proyecto.

### Migrar desde la v3 (una vez)

```bash
python3 equipo.py migrar          # mueve config, estado, worktrees y clon a proyectos/ensayo
python3 equipo.py ensayo estado   # comprobar
```

### Limitación conocida

En proyectos con varios repos, el tablero y el mantenimiento cubren todos, pero el coordinador ejecuta las
tareas del **repo principal** (el primero). Las de los demás repos se quedan en To Do.

---


Codex (TL) publica issues en GitHub → `coordinador.py` las recoge → Claude Code u OpenCode + Ollama
trabajan en un `git worktree` propio → el coordinador verifica alcance y pruebas y abre **una** PR
por issue → Codex revisa. Solo biblioteca estándar de Python 3.9+. Pensado para **Windows nativo**
(PowerShell), donde están tu sesión de `claude`, `gh` y el servicio de Ollama.

```
equipo-ia-lab/
  coordinador.py      diagnóstico, una-vez, vigilar, parar, estado, reanudar, probar, configurar-local
  ensayo.py           fases 3-4: preparar-repo, crear-issues, caida-tras-push, unicidad, integrar, ollama-caida
  config.json         configuración de confianza (repo, autor, agentes, comandos de prueba)
  opencode.json       modelo y permisos de OpenCode; se hereda en worktrees/ y estado/pruebas/
  plantillas/         issue form, plantilla para Codex, contrato del piloto, opencode v1/v2
  repo/               clon del repositorio de ensayo        (se crea)
  worktrees/issue-N   un worktree y una rama por tarea      (se crea)
  estado/             registro.db, logs/issue-N, prompts, ensayo-resultados.json
  pruebas-dobles/     gh/claude/opencode/Ollama falsos para probar el coordinador sin red
```

## 0. Instalación (una vez)

Descomprime en `Documents\30 Proyectos\equipo-ia-lab` (fuera de AcademIA) y abre PowerShell ahí.

```powershell
python coordinador.py iniciar          # crea config.json desde config.example.json
python coordinador.py diagnostico      # fase 1: entorno, versiones, gh, claude auth, Ollama y modelos con "tools"
opencode run --help                    # confirma que existen --model, --file y --auto
```

En el diagnóstico comprueba:
- `claude auth status` debe mostrar inicio de sesión con la cuenta Pro (no `apiKey`). En
  claude.ai → Ajustes → Uso, deja **desactivado** el uso adicional de pago. El coordinador elimina
  `ANTHROPIC_*`, `OPENAI_*`, `GEMINI_*`… del entorno de los procesos hijo.
- Si la línea de variables de proveedor muestra alguna, el hijo ya no la hereda, pero conviene quitarla
  también de tu perfil.

## 1. Configurar y aceptar los desarrolladores (fase 2)

```powershell
python coordinador.py configurar-local                       # elige un modelo instalado con "tools" (prefiere *coder*)
python coordinador.py configurar-local --modelo qwen2.5-coder:14b   # o fíjalo tú
python coordinador.py probar local     # OpenCode crea prueba-local.txt = LISTO; muestra api/ps de Ollama
python coordinador.py probar claude    # claude -p crea prueba-claude.txt = LISTO
```

Ambos deben terminar en `RESULTADO: ACEPTADO`. Si OpenCode es de la generación V1 (la config usa
`permission`/`bash` en lugar de `permissions`/`shell`), sustituye `opencode.json` por
`plantillas/opencode.v1.template.json` con el mismo `model`. Si tu versión no tiene `--auto`, quítalo
de `config.json → agentes.local.args_extra`.

## 2. Repositorio de ensayo (fase 3)

Nombre propuesto: **`<tu-usuario>/equipo-ia-lab-ensayo`, privado**. Confírmalo y ejecuta:

```powershell
python ensayo.py preparar-repo --crear                 # o --nombre otro --owner org
```

Crea el repo privado si no existe, sube el commit inicial (contrato, `.github/ISSUE_TEMPLATE/tarea-agente.yml`),
crea las etiquetas `agent:claude agent:local ready running review blocked` y escribe `repo` y
`autor_autorizado` (tu cuenta de `gh`) en `config.json`.

## 3. Uso diario

| Acción | Comando |
|---|---|
| Arrancar (modo continuo) | `python coordinador.py vigilar` |
| Parar (desde otra terminal) | `python coordinador.py parar`  ·  o Ctrl+C |
| Procesar la cola una vez | `python coordinador.py una-vez` |
| Consultar estado | `python coordinador.py estado` |
| Reanudar una issue | `python coordinador.py reanudar 7` (o volver a poner `ready` en GitHub) |
| Repetir un paso | `python coordinador.py reanudar 7 --desde agente` (`worktree`, `agente`, `verificada`, `commit`, `push`, `pr`, `ci`, `revision-agentes`) |

Reglas que aplica el coordinador:
- Solo issues **abiertas, con `ready`, del autor autorizado y del repo configurado**; las demás se ignoran.
- Reserva atómica en `estado/registro.db` (repo + issue) y cerrojo `estado/coordinador.lock`: un único
  coordinador; un trabajador por proveedor; máximo 5 (`max_trabajadores`).
- El texto de la issue es **dato**: va al agente por stdin (Claude) o como archivo adjunto (OpenCode),
  nunca a un shell. `Comando de prueba` es una clave de `config.json → pruebas`.
- Antes de publicar: archivos cambiados ⊆ `Archivos permitidos`, diff guardado en `estado/logs`, pruebas.
  Después: push, una sola PR (`Closes #N`, agente, commit base, comandos y resultado) y etiqueta `review`.
- `blocked` con comentario (causa, recuperación, log, worktree conservado) ante cuota, permisos, tiempo
  máximo, agente sin cambios, diff fuera de alcance, pruebas fallidas u Ollama caído. Un reintento con
  espera para errores de red. Al reiniciar reconcilia registro, rama remota y PR y solo repite lo pendiente.
- Sin relevo: si Ollama no responde, la tarea local se bloquea; nunca pasa a otro proveedor.

## 4. Ensayo completo (fase 4)

```powershell
python ensayo.py completo        # o paso a paso:
python ensayo.py crear-issues    # #A claude → src/puntos.py ; #B local → tests/test_puntos.py ; mismo commit base
python ensayo.py caida-tras-push # se detiene tras subir ramas y reanuda hasta crear las PR
python ensayo.py unicidad        # repite la orden y fuerza una reanudación: 1 rama y 1 PR por issue
python ensayo.py integrar        # rama local temporal con ambas entregas: verde → fallo deliberado → revertir → verde
python ensayo.py ollama-caida    # te pide parar Ollama, comprueba bloqueo sin relevo, te pide arrancarlo y reanuda
```

Resultados en `estado/ensayo-resultados.json` (con tiempos). Criterio de cierre: dos PR revisables,
integración verde, fallo deliberado detectado, recuperación comprobada y cero PR duplicadas.

## 4 bis. Tablero, cola y mantenimiento (roadmap 2)

### Puesta en marcha (una vez, en este orden)

```powershell
gh auth refresh -s project                       # tu sesión local necesita el scope 'project'
python tablero.py crear                          # Project privado + campos Estado, Prioridad, Bloqueo + enlace al repo
#   → en la web del proyecto crea 2 vistas (1 min): «Tablero» (Board, columnas por Estado)
#     y «Planning» (Table, filtro Estado:Planning, orden Prioridad ↑)
python tablero.py migrar                         # SOLO LECTURA: qué pasaría con las etiquetas actuales
python tablero.py migrar --aplicar               # migra, retira etiquetas de estado y fija fuente_cola=tablero
python ensayo_tablero.py instalar-github         # sube workflows + .equipo-ia, activa Dependabot, variables
gh secret set TABLERO_TOKEN --repo <owner/repo>  # token clásico con scopes repo + project (o desde el panel)
python tablero.py verificar                      # campos, vistas, privacidad y permisos con tu identidad
gh workflow run mantenimiento.yml --repo <owner/repo>   # verifica el acceso del workflow (ver resumen del run)
```

`verificar` (y el panel) leen con GraphQL por qué campo agrupa sus columnas la vista «Tablero»
(`verticalGroupByFields`). Si no es **Estado** (por ejemplo, Status, el campo por defecto de GitHub), lo
marcan como pendiente: Vista Tablero → Column by → Estado → Save. En el ensayo, el doble `fake_gh.py` lo simula
con la clave `agrupar` de cada vista (`{"name": "Tablero", "layout": "BOARD_LAYOUT", "agrupar": ["Estado"]}`).

### Quién mueve cada tarjeta (un único sitio por transición)

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

### Crear una tarea ejecutable desde la terminal

```bash
python3 tablero.py nueva "Añadir media de puntos" --agente local \
  --archivo src/puntos.py --archivo tests/test_puntos.py \
  --criterio "media([2, 4]) == 3" --criterio "lista vacía → ValueError" \
  --prueba unit --prioridad P2 --todo
```

Sin `--todo` queda en Backlog. Si faltan agente, archivos, criterios o prueba, se crea en Backlog con los
huecos marcados (y `--todo` se rechaza). En la web: New issue → «Tarea para agente», añadirla al proyecto
Equipo IA y moverla a To Do.

### Lecciones de configuración del piloto (ya aplicadas)

- OpenCode V2 con `default_agent: plan` global → el laboratorio fuerza `--agent build`.
- Ollama arranca los modelos con 4096 tokens de contexto → usar una variante con `num_ctx 32768`
  (`diagnostico` y `configurar-local` avisan y dan los comandos de PowerShell).
- Tras crear una issue, GitHub tarda unos segundos en mostrarla al filtrar por etiqueta; el ensayo espera.
- `gh pr edit` falla en gh 2.45 (consulta `projectCards`, de los Projects clásicos ya retirados) → al
  reprocesar una tarea con PR abierta, el coordinador actualiza la descripción por la API REST
  (`gh api -X PATCH repos/<repo>/pulls/<n> -f body=...`). El ensayo completo lo comprueba.

### Mantenimiento proactivo (GitHub Actions, con el PC apagado)

`mantenimiento.yml`: semanal (lunes 06:17 UTC, línea `cron`) y manual. Fuentes en `.equipo-ia/mantenimiento.json`:
versiones (archivos de bloqueo + endoflife.date), seguridad (alertas Dependabot), normativa (API del sumario
del BOE con palabras clave; AEPD/EUR-Lex listas para activar) y deuda técnica (tests inestables, PR de
Dependabot bloqueadas). Una clave estable por hallazgo → una issue `mantenimiento` y una tarjeta en
Planning; sin cambios no escribe; con evidencia nueva actualiza solo el bloque automático y comenta una vez.
Si una fuente falla, sigue con las demás y marca la revisión como PARCIAL. Registro consultable: issue
«Registro de mantenimiento» (última ejecución y última correcta con enlace) + resumen del run.

**Palabras de normativa propias de cada proyecto** (sin tocar el código): la variable del repo
`NORMATIVA_PALABRAS` (separadas por comas) se suma a las `palabras` de `mantenimiento.json`, sin duplicados
(no distingue mayúsculas ni tildes) e ignorando espacios sobrantes. Sin la variable se usan solo las del JSON.

```bash
gh variable set NORMATIVA_PALABRAS -R <repo> --body "servicios de pago, IRPF, entidades de crédito"   # p. ej. family-finance
gh variable list -R <repo>                                  # comprobar
gh variable delete NORMATIVA_PALABRAS -R <repo>             # volver a solo las del JSON
```

Aviso inmediato = notificación nativa de Dependabot (activa en https://github.com/settings/notifications →
Dependabot alerts). `aviso-critico.yml` verifica destinatario/configuración y envía un aviso **[SIMULADO]**.

### Lecciones del agente local

Cuando el agente local falla por calidad (no escribe, se sale del alcance, pruebas rojas) se anota un
borrador en `estado/lecciones-pendientes.md`. Convierte el aprendizaje en regla:

```powershell
python coordinador.py leccion local "Antes de terminar, comprueba que el archivo pedido existe en la ruta exacta" --issue 12
```

Se inyecta en cada prompt del agente y genera la skill `.opencode/skills/equipo-lecciones-local/SKILL.md`.

### Ensayos de aceptación

```powershell
python ensayo_tablero.py todos      # o: prioridad · bloqueo · reinicio · aviso-duplicado · aviso-critico · remoto · pro
```

Resultados (verificado / simulado / pendiente) en `estado/ensayo-tablero.json`. Contra GitHub real,
`pro` integra dos PR de ensayo en `main` (pide confirmación).

### Qué depende del PC y qué no

| Sigue funcionando con el PC apagado (GitHub) | Necesita el PC encendido |
|---|---|
| Mantenimiento semanal/manual y propuestas en Planning | Coordinador (`vigilar`) que ejecuta To Do |
| Avisos de Dependabot y PR de Dependabot | Claude Code (sesión Pro) y OpenCode + Ollama |
| Done al integrar PR; PRO al desplegar; reversiones | Worktrees, registro local y lecciones |
| Capturar, priorizar y autorizar tarjetas en la web/móvil | — |

## 5. Para Codex (TL)

Usa `plantillas/plantilla-tarea-codex.md`: misma cuenta de `gh` que `autor_autorizado` y el repo de
`config.json → repo`. Para reencolar una issue bloqueada tras corregirla, basta con volver a poner `ready`.

## 6. Pasar a AcademIA (después de su v1)

Copia la carpeta, cambia en `config.json` solo `repo`, `clon_local` y `pruebas` (los comandos de Symfony,
React y E2E que verifiques en el proyecto, p. ej. `["php","bin/phpunit"]`, `["npm","test","--","--run"]`),
y ajusta `opencode.json`/`agentes.claude.args` si esas tareas necesitan permisos adicionales.

## Probar el coordinador sin red

`pruebas-dobles/` contiene `gh`, agentes y Ollama falsos; apunta `gh_bin`, `agentes.*.bin` y
`ollama_url` a ellos con un remoto `git init --bare` y `preparar-repo --remoto <ruta>`.
