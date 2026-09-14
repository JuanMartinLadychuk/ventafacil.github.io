import os
import json
import logging
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
            user_id TEXT,
            access_token TEXT,
            refresh_token TEXT,
            expires_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    conn.commit()
    cur.close()
    conn.close()


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


@app.route("/oauth/callback", methods=["GET"])
def oauth_callback():
    code = request.args.get("code")
    error = request.args.get("error")

    if error:
        logging.error("Error en OAuth callback: %s", error)
        return f"<h2>Error de autorización: {error}</h2>", 400

    if not code:
        return "<h2>Falta el parámetro 'code'</h2>", 400

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
        user_id = str(token_data["user_id"])
        expires_in = token_data["expires_in"]

        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO ml_tokens (user_id, access_token, refresh_token, expires_at)
            VALUES (%s, %s, %s, NOW() + (%s || ' seconds')::interval)
            """,
            (user_id, access_token, refresh_token, expires_in),
        )
        conn.commit()
        cur.close()
        conn.close()

        return "<h2>Autorización exitosa. Ya podés cerrar esta ventana.</h2>", 200

    except requests.exceptions.HTTPError as e:
        logging.error("Error intercambiando code por token: %s - Respuesta: %s", e, e.response.text)
        return "<h2>Error al procesar la autorización</h2>", 500
    except Exception as e:
        logging.error("Error intercambiando code por token: %s", e)
        return "<h2>Error al procesar la autorización</h2>", 500


@app.route("/", methods=["GET"])
def index():
    return jsonify({"status": "ventafacil backend running"}), 200


with app.app_context():
    init_db()
    init_tokens_table()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
