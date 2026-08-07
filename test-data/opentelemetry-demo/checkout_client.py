"""Drive the pinned official Demo checkout path without browser or cloud dependencies."""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path
from types import ModuleType

import grpc


def _modules(proto_dir: Path) -> tuple[ModuleType, ModuleType]:
    sys.path.insert(0, str(proto_dir))
    return importlib.import_module("demo_pb2"), importlib.import_module("demo_pb2_grpc")


def _valid_demo_card() -> str:
    # Generate a Luhn-valid synthetic VISA number without storing any account-like fixture value.
    digits = [4, *([0] * 14)]
    checksum = 0
    for index, digit in enumerate(reversed(digits)):
        value = digit * 2 if index % 2 == 0 else digit
        checksum += value - 9 if value > 9 else value
    return "".join(str(digit) for digit in digits) + str((-checksum) % 10)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proto-dir", type=Path, required=True)
    parser.add_argument("--cart-endpoint", required=True)
    parser.add_argument("--checkout-endpoint", required=True)
    args = parser.parse_args()
    messages, services = _modules(args.proto_dir)

    user_id = "fixture-user"
    with (
        grpc.insecure_channel(args.cart_endpoint) as cart_channel,
        grpc.insecure_channel(args.checkout_endpoint) as checkout_channel,
    ):
        grpc.channel_ready_future(cart_channel).result(timeout=20)
        grpc.channel_ready_future(checkout_channel).result(timeout=20)
        cart = services.CartServiceStub(cart_channel)
        checkout = services.CheckoutServiceStub(checkout_channel)

        try:
            checkout.PlaceOrder(
                messages.PlaceOrderRequest(user_id="empty-fixture-user"), timeout=20
            )
        except grpc.RpcError as error:
            print(f"captured expected empty-cart outcome: {error.code().name}")

        cart.AddItem(
            messages.AddItemRequest(
                user_id=user_id,
                item=messages.CartItem(product_id="0PUK6V6EV0", quantity=1),
            ),
            timeout=20,
        )
        request = messages.PlaceOrderRequest(
            user_id=user_id,
            user_currency="USD",
            email="fixture" + chr(64) + "example.com",
            address=messages.Address(
                street_address="fixture-street",
                city="fixture-city",
                state="fixture-state",
                country="fixture-country",
                zip_code="00000",
            ),
            credit_card=messages.CreditCardInfo(
                credit_card_number=_valid_demo_card(),
                credit_card_cvv=111,
                credit_card_expiration_year=2039,
                credit_card_expiration_month=1,
            ),
        )
        checkout.PlaceOrder(request, timeout=30)

        cart.AddItem(
            messages.AddItemRequest(
                user_id=user_id,
                item=messages.CartItem(product_id="1YMWWN1N4O", quantity=1),
            ),
            timeout=20,
        )
        checkout.PlaceOrder(request, timeout=30)

    print("captured one expected failure and two successful official Demo checkouts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
