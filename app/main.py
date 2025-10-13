# app/main.py

from flask import Flask, request, render_template, redirect, url_for
import flask # Menggunakan flask.flash
import mysql.connector
from mysql.connector import Error
import time
from datetime import datetime
import io
import base64
import qrcode
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
        pic = request.form.get('pic', '') # Ambil PIC
        
        try:
            if form_type == 'new':
                part_number = request.form['part_number']
                part_name = request.form['part_name']
                vendor = request.form.get('vendor', '')
                price_str = request.form.get('price', '0')
                quantity = int(request.form['quantity_new'])
                price = float(price_str) if price_str else 0.00
                
                insert_def_query = "INSERT INTO item_definitions (part_number, part_name, vendor, price) VALUES (%s, %s, %s, %s) ON DUPLICATE KEY UPDATE part_name=VALUES(part_name), vendor=VALUES(vendor), price=VALUES(price)"
                cursor.execute(insert_def_query, (part_number, part_name, vendor, price))
            else: 
                part_number = request.form['part_number_existing']
                quantity = int(request.form['quantity'])
                cursor.execute("SELECT part_name, vendor, price FROM item_definitions WHERE part_number = %s", (part_number,))
                item_def = cursor.fetchone()
                if not item_def:
                    flask.flash("Error: Part number yang dipilih tidak valid.", "danger")
                    return redirect(url_for('penerimaan_barang'))
                part_name = item_def['part_name']
                vendor = item_def['vendor']
                price = item_def['price']

            new_parts = []
            for i in range(quantity):
                serial_number = f"{part_number}-{int(time.time())}-{i+1}"
                receipt_date = datetime.now()
                
                query_insert_part = "INSERT INTO parts (part_number, part_name, vendor, price, serial_number, receipt_date, status) VALUES (%s, %s, %s, %s, %s, %s, 'in_stock')"
                cursor.execute(query_insert_part, (part_number, part_name, vendor, price, serial_number, receipt_date))
                
                last_id = cursor.lastrowid 
                log_query = "INSERT INTO transaction_log (timestamp, part_id, serial_number, part_number, part_name, transaction_type, pic) VALUES (%s, %s, %s, %s, %s, 'PENERIMAAN', %s)"
                cursor.execute(log_query, (receipt_date, last_id, serial_number, part_number, part_name, pic))
                
                img = qrcode.make(serial_number)
                buf = io.BytesIO()
                img.save(buf)
                buf.seek(0)
                qr_image = base64.b64encode(buf.getvalue()).decode('utf-8')
                new_parts.append({'serial_number': serial_number, 'part_name': part_name, 'qr_image': qr_image})
            
            conn.commit()
            return render_template('qr_batch.html', new_parts=new_parts)

        except Error as e:
            conn.rollback()
            flask.flash(f"Terjadi error: {e}", "danger")
            return redirect(url_for('penerimaan_barang'))
        finally:
            cursor.close()
            conn.close()
    
    cursor.execute("SELECT * FROM item_definitions ORDER BY part_name ASC")
    item_definitions = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('penerimaan.html', item_definitions=item_definitions)

@app.route('/pengeluaran', methods=['GET', 'POST'])
def pengeluaran_barang():
    conn = get_db_connection()
    if conn is None: return "Koneksi database gagal."
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        serial_number = request.form['serial_number']
        notes = request.form.get('notes', '')
        pic = request.form.get('pic', '')
        equipment_id = request.form.get('equipment_id', '')

        try:
            cursor.execute("SELECT * FROM parts WHERE serial_number = %s", (serial_number,))
            part = cursor.fetchone()
            if not part:
                flask.flash(f"Error: Part dengan serial number {serial_number} tidak ditemukan.", "danger")
                return redirect(url_for('pengeluaran_barang'))
            if part['status'] != 'in_stock':
                flask.flash(f"Error: Part {serial_number} tidak bisa dikeluarkan karena statusnya '{part['status']}'.", "warning")
                return redirect(url_for('pengeluaran_barang'))

            equipment_code = None
            if equipment_id:
                cursor.execute("SELECT equipment_code FROM equipment WHERE id = %s", (equipment_id,))
                equipment = cursor.fetchone()
                if equipment:
                    equipment_code = equipment['equipment_code']
            
            new_status = 'installed' if equipment_id else 'used'
            transaction_type = 'PEMASANGAN' if new_status == 'installed' else 'PENGELUARAN'

            log_query = "INSERT INTO transaction_log (timestamp, part_id, serial_number, part_number, part_name, transaction_type, pic, equipment_code, notes) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
            cursor.execute(log_query, (datetime.now(), part['id'], serial_number, part['part_number'], part['part_name'], transaction_type, pic, equipment_code, notes))
            
            update_query = "UPDATE parts SET status = %s WHERE serial_number = %s"
            cursor.execute(update_query, (new_status, serial_number,))
            
            if new_status == 'installed':
                insert_history_query = "INSERT INTO usage_history (part_id, equipment_id, install_date) VALUES (%s, %s, %s)"
                cursor.execute(insert_history_query, (part['id'], equipment_id, datetime.now()))

            conn.commit()
            flask.flash(f"Part {part['part_name']} ({serial_number}) berhasil dicatat sebagai '{new_status}'.", "success")
        
        except Error as e:
            conn.rollback()
            flask.flash(f"Terjadi error database: {e}", "danger")
        finally:
            cursor.close()
            conn.close()
        
        return redirect(url_for('pengeluaran_barang'))
    
    cursor.execute("SELECT * FROM equipment ORDER BY equipment_code ASC")
    equipment_list = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('pengeluaran.html', equipment_list=equipment_list)

# --- SISA SEMUA FUNGSI ANDA YANG LAIN (inventory, log_transaksi, history, dashboard, dll.) TETAP DI SINI ---
# ... (pastikan semua fungsi lain yang sudah ada tidak terhapus) ...