import requests

CLIENT_ID = os.environ.get("ML_CLIENT_ID")
CLIENT_SECRET = os.environ.get("ML_CLIENT_SECRET")
REDIRECT_URI = "https://ventafacil-goio.onrender.com/oauth/callback"


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
            VALUES (%s, %s, %s, NOW() + INTERVAL '%s seconds')
            """,
            (user_id, access_token, refresh_token, expires_in),
        )
        conn.commit()
        cur.close()
        conn.close()

        return "<h2>Autorización exitosa. Ya podés cerrar esta ventana.</h2>", 200

    except Exception as e:
        logging.error("Error intercambiando code por token: %s", e)
        return "<h2>Error al procesar la autorización</h2>", 500


with app.app_context():
    init_tokens_table()
