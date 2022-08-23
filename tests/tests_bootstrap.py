from algojig import get_suggested_params
from algojig.exceptions import LogicEvalError
from algojig.ledger import JigLedger
from algosdk.account import generate_account
from algosdk.atomic_transaction_composer import AtomicTransactionComposer, LogicSigTransactionSigner
from algosdk.encoding import decode_address
from algosdk.future import transaction
from algosdk.future.transaction import OnComplete

from .constants import *
from .core import BaseTestCase
from .utils import get_pool_logicsig_bytecode


class TestBootstrap(BaseTestCase):

    @classmethod
    def setUpClass(cls):
        cls.sp = get_suggested_params()
        cls.app_creator_sk, cls.app_creator_address = generate_account()
        cls.user_sk, cls.user_addr = generate_account()

        cls.minimum_fee = 7000
        cls.sp.fee = cls.minimum_fee
        cls.asset_1_id = 5
        cls.asset_2_id = 2
        cls.pool_token_total_supply = 18446744073709551615

    def setUp(self):
        self.ledger = JigLedger()
        self.create_amm_app()
        self.ledger.set_account_balance(self.user_addr, 1_000_000)
        self.asset_2_id = self.ledger.create_asset(asset_id=None, params=dict(unit_name="BTC"))
        self.asset_1_id = self.ledger.create_asset(asset_id=None, params=dict(unit_name="USD"))
        self.ledger.set_account_balance(self.user_addr, 0, asset_id=self.asset_1_id)
        self.ledger.set_account_balance(self.user_addr, 0, asset_id=self.asset_2_id)

    def test_pass(self):
        lsig_account = get_pool_logicsig_bytecode(amm_pool_template, APPLICATION_ID, self.asset_1_id, self.asset_2_id)
        pool_address = lsig_account.address()
        self.ledger.set_account_balance(pool_address, 2_000_000)
        transactions = [
            transaction.LogicSigTransaction(
                transaction.ApplicationOptInTxn(
                    sender=pool_address,
                    sp=self.sp,
                    index=APPLICATION_ID,
                    app_args=[METHOD_BOOTSTRAP, self.asset_1_id, self.asset_2_id],
                    foreign_assets=[self.asset_1_id, self.asset_2_id],
                    rekey_to=APPLICATION_ADDRESS,
                ),
                lsig_account
            )
        ]

        block = self.ledger.eval_transactions(transactions)
        block_txns = block[b'txns']

        # outer transactions
        self.assertEqual(len(block_txns), 1)
        txn = block_txns[0]
        self.assertEqual(
            txn[b'txn'],
            {
                b'apaa': [b'bootstrap', self.asset_1_id.to_bytes(8, "big"), self.asset_2_id.to_bytes(8, "big")],
                b'apan': transaction.OnComplete.OptInOC,
                b'apas': [self.asset_1_id, self.asset_2_id],
                b'apid': APPLICATION_ID,
                b'fee': self.minimum_fee,
                b'fv': self.sp.first,
                b'lv': self.sp.last,
                b'rekey': decode_address(APPLICATION_ADDRESS),
                b'snd': decode_address(pool_address),
                b'type': b'appl'
            }
        )

        # inner transactions
        inner_transactions = txn[b'dt'][b'itx']
        self.assertEqual(len(inner_transactions), 6)

        # inner transactions - [0]
        self.assertDictEqual(
            inner_transactions[0][b'txn'],
            {
                b'amt': 200000,
                b'fv': self.sp.first,
                b'lv': self.sp.last,
                b'rcv': decode_address(APPLICATION_ADDRESS),
                b'snd': decode_address(pool_address),
                b'type': b'pay'
            }
        )

        # inner transactions - [1]
        created_asset_id = inner_transactions[1][b'caid']

        self.assertDictEqual(
            inner_transactions[1][b'txn'],
            {
                b'apar': {
                    b'an': b'TinymanPool2.0 USD-BTC',
                    b'au': b'https://tinyman.org',
                    b'dc': 6,
                    b't': self.pool_token_total_supply,
                    b'un': b'TMPOOL2'
                },
                b'fv': self.sp.first,
                b'lv': self.sp.last,
                b'snd': decode_address(APPLICATION_ADDRESS),
                b'type': b'acfg'
            }
        )

        # inner transactions - [2]
        self.assertDictEqual(
            inner_transactions[2][b'txn'],
            {
                b'arcv': decode_address(pool_address),
                b'fv': self.sp.first,
                b'lv': self.sp.last,
                b'snd': decode_address(pool_address),
                b'type': b'axfer',
                b'xaid': self.asset_1_id
            }
        )

        # inner transactions - [3]
        self.assertDictEqual(
            inner_transactions[3][b'txn'],
            {
                b'arcv': decode_address(pool_address),
                b'fv': self.sp.first,
                b'lv': self.sp.last,
                b'snd': decode_address(pool_address),
                b'type': b'axfer',
                b'xaid': self.asset_2_id
            }
        )

        # inner transactions - [4]
        self.assertDictEqual(
            inner_transactions[4][b'txn'],
            {
                b'arcv': decode_address(pool_address),
                b'fv': self.sp.first,
                b'lv': self.sp.last,
                b'snd': decode_address(pool_address),
                b'type': b'axfer',
                b'xaid': created_asset_id
            }
        )

        # inner transactions - [5]
        self.assertDictEqual(
            inner_transactions[5][b'txn'],
            {
                b'aamt': 18446744073709551615,
                b'arcv': decode_address(pool_address),
                b'fv': self.sp.first,
                b'lv': self.sp.last,
                b'snd': decode_address(APPLICATION_ADDRESS),
                b'type': b'axfer',
                b'xaid': created_asset_id
            }
        )

        # local state delta
        pool_delta = txn[b'dt'][b'ld'][0]
        self.assertDictEqual(
            pool_delta,
            {
                b'asset_1_id': {b'at': 2, b'ui': self.asset_1_id},
                b'asset_1_reserves': {b'at': 2},
                b'asset_2_id': {b'at': 2, b'ui': self.asset_2_id},
                b'asset_2_reserves': {b'at': 2},
                b'cumulative_asset_1_price': {b'at': 1, b'bs': BYTE_ZERO},
                b'cumulative_asset_2_price': {b'at': 1, b'bs': BYTE_ZERO},
                b'cumulative_price_update_timestamp': {b'at': 2, b'ui': BLOCK_TIME_DELTA},
                b'issued_pool_tokens': {b'at': 2},
                b'pool_token_asset_id': {b'at': 2, b'ui': created_asset_id},
                b'poolers_fee_share': {b'at': 2, b'ui': POOLERS_FEE_SHARE},
                b'protocol_fee_share': {b'at': 2, b'ui': PROTOCOL_FEE_SHARE},
                b'protocol_fees_asset_1': {b'at': 2},
                b'protocol_fees_asset_2': {b'at': 2}
            }
        )

    def test_abi_bootstrap(self):
        lsig_account = get_pool_logicsig_bytecode(amm_pool_template, APPLICATION_ID, self.asset_1_id, self.asset_2_id)
        pool_address = lsig_account.address()
        lsig_signer = LogicSigTransactionSigner(lsig_account)
        self.ledger.set_account_balance(pool_address, 2_000_000)

        method = contract.get_method_by_name(METHOD_BOOTSTRAP)
        self.assertEqual(method.get_selector(), ABI_METHOD[METHOD_BOOTSTRAP])

        composer = AtomicTransactionComposer()
        composer.add_method_call(
            app_id=APPLICATION_ID,
            method=method,
            sender=pool_address,
            sp=self.sp,
            signer=lsig_signer,
            method_args=[self.asset_1_id, self.asset_2_id, self.asset_1_id, self.asset_2_id],
            on_complete=OnComplete.OptInOC,
            rekey_to=APPLICATION_ADDRESS
        )

        composer.gather_signatures()
        block = self.ledger.eval_transactions(composer.signed_txns)
        block_txns = block[b'txns']
        # outer transactions
        self.assertEqual(len(block_txns), 1)

    def test_fail_rekey(self):
        lsig_account = get_pool_logicsig_bytecode(amm_pool_template, APPLICATION_ID, self.asset_1_id, self.asset_2_id)
        pool_address = lsig_account.address()
        self.ledger.set_account_balance(pool_address, 2_000_000)

        # TODO: Isn't this transaction rejected by the pool logic sig?
        # Rekey is missing
        transactions = [
            transaction.LogicSigTransaction(
                transaction.ApplicationOptInTxn(
                    sender=lsig_account.address(),
                    sp=self.sp,
                    index=APPLICATION_ID,
                    app_args=[METHOD_BOOTSTRAP, self.asset_1_id, self.asset_2_id],
                    foreign_assets=[self.asset_1_id, self.asset_2_id],
                ),
                lsig_account
            )
        ]

        with self.assertRaises(LogicEvalError) as e:
            self.ledger.eval_transactions(transactions)
        self.assertEqual(e.exception.source['line'], 'assert(Txn.RekeyTo == Global.CurrentApplicationAddress)')

        # Rekey address is wrong
        transactions = [
            transaction.LogicSigTransaction(
                transaction.ApplicationOptInTxn(
                    sender=lsig_account.address(),
                    sp=self.sp,
                    index=APPLICATION_ID,
                    app_args=[METHOD_BOOTSTRAP, self.asset_1_id, self.asset_2_id],
                    foreign_assets=[self.asset_1_id, self.asset_2_id],
                    rekey_to=generate_account()[1],
                ),
                lsig_account
            )
        ]

        with self.assertRaises(LogicEvalError) as e:
            self.ledger.eval_transactions(transactions)
        self.assertEqual(e.exception.source['line'], 'assert(Txn.RekeyTo == Global.CurrentApplicationAddress)')

    def test_fail_wrong_ids_for_logicsig(self):
        wrong_asset_1_id = self.asset_1_id + 1
        lsig_account = get_pool_logicsig_bytecode(amm_pool_template, APPLICATION_ID, wrong_asset_1_id, self.asset_2_id)
        pool_address = lsig_account.address()
        self.ledger.set_account_balance(pool_address, 2_000_000)
        transactions = [
            transaction.LogicSigTransaction(
                transaction.ApplicationOptInTxn(
                    sender=lsig_account.address(),
                    sp=self.sp,
                    index=APPLICATION_ID,
                    app_args=[METHOD_BOOTSTRAP, self.asset_1_id, self.asset_2_id],
                    foreign_assets=[self.asset_1_id, self.asset_2_id],
                    rekey_to=APPLICATION_ADDRESS,
                ),
                lsig_account
            )
        ]

        with self.assertRaises(LogicEvalError) as e:
            self.ledger.eval_transactions(transactions)
        self.assertEqual(e.exception.source['line'], 'assert(hash == pool_address)')

    def test_fail_wrong_asset_order(self):
        lsig_account = get_pool_logicsig_bytecode(amm_pool_template, APPLICATION_ID, self.asset_2_id, self.asset_1_id)
        pool_address = lsig_account.address()
        self.ledger.set_account_balance(pool_address, 2_000_000)
        transactions = [
            transaction.LogicSigTransaction(
                transaction.ApplicationOptInTxn(
                    sender=lsig_account.address(),
                    sp=self.sp,
                    index=APPLICATION_ID,
                    app_args=[METHOD_BOOTSTRAP, self.asset_2_id, self.asset_1_id],
                    foreign_assets=[self.asset_2_id, self.asset_1_id],
                    rekey_to=APPLICATION_ADDRESS,
                ),
                lsig_account
            )
        ]

        with self.assertRaises(LogicEvalError) as e:
            self.ledger.eval_transactions(transactions)
        self.assertEqual(e.exception.source['line'], 'assert(asset_1_id > asset_2_id)')

    def test_fail_different_assets_are_included_in_application_args_and_foreign_assets(self):
        lsig_account = get_pool_logicsig_bytecode(amm_pool_template, APPLICATION_ID, self.asset_1_id, self.asset_2_id)
        pool_address = lsig_account.address()
        self.ledger.set_account_balance(pool_address, 2_000_000)
        transactions = [
            transaction.LogicSigTransaction(
                transaction.ApplicationOptInTxn(
                    sender=lsig_account.address(),
                    sp=self.sp,
                    index=APPLICATION_ID,
                    app_args=[METHOD_BOOTSTRAP, self.asset_1_id, self.asset_2_id],
                    foreign_assets=[self.asset_1_id + 9999, self.asset_2_id],
                    rekey_to=APPLICATION_ADDRESS,
                ),
                lsig_account
            )
        ]
        with self.assertRaises(LogicEvalError) as e:
            self.ledger.eval_transactions(transactions)
        self.assertEqual(e.exception.source['line'], 'assert(asset_1_id == Txn.Assets[0])')

        transactions = [
            transaction.LogicSigTransaction(
                transaction.ApplicationOptInTxn(
                    sender=lsig_account.address(),
                    sp=self.sp,
                    index=APPLICATION_ID,
                    app_args=[METHOD_BOOTSTRAP, self.asset_1_id, self.asset_2_id],
                    foreign_assets=[self.asset_1_id, self.asset_2_id + 9999],
                    rekey_to=APPLICATION_ADDRESS,
                ),
                lsig_account
            )
        ]
        with self.assertRaises(LogicEvalError) as e:
            self.ledger.eval_transactions(transactions)
        self.assertEqual(e.exception.source['line'], 'assert(asset_2_id == Txn.Assets[1])')

    def test_fail_insufficient_fee(self):
        lsig_account = get_pool_logicsig_bytecode(amm_pool_template, APPLICATION_ID, self.asset_1_id, self.asset_2_id)
        pool_address = lsig_account.address()
        self.ledger.set_account_balance(pool_address, 2_000_000)
        transactions = [
            transaction.LogicSigTransaction(
                transaction.ApplicationOptInTxn(
                    sender=lsig_account.address(),
                    sp=self.sp,
                    index=APPLICATION_ID,
                    app_args=[METHOD_BOOTSTRAP, self.asset_1_id, self.asset_2_id],
                    foreign_assets=[self.asset_1_id, self.asset_2_id],
                    rekey_to=APPLICATION_ADDRESS,
                ),
                lsig_account
            )
        ]
        transactions[0].transaction.fee = self.minimum_fee - 1

        with self.assertRaises(LogicEvalError) as e:
            self.ledger.eval_transactions(transactions)
        self.assertEqual(e.exception.source['line'], 'inner_txn:')

    def test_fail_wrong_method_name(self):
        lsig_account = get_pool_logicsig_bytecode(amm_pool_template, APPLICATION_ID, self.asset_1_id, self.asset_2_id)
        pool_address = lsig_account.address()
        self.ledger.set_account_balance(pool_address, 2_000_000)
        transactions = [
            transaction.LogicSigTransaction(
                transaction.ApplicationOptInTxn(
                    sender=lsig_account.address(),
                    sp=self.sp,
                    index=APPLICATION_ID,
                    app_args=["invalid", self.asset_1_id, self.asset_2_id],
                    foreign_assets=[self.asset_1_id, self.asset_2_id],
                    rekey_to=APPLICATION_ADDRESS,
                ),
                lsig_account
            )
        ]

        with self.assertRaises(LogicEvalError) as e:
            self.ledger.eval_transactions(transactions)
        self.assertTrue(f'assert((Txn.ApplicationArgs[0] == "{METHOD_BOOTSTRAP}") || (Txn.ApplicationArgs[0] ==' in e.exception.source['line'])

    def test_fail_bad_asset_1_total(self):
        self.asset_2_id = self.ledger.create_asset(asset_id=None, params=dict(unit_name="NFT", total=100))
        self.asset_1_id = self.ledger.create_asset(asset_id=None, params=dict(unit_name="BTC"))
        lsig_account = get_pool_logicsig_bytecode(amm_pool_template, APPLICATION_ID, self.asset_1_id, self.asset_2_id)
        pool_address = lsig_account.address()
        self.ledger.set_account_balance(pool_address, 2_000_000)
        transactions = [
            transaction.LogicSigTransaction(
                transaction.ApplicationOptInTxn(
                    sender=lsig_account.address(),
                    sp=self.sp,
                    index=APPLICATION_ID,
                    app_args=[METHOD_BOOTSTRAP, self.asset_1_id, self.asset_2_id],
                    foreign_assets=[self.asset_1_id, self.asset_2_id],
                    rekey_to=APPLICATION_ADDRESS,
                ),
                lsig_account
            )
        ]
        transactions[0].transaction.fee = self.minimum_fee - 1

        with self.assertRaises(LogicEvalError) as e:
            self.ledger.eval_transactions(transactions)
        self.assertEqual(e.exception.source['line'], 'assert(exists && (asset_total >= ASSET_MIN_TOTAL))')

    def test_fail_bad_asset_2_total(self):
        self.asset_2_id = self.ledger.create_asset(asset_id=None, params=dict(unit_name="USDC"))
        self.asset_1_id = self.ledger.create_asset(asset_id=None, params=dict(unit_name="NFT", total=1))
        lsig_account = get_pool_logicsig_bytecode(amm_pool_template, APPLICATION_ID, self.asset_1_id, self.asset_2_id)
        pool_address = lsig_account.address()
        self.ledger.set_account_balance(pool_address, 2_000_000)
        transactions = [
            transaction.LogicSigTransaction(
                transaction.ApplicationOptInTxn(
                    sender=lsig_account.address(),
                    sp=self.sp,
                    index=APPLICATION_ID,
                    app_args=[METHOD_BOOTSTRAP, self.asset_1_id, self.asset_2_id],
                    foreign_assets=[self.asset_1_id, self.asset_2_id],
                    rekey_to=APPLICATION_ADDRESS,
                ),
                lsig_account
            )
        ]
        transactions[0].transaction.fee = self.minimum_fee - 1

        with self.assertRaises(LogicEvalError) as e:
            self.ledger.eval_transactions(transactions)
        self.assertEqual(e.exception.source['line'], 'assert(exists && (asset_total >= ASSET_MIN_TOTAL))')


class TestBootstralgoPair(BaseTestCase):

    @classmethod
    def setUpClass(cls):
        cls.sp = get_suggested_params()
        cls.app_creator_sk, cls.app_creator_address = generate_account()
        cls.user_sk, cls.user_addr = generate_account()
        cls.minimum_fee = 6000
        cls.sp.fee = cls.minimum_fee
        cls.asset_1_id = 5
        cls.pool_token_total_supply = 18446744073709551615

    def setUp(self):
        self.ledger = JigLedger()
        self.create_amm_app()
        self.ledger.set_account_balance(self.user_addr, 1_000_000)
        self.ledger.create_asset(self.asset_1_id, params=dict(unit_name="USD"))
        self.ledger.set_account_balance(self.user_addr, 0, asset_id=self.asset_1_id)

    def test_pass(self):
        lsig_account = get_pool_logicsig_bytecode(amm_pool_template, APPLICATION_ID, self.asset_1_id, ALGO_ASSET_ID)
        pool_address = lsig_account.address()
        self.ledger.set_account_balance(pool_address, 2_000_000)
        transactions = [
            transaction.LogicSigTransaction(
                transaction.ApplicationOptInTxn(
                    sender=lsig_account.address(),
                    sp=self.sp,
                    index=APPLICATION_ID,
                    app_args=[METHOD_BOOTSTRAP, self.asset_1_id, ALGO_ASSET_ID],
                    foreign_assets=[self.asset_1_id, ALGO_ASSET_ID],
                    rekey_to=APPLICATION_ADDRESS,
                ),
                lsig_account
            )
        ]

        block = self.ledger.eval_transactions(transactions)
        block_txns = block[b'txns']

        # outer transactions
        self.assertEqual(len(block_txns), 1)
        txn = block_txns[0]
        self.assertEqual(
            txn[b'txn'],
            {
                b'apaa': [b'bootstrap', self.asset_1_id.to_bytes(8, "big"), ALGO_ASSET_ID.to_bytes(8, "big")],
                b'apan': transaction.OnComplete.OptInOC,
                b'apas': [self.asset_1_id, ALGO_ASSET_ID],
                b'apid': APPLICATION_ID,
                b'fee': self.minimum_fee,
                b'fv': self.sp.first,
                b'lv': self.sp.last,
                b'rekey': decode_address(APPLICATION_ADDRESS),
                b'snd': decode_address(pool_address),
                b'type': b'appl'
            }
        )

        # inner transactions
        inner_transactions = txn[b'dt'][b'itx']
        self.assertEqual(len(inner_transactions), 5)

        # inner transactions - [0]
        self.assertDictEqual(
            inner_transactions[0][b'txn'],
            {
                b'amt': 200000,
                b'fv': self.sp.first,
                b'lv': self.sp.last,
                b'rcv': decode_address(APPLICATION_ADDRESS),
                b'snd': decode_address(pool_address),
                b'type': b'pay'
            }
        )

        # inner transactions - [1]
        created_asset_id = inner_transactions[1][b'caid']
        self.assertDictEqual(
            inner_transactions[1][b'txn'],
            {
                b'apar': {
                    b'an': b'TinymanPool2.0 USD-ALGO',
                    b'au': b'https://tinyman.org',
                    b'dc': 6,
                    b't': self.pool_token_total_supply,
                    b'un': b'TMPOOL2'
                },
                b'fv': self.sp.first,
                b'lv': self.sp.last,
                b'snd': decode_address(APPLICATION_ADDRESS),
                b'type': b'acfg'
            }
        )

        # inner transactions - [2]
        self.assertDictEqual(
            inner_transactions[2][b'txn'],
            {
                b'arcv': decode_address(pool_address),
                b'fv': self.sp.first,
                b'lv': self.sp.last,
                b'snd': decode_address(pool_address),
                b'type': b'axfer',
                b'xaid': self.asset_1_id
            }
        )

        # inner transactions - [3]
        self.assertDictEqual(
            inner_transactions[3][b'txn'],
            {
                b'arcv': decode_address(pool_address),
                b'fv': self.sp.first,
                b'lv': self.sp.last,
                b'snd': decode_address(pool_address),
                b'type': b'axfer',
                b'xaid': created_asset_id
            }
        )

        # inner transactions - [4]
        self.assertDictEqual(
            inner_transactions[4][b'txn'],
            {
                b'aamt': 18446744073709551615,
                b'arcv': decode_address(pool_address),
                b'fv': self.sp.first,
                b'lv': self.sp.last,
                b'snd': decode_address(APPLICATION_ADDRESS),
                b'type': b'axfer',
                b'xaid': created_asset_id
            }
        )

        # local state delta
        pool_delta = txn[b'dt'][b'ld'][0]
        self.assertDictEqual(
            pool_delta,
            {
                b'asset_1_id': {b'at': 2, b'ui': self.asset_1_id},
                b'asset_1_reserves': {b'at': 2},
                b'asset_2_id': {b'at': 2},      # b'ui': ALGO_ASSET_ID
                b'asset_2_reserves': {b'at': 2},
                b'cumulative_asset_1_price': {b'at': 1, b'bs': BYTE_ZERO},
                b'cumulative_asset_2_price': {b'at': 1, b'bs': BYTE_ZERO},
                b'cumulative_price_update_timestamp': {b'at': 2, b'ui': BLOCK_TIME_DELTA},
                b'issued_pool_tokens': {b'at': 2},
                b'pool_token_asset_id': {b'at': 2, b'ui': created_asset_id},
                b'poolers_fee_share': {b'at': 2, b'ui': POOLERS_FEE_SHARE},
                b'protocol_fee_share': {b'at': 2, b'ui': PROTOCOL_FEE_SHARE},
                b'protocol_fees_asset_1': {b'at': 2},
                b'protocol_fees_asset_2': {b'at': 2}
            }
        )

    def test_abi_bootstrap(self):
        lsig_account = get_pool_logicsig_bytecode(amm_pool_template, APPLICATION_ID, self.asset_1_id, ALGO_ASSET_ID)
        pool_address = lsig_account.address()
        self.ledger.set_account_balance(pool_address, 2_000_000)

        method = contract.get_method_by_name("bootstrap")
        self.assertEqual(method.get_selector(), ABI_METHOD[METHOD_BOOTSTRAP])

        lsig_signer = LogicSigTransactionSigner(lsig_account)
        composer = AtomicTransactionComposer()
        composer.add_method_call(
            app_id=APPLICATION_ID,
            method=method,
            sender=pool_address,
            sp=self.sp,
            signer=lsig_signer,
            method_args=[self.asset_1_id, ALGO_ASSET_ID, self.asset_1_id, ALGO_ASSET_ID],
            on_complete=OnComplete.OptInOC,
            rekey_to=APPLICATION_ADDRESS
        )

        composer.gather_signatures()
        block = self.ledger.eval_transactions(composer.signed_txns)
        block_txns = block[b'txns']
        # outer transactions
        self.assertEqual(len(block_txns), 1)
