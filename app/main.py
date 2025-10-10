# app/main.py

# Impor library standar Flask
from flask import Flask, request, render_template, redirect, url_for, flash
import flask  # Ditambahkan untuk mengatasi konflik nama 'flash'

# Impor untuk database
import mysql.connector
from mysql.connector import Error

# Impor library pendukung lainnya
import time
from datetime import datetime
import io
import base64
import qrcode

# Impor file konfigurasi kita
import config

app = Flask(__name__)

app.secret_key = config.SECRET_KEY
db_config = {
    'host': config.DB_HOST,
    'user': config.DB_USER,
    'password': config.DB_PASSWORD,
    'database': config.DB_NAME
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

@app.route('/penerimaan', methods=['GET', 'POST'])
def penerimaan_barang():
    conn = get_db_connection()
    if conn is None: return "Koneksi database gagal."
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        form_type = request.form.get('form_type')

        try:
            if form_type == 'new':
                # Logika untuk barang baru (tidak berubah)
                part_number = request.form['part_number']
                part_name = request.form['part_name']
                vendor = request.form.get('vendor', '')
                price = request.form.get('price', 0)
                quantity = int(request.form['quantity_new'])

                # Simpan juga definisi item baru ini ke tabel master
                insert_def_query = "INSERT INTO item_definitions (part_number, part_name, vendor, price) VALUES (%s, %s, %s, %s) ON DUPLICATE KEY UPDATE part_name=VALUES(part_name)"
                cursor.execute(insert_def_query, (part_number, part_name, vendor, price))

            else: # Logika untuk barang lama (existing)
                part_number = request.form['part_number_existing']
                quantity = int(request.form['quantity'])

                # Ambil detail dari tabel definisi item
                cursor.execute("SELECT part_name, vendor, price FROM item_definitions WHERE part_number = %s", (part_number,))
                item_def = cursor.fetchone()
                if not item_def:
                    flask.flash("Error: Part number yang dipilih tidak valid.", "danger")
                    return redirect(url_for('penerimaan_barang'))

                part_name = item_def['part_name']
                vendor = item_def['vendor']
                price = item_def['price']

            # Proses pembuatan item dan QR code (sama untuk keduanya)
            new_parts = []
            for i in range(quantity):
                serial_number = f"{part_number}-{int(time.time())}-{i+1}"
                receipt_date = datetime.now()

                query = """
                    INSERT INTO parts (part_number, part_name, vendor, price, serial_number, receipt_date, status) 
                    VALUES (%s, %s, %s, %s, %s, %s, 'in_stock')
                """
                cursor.execute(query, (part_number, part_name, vendor, price, serial_number, receipt_date))

                # ... (sisa logika log transaksi dan pembuatan QR code tetap sama) ...
                # (Pastikan kode log transaksi Anda ada di sini)

            conn.commit()
            # ... (kode redirect ke qr_batch.html tetap sama) ...
            return render_template('qr_batch.html', new_parts=new_parts) # Asumsi kode pembuatan QR ada di atas

        except Error as e:
            conn.rollback()
            flask.flash(f"Terjadi error: {e}", "danger")
            return redirect(url_for('penerimaan_barang'))
        finally:
            cursor.close()
            conn.close()

    # Bagian GET: Ambil daftar dari tabel definisi item yang baru
    cursor.execute("SELECT * FROM item_definitions ORDER BY part_name ASC")
    item_definitions = cursor.fetchall()
    cursor.close()
    conn.close()
    # Ganti nama variabel yang dikirim ke template
    return render_template('penerimaan.html', item_definitions=item_definitions)

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

# GANTI FUNGSI LAMA DENGAN VERSI BARU INI
@app.route('/inventory')
def inventory():
    conn = get_db_connection()
    if conn is None: return "Koneksi database gagal."
    cursor = conn.cursor(dictionary=True)

    # Query ini mengelompokkan data dari tabel 'parts'
    query = """
        SELECT part_number, part_name, vendor, COUNT(*) as stock_count
        FROM parts
        WHERE status = 'in_stock'
        GROUP BY part_number, part_name, vendor
        ORDER BY part_name ASC
    """
    cursor.execute(query)
    inventory_summary = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('inventory.html', inventory_summary=inventory_summary)

# Tambahkan route ini di main.py

@app.route('/inventory_detail/<part_number>')
def inventory_detail(part_number):
    conn = get_db_connection()
    if conn is None: return "Koneksi database gagal."
    cursor = conn.cursor(dictionary=True)

    # Ambil semua part individual yang 'in_stock' untuk part_number tertentu
    query = "SELECT * FROM parts WHERE part_number = %s AND status = 'in_stock' ORDER BY purchase_date DESC"
    cursor.execute(query, (part_number,))
    part_list = cursor.fetchall()
    
    # Ambil info umum part (kita ambil dari data pertama karena semuanya sama)
    part_info = part_list[0] if part_list else {'part_name': 'Tidak Ditemukan', 'part_number': part_number, 'vendor': 'N/A'}

    cursor.close()
    conn.close()

    return render_template('inventory_detail.html', part_list=part_list, part_info=part_info)


@app.route('/qr/<serial_number>')
def show_qr(serial_number):
    # Logika pembuatan QR Code
    import qrcode # Pastikan ini diimpor di atas

    img = qrcode.make(serial_number)
    buf = io.BytesIO()
    img.save(buf)
    buf.seek(0)
    qr_code_image = base64.b64encode(buf.getvalue()).decode('utf-8')

    return render_template('show_qr.html', serial_number=serial_number, qr_code_image=qr_code_image)

# --- ROUTE BARU UNTUK PENGELUARAN BARANG ---
@app.route('/pengeluaran', methods=['GET', 'POST'])
def pengeluaran_barang():
    if request.method == 'POST':
        serial_number = request.form['serial_number']
        notes = request.form.get('notes', '')

        conn = get_db_connection()
        if conn is None: return "Koneksi database gagal."
        cursor = conn.cursor(dictionary=True)

        try:
            # Cek dulu status part
            cursor.execute("SELECT * FROM parts WHERE serial_number = %s", (serial_number,))
            part = cursor.fetchone()
            if not part:
                flask.flash(f"Error: Part dengan serial number {serial_number} tidak ditemukan.", "danger")
                return redirect(url_for('pengeluaran_barang'))
            if part['status'] != 'in_stock':
                flask.flash(f"Error: Part {serial_number} tidak bisa dikeluarkan karena statusnya '{part['status']}'.", "warning")
                return redirect(url_for('pengeluaran_barang'))
            
            # Setelah validasi, sebelum UPDATE
            log_query = """
            INSERT INTO transaction_log (timestamp, part_id, serial_number, transaction_type, quantity, notes)
            VALUES (%s, %s, %s, 'PENGELUARAN', -1, %s)
            """
            cursor.execute(log_query, (datetime.now(), part['id'], serial_number, notes))

            # Update status menjadi 'used'
            update_query = "UPDATE parts SET status = 'used' WHERE serial_number = %s"
            cursor.execute(update_query, (serial_number,))
            conn.commit()
            flask.flash(f"Part {part['part_name']} ({serial_number}) berhasil dikeluarkan dari stok.", "success")

        except Error as e:
            conn.rollback()
            flask.flash(f"Terjadi error database: {e}", "danger")
        finally:
            cursor.close()
            conn.close()

        return redirect(url_for('pengeluaran_barang'))

    # Bagian GET, hanya menampilkan halaman
    return render_template('pengeluaran.html')

@app.route('/log_transaksi')
def log_transaksi():
    conn = get_db_connection()
    if conn is None: return "Koneksi database gagal."
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM transaction_log ORDER BY timestamp DESC")
    logs = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('log_transaksi.html', logs=logs)

if __name__ == '__main__':
    app.run(debug=True)