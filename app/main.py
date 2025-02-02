from app import app, db

if __name__ == '__main__':
    with app.app_context():
        db.create_all()  # Create required tables in the database if they don't exist.
    app.run(debug=True)
