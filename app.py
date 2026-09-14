import os
import json
import logging
from flask import Flask, request, jsonify
import psycopg2

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

DATABASE_URL = os.environ.get("DATABASE_URL")


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
        # ML requiere 200 igual, o reintenta agresivamente
        return jsonify({"status": "error_logged"}), 200

    return jsonify({"status": "ok"}), 200


@app.route("/ml/webhook", methods=["GET"])
def ml_webhook_check():
    return jsonify({"status": "alive"}), 200


with app.app_context():
    init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
