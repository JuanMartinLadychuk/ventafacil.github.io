import os
import json
import logging
from datetime import datetime, timedelta

from flask import Flask, request, jsonify
import psycopg2
import requests

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

DATABASE_URL = os.environ.get("DATABASE_URL")
CLIENT_ID = os.environ.get("ML_CLIENT_ID")
CLIENT_SECRET = os.environ.get("ML_CLIENT_SECRET")
REDIRECT_URI = "https://ventafacil-goio.onrender.com/oauth/callback"


def get_connection():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    if not DATABASE_URL:
        logging.warning("DATABASE_URL no configurada, se omite init_db")
        return
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ml_notifications (
            id SERIAL PRIMARY KEY,
            resource TEXT,
            topic TEXT,
            user_id TEXT,
            application_id TEXT,
            attempts INTEGER,
            sent DATE,
            received DATE,
            raw_payload JSONB,
            processed BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    conn.commit()
    cur.close()
    conn.close()


def init_tokens_table():
    if not DATABASE_URL:
        return
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ml_tokens (
            id SERIAL PRIMARY KEY,
            ml_user_id VARCHAR(50),
            nickname VARCHAR(150),
            access_token TEXT,
            refresh_token TEXT,
            expires_in INTEGER,
            expires_at TIMESTAMP,
            site_id VARCHAR(10),
            active SMALLINT DEFAULT 1,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)
    conn.commit()
    cur.close()
    conn.close()


# ---------------------------------------------------------------------------
# Diseño compartido de las páginas HTML (login / resultado de autorización)
# ---------------------------------------------------------------------------

def _pagina(titulo, cuerpo_html, tono="info"):
    colores = {
        "info": "#3d5a66",
        "success": "#2e7d32",
        "error": "#b3261e",
    }
    color_acento = colores.get(tono, colores["info"])
    return f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>VentaFacil — {titulo}</title>
        <style>
            * {{ box-sizing: border-box; }}
            body {{
                margin: 0;
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                background: #17262c;
                font-family: -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
                color: #e8edf0;
            }}
            .tarjeta {{
                background: #21343c;
                border-radius: 16px;
                padding: 40px 36px;
                max-width: 420px;
                width: 90%;
                text-align: center;
                box-shadow: 0 10px 30px rgba(0,0,0,0.35);
                border-top: 4px solid {color_acento};
            }}
            .logo {{
                font-size: 22px;
                font-weight: 700;
                letter-spacing: 0.5px;
                margin-bottom: 4px;
                color: #ffffff;
            }}
            .subtitulo {{
                font-size: 13px;
                color: #93a5ad;
                margin-bottom: 24px;
            }}
            h1 {{
                font-size: 19px;
                font-weight: 600;
                margin: 0 0 12px 0;
                color: #ffffff;
            }}
            p {{
                font-size: 14px;
                line-height: 1.5;
                color: #c3d0d4;
                margin: 0 0 24px 0;
            }}
            a.boton {{
                display: inline-block;
                background: {color_acento};
                color: #ffffff;
                text-decoration: none;
                font-weight: 600;
                font-size: 14px;
                padding: 12px 28px;
                border-radius: 8px;
                transition: opacity 0.15s;
            }}
            a.boton:hover {{ opacity: 0.85; }}
            .icono {{
                font-size: 40px;
                margin-bottom: 12px;
            }}
        </style>
    </head>
    <body>
        <div class="tarjeta">
            <div class="logo">VentaFacil</div>
            <div class="subtitulo">Integración con Mercado Libre</div>
            {cuerpo_html}
        </div>
    </body>
    </html>
    """


# ---------------------------------------------------------------------------
# Webhook de notificaciones de Mercado Libre
# ---------------------------------------------------------------------------

@app.route("/ml/webhook", methods=["POST"])
def ml_webhook():
    payload = request.get_json(silent=True) or {}
    logging.info("Notificacion ML recibida: %s", payload)

    try:
        if DATABASE_URL:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO ml_notifications
                (resource, topic, user_id, application_id, attempts, sent, received, raw_payload)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    payload.get("resource"),
                    payload.get("topic"),
                    str(payload.get("user_id")),
                    str(payload.get("application_id")),
                    payload.get("attempts"),
                    payload.get("sent"),
                    payload.get("received"),
                    json.dumps(payload),
                ),
            )
            conn.commit()
            cur.close()
            conn.close()
    except Exception as e:
        logging.error("Error guardando notificacion: %s", e)
        return jsonify({"status": "error_logged"}), 200

    return jsonify({"status": "ok"}), 200


@app.route("/ml/webhook", methods=["GET"])
def ml_webhook_check():
    return jsonify({"status": "alive"}), 200


# ---------------------------------------------------------------------------
# OAuth con Mercado Libre
# ---------------------------------------------------------------------------

@app.route("/oauth/login", methods=["GET"])
def oauth_login():
    auth_url = (
        "https://auth.mercadolibre.com.ar/authorization"
        f"?response_type=code&client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
    )
    cuerpo = f"""
        <h1>Conectar con Mercado Libre</h1>
        <p>Vas a autorizar a VentaFacil a acceder a tu cuenta de Mercado Libre
        (catálogo, mensajes e imágenes). Podés desconectarla en cualquier
        momento desde la app.</p>
        <a class="boton" href="{auth_url}">Autorizar cuenta</a>
    """
    return _pagina("Conectar cuenta", cuerpo, tono="info"), 200


@app.route("/oauth/callback", methods=["GET"])
def oauth_callback():
    code = request.args.get("code")
    error = request.args.get("error")

    if error:
        logging.error("Error en OAuth callback: %s", error)
        cuerpo = f"""
            <div class="icono">⚠️</div>
            <h1>No se pudo autorizar</h1>
            <p>Mercado Libre devolvió un error: <strong>{error}</strong>.
            Volvé a la app e intentá conectar de nuevo.</p>
        """
        return _pagina("Error de autorización", cuerpo, tono="error"), 400

    if not code:
        cuerpo = """
            <div class="icono">⚠️</div>
            <h1>Falta información</h1>
            <p>No llegó el código de autorización. Volvé a intentar desde la app.</p>
        """
        return _pagina("Error de autorización", cuerpo, tono="error"), 400

    try:
        response = requests.post(
            "https://api.mercadolibre.com/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "code": code,
                "redirect_uri": REDIRECT_URI,
            },
        )
        response.raise_for_status()
        token_data = response.json()

        access_token = token_data["access_token"]
        refresh_token = token_data["refresh_token"]
        ml_user_id = str(token_data["user_id"])
        expires_in = token_data["expires_in"]

        # Traer el nickname para que el escritorio no tenga que pedirlo aparte.
        nickname = None
        try:
            r_user = requests.get(
                f"https://api.mercadolibre.com/users/{ml_user_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10,
            )
            if r_user.ok:
                nickname = r_user.json().get("nickname")
        except requests.RequestException:
            pass

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("UPDATE ml_tokens SET active=0 WHERE ml_user_id=%s AND active=1", (ml_user_id,))
        cur.execute(
            """
            INSERT INTO ml_tokens (ml_user_id, nickname, access_token, refresh_token,
                                    expires_in, expires_at, active, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, NOW() + (%s || ' seconds')::interval, 1, NOW(), NOW())
            """,
            (ml_user_id, nickname, access_token, refresh_token, expires_in, expires_in),
        )
        conn.commit()
        cur.close()
        conn.close()

        cuerpo = f"""
            <div class="icono">✅</div>
            <h1>Cuenta conectada</h1>
            <p>Se vinculó correctamente {"la cuenta <strong>" + nickname + "</strong>" if nickname else "tu cuenta de Mercado Libre"}.
            Ya podés cerrar esta ventana y volver a VentaFacil.</p>
        """
        return _pagina("Autorización exitosa", cuerpo, tono="success"), 200

    except Exception as e:
        logging.error("Error intercambiando code por token: %s", e)
        cuerpo = """
            <div class="icono">⚠️</div>
            <h1>No se pudo completar la conexión</h1>
            <p>Hubo un problema al procesar la autorización. Volvé a la app e intentá de nuevo.</p>
        """
        return _pagina("Error de autorización", cuerpo, tono="error"), 500


# ---------------------------------------------------------------------------
# API que consume la app de escritorio
# ---------------------------------------------------------------------------

@app.route("/api/ml/latest", methods=["GET"])
def latest_account():
    """Devuelve la cuenta de ML autorizada más recientemente (para que el
    escritorio pueda vincularse después de que el usuario autoriza desde el
    navegador, ya que ese paso no pasa por la app de escritorio)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT ml_user_id, nickname FROM ml_tokens WHERE active=1 ORDER BY created_at DESC LIMIT 1"
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return jsonify({"error": "no hay ninguna cuenta conectada"}), 404
    return jsonify({"ml_user_id": row[0], "nickname": row[1]}), 200


@app.route("/api/ml/token", methods=["GET"])
def get_valid_token():
    ml_user_id = request.args.get("ml_user_id")
    if not ml_user_id:
        return jsonify({"error": "falta ml_user_id"}), 400

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT access_token, refresh_token, expires_at FROM ml_tokens "
        "WHERE ml_user_id = %s AND active = 1 ORDER BY created_at DESC LIMIT 1",
        (ml_user_id,),
    )
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close()
        return jsonify({"error": "no hay token para ese usuario"}), 404

    access_token, refresh_token, expires_at = row

    if expires_at <= datetime.utcnow() + timedelta(minutes=5):
        resp = requests.post(
            "https://api.mercadolibre.com/oauth/token",
            data={
                "grant_type": "refresh_token",
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "refresh_token": refresh_token,
            },
        )
        if resp.ok:
            data = resp.json()
            access_token = data["access_token"]
            cur.execute(
                "UPDATE ml_tokens SET access_token=%s, refresh_token=%s, "
                "expires_at = NOW() + (%s || ' seconds')::interval, updated_at=NOW() "
                "WHERE ml_user_id=%s AND active=1",
                (access_token, data["refresh_token"], data["expires_in"], ml_user_id),
            )
            conn.commit()
        else:
            cur.close(); conn.close()
            return jsonify({"error": "no se pudo refrescar el token"}), 502

    cur.close(); conn.close()
    return jsonify({"access_token": access_token}), 200


@app.route("/", methods=["GET"])
def index():
    return jsonify({"status": "ventafacil backend running"}), 200


with app.app_context():
    init_db()
    init_tokens_table()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
