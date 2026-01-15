"""
Background scheduler for automated tasks like weekly reports.
Uses APScheduler for reliable background job execution.

NOTE: On Vercel serverless, APScheduler won't work. Use external cron
service (like cron-job.org) to call /api/cron/weekly-reports instead.
"""

import atexit
from datetime import datetime
from app.logger import log_info, log_error, log_warning

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    SCHEDULER_AVAILABLE = True
except ImportError:
    SCHEDULER_AVAILABLE = False
    log_warning("APScheduler not available - use /api/cron/weekly-reports endpoint instead", tag="Scheduler")

# Global scheduler instance
scheduler = None


def send_weekly_reports_job():
    """Job to generate and send weekly reports every Monday at 8 AM"""
    from app import app, db
    from app.reports import generate_all_weekly_reports, get_report_email_html
    from app.email_service import send_report_email, is_email_configured
    
    with app.app_context():
        log_info(f"Starting weekly report generation at {datetime.utcnow()}", tag="Scheduler")
        
        try:
            # Generate reports for all years
            reports = generate_all_weekly_reports()
            log_info(f"Generated {len(reports)} reports", tag="Scheduler")
            
            # Send emails if configured
            if is_email_configured():
                for report in reports:
                    html_content = get_report_email_html(report)
                    success, message = send_report_email(report, html_content)
                    
                    if success:
                        log_info(f"Email sent for Year {report.year}", tag="Scheduler")
                    else:
                        log_error(f"Failed to send email for Year {report.year}: {message}", tag="Scheduler")
            else:
                log_info("Email not configured - reports saved to dashboard only", tag="Scheduler")
                
        except Exception as e:
            log_error(f"Error in weekly report job: {e}", tag="Scheduler")


def init_scheduler(app):
    """Initialize and start the background scheduler"""
    global scheduler
    
    if not SCHEDULER_AVAILABLE:
        log_warning("APScheduler not installed, skipping initialization", tag="Scheduler")
        return None
    
    if scheduler is not None:
        return scheduler
    
    scheduler = BackgroundScheduler()
    
    # Weekly report: Monday at 8 AM (local time)
    scheduler.add_job(
        func=send_weekly_reports_job,
        trigger=CronTrigger(
            day_of_week='mon',
            hour=8,
            minute=0
        ),
        id='weekly_report_job',
        name='Send Weekly Reports to HoD',
        replace_existing=True
    )
    
    scheduler.start()
    log_info("Background scheduler initialized", tag="Scheduler")
    log_info("Weekly reports scheduled for Monday 8:00 AM", tag="Scheduler")
    
    # Shut down scheduler when app exits
    atexit.register(lambda: scheduler.shutdown(wait=False))
    
    return scheduler


def get_scheduler_status() -> dict:
    """Get current scheduler status and next run times"""
    global scheduler
    
    if scheduler is None:
        return {"status": "not_initialized", "jobs": []}
    
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None
        })
    
    return {
        "status": "running" if scheduler.running else "stopped",
        "jobs": jobs
    }


def trigger_weekly_reports_now():
    """Manually trigger weekly report generation"""
    global scheduler
    
    if scheduler is None:
        # Run directly without scheduler
        send_weekly_reports_job()
    else:
        # Add a one-time job to run immediately
        scheduler.add_job(
            func=send_weekly_reports_job,
            id='manual_weekly_report',
            replace_existing=True
        )
