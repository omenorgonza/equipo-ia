# Agentes y lecciones

[← Índice de la documentación](README.md)

## Perfiles

| Quién | Papel | Qué hace |
|---|---|---|
| **Óscar** | Decide | Captura ideas en Backlog, autoriza pasando a To Do, integra las PR. |
| **Codex** | Team Leader (TL) | Prepara las issues (Planning) con agente, archivos permitidos, criterios y prueba; revisa las PR. |
| **Claude** (`agent:claude`) | Desarrollador senior | Claude Code con la sesión Pro. Es el `revision.senior`: revisa, recibe las tareas escaladas y puede delegar subtareas. |
| **local** (`agent:local`) | Desarrollador junior | OpenCode + Ollama en tu PC. Sus fallos se reintentan y escalan al senior. |
| **codex** (`agent:codex`, opcional) | Revisor y, a veces, autor | Codex CLI (`codex exec`) con tu sesión de ChatGPT. Ver [Motores del equipo](#motores-del-equipo). |
| **local-plus** (`agent:local-plus`, opcional) | Desarrollador local para tareas medianas | Un segundo modelo de Ollama más potente, sin coste. Ver [Motores del equipo](#motores-del-equipo). |

Para Codex (TL): usa `plantillas/plantilla-tarea-codex.md`, con la misma cuenta de `gh` que `autor_autorizado` y
el repo de `config.json → repo`. Para reencolar una issue bloqueada tras corregirla, basta con volver a poner
`ready` (piloto con etiquetas) o vaciar Bloqueo en el tablero.

Cómo instalar y aceptar cada agente: [Instalación](instalacion.md#agentes-configurar-y-aceptar-los-desarrolladores-fase-2).

## Revisión entre agentes (paso `revision-agentes`)

Antes de que una PR llegue a **Testing / Review**, otro agente la revisa en **dos rondas como mínimo**. La PR
sigue en borrador (proyectos con `--prueba ci`) hasta que la revisión la aprueba. Configuración en `equipo.json`
(o en el `config.json` del proyecto; sin nada escrito se aplican estos valores):

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

## Reintento y escalado automáticos cuando el junior falla

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
senior no está activo, cuando el junior gasta sus intentos la tarea queda en Bloqueo.

### Activar y ajustar el escalado

**Desde el panel.** Cada proyecto tiene la casilla «Escalar al senior» y el selector «tras N fallo(s) del junior».
Pulsa «Guardar escalado»: el panel cambia solo esas dos claves del `config.json` del proyecto y el equipo en marcha
las aplica en el ciclo siguiente, sin reiniciar.

**A mano, en `proyectos/<nombre>/config.json`** (o en `equipo.json` para todos los proyectos):

```jsonc
"escalar_fallos": true,      // false: el primer fallo bloquea la tarea, sin reintento ni escalado
"fallos_para_escalar": 2     // intentos del junior antes de pasar al senior (1–5; con 1 escala al primer fallo)
```

`escalar_fallos` también entiende `"false"`, `"no"` o `0` escritos a mano (y `"true"`, `"sí"`, `1`). Con un valor
que no entiende, lo deja **activado** y lo avisa una vez en el log. Lo mismo vale para `activo` y `standalone` de
cada agente y para `revision.antes_de_pr` (este, si no se entiende, queda apagado).

Los intentos gastados se guardan en el registro: tras un Bloqueo y `reanudar`, el junior solo tiene los que le
quedaban (si ya los gastó, la tarea pasa directamente al senior). Cuando el agente **termina** la tarea (su trabajo
llega al commit), el contador vuelve a cero: si después la CI sale en rojo y ejecutas `reanudar N --desde agente`,
empieza con todos sus intentos (si la tarea ya había escalado, sigue con quien la terminó). Si después de escalar
devuelves la etiqueta al junior, manda la etiqueta: el coordinador pone el campo Agente al día y el junior empieza
con todos sus intentos.

Si una issue no tiene exactamente una etiqueta de agente, el Bloqueo dice cuáles valen: solo las de los agentes
activos.

## Motores del equipo

Además de Claude y del agente local, el equipo admite más motores. Cada uno es una entrada de `agentes` en
`equipo.json` (para todos los proyectos) o en el `config.json` de un proyecto; `config.example.json` trae `codex`
y `local-plus` apagados (`"activo": false`). **Sin estas claves todo funciona como siempre**: sin cadena de
escalado, sin reservas y sin agentes nuevos. Nada de esto guarda cuentas ni datos personales en el repo.

### Añadir Codex (sesión de ChatGPT)

1. Instala Codex CLI e inicia sesión con tu cuenta de ChatGPT: `codex login`. La sesión queda en tu perfil de
   usuario (`~/.codex`), fuera del repo.
2. En `agentes`, activa la entrada:

   ```json
   "codex": {"activo": true, "etiqueta": "agent:codex", "proveedor": "codex", "bin": ["codex"],
             "args": ["exec", "--sandbox", "workspace-write"]}
   ```

3. `python3 equipo.py <proyecto> diagnostico` muestra la versión y el estado de la sesión (`codex login status`)
   sin secretos: tokens y claves salen enmascarados. Avisa si no hay sesión o si Codex usa una API key (de pago).
4. `python3 equipo.py <proyecto> probar codex` hace la prueba de aceptación.

El coordinador lanza `codex exec … --json -` con el prompt por la entrada estándar y sin las variables `OPENAI_*` ni
`CODEX_API_KEY`: siempre usa la sesión de ChatGPT, nunca la API de pago. **Como autor** (`agent:codex`) trabaja
con el sandbox `workspace-write` en su worktree y sigue el camino de siempre: commit → PR → CI → revisión. **Como
revisor** va con `--sandbox read-only`, sin aprobaciones automáticas ni sesiones anteriores; si aun así escribe, o
lo intenta (un evento `file_change`), la ronda no cuenta y se descartan sus cambios.

> `tablero.py nueva --agente` todavía solo acepta `claude` y `local`: para una tarea de Codex, crea la tarjeta y
> cambia su etiqueta a `agent:codex` y su campo **Agente** a `codex`.

### Revisores y reservas

Para que el trabajo de Claude lo mire otro modelo (y repartir la cuota), en `revision`:

```json
"revision": {"revisores": {"claude": "codex", "local": "claude", "codex": "claude"}, "reservas": {"codex": "claude"}}
```

- `revisores`: quién revisa a cada autor (si el revisor está apagado, revisa otro agente activo, el senior primero).
- `reservas`: si un revisor se queda **sin cuota**, revisa su reserva en esa ronda y la PR lleva una nota
  («el revisor `codex` no tiene cuota: revisa `claude` (reserva)»); la ronda sigue contando.
  Si la reserva es **el propio autor** (p. ej. Claude escribió el cambio y `codex` → `claude`), revisa otro agente
  activo (el senior primero) y la nota lo explica («su reserva `claude` es el autor del cambio, así que revisa
  `local`»). Si no hay ninguno, el autor revisa su propio cambio en una sesión nueva y la nota lo dice claramente
  («⚠ `claude` revisa su propio cambio»), para que lo mires con más cuidado.
- Codex **sin cuota como autor**: Bloqueo «Cuota agotada» sin culpa del agente (ni reintento ni escalado), como
  con Claude. `reanudar N` cuando se renueve.

### Añadir un segundo agente local

Para tareas medianas sin coste, un modelo de Ollama más grande (por ejemplo `gpt-oss:20b` con 32k de contexto):

1. `ollama pull gpt-oss:20b` y, si su contexto por defecto es corto, una variante con `num_ctx 32768`
   (`diagnostico` y `configurar-local` te dan los comandos).
2. Añade el agente en `agentes` (copia `local-plus` de `config.example.json` y pon `"activo": true`).
3. Fija su modelo: `python3 equipo.py <proyecto> configurar-local --agente local-plus --modelo gpt-oss:20b-32k:latest`.
   Solo cambia ese agente (en el archivo donde está definido); el agente `local` y el modelo por defecto de
   `opencode.json` no se tocan. Si `opencode.json` tiene su propio catálogo de modelos, el nuevo se añade.

Cada agente local se lanza con `opencode run --standalone --model <su modelo>`: su propia ejecución, sin compartir
sesión con el otro. Si tu OpenCode no conoce `--standalone`, pon `"standalone": false` en el agente.
`diagnostico` lista el catálogo de OpenCode (`opencode models`) y avisa si el modelo de un agente local no está
instalado en Ollama o no aparece en ese catálogo, que es lo que haría fallar al agente al arrancar. Si el servicio de
OpenCode no arranca, usa lo que `opencode models` llegara a listar o, si no listó nada, el catálogo propio de
`opencode.json` (`provider.ollama.models`), y dice de dónde lo ha sacado.

`probar <agente>` trabaja en una carpeta nueva de `estado/pruebas/` que es su propio repo git: OpenCode escribe en
la raíz git del directorio actual, así que sin ese repo el archivo de la prueba caería en la raíz del laboratorio.
Si no puede crear ese repo (`git init` falla, p. ej. por un `git_bin` mal puesto), `probar` se detiene con `FALLO`
antes de lanzar el agente.

Si añades un agente solo en el `config.json` de un proyecto, `python3 equipo.py <proyecto> preparar` crea su
etiqueta (`agent:<nombre>`) en los repos del proyecto; repite también el resto de la preparación de GitHub
(variables y comprobación del secreto `TABLERO_TOKEN`) sin tocar el código. Solo dice «etiquetas al día» si GitHub
las aceptó todas: si rechaza alguna (token sin permiso de escritura, red…), lista cada etiqueta con su motivo, la deja
en «Pendiente para Óscar» y termina con error.

### Cadena de escalado

Con varios agentes, el junior no tiene por qué saltar directamente al senior:

```json
"cadena_escalado": ["local", "local-plus", "claude"]
```

Cuando un agente de la cadena gasta sus `fallos_para_escalar` intentos, la tarea pasa al **siguiente agente activo**
de la cadena (etiqueta, campo Agente y comentario «pasa a `local-plus` (siguiente en la cadena de escalado)»). Con el
valor por defecto (2), dos fallos de `local` → `local-plus`; dos de `local-plus` → `claude`. Los agentes que no
están en la cadena escalan al `senior`, como siempre. El panel muestra la cadena junto al ajuste del escalado; se
cambia en el `config.json` y `vigilar` la relee en cada ciclo.

### Turnos de GPU

`max_por_proveedor` (1 por defecto) limita cuántos agentes de un **mismo proveedor** trabajan a la vez, contando a
los revisores. Los dos agentes locales comparten el proveedor `ollama`, así que con `1` **nunca corren a la vez**
y no se pelean por la GPU: el segundo espera su turno («esperando turno de local-plus (ollama)»). Claude, Codex y
Ollama son proveedores distintos y sí pueden trabajar en paralelo.

## Lecciones y skills

`lecciones/` es compartida por todos los proyectos: lo que aprende un agente sirve en todos. Cada agente tiene
su archivo (`lecciones/<agente>.md`); sus reglas se inyectan en cada prompt del agente y generan la skill
`.opencode/skills/equipo-lecciones-<agente>/SKILL.md`. Llegan por dos caminos:

- **Hallazgos de la revisión entre agentes** corregidos por el autor (automático, ver arriba).
- **Fallos del agente local por calidad** (no escribe, se sale del alcance, pruebas rojas): se anota un borrador
  en `estado/lecciones-pendientes.md`. Convierte el aprendizaje en regla:

```powershell
python coordinador.py leccion local "Antes de terminar, comprueba que el archivo pedido existe en la ruta exacta" --issue 12
```

En la v4: `python3 equipo.py <proyecto> leccion local "…" --issue 12`.
