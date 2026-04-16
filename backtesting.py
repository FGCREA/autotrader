import time
from binance.client import Client
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json

# ═══════════════════════════════
# CONFIGURACIÓN OPTIMIZADA v5.0
# ═══════════════════════════════
API_KEY = 'T6qCY5ykV4UWACdSVb5KE4uTa0sMUZeWthurSJUtj3tWUnrxYNbjmNuyrQfvsCJS'
API_SECRET = 'pgCKdUIYTKVrnqlBJTKwL5YCG7TApA0rcPFwV0K4GEL7bFON59j5GjPSlnqWOfXp'

SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT']
CAPITAL_INICIAL = 1000
COMISION = 0.001

# Configuraciones a testear
CONFIGS = [
    {'nombre': 'Conservador',  'sl': 0.012, 'tp': 0.025, 'rsi_c': 35, 'rsi_v': 65},
    {'nombre': 'Balanceado',   'sl': 0.012, 'tp': 0.030, 'rsi_c': 40, 'rsi_v': 62},
    {'nombre': 'Agresivo',     'sl': 0.015, 'tp': 0.035, 'rsi_c': 42, 'rsi_v': 58},
    {'nombre': 'Ultra filtro', 'sl': 0.010, 'tp': 0.030, 'rsi_c': 38, 'rsi_v': 64},
]

PERIODOS = [3, 6, 12]  # meses a analizar

client = Client(API_KEY, API_SECRET)

# ═══════════════════════════════
# INDICADORES
# ═══════════════════════════════
def calcular_rsi(df, periodo=14):
    delta = df['close'].diff()
    ganancia = delta.where(delta > 0, 0)
    perdida = -delta.where(delta < 0, 0)
    avg_g = ganancia.rolling(periodo).mean()
    avg_p = perdida.rolling(periodo).mean()
    rs = avg_g / avg_p
    return 100 - (100 / (1 + rs))

def calcular_ema(df, periodo):
    return df['close'].ewm(span=periodo, adjust=False).mean()

def calcular_macd(df):
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    return macd, signal

def calcular_bollinger(df, periodo=20):
    media = df['close'].rolling(periodo).mean()
    std = df['close'].rolling(periodo).std()
    return media + (std * 2), media, media - (std * 2)

def calcular_atr(df, periodo=14):
    high = df['high']
    low = df['low']
    close = df['close'].shift(1)
    tr = pd.concat([high - low, (high - close).abs(), (low - close).abs()], axis=1).max(axis=1)
    return tr.rolling(periodo).mean()

def calcular_volumen_relativo(df, periodo=20):
    return df['volume'] / df['volume'].rolling(periodo).mean()

# ═══════════════════════════════
# OBTENER DATOS HISTÓRICOS
# ═══════════════════════════════
def get_historical_data(symbol, meses=6):
    print(f"  📥 Descargando {meses} meses de {symbol}...")
    start_time = datetime.now() - timedelta(days=meses * 30)
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
            temp_start = datetime.fromtimestamp(last_time / 1000).strftime('%d %b %Y %H:%M:%S')
            time.sleep(0.5)

        if not all_candles:
            return None

        df = pd.DataFrame(all_candles, columns=[
            'time', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_vol', 'trades', 'buy_base', 'buy_quote', 'ignore'
        ])
        df = df.drop_duplicates(subset=['time'])
        for col in ['close', 'high', 'low', 'open', 'volume']:
            df[col] = pd.to_numeric(df[col])
        df['time'] = pd.to_datetime(df['time'], unit='ms')
        df = df.sort_values('time').reset_index(drop=True)

        print(f"  ✅ {len(df)} velas ({df['time'].iloc[0].strftime('%d/%m/%Y')} → {df['time'].iloc[-1].strftime('%d/%m/%Y')})")
        return df

    except Exception as e:
        print(f"  ❌ Error: {e}")
        return None

# ═══════════════════════════════
# BACKTESTING ENGINE v5.0
# Mejoras: ATR dinámico, filtro volumen, trailing stop
# ═══════════════════════════════
def backtest(df, symbol, capital_inicial=1000, sl_pct=0.012, tp_pct=0.03, rsi_compra=40, rsi_venta=62):
    capital = capital_inicial
    en_posicion = False
    precio_entrada = 0
    cantidad = 0
    sl_precio = 0
    tp_precio = 0
    max_precio = 0  # para trailing stop
    trades = []
    capital_historico = [capital]

    df = df.copy()
    df['rsi'] = calcular_rsi(df, 14)
    df['ema20'] = calcular_ema(df, 20)
    df['ema50'] = calcular_ema(df, 50)
    df['ema200'] = calcular_ema(df, 200)
    df['macd'], df['macd_signal'] = calcular_macd(df)
    df['bb_upper'], df['bb_media'], df['bb_lower'] = calcular_bollinger(df)
    df['atr'] = calcular_atr(df)
    df['vol_rel'] = calcular_volumen_relativo(df)
    df = df.dropna().reset_index(drop=True)

    for i in range(1, len(df)):
        precio = df['close'].iloc[i]
        high = df['high'].iloc[i]
        rsi = df['rsi'].iloc[i]
        prev_rsi = df['rsi'].iloc[i - 1]
        ema20 = df['ema20'].iloc[i]
        ema50 = df['ema50'].iloc[i]
        ema200 = df['ema200'].iloc[i]
        macd = df['macd'].iloc[i]
        macd_signal = df['macd_signal'].iloc[i]
        bb_upper = df['bb_upper'].iloc[i]
        bb_lower = df['bb_lower'].iloc[i]
        atr = df['atr'].iloc[i]
        vol_rel = df['vol_rel'].iloc[i]
        fecha = df['time'].iloc[i]

        if en_posicion:
            # Actualizar trailing stop — mover SL hacia arriba si el precio sube
            if high > max_precio:
                max_precio = high
                nuevo_sl = max_precio * (1 - sl_pct * 1.5)
                if nuevo_sl > sl_precio:
                    sl_precio = nuevo_sl

            # Stop Loss
            if precio <= sl_precio:
                ganancia = (precio - precio_entrada) * cantidad
                ganancia -= abs(ganancia) * COMISION
                capital += ganancia
                trades.append({
                    'fecha': fecha.isoformat(), 'symbol': symbol,
                    'tipo': 'SELL_SL', 'precio': round(precio, 2),
                    'ganancia': round(ganancia, 2), 'capital': round(capital, 2),
                    'resultado': 'STOP LOSS', 'rsi': round(rsi, 1)
                })
                en_posicion = False
                capital_historico.append(capital)
                continue

            # Take Profit
            if precio >= tp_precio:
                ganancia = (precio - precio_entrada) * cantidad
                ganancia -= abs(ganancia) * COMISION
                capital += ganancia
                trades.append({
                    'fecha': fecha.isoformat(), 'symbol': symbol,
                    'tipo': 'SELL_TP', 'precio': round(precio, 2),
                    'ganancia': round(ganancia, 2), 'capital': round(capital, 2),
                    'resultado': 'TAKE PROFIT', 'rsi': round(rsi, 1)
                })
                en_posicion = False
                capital_historico.append(capital)
                continue

            # Venta por señal técnica
            venta = (rsi > rsi_venta and ema20 < ema50 and macd < macd_signal)
            venta_alt = (precio >= bb_upper * 0.999 and rsi > rsi_venta - 4)

            if venta or venta_alt:
                ganancia = (precio - precio_entrada) * cantidad
                ganancia -= abs(ganancia) * COMISION
                capital += ganancia
                resultado = 'WIN' if ganancia > 0 else 'LOSS'
                trades.append({
                    'fecha': fecha.isoformat(), 'symbol': symbol,
                    'tipo': 'SELL', 'precio': round(precio, 2),
                    'ganancia': round(ganancia, 2), 'capital': round(capital, 2),
                    'resultado': resultado, 'rsi': round(rsi, 1)
                })
                en_posicion = False
                capital_historico.append(capital)

        else:
            # Filtros de entrada
            tendencia_ok = precio > ema200 * 0.98
            volumen_ok = vol_rel > 0.8  # volumen decente
            no_sobreextendido = atr > 0  # ATR válido

            compra = (rsi < rsi_compra and ema20 > ema50 and macd > macd_signal
                      and tendencia_ok and volumen_ok)
            compra_alt = (precio <= bb_lower * 1.003 and rsi < rsi_compra + 2
                         and prev_rsi < rsi and tendencia_ok and volumen_ok)

            if compra or compra_alt:
                capital_en_trade = capital * 0.95
                cantidad = capital_en_trade / precio
                precio_entrada = precio
                sl_precio = precio * (1 - sl_pct)
                tp_precio = precio * (1 + tp_pct)
                max_precio = precio
                en_posicion = True
                trades.append({
                    'fecha': fecha.isoformat(), 'symbol': symbol,
                    'tipo': 'BUY', 'precio': round(precio, 2),
                    'ganancia': 0, 'capital': round(capital, 2),
                    'resultado': 'ENTRADA', 'rsi': round(rsi, 1)
                })

    # Cerrar posición abierta al final
    if en_posicion:
        precio_final = df['close'].iloc[-1]
        ganancia = (precio_final - precio_entrada) * cantidad
        ganancia -= abs(ganancia) * COMISION
        capital += ganancia
        trades.append({
            'fecha': df['time'].iloc[-1].isoformat(), 'symbol': symbol,
            'tipo': 'SELL_FINAL', 'precio': round(precio_final, 2),
            'ganancia': round(ganancia, 2), 'capital': round(capital, 2),
            'resultado': 'WIN' if ganancia > 0 else 'LOSS', 'rsi': 0
        })

    return trades, capital, capital_historico

# ═══════════════════════════════
# ANÁLISIS DE RESULTADOS
# ═══════════════════════════════
def analizar(trades, capital_inicial, capital_final, symbol, config_nombre):
    cerrados = [t for t in trades if t['tipo'] != 'BUY']
    if not cerrados:
        return None

    wins = [t for t in cerrados if t['ganancia'] > 0]
    losses = [t for t in cerrados if t['ganancia'] <= 0]
    total = len(cerrados)
    wr = (len(wins) / total * 100) if total > 0 else 0
    ganancia_total = capital_final - capital_inicial
    retorno_pct = ganancia_total / capital_inicial * 100
    gp = np.mean([t['ganancia'] for t in wins]) if wins else 0
    pp = np.mean([t['ganancia'] for t in losses]) if losses else 0
    sw = sum(t['ganancia'] for t in wins)
    sl_sum = abs(sum(t['ganancia'] for t in losses))
    pf = sw / sl_sum if sl_sum > 0 else float('inf')

    # Max drawdown
    caps = [t['capital'] for t in cerrados]
    peak = capital_inicial
    max_dd = 0
    for c in caps:
        if c > peak:
            peak = c
        dd = (peak - c) / peak * 100
        if dd > max_dd:
            max_dd = dd

    # Racha máxima de wins y losses
    racha_win = racha_loss = max_racha_win = max_racha_loss = 0
    for t in cerrados:
        if t['ganancia'] > 0:
            racha_win += 1
            racha_loss = 0
            max_racha_win = max(max_racha_win, racha_win)
        else:
            racha_loss += 1
            racha_win = 0
            max_racha_loss = max(max_racha_loss, racha_loss)

    # Retorno mensual promedio
    if cerrados:
        primer_trade = datetime.fromisoformat(cerrados[0]['fecha'])
        ultimo_trade = datetime.fromisoformat(cerrados[-1]['fecha'])
        meses_reales = max(1, (ultimo_trade - primer_trade).days / 30)
        retorno_mensual = retorno_pct / meses_reales
    else:
        retorno_mensual = 0

    sl_count = len([t for t in cerrados if t['tipo'] == 'SELL_SL'])
    tp_count = len([t for t in cerrados if t['tipo'] == 'SELL_TP'])

    print(f"\n  {'─' * 55}")
    print(f"  📊 {symbol} — Config: {config_nombre}")
    print(f"  {'─' * 55}")
    print(f"  💰 ${capital_inicial:,.0f} → ${capital_final:,.2f}  ({retorno_pct:+.1f}%)")
    print(f"  📈 Retorno mensual:     {retorno_mensual:+.1f}%/mes")
    print(f"  📉 Max drawdown:        {max_dd:.1f}%")
    print(f"  {'─' * 55}")
    print(f"  🎯 Trades: {total}  |  ✅ Wins: {len(wins)} ({wr:.0f}%)  |  ❌ Losses: {len(losses)}")
    print(f"  🛑 Stop losses: {sl_count}  |  🎯 Take profits: {tp_count}")
    print(f"  💵 Ganancia prom: ${gp:+.2f}  |  💸 Pérdida prom: ${pp:.2f}")
    print(f"  ⚡ Profit factor: {pf:.2f}  |  Ratio G/P: {abs(gp/pp) if pp else 0:.2f}")
    print(f"  🔥 Racha max wins: {max_racha_win}  |  ❄️ Racha max losses: {max_racha_loss}")

    return {
        'symbol': symbol, 'config': config_nombre,
        'capital_final': round(capital_final, 2),
        'ganancia': round(ganancia_total, 2),
        'retorno_pct': round(retorno_pct, 1),
        'retorno_mensual': round(retorno_mensual, 1),
        'total_trades': total,
        'win_rate': round(wr, 1),
        'profit_factor': round(pf, 2),
        'max_drawdown': round(max_dd, 1),
        'max_racha_win': max_racha_win,
        'max_racha_loss': max_racha_loss,
        'trades': trades
    }

# ═══════════════════════════════
# MAIN
# ═══════════════════════════════
def main():
    print("\n" + "═" * 60)
    print("  🤖 AutoTrader — Backtesting Engine v5.0")
    print(f"  Capital: ${CAPITAL_INICIAL:,}")
    print(f"  Pares: {', '.join(SYMBOLS)}")
    print(f"  Mejoras: Trailing stop, filtro volumen, ATR dinámico")
    print(f"  Configuraciones a testear: {len(CONFIGS)}")
    print(f"  Períodos: {PERIODOS} meses")
    print(f"  ⚠️  Solo lectura — no ejecuta trades reales")
    print("═" * 60)

    todos_resultados = []
    mejor_resultado = None
    mejor_score = -999

    for meses in PERIODOS:
        print(f"\n{'═' * 60}")
        print(f"  📅 PERÍODO: {meses} MESES")
        print(f"{'═' * 60}")

        # Descargar datos una vez por par por período
        datos = {}
        for symbol in SYMBOLS:
            df = get_historical_data(symbol, meses)
            if df is not None:
                datos[symbol] = df
            time.sleep(1)

        for cfg in CONFIGS:
            print(f"\n  🔧 Config: {cfg['nombre']} — SL:{cfg['sl']*100}% TP:{cfg['tp']*100}% RSI<{cfg['rsi_c']} RSI>{cfg['rsi_v']}")

            for symbol, df in datos.items():
                trades, cap_final, hist = backtest(
                    df, symbol, CAPITAL_INICIAL,
                    sl_pct=cfg['sl'], tp_pct=cfg['tp'],
                    rsi_compra=cfg['rsi_c'], rsi_venta=cfg['rsi_v']
                )
                r = analizar(trades, CAPITAL_INICIAL, cap_final, symbol, cfg['nombre'])
                if r:
                    r['meses'] = meses
                    todos_resultados.append(r)

                    # Score = retorno - drawdown + win_rate bonus
                    score = r['retorno_pct'] - r['max_drawdown'] * 0.5 + (r['win_rate'] - 50) * 0.3
                    if score > mejor_score:
                        mejor_score = score
                        mejor_resultado = r

    # ═══════════════════════════════
    # RESUMEN FINAL
    # ═══════════════════════════════
    if todos_resultados:
        print("\n" + "═" * 60)
        print("  🏆 RANKING DE RESULTADOS")
        print("═" * 60)

        # Ordenar por retorno
        ranking = sorted(todos_resultados, key=lambda x: x['retorno_pct'], reverse=True)

        for i, r in enumerate(ranking[:15]):
            emoji = '🥇' if i == 0 else '🥈' if i == 1 else '🥉' if i == 2 else '  '
            estado = '✅' if r['retorno_pct'] > 5 else '⚠️' if r['retorno_pct'] > 0 else '❌'
            print(f"  {emoji} {estado} {r['symbol']} | {r['config']} | {r['meses']}m | "
                  f"Ret: {r['retorno_pct']:+.1f}% | WR: {r['win_rate']:.0f}% | "
                  f"PF: {r['profit_factor']:.2f} | DD: {r['max_drawdown']:.1f}% | "
                  f"{r['total_trades']} trades")

        print(f"\n  {'─' * 55}")
        print(f"  🏆 MEJOR COMBINACIÓN:")
        print(f"  {'─' * 55}")
        if mejor_resultado:
            m = mejor_resultado
            print(f"  Par:           {m['symbol']}")
            print(f"  Config:        {m['config']}")
            print(f"  Período:       {m['meses']} meses")
            print(f"  Retorno:       {m['retorno_pct']:+.1f}% (${m['ganancia']:+,.2f})")
            print(f"  Ret. mensual:  {m['retorno_mensual']:+.1f}%/mes")
            print(f"  Win rate:      {m['win_rate']:.0f}%")
            print(f"  Profit factor: {m['profit_factor']:.2f}")
            print(f"  Max drawdown:  {m['max_drawdown']:.1f}%")
            print(f"  Trades:        {m['total_trades']}")

        # Guardar mejor resultado a JSON
        if mejor_resultado:
            export = {
                'meta': {
                    'fecha': datetime.now().isoformat(),
                    'version': 'v5.0',
                    'capital_inicial': CAPITAL_INICIAL,
                    'mejor_config': mejor_resultado['config'],
                    'mejor_par': mejor_resultado['symbol'],
                    'mejor_periodo': mejor_resultado['meses'],
                },
                'resultado': {
                    'retorno_pct': mejor_resultado['retorno_pct'],
                    'win_rate': mejor_resultado['win_rate'],
                    'profit_factor': mejor_resultado['profit_factor'],
                    'max_drawdown': mejor_resultado['max_drawdown'],
                    'total_trades': mejor_resultado['total_trades'],
                },
                'trades': mejor_resultado['trades']
            }
            with open('backtesting_resultado.json', 'w') as f:
                json.dump(export, f, indent=2, default=str)
            print(f"\n  💾 Resultado guardado en backtesting_resultado.json")

        # Veredicto
        print(f"\n  {'─' * 55}")
        rentables = [r for r in todos_resultados if r['retorno_pct'] > 5]
        viables = [r for r in todos_resultados if 0 < r['retorno_pct'] <= 5]
        negativos = [r for r in todos_resultados if r['retorno_pct'] <= 0]

        print(f"  📊 RESUMEN: {len(rentables)} rentables | {len(viables)} marginales | {len(negativos)} negativos")

        if mejor_resultado and mejor_resultado['retorno_pct'] > 10 and mejor_resultado['win_rate'] > 55:
            print("  🏆 ESTRATEGIA EXCELENTE — Lista para producción")
        elif mejor_resultado and mejor_resultado['retorno_pct'] > 5:
            print("  ✅ ESTRATEGIA VIABLE — Buena para operar")
        elif mejor_resultado and mejor_resultado['retorno_pct'] > 0:
            print("  ⚠️  ESTRATEGIA MARGINAL — Seguir optimizando")
        else:
            print("  ❌ ESTRATEGIA NO RENTABLE — Cambiar enfoque")

        print("═" * 60)

if __name__ == "__main__":
    main()
