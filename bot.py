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
SYMBOL = 'BTCUSDT'
CAPITAL = 100
STOP_LOSS = 0.015
TAKE_PROFIT = 0.03

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
        print("📱 Notificación enviada a Telegram")
    except Exception as e:
        print(f"❌ Error Telegram: {e}")

# ═══════════════════════════════
# OBTENER DATOS
# ═══════════════════════════════
def get_candles():
    candles = client.get_klines(
        symbol=SYMBOL,
        interval=Client.KLINE_INTERVAL_15MINUTE,
        limit=100
    )
    df = pd.DataFrame(candles, columns=[
        'time','open','high','low','close','volume',
        'close_time','quote_vol','trades','buy_base',
        'buy_quote','ignore'
    ])
    df['close'] = pd.to_numeric(df['close'])
    return df

# ═══════════════════════════════
# CALCULAR RSI
# ═══════════════════════════════
def calcular_rsi(df, periodo=14):
    delta = df['close'].diff()
    ganancia = delta.where(delta > 0, 0)
    perdida = -delta.where(delta < 0, 0)
    avg_ganancia = ganancia.rolling(periodo).mean()
    avg_perdida = perdida.rolling(periodo).mean()
    rs = avg_ganancia / avg_perdida
    return 100 - (100 / (1 + rs))

# ═══════════════════════════════
# CALCULAR EMA
# ═══════════════════════════════
def calcular_ema(df, periodo):
    return df['close'].ewm(span=periodo, adjust=False).mean()

# ═══════════════════════════════
# GUARDAR EN SUPABASE + TELEGRAM
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
        print("✅ Trade guardado en Supabase")

        emoji = '🟢' if side == 'BUY' else '🔴'
        mensaje = f"""{emoji} <b>AutoTrader — {side}</b>
Par: {symbol}
Precio: ${price:.2f}
Cantidad: {quantity}
RSI: {rsi:.1f}
PnL estimado: ${pnl:.2f}"""
        enviar_telegram(mensaje)

    except Exception as e:
        print(f"❌ Error guardando trade: {e}")

# ═══════════════════════════════
# SEÑAL DE TRADING
# ═══════════════════════════════
def obtener_senal(df):
    rsi = calcular_rsi(df)
    ema20 = calcular_ema(df, 20)
    ema50 = calcular_ema(df, 50)

    ultimo_rsi = rsi.iloc[-1]
    ultimo_ema20 = ema20.iloc[-1]
    ultimo_ema50 = ema50.iloc[-1]
    ultimo_precio = df['close'].iloc[-1]

    print(f"Precio: {ultimo_precio:.2f} | RSI: {ultimo_rsi:.1f} | EMA20: {ultimo_ema20:.2f} | EMA50: {ultimo_ema50:.2f}")

    if ultimo_rsi < 35 and ultimo_ema20 > ultimo_ema50:
        return 'BUY', ultimo_rsi, ultimo_precio
    elif ultimo_rsi > 65 and ultimo_ema20 < ultimo_ema50:
        return 'SELL', ultimo_rsi, ultimo_precio

    return 'HOLD', ultimo_rsi, ultimo_precio

# ═══════════════════════════════
# EJECUTAR TRADE
# ═══════════════════════════════
def ejecutar_trade(senal, precio, rsi):
    cantidad = round(CAPITAL / precio, 5)

    if senal == 'BUY':
        pnl = round(CAPITAL * TAKE_PROFIT, 2)
        stop = round(precio * (1 - STOP_LOSS), 2)
        tp = round(precio * (1 + TAKE_PROFIT), 2)
        print(f"🟢 COMPRANDO {cantidad} BTC a ${precio:.2f}")
        print(f"   Stop Loss: ${stop} | Take Profit: ${tp}")
        guardar_trade(SYMBOL, 'BUY', precio, cantidad, pnl, rsi, senal)

    elif senal == 'SELL':
        pnl = round(CAPITAL * TAKE_PROFIT * -1, 2)
        print(f"🔴 VENDIENDO {cantidad} BTC a ${precio:.2f}")
        guardar_trade(SYMBOL, 'SELL', precio, cantidad, pnl, rsi, senal)

# ═══════════════════════════════
# LOOP PRINCIPAL
# ═══════════════════════════════
def main():
    print("🤖 AutoTrader Bot iniciado")
    print(f"Par: {SYMBOL} | Capital: ${CAPITAL}")
    print("─" * 50)

    enviar_telegram("🤖 <b>AutoTrader Bot iniciado</b>\nAnalizando mercado en tiempo real...")

    while True:
        try:
            df = get_candles()
            senal, rsi, precio = obtener_senal(df)

            if senal != 'HOLD':
                ejecutar_trade(senal, precio, rsi)
            else:
                print("⏳ HOLD — sin señal clara")

            print("─" * 50)
            time.sleep(60)

        except Exception as e:
            print(f"❌ Error: {e}")
            time.sleep(30)

if __name__ == "__main__":
    main()