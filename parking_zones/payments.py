import logging
import secrets
from django.conf import settings
from django.utils import timezone
from .models import PaymentTransaction
from .services import PaymentService

logger = logging.getLogger(__name__)


class DemoPaymentAdapter:
    """
    Explicitly labeled DEMO payment simulation adapter for SomPark.
    Used for local development and demonstration of deposit and exit payments.

    REAL PAYMENT PROVIDER INTEGRATION GUIDE:
    To integrate real Cambodian banking gateways (e.g. Bakong KHQR, ABA PayWay, Wing):
    1. Set settings.DEMO_PAYMENT_ENABLED = False in production.
    2. Implement cryptographic HMAC-SHA512 webhook signature verification.
    3. Register server-to-server callback URLs with the banking gateway.
    4. Validate currency == 'KHR', transaction amount matches server state,
       and store gateway reference codes in PaymentTransaction.raw_response.
    """

    @classmethod
    def is_enabled(cls) -> bool:
        return getattr(settings, 'DEMO_PAYMENT_ENABLED', True)

    @classmethod
    def simulate_payment(cls, txn_id: int, outcome: str) -> tuple[bool, str]:
        """
        Simulates payment outcomes: 'success', 'failure', or 'cancel'.
        Enforces that simulation can only run if DEMO_PAYMENT_ENABLED=True.
        """
        if not cls.is_enabled():
            raise PermissionDenied('Demo payment simulation is disabled in this environment.')

        txn = PaymentTransaction.objects.filter(id=txn_id).first()
        if not txn:
            return False, 'Transaction record not found.'

        if txn.status == 'SUCCESS':
            return True, 'Transaction is already completed successfully.'

        if outcome == 'success':
            ref = f"DEMO-OK-{secrets.token_hex(6).upper()}"
            success, msg = PaymentService.confirm_deposit(txn_id=txn.id, provider_ref=ref)
            return success, msg

        elif outcome == 'failure':
            txn.status = 'FAILED'
            txn.raw_response = {
                'simulated_at': timezone.now().isoformat(),
                'error': 'Simulated bank card / insufficient funds error'
            }
            txn.save(update_fields=['status', 'raw_response', 'updated_at'])
            return False, 'Simulated payment failure recorded. Customer may retry.'

        elif outcome == 'cancel':
            txn.status = 'CANCELLED'
            txn.raw_response = {
                'simulated_at': timezone.now().isoformat(),
                'reason': 'Customer cancelled checkout flow'
            }
            txn.save(update_fields=['status', 'raw_response', 'updated_at'])
            return False, 'Payment attempt was cancelled. Reservation hold remains active until timeout.'

        else:
            return False, f'Unknown simulation outcome: {outcome}'
