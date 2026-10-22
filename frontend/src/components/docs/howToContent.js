// "Cómo usar" step-by-step guides for both bots. `bot` = "crypto" | "fx".
export function buildHowTo(bot) {
  const fx = bot === "fx";
  const cur = fx ? "USD" : "USDT";
  const brokerName = fx ? "HFM (MetaApi)" : "Bybit";
  return [
    {
      id: "inicio", icon: "Compass", title: "1 · Primeros pasos y recorrido por el panel",
      steps: [
        "Entra con la clave del panel (una sola clave compartida, sin usuario). La sesión dura 7 días; con «Cerrar sesión» (icono de salida en la cabecera) la cierras antes.",
        "En la pantalla inicial eliges el bot: Bybit AI Trader (cripto) o HotForex AI Trading (forex). Cada tarjeta muestra en vivo si el bot está activo, su modo (PAPER/REAL), la equidad y el retorno. «Cambiar bot» en la cabecera te devuelve aquí.",
        "Cabecera: badge de modo (Paper trading / Modo REAL), origen de los datos, cuenta atrás del próximo análisis, estado del bot, botones Escanear, Reiniciar (cuenta paper), Iniciar/Detener, Ajustes, Documentación y Cambiar bot.",
        "Fila de KPIs: Balance, Equidad (con retorno total y aportes), PnL no realizado, PnL diario, tasa de acierto, operaciones y drawdown máximo. Pasa el ratón por encima para ver cómo se calcula cada uno.",
        "Columna izquierda: Mercado en vivo (precio, cambio 24 h, RSI, sesgo" + (fx ? " y sesiones abiertas" : " y chip de funding") + "). Centro: gráfico de velas con EMAs, RSI y marcadores de operaciones (haz clic en un par para cambiarlo). Derecha: Plan de trading (perfil, estrategias activas, riesgo, curva de equidad) y Evaluación IA.",
        "Pestañas inferiores: Posiciones, Historial, Backtest, Rendimiento, Optimizador, Noticias" + (fx ? " y agenda" : "") + ", Plan de crecimiento y Evolución. Debajo, el Terminal con el registro completo del bot, coloreado por nivel (ORDER, AI, RISK, NEWS, PLAN, ERROR…) y con botón para limpiarlo.",
      ],
    },
    {
      id: "ciclo", icon: "Play", title: "2 · Iniciar el bot y entender su ciclo",
      steps: [
        "Pulsa «Iniciar bot». Desde ese momento escanea todos los pares cada N segundos (Intervalo de escaneo) y vigila las posiciones cada 5 s. Si reinicias el servidor, el bot recuerda que estaba activo y continúa solo.",
        "«Escanear» fuerza un análisis inmediato sin esperar al temporizador. Útil tras cambiar ajustes.",
        "Ciclo de una señal: estrategia detecta configuración → filtro de temporalidad superior → puertas de riesgo (tope de posiciones, par ya abierto, límite diario, noticias" + (fx ? ", sesión, mercado abierto, conexión con HFM" : ", funding") + ") → IA (confianza mínima) → cálculo de tamaño → orden con SL/TP → trailing.",
        "En «Evaluación IA» verás la última decisión con su razonamiento; en el feed de señales, cada señal con su etiqueta (APROBADA, RECHAZADA, BAJA_CONFIANZA, BLOQUEADA, NOTICIAS" + (fx ? ", SESION, MERCADO, NO_EJECUTADA" : ", FUNDING, NO_EJECUTADA") + ") y la nota del motivo.",
        "Las señales no operadas se simulan en la sombra automáticamente; su resultado aparece en Rendimiento → Operaciones sombra.",
        "«Detener bot» no cierra posiciones: siguen protegidas por su stop y objetivo y el monitor las sigue gestionando. Para salir de todo usa «Cerrar todas» en Posiciones.",
      ],
    },
    {
      id: "estrategia", icon: "SlidersHorizontal", title: "3 · Configurar estrategia, riesgo y perfil",
      steps: [
        "Pestaña «Estrategia y riesgo» (dentro del panel): pares a vigilar, temporalidad (" + (fx ? "5m/15m/1h/4h" : "1m/5m/15m/1h/4h") + "), estrategias encendidas (chips), criterios de entrada (Estrictos/Relajados/Mínimos), filtro de temporalidad superior, filtro de IA y su confianza mínima.",
        `Riesgo: % por operación, posiciones máximas, apalancamiento (${fx ? "1:N" : "Nx"}), límite de pérdida diaria (%) e intervalo de escaneo. Si escribes un valor fuera de rango el panel lo recorta y te avisa.`,
        fx ? "Solo forex: «Riesgo máx. lote mínimo (%)» permite abrir con 0,01 lotes aunque el riesgo real supere tu % si no pasa de ese tope (imprescindible con poco capital en oro/plata); «Cerrar antes del fin de semana»; y «Sesiones para abrir posiciones» (vacío = todas)."
           : "El filtro de funding (Ajustes → Filtro de funding) y el agente de noticias complementan estos ajustes sin tocar la estrategia.",
        "Deslizador «Perfil de riesgo» (0 Conservador → 4 Máximo): aplica un preset completo de pares, temporalidad, criterios, IA, riesgo, posiciones, apalancamiento y límite diario. Si cambias algo a mano el perfil pasa a «Personalizado». Los niveles 3-4 piden confirmación.",
        "Cada cambio guardado queda registrado en Evolución con su antes/después para que puedas medirlo y deshacerlo.",
      ],
    },
    {
      id: "posiciones", icon: "ListOrdered", title: "4 · Posiciones, cierres e historial",
      steps: [
        "Posiciones: par, lado, tamaño, entrada, precio actual, SL/TP vigentes (el stop se mueve solo con breakeven y trailing), PnL y botón «Cerrar» por posición. «Cerrar todas» pide confirmación.",
        "Motivos de cierre: TP (objetivo), SL (stop), TRAILING (stop dinámico), MANUAL, TIEMPO (72 h)" + (fx ? " y FIN_SEMANA (cierre antes del hueco del fin de semana)." : "."),
        "Historial: todas las operaciones cerradas con PnL neto de comisiones, estrategia, motivo, duración y confianza de la IA. Rendimiento las agrega por estrategia, par, lado y motivo.",
        "En modo REAL, si cierras una posición desde la app del bróker el bot lo detecta en segundos, registra el resultado real y lo refleja aquí.",
      ],
    },
    {
      id: "backtest", icon: "FlaskConical", title: "5 · Backtest",
      steps: [
        "Elige par, temporalidad y capital; el backtest usa 1.000 velas reales, tus estrategias y criterios actuales, los parámetros SL/TP aplicados y los mismos costes que el paper.",
        "Lee: retorno, drawdown máximo, acierto, profit factor, expectativa en R, operaciones por estrategia" + (fx ? ", pips netos, cierres de fin de semana, señales descartadas por sesión y por lote mínimo." : " y señales rechazadas por lote mínimo."),
        "Un backtest positivo no garantiza nada: compáralo con el walk-forward del Optimizador antes de aplicar parámetros.",
      ],
    },
    {
      id: "optimizador", icon: "Target", title: "6 · Optimizador, walk-forward y revalidación semanal",
      steps: [
        "«Optimizar» un par (o «Optimizar todos») prueba 54 combinaciones de SL/TP/ATR y propone la más robusta (SQN promediado con sus vecinas). El mapa de calor muestra el paisaje completo; «Aplicar» guarda los parámetros solo para ese par; «Quitar» vuelve a los valores por defecto.",
        "«Validar walk-forward» (o «Validar todos») optimiza por tramos y opera a ciegas fuera de muestra. Veredictos: ROBUSTO (aplicar), DUDOSO (con cautela), SOBREAJUSTADO / NO_RENTABLE (no aplicar o quitar), INSUFICIENTE (pocas operaciones). Si el par ya tiene parámetros aplicados, también valida ESOS parámetros.",
        "La columna «Decisión» del resumen multi-par resume todo en un semáforo: Aplicar · Con cautela · No aplicar · Mantener · Vigilar · Quitar parámetros.",
        "Tarjeta «Revalidación semanal automática»: cada lunes 07:00 UTC revalida los pares con parámetros aplicados; con «Quitar sobreajustados» activo los elimina solos y te avisa. «Revalidar ahora» lo lanza al momento.",
        "«Optimizar todo con IA» encadena optimizador + backtest + walk-forward de todos los pares y deja que la IA aplique solo lo que supera la validación, explicando cada decisión (tarda 1–3 minutos; puedes seguir el progreso).",
      ],
    },
    {
      id: "rendimiento", icon: "BarChart3", title: "7 · Rendimiento y operaciones sombra",
      steps: [
        "Tablas por estrategia, par, lado y motivo de cierre con operaciones, acierto, PnL y profit factor. Desde aquí puedes apagar una estrategia o un par con un botón.",
        "Decisiones de la IA: cuántas señales aprobó, rechazó o bloqueó cada filtro.",
        "«Operaciones sombra · ¿acierta el filtro?»: PnL simulado de lo que no se operó. Valor del filtro positivo = los bloqueos te ahorraron dinero; negativo = te costaron ganancias. Desglose por motivo, confianza de la IA, estrategia, par" + (fx ? " y sesión." : "."),
        "Si el valor de la IA es muy negativo durante semanas, baja la confianza mínima o cambia a criterios más relajados; si es muy positivo, la IA está haciendo bien su trabajo.",
      ],
    },
    {
      id: "noticias", icon: "Newspaper", title: "8 · Noticias" + (fx ? " y agenda económica" : ""),
      steps: [
        "La pestaña muestra el sentimiento y riesgo del mercado, el riesgo por par, los titulares analizados" + (fx ? ", la agenda de eventos de alto/medio impacto con hora local" : ", los eventos macro de la semana") + " y las alertas activas. El punto rojo en la pestaña indica riesgo ALTO, bloqueo o alerta crítica.",
        "«Actualizar ahora» fuerza un nuevo análisis con la IA (los ciclos automáticos solo la llaman si cambiaron los titulares; con el bot detenido el ciclo se relaja a 60 min).",
        "En Ajustes → Agente de noticias configuras el intervalo, las ventanas de bloqueo alrededor de eventos, el factor de tamaño con riesgo ALTO" + (fx ? ", y el trading por noticias (confianza mínima, confirmación de precio, ventana y duración máxima)." : " y si se activa el filtro."),
        "Cada bloqueo por noticias queda en el feed como NOTICIAS con el motivo y se simula en la sombra.",
      ],
    },
    {
      id: "plan", icon: "TrendingUp", title: "9 · Plan de crecimiento",
      steps: [
        "Calculadora: capital inicial (se toma de tu cuenta), meta de ingreso mensual, aporte mensual y escenario de rentabilidad (Prudente / Realista / Ambicioso / Según backtest). Pulsa «Calcular plan»: obtienes meses hasta la meta, capital objetivo, tabla de fases y proyección mes a mes.",
        "La tabla de fases explica para cada etapa la regla de reinversión, el riesgo por operación y el criterio para avanzar. Fase 0 (Validación en paper) exige ≥ 60 operaciones, PF ≥ 1,3, drawdown ≤ 10 % y ≥ 28 días antes de pasar a dinero real.",
        "«Chequeo del plan · resultados reales» compara tus métricas reales con los criterios de la fase actual; cuando se cumplen aparece «Avanzar a …», que fija la fase y el riesgo recomendado.",
        "«Aportes del plan»: tus depósitos (paper o detectados en el bróker) se agrupan por mes y se comparan con el aporte comprometido; también verás tu capital frente al que el plan preveía a estas alturas.",
        "«Revisar plan y ajustar el bot con IA» pide a la IA una lectura del plan con tus datos reales y propone/aplica cambios dentro de los topes (con botón Deshacer).",
      ],
    },
    {
      id: "evolucion", icon: "GitBranch", title: "10 · Evolución y deshacer cambios",
      steps: [
        "Cinco contadores (cambios, aplicados por la IA, mejoraron, empeoraron, pendientes) y una línea de tiempo con icono por origen: IA (revisión automática, optimizar todo, plan, optimizador), revalidación semanal, perfil, manual o sistema.",
        "Cada evento muestra los ajustes modificados (antes → después), el resumen o razonamiento, y el rendimiento en la ventana posterior frente a la anterior (operaciones, PnL, acierto, PF, equidad) con veredicto Mejoró / Empeoró / Igual / Pendiente (hacen falta ≥ 5 operaciones).",
        "«Deshacer» restaura los valores anteriores de los ajustes que siguen vigentes (si cambiaste algo después, se conserva y se indica). El deshacer se registra como un nuevo evento.",
        "La IA revisa esta misma línea de tiempo en cada revisión automática y deshace sola los cambios con veredicto Empeoró.",
      ],
    },
    {
      id: "ajustes", icon: "Settings2", title: "11 · Ajustes (botón «Ajustes» de la cabecera)",
      steps: [
        "Seguridad: cambia la clave del panel (cierra las demás sesiones).",
        "Inteligencia artificial: fuente (llave universal de Emergent o tu API key de Google Gemini), proveedor y modelo (lista legible o escribir otro), «Probar conexión» antes de guardar, estado de salud en vivo. La configuración de IA es común a ambos bots.",
        "Telegram: crea un bot con @BotFather y pega el token; escribe un mensaje a tu bot y pulsa «Detectar chat ID»; activa los avisos que quieras y envía una prueba. Tarjeta «Resumen semanal»: vista previa y «Enviar ahora».",
        "Revisión IA automática: activar, frecuencia (diaria/semanal + día), aplicar cambios o solo avisar, «Ejecutar ahora» y última revisión con resumen y cambios.",
        "Agente de noticias" + (fx ? "" : " y Filtro de funding") + ": intervalos, ventanas de bloqueo, factores de tamaño" + (fx ? " y trading por noticias." : " y umbrales ALTO/EXTREMO."),
        fx ? "HotForex · cuenta real: token de MetaApi, login, contraseña master, servidor, plataforma MT4/MT5, región, sufijo de símbolos y endpoint avanzado; tipo de cuenta MetaApi con su coste (Cloud G2 alta · recomendada, G1 regular, G1 alta) y «Recrear con el nuevo tipo» si la cuenta ya existe con otro; Vincular, Probar conexión, Comprobar símbolos, Redesplegar y Quitar; aviso de desconexión (segundos); «Cambiar de cuenta · re-basar capital» para pasar de la demo a dinero real sin perder historial."
           : "Bybit · cuenta real: entorno (mainnet/testnet/demo), API key y secret, endpoint avanzado, Probar conexión (equidad, disponible, posiciones, desfase horario) y Quitar.",
        "Modo de operación: lista de comprobación y botón «Pasar a modo REAL» / «Volver a paper».",
        `Cuenta paper: capital inicial, aportes netos, equidad y operaciones; «Depositar / Retirar» para simular aportes; «Reiniciar con este capital» (borra operaciones, señales, sombras y movimientos; también disponible desde la cabecera con $500 ${cur}).`,
        "Copias de seguridad (comunes a ambos bots): última copia, crear ahora, descargar, lista de copias del servidor, restaurar una copia guardada o un archivo .json.gz de tu disco (requiere ambos bots detenidos y escribir RESTAURAR; tu clave actual se conserva).",
      ],
    },
    {
      id: "real", icon: "Landmark", title: `12 · Pasar a modo REAL con ${brokerName}`,
      steps: fx ? [
        "Crea una cuenta en MetaApi.cloud y copia tu token (API access token). En HFM necesitas el login, la contraseña MASTER (no la de inversor: con ella el bot solo podría leer) y el nombre exacto del servidor (p. ej. HFMarketsGlobal-Demo).",
        "Ajustes → HotForex · cuenta real: pega token, login, contraseña, servidor, plataforma y región; «Guardar» y luego «Vincular cuenta» (el bot la crea/despliega en MetaApi; tarda 1–3 min la primera vez).",
        "«Probar conexión» debe mostrar equidad, moneda, apalancamiento y «trading permitido». «Comprobar símbolos» verifica que tus pares cotizan en el bróker (ajusta el sufijo, p. ej. «.r», si hace falta).",
        "Modo de operación: cumple la lista (cuenta vinculada y verificada, trading permitido, bot detenido, sin posiciones; se recomienda haber superado la Fase 0 del plan), escribe REAL y confirma. Las estadísticas se reinician con la equidad real.",
        "Inicia el bot. A partir de ahora las órdenes, el PnL y la equidad vienen de HFM; las señales se siguen calculando con velas de Yahoo. Si la conexión cae más de 60 s te avisará y no abrirá nada hasta recuperarse.",
        "Para volver a paper: detén el bot, cierra posiciones y pulsa «Volver a paper» (la cuenta paper vuelve a $500).",
      ] : [
        "En Bybit crea una API key con permisos de Contratos/Derivados (lectura + órdenes), sin retiros, idealmente restringida a la IP de tu servidor. Para practicar usa el entorno Demo (demo trading) o Testnet.",
        "Ajustes → Bybit · cuenta real: elige el entorno, pega key y secret y pulsa «Probar conexión»: verás equidad, disponible, posiciones y desfase horario (debe ser pequeño).",
        "Modo de operación: cumple la lista (credenciales verificadas, bot detenido, sin posiciones; se recomienda haber superado la Fase 0 del plan), escribe REAL y confirma. Las estadísticas se reinician con la equidad real de tu wallet UNIFIED.",
        "Inicia el bot. Las órdenes son a mercado con stop y objetivo adjuntos (tpslMode Full), el trailing se envía al exchange y los cierres hechos en Bybit se detectan en segundos.",
        "Importante: Bybit bloquea su API desde algunas regiones (p. ej. EE. UU.); el servidor que ejecute el bot debe estar en una región permitida. En paper, si Bybit no responde, los precios se toman de Bitget.",
        "Para volver a paper: detén el bot, cierra posiciones y pulsa «Volver a paper».",
      ],
    },
    {
      id: "vps", icon: "Server", title: "13 · Ejecutarlo en tu propio servidor (VPS)",
      steps: [
        "Pulsa el botón «Instalar en tu VPS» de la cabecera: descarga un zip con la app completa (sin tus claves ni datos) y sigue la guía detallada con los comandos listos para copiar. La misma guía viaja dentro del zip en deploy/INSTALACION.md.",
        "Carpeta deploy/: `install.sh` instala Docker, genera secretos y contraseña, construye los contenedores (Mongo + backend + web con HTTPS automático si usas dominio) y programa los crons: revisión IA 08:00 UTC, walk-forward lunes 07:00, resumen semanal domingos 20:00 y copia de seguridad 03:00.",
        "`update-zip.sh archivo.zip` actualiza a una versión nueva descargada del panel (conserva claves, copias y base de datos); `backup.sh` crea una copia ahora (`--telegram` para enviarla); `restore.sh archivo.json.gz` restaura una copia; `reset-password.sh` cambia la contraseña si la olvidas; `clean-disk.sh` libera espacio (caché de compilación de Docker, imágenes huérfanas, journald).",
        "Las copias se guardan en deploy/backups/ (14 días) y también puedes descargarlas desde Ajustes → Copias de seguridad. Guarda a buen recaudo la CREDENTIAL_ENCRYPTION_KEY de backend.env: sin ella no se pueden leer las API keys de una copia.",
      ],
    },
  ];
}
