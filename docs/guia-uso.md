# Guía de uso: cómo trabajar con el equipo

[← Índice de la documentación](README.md)

## Comandos habituales

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

## El día a día

1. Apunta ideas en **Backlog** (web, móvil o el formulario «Nueva tarea» del [panel](panel.md)). Una issue abierta en el
   repo entra sola en **Planning** (`tablero-issue.yml`); con la etiqueta `estado:backlog` o `estado:todo` cae en
   esa columna, y con `prioridad:p0`…`p3`, con esa prioridad (ver [Tablero](tablero.md#etiquetas-estado-y-prioridad)).
2. Cuando una tarjeta tiene agente, archivos, criterios y prueba, **arrástrala a To Do**: eso la autoriza.
3. Pulsa **Arrancar** en el panel. El equipo toma las tarjetas de To Do y, al terminar, la PR queda en
   **Testing / Review** con la CI en verde.
4. Revisa la PR en GitHub e **intégrala**. La tarjeta pasa sola a **Done**.

## Cola y prioridades

**Qué tarjeta coge primero.** Solo las de **To Do**, por prioridad (P0 → P3; sin prioridad, al final) y, a
igual prioridad, la más antigua. Se salta las que tienen Bloqueo o esperan una dependencia. Hay **un trabajador
por agente**: Claude y el local trabajan en paralelo, pero cada uno con una sola tarea a la vez. Una P0 no
interrumpe la tarea en curso del mismo agente: espera a que termine.

## Dependencias

Se escriben en la sección «Dependencias» de la issue (`#12`) **o** con la relación nativa
**«Blocked by»** de GitHub (en la propia tarjeta: *Relationships → Mark as blocked by*). El coordinador usa la
unión de las dos: la sección y las relaciones «blocked by» abiertas, que lee por REST
(`GET repos/<repo>/issues/<n>/dependencies/blocked_by`; si esa API falla, solo cuenta la sección). Una
«blocked by» de otro repo hace esperar mientras siga abierta. `tablero.py nueva --dep N` (y el campo
Dependencias de «Nueva tarea» en el panel) escribe la sección y además crea la relación
(`POST …/dependencies/blocked_by` con el id numérico de #N); si la API falla, avisa y la tarea se crea igual.

Una dependencia cuenta como lista cuando está en **Testing / Review** o más allá, aunque no esté integrada. La
tarea dependiente parte de `main`, sin los cambios de la anterior, así que si las dos tocan los mismos archivos,
integra antes la primera. Si la dependencia sigue en Backlog o Planning, la dependiente espera indefinidamente:
muévelas juntas o deja la dependiente fuera de To Do (el panel lo avisa en «Requiere tu atención»). El log lo
muestra como `esperando_dependencias: [N]`.

## Integrar varias PR seguidas

Hazlo de una en una y en el orden de la cadena. Después de cada integración, abre la siguiente: si GitHub
muestra **Update branch**, púlsalo y espera a que la CI vuelva a salir en verde. Si dice que hay
**conflictos**, no lo resuelvas a mano: pídeselo al TL o usa «Reintentar con el agente». Con conflictos,
GitHub no lanza la CI y la tarea se queda esperando (el coordinador lo detecta: ver
[CI y pruebas](ci-y-pruebas.md#la-ci-del-proyecto-como-juez---prueba-ci)).

## Parar el equipo

«Parar» es suave: termina la tarea en curso y luego se detiene. Si esa tarea está esperando algo que no llega
(por ejemplo, una CI que no se lanzó), córtalo a mano:

```bash
python3 equipo.py proyectos          # equipo-ia … ● en marcha (PID 12345)
kill 12345
python3 equipo.py equipo-ia reanudar N --desde ci   # o el paso que toque; la tarjeta vuelve a To Do
```

## Tarjetas bloqueadas

El campo **Bloqueo** dice la causa y cómo seguir. En el panel: **Reanudar** continúa desde el paso pendiente
sin volver a llamar al agente; **Reintentar con el agente** le pasa el fallo (por ejemplo, el log de la CI) para
que lo corrija. Para reintentar también basta con **vaciar Bloqueo** en el tablero (o
`python coordinador.py reanudar N`).

## Done y PRO

Done = integrado en `main` con la CI en verde. PRO = funcionando en producción: lo pone solo
`despliegue.yml`/`mantenimiento.yml` cuando un despliegue **correcto** incluye el cambio. No se arrastra a mano
(el sistema lo devuelve a Done). En `equipo-ia` no hay despliegue: **Done es el final**. En los proyectos sin
servidor todavía, el despliegue es simulado. Más detalle en [Mantenimiento](mantenimiento.md#despliegue-y-pro).

## Actualizar tu instalación

Cuando se integran mejoras del propio equipo:

```bash
cd "/mnt/c/Users/neo_s/Documents/30 Proyectos/equipo-ia-lab"
python3 equipo.py equipo-ia parar    # o kill <PID> si está esperando
git pull --ff-only
python3 equipo.py panel              # reinicia el panel (cierra antes el anterior con Ctrl+C)
```

## ¿Qué hago ahora?

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

## Comandos del coordinador (un proyecto, estilo v3)

`coordinador.py` se puede usar directamente sobre el proyecto configurado (en la v4, `equipo.py <proyecto> …`
hace lo mismo para cada proyecto):

| Acción | Comando |
|---|---|
| Arrancar (modo continuo) | `python coordinador.py vigilar` |
| Parar (desde otra terminal) | `python coordinador.py parar`  ·  o Ctrl+C |
| Procesar la cola una vez | `python coordinador.py una-vez` |
| Consultar estado | `python coordinador.py estado` |
| Reanudar una issue | `python coordinador.py reanudar 7` (o volver a poner `ready` en GitHub) |
| Repetir un paso | `python coordinador.py reanudar 7 --desde agente` (`worktree`, `agente`, `verificada`, `commit`, `push`, `pr`, `ci`, `revision-agentes`) |

Las reglas que aplica el coordinador en cada tarea están en [Arquitectura](arquitectura.md#reglas-que-aplica-el-coordinador).
