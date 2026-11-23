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

### Qué hace el panel

- **Requiere tu atención**: PR por revisar, tarjetas bloqueadas (con «Reintentar con el agente»), avisos de
  seguridad críticos/altos y CI en rojo en la rama principal, de todos los proyectos a la vez.
- **Puesta a punto pendiente** (plegable): vistas del tablero, secreto TABLERO_TOKEN, PR de instalación.
- **Una tarjeta por proyecto**: estado del README, resumen, contadores por columna, repos con su CI, tareas en
  curso, enlaces al tablero y botones Arrancar/Parar/Ver log.
- **Nuevo proyecto**: crea uno o varios repos privados con andamiaje (vacío o Python), el tablero, los
  workflows y la configuración. **Añadir proyecto existente**: no toca tu código; detecta la CI y abre una PR
  con la instalación.

Solo escucha en 127.0.0.1 y las acciones exigen un token que cambia en cada arranque.

### Tablero estándar en cada proyecto

Los tableros nuevos se **copian del tablero de ensayo** (vistas «Tablero» y «Planning», campos Estado,
Prioridad y Bloqueo, y workflows desactivados). Para otra plantilla: `plantilla_tablero` en `equipo.json`.
Un tablero creado sin plantilla y aún vacío se sustituye con `python3 equipo.py <proyecto> tablero rehacer`
(el antiguo no se borra; elimínalo tú en Settings → Delete project).

### La CI del proyecto como juez (`--prueba ci`)

En proyectos con CI propia (family-finance: job `tests`), el coordinador no ejecuta pruebas en tu PC:
sube la rama, abre la PR como **borrador** y espera a la CI. Verde → PR lista y tarjeta en Testing / Review.
Rojo → Bloqueo con el log; «Reintentar con el agente» le pasa el extracto del log del fallo.

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
| Repetir un paso | `python coordinador.py reanudar 7 --desde agente` (`worktree`, `agente`, `verificada`, `commit`, `push`, `pr`) |

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
gh secret set TABLERO_TOKEN --repo <owner/repo>  # token clásico con scopes repo + project (para Actions)
python tablero.py verificar                      # campos, vistas, privacidad y permisos con tu identidad
gh workflow run mantenimiento.yml --repo <owner/repo>   # verifica el acceso del workflow (ver resumen del run)
```

### Quién mueve cada tarjeta (un único sitio por transición)

| Estado | Lo mueve | Cuándo |
|---|---|---|
| Backlog | Óscar | captura una idea (`python3 tablero.py nueva "título"` o desde la web) |
| Planning | TL o `mantenimiento.yml` | propuesta con evidencia |
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

### Mantenimiento proactivo (GitHub Actions, con el PC apagado)

`mantenimiento.yml`: semanal (lunes 06:17 UTC, línea `cron`) y manual. Fuentes en `.equipo-ia/mantenimiento.json`:
versiones (archivos de bloqueo + endoflife.date), seguridad (alertas Dependabot), normativa (API del sumario
del BOE con palabras clave; AEPD/EUR-Lex listas para activar) y deuda técnica (tests inestables, PR de
Dependabot bloqueadas). Una clave estable por hallazgo → una issue `mantenimiento` y una tarjeta en
Planning; sin cambios no escribe; con evidencia nueva actualiza solo el bloque automático y comenta una vez.
Si una fuente falla, sigue con las demás y marca la revisión como PARCIAL. Registro consultable: issue
«Registro de mantenimiento» (última ejecución y última correcta con enlace) + resumen del run.

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
