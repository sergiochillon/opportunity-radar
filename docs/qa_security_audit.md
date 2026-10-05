# Reporte de Auditoría Técnica de Calidad (QA) y Seguridad
**Proyecto:** Opportunity Radar  
**Ruta auditada:** `opportunity-radar/`  
**Fecha de auditoría:** 5 de Octubre de 2026  
**Auditor:** Agente Especializado de Calidad y Seguridad (`qa-reviewer`)  
**Estado general:** **APROBADO CON CORRECCIONES APLICADAS**

---

## 1. Resumen Ejecutivo

Se ha llevado a cabo una auditoría exhaustiva e independiente de Calidad de Software (QA) y Seguridad (AppSec) sobre el repositorio **Opportunity Radar**. La auditoría cubrió cinco pilares críticos:
1. **Seguridad e Higiene de Secretos:** Ausencia de credenciales hardcodeadas, ofuscación en logs/trazas y saneamiento de variables de entorno.
2. **Entrada de Datos e Inyecciones:** Resiliencia contra HTML/Markdown injections en Telegram, prevención de path traversal, ausencia de vectores de ejecución de comandos (`shell injection`) y manejo de caracteres nulos (`\x00`).
3. **Contenerización y Permisos Docker:** Configuración no-root, congruencia de UID/GID en montajes bind de `./data` y `./logs`, y robustez del HEALTHCHECK.
4. **Resiliencia de Pipeline y Edge Cases:** Manejo de datos nulos, vacíos, malformados, presupuestos atípicos/negativos y aislamiento de fallos individuales.
5. **Concurrencia en Base de Datos SQLite:** Comportamiento bajo bloqueo transaccional, modo WAL, prevención de deadlocks y gestión de rollbacks limpios.

Durante la auditoría se identificaron **4 vulnerabilidades de severidad media/alta** y **3 defectos de resiliencia y concurrencia**, los cuales fueron **corregidos directamente en el código fuente** y verificados mediante una suite de 12 nuevos tests automatizados específicos.

---

## 2. Tests Ejecutados y Resultado Cuantitativo

### Comando de ejecución
```bash
pytest tests/ -v
```

### Métricas de Ejecución
- **Tests preexistentes:** 33 tests (100% passing)
- **Nuevos tests incorporados (`tests/test_qa_security_edge_cases.py`):** 12 tests (100% passing)
- **Total tests ejecutados:** **45 tests**
- **Resultado final:** **45 passed en 10.84 segundos (0 fallos, 0 errores, 0 regresiones)**

### Detalle de Suites Ejecutadas
| Suite | Casos | Estado | Cobertura Funcional |
|---|:---:|:---:|---|
| `test_deduplication.py` | 2 | PASS | Deduplicación por `source_id` y hash de contenido SHA-256 |
| `test_hard_filters.py` | 9 | PASS | Filtros deterministicos de no-calls, tech-stack, seniority y scams |
| `test_llm_intelligence.py` | 4 | PASS | Validación de esquema Gemini y heurística de fallback |
| `test_normalization.py` | 7 | PASS | Normalización de campos, parseo de rangos y tarifas horarias |
| `test_pipeline_e2e.py` | 1 | PASS | Flujo completo E2E desde collector hasta scoring |
| `test_reddit_collector.py` | 2 | PASS | Mapeo de publicaciones de Reddit y manejo de credenciales ausentes |
| `test_scoring.py` | 3 | PASS | Ponderación multivariable, decaimiento temporal y guardarraíles |
| `test_storage.py` | 3 | PASS | Persistencia relacional, análisis y métricas agregadas |
| `test_telegram.py` | 2 | PASS | Escapado HTML y deduplicación de alertas en Telegram |
| `test_qa_security_edge_cases.py` | 12 | PASS | **Auditoría AppSec: ofuscación de secretos, protocolos URL seguros, resiliencia a null bytes, locking en SQLite y tolerancia a fallos** |

---

## 3. Matriz de Hallazgos y Severidad

| ID | Área | Descripción del Hallazgo | Severidad | Estado |
|---|---|---|:---:|:---:|
| **SEC-01** | Seguridad / Logs | Exposición de `TELEGRAM_BOT_TOKEN` en texto plano en errores HTTP / base de datos | **ALTA** | **CORREGIDO** |
| **SEC-02** | Seguridad / Credenciales | Exposición de credenciales (`gemini_api_key`, `reddit_password`, etc.) en `repr(AppSettings)` | **MEDIA** | **CORREGIDO** |
| **SEC-03** | Parsing / Telegram | Protocolos URL no permitidos (`javascript:`, `file:`) podían generar errores 400 en Telegram | **MEDIA** | **CORREGIDO** |
| **SEC-04** | Telegram / DoS | Títulos y viñetas excesivamente largos superaban el límite duro de 4096 caracteres de Telegram | **MEDIA** | **CORREGIDO** |
| **CONC-01** | SQLite Concurrencia | Enmascaramiento de `database is locked` con `cannot rollback - no transaction is active` | **ALTA** | **CORREGIDO** |
| **DOCK-01** | Docker Permisos | Mismatch de permisos de host UID/GID (1001 vs 1000) provocaba `unable to open database file` | **ALTA** | **CORREGIDO** |
| **PIPE-01** | Pipeline Resiliencia | Falta de aislamiento de fallos: un ítem corrupto detenía el procesamiento de todo el lote | **MEDIA** | **CORREGIDO** |
| **NORM-01** | Normalización | Parseo erróneo de presupuestos negativos (`-$500` era parseado como `$500`) y riesgo en `None` inputs | **MEDIA** | **CORREGIDO** |

---

## 4. Detalle Técnico de Problemas y Correcciones Aplicadas

### 4.1. [SEC-01] Fuga de Tokens de Telegram en Logs y Tabla de Notificaciones
- **Problema:** En `notifications/telegram.py`, cuando `httpx` experimentaba una excepción de red o HTTP (por ejemplo `httpx.HTTPStatusError` 404/401 o `ConnectTimeout`), la representación `str(e)` incluía la URL completa de la petición: `https://api.telegram.org/bot<TOKEN>/sendMessage`. Dicho mensaje con el token en claro se registraba en la columna `error_message` de la tabla `notifications` de SQLite y en los ficheros de log mediante `logger.error(...)`.
- **Impacto:** Fuga de credenciales en repositorios de auditoría, logs y respaldos de base de datos (CWE-532 / CWE-312).
- **Corrección:** Se implementó el método `_sanitize_token(self, text: str) -> str` en `TelegramNotifier`, el cual reemplaza el token del bot por `[REDACTED_BOT_TOKEN]` tanto antes de persistir en base de datos como antes de emitir al logger.

### 4.2. [SEC-02] Representación Insegura de `AppSettings`
- **Problema:** Al invocar `repr(settings)` o convertir la configuración a cadena en trazas de depuración, Pydantic volcaba en texto plano todos los secretos configurados (`telegram_bot_token`, `gemini_api_key`, `reddit_client_secret`, `reddit_password`, `github_pat`).
- **Impacto:** Posible filtración en trazas de excepciones no controladas o volcados de logging.
- **Corrección:** Se marcaron todos los campos confidenciales en `AppSettings` con `Field(default=None, repr=False)`.

### 4.3. [SEC-03] y [SEC-04] Seguridad y Bounding en Mensajes de Telegram
- **Problema:** 
  1. Si una oportunidad contenía URLs malformadas o protocolos peligrosos (ej. `javascript:alert(1)` o enlaces relativos), la etiqueta `<a href="...">` generaba un rechazo HTTP 400 por parte de Telegram (`Unsupported URL protocol`).
  2. Si el título o la descripción de una oportunidad contenía miles de caracteres o caracteres nulos (`\x00`), el mensaje excedía los 4096 caracteres permitidos por la API de Telegram, perdiendo la notificación irreversiblemente.
- **Corrección:**
  - Se restringió la generación de enlaces `<a href="...">` exclusivamente a esquemas seguros (`http://`, `https://`, `tg://`). Cualquier otra URL se escapa y muestra como texto plano seguro.
  - Se depuran caracteres nulos (`\x00`) en todos los campos.
  - Se acotó la longitud del título a un máximo de 280 caracteres y cada viñeta/alerta a 150 caracteres, asegurando que el mensaje nunca sobrepase los límites de Telegram.

### 4.4. [CONC-01] Gestión de Concurrencia y Rollbacks en SQLite
- **Problema:** En `storage/database.py`, el context manager `transaction()` contenía:
  ```python
  try:
      conn.execute("BEGIN IMMEDIATE;")
      yield conn
      conn.execute("COMMIT;")
  except Exception:
      conn.execute("ROLLBACK;")
      raise
  ```
  Si `BEGIN IMMEDIATE;` agotaba el `busy_timeout` de 10 segundos debido a un escritor concurrente reteniendo el cerrojo, SQLite levantaba `sqlite3.OperationalError: database is locked`. Al entrar en el bloque `except`, se ejecutaba `conn.execute("ROLLBACK;")`. Dado que la transacción nunca llegó a abrirse, SQLite lanzaba un segundo error fatal: `sqlite3.OperationalError: cannot rollback - no transaction is active`, enmascarando la causa raíz del bloqueo.
- **Corrección:** Se modificó la rutina para verificar `if conn.in_transaction:` antes de intentar el rollback. Adicionalmente, `PRAGMA journal_mode = WAL;` se movió a `init_schema()`, evitando que cada conexión de lectura individual compita innecesariamente por el cerrojo del journal mode.

### 4.5. [DOCK-01] Mismatch de Permisos No-Root en Docker y Bind Mounts
- **Problema:** El `Dockerfile` definía rígidamente un usuario `radaruser` con UID 1000 y GID 1000. En hosts Linux donde el usuario principal tiene un UID/GID diferente (por ejemplo UID 1001, habitual en máquinas cloud de Ubuntu), los directorios montados `./data:/app/data` y `./logs:/app/logs` tenían propiedad 1001:1001 con permisos 775. El usuario del contenedor (UID 1000) no tenía permisos de escritura en `/app/data`, haciendo que el arranque fallara inmediatamente con:
  `sqlite3.OperationalError: unable to open database file`.
- **Corrección:**
  - Se declararon argumentos de construcción `ARG USER_UID=1000` y `ARG USER_GID=1000` en el `Dockerfile`.
  - Se actualizaron las directivas de creación de usuario para adaptarse al UID/GID del host.
  - Se actualizó `docker-compose.yml` para transferir `${USER_UID:-1000}` y `${USER_GID:-1000}`.
  - Se dinamizó el `HEALTHCHECK` del Dockerfile para resolver la ruta de la base de datos a través de `DATABASE_PATH`.

### 4.6. [PIPE-01] Tolerancia a Fallos en el Orquestador
- **Problema:** En `pipeline/orchestrator.py`, el bucle principal `for opp in all_opportunities:` no capturaba excepciones a nivel individual. Si un único ítem presentaba un dato anómalo o causaba un fallo imprevisto, se abortaba todo el ciclo, dejando de procesar todas las demás oportunidades pendientes.
- **Corrección:** Se encapsuló el procesamiento por oportunidad en un bloque `try...except Exception as e`, registrando el error sin interrumpir el pipeline para los ítems restantes.

### 4.7. [NORM-01] Parseo de Presupuestos y Manejo de Entradas Nulas
- **Problema:**
  1. Si un texto contenía un importe precedido de signo negativo (ej. `Budget: -$500`), el lookbehind `(?<![-–])` fallaba en `-5`, pero al iterar el motor de expresiones regulares sobre el siguiente dígito `0`, el lookbehind tenía éxito contra `5`, extrayendo falsamente `$500` o `00 USD`.
  2. Si `normalize_raw_item` recibía `title=None`, `url=None` o `created_at=None`, la aplicación fallaba con `AttributeError`.
- **Corrección:**
  - Se corrigió el lookbehind a `(?<![-–\d])` para bloquear cualquier subcadena numérica precedida de signo menos.
  - Se reforzó `normalize_raw_item` para aceptar valores nulos asignando valores por defecto seguros (`""` para textos, `datetime.now(timezone.utc)` para fechas) y eliminando bytes nulos.

---

## 5. Verificación de Áreas Críticas Requeridas

1. **Secretos y Tokens Hardcodeados:**
   - Auditoría estática mediante expresiones regulares sobre todo el árbol de directorios: **0 secretos encontrados**.
   - `.gitignore` cubre `.env`, `*.env`, `*.pem`, `*.key`, `credentials.json`, `*.db`, `data/`, `logs/`.
   - `.env.example` contiene plantillas vacías sin valores reales.

2. **Parsing de HTML/Markdown e Inyección:**
   - Telegram HTML Escaping: Validado y verificado.
   - Shell Injection: **0 llamadas a `subprocess`, `os.system`, `os.popen`, `exec` o `eval`** en todo el proyecto.
   - Path Traversal: Las rutas de base de datos se leen exclusivamente de variables de entorno configuradas por el administrador del sistema.

3. **Docker y Permisos de Almacenamiento:**
   - Configuración no-root verificada con `id` (`uid=1000(radaruser)` o UID configurable).
   - `security_opt: - no-new-privileges:true` presente en `docker-compose.yml`.
   - Ejecución verificada en contenedor con bind mounts de `./data` y `./logs`.
   - `HEALTHCHECK` verificado en tiempo de ejecución (`status: healthy`).

4. **Concurrencia en SQLite:**
   - 20 transacciones concurrentes en hilos independientes: **0 errores**.
   - 10 procesos simultáneos de lectura y escritura: **0 errores**.
   - Timeouts de bloqueo limpios sin excepciones residuales de rollback.

---

## 6. Problemas Pendientes / Recomendaciones para Producción

1. **Rotación de Tokens en Despliegue:**
   - Recordar que en entornos de producción los tokens de `.env` deben gestionarse con permisos restringidos de sistema de archivos (`chmod 600 .env`).
2. **Volúmenes de Producción:**
   - En despliegues distribuidos multi-nodo, se recomienda montar el volumen de datos sobre almacenamiento local persistente con baja latencia para optimizar el rendimiento del modo WAL de SQLite.
3. **Monitoreo de Cuotas de APIs:**
   - Se recomienda supervisar periódicamente los logs de cuota de Gemini y los encabezados `X-Ratelimit-Remaining` de Reddit para ajustar el intervalo del scheduler si aumentan los volúmenes de escaneo.

---
**Conclusión de la Auditoría:**
El software cumple rigurosamente con los estándares de calidad técnica, seguridad defensiva, manejo seguro de concurrencia y tolerancia a fallos. Todos los defectos identificados fueron subsanados satisfactoriamente.
