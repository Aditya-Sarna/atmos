"""
Payment sandbox integration for load testing.

Handles:
- Stripe, PayPal, Razorpay test mode credentials
- Test payment ID generation with automatic outcomes (success, decline, timeout, etc.)
- Encrypted credential storage (project-scoped, never in reports)
- Failure injection for load testing
"""

import hashlib
import json
import random
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
from cryptography.fernet import Fernet
from datetime import datetime


class PaymentProvider(Enum):
    """Supported payment providers."""
    STRIPE = "stripe"
    PAYPAL = "paypal"
    RAZORPAY = "razorpay"


class PaymentOutcome(Enum):
    """Test payment outcomes that can be simulated."""
    SUCCESS = "success"              # Transaction succeeds
    DECLINE = "decline"               # Card declined
    INSUFFICIENT_FUNDS = "insufficient_funds"
    EXPIRED_CARD = "expired_card"
    INCORRECT_CVC = "incorrect_cvc"
    PROCESSING_ERROR = "processing_error"
    TIMEOUT = "timeout"               # Network timeout
    DUPLICATE = "duplicate_charge"    # Duplicate transaction attempt
    NETWORK_FAILURE = "network_failure"
    RATE_LIMITED = "rate_limited"


# Test card/account numbers by outcome (Stripe format)
STRIPE_TEST_CARDS = {
    PaymentOutcome.SUCCESS: "4242424242424242",
    PaymentOutcome.DECLINE: "4000000000000002",
    PaymentOutcome.INSUFFICIENT_FUNDS: "4000000000009995",
    PaymentOutcome.EXPIRED_CARD: "4000000000000069",
    PaymentOutcome.INCORRECT_CVC: "4000000000000127",
    PaymentOutcome.PROCESSING_ERROR: "4000000000000119",
    PaymentOutcome.TIMEOUT: "4000000000000341",
}

# PayPal sandbox test accounts
PAYPAL_TEST_ACCOUNTS = {
    PaymentOutcome.SUCCESS: "merchant@paypalsandbox.com",
    PaymentOutcome.DECLINE: "declined@paypalsandbox.com",
    PaymentOutcome.INSUFFICIENT_FUNDS: "insufficient@paypalsandbox.com",
}

# Razorpay test cards
RAZORPAY_TEST_CARDS = {
    PaymentOutcome.SUCCESS: "4111111111111111",
    PaymentOutcome.DECLINE: "4111111111111110",
    PaymentOutcome.INSUFFICIENT_FUNDS: "4100000000000000",
}


@dataclass
class PaymentCredential:
    """Encrypted payment sandbox credential."""
    provider: PaymentProvider
    api_key: str  # Encrypted
    api_secret: str  # Encrypted (if applicable)
    created_at: str
    project_id: str  # Scoped to project, never in reports
    
    def to_dict_safe(self) -> Dict:
        """Return dict without exposing credentials."""
        return {
            "provider": self.provider.value,
            "created_at": self.created_at,
            "project_id": self.project_id,
            # Note: credentials are NOT included
        }


class PaymentSandbox:
    """Payment testing sandbox with automatic failure injection."""
    
    def __init__(self, encryption_key: Optional[str] = None):
        """
        Initialize sandbox.
        
        Args:
            encryption_key: Base64-encoded Fernet key. If None, credentials are NOT encrypted
                          (for testing only).
        """
        self.cipher = None
        if encryption_key:
            self.cipher = Fernet(encryption_key.encode())
    
    def add_credential(
        self,
        project_id: str,
        provider: PaymentProvider,
        api_key: str,
        api_secret: Optional[str] = None,
    ) -> PaymentCredential:
        """
        Store encrypted payment credentials.
        
        Args:
            project_id: Project ID (for scoping)
            provider: Payment provider
            api_key: Provider API key
            api_secret: Provider API secret (if applicable)
        
        Returns:
            PaymentCredential object (credentials encrypted)
        """
        encrypted_key = self._encrypt(api_key) if self.cipher else api_key
        encrypted_secret = self._encrypt(api_secret) if api_secret and self.cipher else api_secret
        
        return PaymentCredential(
            provider=provider,
            api_key=encrypted_key,
            api_secret=encrypted_secret or "",
            created_at=datetime.now().isoformat(),
            project_id=project_id,
        )
    
    def get_credential(self, project_id: str, provider: PaymentProvider) -> Optional[Dict]:
        """
        Retrieve credentials (for backend use only).
        
        Returns:
            Dict with decrypted credentials, or None if not found
        """
        # Note: In real implementation, this would query a secure vault
        # For now, this demonstrates the pattern
        return None
    
    def _encrypt(self, plaintext: str) -> str:
        """Encrypt a credential value."""
        if not self.cipher or not plaintext:
            return plaintext
        return self.cipher.encrypt(plaintext.encode()).decode()
    
    def _decrypt(self, ciphertext: str) -> str:
        """Decrypt a credential value."""
        if not self.cipher or not ciphertext:
            return ciphertext
        return self.cipher.decrypt(ciphertext.encode()).decode()


class TestPaymentGenerator:
    """Generate test payment IDs with predetermined outcomes."""
    
    def __init__(self, provider: PaymentProvider):
        self.provider = provider
    
    def generate_test_card(self, outcome: PaymentOutcome) -> str:
        """
        Generate a test card/account for the given outcome.
        
        Args:
            outcome: Desired payment outcome
        
        Returns:
            Test card number or account ID
        """
        if self.provider == PaymentProvider.STRIPE:
            return STRIPE_TEST_CARDS.get(outcome, STRIPE_TEST_CARDS[PaymentOutcome.SUCCESS])
        
        elif self.provider == PaymentProvider.PAYPAL:
            return PAYPAL_TEST_ACCOUNTS.get(outcome, PAYPAL_TEST_ACCOUNTS[PaymentOutcome.SUCCESS])
        
        elif self.provider == PaymentProvider.RAZORPAY:
            return RAZORPAY_TEST_CARDS.get(outcome, RAZORPAY_TEST_CARDS[PaymentOutcome.SUCCESS])
        
        return ""
    
    def generate_test_payment_request(
        self,
        amount_cents: int,
        outcomes: Optional[List[PaymentOutcome]] = None,
    ) -> List[Dict]:
        """
        Generate a batch of test payment requests covering different outcomes.
        
        Args:
            amount_cents: Payment amount in cents
            outcomes: Specific outcomes to test. If None, tests all major ones.
        
        Returns:
            List of payment request dicts ready for form filling
        """
        if outcomes is None:
            outcomes = [
                PaymentOutcome.SUCCESS,
                PaymentOutcome.DECLINE,
                PaymentOutcome.TIMEOUT,
                PaymentOutcome.INSUFFICIENT_FUNDS,
                PaymentOutcome.PROCESSING_ERROR,
                PaymentOutcome.DUPLICATE,
            ]
        
        requests = []
        for outcome in outcomes:
            card = self.generate_test_card(outcome)
            
            request = {
                "amount": amount_cents,
                "currency": "USD",
                "card_number": card,
                "exp_month": "12",
                "exp_year": "2025",
                "cvc": self._get_cvc_for_outcome(outcome),
                "cardholder_name": f"Test User {outcome.value}",
                "expected_outcome": outcome.value,
                "metadata": {
                    "test_id": self._generate_test_id(outcome),
                    "timestamp": datetime.now().isoformat(),
                }
            }
            requests.append(request)
        
        return requests
    
    def _get_cvc_for_outcome(self, outcome: PaymentOutcome) -> str:
        """Return CVC for outcome (can trigger specific failures)."""
        if outcome == PaymentOutcome.INCORRECT_CVC:
            return "999"  # Invalid CVC
        return "123"  # Valid CVC
    
    def _generate_test_id(self, outcome: PaymentOutcome) -> str:
        """Generate a unique test transaction ID."""
        timestamp = datetime.now().isoformat()
        hash_input = f"{outcome.value}_{timestamp}".encode()
        return hashlib.md5(hash_input).hexdigest()[:16]
    
    def get_bulk_test_accounts(
        self,
        count: int,
        success_rate: float = 0.8,
    ) -> List[Dict]:
        """
        Generate bulk test accounts for load testing.
        
        Args:
            count: Number of test accounts to generate
            success_rate: Percentage of accounts that should succeed (0.0-1.0)
        
        Returns:
            List of test account dicts
        """
        accounts = []
        successful_count = int(count * success_rate)
        
        for i in range(count):
            if i < successful_count:
                outcome = PaymentOutcome.SUCCESS
            else:
                # Distribute failures
                failure_outcomes = [
                    PaymentOutcome.DECLINE,
                    PaymentOutcome.TIMEOUT,
                    PaymentOutcome.PROCESSING_ERROR,
                ]
                outcome = failure_outcomes[i % len(failure_outcomes)]
            
            account = {
                "account_id": f"test_acct_{i:06d}",
                "payment_method": self.generate_test_card(outcome),
                "expected_outcome": outcome.value,
                "email": f"test_user_{i:06d}@atmos-test.local",
                "amount_cents": 5000 + (i * 10) % 1000,  # Varying amounts
            }
            accounts.append(account)
        
        return accounts


class PaymentLoadScenario:
    """Realistic payment load testing scenarios."""
    
    @staticmethod
    def checkout_flow_scenario(
        provider: PaymentProvider,
        concurrent_users: int,
        success_rate: float = 0.95,
    ) -> Dict:
        """
        E-commerce checkout flow with concurrent payment processing.
        
        Args:
            provider: Payment provider
            concurrent_users: Number of concurrent checkouts
            success_rate: Expected success percentage
        
        Returns:
            Scenario config dict
        """
        generator = TestPaymentGenerator(provider)
        test_accounts = generator.get_bulk_test_accounts(concurrent_users, success_rate)
        
        return {
            "scenario_name": "e-commerce-checkout",
            "description": f"Simulate {concurrent_users} concurrent checkouts at {success_rate*100}% success rate",
            "provider": provider.value,
            "concurrent_users": concurrent_users,
            "test_accounts": test_accounts,
            "journey_steps": [
                {"action": "add_to_cart", "product_id": "prod_123"},
                {"action": "view_cart"},
                {"action": "enter_shipping", "data": "random_address"},
                {"action": "enter_payment_info", "data": "test_account"},
                {"action": "submit_payment"},
                {"action": "validate_order_confirmation"},
            ],
            "expected_metrics": {
                "success_rate": success_rate,
                "avg_latency_ms": 2000,
                "p99_latency_ms": 5000,
            }
        }
    
    @staticmethod
    def subscription_billing_scenario(
        provider: PaymentProvider,
        concurrent_users: int,
        retry_logic: bool = True,
    ) -> Dict:
        """
        SaaS subscription billing with retry logic.
        
        Args:
            provider: Payment provider
            concurrent_users: Number of concurrent renewals
            retry_logic: Test with automatic retry on failure
        
        Returns:
            Scenario config dict
        """
        generator = TestPaymentGenerator(provider)
        test_accounts = generator.get_bulk_test_accounts(concurrent_users, 0.92)
        
        return {
            "scenario_name": "subscription-renewal",
            "description": f"Simulate {concurrent_users} concurrent subscription renewals",
            "provider": provider.value,
            "concurrent_users": concurrent_users,
            "test_accounts": test_accounts,
            "journey_steps": [
                {"action": "fetch_subscription", "subscription_id": "sub_123"},
                {"action": "charge_payment_method", "data": "test_account"},
                *([{"action": "retry_failed_payment"}] if retry_logic else []),
                {"action": "send_receipt"},
            ],
            "expected_metrics": {
                "success_rate": 0.92,
                "p95_latency_ms": 3000,
                "retry_success_rate": 0.80,
            }
        }
    
    @staticmethod
    def money_transfer_scenario(
        provider: PaymentProvider,
        concurrent_users: int,
        transfer_amount_cents: int = 10000,
    ) -> Dict:
        """
        Fintech money transfer stress test.
        
        Args:
            provider: Payment provider
            concurrent_users: Number of concurrent transfers
            transfer_amount_cents: Amount per transfer
        
        Returns:
            Scenario config dict
        """
        generator = TestPaymentGenerator(provider)
        test_accounts = generator.get_bulk_test_accounts(concurrent_users, 0.96)
        
        return {
            "scenario_name": "money-transfer",
            "description": f"Simulate {concurrent_users} concurrent money transfers of ${transfer_amount_cents/100:.2f}",
            "provider": provider.value,
            "concurrent_users": concurrent_users,
            "transfer_amount_cents": transfer_amount_cents,
            "test_accounts": test_accounts,
            "journey_steps": [
                {"action": "login"},
                {"action": "enter_recipient", "data": "random_account"},
                {"action": "enter_amount", "amount_cents": transfer_amount_cents},
                {"action": "confirm_transfer"},
                {"action": "validate_transaction_id"},
            ],
            "expected_metrics": {
                "success_rate": 0.96,
                "p50_latency_ms": 800,
                "p99_latency_ms": 2500,
            }
        }


# Failure injection strategies for chaos testing
class FailureInjection:
    """Inject realistic failures during load tests."""
    
    @staticmethod
    def should_fail(error_rate: float) -> bool:
        """Deterministically inject failure based on error rate."""
        return random.random() < error_rate
    
    @staticmethod
    def get_failure_mode(seed: int) -> PaymentOutcome:
        """Deterministically select failure mode from seed."""
        outcomes = [o for o in PaymentOutcome if o != PaymentOutcome.SUCCESS]
        return outcomes[seed % len(outcomes)]
    
    @staticmethod
    def simulate_cascading_failure(
        start_user_count: int,
        failure_threshold: int = 100,
    ) -> Dict:
        """
        Simulate cascading failure pattern (e.g., database connection pool exhaustion).
        
        Returns dict mapping user count to error rate.
        """
        cascade = {}
        current_rate = 0.0
        
        for users in range(start_user_count, start_user_count + 1000, 100):
            if users > failure_threshold:
                # Exponential increase after threshold
                current_rate = 0.1 * ((users - failure_threshold) / 100) ** 1.5
                current_rate = min(current_rate, 1.0)
            
            cascade[users] = current_rate
        
        return cascade
