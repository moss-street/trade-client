import argparse
import getpass
import math
import os
import sys
import uuid

import grpc
from api_models import auth, trade

sys.modules.setdefault("auth", auth)
sys.modules.setdefault("trade", trade)

from api_models.auth.v1 import auth_pb2, auth_pb2_grpc
from api_models.trade.v1 import trading_pb2, trading_pb2_grpc


def parse_args():
    parser = argparse.ArgumentParser(description="Trade service gRPC client")
    parser.add_argument("--target", default="127.0.0.1:8080")
    parser.add_argument("--email", required=True)
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create")
    create.add_argument("--source", required=True)
    create.add_argument("--destination", required=True)
    create.add_argument("--quantity", required=True, type=float)
    create.add_argument("--side", choices=("buy", "sell"), default="buy")
    create.add_argument("--type", choices=("market", "limit"), default="limit")
    create.add_argument("--price", type=float)

    get = commands.add_parser("get")
    get.add_argument("trade_id", type=int)

    delete = commands.add_parser("delete")
    delete.add_argument("trade_id", type=int)

    balance = commands.add_parser("balance")
    balance.add_argument("symbol")

    sequence = commands.add_parser("sequence")
    sequence.add_argument("--source", required=True)
    sequence.add_argument("--destination", required=True)
    sequence.add_argument("--quantity", required=True, type=float)
    sequence.add_argument("--side", choices=("buy", "sell"), default="buy")
    sequence.add_argument("--type", choices=("market", "limit"), default="limit")
    sequence.add_argument("--price", type=float)

    simulate = commands.add_parser(
        "simulate",
        help="Run isolated matching and cancellation scenarios against a live server",
    )
    simulate.add_argument("--rounds", type=int, default=1)
    simulate.add_argument(
        "--email-prefix",
        default="simulation",
        help="Prefix for unique simulation account emails",
    )
    return parser.parse_args()


def login(auth_stub, email, password=None):
    if password is None:
        password = os.environ.get("MARKET_SIM_PASSWORD")
    if password is None:
        password = getpass.getpass("Password: ")

    response = auth_stub.LoginUser(
        auth_pb2.LoginUserRequest(email=email, password=password)
    )
    if (
        response.status != auth_pb2.LoginUserResponse.STATUS_OK
        or not response.HasField("user")
    ):
        raise RuntimeError("Login failed")
    if not response.user.HasField("token") or not response.user.token.token:
        raise RuntimeError("Login response did not include an auth token")
    return response.user.token.token


def create_trade(stub, metadata, args):
    response = submit_trade(
        stub,
        metadata,
        args.source,
        args.destination,
        args.quantity,
        args.side,
        args.type,
        args.price,
    )
    print(response)
    return response


def submit_trade(
    stub, metadata, source, destination, quantity, side, trade_type_name, price
):
    if quantity <= 0:
        raise ValueError("--quantity must be greater than zero")
    if trade_type_name == "limit" and price is None:
        raise ValueError("--price is required for limit orders")
    if trade_type_name == "market" and price is not None:
        raise ValueError("--price cannot be used with market orders")

    trade_type = (
        trading_pb2.TradeRequest.TRADE_TYPE_LIMIT
        if trade_type_name == "limit"
        else trading_pb2.TradeRequest.TRADE_TYPE_MARKET
    )
    transaction_type = (
        trading_pb2.TradeRequest.TRANSACTION_TYPE_BUY
        if side == "buy"
        else trading_pb2.TradeRequest.TRANSACTION_TYPE_SELL
    )
    request = trading_pb2.CreateTradeRequest(
        trade_request=trading_pb2.TradeRequest(
            trade_type=trade_type,
            transaction_type=transaction_type,
            symbol_source=source,
            symbol_dest=destination,
            source_quantity=quantity,
            **({"price": price} if price is not None else {}),
        )
    )
    response = stub.CreateTrade(request, metadata=metadata)
    if response.status != trading_pb2.CreateTradeResponse.CREATE_TRADE_STATUS_OK:
        raise RuntimeError("Trade creation failed")
    return response


def create_simulation_session(auth_stub, email, password):
    created = auth_stub.CreateUser(
        auth_pb2.CreateUserRequest(
            email=email,
            password=password,
            first_name="Simulation",
            last_name="Trader",
        )
    )
    if created.status != auth_pb2.CreateUserResponse.STATUS_OK:
        raise RuntimeError(
            f"Could not create simulation user {email}: {created.message}"
        )
    return (("auth", login(auth_stub, email, password)),)


def balance(stub, metadata, symbol):
    response = stub.GetWalletBalance(
        trading_pb2.GetWalletBalanceRequest(symbol=symbol),
        metadata=metadata,
    )
    if (
        response.status
        != trading_pb2.GetWalletBalanceResponse.GET_WALLET_BALANCE_STATUS_OK
    ):
        raise RuntimeError(f"Could not fetch {symbol} balance")
    return response.balance


def assert_balance(stub, metadata, symbol, expected):
    actual = balance(stub, metadata, symbol)
    if not math.isclose(actual, expected, rel_tol=0, abs_tol=1e-9):
        raise RuntimeError(
            f"Unexpected {symbol} balance: expected {expected}, got {actual}"
        )


def assert_trade_found(stub, metadata, trade_id):
    found = stub.GetTrade(
        trading_pb2.GetTradeRequest(trade_id=trade_id),
        metadata=metadata,
    )
    if found.status != trading_pb2.GetTradeResponse.GET_TRADE_STATUS_OK:
        raise RuntimeError(f"Trade {trade_id.trade_id} was not retained")


def cancel_trade(stub, metadata, trade_id):
    cancelled = stub.DeleteTrade(
        trading_pb2.DeleteTradeRequest(trade_id=trade_id),
        metadata=metadata,
    )
    if cancelled.status != trading_pb2.DeleteTradeResponse.DELETE_TRADE_STATUS_OK:
        raise RuntimeError(f"Trade {trade_id.trade_id} was not cancelled")


def simulation_session(auth_stub, password, email_prefix, run_id, round_number, role):
    email = f"{email_prefix}-{role}-{run_id}-{round_number}@example.com"
    return create_simulation_session(auth_stub, email, password)


def run_limit_order_scenario(
    auth_stub, trade_stub, password, email_prefix, run_id, round_number
):
    cheap_seller = simulation_session(
        auth_stub, password, email_prefix, run_id, round_number, "cheap-limit-seller"
    )
    expensive_seller = simulation_session(
        auth_stub,
        password,
        email_prefix,
        run_id,
        round_number,
        "expensive-limit-seller",
    )
    buyer = simulation_session(
        auth_stub, password, email_prefix, run_id, round_number, "limit-buyer"
    )

    cheap = submit_trade(
        trade_stub, cheap_seller, "USD", "BTC", 1.0, "sell", "limit", 2.0
    )
    expensive = submit_trade(
        trade_stub, expensive_seller, "USD", "BTC", 1.0, "sell", "limit", 4.0
    )
    buyer_trade = submit_trade(
        trade_stub, buyer, "BTC", "USD", 3.0, "buy", "limit", 0.5
    )

    assert_balance(trade_stub, cheap_seller, "USD", 49.0)
    assert_balance(trade_stub, cheap_seller, "BTC", 52.0)
    assert_balance(trade_stub, expensive_seller, "USD", 49.0)
    assert_balance(trade_stub, expensive_seller, "BTC", 51.0)
    assert_balance(trade_stub, buyer, "BTC", 47.0)
    assert_balance(trade_stub, buyer, "USD", 51.25)
    assert_trade_found(trade_stub, buyer, buyer_trade.trade_id)

    cancel_trade(trade_stub, expensive_seller, expensive.trade_id)
    assert_balance(trade_stub, expensive_seller, "USD", 49.75)
    assert_trade_found(trade_stub, cheap_seller, cheap.trade_id)


def run_market_order_scenario(
    auth_stub, trade_stub, password, email_prefix, run_id, round_number
):
    seller = simulation_session(
        auth_stub, password, email_prefix, run_id, round_number, "market-seller"
    )
    buyer = simulation_session(
        auth_stub, password, email_prefix, run_id, round_number, "market-buyer"
    )
    unmatched_buyer = simulation_session(
        auth_stub,
        password,
        email_prefix,
        run_id,
        round_number,
        "unmatched-market-buyer",
    )

    submit_trade(trade_stub, seller, "USD", "BTC", 1.0, "sell", "limit", 2.0)
    market = submit_trade(trade_stub, buyer, "BTC", "USD", 4.0, "buy", "market", None)

    assert_balance(trade_stub, seller, "USD", 49.0)
    assert_balance(trade_stub, seller, "BTC", 52.0)
    assert_balance(trade_stub, buyer, "BTC", 48.0)
    assert_balance(trade_stub, buyer, "USD", 51.0)
    assert_trade_found(trade_stub, buyer, market.trade_id)

    unmatched = submit_trade(
        trade_stub, unmatched_buyer, "BTC", "USD", 5.0, "buy", "market", None
    )
    assert_balance(trade_stub, unmatched_buyer, "BTC", 50.0)
    assert_balance(trade_stub, unmatched_buyer, "USD", 50.0)
    assert_trade_found(trade_stub, unmatched_buyer, unmatched.trade_id)


def run_simulation(channel, args, password):
    if args.rounds <= 0:
        raise ValueError("--rounds must be greater than zero")

    auth_stub = auth_pb2_grpc.AuthorizationServiceStub(channel)
    trade_stub = trading_pb2_grpc.TradeServiceStub(channel)
    run_id = uuid.uuid4().hex

    for round_number in range(args.rounds):
        run_limit_order_scenario(
            auth_stub,
            trade_stub,
            password,
            args.email_prefix,
            run_id,
            round_number,
        )
        run_market_order_scenario(
            auth_stub,
            trade_stub,
            password,
            args.email_prefix,
            run_id,
            round_number,
        )
        print(
            f"Simulation round {round_number + 1}/{args.rounds} passed "
            "(limit price priority, partial fills, cancellation, and market orders)"
        )


def main():
    args = parse_args()
    try:
        with grpc.insecure_channel(args.target) as channel:
            auth_stub = auth_pb2_grpc.AuthorizationServiceStub(channel)
            if args.command == "simulate":
                password = os.environ.get("MARKET_SIM_PASSWORD")
                if password is None:
                    password = getpass.getpass("Password for simulation accounts: ")
                run_simulation(channel, args, password)
                return 0

            token = login(auth_stub, args.email)
            metadata = (("auth", token),)
            trade_stub = trading_pb2_grpc.TradeServiceStub(channel)

            if args.command in ("create", "sequence"):
                created = create_trade(trade_stub, metadata, args)
                if args.command == "sequence":
                    trade_id = created.trade_id.trade_id
                    found = trade_stub.GetTrade(
                        trading_pb2.GetTradeRequest(
                            trade_id=trading_pb2.TradeId(trade_id=trade_id)
                        ),
                        metadata=metadata,
                    )
                    print(found)
                    if found.status != trading_pb2.GetTradeResponse.GET_TRADE_STATUS_OK:
                        raise RuntimeError("Trade lookup failed after creation")
                    deleted = trade_stub.DeleteTrade(
                        trading_pb2.DeleteTradeRequest(
                            trade_id=trading_pb2.TradeId(trade_id=trade_id)
                        ),
                        metadata=metadata,
                    )
                    print(deleted)
                    if (
                        deleted.status
                        != trading_pb2.DeleteTradeResponse.DELETE_TRADE_STATUS_OK
                    ):
                        raise RuntimeError("Trade deletion failed")
            elif args.command == "balance":
                response = trade_stub.GetWalletBalance(
                    trading_pb2.GetWalletBalanceRequest(symbol=args.symbol),
                    metadata=metadata,
                )
                print(response)
                if response.status not in (
                    trading_pb2.GetWalletBalanceResponse.GET_WALLET_BALANCE_STATUS_OK,
                    trading_pb2.GetWalletBalanceResponse.GET_WALLET_BALANCE_STATUS_NOT_FOUND,
                ):
                    raise RuntimeError("Wallet balance lookup failed")
            elif args.command == "get":
                response = trade_stub.GetTrade(
                    trading_pb2.GetTradeRequest(
                        trade_id=trading_pb2.TradeId(trade_id=args.trade_id)
                    ),
                    metadata=metadata,
                )
                print(response)
            else:
                response = trade_stub.DeleteTrade(
                    trading_pb2.DeleteTradeRequest(
                        trade_id=trading_pb2.TradeId(trade_id=args.trade_id)
                    ),
                    metadata=metadata,
                )
                print(response)
    except (grpc.RpcError, RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
