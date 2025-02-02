from datetime import datetime
from app import db

class StudentStats(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # Note: we're now using a composite uniqueness by filtering on both username and roll_no in the process_student function,
    # so we do not enforce unique constraint here. Adjust as needed.
    username = db.Column(db.String(80), nullable=False)
    actual_name = db.Column(db.String(120))
    roll_no = db.Column(db.String(20), nullable=False)
    easy = db.Column(db.Integer, default=0)
    medium = db.Column(db.Integer, default=0)
    hard = db.Column(db.Integer, default=0)
    total = db.Column(db.Integer, default=0)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<StudentStats {self.username} - {self.roll_no}>'
