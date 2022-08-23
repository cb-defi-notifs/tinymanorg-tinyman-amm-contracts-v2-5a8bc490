from unittest.mock import ANY

from algojig import get_suggested_params
from algojig.exceptions import LogicEvalError
from algojig.ledger import JigLedger
from algosdk.account import generate_account
from algosdk.atomic_transaction_composer import AccountTransactionSigner
from algosdk.encoding import decode_address
from algosdk.future import transaction

from .constants import *
from .core import BaseTestCase
from .utils import get_pool_logicsig_bytecode


class TestRemoveLiquidity(BaseTestCase):

    @classmethod
    def setUpClass(cls):
        cls.sp = get_suggested_params()
        cls.app_creator_sk, cls.app_creator_address = generate_account()
        cls.user_sk, cls.user_addr = generate_account()
        cls.asset_1_id = 5
        cls.asset_2_id = 2

    def reset_ledger(self):
        self.ledger = JigLedger()
        self.create_amm_app()
        self.ledger.set_account_balance(self.user_addr, 1_000_000)
        self.ledger.set_account_balance(self.user_addr, MAX_ASSET_AMOUNT, asset_id=self.asset_1_id)
        self.ledger.set_account_balance(self.user_addr, MAX_ASSET_AMOUNT, asset_id=self.asset_2_id)

        lsig = get_pool_logicsig_bytecode(amm_pool_template, APPLICATION_ID, self.asset_1_id, self.asset_2_id)
        self.pool_address = lsig.address()
        self.bootstrap_pool()
        self.ledger.opt_in_asset(self.user_addr, self.pool_token_asset_id)

    def setUp(self):
        self.reset_ledger()

    def test_remove_liquidity(self):
        test_cases = [
            dict(
                msg="Test basic remove liquidity.",
                initials=dict(
                    asset_1_reserves=1_000_000,
                    asset_2_reserves=1_000_000,
                    issued_pool_token_amount=1_000_000,
                ),
                inputs=dict(
                    removed_pool_token_amount=5_000,
                ),
                outputs=dict(
                    asset_1_out=5_000,
                    asset_2_out=5_000,
                    local_state_delta={
                        b'asset_1_reserves': {b'at': 2, b'ui': 1_000_000 - 5_000},
                        b'asset_2_reserves': {b'at': 2, b'ui': 1_000_000 - 5_000},
                        b'issued_pool_tokens': {b'at': 2, b'ui': 1_000_000 - 5_000},
                    }
                )
            ),
            dict(
                msg="Test removing 0 pool token. It should fail because asset out amounts are 0.",
                initials=dict(
                    asset_1_reserves=1_000_000,
                    asset_2_reserves=1_000_000,
                    issued_pool_token_amount=1_000_000,
                ),
                inputs=dict(
                    removed_pool_token_amount=0,
                ),
                exception=dict(
                    source_line='assert(asset_1_amount && asset_2_amount)'
                )
            ),
            dict(
                msg="One of the asset out is 0 and asset out amounts are rounded down.",
                initials=dict(
                    asset_1_reserves=100_000_000,
                    asset_2_reserves=1,
                    issued_pool_token_amount=10_000,
                ),
                inputs=dict(
                    removed_pool_token_amount=500,
                ),
                exception=dict(
                    source_line='assert(asset_1_amount && asset_2_amount)'
                )
            ),
            dict(
                msg="Remove mistakenly added NFT (Remove all circulating pool tokens).",
                initials=dict(
                    asset_1_reserves=100_000_000,
                    asset_2_reserves=1,
                    issued_pool_token_amount=10_000,
                ),
                inputs=dict(
                    removed_pool_token_amount=10_000 - LOCKED_POOL_TOKENS,
                ),
                outputs=dict(
                    asset_1_out=100_000_000,
                    asset_2_out=1,
                    local_state_delta={
                        b'asset_1_reserves': {b'at': 2},
                        b'asset_2_reserves': {b'at': 2},
                        b'issued_pool_tokens': {b'at': 2},
                    }
                )
            )
        ]

        for test_case in test_cases:
            with self.subTest(**test_case):
                initials = test_case["initials"]
                inputs = test_case["inputs"]

                self.reset_ledger()
                self.set_initial_pool_liquidity(asset_1_reserves=initials["asset_1_reserves"], asset_2_reserves=initials["asset_2_reserves"], liquidity_provider_address=self.user_addr)
                self.assertEqual(initials["issued_pool_token_amount"], self.ledger.accounts[self.pool_address]['local_states'][APPLICATION_ID][b'issued_pool_tokens'])

                txn_group = self.get_remove_liquidity_transactions(liquidity_asset_amount=inputs["removed_pool_token_amount"], app_call_fee=3_000)
                txn_group = transaction.assign_group_id(txn_group)
                stxns = self.sign_txns(txn_group, self.user_sk)

                if exception := test_case.get("exception"):
                    with self.assertRaises(LogicEvalError) as e:
                        self.ledger.eval_transactions(stxns)

                    self.assertEqual(e.exception.source['line'], exception.get("source_line"))

                else:
                    outputs = test_case["outputs"]

                    block = self.ledger.eval_transactions(stxns)
                    block_txns = block[b'txns']

                    # outer transactions
                    self.assertEqual(len(block_txns), 2)

                    # outer transactions [0]
                    txn = block_txns[0]
                    self.assertEqual(
                        txn[b'txn'],
                        {
                            b'aamt': inputs["removed_pool_token_amount"],
                            b'arcv': decode_address(self.pool_address),
                            b'fee': self.sp.fee,
                            b'fv': self.sp.first,
                            b'grp': ANY,
                            b'lv': self.sp.last,
                            b'snd': decode_address(self.user_addr),
                            b'type': b'axfer',
                            b'xaid': self.pool_token_asset_id
                        }
                    )

                    # outer transactions [1]
                    txn = block_txns[1]
                    self.assertEqual(
                        txn[b'txn'],
                        {
                            b'apaa': [b'remove_liquidity'],
                            b'apas': [self.asset_1_id, self.asset_2_id],
                            b'apat': [decode_address(self.pool_address)],
                            b'apid': APPLICATION_ID,
                            b'fee': self.sp.fee * 3,
                            b'fv': self.sp.first,
                            b'grp': ANY,
                            b'lv': self.sp.last,
                            b'snd': decode_address(self.user_addr),
                            b'type': b'appl'
                        }
                    )

                    # inner transactions
                    inner_transactions = txn[b'dt'][b'itx']
                    self.assertEqual(len(inner_transactions), 2)

                    # inner transactions - [0]
                    self.assertDictEqual(
                        inner_transactions[0][b'txn'],
                        {
                            b'aamt': outputs["asset_1_out"],
                            b'arcv': decode_address(self.user_addr),
                            b'fv': self.sp.first,
                            b'lv': self.sp.last,
                            b'snd': decode_address(self.pool_address),
                            b'type': b'axfer',
                            b'xaid': self.asset_1_id
                        }
                    )

                    # inner transactions - [1]
                    self.assertDictEqual(
                        inner_transactions[1][b'txn'],
                        {
                            b'aamt': outputs["asset_2_out"],
                            b'arcv': decode_address(self.user_addr),
                            b'fv': self.sp.first,
                            b'lv': self.sp.last,
                            b'snd': decode_address(self.pool_address),
                            b'type': b'axfer',
                            b'xaid': self.asset_2_id
                        }
                    )

                    # local state delta
                    pool_local_state_delta = txn[b'dt'][b'ld'][1]
                    self.assertDictEqual(pool_local_state_delta, outputs["local_state_delta"])

    def test_abi_remove_liquidity(self):
        asset_1_reserves = 1_000_000
        asset_2_reserves = 1_000_000
        issued_pool_token_amount = 1_000_000
        removed_pool_token_amount = 5_000
        asset_1_out = 5_000
        asset_2_out = 5_000

        self.set_initial_pool_liquidity(asset_1_reserves=asset_1_reserves, asset_2_reserves=asset_2_reserves, liquidity_provider_address=self.user_addr)
        self.assertEqual(issued_pool_token_amount, self.ledger.accounts[self.pool_address]['local_states'][APPLICATION_ID][b'issued_pool_tokens'])

        method = contract.get_method_by_name(METHOD_REMOVE_LIQUIDITY)
        self.assertEqual(method.get_selector(), ABI_METHOD[METHOD_REMOVE_LIQUIDITY])

        user_signer = AccountTransactionSigner(self.user_sk)
        composer = self.get_abi_remove_liquidity_atomic_composer(liquidity_asset_amount=removed_pool_token_amount, signer=user_signer, app_call_fee=3_000)
        composer.gather_signatures()
        block = self.ledger.eval_transactions(composer.signed_txns)
        block_txns = block[b'txns']

        # outer transactions
        self.assertEqual(len(block_txns), 2)

        # outer transactions [0]
        txn = block_txns[0]
        self.assertEqual(
            txn[b'txn'],
            {
                b'aamt': removed_pool_token_amount,
                b'arcv': decode_address(self.pool_address),
                b'fee': self.sp.fee,
                b'fv': self.sp.first,
                b'grp': ANY,
                b'lv': self.sp.last,
                b'snd': decode_address(self.user_addr),
                b'type': b'axfer',
                b'xaid': self.pool_token_asset_id
            }
        )

        # outer transactions [1]
        txn = block_txns[1]
        self.assertEqual(
            txn[b'txn'],
            {
                b'apaa': [
                    ABI_METHOD[METHOD_REMOVE_LIQUIDITY],
                    # Assets
                    (0).to_bytes(1, "big"),
                    (1).to_bytes(1, "big"),
                    # Accounts
                    (1).to_bytes(1, "big"),
                ],
                b'apas': [self.asset_1_id, self.asset_2_id],
                b'apat': [decode_address(self.pool_address)],
                b'apid': APPLICATION_ID,
                b'fee': self.sp.fee * 3,
                b'fv': self.sp.first,
                b'grp': ANY,
                b'lv': self.sp.last,
                b'snd': decode_address(self.user_addr),
                b'type': b'appl'
            }
        )

        # inner transactions
        inner_transactions = txn[b'dt'][b'itx']
        self.assertEqual(len(inner_transactions), 2)

        # inner transactions - [0]
        self.assertDictEqual(
            inner_transactions[0][b'txn'],
            {
                b'aamt': asset_1_out,
                b'arcv': decode_address(self.user_addr),
                b'fv': self.sp.first,
                b'lv': self.sp.last,
                b'snd': decode_address(self.pool_address),
                b'type': b'axfer',
                b'xaid': self.asset_1_id
            }
        )

        # inner transactions - [1]
        self.assertDictEqual(
            inner_transactions[1][b'txn'],
            {
                b'aamt': asset_2_out,
                b'arcv': decode_address(self.user_addr),
                b'fv': self.sp.first,
                b'lv': self.sp.last,
                b'snd': decode_address(self.pool_address),
                b'type': b'axfer',
                b'xaid': self.asset_2_id
            }
        )

        # local state delta
        pool_local_state_delta = txn[b'dt'][b'ld'][1]
        self.assertDictEqual(
            pool_local_state_delta,
            {
                b'asset_1_reserves': {b'at': 2, b'ui': 1_000_000 - 5_000},
                b'asset_2_reserves': {b'at': 2, b'ui': 1_000_000 - 5_000},
                b'issued_pool_tokens': {b'at': 2, b'ui': 1_000_000 - 5_000},
            }
        )


class TestRemoveLiquidityAlgoPair(BaseTestCase):

    @classmethod
    def setUpClass(cls):
        cls.sp = get_suggested_params()
        cls.app_creator_sk, cls.app_creator_address = generate_account()
        cls.user_sk, cls.user_addr = generate_account()
        cls.asset_1_id = 5
        cls.asset_2_id = ALGO_ASSET_ID

    def reset_ledger(self):
        self.ledger = JigLedger()
        self.create_amm_app()
        self.ledger.set_account_balance(self.user_addr, 2_000_000)
        self.ledger.set_account_balance(self.user_addr, MAX_ASSET_AMOUNT, asset_id=self.asset_1_id)

        lsig = get_pool_logicsig_bytecode(amm_pool_template, APPLICATION_ID, self.asset_1_id, self.asset_2_id)
        self.pool_address = lsig.address()
        self.bootstrap_pool()
        self.ledger.opt_in_asset(self.user_addr, self.pool_token_asset_id)

    def setUp(self):
        self.reset_ledger()

    def test_remove_liquidity(self):
        test_cases = [
            dict(
                msg="Test basic remove liquidity.",
                initials=dict(
                    asset_1_reserves=1_000_000,
                    asset_2_reserves=1_000_000,
                    issued_pool_token_amount=1_000_000,
                ),
                inputs=dict(
                    removed_pool_token_amount=5_000,
                ),
                outputs=dict(
                    asset_1_out=5_000,
                    asset_2_out=5_000,
                    local_state_delta={
                        b'asset_1_reserves': {b'at': 2, b'ui': 1_000_000 - 5_000},
                        b'asset_2_reserves': {b'at': 2, b'ui': 1_000_000 - 5_000},
                        b'issued_pool_tokens': {b'at': 2, b'ui': 1_000_000 - 5_000},
                    }
                )
            ),
            dict(
                msg="Test removing 0 pool token. It should fail because asset out amounts are 0.",
                initials=dict(
                    asset_1_reserves=1_000_000,
                    asset_2_reserves=1_000_000,
                    issued_pool_token_amount=1_000_000,
                ),
                inputs=dict(
                    removed_pool_token_amount=0,
                ),
                exception=dict(
                    source_line='assert(asset_1_amount && asset_2_amount)'
                )
            ),
            dict(
                msg="One of the asset out is 0 and asset out amounts are rounded down.",
                initials=dict(
                    asset_1_reserves=100_000_000,
                    asset_2_reserves=1,
                    issued_pool_token_amount=10_000,
                ),
                inputs=dict(
                    removed_pool_token_amount=500,
                ),
                exception=dict(
                    source_line='assert(asset_1_amount && asset_2_amount)'
                )
            ),
            dict(
                msg="Remove mistakenly added NFT (Remove all circulating pool tokens).",
                initials=dict(
                    asset_1_reserves=100_000_000,
                    asset_2_reserves=1,
                    issued_pool_token_amount=10_000,
                ),
                inputs=dict(
                    removed_pool_token_amount=10_000 - LOCKED_POOL_TOKENS,
                ),
                outputs=dict(
                    asset_1_out=100_000_000,
                    asset_2_out=1,
                    local_state_delta={
                        b'asset_1_reserves': {b'at': 2},
                        b'asset_2_reserves': {b'at': 2},
                        b'issued_pool_tokens': {b'at': 2},
                    }
                )
            )
        ]

        for test_case in test_cases:
            with self.subTest(**test_case):
                initials = test_case["initials"]
                inputs = test_case["inputs"]

                self.reset_ledger()
                self.set_initial_pool_liquidity(asset_1_reserves=initials["asset_1_reserves"], asset_2_reserves=initials["asset_2_reserves"], liquidity_provider_address=self.user_addr)
                self.assertEqual(initials["issued_pool_token_amount"], self.ledger.accounts[self.pool_address]['local_states'][APPLICATION_ID][b'issued_pool_tokens'])

                txn_group = self.get_remove_liquidity_transactions(liquidity_asset_amount=inputs["removed_pool_token_amount"], app_call_fee=3_000)
                txn_group = transaction.assign_group_id(txn_group)
                stxns = self.sign_txns(txn_group, self.user_sk)

                if exception := test_case.get("exception"):
                    with self.assertRaises(LogicEvalError) as e:
                        self.ledger.eval_transactions(stxns)

                    self.assertEqual(e.exception.source['line'], exception.get("source_line"))

                else:
                    outputs = test_case["outputs"]

                    block = self.ledger.eval_transactions(stxns)
                    block_txns = block[b'txns']

                    # outer transactions
                    self.assertEqual(len(block_txns), 2)

                    # outer transactions [0]
                    txn = block_txns[0]
                    self.assertEqual(
                        txn[b'txn'],
                        {
                            b'aamt': inputs["removed_pool_token_amount"],
                            b'arcv': decode_address(self.pool_address),
                            b'fee': self.sp.fee,
                            b'fv': self.sp.first,
                            b'grp': ANY,
                            b'lv': self.sp.last,
                            b'snd': decode_address(self.user_addr),
                            b'type': b'axfer',
                            b'xaid': self.pool_token_asset_id
                        }
                    )

                    # outer transactions [1]
                    txn = block_txns[1]
                    self.assertEqual(
                        txn[b'txn'],
                        {
                            b'apaa': [b'remove_liquidity'],
                            b'apas': [self.asset_1_id, self.asset_2_id],
                            b'apat': [decode_address(self.pool_address)],
                            b'apid': APPLICATION_ID,
                            b'fee': self.sp.fee * 3,
                            b'fv': self.sp.first,
                            b'grp': ANY,
                            b'lv': self.sp.last,
                            b'snd': decode_address(self.user_addr),
                            b'type': b'appl'
                        }
                    )

                    # inner transactions
                    inner_transactions = txn[b'dt'][b'itx']
                    self.assertEqual(len(inner_transactions), 2)

                    # inner transactions - [0]
                    self.assertDictEqual(
                        inner_transactions[0][b'txn'],
                        {
                            b'aamt': outputs["asset_1_out"],
                            b'arcv': decode_address(self.user_addr),
                            b'fv': self.sp.first,
                            b'lv': self.sp.last,
                            b'snd': decode_address(self.pool_address),
                            b'type': b'axfer',
                            b'xaid': self.asset_1_id
                        }
                    )

                    # inner transactions - [1]
                    self.assertDictEqual(
                        inner_transactions[1][b'txn'],
                        {
                            b'amt': outputs["asset_2_out"],
                            b'rcv': decode_address(self.user_addr),
                            b'fv': self.sp.first,
                            b'lv': self.sp.last,
                            b'snd': decode_address(self.pool_address),
                            b'type': b'pay',
                        }
                    )

                    # local state delta
                    pool_local_state_delta = txn[b'dt'][b'ld'][1]
                    self.assertDictEqual(pool_local_state_delta, outputs["local_state_delta"])

    def test_abi_remove_liquidity(self):
        asset_1_reserves = 1_000_000
        asset_2_reserves = 1_000_000
        issued_pool_token_amount = 1_000_000
        removed_pool_token_amount = 5_000
        asset_1_out = 5_000
        asset_2_out = 5_000

        self.set_initial_pool_liquidity(asset_1_reserves=asset_1_reserves, asset_2_reserves=asset_2_reserves, liquidity_provider_address=self.user_addr)
        self.assertEqual(issued_pool_token_amount, self.ledger.accounts[self.pool_address]['local_states'][APPLICATION_ID][b'issued_pool_tokens'])

        method = contract.get_method_by_name(METHOD_REMOVE_LIQUIDITY)
        self.assertEqual(method.get_selector(), ABI_METHOD[METHOD_REMOVE_LIQUIDITY])

        user_signer = AccountTransactionSigner(self.user_sk)
        composer = self.get_abi_remove_liquidity_atomic_composer(liquidity_asset_amount=removed_pool_token_amount, signer=user_signer, app_call_fee=3_000)
        composer.gather_signatures()
        block = self.ledger.eval_transactions(composer.signed_txns)
        block_txns = block[b'txns']

        # outer transactions
        self.assertEqual(len(block_txns), 2)

        # outer transactions [0]
        txn = block_txns[0]
        self.assertEqual(
            txn[b'txn'],
            {
                b'aamt': removed_pool_token_amount,
                b'arcv': decode_address(self.pool_address),
                b'fee': self.sp.fee,
                b'fv': self.sp.first,
                b'grp': ANY,
                b'lv': self.sp.last,
                b'snd': decode_address(self.user_addr),
                b'type': b'axfer',
                b'xaid': self.pool_token_asset_id
            }
        )

        # outer transactions [1]
        txn = block_txns[1]
        self.assertEqual(
            txn[b'txn'],
            {
                b'apaa': [
                    ABI_METHOD[METHOD_REMOVE_LIQUIDITY],
                    # Assets
                    (0).to_bytes(1, "big"),
                    (1).to_bytes(1, "big"),
                    # Accounts
                    (1).to_bytes(1, "big"),
                ],
                b'apas': [self.asset_1_id, self.asset_2_id],
                b'apat': [decode_address(self.pool_address)],
                b'apid': APPLICATION_ID,
                b'fee': self.sp.fee * 3,
                b'fv': self.sp.first,
                b'grp': ANY,
                b'lv': self.sp.last,
                b'snd': decode_address(self.user_addr),
                b'type': b'appl'
            }
        )

        # inner transactions
        inner_transactions = txn[b'dt'][b'itx']
        self.assertEqual(len(inner_transactions), 2)

        # inner transactions - [0]
        self.assertDictEqual(
            inner_transactions[0][b'txn'],
            {
                b'aamt': asset_1_out,
                b'arcv': decode_address(self.user_addr),
                b'fv': self.sp.first,
                b'lv': self.sp.last,
                b'snd': decode_address(self.pool_address),
                b'type': b'axfer',
                b'xaid': self.asset_1_id
            }
        )

        # inner transactions - [1]
        self.assertDictEqual(
            inner_transactions[1][b'txn'],
            {
                b'amt': asset_2_out,
                b'rcv': decode_address(self.user_addr),
                b'fv': self.sp.first,
                b'lv': self.sp.last,
                b'snd': decode_address(self.pool_address),
                b'type': b'pay',
            }
        )

        # local state delta
        pool_local_state_delta = txn[b'dt'][b'ld'][1]
        self.assertDictEqual(
            pool_local_state_delta,
            {
                b'asset_1_reserves': {b'at': 2, b'ui': 1_000_000 - 5_000},
                b'asset_2_reserves': {b'at': 2, b'ui': 1_000_000 - 5_000},
                b'issued_pool_tokens': {b'at': 2, b'ui': 1_000_000 - 5_000},
            }
        )
