# Panel local

[← Índice de la documentación](README.md)

```bash
python3 equipo.py panel          # http://127.0.0.1:8765 (se abre en tu navegador de Windows)
python3 equipo.py panel --puerto 8790 --no-abrir
```

Solo escucha en 127.0.0.1 y las acciones exigen un token que cambia en cada arranque (cabecera `X-Token`).

## Qué muestra

- **¿Qué hago ahora?**: el siguiente paso de cada proyecto (ver [Guía de uso](guia-uso.md#qué-hago-ahora)).
- **Requiere tu atención**: PR por revisar, tarjetas bloqueadas, avisos de seguridad críticos/altos y CI en rojo
  en la rama principal, de todos los proyectos a la vez. También avisa cuando una tarea de To Do espera a otra
  que no está ni en To Do, ni en curso, ni en review (Backlog, Planning o fuera del tablero): se quedaría
  esperando para siempre.
- **Puesta a punto pendiente** (plegable): vistas del tablero, vista «Tablero» con columnas por otro campo
  que no es Estado (p. ej. Status), secreto TABLERO_TOKEN, PR de instalación, campo Siguiente que falta.
- **Una tarjeta por proyecto**: estado del README, resumen, contadores por columna, repos con su CI, tareas en
  curso, enlaces al tablero y botones Arrancar/Parar/Ver log. Las tareas de To Do que esperan una dependencia
  (sección o «Blocked by») muestran «espera a #N» con enlace a la dependencia.

## Arrancar / Parar / Ver log

- **Arrancar** lanza el coordinador del proyecto (`equipo.py <proyecto> vigilar`): toma las tarjetas de To Do.
- **Parar** es suave: termina la tarea en curso y luego se detiene (`equipo.py <proyecto> parar`). Si se queda
  esperando algo que no llega, ver [Parar el equipo](guia-uso.md#parar-el-equipo).
- **Ver log** muestra las últimas 60 líneas del log del coordinador (`proyectos/<p>/estado/vigilar.log`).

## Reanudar y Reintentar con el agente

Toda tarjeta bloqueada tiene **Reanudar** (`coordinador.py reanudar N`: sigue desde el paso pendiente, sin
volver a llamar al agente si su trabajo ya está hecho); las que fallaron por CI, pruebas o falta de cambios
tienen además **Reintentar con el agente** (`reanudar N --desde agente`), que le pasa el fallo para que lo
corrija.

## Escalado al senior

Cada proyecto tiene la casilla «Escalar al senior» y el selector «tras N fallo(s) del junior», con los valores de
su `config.json`. «Guardar escalado» cambia solo `escalar_fallos` y `fallos_para_escalar` y el equipo en marcha los
aplica en el ciclo siguiente. Detalles en
[Activar y ajustar el escalado](agentes-y-lecciones.md#activar-y-ajustar-el-escalado).

Si el proyecto tiene `cadena_escalado`, la casilla dice «Escalar por la cadena (local → local-plus → claude)»; la
cadena se cambia en el `config.json` ([Cadena de escalado](agentes-y-lecciones.md#cadena-de-escalado)). El selector
de agente de «Nueva tarea» lista los agentes activos del proyecto.

## Guardar TABLERO_TOKEN

Botón en cada tarjeta: pegas un token clásico en un campo de contraseña; el panel comprueba con GitHub que es
de tu usuario y que tiene los scopes `repo` y `project`, y solo entonces lo guarda con `gh secret set
TABLERO_TOKEN` (por stdin) en **todos** los repos del proyecto, indicando en cuáles. El token no se escribe en
disco, en logs, en la URL ni en las respuestas; la acción es un POST que exige el token del panel.

## Color propio por proyecto

La tarjeta lleva una franja superior y un fondo suave del color del proyecto, y su etiqueta en «Requiere tu
atención» usa el mismo color. Se cambia con las 8 muestras de la tarjeta (azul, verde, naranja, violeta,
turquesa, rosa, ámbar, rojo; legibles en modo claro y oscuro) y se guarda en `proyectos/<p>/config.json`
(clave `color`). `nuevo`/`importar`/`migrar` asignan el primero libre de la paleta.

## Nueva tarea

Botón en la tarjeta del proyecto: formulario con título, objetivo, agente, archivos permitidos, criterios,
prueba, dependencias y prioridad. Por defecto la tarjeta va a **Planning**; con «Directa a To Do» queda
autorizada. Usa `tablero.py nueva` por debajo (ver [Tablero](tablero.md#crear-una-tarea)), así que aplica las
mismas validaciones (To Do exige agente, archivos, criterios y prueba; `ci` solo si el proyecto tiene
`ci.checks`) y sus errores se muestran en el formulario sin crear nada. El campo Dependencias crea también la
relación «Blocked by». API: `POST /api/proyecto/<nombre>/tarea` con la cabecera `X-Token`.

## Nuevo proyecto y Añadir proyecto existente

- **Nuevo proyecto** (`equipo.py nuevo`): crea uno o varios repos privados con andamiaje (vacío o Python), el
  tablero, los workflows y la configuración.
- **Añadir proyecto existente** (`equipo.py importar`): no toca tu código; detecta la CI y abre una PR con la
  instalación.

## Progreso en directo de las tareas en Doing

En la tarjeta del proyecto, cada tarea en curso muestra «#23 · claude · paso agente · 7 min (límite 30) ·
última actividad hace 20 s · 3 archivos cambiados», más la última línea del agente y, si hay tareas
anteriores, el tiempo medio de ese paso («estimado ~N min», de `tiempos` en `registro.db`). Los archivos salen
de `git status --porcelain` en el worktree. Sin actividad durante más de 5 minutos (`umbral_atasco_s` en el
`config.json` del proyecto) la tarea se marca en ámbar como **posible atasco** y sale en «Requiere tu
atención». **Ver progreso** muestra las últimas 60 líneas de `estado/agentes/issue-N.log` y se refresca cada
5 s mientras está abierto; con tareas en curso, el panel refresca el progreso cada 10 s. API: `GET /api/estado`
(campo `progreso` del proyecto y de cada tarjeta) y `GET /api/proyecto/<nombre>/progreso/<N>`.

- El coordinador guarda en `estado/progreso.json`, por tarea en curso: paso (de `PASOS`, ver
  [Arquitectura](arquitectura.md#pasos-del-coordinador)), inicio de la tarea y del paso, agente, límite de
  tiempo del paso y última actividad. La entrada desaparece al salir de Doing (revisión, bloqueo o parada); las
  de un coordinador que ya no está vivo no se muestran.
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
