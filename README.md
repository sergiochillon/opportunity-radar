# 🎯 Opportunity Radar

> Monitor automatizado, personal e inteligente de micro-oportunidades freelance y tareas técnicas para desarrolladores backend / Python.

---

## 📖 Visión General
**Opportunity Radar** es una herramienta de uso estrictamente **personal** diseñada para ejecutarse 24/7 en un VPS a coste 0 €.
Escanea periódicamente fuentes públicas de trabajo técnico (Reddit `r/forhire`, `r/slavelabour`, `r/freelance_forhire`, `r/pythonjobs`, extensible a GitHub Bounties y Freelancer), filtra inmediatamente el 80% de ruido mediante reglas deterministas de coste cero, analiza con Google Gemini las oportunidades candidatas, calcula un scoring multivariable ponderado y te envía por **Telegram** únicamente los encargos que encajan con tu perfil (Python, APIs, scripting, web scraping legítimo, CSV/Excel, automatizaciones, 100% remoto y asíncrono, sin llamadas ni reuniones).

---

## 🏗 Arquitectura del Pipeline

```
[ Reddit API (OAuth2) ]
          │
          ▼
   [ Normalización ] ──> Limpieza, parsing de presupuesto ($/hr -> flat, EUR/USD), UTC dates
          │
          ▼
   [ Deduplicación ] ──> ID, URL canónica, hash de contenido (cross-posts), ventana autor <6h
          │
          ▼
   [ Hard Filters ]  ──> Veto a [For Hire]/[OFFER], unpaid, zoom obligatorio, senior 8+, frontend puro
          │
          ▼
   [ Intelligence ]  ──> Gemini 2.5 Flash con Structured Output (fallback heurístico si no hay cuota)
          │
          ▼
   [ Scoring Engine] ──> Tech (25%), Scope (20%), Budget (15%), Async (15%), Exp (10%), Freshness (10%), Comp (5%)
          │
          ▼
   [ SQLite Storage] ──> WAL mode, concurrencia segura, transacciones atómicas
          │
          ▼
   [ Telegram Bot  ] ──> Solo candidatos HOT (>=80 pts) o GOOD (65-79 pts) con enlace directo
```

---

## 🚀 Puesta en Marcha Rápida (5 minutos)

### 1. Clonar y configurar credenciales
```bash
cp .env.example .env
nano .env
```

Completa las siguientes variables en `.env`:

1. **Telegram**:
   - `TELEGRAM_BOT_TOKEN`: Crea un bot en [@BotFather](https://t.me/BotFather) y copia el token.
   - `TELEGRAM_CHAT_ID`: Habla con [@userinfobot](https://t.me/userinfobot) para obtener tu ID numérico.
2. **Google Gemini (LLM)**:
   - `GEMINI_API_KEY`: Clave gratuita en [Google AI Studio](https://aistudio.google.com/).
3. **Reddit (OAuth2 Script App)**:
   - Ve a [https://www.reddit.com/prefs/apps](https://www.reddit.com/prefs/apps).
   - Haz clic en **"create another app..."** al final de la página.
   - Selecciona el tipo **"script"**.
   - Nombre: `OpportunityRadar`.
   - Redirect URI: `http://localhost:8080`.
   - Copia el Client ID (debajo del nombre de la app) y el Secret.
   - Completa en `.env`: `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USERNAME`, `REDDIT_PASSWORD`.

---

### 2. Probar conectividad con Telegram
```bash
python3 scripts/test_notification.py
```
Recibirás un mensaje de prueba con formato HTML en tu chat de Telegram.

---

### 3. Ejecutar un ciclo de prueba manual
```bash
python3 scripts/run_radar.py --once
```

---

### 4. Consultar métricas y resumen
```bash
python3 scripts/summary.py
```

Salida típica:
```text
=======================================================
           OPPORTUNITY RADAR: METRICS SUMMARY          
=======================================================
 Database Path         : data/radar.db
 Last Found Opportunity: 2026-10-05T08:50:00+00:00
-------------------------------------------------------
 Total Opportunities   : 142
 Passed Hard Filters   : 28
 Rejected Hard Filters : 114
-------------------------------------------------------
 OPPORTUNITY TIERS:
   🔥 HOT  (>= 80 pts) : 4
   ⚡ GOOD (65-79 pts) : 7
   📉 LOW  (50-64 pts) : 12
   ❌ IGNORE (< 50 pts): 5
-------------------------------------------------------
 NOTIFICATIONS:
   ✓ Sent Successfully : 11
   ✗ Failed Attempts   : 0
=======================================================
```

---

## ⚙️ Configuración del Perfil (`config/profile.yaml`)

Puedes modificar tus preferencias, habilidades y restricciones sin tocar una sola línea de código:

```yaml
skills:
  - Python
  - SQL
  - FastAPI
  - Docker
  - Linux
  - web scraping
  - automation
  - CSV
  - Excel

preferred_tasks:
  - bug fixing
  - small scripts
  - API integrations
  - automation
  - scraping

avoid:
  - frontend
  - React
  - Next.js
  - Vue
  - mobile
  - calls
  - meetings
  - unpaid

constraints:
  remote_only: true
  async_only: true
  no_calls: true
  no_unpaid: true

budget:
  minimum: 10.0
  preferred_minimum: 20.0
  preferred_maximum: 300.0
```

---

## 🐳 Ejecución en Producción 24/7

### Opción A: Docker Compose (Recomendada)
```bash
docker compose up -d --build
```
Ver logs en vivo:
```bash
docker compose logs -f
```

### Opción B: Servicio Nativo de Systemd
Crea `/etc/systemd/system/opportunity-radar.service`:
```ini
[Unit]
Description=Opportunity Radar 24/7 Daemon
After=network.target

[Service]
Type=simple
User=YOUR_USER
WorkingDirectory=/path/to/opportunity-radar
ExecStart=/path/to/opportunity-radar/.venv/bin/python3 scripts/run_radar.py --daemon
Restart=always
RestartSec=30
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```
Activar y arrancar:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now opportunity-radar
sudo systemctl status opportunity-radar
```

---

## 🧪 Tests Automatizados
La suite completa cuenta con 45 tests unitarios, integrados y de seguridad AppSec (sin dependencias externas ni llamadas a red en tests):

```bash
pytest tests/ -v
```

---

## 🔒 Seguridad y Privacidad
- **Cero fugas de credenciales**: `.env`, bases de datos SQLite y logs están estrictamente ignorados en `.gitignore`.
- **Ejecución no-root**: El contenedor de Docker corre bajo el usuario no privilegiado `radaruser`.
- **Aislamiento**: El sistema nunca ejecuta código arbitrario proveniente del texto de las ofertas.
- **Sanitización HTML**: Los textos se escapan antes de enviarse a Telegram para evitar inyecciones.
