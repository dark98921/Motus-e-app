from flask import Flask, render_template, request, redirect, session, send_file, flash
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
import pandas as pd
import io
import os

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-motuse-2024")

# Configurazione database per production
DB_PATH = os.path.join(os.path.dirname(__file__), 'instance', 'motus.db')
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# -------------------- DATABASE INIT --------------------
def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        role TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS participants (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        surname TEXT,
        role TEXT,
        company TEXT,
        attended INTEGER DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # Admin di default
    default_password = "21Settembre"
    hashed_password = generate_password_hash(default_password)
    
    try:
        cur.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                    ("Motus-E", hashed_password, "admin"))
        conn.commit()
        print("✅ Creato admin default: Motus-E / 21Settembre")
    except sqlite3.IntegrityError:
        print("ℹ️ Admin già esistente")
    
    conn.close()

# -------------------- ROUTES --------------------
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE username=?", (username,))
        user = cur.fetchone()
        
        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            conn.close()
            return redirect("/dashboard")
        
        conn.close()
        return render_template("login.html", error="Username o password errati")
    
    return render_template("login.html")

@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    if "user_id" not in session:
        return redirect("/")
    
    conn = get_db_connection()
    cur = conn.cursor()

    search_query = request.args.get('search', '')

    # Gestione presenza/assenza
    if request.method == "POST":
        if "toggle_attendance" in request.form:
            participant_id = request.form.get("participant_id")
            current_status = request.form.get("current_status")
            
            new_status = 0 if int(current_status) == 1 else 1
            
            cur.execute("UPDATE participants SET attended=? WHERE id=?", (new_status, participant_id))
            conn.commit()
            flash("Stato presenza aggiornato!", "success")
            return redirect("/dashboard?search=" + search_query)

        # Import Excel dalla dashboard
        if "import_excel" in request.files:
            file = request.files["import_excel"]
            if file.filename != '':
                try:
                    df = pd.read_excel(file)
                    imported_count = 0
                    for _, row in df.iterrows():
                        cur.execute("SELECT id FROM participants WHERE name=? AND surname=?", 
                                   (row.get("Nome",""), row.get("Cognome","")))
                        existing = cur.fetchone()
                        
                        if not existing:
                            cur.execute("INSERT INTO participants (name,surname,role,company) VALUES (?,?,?,?)",
                                        (row.get("Nome",""), row.get("Cognome",""), 
                                         row.get("Ruolo",""), row.get("Azienda","")))
                            imported_count += 1
                    
                    conn.commit()
                    flash(f"Importati {imported_count} nuovi partecipanti!", "success")
                    return redirect("/dashboard")
                except Exception as e:
                    flash(f"Errore nell'importazione: {str(e)}", "error")

    # Statistiche
    cur.execute("SELECT COUNT(*) as total FROM participants")
    total_participants = cur.fetchone()["total"]
    
    cur.execute("SELECT COUNT(*) as present FROM participants WHERE attended=1")
    present_participants = cur.fetchone()["present"]
    
    cur.execute("SELECT COUNT(*) as total_users FROM users")
    total_users = cur.fetchone()["total_users"]
    
    # Query partecipanti con filtro ricerca
    if search_query:
        cur.execute("""
            SELECT *, 
                   CASE WHEN attended = 1 THEN 'Presente' ELSE 'Assente' END as status_text,
                   CASE WHEN attended = 1 THEN 'success' ELSE 'warning' END as status_class
            FROM participants 
            WHERE name LIKE ? OR surname LIKE ? OR company LIKE ? OR role LIKE ?
            ORDER BY name, surname
        """, (f'%{search_query}%', f'%{search_query}%', f'%{search_query}%', f'%{search_query}%'))
    else:
        cur.execute("""
            SELECT *, 
                   CASE WHEN attended = 1 THEN 'Presente' ELSE 'Assente' END as status_text,
                   CASE WHEN attended = 1 THEN 'success' ELSE 'warning' END as status_class
            FROM participants 
            ORDER BY name, surname
        """)
    
    all_participants = cur.fetchall()
    
    conn.close()

    return render_template("dashboard.html",
                         total_participants=total_participants,
                         present_participants=present_participants,
                         total_users=total_users,
                         all_participants=all_participants,
                         search_query=search_query,
                         session=session)

@app.route("/participants", methods=["GET", "POST"])
def participants():
    if "user_id" not in session:
        return redirect("/")
    
    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == "POST":
        if "add_participant" in request.form:
            name = request.form.get("name", "")
            surname = request.form.get("surname", "")
            role = request.form.get("role", "")
            company = request.form.get("company", "")
            cur.execute("INSERT INTO participants (name,surname,role,company) VALUES (?,?,?,?)",
                        (name,surname,role,company))
            conn.commit()
            flash("Partecipante aggiunto con successo!", "success")

        elif "update" in request.form:
            pid = request.form.get("participant_id")
            cur.execute("""UPDATE participants SET name=?, surname=?, role=?, company=?, attended=?
                        WHERE id=?""",
                        (
                            request.form.get("name"),
                            request.form.get("surname"),
                            request.form.get("role"),
                            request.form.get("company"),
                            1 if request.form.get("attended") else 0,
                            pid
                        ))
            conn.commit()
            flash("Partecipante aggiornato con successo!", "success")

        elif "delete" in request.form:
            pid = request.form.get("participant_id")
            cur.execute("DELETE FROM participants WHERE id=?", (pid,))
            conn.commit()
            flash("Partecipante eliminato con successo!", "success")

        elif "import_excel" in request.files:
            file = request.files["import_excel"]
            if file.filename != '':
                try:
                    df = pd.read_excel(file)
                    imported_count = 0
                    for _, row in df.iterrows():
                        cur.execute("SELECT id FROM participants WHERE name=? AND surname=?", 
                                   (row.get("Nome",""), row.get("Cognome","")))
                        existing = cur.fetchone()
                        
                        if not existing:
                            cur.execute("INSERT INTO participants (name,surname,role,company) VALUES (?,?,?,?)",
                                        (row.get("Nome",""), row.get("Cognome",""), 
                                         row.get("Ruolo",""), row.get("Azienda","")))
                            imported_count += 1
                    
                    conn.commit()
                    flash(f"Importati {imported_count} nuovi partecipanti!", "success")
                except Exception as e:
                    flash(f"Errore nell'importazione: {str(e)}", "error")

    # Filtro ricerca
    search = request.args.get('search', '')
    if search:
        cur.execute("""SELECT * FROM participants 
                      WHERE name LIKE ? OR surname LIKE ? OR company LIKE ? OR role LIKE ?
                      ORDER BY name, surname""", 
                   (f'%{search}%', f'%{search}%', f'%{search}%', f'%{search}%'))
    else:
        cur.execute("SELECT * FROM participants ORDER BY name, surname")
    
    participants_list = cur.fetchall()
    conn.close()

    return render_template("participants.html",
                         participants=participants_list,
                         search=search,
                         session=session)

@app.route("/users", methods=["GET", "POST"])
def users():
    if "user_id" not in session or session.get("role") != "admin":
        return redirect("/dashboard")
    
    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == "POST":
        if "create_user" in request.form:
            username = request.form.get("username")
            password = request.form.get("password")
            role = request.form.get("role")
            
            hashed_password = generate_password_hash(password)
            try:
                cur.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                           (username, hashed_password, role))
                conn.commit()
                flash("Utente creato con successo!", "success")
            except sqlite3.IntegrityError:
                flash("Username già esistente!", "error")

        elif "update_user" in request.form:
            user_id = request.form.get("user_id")
            new_role = request.form.get("role")
            new_password = request.form.get("new_password")
            
            if new_password:
                hashed_password = generate_password_hash(new_password)
                cur.execute("UPDATE users SET role=?, password=? WHERE id=?", 
                           (new_role, hashed_password, user_id))
            else:
                cur.execute("UPDATE users SET role=? WHERE id=?", 
                           (new_role, user_id))
            conn.commit()
            flash("Utente aggiornato con successo!", "success")

    cur.execute("SELECT * FROM users ORDER BY created_at DESC")
    users_list = cur.fetchall()
    conn.close()

    return render_template("users.html", users=users_list, session=session)

@app.route("/export_excel")
def export_excel():
    if "user_id" not in session:
        return redirect("/")
    
    conn = get_db_connection()
    df = pd.read_sql_query("""
        SELECT name as Nome, surname as Cognome, role as Ruolo, 
               company as Azienda, attended as Presente 
        FROM participants
    """, conn)
    conn.close()
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Partecipanti")
        writer.close()
    
    output.seek(0)
    return send_file(output, download_name="partecipanti_motus.xlsx", as_attachment=True)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# Inizializza il database all'avvio
with app.app_context():
    init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
