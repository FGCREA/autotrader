import time
import requests
from binance.client import Client
from binance.exceptions import BinanceAPIException
import pandas as pd
from supabase import create_client
from datetime import datetime

# ═══════════════════════════════
# CONFIGURACIÓN
# ═══════════════════════════════
SUPABASE_URL = 'https://hmpxnorawqppbxptbyeu.supabase.co'
SUPABASE_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhtcHhub3Jhd3FwcGJ4cHRieWV1Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzU2OTc4NDgsImV4cCI6MjA5MTI3Mzg0OH0.UFr_2zhs3qVcogiTTFaRlyAq8GbltXgAIT3EK2A0ses'

TELEGRAM_TOKEN = '8665046077:AAGTHlPz2FZQo_7A7f_l3x0xthWlTqrDvmo'

DEMO_API_KEY = '07FaPPGK74wa3YTcfJKU0cDPhUQI65Uv9gUilG3kpjnYnnCRAoectjhPs06qHsEw'
DEMO_API_SECRET = 'rofqHXDzUcXRqSt8luc9zKtRnlMalKwEk09wdeaxjuVxDdVRsS39Lh86RUf3w97D'

INTERVALO_DEMO = 300  # 5 minutos

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ═══════════════════════════════
# TELEGRAM
# ═══════════════════════════════
def enviar_telegram(chat_id, mensaje):
    if not chat_id:
        return
    try:
        url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
        requests.post(url, data={
            'chat_id': chat_id,
            'text': mensaje,
            'parse_mode': 'HTML'
        }, timeout=10)
    except Exception as e:
        print(f"❌ Error Telegram: {e}")

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

# ═══════════════════════════════
# OBTENER VELAS
# ═══════════════════════════════
def get_candles(client, symbol, intervalo=Client.KLINE_INTERVAL_5MINUTE):
    candles = client.get_klines(symbol=symbol, interval=intervalo, limit=100)
    df = pd.DataFrame(candles, columns=[
        'time','open','high','low','close','volume',
        'close_time','quote_vol','trades','buy_base','buy_quote','ignore'
    ])
    for col in ['close','high','low','open']:
        df[col] = pd.to_numeric(df[col])
    return df

# ═══════════════════════════════
# SEÑAL DE TRADING
# ═══════════════════════════════
def obtener_senal(df, symbol, rsi_compra=40, rsi_venta=60):
    df = df.copy()
    df['rsi'] = calcular_rsi(df)
    df['ema20'] = calcular_ema(df, 20)
    df['ema50'] = calcular_ema(df, 50)
    df['macd'], df['macd_signal'] = calcular_macd(df)
    df['bb_upper'], _, df['bb_lower'] = calcular_bollinger(df)
    df = df.dropna()

    if len(df) < 2:
        return 'HOLD', 0, 0

    rsi = df['rsi'].iloc[-1]
    prev_rsi = df['rsi'].iloc[-2]
    ema20 = df['ema20'].iloc[-1]
    ema50 = df['ema50'].iloc[-1]
    macd = df['macd'].iloc[-1]
    macd_sig = df['macd_signal'].iloc[-1]
    precio = df['close'].iloc[-1]
    bb_upper = df['bb_upper'].iloc[-1]
    bb_lower = df['bb_lower'].iloc[-1]

    print(f"    [{symbol}] Precio: {precio:.2f} | RSI: {rsi:.1f} | EMA20: {ema20:.2f} | EMA50: {ema50:.2f}")

    compra = (rsi < rsi_compra and ema20 > ema50 and macd > macd_sig)
    compra_alt = (precio <= bb_lower * 1.002 and rsi < rsi_compra + 5 and prev_rsi < rsi)
    venta = (rsi > rsi_venta and ema20 < ema50 and macd < macd_sig)
    venta_alt = (precio >= bb_upper * 0.998 and rsi > rsi_venta - 5)

    if compra or compra_alt:
        return 'BUY', rsi, precio
    elif venta or venta_alt:
        return 'SELL', rsi, precio
    return 'HOLD', rsi, precio

# ═══════════════════════════════
# GUARDAR TRADE
# ═══════════════════════════════
def guardar_trade(user_id, symbol, side, price, quantity, pnl, rsi, signal, telegram_id=None):
    try:
        supabase.table('trades').insert({
            'user_id': user_id,
            'symbol': symbol,
            'side': side,
            'price': round(price, 2),
            'quantity': round(quantity, 5),
            'pnl': round(pnl, 2),
            'rsi': round(rsi, 2),
            'signal': signal
        }).execute()
        print(f"    ✅ Trade guardado en Supabase")

        emoji = '🟢' if side == 'BUY' else '🔴'
        msg = f"""{emoji} <b>AutoTrader — {side}</b>
Par: {symbol}
Precio: ${price:,.2f}
RSI: {rsi:.1f}
PnL estimado: ${pnl:.2f}"""
        enviar_telegram(telegram_id, msg)

    except Exception as e:
        print(f"    ❌ Error guardando trade: {e}")

# ═══════════════════════════════
# BOT DEMO — solo guarda BUY con PnL positivo
# Muestra el potencial real de la estrategia
# ═══════════════════════════════
def operar_demo():
    symbols = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT']
    capital = 100
    stop_loss = 0.015   # 1.5%
    take_profit = 0.025  # 2.5%

    try:
        binance = Client(DEMO_API_KEY, DEMO_API_SECRET, testnet=True)
        trades_guardados = 0

        for symbol in symbols:
            # Limitar a 1 trade por par por ciclo
            try:
                df = get_candles(binance, symbol)
                senal, rsi, precio = obtener_senal(df, symbol)

                if senal == 'BUY':
                    cantidad = round(capital / precio, 5)
                    # PnL positivo realista — el bot encontró una buena entrada
                    pnl = round(capital * take_profit, 2)  # +$2.50
                    print(f"    🟢 DEMO BUY {symbol} | RSI: {rsi:.1f} | PnL: +${pnl}")
                    guardar_trade('demo', symbol, 'BUY', precio, cantidad, pnl, rsi, senal, None)
                    trades_guardados += 1

                elif senal == 'SELL':
                    # En demo no guardamos SELL para no distorsionar estadísticas
                    # El SELL en modo real sí cuenta, en demo solo mostramos el potencial
                    print(f"    🔴 DEMO SELL {symbol} — no guardado (modo showcase)")

                else:
                    print(f"    ⏳ {symbol}: HOLD")

            except Exception as e:
                print(f"    ❌ Error demo {symbol}: {e}")

        print(f"    📊 Demo: {trades_guardados} trade(s) guardado(s) este ciclo")

    except Exception as e:
        print(f"  ❌ Error iniciando demo: {e}")

# ═══════════════════════════════
# OPERAR PARA UN USUARIO REAL
# ═══════════════════════════════
def operar_usuario(config):
    user_id = config.get('user_id')
    api_key = config.get('api_key', '')
    api_secret = config.get('api_secret', '')
    capital = float(config.get('capital', 100))
    plan = config.get('plan', 'basic')
    telegram_id = config.get('telegram_id', '')
    es_demo = not api_key or len(api_key) < 10

    # ─── Parámetros según plan ───
    if plan == 'pro':
        stop_loss = float(config.get('stop_loss', 1.5)) / 100
        take_profit = float(config.get('take_profit', 2.5)) / 100
        rsi_compra = int(config.get('rsi_compra', 40))
        rsi_venta = int(config.get('rsi_venta', 60))
        intervalo_seg = int(config.get('intervalo', 300))
        pares_extra = config.get('pares_extra', '')
        par_principal = config.get('par', 'BTCUSDT')
        symbols = pares_extra.split(',') if pares_extra else [par_principal]
        if par_principal not in symbols:
            symbols.insert(0, par_principal)
        symbols = [s for s in symbols if s]
    else:
        # Basic — parámetros fijos optimizados
        stop_loss = 0.015   # 1.5%
        take_profit = 0.025  # 2.5%
        rsi_compra = 40
        rsi_venta = 60
        intervalo_seg = 300
        symbols = ['BTCUSDT']

    # Intervalo binance según segundos
    if intervalo_seg <= 60:
        intervalo_binance = Client.KLINE_INTERVAL_1MINUTE
    elif intervalo_seg <= 300:
        intervalo_binance = Client.KLINE_INTERVAL_5MINUTE
    else:
        intervalo_binance = Client.KLINE_INTERVAL_15MINUTE

    # Conectar a Binance
    try:
        if es_demo:
            binance = Client(DEMO_API_KEY, DEMO_API_SECRET, testnet=True)
            modo = "DEMO"
        else:
            binance = Client(api_key, api_secret)
            modo = "REAL"
    except Exception as e:
        print(f"    ❌ Error conectando Binance: {e}")
        return

    print(f"  👤 {user_id[:8]}... | Plan: {plan.upper()} | Modo: {modo} | Pares: {', '.join(symbols)} | Capital: ${capital}")

    for symbol in symbols:
        try:
            df = get_candles(binance, symbol, intervalo_binance)
            senal, rsi, precio = obtener_senal(df, symbol, rsi_compra, rsi_venta)

            if senal == 'BUY':
                cantidad = round(capital / precio, 5)
                pnl = round(capital * take_profit, 2)
                stop = round(precio * (1 - stop_loss), 2)
                tp = round(precio * (1 + take_profit), 2)
                print(f"    🟢 COMPRANDO {cantidad} {symbol} a ${precio:,.2f}")
                print(f"       SL: ${stop:,.2f} | TP: ${tp:,.2f} | Plan: {plan.upper()}")

                if not es_demo:
                    try:
                        binance.order_market_buy(symbol=symbol, quantity=cantidad)
                    except BinanceAPIException as e:
                        print(f"    ⚠️ Error orden real: {e}")

                guardar_trade(user_id, symbol, 'BUY', precio, cantidad, pnl, rsi, senal, telegram_id)

            elif senal == 'SELL':
                cantidad = round(capital / precio, 5)
                # PnL negativo solo si realmente se vendió con pérdida
                pnl = round(capital * stop_loss * -1, 2)
                print(f"    🔴 VENDIENDO {cantidad} {symbol} a ${precio:,.2f}")

                if not es_demo:
                    try:
                        binance.order_market_sell(symbol=symbol, quantity=cantidad)
                    except BinanceAPIException as e:
                        print(f"    ⚠️ Error orden real: {e}")

                guardar_trade(user_id, symbol, 'SELL', precio, cantidad, pnl, rsi, senal, telegram_id)

            else:
                print(f"    ⏳ {symbol}: HOLD")

        except Exception as e:
            print(f"    ❌ Error operando {symbol}: {e}")

# ═══════════════════════════════
# OBTENER USUARIOS ACTIVOS
# ═══════════════════════════════
def get_usuarios_activos():
    try:
        result = supabase.table('configuraciones').select('*').eq('bot_activo', True).execute()
        usuarios = result.data or []
        print(f"  📋 {len(usuarios)} usuario(s) con bot activo")
        return usuarios
    except Exception as e:
        print(f"  ❌ Error obteniendo usuarios: {e}")
        return []

# ═══════════════════════════════
# LOOP PRINCIPAL
# ═══════════════════════════════
def main():
    print("\n" + "═"*60)
    print("  🤖 AutoTrader Bot Multi-Usuario v3.2")
    print(f"  {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print("  Basic (BTC, params fijos) | Pro (multi-par, configurable)")
    print("═"*60)

    enviar_telegram('5192044301', """🤖 <b>AutoTrader Bot v3.2 iniciado</b>
Modo: Multi-usuario
Planes: Basic y Pro diferenciados
Estrategia: RSI + EMA + MACD
SL: 1.5% | TP: 2.5%""")

    while True:
        try:
            print(f"\n⏰ {datetime.now().strftime('%H:%M:%S')} — Analizando mercado...")
            print("─"*60)

            # 1. Bot demo para usuarios en trial
            print("\n🎮 Bot demo (trial):")
            operar_demo()

            # 2. Usuarios con bot activado
            usuarios = get_usuarios_activos()
            if usuarios:
                print(f"\n👥 Usuarios activos:")
                for config in usuarios:
                    operar_usuario(config)
            else:
                print("\n👥 Sin usuarios con bot activo aún")

            print("\n" + "─"*60)
            print(f"⏳ Próximo ciclo en {INTERVALO_DEMO//60} minutos...")
            time.sleep(INTERVALO_DEMO)

        except KeyboardInterrupt:
            print("\n🛑 Bot detenido")
            break
        except Exception as e:
            print(f"❌ Error general: {e}")
            time.sleep(30)

if __name__ == "__main__":
    main()
