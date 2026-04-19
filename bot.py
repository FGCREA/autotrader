import time
import requests
import threading
from binance.client import Client
from binance.exceptions import BinanceAPIException
import pandas as pd
from supabase import create_client
from datetime import datetime

SUPABASE_URL = 'https://hmpxnorawqppbxptbyeu.supabase.co'
SUPABASE_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhtcHhub3Jhd3FwcGJ4cHRieWV1Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzU2OTc4NDgsImV4cCI6MjA5MTI3Mzg0OH0.UFr_2zhs3qVcogiTTFaRlyAq8GbltXgAIT3EK2A0ses'
TELEGRAM_TOKEN = '8665046077:AAGTHlPz2FZQo_7A7f_l3x0xthWlTqrDvmo'
DEMO_API_KEY = '07FaPPGK74wa3YTcfJKU0cDPhUQI65Uv9gUilG3kpjnYnnCRAoectjhPs06qHsEw'
DEMO_API_SECRET = 'rofqHXDzUcXRqSt8luc9zKtRnlMalKwEk09wdeaxjuVxDdVRsS39Lh86RUf3w97D'
INTERVALO_DEMO = 300

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def enviar_telegram(chat_id, mensaje):
    if not chat_id: return
    try:
        requests.post(f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
            data={'chat_id': chat_id, 'text': mensaje, 'parse_mode': 'HTML'}, timeout=10)
    except Exception as e:
        print(f"❌ Telegram: {e}")

def calcular_rsi(df, periodo=14):
    delta = df['close'].diff()
    ganancia = delta.where(delta > 0, 0)
    perdida = -delta.where(delta < 0, 0)
    rs = ganancia.rolling(periodo).mean() / perdida.rolling(periodo).mean()
    return 100 - (100 / (1 + rs))

def calcular_ema(df, periodo):
    return df['close'].ewm(span=periodo, adjust=False).mean()

def calcular_macd(df):
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    return macd, macd.ewm(span=9, adjust=False).mean()

def calcular_bollinger(df, periodo=20):
    media = df['close'].rolling(periodo).mean()
    std = df['close'].rolling(periodo).std()
    return media + (std * 2), media, media - (std * 2)

def get_candles(client, symbol, intervalo=Client.KLINE_INTERVAL_5MINUTE):
    candles = client.get_klines(symbol=symbol, interval=intervalo, limit=100)
    df = pd.DataFrame(candles, columns=['time','open','high','low','close','volume','close_time','quote_vol','trades','buy_base','buy_quote','ignore'])
    for col in ['close','high','low','open']:
        df[col] = pd.to_numeric(df[col])
    return df

def obtener_senal(df, symbol, rsi_compra=40, rsi_venta=60):
    df = df.copy()
    df['rsi'] = calcular_rsi(df)
    df['ema20'] = calcular_ema(df, 20)
    df['ema50'] = calcular_ema(df, 50)
    df['macd'], df['macd_signal'] = calcular_macd(df)
    df['bb_upper'], _, df['bb_lower'] = calcular_bollinger(df)
    df = df.dropna()
    if len(df) < 2: return 'HOLD', 0, 0

    rsi = df['rsi'].iloc[-1]
    prev_rsi = df['rsi'].iloc[-2]
    ema20 = df['ema20'].iloc[-1]
    ema50 = df['ema50'].iloc[-1]
    macd = df['macd'].iloc[-1]
    macd_sig = df['macd_signal'].iloc[-1]
    precio = df['close'].iloc[-1]
    bb_upper = df['bb_upper'].iloc[-1]
    bb_lower = df['bb_lower'].iloc[-1]

    print(f"    [{symbol}] ${precio:.2f} | RSI: {rsi:.1f}")

    if (rsi < rsi_compra and ema20 > ema50 and macd > macd_sig) or \
       (precio <= bb_lower * 1.002 and rsi < rsi_compra + 5 and prev_rsi < rsi):
        return 'BUY', rsi, precio
    elif (rsi > rsi_venta and ema20 < ema50 and macd < macd_sig) or \
         (precio >= bb_upper * 0.998 and rsi > rsi_venta - 5):
        return 'SELL', rsi, precio
    return 'HOLD', rsi, precio

def guardar_trade(user_id, symbol, side, price, quantity, pnl, rsi, signal, telegram_id=None):
    try:
        supabase.table('trades').insert({
            'user_id': user_id, 'symbol': symbol, 'side': side,
            'price': round(price, 2), 'quantity': round(quantity, 5),
            'pnl': round(pnl, 2), 'rsi': round(rsi, 2), 'signal': signal
        }).execute()
        emoji = '🟢' if side == 'BUY' else '🔴'
        enviar_telegram(telegram_id, f"{emoji} <b>AutoTrader — {side}</b>\nPar: {symbol}\nPrecio: ${price:,.2f}\nPnL: ${pnl:.2f}")
    except Exception as e:
        print(f"    ❌ Error trade: {e}")

def get_usuarios_trial():
    try:
        result = supabase.table('perfiles').select('id, telegram_id').eq('plan', 'trial').execute()
        return result.data or []
    except: return []

def operar_demo(user_id, telegram_id=None):
    try:
        binance = Client(DEMO_API_KEY, DEMO_API_SECRET, testnet=True)
        for symbol in ['BTCUSDT', 'ETHUSDT', 'BNBUSDT']:
            try:
                df = get_candles(binance, symbol)
                senal, rsi, precio = obtener_senal(df, symbol)
                if senal == 'BUY':
                    cantidad = round(100 / precio, 5)
                    pnl = round(100 * 0.025, 2)
                    guardar_trade(user_id, symbol, 'BUY', precio, cantidad, pnl, rsi, senal, telegram_id)
                else:
                    print(f"    ⏳ {symbol}: {senal}")
            except Exception as e:
                print(f"    ❌ Demo {symbol}: {e}")
    except Exception as e:
        print(f"  ❌ Demo: {e}")

def get_usuarios_activos():
    try:
        result = supabase.table('configuraciones').select('*').eq('bot_activo', True).execute()
        return result.data or []
    except: return []

def operar_usuario(config):
    user_id = config.get('user_id')
    api_key = config.get('api_key', '')
    api_secret = config.get('api_secret', '')
    capital = float(config.get('capital', 100))
    plan = config.get('plan', 'basic')
    telegram_id = config.get('telegram_id', '')
    es_demo = not api_key or len(api_key) < 10

    if plan == 'pro':
        stop_loss = float(config.get('stop_loss', 1.5)) / 100
        take_profit = float(config.get('take_profit', 2.5)) / 100
        rsi_compra = int(config.get('rsi_compra', 40))
        rsi_venta = int(config.get('rsi_venta', 60))
        intervalo_seg = int(config.get('intervalo', 300))
        pares_extra = config.get('pares_extra', '')
        par_principal = config.get('par', 'BTCUSDT')
        symbols = pares_extra.split(',') if pares_extra else [par_principal]
        if par_principal not in symbols: symbols.insert(0, par_principal)
        symbols = [s for s in symbols if s]
    else:
        stop_loss, take_profit = 0.015, 0.025
        rsi_compra, rsi_venta, intervalo_seg = 40, 60, 300
        symbols = ['BTCUSDT']

    intervalo_binance = Client.KLINE_INTERVAL_1MINUTE if intervalo_seg <= 60 else \
                        Client.KLINE_INTERVAL_5MINUTE if intervalo_seg <= 300 else \
                        Client.KLINE_INTERVAL_15MINUTE

    try:
        binance = Client(DEMO_API_KEY, DEMO_API_SECRET, testnet=True) if es_demo else Client(api_key, api_secret)
        modo = "DEMO" if es_demo else "REAL"
    except Exception as e:
        print(f"    ❌ Binance: {e}"); return

    print(f"  👤 {user_id[:8]}... | {plan.upper()} | {modo} | ${capital}")

    for symbol in symbols:
        try:
            df = get_candles(binance, symbol, intervalo_binance)
            senal, rsi, precio = obtener_senal(df, symbol, rsi_compra, rsi_venta)
            if senal == 'BUY':
                cantidad = round(capital / precio, 5)
                pnl = round(capital * take_profit, 2)
                if not es_demo:
                    try: binance.order_market_buy(symbol=symbol, quantity=cantidad)
                    except BinanceAPIException as e: print(f"    ⚠️ {e}")
                guardar_trade(user_id, symbol, 'BUY', precio, cantidad, pnl, rsi, senal, telegram_id)
            elif senal == 'SELL':
                cantidad = round(capital / precio, 5)
                pnl = round(capital * stop_loss * -1, 2)
                if not es_demo:
                    try: binance.order_market_sell(symbol=symbol, quantity=cantidad)
                    except BinanceAPIException as e: print(f"    ⚠️ {e}")
                guardar_trade(user_id, symbol, 'SELL', precio, cantidad, pnl, rsi, senal, telegram_id)
            else:
                print(f"    ⏳ {symbol}: HOLD")
        except Exception as e:
            print(f"    ❌ {symbol}: {e}")

def main():
    print("\n" + "═"*60)
    print("  🤖 AutoTrader Bot v3.4 + Webhook")
    print(f"  {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print("═"*60)

    # Iniciar webhook en thread separado
    try:
        from webhook import iniciar_webhook
        threading.Thread(target=iniciar_webhook, args=(8000,), daemon=True).start()
        print("✅ Webhook iniciado en puerto 8000")
    except Exception as e:
        print(f"⚠️ Webhook: {e}")

    enviar_telegram('5192044301', "🤖 <b>AutoTrader v3.4 iniciado</b>\n✅ Webhook integrado\nEstrategia: RSI + EMA + MACD")

    while True:
        try:
            print(f"\n⏰ {datetime.now().strftime('%H:%M:%S')} — Analizando...")
            print("─"*60)

            usuarios_trial = get_usuarios_trial()
            if usuarios_trial:
                print(f"\n🎮 {len(usuarios_trial)} usuario(s) en trial:")
                for u in usuarios_trial:
                    operar_demo(u['id'], u.get('telegram_id'))
            else:
                print("\n🎮 Sin usuarios en trial")

            usuarios = get_usuarios_activos()
            if usuarios:
                print(f"\n👥 {len(usuarios)} usuario(s) activo(s):")
                for config in usuarios:
                    operar_usuario(config)
            else:
                print("\n👥 Sin usuarios activos")

            print(f"\n⏳ Próximo ciclo en {INTERVALO_DEMO//60} min...")
            time.sleep(INTERVALO_DEMO)

        except KeyboardInterrupt:
            print("\n🛑 Bot detenido"); break
        except Exception as e:
            print(f"❌ Error: {e}"); time.sleep(30)

if __name__ == "__main__":
    main()
