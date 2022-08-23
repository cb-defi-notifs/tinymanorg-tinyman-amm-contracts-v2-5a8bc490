from unittest.mock import ANY

from algojig import get_suggested_params
from algojig.exceptions import LogicEvalError
from algojig.ledger import JigLedger
from algosdk.account import generate_account
from algosdk.atomic_transaction_composer import AccountTransactionSigner
from algosdk.encoding import decode_address

from .constants import *
from .core import BaseTestCase
from .utils import get_pool_logicsig_bytecode


class TestClaimExtra(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        cls.sp = get_suggested_params()
        cls.app_creator_sk, cls.app_creator_address = generate_account()
        cls.user_sk, cls.user_addr = generate_account()
        cls.asset_1_id = 5
        cls.asset_2_id = 2

    def setUp(self):
        self.ledger = JigLedger()
        self.create_amm_app()
        self.ledger.set_account_balance(self.user_addr, 1_000_000)
        self.ledger.set_account_balance(self.user_addr, MAX_ASSET_AMOUNT, asset_id=self.asset_1_id)
        self.ledger.set_account_balance(self.user_addr, MAX_ASSET_AMOUNT, asset_id=self.asset_2_id)

        lsig = get_pool_logicsig_bytecode(amm_pool_template, APPLICATION_ID, self.asset_1_id, self.asset_2_id)
        self.pool_address = lsig.address()
        self.bootstrap_pool()
        self.ledger.opt_in_asset(self.user_addr, self.pool_token_asset_id)
        self.set_initial_pool_liquidity(asset_1_reserves=1_000_000, asset_2_reserves=1_000_000, liquidity_provider_address=self.user_addr)

    def test_pass(self):
        fee_collector = self.app_creator_address
        fee_collector_sk = self.app_creator_sk
        self.ledger.set_account_balance(fee_collector, 1_000_000)
        self.ledger.opt_in_asset(fee_collector, self.asset_1_id)
        self.ledger.opt_in_asset(fee_collector, self.asset_2_id)

        asset_1_extra = 5_000
        asset_2_extra = 10_000
        self.ledger.move(asset_1_extra, self.asset_1_id, receiver=self.pool_address)
        self.ledger.move(asset_2_extra, self.asset_2_id, receiver=self.pool_address)

        txn_group = self.get_claim_extra_transactions(fee_collector=fee_collector, app_call_fee=3_000)
        stxns = self.sign_txns(txn_group, fee_collector_sk)

        block = self.ledger.eval_transactions(stxns)
        block_txns = block[b'txns']

        # outer transactions
        self.assertEqual(len(block_txns), 1)
        txn = block_txns[0]
        self.assertDictEqual(
            txn[b'txn'],
            {
                b'apaa': [b'claim_extra'],
                b'apas': [self.asset_1_id, self.asset_2_id],
                b'apat': [decode_address(self.pool_address)],
                b'apid': APPLICATION_ID,
                b'fee': ANY,
                b'fv': ANY,
                b'lv': ANY,
                b'snd': decode_address(fee_collector),
                b'type': b'appl'
            }
        )

        inner_transactions = txn[b'dt'][b'itx']
        self.assertEqual(len(inner_transactions), 2)

        # inner transactions - [0]
        self.assertDictEqual(
            inner_transactions[0][b'txn'],
            {
                b'aamt': asset_1_extra,
                b'arcv': decode_address(fee_collector),
                b'fv': self.sp.first,
                b'lv': self.sp.last,
                b'snd': decode_address(self.pool_address),
                b'type': b'axfer',
                b'xaid': self.asset_1_id
            },
        )

        # inner transactions - [1]
        self.assertDictEqual(
            inner_transactions[1][b'txn'],
            {
                b'aamt': asset_2_extra,
                b'arcv': decode_address(fee_collector),
                b'fv': self.sp.first,
                b'lv': self.sp.last,
                b'snd': decode_address(self.pool_address),
                b'type': b'axfer',
                b'xaid': self.asset_2_id
            },
        )

    def test_abi_claim_extra(self):
        fee_collector = self.app_creator_address
        fee_collector_sk = self.app_creator_sk
        self.ledger.set_account_balance(fee_collector, 1_000_000)
        self.ledger.opt_in_asset(fee_collector, self.asset_1_id)
        self.ledger.opt_in_asset(fee_collector, self.asset_2_id)

        asset_1_extra = 5_000
        asset_2_extra = 10_000
        self.ledger.move(asset_1_extra, self.asset_1_id, receiver=self.pool_address)
        self.ledger.move(asset_2_extra, self.asset_2_id, receiver=self.pool_address)

        # Check method selectors
        method = contract.get_method_by_name(METHOD_CLAIM_EXTRA)
        self.assertEqual(method.get_selector(), ABI_METHOD[METHOD_CLAIM_EXTRA])

        fee_collector_signer = AccountTransactionSigner(fee_collector_sk)
        composer = self.get_abi_claim_extra_atomic_composer(fee_collector=fee_collector, signer=fee_collector_signer, app_call_fee=3_000)
        composer.gather_signatures()
        block = self.ledger.eval_transactions(composer.signed_txns)
        block_txns = block[b'txns']

        # outer transactions
        self.assertEqual(len(block_txns), 1)
        txn = block_txns[0]
        self.assertDictEqual(
            txn[b'txn'],
            {
                b'apaa': [
                    ABI_METHOD[METHOD_CLAIM_EXTRA],
                    # Assets
                    (0).to_bytes(1, "big"),
                    (1).to_bytes(1, "big"),
                    # Accounts
                    (1).to_bytes(1, "big"),
                ],
                b'apas': [self.asset_1_id, self.asset_2_id],
                b'apat': [decode_address(self.pool_address)],
                b'apid': APPLICATION_ID,
                b'fee': ANY,
                b'fv': ANY,
                b'lv': ANY,
                b'snd': decode_address(fee_collector),
                b'type': b'appl'
            }
        )

        inner_transactions = txn[b'dt'][b'itx']
        self.assertEqual(len(inner_transactions), 2)

        # inner transactions - [0]
        self.assertDictEqual(
            inner_transactions[0][b'txn'],
            {
                b'aamt': asset_1_extra,
                b'arcv': decode_address(fee_collector),
                b'fv': self.sp.first,
                b'lv': self.sp.last,
                b'snd': decode_address(self.pool_address),
                b'type': b'axfer',
                b'xaid': self.asset_1_id
            },
        )

        # inner transactions - [1]
        self.assertDictEqual(
            inner_transactions[1][b'txn'],
            {
                b'aamt': asset_2_extra,
                b'arcv': decode_address(fee_collector),
                b'fv': self.sp.first,
                b'lv': self.sp.last,
                b'snd': decode_address(self.pool_address),
                b'type': b'axfer',
                b'xaid': self.asset_2_id
            },
        )

    def test_fail_sender_is_not_fee_collector(self):
        asset_1_extra = 0
        asset_2_extra = 0
        self.ledger.move(asset_1_extra, self.asset_1_id, receiver=self.pool_address)
        self.ledger.move(asset_2_extra, self.asset_2_id, receiver=self.pool_address)

        txn_group = self.get_claim_extra_transactions(fee_collector=self.user_addr, app_call_fee=3_000)
        stxns = self.sign_txns(txn_group, self.user_sk)

        with self.assertRaises(LogicEvalError) as e:
            self.ledger.eval_transactions(stxns)
        self.assertEqual(e.exception.source['line'], 'assert(user_address == app_global_get("fee_collector"))')

    def test_pass_only_one_of_the_asset_has_extra(self):
        fee_collector = self.app_creator_address
        fee_collector_sk = self.app_creator_sk
        self.ledger.set_account_balance(fee_collector, 1_000_000)
        self.ledger.opt_in_asset(fee_collector, self.asset_1_id)
        self.ledger.opt_in_asset(fee_collector, self.asset_2_id)

        asset_1_extra = 0
        asset_2_extra = 5_000
        self.ledger.move(asset_1_extra, self.asset_1_id, receiver=self.pool_address)
        self.ledger.move(asset_2_extra, self.asset_2_id, receiver=self.pool_address)

        txn_group = self.get_claim_extra_transactions(fee_collector=fee_collector, app_call_fee=3_000)
        stxns = self.sign_txns(txn_group, fee_collector_sk)

        block = self.ledger.eval_transactions(stxns)
        block_txns = block[b'txns']

        # outer transactions
        self.assertEqual(len(block_txns), 1)

        txn = block_txns[0]
        inner_transactions = txn[b'dt'][b'itx']
        self.assertEqual(len(inner_transactions), 2)

        # inner transactions - [0]
        self.assertDictEqual(
            inner_transactions[0][b'txn'],
            {
                b'arcv': decode_address(fee_collector),
                b'fv': self.sp.first,
                b'lv': self.sp.last,
                b'snd': decode_address(self.pool_address),
                b'type': b'axfer',
                b'xaid': self.asset_1_id
            },
        )

        # inner transactions - [1]
        self.assertDictEqual(
            inner_transactions[1][b'txn'],
            {
                b'aamt': asset_2_extra,
                b'arcv': decode_address(fee_collector),
                b'fv': self.sp.first,
                b'lv': self.sp.last,
                b'snd': decode_address(self.pool_address),
                b'type': b'axfer',
                b'xaid': self.asset_2_id
            },
        )

    def test_fail_there_is_no_extra(self):
        fee_collector = self.app_creator_address
        fee_collector_sk = self.app_creator_sk
        self.ledger.set_account_balance(fee_collector, 1_000_000)
        self.ledger.opt_in_asset(fee_collector, self.asset_1_id)
        self.ledger.opt_in_asset(fee_collector, self.asset_2_id)

        asset_1_extra = 0
        asset_2_extra = 0
        self.ledger.move(asset_1_extra, self.asset_1_id, receiver=self.pool_address)
        self.ledger.move(asset_2_extra, self.asset_2_id, receiver=self.pool_address)

        txn_group = self.get_claim_extra_transactions(fee_collector=fee_collector, app_call_fee=3_000)
        stxns = self.sign_txns(txn_group, fee_collector_sk)

        with self.assertRaises(LogicEvalError) as e:
            self.ledger.eval_transactions(stxns)
        self.assertEqual(e.exception.source['line'], 'assert(asset_1_amount || asset_2_amount)')

    def test_fail_fee_collector_did_not_opt_in(self):
        fee_collector = self.app_creator_address
        fee_collector_sk = self.app_creator_sk
        self.ledger.set_account_balance(fee_collector, 1_000_000)

        asset_1_extra = 5_000
        asset_2_extra = 10_000
        self.ledger.move(asset_1_extra, self.asset_1_id, receiver=self.pool_address)
        self.ledger.move(asset_2_extra, self.asset_2_id, receiver=self.pool_address)

        txn_group = self.get_claim_extra_transactions(fee_collector=fee_collector, app_call_fee=3_000)
        stxns = self.sign_txns(txn_group, fee_collector_sk)

        with self.assertRaises(LogicEvalError) as e:
            self.ledger.eval_transactions(stxns)
        self.assertEqual(e.exception.source['line'], 'inner_txn:')


class TestClaimExtraAlgoPair(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        cls.sp = get_suggested_params()
        cls.app_creator_sk, cls.app_creator_address = generate_account()
        cls.user_sk, cls.user_addr = generate_account()
        cls.asset_1_id = 5
        cls.asset_2_id = ALGO_ASSET_ID

    def setUp(self):
        self.ledger = JigLedger()
        self.create_amm_app()
        self.ledger.set_account_balance(self.user_addr, 100_000_000)
        self.ledger.set_account_balance(self.user_addr, MAX_ASSET_AMOUNT, asset_id=self.asset_1_id)

        lsig = get_pool_logicsig_bytecode(amm_pool_template, APPLICATION_ID, self.asset_1_id, self.asset_2_id)
        self.pool_address = lsig.address()
        self.bootstrap_pool()
        self.ledger.opt_in_asset(self.user_addr, self.pool_token_asset_id)
        self.set_initial_pool_liquidity(asset_1_reserves=1_000_000, asset_2_reserves=1_000_000, liquidity_provider_address=self.user_addr)

    def test_pass(self):
        fee_collector = self.app_creator_address
        fee_collector_sk = self.app_creator_sk
        self.ledger.set_account_balance(fee_collector, 1_000_000)
        self.ledger.opt_in_asset(fee_collector, self.asset_1_id)

        asset_1_extra = 5_000
        asset_2_extra = 10_000
        self.ledger.move(asset_1_extra, self.asset_1_id, receiver=self.pool_address)
        self.ledger.move(asset_2_extra, self.asset_2_id, receiver=self.pool_address)

        txn_group = self.get_claim_extra_transactions(fee_collector=fee_collector, app_call_fee=3_000)
        stxns = self.sign_txns(txn_group, fee_collector_sk)

        block = self.ledger.eval_transactions(stxns)
        block_txns = block[b'txns']

        # outer transactions
        self.assertEqual(len(block_txns), 1)
        txn = block_txns[0]
        self.assertDictEqual(
            txn[b'txn'],
            {
                b'apaa': [b'claim_extra'],
                b'apas': [self.asset_1_id],
                b'apat': [decode_address(self.pool_address)],
                b'apid': APPLICATION_ID,
                b'fee': ANY,
                b'fv': ANY,
                b'lv': ANY,
                b'snd': decode_address(fee_collector),
                b'type': b'appl'
            }
        )

        inner_transactions = txn[b'dt'][b'itx']
        self.assertEqual(len(inner_transactions), 2)

        # inner transactions - [0]
        self.assertDictEqual(
            inner_transactions[0][b'txn'],
            {
                b'aamt': asset_1_extra,
                b'arcv': decode_address(fee_collector),
                b'fv': self.sp.first,
                b'lv': self.sp.last,
                b'snd': decode_address(self.pool_address),
                b'type': b'axfer',
                b'xaid': self.asset_1_id
            },
        )

        # inner transactions - [1]
        self.assertDictEqual(
            inner_transactions[1][b'txn'],
            {
                b'amt': asset_2_extra,
                b'rcv': decode_address(fee_collector),
                b'fv': self.sp.first,
                b'lv': self.sp.last,
                b'snd': decode_address(self.pool_address),
                b'type': b'pay',
            },
        )

    def test_pass_there_is_no_algo_extra(self):
        fee_collector = self.app_creator_address
        fee_collector_sk = self.app_creator_sk
        self.ledger.set_account_balance(fee_collector, 1_000_000)
        self.ledger.opt_in_asset(fee_collector, self.asset_1_id)

        asset_1_extra = 5_000
        asset_2_extra = 0
        self.ledger.move(asset_1_extra, self.asset_1_id, receiver=self.pool_address)
        self.ledger.move(asset_2_extra, self.asset_2_id, receiver=self.pool_address)

        txn_group = self.get_claim_extra_transactions(fee_collector=fee_collector, app_call_fee=3_000)
        stxns = self.sign_txns(txn_group, fee_collector_sk)

        block = self.ledger.eval_transactions(stxns)
        block_txns = block[b'txns']

        # outer transactions
        self.assertEqual(len(block_txns), 1)
        txn = block_txns[0]
        self.assertDictEqual(
            txn[b'txn'],
            {
                b'apaa': [b'claim_extra'],
                b'apas': [self.asset_1_id],
                b'apat': [decode_address(self.pool_address)],
                b'apid': APPLICATION_ID,
                b'fee': ANY,
                b'fv': ANY,
                b'lv': ANY,
                b'snd': decode_address(fee_collector),
                b'type': b'appl'
            }
        )

        inner_transactions = txn[b'dt'][b'itx']
        self.assertEqual(len(inner_transactions), 2)

        # inner transactions - [0]
        self.assertDictEqual(
            inner_transactions[0][b'txn'],
            {
                b'aamt': asset_1_extra,
                b'arcv': decode_address(fee_collector),
                b'fv': self.sp.first,
                b'lv': self.sp.last,
                b'snd': decode_address(self.pool_address),
                b'type': b'axfer',
                b'xaid': self.asset_1_id
            },
        )

        # inner transactions - [1]
        self.assertDictEqual(
            inner_transactions[1][b'txn'],
            {
                b'rcv': decode_address(fee_collector),
                b'fv': self.sp.first,
                b'lv': self.sp.last,
                b'snd': decode_address(self.pool_address),
                b'type': b'pay',
            },
        )
