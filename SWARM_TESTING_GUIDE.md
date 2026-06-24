# Atmos Swarm Testing & Ship Reports

## Overview

Atmos now includes **concurrent user load testing** with business-focused reporting. Instead of just metrics, Atmos answers the questions founders actually care about:

- Can users use it?
- Can it handle peak traffic?
- Are payments working?
- Will users abandon checkout?
- **Should you launch?**

---

## Architecture

### Core Modules

#### `load_simulator.py` (1000+ lines)
- **LoadSimulator**: Orchestrates concurrent user simulation
- **LoadProfile**: Burst, Ramp, Soak testing modes
- **UserMode**: Startup (10-500), Growth (1K-10K), Enterprise (25K+)
- **UserSession & LoadTestMetrics**: Tracks per-user and aggregate metrics

**Key Methods:**
```python
async def run_burst_test(target_users, journey_template, duration_secs)
async def run_ramp_test(journey_template, user_mode, duration_per_stage_secs)
async def run_soak_test(concurrent_users, journey_template, duration_secs)
```

#### `payment_sandbox.py` (500+ lines)
- **PaymentSandbox**: Manages encrypted payment credentials (never exposed)
- **TestPaymentGenerator**: Generates test cards with predetermined outcomes
- **PaymentLoadScenario**: Realistic scenarios (checkout, subscriptions, transfers)
- **FailureInjection**: Simulate cascading failures for chaos testing

**Test Outcomes:**
- SUCCESS, DECLINE, INSUFFICIENT_FUNDS, EXPIRED_CARD
- INCORRECT_CVC, PROCESSING_ERROR, TIMEOUT, DUPLICATE_CHARGE, NETWORK_FAILURE, RATE_LIMITED

**Payment Providers:**
- Stripe (test mode cards)
- PayPal (sandbox accounts)
- Razorpay (test cards)

#### `ship_report.py` (500+ lines)
- **ShipReportGenerator**: Translates technical metrics to business decisions
- **ShipReport**: Executive-focused output with readiness score
- **ShipReportIssue**: Categorized issues with business impact

**Report Sections:**
1. **Executive Summary** - One paragraph decision statement
2. **Key Questions** - Yes/no answers to business concerns
3. **Readiness Status** - SHIP_NOW, SHIP_WITH_WARNINGS, NOT_READY, CRITICAL_BLOCKER
4. **Confidence Score** - 0-100 based on test coverage
5. **Top 3 Issues** - Ranked by impact
6. **Launch Blockers** - Must-fix items
7. **Recommendations** - Prioritized action items
8. **Revenue Impact** - $ per hour at given failure rates

---

## Load Testing Modes

### Burst Test ⚡
```python
results = await simulator.run_burst_test(
    target_users=1000,
    journey_template="ecommerce",
    duration_secs=30,
)
```
- Spawn all users at once
- Measure breaking point
- Fast detection (good for Startup mode)

### Ramp Test 📈
```python
results = await simulator.run_ramp_test(
    journey_template="finance",
    user_mode=UserMode.GROWTH,  # 1K → 2.5K → 5K → 10K
    duration_per_stage_secs=60,
)
```
- Gradually increase load
- Detect degradation points
- Shows where system breaks

### Soak Test 💧
```python
results = await simulator.run_soak_test(
    concurrent_users=500,
    journey_template="saas",
    duration_secs=43200,  # 12 hours
)
```
- Sustained load over long period
- Find memory leaks
- Test reliability at steady state

---

## User Journey Templates

### E-Commerce 🛒
```
Browse Products → View Details → Add to Cart → Checkout → Payment → Order Confirmation
```

### Finance 💳
```
Login → Dashboard → Enter Payment Info → Input 2 Payment IDs → Authorize → Confirm Receipt
```

### SaaS ⚙️
```
Sign Up → Verify Email → Dashboard → Create Resource → Share → Dashboard
```

### Custom Journeys
Define your own with `UserJourneyStep`:
```python
journey = [
    UserJourneyStep(action="navigate", value="https://app.com"),
    UserJourneyStep(action="fill", selector="[name='email']", value="test@example.com"),
    UserJourneyStep(action="click", selector="[type='submit']"),
    UserJourneyStep(action="validate", selector=".dashboard"),
]
```

---

## Payment Testing

### Sandbox-Only (No Production Credentials)
```python
from payment_sandbox import TestPaymentGenerator, PaymentProvider

generator = TestPaymentGenerator(PaymentProvider.STRIPE)

# Generate test cards for different outcomes
success_card = generator.generate_test_card(PaymentOutcome.SUCCESS)
decline_card = generator.generate_test_card(PaymentOutcome.DECLINE)
timeout_card = generator.generate_test_card(PaymentOutcome.TIMEOUT)
```

### Bulk Test Account Generation
```python
accounts = generator.get_bulk_test_accounts(
    count=1000,
    success_rate=0.95,  # 950 succeed, 50 fail
)
# Returns list of test account dicts with predetermined outcomes
```

### Predefined Scenarios
```python
scenario = PaymentLoadScenario.checkout_flow_scenario(
    provider=PaymentProvider.STRIPE,
    concurrent_users=5000,
    success_rate=0.96,
)

scenario = PaymentLoadScenario.subscription_billing_scenario(
    provider=PaymentProvider.PAYPAL,
    concurrent_users=10000,
    retry_logic=True,
)

scenario = PaymentLoadScenario.money_transfer_scenario(
    provider=PaymentProvider.RAZORPAY,
    concurrent_users=2500,
    transfer_amount_cents=10000,
)
```

---

## Ship Report Examples

### ✅ Ready to Ship
```
ATMOS SHIP REPORT
═════════════════════════════════════════════════════════════

Readiness: SHIP_NOW
Confidence: 94/100

EXECUTIVE SUMMARY
─────────────────
App is ready to launch. All critical systems pass load tests,
payments are working reliably (99.2% success), and infrastructure 
handles 5,000 concurrent users. Confidence: 94/100.

KEY QUESTIONS
─────────────
Can users use it? YES ✓
Can disabled users use it? YES ✓
Can it handle 5,000 users? YES ✓
Are payments working? YES ✓
Will users abandon checkout? LOW
Should you launch? YES ✓

METRICS
───────
Success Rate: 99.2%
Error Rate: 0.1%
P95 Latency: 850ms
Breaking Point: Not detected
Revenue Risk (per hour): $0
```

### ⚠️ Ship with Warnings
```
ATMOS SHIP REPORT
═════════════════════════════════════════════════════════════

Readiness: SHIP_WITH_WARNINGS
Confidence: 72/100

EXECUTIVE SUMMARY
─────────────────
App can launch with caution. 2 issue(s) identified that should be
addressed post-launch or during soft rollout. Peak capacity: 3,200
users. Checkout abandonment risk: MODERATE. Confidence: 72/100.

LAUNCH BLOCKERS
───────────────

RECOMMENDATIONS
───────────────
→ Performance: P95 latency is 2400ms. Profile API endpoints, 
  optimize database queries, implement caching.
→ UX: High checkout latency increases abandonment. Implement 
  one-page checkout, lazy loading, or progressive payment processing.
```

### ✗ Not Ready
```
ATMOS SHIP REPORT
═════════════════════════════════════════════════════════════

Readiness: NOT_READY
Confidence: 34/100

⚠ STOP: App should not launch yet. 3 issue(s) require fixing.
Success rate: 87% (target: 99%+). Peak capacity: 800 users may be
insufficient. Estimated fix time: 24 hours.

LAUNCH BLOCKERS
───────────────
🚫 Payment Processing Unreliable: Success rate 87% (target 99%+)
🚫 Database bottleneck at 3500 users
🚫 Accessibility: Focus state may be invisible for keyboard users
```

---

## API Endpoints

### Configure Swarm Test
```
POST /api/runs/{run_id}/swarm/config
Content-Type: application/json

{
  "profile": "burst",
  "user_mode": "startup",
  "target_users": 500,
  "journey_template": "ecommerce",
  "duration_secs": 60,
  "payment_provider": "stripe"
}
```

### Get Swarm Results
```
GET /api/runs/{run_id}/swarm/results

Response:
{
  "test_id": "burst_500_1234567890",
  "status": "completed",
  "summary": {
    "success_rate": 0.992,
    "error_rate": 0.008,
    "latency_p95": 850,
    "latency_p99": 1200,
    "breaking_point_users": null,
    "revenue_risk_per_hour": 0
  }
}
```

### Generate Ship Report
```
POST /api/runs/{run_id}/swarm/ship-report

Response:
{
  "readiness": "ship_now",
  "confidence_score": 94,
  "executive_summary": "...",
  "can_handle_peak_users": 5000,
  "are_payments_working": true,
  "top_3_issues": [],
  "launch_blockers": [],
  "recommendations": []
}
```

---

## Frontend Component

The `SwarmTesting.jsx` component provides:

1. **Config Tab** - Select test parameters
   - Profile (Burst/Ramp/Soak)
   - User Mode (Startup/Growth/Enterprise)
   - Journey Template
   - Duration

2. **Monitoring Tab** - Real-time metrics
   - Concurrent users
   - Success rate
   - P95 latency
   - Error rate

3. **Results Tab** - Detailed metrics
   - Total sessions, successful sessions
   - Breaking point detection
   - Revenue impact calculation
   - Latency percentiles

4. **Ship Report Tab** - Business decision
   - Readiness status with confidence score
   - Key questions answered
   - Launch blockers
   - Ranked recommendations

---

## Usage Example

### End-to-End: Testing an E-commerce App

```python
from load_simulator import LoadSimulator, UserMode
from payment_sandbox import PaymentLoadScenario, PaymentProvider
from ship_report import ShipReportGenerator

# 1. Run ramp test on e-commerce app
simulator = LoadSimulator(browser, "https://shop.example.com", run_id)

ramp_results = await simulator.run_ramp_test(
    journey_template="ecommerce",
    user_mode=UserMode.GROWTH,
    duration_per_stage_secs=60,
)

# 2. Test payment processing
scenario = PaymentLoadScenario.checkout_flow_scenario(
    provider=PaymentProvider.STRIPE,
    concurrent_users=5000,
    success_rate=0.96,
)

payment_results = await run_payment_test(scenario)

# 3. Generate Ship Report
generator = ShipReportGenerator(app_name="MyShop")
report = generator.generate_from_load_test(
    load_metrics={
        "success_rate": ramp_results[-1].success_rate,
        "error_rate": ramp_results[-1].error_rate,
        "latency_p95": ramp_results[-1].latency_p95_ms,
        "breaking_point_users": ramp_results[-1].breaking_point_users,
    },
    payment_test_results=payment_results,
)

# 4. Output business decision
print(generator.render_text(report))
# → SHIP_NOW / SHIP_WITH_WARNINGS / NOT_READY / CRITICAL_BLOCKER
```

---

## Key Metrics Explained

| Metric | What It Means | Target |
|--------|---------------|--------|
| Success Rate | % of users who completed journey | >99% |
| Error Rate | % of failed requests | <1% |
| P50 Latency | Median response time | <500ms |
| P95 Latency | 95th percentile response time | <2000ms |
| P99 Latency | 99th percentile response time | <5000ms |
| Throughput | Transactions/second | Depends on infra |
| Breaking Point | Concurrent users before failure | Document capacity |
| Revenue Risk | $ lost per hour at failure rate | Minimize |

---

## Integration with Main Atmos Pipeline

Swarm testing is integrated as a new **Phase** in the test pipeline:

```
Phase 1: GitHub Boot
Phase 2: Project Understanding
Phase 3: Crawling & Clicking
Phase 4: Per-Page Vision Analysis
Phase 5: Accessibility Audit
Phase 6: Human Persona Simulation
Phase 7: Executed Fixes
Phase 8: Boundary Input Fuzzing
Phase 9: Per-Screen Test Cases
Phase 10: Architecture Analysis
Phase 11: Competitive Benchmark
→ PHASE 12: SWARM TESTING ← NEW
→ PHASE 13: SHIP REPORT GENERATION ← NEW
Phase 14: Executive Report
```

---

## Configuration Examples

### Startup Testing (Pre-launch verification)
```python
config = SwarmConfigBody(
    profile=LoadProfileType.BURST,
    user_mode=UserModeType.STARTUP,  # 10, 50, 100, 250, 500
    journey_template=JourneyTemplateType.ECOMMERCE,
    duration_secs=30,
)
```

### Growth Testing (Capacity planning)
```python
config = SwarmConfigBody(
    profile=LoadProfileType.RAMP,
    user_mode=UserModeType.GROWTH,  # 1K → 2.5K → 5K → 10K
    journey_template=JourneyTemplateType.SAAS,
    duration_secs=60,  # Per stage
)
```

### Enterprise Testing (Chaos engineering)
```python
config = SwarmConfigBody(
    profile=LoadProfileType.SOAK,
    user_mode=UserModeType.ENTERPRISE,  # 25K, 50K, 100K+
    journey_template=JourneyTemplateType.FINANCE,
    duration_secs=43200,  # 12 hours
    payment_provider="razorpay",
)
```

---

## What's Next

- **Scheduled Tests**: Run swarm tests on a schedule (daily, weekly)
- **Benchmark Comparisons**: Compare your app to competitors
- **Cost Analysis**: $ per concurrent user on AWS/GCP/Azure
- **Geographic Distribution**: Test from multiple regions
- **Custom Failure Injection**: Chaos engineering scenarios
- **Metrics Export**: Send data to DataDog, New Relic, CloudWatch
- **Slack Alerts**: Notify when breaking point is reached

---

## Credits

Built with:
- Playwright for realistic browser automation
- Asyncio for concurrent simulation
- Cryptography for secure credential storage
- Claude Sonnet 4.5 for business report generation
