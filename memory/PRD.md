# PRD · Bybit AI Trader (Paper Trading 24/7)

## Original problem statement
"Hola! me gustaría construir un script para que analice en tiempo real el mercado de criptomonedas, haga entradas siguiendo un plan de trading y haga el trading en automático las 24 horas, la plataforma a conectar de preferencia seria bybit, el resto de sugerencias y mejoras a tu criterio, analizando casos de éxito anteriores"

## User choices
- Paper trading with real live data (no API keys)
- USDT perpetual futures (long/short)
- AI confirmation: Claude Sonnet (claude-sonnet-5-5 via Emergent LLM key)
- Conservative risk: 1% per trade, max 3 positions, 3x, daily loss limit 5%
- Strategy: default multi-strategy

## Architecture
- Backend FastAPI (/app/backend): market.py (Bybit v5 → auto-fallback to Bitget USDT-FUTURES when geo-blocked), indicators.py (EMA/RSI/MACD/ATR/BB/ADX/Donchian), strategies.py (trend_ema, mean_reversion, breakout_turtle), risk.py (sizing, SL/TP, breakeven+trailing), ai_advisor.py (Claude), engine.py (24/7 asyncio loops: monitor 5s, scan every N sec, auto-resume on restart), backtest.py, server.py (routes).
- MongoDB collections: settings, account, positions, trades, signals, logs, equity, config (clave, IA, Telegram, revisión automática).
- Frontend React dashboard (Spanish): header controls, KPIs, watchlist, lightweight-charts candles+EMA+RSI+markers, plan panel, positions/history/backtest tabs, AI signals log, settings, terminal log.
- QA helper: /app/scripts/inject_signal.py SYMBOL side [noai]

## Implemented (2026-06)
- Live market analysis, 3 strategies + multi-mode, HTF filter, AI approval with min confidence, paper execution with fees 0.055% + slippage, SL/TP/breakeven/trailing, daily loss pause, max positions, drawdown tracking, equity curve, backtest on 1000 real candles, reset account, logs.
- Tested: iteration_1 backend 100%, frontend 95% → minor UI fixes applied (mobile header wrap, Spanish validation, KPI grid, blocked signals stored as BLOQUEADA, risk recheck inside lock).

## Implemented (2026-06, iteration 2 · "plan de crecimiento")
- Paper account initial balance set to $500 (engine.INITIAL_BALANCE); POST /api/account/reset accepts optional {initial_balance}.
- Bybit lot-size enforcement (risk.LOT_SIZES, qty step floor, MIN_NOTIONAL 5 USDT) in live sizing and backtest; backtest now uses account initial balance + symbol, returns expectancy_r / rejected_lot / strategy_stats.
- GET /api/performance: live trade stats by strategy/symbol/side/reason + AI decision counts → "Rendimiento" tab.
- POST /api/plan (plan.py): compound growth plan with phases (semilla → crecimiento → consolidación → ingreso, risk 1% → 1.5%, 100% reinvest until target capital, then withdraw 80%), 4 scenarios (2.5% / 4% / 6% / backtest-derived Monte Carlo median), months to reach target monthly income, Monte Carlo (3000 sims × 12 months) on backtest R-multiples with concurrency factor, per-symbol & per-strategy backtest breakdown → "Plan de crecimiento" tab (GrowthPlan + plan/*.jsx).
- Result for $500 → $1.000/mes with 0 deposits: conservador 12a2m, base 7a, optimista 4a4m, backtest(2.3%/mes) 13a4m. Monthly deposits shorten it drastically.
- Tested: iteration_2 backend 15/15 (one numpy int64 serialization bug fixed by tester), frontend all flows pass.

## Implemented (2026-06, iteration 3 · optimizador + chequeo del plan + IA)
- optimizer.py: 54-combo grid (SL 1–3×ATR, TP 2–6×ATR with R:R≥1.5, ATR 10/14/20) per pair, robust pick = Van Tharp SQN averaged over 3×3 grid neighbours; backtest.py refactored into scan_signals()+simulate() (signals independent of SL/TP → fast); strategies accept params {sl_atr,tp_atr}; build_df(atr_period). Settings.symbol_params[symbol] applied by the live engine, plan backtests and /backtest. UI tab "Optimizador" (compare baseline vs optimum, heatmap, apply/remove, multi-pair summary).
- Plan check-in (plan.build_checkin + engine.checkin): phase criteria evaluated on real paper stats (validación: ≥60 ops, PF≥1.3, DD≤10%, ≥28 días; semilla: 2× capital, DD<12%; crecimiento: $5k, PF≥1.3, ≥100 ops; consolidación: capital objetivo; ingreso: ganancia 30d ≥ meta, DD≤15%). Settings persist plan_scenario/plan_target_monthly/plan_monthly_deposit/plan_phase; "Avanzar a fase" button sets plan_phase + phase risk; alert dot on Plan tab; daily PLAN log at UTC rollover; `checkin` included in /dashboard.
- AI buttons (POST /api/ai/advise scope optimizer|plan): Claude receives settings, account, real performance, check-in and optimizer/backtest results, returns JSON {summary, changes, notes}; backend applies whitelisted changes with caps (risk≤1.5%, lev≤5, max_pos≤5, ≥2 symbols) and returns applied/previous → UI AiAdvice component with "Deshacer".
- Tested: iteration_3 backend 18/18, frontend all flows pass; 2 minor state bugs fixed (heatmap ATR reset per pair, applied state derived from settings).

## Implemented (2026-06, iteration 4 · acceso, ajustes, Telegram, revisión automática)
- Auth: single shared password (no username), bcrypt hash in Mongo `config` doc seeded from INITIAL_PASSWORD env (BlackCat2233@), JWT HS256 (JWT_SECRET env, 7 días) con token_version para invalidar sesiones al cambiar clave; brute force 5 intentos/IP → 15 min (IP = último X-Forwarded-For) + contador global (20). Routers: public (/api/, /api/auth/login), api (protegido), cron (/api/cron/*, Bearer WEBHOOK_CRON_SECRET). Frontend: Login.jsx, token en localStorage, interceptores axios, evento auth:logout.
- Ajustes (vista completa desde el header): Seguridad (cambio de clave), IA (proveedor/modelo/API key propia o clave Emergent, probar conexión), Telegram (token, detectar chat ID vía getUpdates, toggles por tipo de alerta, prueba), Revisión IA automática (activa, diaria/semanal + día, aplicar o solo avisar, ejecutar ahora, última revisión), Cuenta paper (reiniciar con capital personalizado). Backend: config.py (ConfigStore, secretos enmascarados), notify.py (Telegram HTML), review.py (contexto IA compartido, apply_ai_changes, run_auto_review).
- Telegram hooks en engine: apertura/cierre, límite diario, decisiones de Claude, resumen diario + plan (00:00 UTC), resultado/errores de revisión automática.
- Cron `.emergent/crons.yml` ai-review-daily (08:00 UTC) → POST /api/cron/ai-review decide si toca (frecuencia/día, >20h desde la última) y lanza la revisión en background con manejo de errores.
- Prompt del asesor endurecido: cambios estructurales (pares/estrategia/riesgo) solo con ≥30 operaciones reales; backtest/optimizador solo justifican symbol_params.
- Tested: iteration_4 backend 28/29 (fallo del 502 por ingress → ahora 424), frontend completo OK; fixes: XFF spoof, merge de alertas, task de cron con try/except.

## Implemented (2026-06, iteration 5 · modo REAL en Bybit)
- bybit.py: cliente V5 firmado (HMAC-SHA256, recv_window 5000): wallet UNIFIED, instruments-info (lotes/tick, caché 1h), set-leverage (ignora 110043), orden Market con SL/TP adjuntos (tpslMode Full), trading-stop, order realtime/history, position list, closed-pnl. Entornos mainnet/testnet/demo + endpoint personalizado. live.py: LiveBroker (open con espera de llenado, close reduce-only, set_stop, closed_result filtrado por side/qty/tiempo).
- engine: apply_config (listener del ConfigStore) crea el broker; en REAL dimensiona con la equidad real + filtros de lote del instrumento, envía la orden, registra Position{live, order_id}; el monitor sincroniza marca/PnL desde el exchange, empuja el trailing al exchange, detecta cierres en Bybit (periodo de gracia 20s + recomprobación) y registra Trade{live}; cierre manual reduce-only; account_summary usa la wallet de Bybit (exchange_synced/exchange_error).
- Config: bybit_api_key/secret cifrados (Fernet, CREDENTIAL_ENCRYPTION_KEY), bybit_env, bybit_base_url, bybit_verified_at/equity, trading_mode, live_since. Endpoints: POST /api/bybit/test, GET/POST /api/mode (checklist: claves, verificación, bot detenido, sin posiciones; recomendado Fase 0; confirmación "REAL"; reset de estadísticas con la equidad real), POST /api/positions/close-all; guardas en /bot/start (REAL exige credenciales verificadas) y /account/reset (409 con posiciones reales).
- UI: Ajustes → "Bybit · cuenta real" (entorno, key, secret, endpoint avanzado, probar conexión con equidad/disponible/posiciones/desfase, quitar) y "Modo de operación" (badge, checklist, botón "Pasar a modo REAL" con diálogo y texto REAL, "Volver a paper"); header con badge "Modo REAL · Bybit env"; banner si Bybit no responde; botón "Cerrar todas" con confirmación.
- Testing: Bybit está geo-bloqueado en este pod → mock local firmado `scripts/bybit_mock.py` (puerto 8011). iteration_5: backend 20/20, frontend OK; fixes de seguridad posteriores (carrera al abrir, closed-pnl por side/qty, verificación obligatoria para iniciar en REAL, confirmación de cierre total).

## Implemented (2026-06, iteration 6 · kit de despliegue VPS)
- `/app/deploy/`: docker-compose.yml (mongo + backend + web=Caddy sirviendo el build y proxy /api → backend:8001; backend expuesto solo en 127.0.0.1:8001), backend.Dockerfile (python:3.11-slim, pip con extra-index de emergentintegrations, sin herramientas dev), frontend.Dockerfile (node:20-alpine build con REACT_APP_BACKEND_URL="" → API relativa `/api`; luego caddy:2-alpine), Caddyfile (`{$SITE_ADDRESS}`: `:80` por IP o dominio → HTTPS automático), install.sh (Docker, swap si <3.5GB, genera deploy/.env y backend.env con secretos aleatorios + contraseña, build, crontab 08:00 UTC, ufw), cron-ai-review.sh (POST /api/cron/ai-review con Bearer WEBHOOK_CRON_SECRET), update.sh (git pull + rebuild), README.md. `.dockerignore` en la raíz excluye .env/node_modules/.git.
- Verificado localmente: build de producción del frontend genera baseURL "/api" sin URL de preview; `cron-ai-review.sh` → `{"accepted":true}`. Docker no está disponible en el pod, así que compose/Dockerfiles quedan por validar en el VPS.
- Fix tras primer intento en el VPS (Vultr, dominio macdeploy.work): `frontend/yarn.lock` no está en git (la plataforma no lo commitea) → copia en `deploy/frontend.yarn.lock`; frontend.Dockerfile usa `COPY ... deploy/frontend.yarn.loc[k]` + frozen-lockfile con fallback a `yarn install` si falta. install.sh imprime la contraseña generada justo tras crear backend.env. iteration_6: ambas ramas (frozen/fallback) construyen con "/api"; cron 200/401/duplicate OK. Si cambia package.json, re-copiar el lockfile a deploy/.

## Implemented (2026-06, iteration 7 · perfil de riesgo, estrategias nuevas, optimización global IA)
- profiles.py: 5 presets (0 Conservador = config original · 1 Moderado · 2 Activo · 3 Agresivo · 4 Máximo) que fijan symbols (6/8/10/12/12), timeframe (1h→15m desde L3), signal_mode (strict/relaxed/minimal), htf_filter, ai_enabled/ai_min_confidence (60/55/50/40/off), risk_per_trade (1/1.25/1.5/2/3), max_positions (3/4/5/6/8), leverage (3/3/5/5/10), daily_loss_limit (5/6/8/10/15), disabled_strategies (nuevas apagadas en L0-L1). `detect_profile` → nivel activo o null (Personalizado). `ai_policy(level)` → topes IA = max(base 1.5%/5x/5pos, preset) y mínimos de evidencia (30/20 ops en L0-1, 20/15 en L2+).
- strategies.py: MODES con umbrales por modo (RSI, ADX, volumen, MACD/EMA200 opcionales, score mínimo); 2 estrategias nuevas `supertrend_momentum` (giro Supertrend 10/3 + EMA50 + RSI + ADX) y `ema_pullback` (EMA50>EMA200, toque EMA21 y vela de continuación); `evaluate(..., mode, disabled)`; `disabled` solo aplica con strategy="all". indicators.py añade `st`/`st_dir`.
- Settings: `signal_mode`, `disabled_strategies` (≥1 activa), `risk_profile`. Endpoints: GET /api/meta (+signal_modes, mode_info, profiles), POST /api/profile {level} (log + Telegram "review"; 409 si REAL+bot corriendo+nivel≥3), /api/dashboard (+profile_active, optimize_job). backtest/optimizer/plan reciben mode/disabled.
- review.py: `apply_ai_changes` usa topes del perfil, soporta `disabled_strategies` (fuerza strategy="all"); prompt del asesor dinámico (respeta el nivel elegido, no lo vuelve más conservador/agresivo). `run_global_optimization` + job en background: POST /api/ai/optimize-all (409 si en curso) / GET estado {status, step, result{summary, applied, previous, notes, optimizer[por par], ran_at}}; aplica directamente y avisa por Telegram.
- UI: RiskProfileBar.jsx (slider 5 niveles, chips del preset, aviso, AlertDialog en L3-L4, badge Personalizado, reset del formulario al aplicar), SettingsPanel (chips de estrategias on/off, selector de criterios con descripción, intervalo en "seg"), Performance (botón Activo/Apagado por estrategia y por par), Optimizer (tarjeta "Optimizar todo con IA" con polling y AiResult reutilizable), BotPanel (perfil + nº estrategias activas).
- Tested iteration_7: backend 16/16, frontend completo OK; fixes: reset de formulario sucio al aplicar perfil, revertir preview al cancelar diálogo, contraste de etiquetas. Medición: señales 42 días BTC 1h = 38 (strict, 3 estrategias) → 56 relaxed → 76 minimal → 150 minimal con 5 estrategias.

## Implemented (2026-06, iteration 8 · robustez de datos de mercado)
- Bug VPS: `[ERROR] XRPUSDT: 'list'` → market.py accedía a `result.list` sin comprobar retCode (Bybit devolvió error, p.ej. 10006 rate limit). Fix: `_bybit()` (status/retCode, 2 intentos con backoff, error descriptivo), `_bitget()` (code 00000), fallback automático Bybit→Bitget por petición (aviso en log máx. 1/5 min), caché obsoleta si ambos fallan, error claro "sin datos de mercado para…". iteration_8: 12/12 + regresión API OK.

## Implemented (2026-06, iteration 9 · operaciones sombra + agente de noticias)
- shadow.py: cada señal RECHAZADA / BAJA_CONFIANZA (IA), BLOQUEADA (riesgo) o NOTICIAS se simula como "operación sombra" (mismo sizing/SL/TP/trailing, slippage y comisiones; timeout 72h) en db.shadow_positions → db.shadow_trades. `shadow_stats` (total, filter_value = −PnL sombra, ai, by_kind, by_confidence 4 buckets, by_strategy, by_symbol) incluido en GET /api/performance.shadow; `recent_rejections` (10 motivos de Claude) + stats sombra + noticias entran en el contexto de "Optimizar todo con IA" y la revisión automática. reset_account borra shadow_*. UI: bloque "Operaciones sombra · ¿acierta el filtro?" en Rendimiento (performance/ShadowStats.jsx).
- news.py (NewsAgent): RSS CoinDesk/CoinTelegraph/The Block/Decrypt + calendario ForexFactory (USD High/Medium, 72h) → Claude (sesión "news", reintento si JSON inválido) → market{sentiment, risk, summary}, pairs, alerts (ALTA/CRITICA, dedupe por hash → Telegram kind "news" + log NEWS). Loop en proceso cada news_interval_min (def. 20). `gate(symbol)` → bloqueo por evento ALTO en ventana (before 45 / after 30 min) o alerta CRITICA del par/MARKET (24h) → señal registrada como ai_decision NOTICIAS + sombra; factor de tamaño (0.5) si riesgo ALTO (mercado o par) → open_position(risk_factor). `context(symbol)` entra en el prompt de evaluación de señales (_news_lines). Endpoints GET /api/news, POST /api/news/refresh; dashboard.news (summary). Config AppConfig news_* (+ConfigUpdate con límites) y DEFAULT_ALERTS.news. UI: pestaña "Noticias" (NewsPanel.jsx, punto rojo si riesgo ALTO/bloqueo/crítica), Ajustes → "Agente de noticias" (admin/NewsSection.jsx), toggle Telegram news, nivel de log NEWS.
- migrations.py: "2026-10-20-activo" baja el perfil 3→2 una sola vez al arrancar (pedido por el usuario tras ver 0/6 en Agresivo); registrada en db.migrations.
- Tested iteration_9: backend 16/16 (gate, parse_feed, relevant, /news, config, ciclo sombra, inject → sombra RECHAZADA, reset), frontend completo OK.

## Known constraints
- Bybit API blocks the US server region (CloudFront 403) → prices from Bitget perps mirror. Real Bybit order execution requires running from an allowed region.

## Backlog
- P1: Probar el ejecutor REAL contra Bybit testnet/demo desde el VPS de Singapur (aquí solo mock)
- P1: Telegram: configurar token/chat en el VPS y validar alertas end-to-end
- P2: Walk-forward validation of optimizer params (in-sample/out-of-sample), AI backtest sampling
- P2: Funding-rate & news sentiment context for AI
- P2: Backup nocturno de Mongo en el VPS
