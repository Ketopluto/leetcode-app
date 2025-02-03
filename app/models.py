from datetime import datetime
from app import db

class StudentStats(db.Model):
    __tablename__ = 'student_stats'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False)
    actual_name = db.Column(db.String(120))
    roll_no = db.Column(db.String(20), unique=True, nullable=False)  # ensure uniqueness
    # Updated column names to reflect new API data
    easy_solved = db.Column(db.Integer, default=0)
    medium_solved = db.Column(db.Integer, default=0)
    hard_solved = db.Column(db.Integer, default=0)
    total_solved = db.Column(db.Integer, default=0)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<StudentStats {self.username} - {self.roll_no}>'
