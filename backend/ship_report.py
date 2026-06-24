"""
Atmos Ship Report Generator - Business-focused load testing insights.

Translates technical metrics into founder/PM-friendly recommendations:
- Can users use it?
- Can disabled users use it?
- Can it handle N users?
- Are payments working?
- Will users abandon checkout?
- Should you launch?
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import statistics


class ReadinessRating(Enum):
    """Readiness to ship."""
    SHIP_NOW = "ship_now"         # ✓ Ready
    SHIP_WITH_WARNINGS = "warnings"  # ⚠ Ready with caveats
    NOT_READY = "not_ready"       # ✗ Fix issues first
    CRITICAL_BLOCKER = "critical"  # 🚫 Stop


@dataclass
class ShipReportIssue:
    """Single issue identified in ship report."""
    category: str  # "accessibility", "performance", "payment", "scalability"
    severity: str  # "critical", "warning", "info"
    title: str
    description: str
    impact: str  # Business impact statement
    recommendation: str
    estimated_fix_time_hours: int
    blocker: bool  # True if must fix before launch


@dataclass
class ShipReport:
    """Executive ship report for founders/PMs."""
    generated_at: str
    app_name: str
    
    # Core questions
    can_users_use_it: bool
    can_disabled_users_use_it: bool
    can_handle_peak_users: int  # Max concurrent users before degradation
    are_payments_working: bool
    checkout_abandonment_risk: str  # "low", "moderate", "high"
    
    # Overall readiness
    readiness: ReadinessRating
    confidence_score: int  # 0-100
    
    # Key metrics
    success_rate: float  # %
    latency_p95_ms: float
    error_rate: float  # %
    breaking_point_users: Optional[int]
    revenue_risk_per_hour: float  # $
    
    # Actionable issues
    issues: List[ShipReportIssue] = field(default_factory=list)
    
    # Summary sections
    executive_summary: str = ""
    top_3_issues: List[str] = field(default_factory=list)
    launch_blockers: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)


class ShipReportGenerator:
    """Generate business-focused ship readiness reports."""
    
    def __init__(self, app_name: str):
        self.app_name = app_name
    
    def generate_from_load_test(
        self,
        load_metrics: Dict[str, Any],
        accessibility_issues: Optional[List[Dict]] = None,
        payment_test_results: Optional[Dict] = None,
    ) -> ShipReport:
        """
        Generate a ship report from load test and other audit results.
        
        Args:
            load_metrics: Results from load simulator (burst/ramp/soak)
            accessibility_issues: Issues found in accessibility audit
            payment_test_results: Results from payment sandbox testing
        
        Returns:
            ShipReport ready for founder/PM consumption
        """
        report = ShipReport(
            generated_at=datetime.now().isoformat(),
            app_name=self.app_name,
            can_users_use_it=True,
            can_disabled_users_use_it=False,
            can_handle_peak_users=0,
            are_payments_working=False,
            checkout_abandonment_risk="unknown",
            readiness=ReadinessRating.NOT_READY,
            confidence_score=0,
            success_rate=0.0,
            latency_p95_ms=0.0,
            error_rate=0.0,
            revenue_risk_per_hour=0.0,
        )
        
        # Extract key metrics
        if load_metrics:
            report.success_rate = load_metrics.get("success_rate", 0.0)
            report.latency_p95_ms = load_metrics.get("latency_p95", 0.0)
            report.error_rate = load_metrics.get("error_rate", 0.0)
            report.breaking_point_users = load_metrics.get("breaking_point_users")
            report.revenue_risk_per_hour = load_metrics.get("revenue_impact_dollars", 0.0)
        
        # Analyze accessibility
        if accessibility_issues:
            report.can_disabled_users_use_it = len(accessibility_issues) == 0
            self._analyze_accessibility(report, accessibility_issues)
        
        # Analyze payments
        if payment_test_results:
            report.are_payments_working = payment_test_results.get("all_passed", False)
            self._analyze_payments(report, payment_test_results)
        
        # Detect peak user capacity
        report.can_handle_peak_users = self._detect_peak_capacity(load_metrics)
        
        # Detect checkout abandonment risk
        report.checkout_abandonment_risk = self._estimate_abandonment_risk(load_metrics)
        
        # Synthesize readiness
        report.readiness = self._determine_readiness(report)
        report.confidence_score = self._calculate_confidence(report)
        
        # Generate narrative sections
        report.executive_summary = self._generate_executive_summary(report)
        report.top_3_issues = self._extract_top_issues(report.issues)
        report.launch_blockers = [i.title for i in report.issues if i.blocker]
        report.recommendations = self._generate_recommendations(report)
        
        return report
    
    def _analyze_accessibility(
        self,
        report: ShipReport,
        accessibility_issues: List[Dict],
    ) -> None:
        """Analyze accessibility findings."""
        if not accessibility_issues:
            return
        
        for issue in accessibility_issues:
            severity = issue.get("severity", "warning").lower()
            
            report.issues.append(ShipReportIssue(
                category="accessibility",
                severity=severity,
                title=issue.get("title", "Accessibility Issue"),
                description=issue.get("description", ""),
                impact="Disabled users cannot access feature; legal liability under WCAG/ADA",
                recommendation="Add aria-labels, ensure keyboard navigation, test with screen readers",
                estimated_fix_time_hours=4 if severity == "critical" else 2,
                blocker=(severity == "critical"),
            ))
    
    def _analyze_payments(
        self,
        report: ShipReport,
        payment_results: Dict,
    ) -> None:
        """Analyze payment testing results."""
        success_rate = payment_results.get("success_rate", 0.0)
        failure_scenarios = payment_results.get("failures", [])
        
        if success_rate < 0.99:
            report.issues.append(ShipReportIssue(
                category="payment",
                severity="critical",
                title="Payment Processing Unreliable",
                description=f"Success rate: {success_rate*100:.1f}% (target: 99%+)",
                impact=f"Every 100 transactions: {int((1-success_rate)*100)} fail. Annual revenue loss: ${(1-success_rate)*365*24*1000*50:,.0f}",
                recommendation="Debug with payment provider, test timeout handling, add retry logic",
                estimated_fix_time_hours=8,
                blocker=True,
            ))
        
        for scenario in failure_scenarios:
            if scenario.get("count", 0) > 0:
                report.issues.append(ShipReportIssue(
                    category="payment",
                    severity="warning",
                    title=f"Payment Decline: {scenario.get('type', 'Unknown')}",
                    description=scenario.get("description", ""),
                    impact="Some users cannot complete purchases",
                    recommendation="Test edge case handling in checkout flow",
                    estimated_fix_time_hours=2,
                    blocker=False,
                ))
    
    def _detect_peak_capacity(self, load_metrics: Dict[str, Any]) -> int:
        """Detect maximum concurrent users the system can sustain."""
        if not load_metrics:
            return 0
        
        # If ramp test results, find last healthy stage
        if "ramp_stages" in load_metrics:
            stages = load_metrics["ramp_stages"]
            for stage in reversed(stages):
                if stage.get("health_status") == "healthy":
                    return stage.get("users", 0)
        
        # Fallback: use breaking point
        breaking_point = load_metrics.get("breaking_point_users")
        if breaking_point:
            return int(breaking_point * 0.8)  # Conservative estimate
        
        # Fallback: estimate from error rate
        target_users = load_metrics.get("target_users", 0)
        error_rate = load_metrics.get("error_rate", 0.0)
        
        if error_rate < 5:
            return target_users  # Passed this load
        
        return int(target_users * (1 - error_rate / 10))
    
    def _estimate_abandonment_risk(self, load_metrics: Dict[str, Any]) -> str:
        """Estimate checkout abandonment risk based on latency."""
        if not load_metrics:
            return "unknown"
        
        latency_p95 = load_metrics.get("latency_p95", 0.0)
        error_rate = load_metrics.get("error_rate", 0.0)
        
        # Research-backed thresholds:
        # - > 1000ms: 7% abandonment increase per 1s
        # - > 3000ms: 40% abandonment increase
        # - Errors: +10% per 1% error rate
        
        risk_score = 0.0
        
        if latency_p95 > 3000:
            risk_score += 40
        elif latency_p95 > 1000:
            risk_score += (latency_p95 - 1000) / 200 * 7
        
        risk_score += error_rate * 10
        
        if risk_score < 15:
            return "low"
        elif risk_score < 35:
            return "moderate"
        else:
            return "high"
    
    def _determine_readiness(self, report: ShipReport) -> ReadinessRating:
        """Determine overall readiness to ship."""
        # Count issues by severity
        critical_issues = sum(1 for i in report.issues if i.blocker)
        
        if critical_issues > 0:
            return ReadinessRating.CRITICAL_BLOCKER
        
        if not report.are_payments_working:
            return ReadinessRating.CRITICAL_BLOCKER
        
        warnings = sum(1 for i in report.issues if i.severity == "warning")
        
        if warnings > 3:
            return ReadinessRating.NOT_READY
        
        if report.success_rate < 0.95:
            return ReadinessRating.NOT_READY
        
        if report.checkout_abandonment_risk == "high":
            return ReadinessRating.SHIP_WITH_WARNINGS
        
        if warnings > 0:
            return ReadinessRating.SHIP_WITH_WARNINGS
        
        return ReadinessRating.SHIP_NOW
    
    def _calculate_confidence(self, report: ShipReport) -> int:
        """Calculate confidence score 0-100."""
        score = 100
        
        # Deduct for issues
        for issue in report.issues:
            if issue.blocker:
                score -= 20
            elif issue.severity == "critical":
                score -= 15
            elif issue.severity == "warning":
                score -= 5
        
        # Deduct for metrics
        if report.success_rate < 0.99:
            score -= int((1 - report.success_rate) * 100)
        
        if report.error_rate > 5:
            score -= min(report.error_rate, 20)
        
        # Add for scale coverage
        if report.can_handle_peak_users > 1000:
            score += 10
        
        return max(0, min(100, score))
    
    def _generate_executive_summary(self, report: ShipReport) -> str:
        """Generate one-paragraph executive summary."""
        if report.readiness == ReadinessRating.SHIP_NOW:
            return (
                f"{self.app_name} is ready to launch. All critical systems pass load tests, "
                f"payments are working reliably ({report.success_rate*100:.0f}% success), "
                f"and infrastructure handles {report.can_handle_peak_users:,} concurrent users. "
                f"Confidence: {report.confidence_score}/100."
            )
        
        elif report.readiness == ReadinessRating.SHIP_WITH_WARNINGS:
            issues = len(report.issues)
            return (
                f"{self.app_name} can launch with caution. {issues} issue(s) identified that "
                f"should be addressed post-launch or during soft rollout. "
                f"Peak capacity: {report.can_handle_peak_users:,} users. "
                f"Checkout abandonment risk: {report.checkout_abandonment_risk}. "
                f"Confidence: {report.confidence_score}/100."
            )
        
        elif report.readiness == ReadinessRating.NOT_READY:
            blockers = len(report.launch_blockers)
            return (
                f"⚠ {self.app_name} should not launch yet. {blockers} issue(s) require fixing. "
                f"Success rate: {report.success_rate*100:.0f}% (target: 99%+). "
                f"Peak capacity: {report.can_handle_peak_users:,} users may be insufficient. "
                f"Estimated fix time: {sum(i.estimated_fix_time_hours for i in report.issues)} hours."
            )
        
        else:  # CRITICAL_BLOCKER
            return (
                f"🚫 STOP: {self.app_name} has critical issues preventing launch. "
                f"Payments {'not working' if not report.are_payments_working else 'working'}. "
                f"Critical issues: {len(report.launch_blockers)}. "
                f"Do not proceed until resolved."
            )
    
    def _extract_top_issues(self, issues: List[ShipReportIssue]) -> List[str]:
        """Extract top 3 issues by impact."""
        # Sort by severity then by estimated fix time
        severity_order = {"critical": 0, "warning": 1, "info": 2}
        sorted_issues = sorted(
            issues,
            key=lambda x: (severity_order.get(x.severity, 3), -x.estimated_fix_time_hours)
        )
        
        return [issue.title for issue in sorted_issues[:3]]
    
    def _generate_recommendations(self, report: ShipReport) -> List[str]:
        """Generate prioritized recommendations."""
        recommendations = []
        
        # Critical fixes first
        for issue in report.issues:
            if issue.blocker:
                recommendations.append(f"CRITICAL: {issue.recommendation}")
        
        # Scalability recommendations
        if report.can_handle_peak_users < 1000:
            recommendations.append(
                f"Scalability: Current capacity {report.can_handle_peak_users:,} users. "
                "Plan database optimization, caching, or load balancer upgrade for growth."
            )
        
        # Performance recommendations
        if report.latency_p95_ms > 2000:
            recommendations.append(
                f"Performance: P95 latency is {report.latency_p95_ms:.0f}ms. "
                "Profile API endpoints, optimize database queries, implement caching."
            )
        
        # Checkout recommendations
        if report.checkout_abandonment_risk in ["moderate", "high"]:
            recommendations.append(
                "UX: High checkout latency increases abandonment. "
                "Implement one-page checkout, lazy loading, or progressive payment processing."
            )
        
        # Accessibility recommendations
        accessibility_issues = [i for i in report.issues if i.category == "accessibility"]
        if accessibility_issues:
            recommendations.append(
                f"Accessibility: {len(accessibility_issues)} issue(s) found. "
                "Add ARIA labels, keyboard navigation, and test with screen readers."
            )
        
        return recommendations
    
    def render_text(self, report: ShipReport) -> str:
        """Render report as plain text."""
        lines = [
            "=" * 60,
            "ATMOS SHIP REPORT",
            "=" * 60,
            "",
            f"App: {report.app_name}",
            f"Generated: {report.generated_at}",
            f"Readiness: {report.readiness.value.upper()}",
            f"Confidence: {report.confidence_score}/100",
            "",
            "━" * 60,
            "EXECUTIVE SUMMARY",
            "━" * 60,
            report.executive_summary,
            "",
            "━" * 60,
            "KEY QUESTIONS",
            "━" * 60,
            f"Can users use it? {'YES ✓' if report.can_users_use_it else 'NO ✗'}",
            f"Can disabled users use it? {'YES ✓' if report.can_disabled_users_use_it else 'NO ✗'}",
            f"Can it handle {report.can_handle_peak_users:,} users? {'YES ✓' if report.can_handle_peak_users > 1000 else 'NO ✗'}",
            f"Are payments working? {'YES ✓' if report.are_payments_working else 'NO ✗'}",
            f"Will users abandon checkout? {report.checkout_abandonment_risk.upper()}",
            f"Should you launch? {'YES ✓' if report.readiness in [ReadinessRating.SHIP_NOW, ReadinessRating.SHIP_WITH_WARNINGS] else 'NO ✗'}",
            "",
            "━" * 60,
            "METRICS",
            "━" * 60,
            f"Success Rate: {report.success_rate*100:.1f}%",
            f"Error Rate: {report.error_rate:.1f}%",
            f"P95 Latency: {report.latency_p95_ms:.0f}ms",
            f"Breaking Point: {report.breaking_point_users or 'Not detected'} users",
            f"Revenue Risk (per hour): ${report.revenue_risk_per_hour:,.0f}",
            "",
        ]
        
        if report.top_3_issues:
            lines.extend([
                "━" * 60,
                "TOP 3 ISSUES",
                "━" * 60,
            ])
            for i, issue in enumerate(report.top_3_issues, 1):
                lines.append(f"{i}. {issue}")
            lines.append("")
        
        if report.launch_blockers:
            lines.extend([
                "━" * 60,
                "LAUNCH BLOCKERS",
                "━" * 60,
            ])
            for blocker in report.launch_blockers:
                lines.append(f"🚫 {blocker}")
            lines.append("")
        
        if report.recommendations:
            lines.extend([
                "━" * 60,
                "RECOMMENDATIONS",
                "━" * 60,
            ])
            for rec in report.recommendations:
                lines.append(f"→ {rec}")
            lines.append("")
        
        lines.extend([
            "=" * 60,
            f"Report generated by Atmos • {datetime.now().isoformat()}",
            "=" * 60,
        ])
        
        return "\n".join(lines)
    
    def render_json(self, report: ShipReport) -> Dict[str, Any]:
        """Render report as JSON-serializable dict."""
        return {
            "generated_at": report.generated_at,
            "app_name": report.app_name,
            "readiness": report.readiness.value,
            "confidence_score": report.confidence_score,
            "can_users_use_it": report.can_users_use_it,
            "can_disabled_users_use_it": report.can_disabled_users_use_it,
            "can_handle_peak_users": report.can_handle_peak_users,
            "are_payments_working": report.are_payments_working,
            "checkout_abandonment_risk": report.checkout_abandonment_risk,
            "metrics": {
                "success_rate": report.success_rate,
                "error_rate": report.error_rate,
                "latency_p95_ms": report.latency_p95_ms,
                "breaking_point_users": report.breaking_point_users,
                "revenue_risk_per_hour": report.revenue_risk_per_hour,
            },
            "executive_summary": report.executive_summary,
            "top_3_issues": report.top_3_issues,
            "launch_blockers": report.launch_blockers,
            "recommendations": report.recommendations,
            "all_issues": [
                {
                    "category": i.category,
                    "severity": i.severity,
                    "title": i.title,
                    "description": i.description,
                    "impact": i.impact,
                    "recommendation": i.recommendation,
                    "estimated_fix_time_hours": i.estimated_fix_time_hours,
                    "blocker": i.blocker,
                }
                for i in report.issues
            ],
        }
