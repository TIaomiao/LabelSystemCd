from app import app
from extensions import db
from models import CardiacAnnotation

with app.app_context():
    print("Creating CardiacAnnotation table...")
    db.create_all()
    print("Done!")
