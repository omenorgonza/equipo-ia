# Instalación

[← Índice de la documentación](README.md)

El equipo se instala una vez y sirve para todos los proyectos. La carpeta de trabajo es
`Documents\30 Proyectos\equipo-ia-lab` (fuera de AcademIA); desde WSL,
`/mnt/c/Users/neo_s/Documents/30 Proyectos/equipo-ia-lab`. Los comandos de la v4 (`python3 equipo.py …`) se
lanzan en WSL. Los de la puesta en marcha original (v3) se escribieron para PowerShell en Windows nativo
(`python coordinador.py …`: se descomprimía el equipo en esa carpeta y se abría PowerShell ahí); en WSL son
los mismos con `python3`.

## En WSL

- Python 3.9+ (solo biblioteca estándar), `git` y `gh` con tu sesión iniciada.
- Clona el repo del equipo (`omenorgonza/equipo-ia`) en la carpeta de trabajo; `.gitignore` deja fuera tu
  configuración, los tokens y las carpetas de cada proyecto (`proyectos/`).
- El panel (`python3 equipo.py panel`) se abre en tu navegador de Windows: ver [Panel](panel.md).
- Para actualizar tras integrar una mejora del equipo: [Guía de uso](guia-uso.md#actualizar-tu-instalación).

## Configuración inicial y diagnóstico

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

## Agentes: configurar y aceptar los desarrolladores (fase 2)

```powershell
python coordinador.py configurar-local                       # elige un modelo instalado con "tools" (prefiere *coder*)
python coordinador.py configurar-local --modelo qwen2.5-coder:14b   # o fíjalo tú
python coordinador.py probar local     # OpenCode crea prueba-local.txt = LISTO; muestra api/ps de Ollama
python coordinador.py probar claude    # claude -p crea prueba-claude.txt = LISTO
```

Ambos deben terminar en `RESULTADO: ACEPTADO`. Si OpenCode es de la generación V1 (la config usa
`permission`/`bash` en lugar de `permissions`/`shell`), sustituye `opencode.json` por
`plantillas/opencode.v1.template.json` con el mismo `model`. Si tu versión no tiene `--auto`, quítalo
de `config.json → agentes.local.args_extra`. `opencode.json` (modelo y permisos de OpenCode) se hereda en
`worktrees/` y `estado/pruebas/`.

Quién es quién (TL, senior, junior) está en [Agentes y lecciones](agentes-y-lecciones.md).

## Ollama

- El agente local es OpenCode + Ollama. `configurar-local` fija el modelo en `opencode.json` y `config.json`.
- Ollama arranca los modelos con 4096 tokens de contexto: usa una variante con `num_ctx 32768`
  (`diagnostico` y `configurar-local` avisan y dan los comandos de PowerShell). Ver
  [Limitaciones](limitaciones.md#problemas-resueltos).
- Sin relevo: si Ollama no responde, la tarea local se bloquea; nunca pasa a otro proveedor.

## Token y secretos (tablero y Actions)

Puesta en marcha del tablero y de los workflows, una vez y en este orden:

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

- `TABLERO_TOKEN` es un token clásico con los scopes `repo` y `project`. Lo puedes guardar también desde el
  panel (botón «Guardar TABLERO_TOKEN»), que lo comprueba y lo sube a todos los repos del proyecto: ver
  [Panel](panel.md#guardar-tablero_token).
- Las vistas y la agrupación por Estado se explican en [Tablero](tablero.md#vistas-y-agrupación-por-estado).
- Los proyectos nuevos (`equipo.py nuevo`) o importados (`equipo.py importar`, «Añadir proyecto existente»)
  traen el tablero, los workflows y la configuración ya instalados.

## Repositorio de ensayo (fase 3)

Nombre propuesto: **`<tu-usuario>/equipo-ia-lab-ensayo`, privado**. Confírmalo y ejecuta:

```powershell
python ensayo.py preparar-repo --crear                 # o --nombre otro --owner org
```

Crea el repo privado si no existe, sube el commit inicial (contrato, `.github/ISSUE_TEMPLATE/tarea-agente.yml`),
crea las etiquetas `agent:claude agent:local ready running review blocked` y escribe `repo` y
`autor_autorizado` (tu cuenta de `gh`) en `config.json`. El ensayo completo de la fase 4 está en
[CI y pruebas](ci-y-pruebas.md#ensayo-completo-del-piloto-fase-4).

## Migrar desde la v3 (una vez)

```bash
python3 equipo.py migrar          # mueve config, estado, worktrees y clon a proyectos/ensayo
python3 equipo.py ensayo estado   # comprobar
```

## Pasar a AcademIA (después de su v1)

Copia la carpeta, cambia en `config.json` solo `repo`, `clon_local` y `pruebas` (los comandos de Symfony,
React y E2E que verifiques en el proyecto, p. ej. `["php","bin/phpunit"]`, `["npm","test","--","--run"]`),
y ajusta `opencode.json`/`agentes.claude.args` si esas tareas necesitan permisos adicionales. En la v4 lo
normal es darlo de alta como proyecto (`equipo.py importar` o «Añadir proyecto existente» en el panel).
