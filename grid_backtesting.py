import time
from binance.client import Client
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# ═══════════════════════════════
# CONFIGURACIÓN GRID BOT
# ═══════════════════════════════
API_KEY = 'T6qCY5ykV4UWACdSVb5KE4uTa0sMUZeWthurSJUtj3tWUnrxYNbjmNuyrQfvsCJS'
API_SECRET = 'pgCKdUIYTKVrnqlBJTKwL5YCG7TApA0rcPFwV0K4GEL7bFON59j5GjPSlnqWOfXp'

# Parámetros del Grid
SYMBOL = 'BTCUSDT'
CAPITAL_INICIAL = 1000      # USDT total a usar
NIVELES = 10                # Número de grillas (más niveles = más trades)
RANGO_PCT = 0.20            # Rango total de la grilla (20% arriba y abajo)
COMISION = 0.001            # 0.1% por trade
MESES = 6

# ═══════════════════════════════
# CONEXIÓN BINANCE REAL
# ═══════════════════════════════
client = Client(API_KEY, API_SECRET)

# ═══════════════════════════════
# OBTENER DATOS HISTÓRICOS
# ═══════════════════════════════
def get_historical_data(symbol, meses=6):
    print(f"  📥 Descargando {meses} meses de {symbol}...")
    start_time = datetime.now() - timedelta(days=meses*30)
    start_str = start_time.strftime('%d %b %Y')

    try:
        all_candles = []
        temp_start = start_str

        while True:
            candles = client.get_historical_klines(
                symbol=symbol,
                interval=Client.KLINE_INTERVAL_1HOUR,
                start_str=temp_start,
                limit=1000
            )
            if not candles:
                break
            all_candles.extend(candles)
            if len(candles) < 1000:
                break
            last_time = candles[-1][0]
            temp_start = datetime.fromtimestamp(last_time/1000).strftime('%d %b %Y %H:%M:%S')
            time.sleep(0.5)

        if not all_candles:
            return None

        df = pd.DataFrame(all_candles, columns=[
            'time','open','high','low','close','volume',
            'close_time','quote_vol','trades','buy_base','buy_quote','ignore'
        ])
        df = df.drop_duplicates(subset=['time'])
        for col in ['close','high','low','open']:
            df[col] = pd.to_numeric(df[col])
        df['time'] = pd.to_datetime(df['time'], unit='ms')
        df = df.sort_values('time').reset_index(drop=True)

        print(f"  ✅ {len(df)} velas ({df['time'].iloc[0].strftime('%d/%m/%Y')} → {df['time'].iloc[-1].strftime('%d/%m/%Y')})")
        return df

    except Exception as e:
        print(f"  ❌ Error: {e}")
        return None

# ═══════════════════════════════
# GRID BOT ENGINE
# ═══════════════════════════════
def crear_grilla(precio_base, niveles, rango_pct):
    """Crea los niveles de compra y venta de la grilla"""
    paso = (rango_pct * 2) / niveles
    grilla = []

    for i in range(-niveles//2, niveles//2 + 1):
        nivel_precio = precio_base * (1 + i * paso / 2)
        grilla.append(round(nivel_precio, 2))

    return sorted(grilla)

def backtest_grid(df, capital_inicial, niveles, rango_pct):
    """
    Simula el Grid Bot en datos históricos.
    
    El bot divide el capital en niveles y coloca órdenes de compra
    y venta en cada nivel. Cada vez que el precio cruza un nivel
    ejecuta el trade correspondiente.
    """
    precio_inicial = df['close'].iloc[0]
    grilla = crear_grilla(precio_inicial, niveles, rango_pct)

    print(f"\n  📊 Grilla configurada:")
    print(f"     Precio base:    ${precio_inicial:,.2f}")
    print(f"     Nivel inferior: ${grilla[0]:,.2f}")
    print(f"     Nivel superior: ${grilla[-1]:,.2f}")
    print(f"     Niveles:        {len(grilla)}")
    print(f"     Capital/nivel:  ${capital_inicial/niveles:,.2f}")

    # Capital por nivel
    capital_por_nivel = capital_inicial / niveles
    usdt_disponible = capital_inicial / 2    # 50% en USDT para compras
    btc_disponible = (capital_inicial / 2) / precio_inicial  # 50% en BTC para ventas

    trades = []
    ganancia_total = 0
    ultimo_nivel = None
    nivel_actual_idx = None

    # Encontrar en qué nivel está el precio inicial
    for i, nivel in enumerate(grilla):
        if precio_inicial >= nivel:
            nivel_actual_idx = i

    capital_historico = [capital_inicial]
    capital_acumulado = capital_inicial

    for i in range(1, len(df)):
        precio = df['close'].iloc[i]
        high = df['high'].iloc[i]
        low = df['low'].iloc[i]
        fecha = df['time'].iloc[i]

        # Verificar qué niveles cruzó el precio en esta vela
        for j, nivel in enumerate(grilla):

            # COMPRA — precio bajó hasta este nivel
            if low <= nivel and nivel < precio and j < nivel_actual_idx if nivel_actual_idx else True:
                if usdt_disponible >= capital_por_nivel:
                    cantidad_btc = (capital_por_nivel / nivel) * (1 - COMISION)
                    usdt_disponible -= capital_por_nivel
                    btc_disponible += cantidad_btc
                    ganancia_nivel = 0  # Se realiza al vender

                    trades.append({
                        'fecha': fecha,
                        'tipo': 'BUY',
                        'precio': nivel,
                        'cantidad': cantidad_btc,
                        'ganancia': 0,
                        'nivel': j
                    })

            # VENTA — precio subió hasta este nivel
            elif high >= nivel and nivel > precio and j > (nivel_actual_idx if nivel_actual_idx else 0):
                if btc_disponible >= capital_por_nivel / nivel:
                    cantidad_btc = capital_por_nivel / nivel
                    if cantidad_btc <= btc_disponible:
                        ingreso = cantidad_btc * nivel * (1 - COMISION)
                        costo = cantidad_btc * (nivel * (1 - (rango_pct * 2 / niveles) / 2))
                        ganancia = ingreso - costo - (capital_por_nivel * COMISION)
                        ganancia = capital_por_nivel * (rango_pct * 2 / niveles) / 2 * (1 - COMISION * 2)

                        btc_disponible -= cantidad_btc
                        usdt_disponible += ingreso
                        ganancia_total += ganancia
                        capital_acumulado += ganancia

                        trades.append({
                            'fecha': fecha,
                            'tipo': 'SELL',
                            'precio': nivel,
                            'cantidad': cantidad_btc,
                            'ganancia': ganancia,
                            'nivel': j
                        })

                        capital_historico.append(capital_acumulado)

        # Actualizar nivel actual
        for k, nivel in enumerate(grilla):
            if precio >= nivel:
                nivel_actual_idx = k

    # Valor final incluyendo BTC en cartera
    precio_final = df['close'].iloc[-1]
    valor_btc_final = btc_disponible * precio_final
    capital_final = usdt_disponible + valor_btc_final

    return trades, capital_final, ganancia_total, capital_historico

# ═══════════════════════════════
# ANÁLISIS DE RESULTADOS
# ═══════════════════════════════
def analizar_grid(trades, capital_inicial, capital_final, ganancia_trading):
    ventas = [t for t in trades if t['tipo'] == 'SELL']
    compras = [t for t in trades if t['tipo'] == 'BUY']

    retorno_pct = (capital_final - capital_inicial) / capital_inicial * 100
    ganancia_mes = ganancia_trading / MESES

    print(f"\n  {'─'*50}")
    print(f"  📊 RESULTADOS GRID BOT — {MESES} meses")
    print(f"  {'─'*50}")
    print(f"  💰 Capital inicial:       ${capital_inicial:,.2f}")
    print(f"  💰 Capital final:         ${capital_final:,.2f}")
    print(f"  📈 Retorno total:         ${capital_final-capital_inicial:+,.2f} ({retorno_pct:+.1f}%)")
    print(f"  💵 Ganancia por trading:  ${ganancia_trading:+,.2f}")
    print(f"  📅 Ganancia mensual prom: ${ganancia_mes:+,.2f}")
    print(f"  {'─'*50}")
    print(f"  🎯 Total trades:          {len(trades)}")
    print(f"  🟢 Compras ejecutadas:    {len(compras)}")
    print(f"  🔴 Ventas ejecutadas:     {len(ventas)}")
    print(f"  💵 Ganancia por venta:    ${(ganancia_trading/len(ventas) if ventas else 0):+,.2f}")
    print(f"  {'─'*50}")

    return {
        'capital_final': capital_final,
        'retorno_pct': retorno_pct,
        'ganancia_trading': ganancia_trading,
        'ganancia_mensual': ganancia_mes,
        'total_trades': len(trades),
        'ventas': len(ventas),
        'compras': len(compras)
    }

# ═══════════════════════════════
# COMPARAR CONFIGURACIONES
# ═══════════════════════════════
def comparar_configuraciones(df):
    """Prueba múltiples configuraciones de grilla para encontrar la óptima"""
    configs = [
        {'niveles': 5,  'rango': 0.15, 'nombre': '5 niveles / 15% rango'},
        {'niveles': 10, 'rango': 0.20, 'nombre': '10 niveles / 20% rango'},
        {'niveles': 15, 'rango': 0.25, 'nombre': '15 niveles / 25% rango'},
        {'niveles': 20, 'rango': 0.30, 'nombre': '20 niveles / 30% rango'},
    ]

    print(f"\n  {'─'*50}")
    print(f"  🔬 COMPARANDO CONFIGURACIONES")
    print(f"  {'─'*50}")
    print(f"  {'Configuración':<30} {'Retorno':>8} {'Trades':>8} {'Mensual':>10}")
    print(f"  {'─'*50}")

    mejor = None
    mejor_retorno = -999

    for cfg in configs:
        trades, cap_final, gan_trading, _ = backtest_grid(
            df, CAPITAL_INICIAL, cfg['niveles'], cfg['rango']
        )
        ventas = [t for t in trades if t['tipo'] == 'SELL']
        retorno = (cap_final - CAPITAL_INICIAL) / CAPITAL_INICIAL * 100
        mensual = gan_trading / MESES

        print(f"  {cfg['nombre']:<30} {retorno:>+7.1f}% {len(trades):>8} ${mensual:>8.2f}/mes")

        if retorno > mejor_retorno:
            mejor_retorno = retorno
            mejor = cfg

    print(f"  {'─'*50}")
    print(f"  🏆 Mejor configuración: {mejor['nombre']}")
    return mejor

# ═══════════════════════════════
# MAIN
# ═══════════════════════════════
def main():
    print("\n" + "═"*60)
    print("  🤖 AutoTrader — Grid Bot Backtesting v1.0")
    print(f"  Par: {SYMBOL} | Capital: ${CAPITAL_INICIAL:,} | Período: {MESES} meses")
    print(f"  Niveles: {NIVELES} | Rango: {RANGO_PCT*100:.0f}%")
    print(f"  ⚠️  Solo lectura — no ejecuta trades reales")
    print("═"*60)

    print(f"\n📥 Obteniendo datos históricos...")
    df = get_historical_data(SYMBOL, MESES)
    if df is None:
        print("❌ No se pudieron obtener datos")
        return

    # Comparar configuraciones
    mejor_config = comparar_configuraciones(df)

    # Backtesting con mejor configuración
    print(f"\n\n🚀 Backtesting con mejor configuración...")
    trades, capital_final, ganancia_trading, capital_hist = backtest_grid(
        df, CAPITAL_INICIAL, mejor_config['niveles'], mejor_config['rango']
    )

    resultado = analizar_grid(trades, CAPITAL_INICIAL, capital_final, ganancia_trading)

    # Proyecciones
    print(f"\n  {'═'*50}")
    print(f"  📈 PROYECCIONES CON GRID BOT")
    print(f"  {'═'*50}")

    retorno_mensual = resultado['retorno_pct'] / MESES

    for capital in [500, 1000, 2000, 5000, 10000]:
        ganancia_mes = capital * retorno_mensual / 100
        print(f"  Capital ${capital:>7,} → ${ganancia_mes:>8.2f}/mes ({retorno_mensual:.1f}%/mes)")

    print(f"\n  {'═'*50}")
    print(f"  💡 VEREDICTO FINAL")
    print(f"  {'═'*50}")

    if resultado['retorno_pct'] > 15:
        print(f"  🏆 EXCELENTE — +{resultado['retorno_pct']:.1f}% en {MESES} meses")
        print(f"  ✅ Grid Bot listo para producción")
    elif resultado['retorno_pct'] > 8:
        print(f"  ✅ BUENO — +{resultado['retorno_pct']:.1f}% en {MESES} meses")
        print(f"  ✅ Grid Bot viable para producción")
    elif resultado['retorno_pct'] > 0:
        print(f"  ⚠️  MODERADO — +{resultado['retorno_pct']:.1f}% en {MESES} meses")
        print(f"  ⚠️  Optimizar antes de producción")
    else:
        print(f"  ❌ NEGATIVO — {resultado['retorno_pct']:.1f}% en {MESES} meses")
        print(f"  ❌ Revisar configuración")

    print(f"  {'═'*50}")

if __name__ == "__main__":
    main()
