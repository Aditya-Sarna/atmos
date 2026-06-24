"""
Swarm Testing API Endpoints and Integration for Atmos.

New endpoints:
- POST /api/runs/{run_id}/swarm/config - Set load test parameters
- GET /api/runs/{run_id}/swarm/results - Get swarm test results
- POST /api/runs/{run_id}/swarm/ship-report - Generate Ship Report
"""

from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from enum import Enum


class LoadProfileType(str, Enum):
    """Load testing profile types."""
    BURST = "burst"
    RAMP = "ramp"
    SOAK = "soak"


class UserModeType(str, Enum):
    """Concurrent user targets."""
    STARTUP = "startup"       # 10-500 users
    GROWTH = "growth"         # 1000-10000 users
    ENTERPRISE = "enterprise" # 25000+ users


class JourneyTemplateType(str, Enum):
    """Predefined user journey templates."""
    ECOMMERCE = "ecommerce"   # Browse → Add to cart → Checkout
    FINANCE = "finance"       # Login → Payment info → Transfer
    SAAS = "saas"             # Sign up → Dashboard


class SwarmConfigBody(BaseModel):
    """Configuration for swarm load testing."""
    profile: LoadProfileType = LoadProfileType.BURST
    user_mode: Optional[UserModeType] = None
    target_users: Optional[int] = None
    journey_template: JourneyTemplateType = JourneyTemplateType.ECOMMERCE
    duration_secs: int = 60
    payment_provider: Optional[str] = None  # "stripe", "paypal", "razorpay"
    
    class Config:
        description = "Configure load test parameters"


class SwarmResultsResponse(BaseModel):
    """Response containing swarm test results."""
    test_id: str
    profile: str
    target_users: int
    success_rate: float
    error_rate: float
    latency_p50_ms: float
    latency_p95_ms: float
    latency_p99_ms: float
    breaking_point_users: Optional[int]
    revenue_risk_per_hour: float
    status: str


class ShipReportResponse(BaseModel):
    """Ship report response."""
    readiness: str  # "ship_now", "warnings", "not_ready", "critical"
    confidence_score: int
    executive_summary: str
    can_users_use_it: bool
    can_handle_peak_users: int
    are_payments_working: bool
    checkout_abandonment_risk: str
    top_3_issues: List[str]
    launch_blockers: List[str]
    recommendations: List[str]
