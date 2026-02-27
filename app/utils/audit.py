from app import mysql
from flask import request
from flask_login import current_user

def log_audit(action: str, details: str = None, user_id=None, username=None):
    try:
        uid = user_id or (current_user.id if current_user.is_authenticated else None)
        uname = username or (current_user.username if current_user.is_authenticated else 'anonymous')
        ip = request.remote_addr

        cur = mysql.connection.cursor()
        cur.execute(
            "INSERT INTO audit_logs (user_id, username, action, details, ip_address) "
            "VALUES (%s, %s, %s, %s, %s)",
            (uid, uname, action, details, ip)
        )
        mysql.connection.commit()
        cur.close()
    except Exception as e:
        print(f"Audit log error: {e}")