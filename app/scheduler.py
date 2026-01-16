"""
Background scheduler for automated tasks like weekly reports and stats refresh.
Uses APScheduler for reliable background job execution.

NOTE: On Vercel serverless, APScheduler won't work. Use external cron
service (like cron-job.org) to call /api/cron/weekly-reports instead.
"""

import atexit
import os
from datetime import datetime
from app.logger import log_info, log_error, log_warning

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger
    SCHEDULER_AVAILABLE = True
except ImportError:
    SCHEDULER_AVAILABLE = False
    log_warning("APScheduler not available - use /api/cron/weekly-reports endpoint instead", tag="Scheduler")

# Global scheduler instance
scheduler = None

# Configurable refresh interval (in minutes)
STATS_REFRESH_INTERVAL = int(os.environ.get('STATS_REFRESH_INTERVAL', 30))


def refresh_all_stats_job():
    """Job to refresh all student stats from LeetCode API"""
    from app import app, db, cache
    from app.routes import get_all_stats
    
    with app.app_context():
        log_info(f"Starting automatic stats refresh at {datetime.utcnow()}", tag="Scheduler")
        
        try:
            # Clear memory cache to force fresh fetch
            try:
                cache.clear()
                log_info("Memory cache cleared", tag="Scheduler")
            except Exception as e:
                log_warning(f"Could not clear cache: {e}", tag="Scheduler")
            
            # Fetch fresh stats (this also updates the database)
            import time
            start_time = time.time()
            results = get_all_stats()
            elapsed = time.time() - start_time
            
            log_info(f"Stats refresh completed: {len(results)} students updated in {elapsed:.1f}s", tag="Scheduler")
            
        except Exception as e:
            log_error(f"Error in stats refresh job: {e}", tag="Scheduler")


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
    
    # Check if running on Vercel (don't start scheduler there)
    IS_VERCEL = os.environ.get('VERCEL') or os.environ.get('VERCEL_ENV')
    if IS_VERCEL:
        log_info("Running on Vercel - scheduler disabled, use cron endpoints instead", tag="Scheduler")
        return None
    
    scheduler = BackgroundScheduler()
    
    # Stats refresh: Every 30 minutes (configurable via STATS_REFRESH_INTERVAL env var)
    scheduler.add_job(
        func=refresh_all_stats_job,
        trigger=IntervalTrigger(minutes=STATS_REFRESH_INTERVAL),
        id='stats_refresh_job',
        name=f'Refresh LeetCode Stats (every {STATS_REFRESH_INTERVAL} min)',
        replace_existing=True
    )
    
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
    log_info(f"Stats refresh scheduled every {STATS_REFRESH_INTERVAL} minutes", tag="Scheduler")
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


def trigger_stats_refresh_now():
    """Manually trigger stats refresh"""
    global scheduler
    
    if scheduler is None:
        # Run directly without scheduler
        refresh_all_stats_job()
    else:
        # Add a one-time job to run immediately
        scheduler.add_job(
            func=refresh_all_stats_job,
            id='manual_stats_refresh',
            replace_existing=True
        )

