# Notas de testing (para agentes futuros)

## Suites backend (pytest, `cd /app/backend && REACT_APP_BACKEND_URL=<preview> python3 -m pytest tests/<file> -n 0`)
- `pytest.ini` fija `-n 2 --dist loadscope`. Casi todos los archivos mutan estado compartido (settings, config, cuenta paper):
  **ejecutar un archivo a la vez o con `-n 0`**. Correr `test_iter4` y `test_iter20` juntos con `-n 2` produce falsos fallos
  (iter20 pone `ai_source=gemini` mientras iter4 comprueba defaults).
- Tests DESTRUCTIVOS de la cuenta paper cripto (hacen `POST /api/account/reset`): `test_trading_bot.py`, `test_plan_performance.py`,
  `test_iter15` (FX). En preview no importa; en el VPS NUNCA ejecutarlos.
- Tests que requieren mocks locales: `test_iter5_live_mode.py` (bybit_mock 8011), `test_iter18_fx_live.py` (metaapi_mock 8012).
- `test_iter12 test_preview_fields_and_coherence` depende de datos sembrados (no es regresión).

## Iteración 20 (2026-10-21)
- `test_iter4_auth_config.py` actualizado: 424 (antes 502), alerta `news`, 3 crons, fixture de login por módulo, Gemini en vez de ai_api_key.
- Tests antiguos (`test_trading_bot`, `test_plan_performance`, `test_optimizer_checkin_ai`) ahora autentican (sesión con Bearer) y
  asumen cuenta de $500 y 5 estrategias.
- Nuevo `test_iter20_ai_source_routers.py`: fuente IA (Emergent vs Gemini propia), errores amigables, override sin guardar, routers movidos.

## Iteración 21
- `tests/test_iter21_hfm_alert_cron_ai.py` (-n 0): usa el mock MetaApi (:8012) y `POST /mock/connection`, pasa el bot FX a REAL con `hfm_alert_after_sec=15` y lo devuelve a paper; el último test reinicia el backend con supervisorctl (ejecutarlo al final, no en paralelo con otras suites).
- `test_iter18` puede fallar esporádicamente en test_08 si el escaneo real del bot abre una posición en GBPUSD/USDJPY mientras el bot está activo en REAL (carrera con el mercado, no regresión); repetir la suite.

## Iteración 25
- `tests/test_trading_bot.py` (suite heredada) DETIENE el bot cripto, reinicia estadísticas y deja el perfil Conservador: no ejecutarla sobre la cuenta del usuario sin restaurar después (bot/start).
- `tests/test_iter25_evolution_backup.py` limpia al final los eventos de evolución que crea (`changes`, `fx_changes`).

## Iteración 49
- El puerto 8011 (mock de Bybit) lo ocupa nginx en este pod: arrancar el mock con `BYBIT_MOCK_PORT=8013` (`tests/test_iter49_backlog.py` lo hace solo). `test_iter5_live_mode.py` y `test_iter28_cashflows.py` siguen apuntando a 8011 → fallan en el pod hasta migrarlos.
- `tests/test_iter49_backlog.py -n 0` pasa el bot cripto a REAL contra el mock con `reset_stats: true` y vuelve a paper (también con reset): solo sobre una cuenta paper desechable (hoy 0 operaciones).
- `tests/test_iter21_hfm_alert_cron_ai.py -k TestHfmDisconnectAlert` es la regresión del refactor `broker_health.transition` en el motor FX.
