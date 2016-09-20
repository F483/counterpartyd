import os
import pycoin
from pycoin.serialize import b2h  # NOQA
from pycoin.serialize import h2b  # NOQA
from pycoin.serialize import b2h_rev  # NOQA
from pycoin.encoding import hash160  # NOQA
from pycoin.key.BIP32Node import BIP32Node
from pycoin.key import Key
from pycoin.encoding import sec_to_public_pair, public_pair_to_sec, to_bytes_32
from counterpartylib.lib import config


def gettxid(rawtx):
    tx = pycoin.tx.Tx.from_hex(rawtx)
    return b2h_rev(tx.hash())


def random_wif(netcode="BTC"):
    return BIP32Node.from_master_secret(os.urandom(32), netcode=netcode).wif()


def wif2sec(wif):
    return Key.from_text(wif).sec()


def wif2pubkey(wif):
    return b2h(wif2sec(wif))


def wif2address(wif):
    return Key.from_text(wif).address()


def wif2secretexponent(wif):
    return Key.from_text(wif).secret_exponent()


def wif2privkey(wif):
    key = Key.from_text(wif)
    secret_exp = key.secret_exponent()
    return to_bytes_32(secret_exp)


def wif2netcode(wif):
    key = Key.from_text(wif)
    return key.netcode()


def decode_pubkey(pubkey):
    """Decode compressed hex pubkey."""
    compressed_pubkey = h2b(pubkey)
    public_pair = sec_to_public_pair(compressed_pubkey)
    return public_pair_to_sec(public_pair, compressed=False)


def pubkey2address(pubkey, netcode="BTC"):
    return sec2address(h2b(pubkey), netcode=netcode)


def sec2address(sec, netcode="BTC"):
    prefix = pycoin.networks.address_prefix_for_netcode(netcode)
    digest = pycoin.encoding.hash160(sec)
    return pycoin.encoding.hash160_sec_to_bitcoin_address(digest, prefix)


def script2address(script_hex, netcode="BTC"):
    return pycoin.tx.pay_to.address_for_pay_to_script(
        h2b(script_hex), netcode=netcode
    )


def hash160hex(hexdata):
    return b2h(hash160(h2b(hexdata)))


def tosatoshis(btcamount):
    return int(btcamount * 100000000)


def get_fee_multaple(factor=1, fee_per_kb=config.DEFAULT_FEE_PER_KB,
                     regular_dust_size=config.DEFAULT_REGULAR_DUST_SIZE):
    # FIXME try to get current values from bitcond instead
    future_tx_fee = fee_per_kb / 2  # mpc tx always < 512 bytes
    return int((future_tx_fee + regular_dust_size) * factor)
