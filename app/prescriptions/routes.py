import os
import uuid
from flask import render_template, request, redirect, url_for, flash, current_app, send_file, abort, jsonify, session
from flask_login import login_required, current_user
from app.prescriptions import prescriptions_bp
from app.utils.encryption import encrypt, decrypt, encrypt_file, decrypt_file
from app.utils.audit import log_audit
from app import mysql
from datetime import datetime, timezone
import io

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def save_encrypted_file(file, upload_folder):
    """Encrypt and save a file, return stored filename and extension."""
    ext = file.filename.rsplit('.', 1)[1].lower()
    filename = f"{uuid.uuid4().hex}.enc"
    os.makedirs(upload_folder, exist_ok=True)
    encrypted_bytes = encrypt_file(file.read())
    with open(os.path.join(upload_folder, filename), 'wb') as f:
        f.write(encrypted_bytes)
    return filename, ext


@prescriptions_bp.route('/dashboard')
@login_required
def dashboard():
    cur = mysql.connection.cursor()
    cur.execute(
        "SELECT id, patient_name, medication, dosage, notes, image_path, created_at "
        "FROM prescriptions WHERE user_id = %s ORDER BY created_at DESC",
        (current_user.id,)
    )
    rows = cur.fetchall()

    prescriptions = []
    for row in rows:
        # Fetch all images for this prescription
        cur.execute(
            "SELECT id, filename, original_ext FROM prescription_images "
            "WHERE prescription_id = %s",
            (row[0],)
        )
        images = cur.fetchall()

        prescriptions.append({
            'id': row[0],
            'patient_name': decrypt(row[1]),
            'medication': decrypt(row[2]),
            'dosage': decrypt(row[3]),
            'notes': decrypt(row[4]) if row[4] else '',
            'image_path': row[5],  # legacy single image
            'images': [{'id': img[0], 'ext': img[2]} for img in images],
            'created_at': row[6]
        })

    cur.close()
    return render_template('dashboard.html', prescriptions=prescriptions)


@prescriptions_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add_prescription():
    if request.method == 'POST':
        patient_name = request.form['patient_name']
        medication = request.form['medication']
        dosage = request.form['dosage']
        notes = request.form.get('notes', '')
        image_files = request.files.getlist('images')

        enc_patient = encrypt(patient_name)
        enc_medication = encrypt(medication)
        enc_dosage = encrypt(dosage)
        enc_notes = encrypt(notes) if notes else None

        try:
            cur = mysql.connection.cursor()
            cur.execute(
                "INSERT INTO prescriptions (user_id, patient_name, medication, dosage, notes) "
                "VALUES (%s, %s, %s, %s, %s)",
                (current_user.id, enc_patient, enc_medication, enc_dosage, enc_notes)
            )
            mysql.connection.commit()
            prescription_id = cur.lastrowid

            # Save each uploaded image
            upload_folder = current_app.config['UPLOAD_FOLDER']
            for image_file in image_files:
                if image_file and allowed_file(image_file.filename):
                    filename, ext = save_encrypted_file(image_file, upload_folder)
                    cur.execute(
                        "INSERT INTO prescription_images (prescription_id, filename, original_ext) "
                        "VALUES (%s, %s, %s)",
                        (prescription_id, filename, ext)
                    )
            mysql.connection.commit()
            cur.close()

            current_app.logger.info(
                f"PRESCRIPTION ADDED | user_id={current_user.id} | patient={patient_name}"
            )
            log_audit('PRESCRIPTION_ADDED', f'Added prescription for patient: {patient_name}')
            flash('Prescription saved securely!', 'success')
            return redirect(url_for('prescriptions.dashboard'))
        except Exception as e:
            current_app.logger.error(
                f"PRESCRIPTION ADD FAILED | user_id={current_user.id} | error={str(e)}"
            )
            flash(f'Error saving prescription: {str(e)}', 'danger')

    return render_template('add_prescription.html')


@prescriptions_bp.route('/edit/<int:prescription_id>', methods=['GET', 'POST'])
@login_required
def edit_prescription(prescription_id):
    cur = mysql.connection.cursor()
    cur.execute(
        "SELECT id, patient_name, medication, dosage, notes, image_path "
        "FROM prescriptions WHERE id = %s AND user_id = %s",
        (prescription_id, current_user.id)
    )
    row = cur.fetchone()

    if not row:
        flash('Prescription not found.', 'danger')
        return redirect(url_for('prescriptions.dashboard'))

    cur.execute(
        "SELECT id, filename, original_ext FROM prescription_images "
        "WHERE prescription_id = %s",
        (prescription_id,)
    )
    existing_images = [{'id': img[0], 'ext': img[2]} for img in cur.fetchall()]

    prescription = {
        'id': row[0],
        'patient_name': decrypt(row[1]),
        'medication': decrypt(row[2]),
        'dosage': decrypt(row[3]),
        'notes': decrypt(row[4]) if row[4] else '',
        'image_path': row[5],
        'images': existing_images
    }

    if request.method == 'POST':
        patient_name = request.form['patient_name']
        medication = request.form['medication']
        dosage = request.form['dosage']
        notes = request.form.get('notes', '')
        image_files = request.files.getlist('images')
        remove_image_ids = request.form.getlist('remove_image')

        # Remove selected images
        for img_id in remove_image_ids:
            cur.execute(
                "SELECT filename FROM prescription_images WHERE id = %s AND prescription_id = %s",
                (img_id, prescription_id)
            )
            img_row = cur.fetchone()
            if img_row:
                filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], img_row[0])
                if os.path.exists(filepath):
                    os.remove(filepath)
                cur.execute("DELETE FROM prescription_images WHERE id = %s", (img_id,))

        # Add new images
        upload_folder = current_app.config['UPLOAD_FOLDER']
        for image_file in image_files:
            if image_file and allowed_file(image_file.filename):
                filename, ext = save_encrypted_file(image_file, upload_folder)
                cur.execute(
                    "INSERT INTO prescription_images (prescription_id, filename, original_ext) "
                    "VALUES (%s, %s, %s)",
                    (prescription_id, filename, ext)
                )

        enc_patient = encrypt(patient_name)
        enc_medication = encrypt(medication)
        enc_dosage = encrypt(dosage)
        enc_notes = encrypt(notes) if notes else None

        try:
            cur.execute(
                "UPDATE prescriptions SET patient_name=%s, medication=%s, "
                "dosage=%s, notes=%s WHERE id=%s AND user_id=%s",
                (enc_patient, enc_medication, enc_dosage, enc_notes,
                 prescription_id, current_user.id)
            )
            mysql.connection.commit()
            cur.close()
            log_audit('PRESCRIPTION_UPDATED', f'Updated prescription ID: {prescription_id}')
            flash('Prescription updated successfully!', 'success')
            return redirect(url_for('prescriptions.dashboard'))
        except Exception as e:
            flash(f'Error updating prescription: {str(e)}', 'danger')

    return render_template('edit_prescription.html', prescription=prescription)


@prescriptions_bp.route('/image/<int:image_id>')
@login_required
def serve_image(image_id):
    cur = mysql.connection.cursor()
    # Verify image belongs to current user via join
    cur.execute(
        "SELECT pi.filename, pi.original_ext FROM prescription_images pi "
        "JOIN prescriptions p ON pi.prescription_id = p.id "
        "WHERE pi.id = %s AND p.user_id = %s",
        (image_id, current_user.id)
    )
    row = cur.fetchone()
    cur.close()

    if not row:
        abort(404)

    filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], row[0])
    if not os.path.exists(filepath):
        abort(404)

    with open(filepath, 'rb') as f:
        encrypted_bytes = f.read()

    decrypted_bytes = decrypt_file(encrypted_bytes)

    mime_types = {
        'png': 'image/png',
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'pdf': 'application/pdf'
    }

    return send_file(
        io.BytesIO(decrypted_bytes),
        mimetype=mime_types.get(row[1], 'application/octet-stream'),
        as_attachment=False
    )


@prescriptions_bp.route('/delete/<int:prescription_id>', methods=['POST'])
@login_required
def delete_prescription(prescription_id):
    cur = mysql.connection.cursor()
    cur.execute(
        "SELECT image_path FROM prescriptions WHERE id = %s AND user_id = %s",
        (prescription_id, current_user.id)
    )
    row = cur.fetchone()

    if row:
        # Delete all images from prescription_images table
        cur.execute(
            "SELECT filename FROM prescription_images WHERE prescription_id = %s",
            (prescription_id,)
        )
        images = cur.fetchall()
        for img in images:
            filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], img[0])
            if os.path.exists(filepath):
                os.remove(filepath)

        cur.execute("DELETE FROM prescriptions WHERE id = %s AND user_id = %s",
                    (prescription_id, current_user.id))
        mysql.connection.commit()
        log_audit('PRESCRIPTION_DELETED', f'Deleted prescription ID: {prescription_id}')
        flash('Prescription deleted.', 'success')
    else:
        log_audit('PRESCRIPTION_DELETE_FAILED', f'Attempted to delete non-existent prescription ID: {prescription_id}')
        flash('Prescription not found.', 'danger')

    cur.close()
    return redirect(url_for('prescriptions.dashboard'))


@prescriptions_bp.route('/search')
@login_required
def search():
    query = request.args.get('q', '').strip().lower()
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()

    cur = mysql.connection.cursor()
    cur.execute(
        "SELECT id, patient_name, medication, dosage, notes, created_at "
        "FROM prescriptions WHERE user_id = %s",
        (current_user.id,)
    )
    rows = cur.fetchall()

    results = []
    for row in rows:
        patient_name = decrypt(row[1])
        medication = decrypt(row[2])
        dosage = decrypt(row[3])
        notes = decrypt(row[4]) if row[4] else ''
        created_at = row[5]

        # Text filter
        if query and query not in patient_name.lower() and query not in medication.lower():
            continue

        # Date range filter
        if date_from:
            try:
                from_date = datetime.strptime(date_from, '%Y-%m-%d').date()
                if created_at.date() < from_date:
                    continue
            except ValueError:
                pass

        if date_to:
            try:
                to_date = datetime.strptime(date_to, '%Y-%m-%d').date()
                if created_at.date() > to_date:
                    continue
            except ValueError:
                pass

        cur.execute(
            "SELECT id, original_ext FROM prescription_images "
            "WHERE prescription_id = %s",
            (row[0],)
        )
        images = [{'id': img[0], 'ext': img[1]} for img in cur.fetchall()]

        results.append({
            'id': row[0],
            'patient_name': patient_name,
            'medication': medication,
            'dosage': dosage,
            'notes': notes,
            'images': images,
            'created_at': created_at.strftime('%d %b %Y')
        })

    cur.close()
    return jsonify(results)


@prescriptions_bp.route('/ping')
@login_required
def ping():
    session['last_active'] = datetime.now(timezone.utc).timestamp()
    return jsonify({'status': 'ok'})