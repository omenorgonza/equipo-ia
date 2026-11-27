# Mantenimiento, despliegue y PRO

[← Índice de la documentación](README.md)

## Workflows de GitHub Actions

Se instalan en cada proyecto desde `repo-plantilla/.github/workflows/` (con `ensayo_tablero.py instalar-github`,
`equipo.py nuevo` o `equipo.py importar`) junto con los scripts de `repo-plantilla/.equipo-ia/`. Funcionan con
el PC apagado y usan el secreto `TABLERO_TOKEN` (ver [Instalación](instalacion.md#token-y-secretos-tablero-y-actions)).

| Workflow | Qué hace |
|---|---|
| `pruebas.yml` | CI de la plantilla (check `pruebas`) en cada PR y en `main`. |
| `tablero-issue.yml` | Mete en el tablero las issues abiertas sin pasar por él (ver [Tablero](tablero.md#etiquetas-estado-y-prioridad)). |
| `tablero-pr.yml` | PR integrada en la rama objetivo con pruebas verdes → tarjeta en Done. |
| `despliegue.yml` | Despliegue (manual; hoy **simulado**) y paso a PRO de lo que contiene. |
| `mantenimiento.yml` | Revisión proactiva semanal y manual (abajo); también reconcilia PRO. |
| `aviso-critico.yml` | Ensayo del aviso inmediato de seguridad. |

El repo del propio equipo tiene además `ci-equipo.yml` (job `ensayos`), que ejecuta el
[ensayo completo](ci-y-pruebas.md#el-ensayo-completo-del-equipo-check-ensayos).

## Mantenimiento proactivo (con el PC apagado)

`mantenimiento.yml`: semanal (lunes 06:17 UTC, línea `cron`) y manual. Fuentes en `.equipo-ia/mantenimiento.json`:

- **Versiones**: archivos de bloqueo + endoflife.date.
- **Seguridad**: alertas Dependabot.
- **Normativa**: API del sumario del BOE con palabras clave; AEPD/EUR-Lex listas para activar.
- **Deuda técnica**: tests inestables, PR de Dependabot bloqueadas.

Una clave estable por hallazgo → una issue `mantenimiento` y una tarjeta en Planning; sin cambios no escribe;
con evidencia nueva actualiza solo el bloque automático y comenta una vez. Si una fuente falla, sigue con las
demás y marca la revisión como PARCIAL. Registro consultable: issue «Registro de mantenimiento» (última
ejecución y última correcta con enlace) + resumen del run.

### Palabras de normativa propias de cada proyecto (BOE)

Sin tocar el código: la variable del repo `NORMATIVA_PALABRAS` (separadas por comas) se suma a las `palabras`
de `mantenimiento.json`, sin duplicados (no distingue mayúsculas ni tildes) e ignorando espacios sobrantes. Sin
la variable se usan solo las del JSON.

```bash
gh variable set NORMATIVA_PALABRAS -R <repo> --body "servicios de pago, IRPF, entidades de crédito"   # p. ej. family-finance
gh variable list -R <repo>                                  # comprobar
gh variable delete NORMATIVA_PALABRAS -R <repo>             # volver a solo las del JSON
```

### Seguridad: aviso inmediato

Aviso inmediato = notificación nativa de Dependabot (activa en https://github.com/settings/notifications →
Dependabot alerts). `aviso-critico.yml` verifica destinatario/configuración y envía un aviso **[SIMULADO]**. El
panel muestra los avisos críticos/altos en «Requiere tu atención».

## Despliegue y PRO

- PRO = funcionando en producción. Lo ponen solo `despliegue.yml` / `mantenimiento.yml` cuando el último
  despliegue **correcto** contiene el commit.
- `despliegue.yml` solo se dispara a mano (o, en el futuro, desde el proceso real de publicación); mover una
  tarjeta del tablero **nunca** lo dispara. En los proyectos sin servidor todavía, el despliegue es simulado
  (entrada `resultado`: success/failure).
- Arrastrar una tarjeta a PRO no despliega nada; la siguiente reconciliación la devuelve a Done (si su PR está
  integrada) o a Testing / Review (si no), con una nota. Una reversión (despliegue correcto de un SHA anterior)
  también devuelve a Done las afectadas.
- En `equipo-ia` no hay despliegue: **Done es el final**.
