"""
Email service for sending weekly reports to HoD
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from datetime import datetime

from app.models import WeeklyReport
from app import db

# Email configuration from environment
SMTP_SERVER = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
SMTP_USERNAME = os.environ.get('SMTP_USERNAME', '')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')
HOD_EMAIL = os.environ.get('HOD_EMAIL', '')
FROM_EMAIL = os.environ.get('FROM_EMAIL', SMTP_USERNAME)


def is_email_configured() -> bool:
    """Check if email settings are properly configured"""
    return bool(SMTP_USERNAME and SMTP_PASSWORD and HOD_EMAIL)


def send_email(
    to_email: str,
    subject: str,
    html_content: str,
    from_email: str = None
) -> tuple[bool, str]:
    """
    Send an email using SMTP.
    Returns (success, message)
    """
    if not is_email_configured():
        return False, "Email not configured. Set SMTP_USERNAME, SMTP_PASSWORD, and HOD_EMAIL environment variables."
    
    from_email = from_email or FROM_EMAIL
    
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = from_email
        msg['To'] = to_email
        
        html_part = MIMEText(html_content, 'html')
        msg.attach(html_part)
        
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(from_email, to_email, msg.as_string())
        
        return True, "Email sent successfully"
        
    except smtplib.SMTPAuthenticationError:
        return False, "SMTP authentication failed. Check username and password."
    except smtplib.SMTPException as e:
        return False, f"SMTP error: {str(e)}"
    except Exception as e:
        return False, f"Failed to send email: {str(e)}"


def send_report_email(report: WeeklyReport, html_content: str) -> tuple[bool, str]:
    """
    Send a weekly report email to HoD.
    Updates the report record with email status.
    """
    if not HOD_EMAIL:
        return False, "HOD_EMAIL not configured"
    
    year_suffix = 'st' if report.year == 1 else 'nd' if report.year == 2 else 'rd' if report.year == 3 else 'th'
    year_str = f"{report.year}{year_suffix} Year"
    if report.section:
        year_str += f" ({report.section})"
    
    subject = f"Weekly LeetCode Report - {year_str} | {report.week_start.strftime('%b %d')} - {report.week_end.strftime('%b %d, %Y')}"
    
    success, message = send_email(HOD_EMAIL, subject, html_content)
    
    # Update report with email status
    report.email_sent = success
    report.email_sent_at = datetime.utcnow() if success else None
    db.session.commit()
    
    return success, message


def get_email_status() -> dict:
    """Get current email configuration status"""
    return {
        "configured": is_email_configured(),
        "smtp_server": SMTP_SERVER,
        "smtp_port": SMTP_PORT,
        "from_email": FROM_EMAIL if is_email_configured() else None,
        "hod_email": HOD_EMAIL if HOD_EMAIL else None
    }
