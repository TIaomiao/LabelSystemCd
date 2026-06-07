from app import app
from extensions import db
from models import StructureAssessment

if __name__ == '__main__':
    with app.app_context():
        try:
            StructureAssessment.__table__.drop(db.engine)
            print("Table StructureAssessment dropped.")
        except Exception as e:
            print(f"Error dropping table (might not exist): {e}")
        
        db.create_all()
        print("All tables created (including StructureAssessment).")
