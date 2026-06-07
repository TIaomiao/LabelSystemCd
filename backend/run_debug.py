
import sys
from app import app
from extensions import db
from models import User

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    with app.app_context():
        db.create_all()
        # Create a test user if not exists
        if not User.query.filter_by(username='test_user').first():
            u = User(username='test_user')
            u.set_password('password123')
            db.session.add(u)
            db.session.commit()
            print("Created test_user")
            
    print(f"Starting debug server on {port}...")
    app.run(debug=True, port=port)
