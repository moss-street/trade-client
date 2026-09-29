import argparse
import getpass
import os
import sys

import grpc
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
    return parser.parse_args()


def login(auth_stub, email):
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
    if args.quantity <= 0:
        raise ValueError("--quantity must be greater than zero")
    if args.type == "limit" and args.price is None:
        raise ValueError("--price is required for limit orders")
    if args.type == "market" and args.price is not None:
        raise ValueError("--price cannot be used with market orders")

    trade_type = (
        trading_pb2.TradeRequest.TRADE_TYPE_LIMIT
        if args.type == "limit"
        else trading_pb2.TradeRequest.TRADE_TYPE_MARKET
    )
    transaction_type = (
        trading_pb2.TradeRequest.TRANSACTION_TYPE_BUY
        if args.side == "buy"
        else trading_pb2.TradeRequest.TRANSACTION_TYPE_SELL
    )
    request = trading_pb2.CreateTradeRequest(
        trade_request=trading_pb2.TradeRequest(
            trade_type=trade_type,
            transaction_type=transaction_type,
            symbol_source=args.source,
            symbol_dest=args.destination,
            source_quantity=args.quantity,
            **({"price": args.price} if args.price is not None else {}),
        )
    )
    response = stub.CreateTrade(request, metadata=metadata)
    print(response)
    if response.status != trading_pb2.CreateTradeResponse.CREATE_TRADE_STATUS_OK:
        raise RuntimeError("Trade creation failed")
    return response


def main():
    args = parse_args()
    try:
        with grpc.insecure_channel(args.target) as channel:
            auth_stub = auth_pb2_grpc.AuthorizationServiceStub(channel)
            token = login(auth_stub, args.email)
            metadata = (("Auth", token),)
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
