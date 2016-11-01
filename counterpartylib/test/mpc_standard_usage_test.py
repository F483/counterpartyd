import os
import tempfile
import pytest

# this is require near the top to do setup of the test suite
# from counterpartylib.test import conftest

from counterpartylib.test import util_test
from counterpartylib.test.util_test import CURR_DIR
from counterpartylib.test.fixtures.params import DP
from counterpartylib.lib import util
from micropayment_core.util import b2h
from micropayment_core.keys import address_from_wif
from micropayment_core.keys import pubkey_from_wif
from micropayment_core.util import script_address
from micropayment_core.util import hash160hex
from micropayment_core import scripts


FIXTURE_SQL_FILE = CURR_DIR + '/fixtures/scenarios/unittest_fixture.sql'
FIXTURE_DB = tempfile.gettempdir() + '/fixtures.unittest_fixture.db'


# actors
ALICE_WIF = DP["addresses"][0][2]  # payer
ALICE_ADDRESS = address_from_wif(ALICE_WIF)
ALICE_PUBKEY = pubkey_from_wif(ALICE_WIF)
BOB_WIF = DP["addresses"][1][2]  # payee
BOB_ADDRESS = address_from_wif(BOB_WIF)
BOB_PUBKEY = pubkey_from_wif(BOB_WIF)


# secrets
SPEND_SECRET = b2h(os.urandom(32))
SPEND_SECRET_HASH = hash160hex(SPEND_SECRET)


# deposit
ASSET = "XCP"
NETCODE = "XTN"
DEPOSIT_EXPIRE_TIME = 42
DEPOSIT_SCRIPT = scripts.compile_deposit_script(
    ALICE_PUBKEY, BOB_PUBKEY, SPEND_SECRET_HASH, DEPOSIT_EXPIRE_TIME
)
DEPOSIT_ADDRESS = script_address(DEPOSIT_SCRIPT, NETCODE)
DELAY_TIME = 2


def get_tx(txid):
    return util.api(method="getrawtransaction", params={"tx_hash": txid})


def assert_transferred(payer, payee, quantity):
    assert util.api("mpc_transferred_amount", {"state": payer}) == quantity
    assert util.api("mpc_transferred_amount", {"state": payee}) == quantity


@pytest.mark.usefixtures("server_db")
@pytest.mark.usefixtures("api_server")
def test_usage_xcp(server_db):

    # check initial balances
    alice_balance = util.get_balance(server_db, ALICE_ADDRESS, ASSET)
    deposit_balance = util.get_balance(server_db, DEPOSIT_ADDRESS, ASSET)
    bob_balance = util.get_balance(server_db, BOB_ADDRESS, ASSET)
    assert alice_balance == 91950000000
    assert deposit_balance == 0
    assert bob_balance == 99999990

    # ===== PAYER CREATES DEPOSIT TX =====

    deposit_quantity = 41
    result = util.api(
        method="mpc_make_deposit",
        params={
            "asset": "XCP",
            "payer_pubkey": ALICE_PUBKEY,
            "payee_pubkey": BOB_PUBKEY,
            "spend_secret_hash": SPEND_SECRET_HASH,
            "expire_time": DEPOSIT_EXPIRE_TIME,  # in blocks
            "quantity": deposit_quantity  # in satoshis
        }
    )
    alice_state = result["state"]
    deposit_rawtx = result["topublish"]
    deposit_rawtx = scripts.sign_deposit(get_tx, ALICE_WIF, result["topublish"])

    # ===== PAYEE SETS DEPOSIT =====

    bob_state = util.api("mpc_set_deposit", {
        "asset": "XCP",
        "deposit_script": DEPOSIT_SCRIPT,
        "expected_payee_pubkey": BOB_PUBKEY,
        "expected_spend_secret_hash": SPEND_SECRET_HASH
    })

    assert util.api("mpc_highest_commit", {"state": bob_state}) is None
    assert util.api("mpc_deposit_ttl", {"state": bob_state}) is None

    # ===== PAYER PUBLISHES DEPOSIT TX =====

    before_deposit_transactions = util.api(
        method="search_raw_transactions",
        params={"address": DEPOSIT_ADDRESS, "unconfirmed": False}
    )
    assert len(before_deposit_transactions) == 0

    # insert send, this automatically also creates a block
    util_test.insert_raw_transaction(deposit_rawtx, server_db)

    # check balances after send to deposit
    alice_balance = util.get_balance(server_db, ALICE_ADDRESS, ASSET)
    deposit_balance = util.get_balance(server_db, DEPOSIT_ADDRESS, ASSET)
    bob_balance = util.get_balance(server_db, BOB_ADDRESS, ASSET)
    assert alice_balance == 91950000000 - deposit_quantity
    assert deposit_balance == deposit_quantity
    assert bob_balance == 99999990
    assert util.api("mpc_deposit_ttl", {"state": bob_state}) == 41

    after_deposit_transactions = util.api(
        method="search_raw_transactions",
        params={"address": DEPOSIT_ADDRESS, "unconfirmed": False}
    )
    assert len(after_deposit_transactions) == 1

    # ===== TRANSFER MICRO PAYMENTS =====

    assert_transferred(alice_state, bob_state, 0)

    revoke_secrets = {}
    for transfer_quantity in [1, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41]:

        # ===== PAYEE REQUESTS COMMIT =====

        revoke_secret = b2h(os.urandom(32))
        revoke_secret_hash = hash160hex(revoke_secret)
        revoke_secrets[revoke_secret_hash] = revoke_secret
        bob_state = util.api("mpc_request_commit", {
            "state": bob_state,
            "quantity": transfer_quantity,
            "revoke_secret_hash": revoke_secret_hash
        })

        # ===== PAYER CREATES COMMIT =====

        result = util.api("mpc_create_commit", {
            "state": alice_state,
            "quantity": transfer_quantity,
            "revoke_secret_hash": revoke_secret_hash,
            "delay_time": DELAY_TIME
        })
        alice_state = result["state"]
        commit_script = result["commit_script"]
        commit_rawtx = result["tosign"]["commit_rawtx"]
        deposit_script = result["tosign"]["deposit_script"]
        signed_commit_rawtx = scripts.sign_created_commit(
            get_tx, ALICE_WIF, commit_rawtx, deposit_script
        )

        # ===== PAYEE UPDATES STATE =====

        bob_state = util.api("mpc_add_commit", {
            "state": bob_state,
            "commit_rawtx": signed_commit_rawtx,
            "commit_script": commit_script,
        })
        assert_transferred(alice_state, bob_state, transfer_quantity)

    # ===== PAYEE RETURNS FUNDS =====

    # get secrets to revoke
    revoke_hashes = util.api("mpc_revoke_hashes_until", {
        "state": bob_state, "quantity": 15, "surpass": False,
    })
    secrets = [v for k, v in revoke_secrets.items() if k in revoke_hashes]
    assert len(secrets) == 6

    # payee revokes commits
    bob_state = util.api("mpc_revoke_all", {
        "state": bob_state, "secrets": secrets,
    })

    # payer revokes commits
    alice_state = util.api("mpc_revoke_all", {
        "state": alice_state, "secrets": secrets,
    })
    assert_transferred(alice_state, bob_state, 17)

    # ===== PAYEE CLOSES CHANNEL =====

    highest_commit = util.api("mpc_highest_commit", {"state": bob_state})
    signed_commit_rawtx = scripts.sign_finalize_commit(
        get_tx, BOB_WIF, highest_commit["rawtx"], bob_state["deposit_script"]
    )
    util_test.insert_raw_transaction(signed_commit_rawtx, server_db)

    commits = util.api("mpc_get_published_commits", {"state": alice_state})
    assert commits == [signed_commit_rawtx]

    # check balances after publishing commit
    commit_address = script_address(highest_commit["script"], netcode=NETCODE)
    alice_balance = util.get_balance(server_db, ALICE_ADDRESS, ASSET)
    commit_balance = util.get_balance(server_db, commit_address, ASSET)
    bob_balance = util.get_balance(server_db, BOB_ADDRESS, ASSET)
    assert alice_balance == 91950000000 - deposit_quantity
    assert commit_balance == 17
    assert bob_balance == 99999990

    # ===== PAYEE RECOVERS PAYOUT =====

    # let delay time pass
    for i in range(DELAY_TIME - 1):
        util_test.create_next_block(server_db)

    # get and sign payout
    payouts = util.api("mpc_payouts", {"state": bob_state})
    assert len(payouts) == 1
    payout = payouts[0]
    commit_script = payout["commit_script"]
    signed_payout_rawtx = scripts.sign_payout_recover(
        get_tx, BOB_WIF, payout["payout_rawtx"],
        commit_script, SPEND_SECRET
    )

    commit_transactions = util.api(
        method="search_raw_transactions",
        params={"address": commit_address, "unconfirmed": False}
    )
    assert len(commit_transactions) == 1

    # publish payout transaction
    util_test.insert_raw_transaction(signed_payout_rawtx, server_db)

    # check payee balance
    bob_balance = util.get_balance(server_db, BOB_ADDRESS, ASSET)
    assert bob_balance == 99999990 + 17

    commit_transactions = util.api(
        method="search_raw_transactions",
        params={"address": commit_address, "unconfirmed": False}
    )
    assert len(commit_transactions) == 2  # FIXME why is payout spend not found?

    # ===== PAYER RECOVERS CHANGE =====

    # FIXME why is change note recovered?

    # # get change recoverable
    # recoverables = util.api("mpc_recoverables", {"state": alice_state})
    # assert len(recoverables["change"]) == 1
    # change = recoverables["change"]

    # # publish change recoverable
    # signed_change_rawtx = scripts.sign_change_recover(
    #     get_tx, ALICE_WIF, change["change_rawtx"],
    #     change["deposit_script"], change["spend_secret"]
    # )
    # util_test.insert_raw_transaction(signed_change_rawtx, server_db)

    # alice_balance = util.get_balance(server_db, ALICE_ADDRESS, ASSET)
    # assert alice_balance == 91950000000 - 17


@pytest.mark.usefixtures("server_db")
@pytest.mark.usefixtures("api_server")
def test_usage_btc(server_db):
    pass  # FIXME test
