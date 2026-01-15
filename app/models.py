from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import re

db = SQLAlchemy()

class Student(db.Model):
    __tablename__ = 'students'
    
    id = db.Column(db.Integer, primary_key=True)
    register_number = db.Column(db.String(20), unique=True, nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    leetcode_username = db.Column(db.String(50), nullable=False)
    year = db.Column(db.Integer, nullable=False)  # 1, 2, 3, or 4
    section = db.Column(db.String(10), nullable=True)  # A, B, C, etc. or None
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<Student {self.register_number} - {self.name}>'
    
    @staticmethod
    def extract_username_from_url(url_or_username):
        """
        Extract username from LeetCode profile URL or return username as-is.
        Examples:
        - https://leetcode.com/u/username/ -> username
        - https://leetcode.com/username/ -> username
        - username -> username
        """
        if not url_or_username:
            return None
        
        url_or_username = url_or_username.strip()
        
        if 'leetcode.com' in url_or_username.lower():
            patterns = [
                r'leetcode\.com/u/([^/]+)',
                r'leetcode\.com/([^/]+)',
            ]
            for pattern in patterns:
                match = re.search(pattern, url_or_username)
                if match:
                    return match.group(1)
        
        return url_or_username

class UploadLog(db.Model):
    __tablename__ = 'upload_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(200), nullable=False)
    records_added = db.Column(db.Integer, default=0)
    records_updated = db.Column(db.Integer, default=0)
    upload_time = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='success')
    error_message = db.Column(db.Text, nullable=True)
    
    def __repr__(self):
        return f'<UploadLog {self.filename} at {self.upload_time}>'


class StudentStats(db.Model):
    """Persistent cache of last known LeetCode stats for each student"""
    __tablename__ = 'student_stats'
    
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), unique=True, nullable=False)
    easy_solved = db.Column(db.Integer, default=0)
    medium_solved = db.Column(db.Integer, default=0)
    hard_solved = db.Column(db.Integer, default=0)
    total_solved = db.Column(db.Integer, default=0)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)
    is_stale = db.Column(db.Boolean, default=False)
    
    student = db.relationship('Student', backref=db.backref('stats', uselist=False))
    
    def __repr__(self):
        return f'<StudentStats {self.student_id}: {self.total_solved} solved>'


class WeeklyReport(db.Model):
    """Weekly report for HoD showing student activity"""
    __tablename__ = 'weekly_reports'
    
    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False)
    section = db.Column(db.String(10), nullable=True)
    report_date = db.Column(db.DateTime, default=datetime.utcnow)
    week_start = db.Column(db.DateTime, nullable=False)
    week_end = db.Column(db.DateTime, nullable=False)
    total_students = db.Column(db.Integer, default=0)
    inconsistent_count = db.Column(db.Integer, default=0)  # < threshold solved
    zero_count = db.Column(db.Integer, default=0)          # 0 problems total
    active_count = db.Column(db.Integer, default=0)        # >= threshold solved
    data_json = db.Column(db.Text, nullable=True)          # Detailed breakdown JSON
    email_sent = db.Column(db.Boolean, default=False)
    email_sent_at = db.Column(db.DateTime, nullable=True)
    
    def __repr__(self):
        return f'<WeeklyReport Year {self.year} - {self.report_date}>'

