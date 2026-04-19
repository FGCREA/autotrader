import hmac
import hashlib
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from supabase import create_client
import requests
import threading

# ═══════════════════════════════
# CONFIGURACIÓN
# ═══════════════════════════════
SUPABASE_URL = 'https://hmpxnorawqppbxptbyeu.supabase.co'
SUPABASE_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhtcHhub3Jhd3FwcGJ4cHRieWV1Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzU2OTc4NDgsImV4cCI6MjA5MTI3Mzg0OH0.UFr_2zhs3qVcogiTTFaRlyAq8GbltXgAIT3EK2A0ses'

WEBHOOK_SECRET = 'autotrader2026secret'
TELEGRAM_TOKEN = '8665046077:AAGTHlPz2FZQo_7A7f_l3x0xthWlTqrDvmo'
ADMIN_TELEGRAM = '5192044301'

VARIANT_BASIC = '959101'
VARIANT_PRO = '959116'

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ═══════════════════════════════
# TELEGRAM
# ═══════════════════════════════
def enviar_telegram(chat_id, mensaje):
    try:
        url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
        requests.post(url, data={'chat_id': chat_id, 'text': mensaje, 'parse_mode': 'HTML'}, timeout=10)
    except Exception as e:
        print(f"❌ Error Telegram: {e}")

# ═══════════════════════════════
# VERIFICAR FIRMA
# ═══════════════════════════════
def verificar_firma(body, signature):
    expected = hmac.new(WEBHOOK_SECRET.encode('utf-8'), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)

# ═══════════════════════════════
# ACTUALIZAR PLAN EN SUPABASE
# ═══════════════════════════════
def actualizar_plan(email, plan, order_id):
    try:
        print(f"  📧 Procesando pago: {email} → {plan}")

        # Guardar pago en tabla pagos
        supabase.table('pagos').insert({
            'email': email,
            'plan': plan,
            'order_id': str(order_id),
            'estado': 'pendiente'
        }).execute()

        # Intentar actualizar perfil si ya existe el usuario
        perfiles = supabase.table('perfiles').select('user_id, plan').execute()
        for perfil in (perfiles.data or []):
            # Actualizar configuraciones también
            supabase.table('configuraciones').update({'plan': plan}).eq('user_id', perfil['user_id']).execute()
            supabase.table('perfiles').update({'plan': plan}).eq('user_id', perfil['user_id']).execute()

        print(f"  ✅ Pago registrado correctamente")

        enviar_telegram(ADMIN_TELEGRAM, f"""💰 <b>¡Nuevo pago!</b>
📧 Email: {email}
📦 Plan: {plan.upper()}
🔑 Order: {order_id}""")

        return True
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return False

# ═══════════════════════════════
# PROCESAR EVENTO
# ═══════════════════════════════
def procesar_evento(data):
    try:
        event = data.get('meta', {}).get('event_name', '')
        print(f"\n📨 Evento: {event}")

        if event in ['order_created', 'subscription_created', 'subscription_payment_success']:
            attrs = data.get('data', {}).get('attributes', {})
            email = attrs.get('user_email') or attrs.get('customer_email', '')
            variant_id = str(attrs.get('variant_id', '') or attrs.get('first_order_item', {}).get('variant_id', ''))
            order_id = data.get('data', {}).get('id', '')

            plan = 'pro' if variant_id == VARIANT_PRO else 'basic'
            print(f"  Email: {email} | Variant: {variant_id} | Plan: {plan}")
            actualizar_plan(email, plan, order_id)

        elif event == 'subscription_cancelled':
            email = data.get('data', {}).get('attributes', {}).get('user_email', '')
            enviar_telegram(ADMIN_TELEGRAM, f"⚠️ <b>Cancelación</b>\nEmail: {email}")

    except Exception as e:
        print(f"❌ Error: {e}")

# ═══════════════════════════════
# SERVIDOR HTTP
# ═══════════════════════════════
class WebhookHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{"status":"ok","service":"AutoTrader Webhook"}')

    def do_POST(self):
        if self.path == '/webhook':
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            signature = self.headers.get('X-Signature', '')

            if signature and not verificar_firma(body, signature):
                print("❌ Firma inválida")
                self.send_response(401)
                self.end_headers()
                return

            try:
                data = json.loads(body.decode('utf-8'))
                threading.Thread(target=procesar_evento, args=(data,)).start()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"received":true}')
            except Exception as e:
                print(f"❌ Error: {e}")
                self.send_response(400)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        print(f"🌐 {format % args}")

def iniciar_webhook(port=8000):
    server = HTTPServer(('0.0.0.0', port), WebhookHandler)
    print(f"🚀 Webhook corriendo en puerto {port}")
    server.serve_forever()

if __name__ == '__main__':
    iniciar_webhook()
