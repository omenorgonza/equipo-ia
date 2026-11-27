# Agentes y lecciones

[← Índice de la documentación](README.md)

## Perfiles

| Quién | Papel | Qué hace |
|---|---|---|
| **Óscar** | Decide | Captura ideas en Backlog, autoriza pasando a To Do, integra las PR. |
| **Codex** | Team Leader (TL) | Prepara las issues (Planning) con agente, archivos permitidos, criterios y prueba; revisa las PR. |
| **Claude** (`agent:claude`) | Desarrollador senior | Claude Code con la sesión Pro. Es el `revision.senior`: revisa, recibe las tareas escaladas y puede delegar subtareas. |
| **local** (`agent:local`) | Desarrollador junior | OpenCode + Ollama en tu PC. Sus fallos se reintentan y escalan al senior. |

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
senior no está activo, tras el segundo fallo del junior queda en Bloqueo.

Para desactivarlo (un fallo → Bloqueo, como antes), en `equipo.json` o en el `config.json` del proyecto:

```json
"escalar_fallos": false
```

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
