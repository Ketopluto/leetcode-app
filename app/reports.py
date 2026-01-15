"""
Weekly Report Generation for HoD
Generates year-wise reports on student LeetCode activity
"""

import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from flask import render_template_string

from app import db
from app.models import Student, StudentStats, WeeklyReport

# Configuration
INCONSISTENT_THRESHOLD = 5  # < 5 problems = inconsistent solver


def get_week_boundaries(for_date: datetime = None) -> tuple:
    """Get the start and end of the week (Monday to Sunday)"""
    if for_date is None:
        for_date = datetime.utcnow()
    
    # Get Monday of the current week
    days_since_monday = for_date.weekday()
    week_start = for_date - timedelta(days=days_since_monday)
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Get Sunday (end of week)
    week_end = week_start + timedelta(days=6, hours=23, minutes=59, seconds=59)
    
    return week_start, week_end


def generate_report_for_year(year: int, section: str = None) -> WeeklyReport:
    """
    Generate a weekly report for a specific year (and optionally section).
    
    Categories:
    - Zero Solvers: Students with 0 problems solved
    - Inconsistent: Students with < 5 problems solved (all-time)
    - Active: Students with >= 5 problems solved
    
    Note: "higher studies" students are excluded from reports.
    """
    week_start, week_end = get_week_boundaries()
    
    # Query students
    query = Student.query.filter_by(year=year)
    if section:
        query = query.filter_by(section=section)
    
    students = query.all()
    
    if not students:
        return None
    
    # Categorize students
    zero_solvers = []
    inconsistent_solvers = []
    active_solvers = []
    excluded_count = 0  # higher studies
    
    for student in students:
        # Skip "higher studies" students
        username = (student.leetcode_username or "").strip().lower()
        if username == "higher studies":
            excluded_count += 1
            continue
        
        stats = StudentStats.query.filter_by(student_id=student.id).first()
        
        total = stats.total_solved if stats else 0
        
        student_data = {
            "register_number": student.register_number,
            "name": student.name,
            "leetcode_username": student.leetcode_username,
            "total_solved": total,
            "easy": stats.easy_solved if stats else 0,
            "medium": stats.medium_solved if stats else 0,
            "hard": stats.hard_solved if stats else 0,
        }
        
        if total == 0:
            zero_solvers.append(student_data)
        elif total < INCONSISTENT_THRESHOLD:
            inconsistent_solvers.append(student_data)
        else:
            active_solvers.append(student_data)
    
    # Sort by register number
    zero_solvers.sort(key=lambda x: x["register_number"])
    inconsistent_solvers.sort(key=lambda x: x["register_number"])
    active_solvers.sort(key=lambda x: x["register_number"])
    
    # Create report data
    data = {
        "zero_solvers": zero_solvers,
        "inconsistent_solvers": inconsistent_solvers,
        "active_solvers": active_solvers,
        "threshold": INCONSISTENT_THRESHOLD
    }
    
    # Create and save report
    report = WeeklyReport(
        year=year,
        section=section,
        report_date=datetime.utcnow(),
        week_start=week_start,
        week_end=week_end,
        total_students=len(students) - excluded_count,  # Exclude "higher studies"
        zero_count=len(zero_solvers),
        inconsistent_count=len(inconsistent_solvers),
        active_count=len(active_solvers),
        data_json=json.dumps(data)
    )
    
    db.session.add(report)
    db.session.commit()
    
    return report


def generate_all_weekly_reports() -> List[WeeklyReport]:
    """Generate reports for all years"""
    reports = []
    
    # Get unique year/section combinations
    year_sections = db.session.query(
        Student.year,
        Student.section
    ).distinct().all()
    
    for year, section in year_sections:
        report = generate_report_for_year(year, section)
        if report:
            reports.append(report)
    
    return reports


def get_report_email_html(report: WeeklyReport) -> str:
    """Generate HTML email content for a weekly report"""
    data = json.loads(report.data_json) if report.data_json else {}
    
    year_suffix = 'st' if report.year == 1 else 'nd' if report.year == 2 else 'rd' if report.year == 3 else 'th'
    year_str = f"{report.year}{year_suffix} Year"
    if report.section:
        year_str += f" (Section {report.section})"
    
    template = """
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; color: #333; }
        .header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 8px; }
        .stats-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; margin: 20px 0; }
        .stat-card { background: #f8f9fa; padding: 15px; border-radius: 8px; text-align: center; }
        .stat-number { font-size: 32px; font-weight: bold; }
        .stat-label { color: #666; font-size: 12px; }
        .zero { color: #dc3545; }
        .inconsistent { color: #fd7e14; }
        .active { color: #28a745; }
        table { width: 100%; border-collapse: collapse; margin: 15px 0; }
        th, td { border: 1px solid #dee2e6; padding: 10px; text-align: left; }
        th { background: #f8f9fa; }
        .section-header { margin-top: 25px; padding: 10px; background: #f1f3f4; border-radius: 5px; }
        .alert { padding: 15px; border-radius: 5px; margin: 10px 0; }
        .alert-warning { background: #fff3cd; border-left: 4px solid #ffc107; }
        .alert-danger { background: #f8d7da; border-left: 4px solid #dc3545; }
    </style>
</head>
<body>
    <div class="header">
        <h1>Weekly LeetCode Report</h1>
        <p>{{ year_str }} | Week of {{ week_start }} - {{ week_end }}</p>
    </div>
    
    <div class="stats-grid">
        <div class="stat-card">
            <div class="stat-number zero">{{ zero_count }}</div>
            <div class="stat-label">ZERO SOLVERS</div>
        </div>
        <div class="stat-card">
            <div class="stat-number inconsistent">{{ inconsistent_count }}</div>
            <div class="stat-label">INCONSISTENT (&lt; {{ threshold }})</div>
        </div>
        <div class="stat-card">
            <div class="stat-number active">{{ active_count }}</div>
            <div class="stat-label">ACTIVE SOLVERS</div>
        </div>
    </div>
    
    {% if zero_solvers %}
    <div class="section-header">
        <h3 class="zero">Zero Solvers ({{ zero_solvers|length }} students)</h3>
    </div>
    <div class="alert alert-danger">
        These students have not solved any problems on LeetCode.
    </div>
    <table>
        <tr><th>Register No</th><th>Name</th><th>LeetCode Username</th></tr>
        {% for s in zero_solvers %}
        <tr><td>{{ s.register_number }}</td><td>{{ s.name }}</td><td>{{ s.leetcode_username }}</td></tr>
        {% endfor %}
    </table>
    {% endif %}
    
    {% if inconsistent_solvers %}
    <div class="section-header">
        <h3 class="inconsistent">Inconsistent Solvers ({{ inconsistent_solvers|length }} students)</h3>
    </div>
    <div class="alert alert-warning">
        These students have solved fewer than {{ threshold }} problems.
    </div>
    <table>
        <tr><th>Register No</th><th>Name</th><th>LeetCode</th><th>Easy</th><th>Medium</th><th>Hard</th><th>Total</th></tr>
        {% for s in inconsistent_solvers %}
        <tr>
            <td>{{ s.register_number }}</td>
            <td>{{ s.name }}</td>
            <td>{{ s.leetcode_username }}</td>
            <td>{{ s.easy }}</td>
            <td>{{ s.medium }}</td>
            <td>{{ s.hard }}</td>
            <td>{{ s.total_solved }}</td>
        </tr>
        {% endfor %}
    </table>
    {% endif %}
    
    <p style="color: #888; font-size: 12px; margin-top: 30px;">
        Generated on {{ report_date }} | Total Students: {{ total_students }}
    </p>
</body>
</html>
    """
    
    from jinja2 import Template
    jinja_template = Template(template)
    
    return jinja_template.render(
        year_str=year_str,
        week_start=report.week_start.strftime("%B %d, %Y"),
        week_end=report.week_end.strftime("%B %d, %Y"),
        zero_count=report.zero_count,
        inconsistent_count=report.inconsistent_count,
        active_count=report.active_count,
        threshold=data.get("threshold", INCONSISTENT_THRESHOLD),
        zero_solvers=data.get("zero_solvers", []),
        inconsistent_solvers=data.get("inconsistent_solvers", []),
        total_students=report.total_students,
        report_date=report.report_date.strftime("%B %d, %Y at %I:%M %p")
    )


def get_report_summary(report: WeeklyReport) -> dict:
    """Get a summary of a report for API responses"""
    data = json.loads(report.data_json) if report.data_json else {}
    
    year_suffix = 'st' if report.year == 1 else 'nd' if report.year == 2 else 'rd' if report.year == 3 else 'th'
    year_str = f"{report.year}{year_suffix} Year"
    if report.section:
        year_str += f" ({report.section})"
    
    return {
        "id": report.id,
        "year": report.year,
        "year_display": year_str,
        "section": report.section,
        "report_date": report.report_date.isoformat(),
        "week_start": report.week_start.isoformat(),
        "week_end": report.week_end.isoformat(),
        "total_students": report.total_students,
        "zero_count": report.zero_count,
        "inconsistent_count": report.inconsistent_count,
        "active_count": report.active_count,
        "email_sent": report.email_sent,
        "threshold": data.get("threshold", INCONSISTENT_THRESHOLD)
    }
