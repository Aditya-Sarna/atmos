"""
Concurrent user swarm testing engine for Atmos.

Handles:
- Multiple concurrent browser contexts
- Realistic user journeys (e-commerce, finance, SaaS)
- Metrics collection (latency, errors, throughput)
- Load profiles (Burst, Ramp, Soak)
- Business impact analysis
"""

import asyncio
import os
import time
import statistics
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum
import logging
from playwright.async_api import Browser, BrowserContext, Page
import random
import string

logger = logging.getLogger(__name__)


class LoadProfile(Enum):
    """Load testing profile types."""
    BURST = "burst"           # 0 → target users instantly
    RAMP = "ramp"             # Gradual increase (0 → 100 → 500 → 1000 → 5000)
    SOAK = "soak"             # Sustained load over long duration


class UserMode(Enum):
    """Concurrent user targets."""
    STARTUP = "startup"       # 10, 50, 100, 250, 500
    GROWTH = "growth"         # 1000, 2500, 5000, 10000
    ENTERPRISE = "enterprise" # 25000, 50000, 100000+


class TransactionStatus(Enum):
    """Payment transaction outcomes."""
    SUCCESS = "success"
    DECLINE = "decline"
    REFUND = "refund"
    TIMEOUT = "timeout"
    DUPLICATE = "duplicate_charge"
    NETWORK_FAILURE = "network_failure"


@dataclass
class UserJourneyStep:
    """Single step in a user journey."""
    action: str              # "navigate", "fill", "click", "wait", "validate"
    selector: Optional[str] = None
    value: Optional[str] = None
    wait_ms: int = 0
    expect_success: bool = True


@dataclass
class UserSession:
    """Tracks metrics for a single simulated user."""
    session_id: str
    start_time: float
    end_time: Optional[float] = None
    steps_completed: int = 0
    steps_failed: int = 0
    actions: List[Dict[str, Any]] = field(default_factory=list)
    error_message: Optional[str] = None
    
    @property
    def duration_ms(self) -> float:
        end = self.end_time or time.time()
        return (end - self.start_time) * 1000
    
    @property
    def success(self) -> bool:
        return self.steps_failed == 0 and self.error_message is None


@dataclass
class LoadTestMetrics:
    """Aggregate metrics from load test."""
    test_id: str
    profile: LoadProfile
    user_mode: UserMode
    target_users: int
    actual_concurrent: int
    duration_secs: float
    
    # User session results
    total_sessions: int = 0
    successful_sessions: int = 0
    failed_sessions: int = 0
    user_sessions: List[UserSession] = field(default_factory=list)
    
    # Latency metrics (ms)
    latency_p50: float = 0.0
    latency_p95: float = 0.0
    latency_p99: float = 0.0
    latency_min: float = 0.0
    latency_max: float = 0.0
    latency_mean: float = 0.0
    
    # Throughput
    transactions_per_sec: float = 0.0
    
    # Errors
    error_rate: float = 0.0  # % of users that failed
    timeout_count: int = 0
    crash_count: int = 0
    
    # Business metrics
    successful_transactions: int = 0
    revenue_impact_dollars: float = 0.0
    
    # Bottleneck analysis
    bottleneck_component: str = ""  # "database", "api", "frontend"
    bottleneck_percentage: float = 0.0
    
    # Breaking point detection
    health_status: str = ""  # "healthy", "degraded", "critical"
    breaking_point_users: Optional[int] = None
    
    @property
    def success_rate(self) -> float:
        if self.total_sessions == 0:
            return 0.0
        return (self.successful_sessions / self.total_sessions) * 100


class LoadSimulator:
    """Main orchestrator for concurrent user simulation."""
    
    def __init__(
        self,
        browser: Browser,
        base_url: str,
        run_id: str,
        event_emitter: Optional[Callable] = None,
    ):
        self.browser = browser
        self.base_url = base_url
        self.run_id = run_id
        self.event_emitter = event_emitter or (lambda x: None)
        
    async def run_burst_test(
        self,
        target_users: int,
        journey_template: str,
        duration_secs: int = 30,
        **kwargs
    ) -> LoadTestMetrics:
        """
        Burst test: Spawn all users at once, measure breaking point.
        
        Args:
            target_users: Total concurrent users (10, 50, 100, 250, 500, 1000, etc.)
            journey_template: "ecommerce", "finance", "saas"
            duration_secs: How long to sustain the load
        """
        test_id = f"burst_{target_users}_{int(time.time())}"
        self.emit("load_test_started", {
            "test_id": test_id,
            "profile": "burst",
            "target_users": target_users,
        })
        
        start_time = time.time()
        user_tasks = []
        sessions = []
        
        # Spawn all users immediately
        for i in range(target_users):
            session = UserSession(
                session_id=f"user_{i}_{int(time.time())}",
                start_time=time.time(),
            )
            sessions.append(session)
            
            task = asyncio.create_task(
                self._simulate_user_journey(
                    session=session,
                    journey_template=journey_template,
                    max_duration=duration_secs,
                    **kwargs
                )
            )
            user_tasks.append(task)
        
        # Wait for all to complete or timeout
        results = await asyncio.gather(*user_tasks, return_exceptions=True)
        
        elapsed = time.time() - start_time
        
        # Aggregate metrics
        metrics = self._aggregate_metrics(
            test_id=test_id,
            profile=LoadProfile.BURST,
            user_mode=self._classify_user_mode(target_users),
            target_users=target_users,
            duration_secs=elapsed,
            sessions=sessions,
            results=results,
        )
        
        self.emit("load_test_completed", asdict(metrics))
        return metrics
    
    async def run_ramp_test(
        self,
        journey_template: str,
        user_mode: UserMode = UserMode.STARTUP,
        duration_per_stage_secs: int = 60,
        **kwargs
    ) -> List[LoadTestMetrics]:
        """
        Ramp test: Gradually increase load, detect degradation points.
        
        Args:
            user_mode: STARTUP (10→50→100→250→500), GROWTH (1K→2.5K→5K→10K), etc.
            duration_per_stage_secs: How long each stage sustains
        """
        stages = self._get_ramp_stages(user_mode)
        results = []
        
        self.emit("load_test_started", {
            "test_id": f"ramp_{user_mode.value}",
            "profile": "ramp",
            "stages": stages,
        })
        
        for stage_idx, stage_users in enumerate(stages):
            stage_result = await self.run_burst_test(
                target_users=stage_users,
                journey_template=journey_template,
                duration_secs=duration_per_stage_secs,
                **kwargs
            )
            results.append(stage_result)
            
            # Emit stage completion
            self.emit("ramp_stage_completed", {
                "stage": stage_idx + 1,
                "users": stage_users,
                "success_rate": stage_result.success_rate,
                "latency_p95": stage_result.latency_p95,
            })
            
            # Check if we should continue
            if stage_result.health_status == "critical":
                logger.warning(f"Critical failure at {stage_users} users, stopping ramp")
                break
            
            # Brief pause between stages
            await asyncio.sleep(2)
        
        return results
    
    async def run_soak_test(
        self,
        concurrent_users: int,
        journey_template: str,
        duration_secs: int = 43200,  # 12 hours default
        **kwargs
    ) -> LoadTestMetrics:
        """
        Soak test: Sustained load over long period to find memory leaks.
        
        Args:
            concurrent_users: Steady-state concurrent users
            duration_secs: Total test duration (default 12 hours)
        """
        test_id = f"soak_{concurrent_users}_{int(time.time())}"
        
        self.emit("load_test_started", {
            "test_id": test_id,
            "profile": "soak",
            "concurrent_users": concurrent_users,
            "duration_hours": duration_secs / 3600,
        })
        
        # Spawn pool of workers
        start_time = time.time()
        sessions = []
        worker_tasks = []
        
        for i in range(concurrent_users):
            session = UserSession(
                session_id=f"soak_user_{i}_{int(time.time())}",
                start_time=time.time(),
            )
            sessions.append(session)
            
            task = asyncio.create_task(
                self._continuous_user_journey(
                    session=session,
                    journey_template=journey_template,
                    end_time=start_time + duration_secs,
                    **kwargs
                )
            )
            worker_tasks.append(task)
        
        # Monitor and emit periodic updates
        while time.time() - start_time < duration_secs:
            await asyncio.sleep(60)  # Emit metrics every minute
            elapsed = time.time() - start_time
            successful = sum(1 for s in sessions if s.success)
            self.emit("soak_progress", {
                "elapsed_secs": elapsed,
                "successful_sessions": successful,
                "total_sessions": len(sessions),
            })
        
        # Wait for all workers to finish
        results = await asyncio.gather(*worker_tasks, return_exceptions=True)
        
        elapsed = time.time() - start_time
        
        metrics = self._aggregate_metrics(
            test_id=test_id,
            profile=LoadProfile.SOAK,
            user_mode=UserMode.ENTERPRISE,
            target_users=concurrent_users,
            duration_secs=elapsed,
            sessions=sessions,
            results=results,
        )
        
        self.emit("load_test_completed", asdict(metrics))
        return metrics
    
    async def _simulate_user_journey(
        self,
        session: UserSession,
        journey_template: str,
        max_duration: int = 60,
        **kwargs
    ) -> None:
        """Execute a single user's journey through the app."""
        ctx: Optional[BrowserContext] = None
        page: Optional[Page] = None
        
        # Record a video for the FIRST user of each swarm so the UI has
        # something to play in the Swarm tab. Recording every user would
        # blow up disk + memory.
        record_video = str(session.session_id).startswith("user_0_") or str(session.session_id).startswith("soak_user_0_")
        ctx_kwargs: dict = {}
        if record_video:
            video_dir = Path(os.environ.get("ATMOS_VIDEOS_DIR", "/app/backend/videos"))
            video_dir.mkdir(parents=True, exist_ok=True)
            ctx_kwargs["record_video_dir"] = str(video_dir)
            ctx_kwargs["record_video_size"] = {"width": 1280, "height": 720}

        try:
            ctx = await self.browser.new_context(**ctx_kwargs)
            page = await ctx.new_page()
            
            # Get journey steps based on template
            journey = self._get_journey_steps(journey_template, **kwargs)
            
            step_start = time.time()
            for step in journey:
                if time.time() - step_start > max_duration:
                    session.error_message = "Timeout exceeded"
                    break
                
                step_result = await self._execute_journey_step(page, step, session)
                
                if not step_result:
                    session.steps_failed += 1
                    break
                else:
                    session.steps_completed += 1
            
            session.end_time = time.time()
            
        except Exception as e:
            session.error_message = str(e)
            session.steps_failed += 1
        finally:
            # Persist the recorded video URL on the session so we can return it.
            video_url: Optional[str] = None
            try:
                if record_video and page is not None:
                    video_obj = page.video
                    await page.close()
                    page = None
                    if video_obj:
                        raw_video_path = await video_obj.path()
                        if raw_video_path and Path(raw_video_path).exists():
                            vname = f"{self.run_id}_swarm_{session.session_id}.webm"
                            target = Path(os.environ.get("ATMOS_VIDEOS_DIR", "/app/backend/videos")) / vname
                            Path(raw_video_path).rename(target)
                            video_url = f"/api/screens/{vname}"
            except Exception:  # noqa: BLE001
                video_url = None
            if page:
                try:
                    await page.close()
                except Exception:  # noqa: BLE001
                    pass
            if ctx:
                try:
                    await ctx.close()
                except Exception:  # noqa: BLE001
                    pass
            if video_url:
                self.emit("user_session_video", {"session_id": session.session_id, "video_url": video_url})
                # Also stash on the session so the engine layer can surface it.
                try:
                    setattr(session, "video_url", video_url)
                except Exception:  # noqa: BLE001
                    pass
    
    async def _continuous_user_journey(
        self,
        session: UserSession,
        journey_template: str,
        end_time: float,
        **kwargs
    ) -> None:
        """Continuously execute journeys until end_time is reached."""
        ctx: Optional[BrowserContext] = None
        
        try:
            while time.time() < end_time:
                ctx = await self.browser.new_context()
                page = await ctx.new_page()
                
                journey = self._get_journey_steps(journey_template, **kwargs)
                
                for step in journey:
                    step_result = await self._execute_journey_step(page, step, session)
                    if not step_result:
                        session.steps_failed += 1
                        break
                    else:
                        session.steps_completed += 1
                
                await page.close()
                await ctx.close()
                
                # Emit progress
                self.emit("user_session_step", {
                    "session_id": session.session_id,
                    "steps_completed": session.steps_completed,
                })
        
        except Exception as e:
            session.error_message = str(e)
        finally:
            session.end_time = time.time()
    
    async def _execute_journey_step(
        self,
        page: Page,
        step: UserJourneyStep,
        session: UserSession,
    ) -> bool:
        """Execute a single journey step and track metrics."""
        step_start = time.time()
        
        try:
            if step.action == "navigate":
                await page.goto(step.value, wait_until="domcontentloaded", timeout=10000)
            
            elif step.action == "fill":
                await page.fill(step.selector, step.value, timeout=5000)
            
            elif step.action == "click":
                await page.click(step.selector, timeout=5000)
            
            elif step.action == "wait":
                await asyncio.sleep(step.wait_ms / 1000)
            
            elif step.action == "validate":
                locator = page.locator(step.selector)
                await locator.wait_for(timeout=5000)
            
            duration_ms = (time.time() - step_start) * 1000
            
            session.actions.append({
                "action": step.action,
                "duration_ms": duration_ms,
                "timestamp": datetime.now().isoformat(),
            })
            
            return True
        
        except Exception as e:
            logger.error(f"Step failed: {step.action} - {str(e)}")
            session.error_message = str(e)
            return False
    
    def _get_journey_steps(
        self,
        template: str,
        **kwargs
    ) -> List[UserJourneyStep]:
        """Return predefined journey template."""
        
        if template == "ecommerce":
            return [
                UserJourneyStep(action="navigate", value=self.base_url),
                UserJourneyStep(action="wait", wait_ms=1000),
                UserJourneyStep(action="click", selector="[data-testid='browse-products']"),
                UserJourneyStep(action="wait", wait_ms=500),
                UserJourneyStep(action="click", selector="[data-testid='product-item']"),
                UserJourneyStep(action="wait", wait_ms=500),
                UserJourneyStep(action="click", selector="[data-testid='add-to-cart']"),
                UserJourneyStep(action="wait", wait_ms=500),
                UserJourneyStep(action="click", selector="[data-testid='checkout-button']"),
                UserJourneyStep(action="wait", wait_ms=1000),
                UserJourneyStep(action="validate", selector="[data-testid='checkout-form']"),
            ]
        
        elif template == "finance":
            return [
                UserJourneyStep(action="navigate", value=self.base_url),
                UserJourneyStep(action="wait", wait_ms=1000),
                UserJourneyStep(action="click", selector="[data-testid='login-button']"),
                UserJourneyStep(action="wait", wait_ms=500),
                UserJourneyStep(action="fill", selector="[data-testid='email-input']", value=self._generate_email()),
                UserJourneyStep(action="fill", selector="[data-testid='password-input']", value="TestPassword123!"),
                UserJourneyStep(action="click", selector="[data-testid='submit-button']"),
                UserJourneyStep(action="wait", wait_ms=1000),
                UserJourneyStep(action="click", selector="[data-testid='make-payment']"),
                UserJourneyStep(action="wait", wait_ms=500),
                UserJourneyStep(action="validate", selector="[data-testid='payment-form']"),
            ]
        
        elif template == "saas":
            return [
                UserJourneyStep(action="navigate", value=self.base_url),
                UserJourneyStep(action="wait", wait_ms=1000),
                UserJourneyStep(action="click", selector="[data-testid='sign-up']"),
                UserJourneyStep(action="wait", wait_ms=500),
                UserJourneyStep(action="fill", selector="[data-testid='email']", value=self._generate_email()),
                UserJourneyStep(action="fill", selector="[data-testid='password']", value="SecurePass123!"),
                UserJourneyStep(action="click", selector="[data-testid='accept-terms']"),
                UserJourneyStep(action="click", selector="[data-testid='create-account']"),
                UserJourneyStep(action="wait", wait_ms=1500),
                UserJourneyStep(action="validate", selector="[data-testid='dashboard']"),
            ]
        
        return []
    
    def _get_ramp_stages(self, user_mode: UserMode) -> List[int]:
        """Return user counts for each ramp stage."""
        stages_map = {
            UserMode.STARTUP: [10, 50, 100, 250, 500],
            UserMode.GROWTH: [1000, 2500, 5000, 10000],
            UserMode.ENTERPRISE: [25000, 50000, 100000],
        }
        return stages_map.get(user_mode, [10, 50, 100])
    
    def _classify_user_mode(self, target_users: int) -> UserMode:
        """Classify user count into a mode."""
        if target_users <= 500:
            return UserMode.STARTUP
        elif target_users <= 10000:
            return UserMode.GROWTH
        else:
            return UserMode.ENTERPRISE
    
    def _aggregate_metrics(
        self,
        test_id: str,
        profile: LoadProfile,
        user_mode: UserMode,
        target_users: int,
        duration_secs: float,
        sessions: List[UserSession],
        results: List[Any],
    ) -> LoadTestMetrics:
        """Aggregate individual session metrics into load test metrics."""
        
        successful = sum(1 for s in sessions if s.success)
        failed = len(sessions) - successful
        
        # Extract latencies
        latencies = []
        for session in sessions:
            if session.actions:
                for action in session.actions:
                    latencies.append(action.get("duration_ms", 0))
        
        latencies.sort()
        
        metrics = LoadTestMetrics(
            test_id=test_id,
            profile=profile,
            user_mode=user_mode,
            target_users=target_users,
            actual_concurrent=len(sessions),
            duration_secs=duration_secs,
            total_sessions=len(sessions),
            successful_sessions=successful,
            failed_sessions=failed,
            user_sessions=sessions,
            error_rate=(failed / len(sessions) * 100) if sessions else 0.0,
            transactions_per_sec=(successful / duration_secs) if duration_secs > 0 else 0.0,
        )
        
        # Latency percentiles
        if latencies:
            metrics.latency_min = min(latencies)
            metrics.latency_max = max(latencies)
            metrics.latency_mean = statistics.mean(latencies)
            metrics.latency_p50 = latencies[int(len(latencies) * 0.50)]
            metrics.latency_p95 = latencies[int(len(latencies) * 0.95)]
            metrics.latency_p99 = latencies[int(len(latencies) * 0.99)]
        
        # Business metrics
        metrics.successful_transactions = successful
        metrics.revenue_impact_dollars = self._estimate_revenue_impact(
            failed_count=failed,
            total=len(sessions),
        )
        
        # Detect health status and breaking point
        metrics.health_status = self._classify_health(metrics)
        metrics.breaking_point_users = self._detect_breaking_point(metrics)
        
        return metrics
    
    def _estimate_revenue_impact(
        self,
        failed_count: int,
        total: int,
        avg_transaction_value: float = 50.0,
    ) -> float:
        """Estimate revenue impact per hour based on failure rate."""
        if total == 0:
            return 0.0
        failure_rate = failed_count / total
        # Assume 1000 transactions per hour baseline
        lost_transactions_per_hour = 1000 * failure_rate
        return lost_transactions_per_hour * avg_transaction_value
    
    def _classify_health(self, metrics: LoadTestMetrics) -> str:
        """Classify system health status."""
        if metrics.error_rate < 5.0 and metrics.latency_p95 < 1000:
            return "healthy"
        elif metrics.error_rate < 15.0 and metrics.latency_p95 < 3000:
            return "degraded"
        else:
            return "critical"
    
    def _detect_breaking_point(self, metrics: LoadTestMetrics) -> Optional[int]:
        """Estimate the concurrent user threshold before failure."""
        if metrics.health_status == "healthy":
            return None
        
        # Rough estimation: breaking point is 20% above where we see 10% error rate
        if metrics.error_rate > 10:
            return int(metrics.target_users * 0.8)
        
        return None
    
    def _generate_email(self) -> str:
        """Generate a unique test email."""
        random_suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
        return f"testuser_{random_suffix}@atmos-test.local"
    
    def emit(self, event_type: str, data: Dict[str, Any]) -> None:
        """Emit event to progress tracker."""
        try:
            self.event_emitter({
                "kind": "load_test_event",
                "event_type": event_type,
                "data": data,
                "timestamp": datetime.now().isoformat(),
            })
        except Exception as e:
            logger.error(f"Failed to emit event: {e}")
