import time
import requests
from binance.client import Client
from binance.exceptions import BinanceAPIException
import pandas as pd
from supabase import create_client
from datetime import datetime

# ═══════════════════════════════
# CONFIGURACIÓN SUPABASE
# ═══════════════════════════════
SUPABASE_URL = 'https://hmpxnorawqppbxptbyeu.supabase.co'
SUPABASE_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhtcHhub3Jhd3FwcGJ4cHRieWV1Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzU2OTc4NDgsImV4cCI6MjA5MTI3Mzg0OH0.UFr_2zhs3qVcogiTTFaRlyAq8GbltXgAIT3EK2A0ses'

TELEGRAM_TOKEN = '8665046077:AAGTHlPz2FZQo_7A7f_l3x0xthWlTqrDvmo'

# Bot demo — keys del testnet para usuarios sin Binance configurado
DEMO_API_KEY = '07FaPPGK74wa3YTcfJKU0cDPhUQI65Uv9gUilG3kpjnYnnCRAoectjhPs06qHsEw'
DEMO_API_SECRET = 'rofqHXDzUcXRqSt8luc9zKtRnlMalKwEk09wdeaxjuVxDdVRsS39Lh86RUf3w97D'

INTERVALO = 300  # 5 minutos

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
def get_candles(client, symbol):
    candles = client.get_klines(
        symbol=symbol,
        interval=Client.KLINE_INTERVAL_5MINUTE,
        limit=100
    )
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
# GUARDAR TRADE EN SUPABASE
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
        print(f"    ✅ Trade guardado")

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
# OPERAR PARA UN USUARIO
# ═══════════════════════════════
def operar_usuario(config):
    user_id = config.get('user_id')
    api_key = config.get('api_key', '')
    api_secret = config.get('api_secret', '')
    capital = float(config.get('capital', 100))
    stop_loss = float(config.get('stop_loss', 1.5)) / 100
    take_profit = float(config.get('take_profit', 2.5)) / 100
    par = config.get('par', 'BTCUSDT')
    telegram_id = config.get('telegram_id', '')
    es_demo = not api_key or len(api_key) < 10

    # Conectar a Binance
    try:
        if es_demo:
            client = Client(DEMO_API_KEY, DEMO_API_SECRET, testnet=True)
            modo = "DEMO"
        else:
            client = Client(api_key, api_secret)
            modo = "REAL"
    except Exception as e:
        print(f"    ❌ Error conectando Binance para {user_id}: {e}")
        return

    # RSI personalizado según perfil
    try:
        perfil = supabase.table('perfiles').select('riesgo').eq('user_id', user_id).single().execute()
        riesgo = perfil.data.get('riesgo', 'medium') if perfil.data else 'medium'
    except:
        riesgo = 'medium'

    rsi_map = {'low': (35, 65), 'medium': (40, 60), 'high': (45, 55), 'extreme': (48, 52)}
    rsi_compra, rsi_venta = rsi_map.get(riesgo, (40, 60))

    print(f"  👤 Usuario {user_id[:8]}... | Modo: {modo} | Par: {par} | Capital: ${capital}")

    try:
        df = get_candles(client, par)
        senal, rsi, precio = obtener_senal(df, par, rsi_compra, rsi_venta)

        if senal == 'BUY':
            cantidad = round(capital / precio, 5)
            pnl = round(capital * take_profit, 2)
            stop = round(precio * (1 - stop_loss), 2)
            tp = round(precio * (1 + take_profit), 2)
            print(f"    🟢 COMPRANDO {cantidad} {par} a ${precio:,.2f}")
            print(f"       SL: ${stop:,.2f} | TP: ${tp:,.2f}")

            if not es_demo:
                try:
                    client.order_market_buy(symbol=par, quantity=cantidad)
                except BinanceAPIException as e:
                    print(f"    ⚠️ Error ejecutando orden real: {e}")

            guardar_trade(user_id, par, 'BUY', precio, cantidad, pnl, rsi, senal, telegram_id)

        elif senal == 'SELL':
            cantidad = round(capital / precio, 5)
            pnl = round(capital * take_profit * -0.4, 2)
            print(f"    🔴 VENDIENDO {cantidad} {par} a ${precio:,.2f}")

            if not es_demo:
                try:
                    client.order_market_sell(symbol=par, quantity=cantidad)
                except BinanceAPIException as e:
                    print(f"    ⚠️ Error ejecutando orden real: {e}")

            guardar_trade(user_id, par, 'SELL', precio, cantidad, pnl, rsi, senal, telegram_id)

        else:
            print(f"    ⏳ HOLD — sin señal")

    except Exception as e:
        print(f"    ❌ Error operando para {user_id[:8]}: {e}")

# ═══════════════════════════════
# OBTENER USUARIOS ACTIVOS
# ═══════════════════════════════
def get_usuarios_activos():
    try:
        result = supabase.table('configuraciones').select('*').execute()
        usuarios = result.data or []
        print(f"  📋 {len(usuarios)} usuario(s) con configuración")
        return usuarios
    except Exception as e:
        print(f"  ❌ Error obteniendo usuarios: {e}")
        return []

# ═══════════════════════════════
# DEMO — operar con cuenta demo
# para usuarios sin configuración
# ═══════════════════════════════
def operar_demo():
    """Opera el bot demo para mostrar en el dashboard a todos los usuarios"""
    demo_config = {
        'user_id': 'demo',
        'api_key': '',
        'api_secret': '',
        'capital': 100,
        'stop_loss': 1.5,
        'take_profit': 2.5,
        'par': 'BTCUSDT',
        'telegram_id': '5192044301'
    }

    symbols = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT']

    try:
        client = Client(DEMO_API_KEY, DEMO_API_SECRET, testnet=True)
        for symbol in symbols:
            try:
                df = get_candles(client, symbol)
                senal, rsi, precio = obtener_senal(df, symbol)

                if senal != 'HOLD':
                    cantidad = round(100 / precio, 5)
                    pnl = round(100 * 0.025, 2) if senal == 'BUY' else round(100 * 0.025 * -0.4, 2)
                    guardar_trade('demo', symbol, senal, precio, cantidad, pnl, rsi, senal, None)
                else:
                    print(f"    ⏳ {symbol}: HOLD")

            except Exception as e:
                print(f"    ❌ Error demo {symbol}: {e}")

    except Exception as e:
        print(f"  ❌ Error iniciando demo: {e}")

# ═══════════════════════════════
# LOOP PRINCIPAL
# ═══════════════════════════════
def main():
    print("\n" + "═"*60)
    print("  🤖 AutoTrader Bot Multi-Usuario v3.0 ACTUALIZADO")
    print(f"  {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print("═"*60)

    enviar_telegram('5192044301', """🤖 <b>AutoTrader Bot v3.0 iniciado</b>
Modo: Multi-usuario
Intervalo: 5 minutos
Estrategia: RSI + EMA + MACD""")

    while True:
        try:
            print(f"\n⏰ {datetime.now().strftime('%H:%M:%S')} — Analizando mercado...")
            print("─"*60)

            # 1. Operar bot demo (para todos los usuarios en trial)
            print("\n🎮 Bot demo:")
            operar_demo()

            # 2. Operar para usuarios con Binance configurado
            usuarios = get_usuarios_activos()
            if usuarios:
                print(f"\n👥 Usuarios con Binance real:")
                for config in usuarios:
                    if config.get('bot_activo'):
                        operar_usuario(config)
                    else:
                        print(f"  ⏸️  Usuario {config.get('user_id','')[:8]}... — bot pausado")

            print("\n" + "─"*60)
            print(f"⏳ Próximo análisis en {INTERVALO//60} minutos...")
            time.sleep(INTERVALO)

        except KeyboardInterrupt:
            print("\n🛑 Bot detenido manualmente")
            break
        except Exception as e:
            print(f"❌ Error general: {e}")
            time.sleep(30)

if __name__ == "__main__":
    main()
