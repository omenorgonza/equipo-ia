# CI y pruebas

[← Índice de la documentación](README.md)

## La CI del proyecto como juez (`--prueba ci`)

En proyectos con CI propia (family-finance: job `tests`), el coordinador no ejecuta pruebas en tu PC:
sube la rama, abre la PR como **borrador** y espera a la CI. Verde → revisión entre agentes (ver
[Agentes y lecciones](agentes-y-lecciones.md#revisión-entre-agentes-paso-revision-agentes)) → PR lista y tarjeta
en Testing / Review. Rojo → Bloqueo con el log; «Reintentar con el agente» le pasa el extracto del log del fallo.

- **PR con conflictos con la base**: GitHub no lanza la CI, así que no se espera en vano. En cuanto la API REST
  da `mergeable: false` (`mergeable_state: dirty`) la tarea se bloquea con «PR con conflictos con <base>» y los
  archivos en conflicto. `reanudar N --desde agente` rehace la rama sobre la base actualizada (los cambios
  anteriores quedan en el log y en el prompt, junto con los archivos en conflicto) y la sube con
  `--force-with-lease`.
- **Commits ajenos en la rama** (p. ej. el TL resolviendo conflictos): cuenta la CI del HEAD remoto de la PR
  (`headRefOid`) siempre que descienda del commit del agente. `reanudar N --desde ci` hace antes
  `git pull --ff-only` de la rama remota en el worktree.

Sin CI propia, el coordinador ejecuta en el worktree el `Comando de prueba` de la issue: una clave de
`config.json → pruebas` (nunca un comando libre).

## El ensayo completo del equipo (check «ensayos»)

El código del equipo vive en su propio repositorio (`omenorgonza/equipo-ia`) y se gestiona como cualquier otro
proyecto: tarjetas en su tablero, agentes que trabajan sobre una copia en `proyectos/equipo-ia/` y CI
(`ci-equipo.yml`, job `ensayos`) que ejecuta `pruebas-dobles/ensayo_completo.sh` contra el GitHub simulado.

```bash
bash pruebas-dobles/ensayo_completo.sh            # usa /tmp/sim-ci
bash pruebas-dobles/ensayo_completo.sh /tmp/otra  # otra carpeta de simulación
```

Monta el laboratorio simulado y repasa: ensayos de aceptación del tablero, multiproyecto (migrar, proyecto nuevo,
colores), CI como juez (rojo, conflictos, commits ajenos), revisión entre agentes, fallos del junior, vista
«Tablero», siguiente paso, dependencias «Blocked by», panel (API, Nueva tarea, TABLERO_TOKEN, progreso en
directo), palabras de normativa, **enlaces de la documentación** (`README.md` y `docs/*.md`: archivos y anclas
que existen, título y enlace al índice en cada página) y compilación. Termina con `RESULTADO: todo en verde` o
con el número de fallos.

## Pruebas dobles: probar el coordinador sin red

`pruebas-dobles/` contiene `gh`, agentes y Ollama falsos (`fake_gh.py`, `fake_agente.py`, `fake_ollama.py`) y
`montar_simulacion.sh`, que monta el laboratorio simulado. Para probar a mano, apunta `gh_bin`, `agentes.*.bin` y
`ollama_url` a ellos con un remoto `git init --bare` y `preparar-repo --remoto <ruta>`.

## Ensayo completo del piloto (fase 4)

Sobre el [repositorio de ensayo](instalacion.md#repositorio-de-ensayo-fase-3):

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

## Ensayos de aceptación

```powershell
python ensayo_tablero.py todos      # o: prioridad · bloqueo · reinicio · aviso-duplicado · aviso-critico · remoto · pro
```

Resultados (verificado / simulado / pendiente) en `estado/ensayo-tablero.json`. Contra GitHub real,
`pro` integra dos PR de ensayo en `main` (pide confirmación).
