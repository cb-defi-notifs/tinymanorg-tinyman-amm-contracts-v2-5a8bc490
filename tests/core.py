import unittest
from decimal import Decimal

from algosdk.atomic_transaction_composer import AtomicTransactionComposer, TransactionWithSigner
from algosdk.encoding import decode_address
from algosdk.future import transaction
from algosdk.future.transaction import SuggestedParams

from .constants import *


class BaseTestCase(unittest.TestCase):
    maxDiff = None

    def create_amm_app(self):
        if self.app_creator_address not in self.ledger.accounts:
            self.ledger.set_account_balance(self.app_creator_address, 1_000_000)

        self.ledger.create_app(app_id=APPLICATION_ID, approval_program=amm_approval_program, creator=self.app_creator_address)
        self.ledger.set_global_state(
            APPLICATION_ID,
            {
                b'fee_collector': decode_address(self.app_creator_address),
                b'fee_manager': decode_address(self.app_creator_address),
                b'fee_setter': decode_address(self.app_creator_address),
            }
        )

    def bootstrap_pool(self):
        asset_2_id = getattr(self, "asset_2_id", ALGO_ASSET_ID)
        minimum_balance = 500_000 if asset_2_id else 400_000

        # Set Algo balance
        self.ledger.set_account_balance(self.pool_address, minimum_balance)

        # Rekey to application address
        self.ledger.set_auth_addr(self.pool_address, APPLICATION_ADDRESS)

        # Opt-in to assets
        self.ledger.set_account_balance(self.pool_address, 0, asset_id=self.asset_1_id)
        if asset_2_id != 0:
            self.ledger.set_account_balance(self.pool_address, 0, asset_id=self.asset_2_id)

        # Create pool token
        self.pool_token_asset_id = self.ledger.create_asset(asset_id=None, params=dict(creator=APPLICATION_ADDRESS))

        # Transfer Algo to application address
        self.ledger.set_account_balance(APPLICATION_ADDRESS, 200_000)

        # Transfer pool tokens from application adress to pool
        self.ledger.set_account_balance(APPLICATION_ADDRESS, 0, asset_id=self.pool_token_asset_id)
        self.ledger.set_account_balance(self.pool_address, POOL_TOKEN_TOTAL_SUPPLY, asset_id=self.pool_token_asset_id)

        self.ledger.set_local_state(
            address=self.pool_address,
            app_id=APPLICATION_ID,
            state={
                b'asset_1_id': self.asset_1_id,
                b'asset_2_id': asset_2_id,
                b'pool_token_asset_id': self.pool_token_asset_id,

                b'poolers_fee_share': POOLERS_FEE_SHARE,
                b'protocol_fee_share': PROTOCOL_FEE_SHARE,

                b'asset_1_reserves': 0,
                b'asset_2_reserves': 0,
                b'issued_pool_tokens': 0,

                b'cumulative_asset_1_price': BYTE_ZERO,
                b'cumulative_asset_2_price': BYTE_ZERO,
                b'cumulative_price_update_timestamp': 0,

                b'protocol_fees_asset_1': 0,
                b'protocol_fees_asset_2': 0
            }
        )

    def set_initial_pool_liquidity(self, asset_1_reserves, asset_2_reserves, liquidity_provider_address=None):
        issued_pool_token_amount = int(Decimal.sqrt(Decimal(asset_1_reserves) * Decimal(asset_2_reserves)))
        pool_token_out_amount = issued_pool_token_amount - LOCKED_POOL_TOKENS
        assert pool_token_out_amount > 0

        self.ledger.update_local_state(
            address=self.pool_address,
            app_id=APPLICATION_ID,
            state_delta={
                b'asset_1_reserves': asset_1_reserves,
                b'asset_2_reserves': asset_2_reserves,
                b'issued_pool_tokens': issued_pool_token_amount,
            }
        )

        self.ledger.move(sender=liquidity_provider_address, receiver=self.pool_address, amount=asset_1_reserves, asset_id=self.asset_1_id)
        self.ledger.move(sender=liquidity_provider_address, receiver=self.pool_address, amount=asset_2_reserves, asset_id=self.asset_2_id)
        self.ledger.move(sender=self.pool_address, receiver=liquidity_provider_address, amount=pool_token_out_amount, asset_id=self.pool_token_asset_id)

    def set_pool_protocol_fees(self, protocol_fees_asset_1, protocol_fees_asset_2):
        self.ledger.update_local_state(
            address=self.pool_address,
            app_id=APPLICATION_ID,
            state_delta={
                b'protocol_fees_asset_1': protocol_fees_asset_1,
                b'protocol_fees_asset_2': protocol_fees_asset_2,
            }
        )

        self.ledger.move(receiver=self.pool_address, amount=protocol_fees_asset_1, asset_id=self.asset_1_id)
        self.ledger.move(receiver=self.pool_address, amount=protocol_fees_asset_2, asset_id=self.asset_1_id)

    def get_add_liquidity_transactions(self, asset_1_amount, asset_2_amount, app_call_fee=None):
        txn_group = [
            transaction.AssetTransferTxn(
                sender=self.user_addr,
                sp=self.sp,
                receiver=self.pool_address,
                index=self.asset_1_id,
                amt=asset_1_amount,
            ),
            transaction.AssetTransferTxn(
                sender=self.user_addr,
                sp=self.sp,
                receiver=self.pool_address,
                index=self.asset_2_id,
                amt=asset_2_amount,
            ) if self.asset_2_id else transaction.PaymentTxn(
                sender=self.user_addr,
                sp=self.sp,
                receiver=self.pool_address,
                amt=asset_2_amount,
            ),
            transaction.ApplicationNoOpTxn(
                sender=self.user_addr,
                sp=self.sp,
                index=APPLICATION_ID,
                app_args=[METHOD_ADD_LIQUIDITY],
                foreign_assets=[self.asset_1_id, self.asset_2_id, self.pool_token_asset_id] if self.asset_2_id else [self.asset_1_id, self.pool_token_asset_id],
                accounts=[self.pool_address],
            )
        ]
        txn_group[2].fee = app_call_fee or self.sp.fee
        return txn_group

    def get_abi_add_liquidity_atomic_composer(self, asset_1_amount, asset_2_amount, signer, app_call_fee=None):
        composer = AtomicTransactionComposer()
        asset_1_txn = TransactionWithSigner(
            txn=transaction.AssetTransferTxn(
                sender=self.user_addr,
                sp=self.sp,
                receiver=self.pool_address,
                index=self.asset_1_id,
                amt=asset_1_amount,
            ),
            signer=signer
        )

        if self.asset_2_id:
            asset_2_txn = TransactionWithSigner(
                txn=transaction.AssetTransferTxn(
                    sender=self.user_addr,
                    sp=self.sp,
                    receiver=self.pool_address,
                    index=self.asset_2_id,
                    amt=asset_2_amount,
                ),
                signer=signer
            )
        else:
            asset_2_txn = TransactionWithSigner(
                txn=transaction.PaymentTxn(
                    sender=self.user_addr,
                    sp=self.sp,
                    receiver=self.pool_address,
                    amt=asset_2_amount,
                ),
                signer=signer
            )

        composer.add_method_call(
            app_id=APPLICATION_ID,
            method=contract.get_method_by_name(METHOD_ADD_LIQUIDITY),
            sender=self.user_addr,
            sp=SuggestedParams(**{**self.sp.__dict__, **{"fee": app_call_fee or self.sp.fee}}),
            signer=signer,
            method_args=[
                asset_1_txn,
                asset_2_txn,
                self.asset_1_id,
                self.asset_2_id,
                self.pool_token_asset_id,
                self.pool_address
            ],
        )
        return composer

    def get_remove_liquidity_transactions(self, liquidity_asset_amount, app_call_fee=None):
        txn_group = [
            transaction.AssetTransferTxn(
                sender=self.user_addr,
                sp=self.sp,
                receiver=self.pool_address,
                index=self.pool_token_asset_id,
                amt=liquidity_asset_amount,
            ),
            transaction.ApplicationNoOpTxn(
                sender=self.user_addr,
                sp=self.sp,
                index=APPLICATION_ID,
                app_args=[METHOD_REMOVE_LIQUIDITY],
                foreign_assets=[self.asset_1_id, self.asset_2_id],
                accounts=[self.pool_address],
            )
        ]
        txn_group[1].fee = app_call_fee or self.sp.fee
        return txn_group

    def get_abi_remove_liquidity_atomic_composer(self, liquidity_asset_amount, signer, app_call_fee=None):
        composer = AtomicTransactionComposer()
        pool_liquidity_txn = TransactionWithSigner(
            txn=transaction.AssetTransferTxn(
                sender=self.user_addr,
                sp=self.sp,
                receiver=self.pool_address,
                index=self.pool_token_asset_id,
                amt=liquidity_asset_amount,
            ),
            signer=signer
        )

        composer.add_method_call(
            app_id=APPLICATION_ID,
            method=contract.get_method_by_name(METHOD_REMOVE_LIQUIDITY),
            sender=self.user_addr,
            sp=SuggestedParams(**{**self.sp.__dict__, **{"fee": app_call_fee or self.sp.fee}}),
            signer=signer,
            method_args=[
                pool_liquidity_txn,
                self.asset_1_id,
                self.asset_2_id,
                self.pool_address
            ],
        )
        return composer

    def get_claim_fee_transactions(self, fee_collector, app_call_fee=None):
        txn_group = [
            transaction.ApplicationNoOpTxn(
                sender=fee_collector,
                sp=self.sp,
                index=APPLICATION_ID,
                app_args=[METHOD_CLAIM_FEES],
                foreign_assets=[self.asset_1_id, self.asset_2_id] if self.asset_2_id else [self.asset_1_id],
                accounts=[self.pool_address],
            )
        ]
        txn_group[0].fee = app_call_fee or self.sp.fee
        return txn_group

    def get_abi_claim_fee_atomic_composer(self, fee_collector, signer, app_call_fee=None):
        composer = AtomicTransactionComposer()
        composer.add_method_call(
            app_id=APPLICATION_ID,
            method=contract.get_method_by_name(METHOD_CLAIM_FEES),
            sender=fee_collector,
            sp=SuggestedParams(**{**self.sp.__dict__, **{"fee": app_call_fee or self.sp.fee}}),
            signer=signer,
            method_args=[
                self.asset_1_id,
                self.asset_2_id,
                self.pool_address
            ],
        )
        return composer

    def get_claim_extra_transactions(self, fee_collector, app_call_fee=None):
        txn_group = [
            transaction.ApplicationNoOpTxn(
                sender=fee_collector,
                sp=self.sp,
                index=APPLICATION_ID,
                app_args=[METHOD_CLAIM_EXTRA],
                foreign_assets=[self.asset_1_id, self.asset_2_id] if self.asset_2_id else [self.asset_1_id],
                accounts=[self.pool_address],
            )
        ]
        txn_group[0].fee = app_call_fee or self.sp.fee
        return txn_group

    def get_abi_claim_extra_atomic_composer(self, fee_collector, signer, app_call_fee=None):
        composer = AtomicTransactionComposer()
        composer.add_method_call(
            app_id=APPLICATION_ID,
            method=contract.get_method_by_name(METHOD_CLAIM_EXTRA),
            sender=fee_collector,
            sp=SuggestedParams(**{**self.sp.__dict__, **{"fee": app_call_fee or self.sp.fee}}),
            signer=signer,
            method_args=[
                self.asset_1_id,
                self.asset_2_id,
                self.pool_address
            ],
        )
        return composer

    def get_set_fee_transactions(self, fee_setter, poolers_fee_share, protocol_fee_share, app_call_fee=None):
        txn_group = [
            transaction.ApplicationNoOpTxn(
                sender=fee_setter,
                sp=self.sp,
                index=APPLICATION_ID,
                app_args=[METHOD_SET_FEE, poolers_fee_share, protocol_fee_share],
                accounts=[self.pool_address],
            )
        ]
        txn_group[0].fee = app_call_fee or self.sp.fee
        return txn_group

    def get_abi_set_fee_atomic_composer(self, fee_setter, poolers_fee_share, protocol_fee_share, signer, app_call_fee=None):
        composer = AtomicTransactionComposer()
        composer.add_method_call(
            app_id=APPLICATION_ID,
            method=contract.get_method_by_name(METHOD_SET_FEE),
            sender=fee_setter,
            sp=SuggestedParams(**{**self.sp.__dict__, **{"fee": app_call_fee or self.sp.fee}}),
            signer=signer,
            method_args=[
                poolers_fee_share,
                protocol_fee_share,
                self.pool_address
            ],
        )
        return composer

    @classmethod
    def sign_txns(cls, txns, secret_key):
        return [txn.sign(secret_key)for txn in txns]
