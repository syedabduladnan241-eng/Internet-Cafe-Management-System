
import os
import re
import sqlite3
from pathlib import Path
from datetime import datetime
from functools import wraps

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash
)

from werkzeug.security import generate_password_hash, check_password_hash


# --------------------------------------------------
# FLASK CONFIGURATION
# --------------------------------------------------

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "internet-cafe-development-secret-change-before-deployment"
)

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "database.db"

COMPUTERS = [f"PC-{i:02d}" for i in range(1, 11)]

HOURLY_RATE = 30.00


# --------------------------------------------------
# DATABASE CONNECTION
# --------------------------------------------------

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            computer TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT NOT NULL,
            computer TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT,
            duration REAL DEFAULT 0,
            amount REAL DEFAULT 0,
            status TEXT DEFAULT 'Active'
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS admin_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    """)

    # Create default administrator only if no admin exists.
    admin = cur.execute(
        "SELECT id FROM admin_users LIMIT 1"
    ).fetchone()

    if admin is None:
        password_hash = generate_password_hash("admin123")

        cur.execute("""
            INSERT INTO admin_users (username, password_hash)
            VALUES (?, ?)
        """, ("admin", password_hash))

    conn.commit()
    conn.close()


init_db()


# --------------------------------------------------
# LOGIN PROTECTION
# --------------------------------------------------

def login_required(route_function):

    @wraps(route_function)
    def wrapper(*args, **kwargs):

        if "admin_id" not in session:
            flash("Please login first.", "warning")
            return redirect(url_for("login"))

        return route_function(*args, **kwargs)

    return wrapper


# --------------------------------------------------
# LOGIN
# --------------------------------------------------

@app.route("/", methods=["GET"])
def login():

    if "admin_id" in session:
        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/login", methods=["POST"])
def check_login():

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    if not username or not password:
        flash("Enter username and password.", "danger")
        return redirect(url_for("login"))

    conn = get_db()

    admin = conn.execute("""
        SELECT * FROM admin_users
        WHERE username = ?
    """, (username,)).fetchone()

    conn.close()

    if admin and check_password_hash(
        admin["password_hash"], password
    ):

        session.clear()
        session["admin_id"] = admin["id"]
        session["admin_username"] = admin["username"]

        flash("Login successful!", "success")
        return redirect(url_for("dashboard"))

    flash("Invalid username or password.", "danger")
    return redirect(url_for("login"))


@app.route("/logout", methods=["POST"])
@login_required
def logout():

    session.clear()
    flash("You have been logged out.", "success")

    return redirect(url_for("login"))


# --------------------------------------------------
# DASHBOARD
# --------------------------------------------------

@app.route("/dashboard")
@login_required
def dashboard():

    conn = get_db()

    total_customers = conn.execute(
        "SELECT COUNT(*) FROM customers"
    ).fetchone()[0]

    active_sessions = conn.execute("""
        SELECT COUNT(*) FROM sessions
        WHERE status = 'Active'
    """).fetchone()[0]

    total_revenue = conn.execute("""
        SELECT COALESCE(SUM(amount), 0)
        FROM sessions
        WHERE status = 'Completed'
    """).fetchone()[0]

    total_sessions = conn.execute(
        "SELECT COUNT(*) FROM sessions"
    ).fetchone()[0]

    conn.close()

    return render_template(
        "dashboard.html",
        total_customers=total_customers,
        active_sessions=active_sessions,
        total_revenue=round(total_revenue, 2),
        total_sessions=total_sessions
    )


# --------------------------------------------------
# ADD CUSTOMER
# --------------------------------------------------

@app.route("/add_customer")
@login_required
def add_customer():

    return render_template(
        "add_customer.html",
        computers=COMPUTERS
    )


@app.route("/save_customer", methods=["POST"])
@login_required
def save_customer():

    name = request.form.get("name", "").strip()
    phone = request.form.get("phone", "").strip()
    computer = request.form.get("computer", "").strip()

    if not name:
        flash("Customer name is required.", "danger")
        return redirect(url_for("add_customer"))

    if not re.fullmatch(r"[0-9]{10}", phone):
        flash("Enter a valid 10-digit phone number.", "danger")
        return redirect(url_for("add_customer"))

    if computer not in COMPUTERS:
        flash("Select a valid computer.", "danger")
        return redirect(url_for("add_customer"))

    conn = get_db()

    conn.execute("""
        INSERT INTO customers (name, phone, computer)
        VALUES (?, ?, ?)
    """, (name, phone, computer))

    conn.commit()
    conn.close()

    flash("Customer added successfully!", "success")

    return redirect(url_for("customers"))


# --------------------------------------------------
# VIEW CUSTOMERS
# --------------------------------------------------

@app.route("/customers")
@login_required
def customers():

    keyword = request.args.get("keyword", "").strip()

    conn = get_db()

    if keyword:
        data = conn.execute("""
            SELECT * FROM customers
            WHERE name LIKE ?
               OR phone LIKE ?
               OR computer LIKE ?
            ORDER BY id DESC
        """, (
            f"%{keyword}%",
            f"%{keyword}%",
            f"%{keyword}%"
        )).fetchall()

    else:
        data = conn.execute("""
            SELECT * FROM customers
            ORDER BY id DESC
        """).fetchall()

    conn.close()

    return render_template(
        "customers.html",
        customers=data,
        keyword=keyword
    )


# --------------------------------------------------
# EDIT CUSTOMER
# --------------------------------------------------

@app.route("/edit_customer/<int:id>", methods=["GET", "POST"])
@login_required
def edit_customer(id):

    conn = get_db()

    customer = conn.execute(
        "SELECT * FROM customers WHERE id = ?",
        (id,)
    ).fetchone()

    if customer is None:
        conn.close()
        flash("Customer not found.", "danger")
        return redirect(url_for("customers"))

    if request.method == "POST":

        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        computer = request.form.get("computer", "").strip()

        if not name:
            conn.close()
            flash("Customer name is required.", "danger")
            return redirect(url_for("edit_customer", id=id))

        if not re.fullmatch(r"[0-9]{10}", phone):
            conn.close()
            flash("Enter a valid 10-digit phone number.", "danger")
            return redirect(url_for("edit_customer", id=id))

        if computer not in COMPUTERS:
            conn.close()
            flash("Select a valid computer.", "danger")
            return redirect(url_for("edit_customer", id=id))

        conn.execute("""
            UPDATE customers
            SET name = ?, phone = ?, computer = ?
            WHERE id = ?
        """, (name, phone, computer, id))

        conn.commit()
        conn.close()

        flash("Customer updated successfully!", "success")
        return redirect(url_for("customers"))

    conn.close()

    return render_template(
        "edit_customer.html",
        customer=customer,
        computers=COMPUTERS
    )


# --------------------------------------------------
# DELETE CUSTOMER
# --------------------------------------------------

@app.route("/delete_customer/<int:id>", methods=["POST"])
@login_required
def delete_customer(id):

    conn = get_db()

    customer = conn.execute(
        "SELECT * FROM customers WHERE id = ?",
        (id,)
    ).fetchone()

    if customer is None:
        conn.close()
        flash("Customer not found.", "danger")
        return redirect(url_for("customers"))

    active = conn.execute("""
        SELECT id FROM sessions
        WHERE customer_name = ?
          AND status = 'Active'
    """, (customer["name"],)).fetchone()

    if active:
        conn.close()
        flash(
            "Cannot delete a customer with an active session.",
            "danger"
        )
        return redirect(url_for("customers"))

    conn.execute(
        "DELETE FROM customers WHERE id = ?",
        (id,)
    )

    conn.commit()
    conn.close()

    flash("Customer deleted successfully!", "success")

    return redirect(url_for("customers"))


# --------------------------------------------------
# START SESSION PAGE
# --------------------------------------------------

@app.route("/start_session")
@login_required
def start_session():

    conn = get_db()

    customers = conn.execute("""
        SELECT * FROM customers
        ORDER BY name
    """).fetchall()

    occupied_rows = conn.execute("""
        SELECT computer FROM sessions
        WHERE status = 'Active'
    """).fetchall()

    occupied = [row["computer"] for row in occupied_rows]

    available = [
        computer for computer in COMPUTERS
        if computer not in occupied
    ]

    conn.close()

    return render_template(
        "start_session.html",
        customers=customers,
        computers=available
    )


# --------------------------------------------------
# SAVE SESSION
# --------------------------------------------------

@app.route("/save_session", methods=["POST"])
@login_required
def save_session():

    customer_id = request.form.get("customer_id")
    computer = request.form.get("computer", "").strip()

    if not customer_id or computer not in COMPUTERS:
        flash("Select a valid customer and computer.", "danger")
        return redirect(url_for("start_session"))

    conn = get_db()

    customer = conn.execute(
        "SELECT * FROM customers WHERE id = ?",
        (customer_id,)
    ).fetchone()

    if customer is None:
        conn.close()
        flash("Customer not found.", "danger")
        return redirect(url_for("start_session"))

    active = conn.execute("""
        SELECT id FROM sessions
        WHERE computer = ? AND status = 'Active'
    """, (computer,)).fetchone()

    if active:
        conn.close()
        flash("This computer is already occupied.", "danger")
        return redirect(url_for("start_session"))

    start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn.execute("""
        INSERT INTO sessions
        (customer_name, computer, start_time, status)
        VALUES (?, ?, ?, 'Active')
    """, (customer["name"], computer, start_time))

    conn.commit()
    conn.close()

    flash("Computer session started successfully!", "success")

    return redirect(url_for("active_sessions"))


# --------------------------------------------------
# ACTIVE SESSIONS
# --------------------------------------------------

@app.route("/active_sessions")
@login_required
def active_sessions():

    conn = get_db()

    sessions = conn.execute("""
        SELECT * FROM sessions
        WHERE status = 'Active'
        ORDER BY id DESC
    """).fetchall()

    conn.close()

    return render_template(
        "active_sessions.html",
        sessions=sessions
    )


# --------------------------------------------------
# END SESSION
# --------------------------------------------------

@app.route("/end_session/<int:id>", methods=["POST"])
@login_required
def end_session(id):

    conn = get_db()

    current = conn.execute("""
        SELECT * FROM sessions
        WHERE id = ?
    """, (id,)).fetchone()

    if current is None:
        conn.close()
        flash("Session not found.", "danger")
        return redirect(url_for("active_sessions"))

    if current["status"] != "Active":
        conn.close()
        flash("This session has already been completed.", "warning")
        return redirect(url_for("billing"))

    start_time = datetime.strptime(
        current["start_time"],
        "%Y-%m-%d %H:%M:%S"
    )

    end_time = datetime.now()

    duration = max(
        0,
        (end_time - start_time).total_seconds() / 3600
    )

    amount = round(duration * HOURLY_RATE, 2)

    end_time_string = end_time.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    conn.execute("""
        UPDATE sessions
        SET end_time = ?,
            duration = ?,
            amount = ?,
            status = 'Completed'
        WHERE id = ? AND status = 'Active'
    """, (
        end_time_string,
        round(duration, 2),
        amount,
        id
    ))

    conn.commit()
    conn.close()

    flash("Session completed and bill generated!", "success")

    return redirect(url_for("bill", id=id))


# --------------------------------------------------
# BILL RECEIPT
# --------------------------------------------------

@app.route("/bill/<int:id>")
@login_required
def bill(id):

    conn = get_db()

    data = conn.execute("""
        SELECT
            customer_name,
            computer,
            start_time,
            end_time,
            duration,
            amount,
            status
        FROM sessions
        WHERE id = ?
    """, (id,)).fetchone()

    conn.close()

    if data is None:
        flash("Bill not found.", "danger")
        return redirect(url_for("billing"))

    if data["status"] != "Completed":
        flash("This session has not been completed yet.", "warning")
        return redirect(url_for("active_sessions"))

    return render_template("bill.html", bill=data)


# --------------------------------------------------
# BILLING HISTORY
# --------------------------------------------------

@app.route("/billing")
@login_required
def billing():

    conn = get_db()

    bills = conn.execute("""
        SELECT
            id,
            customer_name,
            computer,
            amount,
            status,
            start_time,
            end_time,
            duration
        FROM sessions
        WHERE status = 'Completed'
        ORDER BY id DESC
    """).fetchall()

    conn.close()

    return render_template(
        "billing.html",
        bills=bills
    )


# --------------------------------------------------
# REPORTS
# --------------------------------------------------

@app.route("/reports")
@login_required
def reports():

    conn = get_db()

    total_customers = conn.execute("""
        SELECT COUNT(*) FROM customers
    """).fetchone()[0]

    total_sessions = conn.execute("""
        SELECT COUNT(*) FROM sessions
    """).fetchone()[0]

    total_revenue = conn.execute("""
        SELECT COALESCE(SUM(amount), 0)
        FROM sessions
        WHERE status = 'Completed'
    """).fetchone()[0]

    today_revenue = conn.execute("""
        SELECT COALESCE(SUM(amount), 0)
        FROM sessions
        WHERE status = 'Completed'
          AND date(end_time) = date('now', 'localtime')
    """).fetchone()[0]

    conn.close()

    return render_template(
        "reports.html",
        total_customers=total_customers,
        total_sessions=total_sessions,
        total_revenue=round(total_revenue, 2),
        today_revenue=round(today_revenue, 2)
    )


# --------------------------------------------------
# ERROR HANDLING
# --------------------------------------------------

@app.errorhandler(404)
def page_not_found(error):
    return "Page not found (404).", 404


@app.errorhandler(500)
def internal_error(error):
    return "An internal server error occurred.", 500


# --------------------------------------------------
# RUN APPLICATION
# --------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True)
