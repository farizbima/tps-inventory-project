# app/main.py

# Impor library standar Flask
from flask import Flask, request, render_template, redirect, url_for
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

# GANTI FUNGSI LAMA ANDA DENGAN YANG INI
# --- ROUTE BARU UNTUK PENERIMAAN BARANG ---
@app.route('/penerimaan', methods=['GET', 'POST'])
def penerimaan_barang():
    conn = get_db_connection()
    if conn is None: return "Koneksi database gagal."
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        item_code = request.form['item_code']
        qty_masuk = int(request.form['qty_masuk'])
        notes = request.form['notes'] # Kita akan gunakan ini nanti untuk log transaksi

        try:
            # Update stok di tabel master
            update_stock_query = "UPDATE master_items SET current_stock = current_stock + %s WHERE item_code = %s"
            cursor.execute(update_stock_query, (qty_masuk, item_code))

            conn.commit()
            flask.flash(f"Stok untuk {item_code} berhasil ditambah sebanyak {qty_masuk} unit!", "success")
            return redirect(url_for('penerimaan_barang'))

        except Error as e:
            conn.rollback()
            flask.flash(f"Terjadi error: {e}", "danger")
        finally:
            cursor.close()
            conn.close()

    # --- Bagian GET (menampilkan form) ---
    cursor.execute("SELECT item_code, nama_barang FROM master_items ORDER BY nama_barang ASC")
    master_items = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template('penerimaan.html', master_items=master_items)

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

@app.route('/inventory')
def inventory():
    search_query = request.args.get('search_query', '')
    conn = get_db_connection()
    if conn is None:
        return "Koneksi database gagal."
    
    cursor = conn.cursor(dictionary=True)
    
    params = []
    # Query ini akan mengelompokkan part berdasarkan part_number, nama, dan vendor,
    # lalu menghitung berapa banyak yang statusnya 'in_stock'
    query = """
        SELECT part_number, part_name, vendor, COUNT(*) as stock_count
        FROM parts
        WHERE status = 'in_stock'
    """

    if search_query:
        query += " AND (part_name LIKE %s OR part_number LIKE %s)"
        params.extend([f"%{search_query}%", f"%{search_query}%"])

    query += " GROUP BY part_number, part_name, vendor ORDER BY part_name ASC"

    cursor.execute(query, tuple(params))
    inventory_data = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('inventory.html', 
                           inventory_data=inventory_data, 
                           search_query=search_query)

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
    conn = get_db_connection()
    if conn is None: return "Koneksi database gagal."
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        # Ambil data dari form
        tanggal = request.form['tanggal']
        pic = request.form['pic']
        item_code = request.form['item_code']
        qty_keluar = int(request.form['qty_keluar'])
        equipment_id = request.form['equipment_id']
        hm_km = request.form['hm_km']
        keterangan = request.form['keterangan']

        try:
            # 1. Cek stok saat ini
            cursor.execute("SELECT current_stock FROM master_items WHERE item_code = %s", (item_code,))
            item = cursor.fetchone()
            if item['current_stock'] < qty_keluar:
                flash(f"Stok tidak mencukupi! Stok saat ini: {item['current_stock']}", "danger")
                return redirect(url_for('pengeluaran_barang'))

            # 2. Masukkan ke tabel transaksi
            trans_query = """
                INSERT INTO inventory_transactions 
                (tanggal, pic, item_code, qty_keluar, equipment_id, hm_km, keterangan)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(trans_query, (tanggal, pic, item_code, qty_keluar, equipment_id, hm_km, keterangan))

            # 3. Kurangi stok di tabel master
            update_stock_query = "UPDATE master_items SET current_stock = current_stock - %s WHERE item_code = %s"
            cursor.execute(update_stock_query, (qty_keluar, item_code))

            conn.commit()
            flash("Transaksi pengeluaran barang berhasil dicatat!", "success")
            return redirect(url_for('pengeluaran_barang'))

        except Error as e:
            conn.rollback()
            flash(f"Terjadi error: {e}", "danger")
        finally:
            cursor.close()
            conn.close()

    # --- Bagian GET (menampilkan form) ---
    # Ambil daftar barang untuk dropdown
    cursor.execute("SELECT item_code, nama_barang, current_stock FROM master_items ORDER BY nama_barang ASC")
    master_items = cursor.fetchall()

    # Ambil daftar equipment untuk dropdown
    cursor.execute("SELECT * FROM equipment ORDER BY equipment_code ASC")
    equipment_list = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('pengeluaran.html', master_items=master_items, equipment_list=equipment_list)

if __name__ == '__main__':
    app.run(debug=True)