# app/main.py

from flask import Flask, request, render_template, redirect, url_for
import mysql.connector
from mysql.connector import Error
import time
from datetime import datetime
import io
import base64

app = Flask(__name__)

db_config = {
    'host': 'localhost',
    'user': 'root',
    'password': 'Awesome998544', # <-- PASTIKAN INI BENAR
    'database': 'tps_parts_db'
}

def get_db_connection():
    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
    except Error as e:
        print(f"Error saat koneksi ke MySQL: {e}")
    return conn

@app.route('/')
def index():
    conn = get_db_connection()
    if conn is None: return "Koneksi database gagal."
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM equipment ORDER BY equipment_code ASC")
    equipment_list = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('scan.html', equipment_list=equipment_list)

# GANTI FUNGSI LAMA ANDA DENGAN YANG INI
@app.route('/register', methods=['GET', 'POST'])
def register_part():
    if request.method == 'POST':
        part_number = request.form['part_number']
        part_name = request.form['part_name']
        vendor = request.form['vendor']
        serial_number = f"{part_number}-{int(time.time())}"
        
        conn = get_db_connection()
        if conn is None: 
            return "Koneksi database gagal."
        
        cursor = conn.cursor()
        query = "INSERT INTO parts (part_number, part_name, vendor, serial_number, status) VALUES (%s, %s, %s, %s, 'in_stock')"
        
        try:
            # 1. Simpan data ke database (HANYA SATU KALI)
            cursor.execute(query, (part_number, part_name, vendor, serial_number))
            conn.commit()

            # 2. Jika berhasil, buat gambar QR code
            import qrcode
            import io
            import base64

            img = qrcode.make(serial_number)
            buf = io.BytesIO()
            img.save(buf)
            buf.seek(0)
            
            qr_code_image = base64.b64encode(buf.getvalue()).decode('utf-8')

            # 3. Tampilkan halaman sukses
            return render_template('register_success.html', serial_number=serial_number, qr_code_image=qr_code_image)
        
        except Error as e:
            # Jika terjadi error, batalkan perubahan dan tampilkan pesan
            conn.rollback()
            return f"Gagal menyimpan data: {e}"
        finally:
            # Apapun yang terjadi, pastikan koneksi ditutup
            cursor.close()
            conn.close()

    # Jika metodenya GET, tampilkan form registrasi
    return render_template('register_part.html')

@app.route('/install', methods=['POST'])
def install_part():
    # Logika instalasi part (tidak berubah)
    serial_number = request.form['serial_number']
    equipment_id = request.form['equipment_id']
    install_time = datetime.now()
    conn = get_db_connection()
    if conn is None: return "Koneksi database gagal."
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM parts WHERE serial_number = %s", (serial_number,))
        part = cursor.fetchone()
        if not part:
            return "Error: Part dengan serial number tersebut tidak ditemukan. <a href='/'>Coba lagi</a>."
        if part['status'] != 'in_stock':
            return f"Error: Part ini berstatus '{part['status']}' dan tidak bisa dipasang. <a href='/'>Coba lagi</a>."
        
        update_query = "UPDATE parts SET status = 'installed' WHERE id = %s"
        cursor.execute(update_query, (part['id'],))
        insert_query = "INSERT INTO usage_history (part_id, equipment_id, install_date) VALUES (%s, %s, %s)"
        cursor.execute(insert_query, (part['id'], equipment_id, install_time))
        conn.commit()
        return f"SUKSES! Part {part['part_name']} ({serial_number}) telah dicatat terpasang. <a href='/'>Kembali ke halaman utama</a>."
    except Error as e:
        conn.rollback()
        return f"Terjadi error pada database: {e}"
    finally:
        cursor.close()
        conn.close()

# --- ROUTE BARU UNTUK PROSES PELEPASAN ---
@app.route('/remove', methods=['POST'])
def remove_part():
    serial_number = request.form['serial_number']
    removal_time = datetime.now()
    conn = get_db_connection()
    if conn is None: return "Koneksi database gagal."
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM parts WHERE serial_number = %s", (serial_number,))
        part = cursor.fetchone()
        if not part:
            return "Error: Part dengan serial number tersebut tidak ditemukan. <a href='/'>Coba lagi</a>."
        if part['status'] != 'installed':
            return f"Error: Part ini tidak sedang terpasang dan tidak bisa dilepas. Status saat ini: '{part['status']}'. <a href='/'>Coba lagi</a>."
        
        # 1. Update status part menjadi 'removed'
        update_part_query = "UPDATE parts SET status = 'removed' WHERE id = %s"
        cursor.execute(update_part_query, (part['id'],))

        # 2. Update catatan di usage_history dengan tanggal pelepasan
        update_history_query = "UPDATE usage_history SET removal_date = %s WHERE part_id = %s AND removal_date IS NULL"
        cursor.execute(update_history_query, (removal_time, part['id']))
        
        conn.commit()
        return f"SUKSES! Part {part['part_name']} ({serial_number}) telah dicatat dilepas. <a href='/'>Kembali ke halaman utama</a>."
    except Error as e:
        conn.rollback()
        return f"Terjadi error pada database: {e}"
    finally:
        cursor.close()
        conn.close()

# --- ROUTE BARU UNTUK MENAMPILKAN RIWAYAT ---
# GANTI FUNGSI LAMA DENGAN YANG INI
@app.route('/history')
def history():
    # Ambil parameter dari URL, jika ada
    search_query = request.args.get('search_query', '')
    equipment_filter = request.args.get('equipment_filter', '')

    conn = get_db_connection()
    if conn is None: return "Koneksi database gagal."
    cursor = conn.cursor(dictionary=True)
    
    # -- Logika Query Dinamis --
    params = []
    base_query = """
        SELECT 
            p.part_name, p.serial_number, e.equipment_code, 
            h.install_date, h.removal_date 
        FROM usage_history h
        JOIN parts p ON h.part_id = p.id
        JOIN equipment e ON h.equipment_id = e.id
    """
    
    where_clauses = []
    if search_query:
        where_clauses.append("(p.part_name LIKE %s OR p.serial_number LIKE %s)")
        params.extend([f"%{search_query}%", f"%{search_query}%"])

    if equipment_filter:
        where_clauses.append("e.id = %s")
        params.append(equipment_filter)
    
    if where_clauses:
        base_query += " WHERE " + " AND ".join(where_clauses)
    
    base_query += " ORDER BY h.install_date DESC"
    # -- Akhir Logika Query Dinamis --

    cursor.execute(base_query, tuple(params))
    history_data = cursor.fetchall()

    # Ambil daftar equipment untuk dropdown filter
    cursor.execute("SELECT * FROM equipment ORDER BY equipment_code ASC")
    equipment_list = cursor.fetchall()
    
    cursor.close()
    conn.close()

    return render_template('history.html', 
                           history_data=history_data, 
                           equipment_list=equipment_list,
                           search_query=search_query,
                           equipment_filter=equipment_filter)

# --- ROUTE BARU UNTUK DASHBOARD ---
@app.route('/dashboard')
def dashboard():
    conn = get_db_connection()
    if conn is None: return "Koneksi database gagal."
    cursor = conn.cursor(dictionary=True)

    # 1. Ambil statistik status part
    cursor.execute("SELECT status, COUNT(*) as count FROM parts GROUP BY status")
    status_counts = cursor.fetchall()
    stats = {'in_stock': 0, 'installed': 0, 'removed': 0}
    for row in status_counts:
        stats[row['status']] = row['count']

    # 2. Ambil Top 5 part dengan umur pakai terpendek (dalam hari)
    query_lifespan = """
        SELECT p.part_name, p.serial_number, DATEDIFF(h.removal_date, h.install_date) as lifespan_days
        FROM usage_history h
        JOIN parts p ON h.part_id = p.id
        WHERE h.removal_date IS NOT NULL
        ORDER BY lifespan_days ASC
        LIMIT 5
    """
    cursor.execute(query_lifespan)
    shortest_lifespan = cursor.fetchall()

    # 3. Ambil Top 5 equipment dengan penggantian terbanyak
    query_changes = """
        SELECT e.equipment_code, e.equipment_type, COUNT(h.id) as change_count
        FROM usage_history h
        JOIN equipment e ON h.equipment_id = e.id
        GROUP BY e.id
        ORDER BY change_count DESC
        LIMIT 5
    """
    cursor.execute(query_changes)
    most_changes = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('dashboard.html', 
                           stats=stats, 
                           shortest_lifespan=shortest_lifespan, 
                           most_changes=most_changes)
if __name__ == '__main__':
    app.run(debug=True)