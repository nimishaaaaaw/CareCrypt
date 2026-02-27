from flask import render_template, request, redirect, url_for, flash, session, current_app
from flask_login import login_user, logout_user, login_required, current_user
from flask_mail import Message
from datetime import datetime, timezone, timedelta
from app.auth import auth_bp
from app.utils.hashing import hash_password, check_password
from app.utils.audit import log_audit
from app.models import User
from app import mysql, limiter, mail
import secrets
import re


@auth_bp.route('/', methods=['GET', 'POST'])
@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def login():
    if request.method == 'POST':
        identifier = request.form['identifier']
        password = request.form['password']

        cur = mysql.connection.cursor()
        cur.execute(
            "SELECT id, username, email, password_hash FROM users "
            "WHERE email = %s OR username = %s",
            (identifier, identifier)
        )
        row = cur.fetchone()
        cur.close()

        if row and check_password(password, row[3]):
            user = User(id=row[0], username=row[1], email=row[2])
            login_user(user)
            session.permanent = True
            current_app.logger.info(
                f"LOGIN SUCCESS | user_id={user.id} | username={user.username} | ip={request.remote_addr}"
            )
            log_audit('LOGIN_SUCCESS', 'User logged in', user_id=user.id, username=user.username)
            return redirect(url_for('prescriptions.dashboard'))
        else:
            current_app.logger.warning(
                f"LOGIN FAILED | identifier={identifier} | ip={request.remote_addr}"
            )
            log_audit('LOGIN_FAILED', f'Failed login attempt for: {identifier}', user_id=None, username=identifier)
            flash('Invalid credentials.', 'danger')

    return render_template('login.html')


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        email = request.form['email'].strip()
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        errors = []
        if not re.match(r'^[\w\.-]+@[\w\.-]+\.\w{2,}$', email):
            errors.append('Invalid email format.')
        if len(password) < 8:
            errors.append('Password must be at least 8 characters.')
        if not re.search(r'[A-Z]', password):
            errors.append('Password must contain at least one uppercase letter.')
        if not re.search(r'[!@#$%^&*(),.?\":{}|<>]', password):
            errors.append('Password must contain at least one special character.')
        if password != confirm_password:
            errors.append('Passwords do not match.')

        if errors:
            for error in errors:
                flash(error, 'danger')
            return render_template('register.html', username=username, email=email)

        hashed = hash_password(password)

        try:
            cur = mysql.connection.cursor()
            cur.execute(
                "INSERT INTO users (username, email, password_hash) VALUES (%s, %s, %s)",
                (username, email, hashed)
            )
            mysql.connection.commit()
            cur.close()
            current_app.logger.info(
                f"REGISTER SUCCESS | username={username} | email={email} | ip={request.remote_addr}"
            )
            log_audit('REGISTER', f'New account created with email: {email}', username=username)
            flash('Account created! Please log in.', 'success')
            return redirect(url_for('auth.login'))
        except Exception as e:
            current_app.logger.error(
                f"REGISTER FAILED | username={username} | error={str(e)}"
            )
            flash('Email or username already exists.', 'danger')

    return render_template('register.html', username='', email='')


@auth_bp.route('/logout')
@login_required
def logout():
    current_app.logger.info(
        f"LOGOUT | user_id={current_user.id} | username={current_user.username}"
    )
    log_audit('LOGOUT', 'User logged out')
    logout_user()
    return redirect(url_for('auth.login'))


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
@limiter.limit("3 per minute")
def forgot_password():
    if request.method == 'POST':
        email = request.form['email'].strip()

        cur = mysql.connection.cursor()
        cur.execute("SELECT id, username FROM users WHERE email = %s", (email,))
        row = cur.fetchone()

        if row:
            user_id = row[0]
            username = row[1]

            token = secrets.token_urlsafe(32)
            expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

            cur.execute(
                "INSERT INTO password_reset_tokens (user_id, token, expires_at) "
                "VALUES (%s, %s, %s)",
                (user_id, token, expires_at)
            )
            mysql.connection.commit()

            reset_url = url_for('auth.reset_password', token=token, _external=True)
            msg = Message(
                subject='CareCrypt — Password Reset Request',
                recipients=[email]
            )
            msg.body = f"""Hi {username},

You requested a password reset for your CareCrypt account.

Click the link below to reset your password (valid for 1 hour):
{reset_url}

If you did not request this, please ignore this email.

— CareCrypt
"""
            mail.send(msg)
            current_app.logger.info(
                f"PASSWORD RESET REQUESTED | user_id={user_id} | email={email}"
            )
            log_audit('PASSWORD_RESET_REQUESTED', f'Reset requested for email: {email}', user_id=user_id)

        cur.close()
        # Always show success to prevent email enumeration
        flash('If that email exists, a reset link has been sent.', 'info')
        return redirect(url_for('auth.login'))

    return render_template('forgot_password.html')


@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    cur = mysql.connection.cursor()
    cur.execute(
        "SELECT user_id, expires_at, used FROM password_reset_tokens "
        "WHERE token = %s",
        (token,)
    )
    row = cur.fetchone()

    if not row:
        flash('Invalid or expired reset link.', 'danger')
        return redirect(url_for('auth.login'))

    user_id = row[0]
    expires_at = row[1]
    used = row[2]

    if used or datetime.now(timezone.utc) > expires_at.replace(tzinfo=timezone.utc):
        cur.close()
        flash('This reset link has expired or already been used.', 'danger')
        return redirect(url_for('auth.forgot_password'))

    if request.method == 'POST':
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        errors = []
        if len(password) < 8:
            errors.append('Password must be at least 8 characters.')
        if not re.search(r'[A-Z]', password):
            errors.append('Password must contain at least one uppercase letter.')
        if not re.search(r'[!@#$%^&*(),.?\":{}|<>]', password):
            errors.append('Password must contain at least one special character.')
        if password != confirm_password:
            errors.append('Passwords do not match.')

        if errors:
            for error in errors:
                flash(error, 'danger')
            cur.close()
            return render_template('reset_password.html', token=token)

        hashed = hash_password(password)

        cur.execute(
            "UPDATE users SET password_hash = %s WHERE id = %s",
            (hashed, user_id)
        )
        cur.execute(
            "UPDATE password_reset_tokens SET used = 1 WHERE token = %s",
            (token,)
        )
        mysql.connection.commit()
        cur.close()

        current_app.logger.info(f"PASSWORD RESET SUCCESS | user_id={user_id}")
        log_audit('PASSWORD_RESET_SUCCESS', 'Password was reset successfully', user_id=user_id)
        flash('Password reset successfully! Please log in.', 'success')
        return redirect(url_for('auth.login'))

    cur.close()
    return render_template('reset_password.html', token=token)


@auth_bp.before_request
def check_session_timeout():
    if current_user.is_authenticated:
        last_active = session.get('last_active')
        now = datetime.now(timezone.utc).timestamp()

        if last_active and (now - last_active) > 900:
            current_app.logger.info(
                f"SESSION TIMEOUT | user_id={current_user.id} | username={current_user.username}"
            )
            log_audit('SESSION_TIMEOUT', 'Session expired due to inactivity')
            logout_user()
            session.clear()
            flash('Your session expired due to inactivity. Please log in again.', 'warning')
            return redirect(url_for('auth.login'))

        session['last_active'] = now