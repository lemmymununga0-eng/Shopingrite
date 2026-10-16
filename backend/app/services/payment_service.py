"""Simulated payment adapter for the demonstration checkout.

It never receives, stores or transmits card numbers or any other payment credentials, and it never
contacts a bank or payment provider. The result it returns says so plainly.
"""
from dataclasses import dataclass

NOTICE = ("DEMONSTRATION PAYMENT: this is a simulated checkout. No card was used and no money was taken or "
          "authorised by any bank.")


@dataclass(frozen=True)
class PaymentResult:
    mode: str
    status: str
    notice: str


class SimulatedPaymentAdapter:
    mode = "SIMULATED"

    def authorize(self, *, order_reference: str, amount_cents: int, currency: str) -> PaymentResult:
        # Intentionally trivial: there is nothing to authorise in a demonstration.
        return PaymentResult(mode=self.mode, status="simulated_approved", notice=NOTICE)


def notice_for(mode: str) -> str:
    return NOTICE if mode == "SIMULATED" else ""
