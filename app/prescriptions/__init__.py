from flask import Blueprint

prescriptions_bp = Blueprint("prescriptions", __name__)

from app.prescriptions import routes