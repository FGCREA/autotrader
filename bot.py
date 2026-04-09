import time
import requests
from binance.client import Client
import pandas as pd
from supabase import create_client

# ═══════════════════════════════
# CONFIGURACIÓN
# ═══════════════════════════════
API_KEY = '07FaPPGK74wa3YTcfJKU0cDPhUQI65Uv9gUilG3kpjnYnnCRAoectjhPs06qHsEw'
API_SECRET = 'rofqHXDzUcXRqSt8luc9zKtRnlMalKwEk09wdeaxjuVxDdVRsS39Lh86RUf3w97D'

SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT']  # Opera 3 pares
CAPITAL = 100
STOP_LOSS = 0.015
TAKE_PROFIT = 0.025
INTERVALO = 300  # 5 minutos

SUPABASE_URL = 'https://hmpxnorawqppbxptbyeu.supabase.co'
SUPABASE_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhtcHhub3Jhd3FwcGJ4cHRieWV1Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzU2OTc4NDgsImV4cCI6MjA5MTI3Mzg0OH0.UFr_2zhs3qVcogiTTFaRlyAq8GbltXgAIT3EK2A0ses'

TELEGRAM_TOKEN = '8665046077:AAGTHlPz2FZQo_7A7f_l3x0xthWlTqrDvmo'
TELEGRAM_CHAT_ID = '5192044301'

# ═══════════════════════════════
# CONEXIONES
# ═══════════════════════════════
client = Client(API_KEY, API_SECRET, testnet=True)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ═══════════════════════════════
# TELEGRAM
# ═══════════════════════════════
def enviar_telegram(mensaje):
    try:
        url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
        requests.post(url, data={
            'chat_id': TELEGRAM_CHAT_ID,
            'text': mensaje,
            'parse_mode': 'HTML'
        })
        print("📱 Telegram enviado")
    except Exception as e:
        print(f"❌ Error Telegram: {e}")

# ═══════════════════════════════
# OBTENER DATOS
# ═══════════════════════════════
def get_candles(symbol):
    candles = client.get_klines(
        symbol=symbol,
        interval=Client.KLINE_INTERVAL_5MINUTE,
        limit=100
    )
    df = pd.DataFrame(candles, columns=[
        'time','open','high','low','close','volume',
        'close_time','quote_vol','trades','buy_base',
        'buy_quote','ignore'
    ])
    df['close'] = pd.to_numeric(df['close'])
    df['high'] = pd.to_numeric(df['high'])
    df['low'] = pd.to_numeric(df['low'])
    df['volume'] = pd.to_numeric(df['volume'])
    return df

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
    upper = media + (std * 2)
    lower = media - (std * 2)
    return upper, media, lower

# ═══════════════════════════════
# GUARDAR TRADE
# ═══════════════════════════════
def guardar_trade(symbol, side, price, quantity, pnl, rsi, signal):
    try:
        supabase.table('trades').insert({
            'symbol': symbol,
            'side': side,
            'price': round(price, 2),
            'quantity': round(quantity, 5),
            'pnl': round(pnl, 2),
            'rsi': round(rsi, 2),
            'signal': signal
        }).execute()
        print(f"✅ Trade guardado en Supabase")

        emoji = '🟢' if side == 'BUY' else '🔴'
        msg = f"""{emoji} <b>AutoTrader — {side}</b>
Par: {symbol}
Precio: ${price:,.2f}
Cantidad: {quantity}
RSI: {rsi:.1f}
PnL estimado: ${pnl:.2f}
Estrategia: RSI + EMA + MACD"""
        enviar_telegram(msg)

    except Exception as e:
        print(f"❌ Error guardando: {e}")

# ═══════════════════════════════
# SEÑAL MEJORADA
# ═══════════════════════════════
def obtener_senal(df, symbol):
    rsi = calcular_rsi(df)
    ema20 = calcular_ema(df, 20)
    ema50 = calcular_ema(df, 50)
    macd, signal = calcular_macd(df)
    upper, media, lower = calcular_bollinger(df)

    ultimo_rsi = rsi.iloc[-1]
    prev_rsi = rsi.iloc[-2]
    ultimo_ema20 = ema20.iloc[-1]
    ultimo_ema50 = ema50.iloc[-1]
    ultimo_macd = macd.iloc[-1]
    ultimo_signal = signal.iloc[-1]
    ultimo_precio = df['close'].iloc[-1]
    ultimo_lower = lower.iloc[-1]
    ultimo_upper = upper.iloc[-1]

    print(f"[{symbol}] Precio: {ultimo_precio:.2f} | RSI: {ultimo_rsi:.1f} | MACD: {ultimo_macd:.2f} | EMA20: {ultimo_ema20:.2f} | EMA50: {ultimo_ema50:.2f}")

    # SEÑAL DE COMPRA — 3 condiciones (antes necesitaba 2)
    compra = (
        ultimo_rsi < 40 and                    # RSI sobrevendido
        ultimo_ema20 > ultimo_ema50 and         # Tendencia alcista
        ultimo_macd > ultimo_signal             # MACD confirma
    )

    # SEÑAL ALTERNATIVA DE COMPRA — precio toca banda inferior
    compra_alt = (
        ultimo_precio <= ultimo_lower * 1.002 and  # Precio cerca de banda inferior
        ultimo_rsi < 45 and                         # RSI bajo
        prev_rsi < ultimo_rsi                       # RSI subiendo
    )

    # SEÑAL DE VENTA
    venta = (
        ultimo_rsi > 60 and                    # RSI sobrecomprado
        ultimo_ema20 < ultimo_ema50 and         # Tendencia bajista
        ultimo_macd < ultimo_signal             # MACD confirma
    )

    # SEÑAL ALTERNATIVA DE VENTA — precio toca banda superior
    venta_alt = (
        ultimo_precio >= ultimo_upper * 0.998 and  # Precio cerca de banda superior
        ultimo_rsi > 55                             # RSI alto
    )

    if compra or compra_alt:
        return 'BUY', ultimo_rsi, ultimo_precio
    elif venta or venta_alt:
        return 'SELL', ultimo_rsi, ultimo_precio

    return 'HOLD', ultimo_rsi, ultimo_precio

# ═══════════════════════════════
# EJECUTAR TRADE
# ═══════════════════════════════
def ejecutar_trade(senal, precio, rsi, symbol):
    cantidad = round(CAPITAL / precio, 5)

    if senal == 'BUY':
        pnl = round(CAPITAL * TAKE_PROFIT, 2)
        stop = round(precio * (1 - STOP_LOSS), 2)
        tp = round(precio * (1 + TAKE_PROFIT), 2)
        print(f"🟢 COMPRANDO {cantidad} {symbol} a ${precio:,.2f}")
        print(f"   Stop Loss: ${stop:,.2f} | Take Profit: ${tp:,.2f}")
        guardar_trade(symbol, 'BUY', precio, cantidad, pnl, rsi, senal)

    elif senal == 'SELL':
        pnl = round(CAPITAL * TAKE_PROFIT * -0.5, 2)
        print(f"🔴 VENDIENDO {cantidad} {symbol} a ${precio:,.2f}")
        guardar_trade(symbol, 'SELL', precio, cantidad, pnl, rsi, senal)

# ═══════════════════════════════
# LOOP PRINCIPAL
# ═══════════════════════════════
def main():
    print("🤖 AutoTrader Bot v2.0 iniciado")
    print(f"Pares: {', '.join(SYMBOLS)}")
    print(f"Capital: ${CAPITAL} | Intervalo: {INTERVALO//60} min")
    print(f"Stop Loss: {STOP_LOSS*100}% | Take Profit: {TAKE_PROFIT*100}%")
    print("─" * 60)

    enviar_telegram("""🤖 <b>AutoTrader Bot v2.0 iniciado</b>
Pares: BTC, ETH, BNB
Estrategia: RSI + EMA + MACD + Bollinger
Intervalo: 5 minutos""")

    while True:
        try:
            print(f"\n⏰ {pd.Timestamp.now().strftime('%H:%M:%S')} — Analizando mercado...")

            for symbol in SYMBOLS:
                try:
                    df = get_candles(symbol)
                    senal, rsi, precio = obtener_senal(df, symbol)

                    if senal != 'HOLD':
                        ejecutar_trade(senal, precio, rsi, symbol)
                    else:
                        print(f"   ⏳ {symbol}: HOLD")

                except Exception as e:
                    print(f"❌ Error con {symbol}: {e}")

            print("─" * 60)
            time.sleep(INTERVALO)

        except Exception as e:
            print(f"❌ Error general: {e}")
            time.sleep(30)

if __name__ == "__main__":
    main()
