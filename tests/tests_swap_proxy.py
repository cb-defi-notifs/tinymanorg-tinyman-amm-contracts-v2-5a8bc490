from algojig import get_suggested_params
from algojig.ledger import JigLedger
from algosdk.account import generate_account
from algosdk.encoding import decode_address
from algosdk.future import transaction

from .constants import *
from .core import BaseTestCase
from .utils import get_pool_logicsig_bytecode

proxy_approval_program = TealishProgram(tealish="""
    #pragma version 7

    const int TINYMAN_APP_ID = 1
    const int FEE_BASIS_POINTS = 100

    assert(Gtxn[0].AssetReceiver == Global.CurrentApplicationAddress)
    int swap_amount = (Gtxn[0].AssetAmount * (10000 - FEE_BASIS_POINTS)) / 10000
    int initial_output_balance
    _, initial_output_balance = asset_holding_get(AssetBalance, Global.CurrentApplicationAddress, Txn.Assets[1])
    inner_group:
        inner_txn:
            TypeEnum: Axfer
            Fee: 0
            AssetReceiver: Txn.Accounts[1]
            XferAsset: Gtxn[0].XferAsset
            AssetAmount: swap_amount
        end
        inner_txn:
            TypeEnum: Appl
            Fee: 0
            ApplicationID: TINYMAN_APP_ID
            ApplicationArgs[0]: "swap"
            ApplicationArgs[1]: Txn.ApplicationArgs[1]
            ApplicationArgs[2]: Txn.ApplicationArgs[2]
            ApplicationArgs[3]: Txn.ApplicationArgs[3]
            ApplicationArgs[4]: "fixed-input"
            Accounts[0]: Txn.Accounts[1]
            Assets[0]: Txn.Assets[0]
            Assets[1]: Txn.Assets[1]
        end
    end

    int new_output_balance
    _, new_output_balance = asset_holding_get(AssetBalance, Global.CurrentApplicationAddress, Txn.Assets[1])
    int output_amount = new_output_balance - initial_output_balance
    inner_txn:
        TypeEnum: Axfer
        Fee: 0
        AssetReceiver: Txn.Sender
        XferAsset: Txn.Assets[1]
        AssetAmount: output_amount
    end
    exit(1)
""")
PROXY_APP_ID = 10
PROXY_ADDRESS = get_application_address(PROXY_APP_ID)


class TestProxySwap(BaseTestCase):

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
        self.ledger.set_account_balance(self.user_addr, 1_000_000, asset_id=self.asset_1_id)
        self.ledger.set_account_balance(self.user_addr, 0, asset_id=self.asset_2_id)

        self.ledger.create_app(app_id=PROXY_APP_ID, approval_program=proxy_approval_program, creator=self.app_creator_address)
        self.ledger.set_account_balance(PROXY_ADDRESS, 1_000_000)
        self.ledger.set_account_balance(PROXY_ADDRESS, 0, asset_id=self.asset_1_id)
        self.ledger.set_account_balance(PROXY_ADDRESS, 0, asset_id=self.asset_2_id)

        lsig = get_pool_logicsig_bytecode(amm_pool_template, APPLICATION_ID, self.asset_1_id, self.asset_2_id)
        self.pool_address = lsig.address()
        self.bootstrap_pool()

    def test_pass(self):
        self.ledger.set_account_balance(self.pool_address, 1_000_000, asset_id=self.asset_1_id)
        self.ledger.set_account_balance(self.pool_address, 1_000_000, asset_id=self.asset_2_id)
        self.ledger.update_local_state(
            address=self.pool_address,
            app_id=APPLICATION_ID,
            state_delta={
                b'asset_1_reserves': 1_000_000,
                b'asset_2_reserves': 1_000_000,
                b'issued_pool_tokens': 1_000_000,
            }
        )

        txn_group = [
            transaction.AssetTransferTxn(
                sender=self.user_addr,
                sp=self.sp,
                receiver=PROXY_ADDRESS,
                index=self.asset_1_id,
                amt=10_000,
            ),
            transaction.ApplicationNoOpTxn(
                sender=self.user_addr,
                sp=self.sp,
                index=PROXY_APP_ID,
                app_args=[METHOD_SWAP, self.asset_1_id, self.asset_2_id, 9000],
                foreign_assets=[self.asset_1_id, self.asset_2_id],
                foreign_apps=[APPLICATION_ID],
                accounts=[self.pool_address],
            )
        ]
        txn_group[1].fee = 5000

        txn_group = transaction.assign_group_id(txn_group)
        stxns = [
            txn_group[0].sign(self.user_sk),
            txn_group[1].sign(self.user_sk),
        ]

        block = self.ledger.eval_transactions(stxns)
        txns = block[b'txns']
        itxn = txns[1][b'dt'][b'itx'][-1][b'txn']
        self.assertEqual(itxn[b'aamt'], 9775)
        self.assertEqual(itxn[b'arcv'], decode_address(self.user_addr))
        self.assertEqual(itxn[b'xaid'], self.asset_2_id)
        self.assertEqual(itxn[b'snd'], decode_address(PROXY_ADDRESS))

        self.assertEqual(self.ledger.get_account_balance(PROXY_ADDRESS, self.asset_1_id)[0], 100)

        # do the same swap again and watch the fees accumulate
        self.ledger.eval_transactions(stxns)
        self.assertEqual(self.ledger.get_account_balance(PROXY_ADDRESS, self.asset_1_id)[0], 200)