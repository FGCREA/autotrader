import time
from binance.client import Client
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# ═══════════════════════════════
# CONFIGURACIÓN BALANCEADA
# Basada en los mejores resultados del backtesting anterior
# BTC: +13.5% con RSI<40 | Ahora agregamos filtro EMA200
# ═══════════════════════════════
API_KEY = 'T6qCY5ykV4UWACdSVb5KE4uTa0sMUZeWthurSJUtj3tWUnrxYNbjmNuyrQfvsCJS'
API_SECRET = 'pgCKdUIYTKVrnqlBJTKwL5YCG7TApA0rcPFwV0K4GEL7bFON59j5GjPSlnqWOfXp'

SYMBOLS = ['BTCUSDT', 'ETHUSDT']  # BTC + ETH — los más líquidos
CAPITAL_INICIAL = 1000
STOP_LOSS = 0.012       # 1.2% — equilibrio entre el 1% y 1.5% original
TAKE_PROFIT = 0.03      # 3% — más alcanzable que 4%, mejor que 2.5%
COMISION = 0.001
MESES = 6

RSI_PERIODO = 14
RSI_COMPRA = 40         # Volvemos al 40 — más señales, mejor rendimiento
RSI_VENTA = 62          # 62 en vez de 60 — menos falsas ventas

# ═══════════════════════════════
# CONEXIÓN BINANCE REAL
# ═══════════════════════════════
client = Client(API_KEY, API_SECRET)

# ═══════════════════════════════
# INDICADORES
# ═══════════════════════════════
def calcular_rsi(df, periodo=14):
    delta = df['close'].diff()
    ganancia = delta.where(delta > 0, 0)
    perdida = -delta.where(delta < 0, 0)
    avg_ganancia = ganancia.rolling(periodo).mean()
    avg_perdida = perdida.rolling(periodo).mean()
    rs = avg_ganancia / avg_perdida
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
# BACKTESTING ENGINE
# ═══════════════════════════════
def backtest(df, symbol, capital_inicial=1000):
    capital = capital_inicial
    en_posicion = False
    precio_entrada = 0
    cantidad = 0
    sl_precio = 0
    tp_precio = 0
    trades = []
    capital_historico = [capital]

    df = df.copy()
    df['rsi'] = calcular_rsi(df, RSI_PERIODO)
    df['ema20'] = calcular_ema(df, 20)
    df['ema50'] = calcular_ema(df, 50)
    df['ema200'] = calcular_ema(df, 200)
    df['macd'], df['macd_signal'] = calcular_macd(df)
    df['bb_upper'], df['bb_media'], df['bb_lower'] = calcular_bollinger(df)
    df = df.dropna().reset_index(drop=True)

    for i in range(1, len(df)):
        precio = df['close'].iloc[i]
        rsi = df['rsi'].iloc[i]
        prev_rsi = df['rsi'].iloc[i-1]
        ema20 = df['ema20'].iloc[i]
        ema50 = df['ema50'].iloc[i]
        ema200 = df['ema200'].iloc[i]
        macd = df['macd'].iloc[i]
        macd_signal = df['macd_signal'].iloc[i]
        bb_upper = df['bb_upper'].iloc[i]
        bb_lower = df['bb_lower'].iloc[i]
        fecha = df['time'].iloc[i]

        if en_posicion:
            if precio <= sl_precio:
                ganancia = (precio - precio_entrada) * cantidad - abs((precio - precio_entrada) * cantidad) * COMISION
                capital += ganancia
                trades.append({'fecha':fecha,'tipo':'SELL_SL','precio':precio,'ganancia':ganancia,'capital':capital,'resultado':'STOP LOSS'})
                en_posicion = False
                capital_historico.append(capital)
                continue

            if precio >= tp_precio:
                ganancia = (precio - precio_entrada) * cantidad - abs((precio - precio_entrada) * cantidad) * COMISION
                capital += ganancia
                trades.append({'fecha':fecha,'tipo':'SELL_TP','precio':precio,'ganancia':ganancia,'capital':capital,'resultado':'TAKE PROFIT'})
                en_posicion = False
                capital_historico.append(capital)
                continue

            venta = (rsi > RSI_VENTA and ema20 < ema50 and macd < macd_signal)
            venta_alt = (precio >= bb_upper * 0.999 and rsi > 58)

            if venta or venta_alt:
                ganancia = (precio - precio_entrada) * cantidad - abs((precio - precio_entrada) * cantidad) * COMISION
                capital += ganancia
                trades.append({'fecha':fecha,'tipo':'SELL','precio':precio,'ganancia':ganancia,'capital':capital,'resultado':'WIN' if ganancia > 0 else 'LOSS'})
                en_posicion = False
                capital_historico.append(capital)

        else:
            tendencia_ok = precio > ema200 * 0.98  # Cerca o encima de EMA200

            compra = (rsi < RSI_COMPRA and ema20 > ema50 and macd > macd_signal and tendencia_ok)
            compra_alt = (precio <= bb_lower * 1.003 and rsi < 42 and prev_rsi < rsi and tendencia_ok)

            if compra or compra_alt:
                capital_en_trade = capital * 0.95
                cantidad = capital_en_trade / precio
                precio_entrada = precio
                sl_precio = precio * (1 - STOP_LOSS)
                tp_precio = precio * (1 + TAKE_PROFIT)
                en_posicion = True
                trades.append({'fecha':fecha,'tipo':'BUY','precio':precio,'ganancia':0,'capital':capital,'resultado':'ENTRADA'})

    if en_posicion:
        precio_final = df['close'].iloc[-1]
        ganancia = (precio_final - precio_entrada) * cantidad - abs((precio_final - precio_entrada) * cantidad) * COMISION
        capital += ganancia
        trades.append({'fecha':df['time'].iloc[-1],'tipo':'SELL_FINAL','precio':precio_final,'ganancia':ganancia,'capital':capital,'resultado':'WIN' if ganancia > 0 else 'LOSS'})

    return trades, capital, capital_historico

# ═══════════════════════════════
# ANÁLISIS
# ═══════════════════════════════
def analizar_resultados(trades, capital_inicial, capital_final, symbol):
    if not trades:
        return None

    cerrados = [t for t in trades if t['tipo'] in ['SELL','SELL_SL','SELL_TP','SELL_FINAL']]
    if not cerrados:
        return None

    wins = [t for t in cerrados if t['ganancia'] > 0]
    losses = [t for t in cerrados if t['ganancia'] <= 0]
    total = len(cerrados)
    wr = (len(wins)/total*100) if total > 0 else 0
    ganancia_total = capital_final - capital_inicial
    retorno_pct = ganancia_total / capital_inicial * 100
    gp = np.mean([t['ganancia'] for t in wins]) if wins else 0
    pp = np.mean([t['ganancia'] for t in losses]) if losses else 0
    sl = len([t for t in cerrados if t['tipo']=='SELL_SL'])
    tp = len([t for t in cerrados if t['tipo']=='SELL_TP'])
    sw = sum(t['ganancia'] for t in wins)
    sl_sum = abs(sum(t['ganancia'] for t in losses))
    pf = sw/sl_sum if sl_sum > 0 else float('inf')

    caps = [t['capital'] for t in cerrados]
    peak = capital_inicial
    max_dd = 0
    for c in caps:
        if c > peak: peak = c
        dd = (peak-c)/peak*100
        if dd > max_dd: max_dd = dd

    ratio_gp = abs(gp/pp) if pp != 0 else float('inf')

    print(f"\n  {'─'*50}")
    print(f"  📊 RESULTADOS {symbol} — {MESES} meses")
    print(f"  {'─'*50}")
    print(f"  💰 Capital inicial:     ${capital_inicial:,.2f}")
    print(f"  💰 Capital final:       ${capital_final:,.2f}")
    print(f"  📈 Ganancia/Pérdida:    ${ganancia_total:+,.2f} ({retorno_pct:+.1f}%)")
    print(f"  📉 Max Drawdown:        {max_dd:.1f}%")
    print(f"  {'─'*50}")
    print(f"  🎯 Total trades:        {total}")
    print(f"  ✅ Wins:                {len(wins)} ({wr:.1f}%)")
    print(f"  ❌ Losses:              {len(losses)} ({100-wr:.1f}%)")
    print(f"  🛑 Stop losses:         {sl}")
    print(f"  🎯 Take profits:        {tp}")
    print(f"  {'─'*50}")
    print(f"  📊 Win rate:            {wr:.1f}%")
    print(f"  💵 Ganancia promedio:   ${gp:+,.2f}")
    print(f"  💸 Pérdida promedio:    ${pp:+,.2f}")
    print(f"  ⚖️  Ratio G/P:           {ratio_gp:.2f}")
    print(f"  ⚡ Profit factor:       {pf:.2f}")
    print(f"  {'─'*50}")

    return {'symbol':symbol,'capital_final':capital_final,'ganancia':ganancia_total,'retorno_pct':retorno_pct,'total_trades':total,'win_rate':wr,'profit_factor':pf,'max_drawdown':max_dd}

# ═══════════════════════════════
# MAIN
# ═══════════════════════════════
def main():
    print("\n" + "═"*60)
    print("  🤖 AutoTrader — Backtesting Engine v4.0")
    print(f"  Período: {MESES} meses | Capital: ${CAPITAL_INICIAL:,}")
    print(f"  Stop Loss: {STOP_LOSS*100}% | Take Profit: {TAKE_PROFIT*100}%")
    print(f"  RSI Compra: <{RSI_COMPRA} | RSI Venta: >{RSI_VENTA}")
    print(f"  Filtro EMA200: activo (no opera en tendencia bajista)")
    print(f"  ⚠️  Solo lectura — no ejecuta trades reales")
    print("═"*60)

    resultados = []

    for symbol in SYMBOLS:
        print(f"\n🔍 Analizando {symbol}...")
        df = get_historical_data(symbol, MESES)
        if df is None:
            continue
        trades, capital_final, hist = backtest(df, symbol, CAPITAL_INICIAL)
        r = analizar_resultados(trades, CAPITAL_INICIAL, capital_final, symbol)
        if r:
            resultados.append(r)
        time.sleep(1)

    if resultados:
        print("\n" + "═"*60)
        print("  📊 RESUMEN GENERAL")
        print("═"*60)

        wr_prom = np.mean([r['win_rate'] for r in resultados])
        ret_prom = np.mean([r['retorno_pct'] for r in resultados])
        dd_prom = np.mean([r['max_drawdown'] for r in resultados])
        trades_total = sum(r['total_trades'] for r in resultados)

        print(f"  Pares:                 {len(resultados)}")
        print(f"  Total trades:          {trades_total}")
        print(f"  Win rate promedio:     {wr_prom:.1f}%")
        print(f"  Retorno promedio:      {ret_prom:+.1f}%")
        print(f"  Max drawdown prom:     {dd_prom:.1f}%")
        print()

        for r in resultados:
            e = '✅' if r['ganancia'] > 0 else '❌'
            print(f"  {e} {r['symbol']}: {r['retorno_pct']:+.1f}% | WR: {r['win_rate']:.0f}% | {r['total_trades']} trades | DD: {r['max_drawdown']:.1f}%")

        print("\n" + "═"*60)
        print("  💡 VEREDICTO")
        print("═"*60)

        if wr_prom >= 55 and ret_prom > 8:
            print("  🏆 ESTRATEGIA EXCELENTE — Lista para producción")
        elif wr_prom >= 50 and ret_prom > 5:
            print("  ✅ ESTRATEGIA VIABLE — Buena para operar")
        elif ret_prom > 0:
            print("  ⚠️  ESTRATEGIA MARGINAL — Seguir optimizando")
        else:
            print("  ❌ ESTRATEGIA NO RENTABLE — Cambiar parámetros")

        print(f"\n  Parámetros usados: SL={STOP_LOSS*100}% | TP={TAKE_PROFIT*100}% | RSI<{RSI_COMPRA} | RSI>{RSI_VENTA}")
        print("═"*60)

if __name__ == "__main__":
    main()
