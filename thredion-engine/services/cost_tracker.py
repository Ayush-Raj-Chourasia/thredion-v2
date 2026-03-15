"""
Cost Tracker — Budget Management & Rate Limiting

Prevents runaway costs by enforcing:
- Daily budget limits
- Monthly budget limits  
- Per-service rate limits (requests/hour)
- Per-service daily spend limits

All paid APIs (SocialKit, Supadata, 2Captcha, etc) must check these guardrails
before making expensive calls.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


class CostService(Enum):
    """Supported paid API services."""
    SOCIALKIT = "socialkit"
    SUPADATA = "supadata"
    TRANSCRIPT24 = "transcript24"
    TWOCAPTCHA = "2captcha"
    ANTICAPTCHA = "anticaptcha"


class CostTracker:
    """
    Track and enforce budget limits for paid APIs.
    
    This is a skeleton - in production should use:
    - Database to store cost_logs table
    - Redis for rate limit counters
    - Scheduled cleanup of old logs
    """
    
    # Global budgets (configurable)
    DAILY_BUDGET = 10.00  # dollars per day
    MONTHLY_BUDGET = 200.00  # dollars per month
    
    # Per-service limits
    SERVICE_CONFIG = {
        CostService.SOCIALKIT: {
            "hourly_requests": 30,
            "daily_spend": 5.00,
            "monthly_spend": 100.00,
            "cost_per_call": 0.50,  # ~$0.50-$2.00 per extraction
        },
        CostService.SUPADATA: {
            "hourly_requests": 20,
            "daily_spend": 3.00,
            "monthly_spend": 75.00,
            "cost_per_call": 1.00,  # ~$1.00-$3.00 per extraction
        },
        CostService.TRANSCRIPT24: {
            "hourly_requests": 10,
            "daily_spend": 2.00,
            "monthly_spend": 50.00,
            "cost_per_call": 1.00,  # $1.00 per credit = ~10 min video
        },
        CostService.TWOCAPTCHA: {
            "hourly_requests": 100,
            "daily_spend": 5.00,
            "monthly_spend": 100.00,
            "cost_per_call": 0.01,  # Very cheap, ~0.01-0.05 per captcha
        },
    }
    
    def __init__(self):
        """Initialize cost tracker (would connect to DB in production)."""
        self.cost_logs = []  # In-memory, replace with DB query in production
    
    def should_use_paid_api(
        self, service: CostService, user_id: str
    ) -> Tuple[bool, str]:
        """
        Check if we should call a paid API.
        
        Returns:
            (should_use: bool, reason: str)
        """
        
        # Check 1: Global daily budget
        today_spend = self._get_today_spend()
        if today_spend >= self.DAILY_BUDGET:
            reason = f"Daily budget exhausted: ${today_spend:.2f} >= ${self.DAILY_BUDGET:.2f}"
            logger.warning(f"🛑 {reason}")
            return False, reason
        
        # Check 2: Global monthly budget
        this_month_spend = self._get_month_spend()
        if this_month_spend >= self.MONTHLY_BUDGET:
            reason = f"Monthly budget exhausted: ${this_month_spend:.2f} >= ${self.MONTHLY_BUDGET:.2f}"
            logger.warning(f"🛑 {reason}")
            return False, reason
        
        # Check 3: Service-specific daily limit
        config = self.SERVICE_CONFIG[service]
        service_daily = self._get_service_spend(service, days=1)
        if service_daily >= config["daily_spend"]:
            reason = f"{service.value} daily limit hit: ${service_daily:.2f} >= ${config['daily_spend']:.2f}"
            logger.warning(f"🛑 {reason}")
            return False, reason
        
        # Check 4: Service-specific monthly limit
        service_monthly = self._get_service_spend(service, days=30)
        if service_monthly >= config["monthly_spend"]:
            reason = f"{service.value} monthly limit hit: ${service_monthly:.2f} >= ${config['monthly_spend']:.2f}"
            logger.warning(f"🛑 {reason}")
            return False, reason
        
        # Check 5: Service-specific hourly rate limit
        service_hourly_requests = self._get_service_requests(service, hours=1)
        if service_hourly_requests >= config["hourly_requests"]:
            reason = f"{service.value} hourly rate limit hit: {service_hourly_requests} >= {config['hourly_requests']}"
            logger.warning(f"🛑 {reason}")
            return False, reason
        
        # All checks passed
        estimated_cost = config.get("cost_per_call", 0)
        reason = f"✅ OK to use {service.value} (est. ${estimated_cost:.2f})"
        logger.debug(reason)
        return True, reason
    
    def log_cost(
        self,
        service: CostService,
        cost: float,
        user_id: str,
        job_id: str,
        success: bool,
        error_reason: str = None,
    ):
        """
        Record a cost transaction.
        
        In production, this would insert into cost_logs table:
        
        INSERT INTO cost_logs (
            service, cost, user_id, job_id, success, 
            error_reason, timestamp
        ) VALUES (...)
        """
        
        log_entry = {
            "service": service.value,
            "cost": cost,
            "user_id": user_id,
            "job_id": job_id,
            "success": success,
            "error_reason": error_reason,
            "timestamp": datetime.utcnow(),
        }
        
        self.cost_logs.append(log_entry)
        
        if success:
            logger.info(f"💰 {service.value}: ${cost:.2f} spent for job {job_id}")
        else:
            logger.warning(f"💰 {service.value}: ${cost:.2f} spent but FAILED: {error_reason}")
    
    # ── Private helpers (would be SQL queries in production) ────────────────
    
    def _get_today_spend(self) -> float:
        """Sum of all costs today."""
        today = datetime.utcnow().date()
        return sum(
            log["cost"]
            for log in self.cost_logs
            if log["timestamp"].date() == today and log["success"]
        )
    
    def _get_month_spend(self) -> float:
        """Sum of all costs this month."""
        now = datetime.utcnow()
        month_start = now.replace(day=1)
        return sum(
            log["cost"]
            for log in self.cost_logs
            if log["timestamp"] >= month_start and log["success"]
        )
    
    def _get_service_spend(self, service: CostService, days: int = 1) -> float:
        """Sum of costs for specific service in last N days."""
        cutoff = datetime.utcnow() - timedelta(days=days)
        return sum(
            log["cost"]
            for log in self.cost_logs
            if log["service"] == service.value and log["timestamp"] >= cutoff and log["success"]
        )
    
    def _get_service_requests(self, service: CostService, hours: int = 1) -> int:
        """Count requests to specific service in last N hours."""
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        return len(
            [
                log for log in self.cost_logs
                if log["service"] == service.value and log["timestamp"] >= cutoff
            ]
        )


# Global instance
cost_tracker = CostTracker()
