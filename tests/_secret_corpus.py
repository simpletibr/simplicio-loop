"""Hostile command lines shared by the producers that write a command into a dashboard event.

Each entry is ``(command, secret)``: no event may carry ``secret`` after the command went through ``runs.redact_command``.
Only fake secrets live here.
"""
from __future__ import annotations

SECRET_CORPUS = [
    ("GH_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz0123456789 gh pr list", "abcdefghijklmnopqrstuvwxyz0123456789"),
    ("tool --token abcdef123456SECRET run", "abcdef123456SECRET"),
    ("tool --password 'correct horse battery' run", "horse battery"),
    ("tool --pat abcdefSECRET123 x", "abcdefSECRET123"),
    ("mysql -u root -p hunter2hunter2 db", "hunter2hunter2"),
    ("mysql -u root -phunter2hunter2 db", "hunter2hunter2"),
    ("sshpass -p 'hunter2hunter2' ssh host", "hunter2hunter2"),
    ("docker login -u me -p hunter2hunter2", "hunter2hunter2"),
    ("twine upload -u __token__ -p pypi-AgEIcHlwaS5vcmcCJGFiY2RlZmdoaWprbG1ub3A", "AgEIcHlwaS5vcmc"),
    ("curl -u admin:S3cretPw99 https://api.example.com/x", "S3cretPw99"),
    ("curl --user admin:S3cretPw99 https://api.example.com/x", "S3cretPw99"),
    ("curl -b 'session=abcdefSECRET1234567' https://x", "abcdefSECRET1234567"),
    ("curl -H 'Authorization: Bearer abcdefghijklmnop' https://x", "abcdefghijklmnop"),
    ("curl -H 'Authorization: Basic dXNlcjpTM2NyZXRQdzk5' https://x", "dXNlcjpTM2NyZXRQdzk5"),
    ("curl -H 'Authorization: sometoken1234567890abcd' https://x", "sometoken1234567890abcd"),
    ("curl -H 'Cookie: session=abcdefSECRET1234567' https://x", "abcdefSECRET1234567"),
    ("curl -H 'Authorization: Bearer eyJhbGciOiJIUzI1NiJ9." + "A" * 520 + ".SIGPART" + "B" * 60 + "' https://x", "SIGPART"),
    ("git clone https://user:p4ssw0rdvalue@example.com/x.git", "p4ssw0rdvalue"),
    ("git clone https://user:p4ssw0rdvalue@localhost/x.git", "p4ssw0rdvalue"),
    ("git clone https://user:p4ssw0rdvalue@gitea:3000/x.git", "p4ssw0rdvalue"),
    ("git clone https://ghp_abcdefghijklmnopqrstuvwxyz0123456789@github.com/x.git", "abcdefghijklmnopqrstuvwxyz0123456789"),
    ("DATABASE_URL=postgres://admin:S3cretPw99@localhost:5432/db pytest -q", "S3cretPw99"),
    ("echo QUtJQVNFQ1JFVEtFWTEyMzQ1Njc4OTBhYmNkZWZnaGlqa2xtbm9wcXJzdHV2d3h5eg== | base64 -d",
     "QUtJQVNFQ1JFVEtFWTEyMzQ1Njc4OTBhYmNkZWZnaGlqa2xtbm9wcXJzdHV2d3h5eg"),
    ("send xox" + "b-123456789012-1234567890123-abcdefghijklmnopqrstuvwx", "abcdefghijklmnopqrstuvwx"),  # split: push protection
    ("npm config set //registry.npmjs.org/:_authToken npm_abcdefghijklmnopqrstuvwxyz0123456789", "abcdefghijklmnopqrstuvwxyz0123456789"),
    ("echo '-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEAxxSECRETKEYBODYxx", "SECRETKEYBODY"),
    ("""curl -d '{"password":"hunter2hunter2"}' https://x""", "hunter2hunter2"),
    ("AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY aws s3 ls", "bPxRfiCYEXAMPLEKEY"),
]
