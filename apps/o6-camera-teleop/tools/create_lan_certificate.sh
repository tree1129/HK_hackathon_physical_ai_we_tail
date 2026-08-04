#!/bin/zsh
set -eu

SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h}"
CERT_DIR="$PROJECT_DIR/.certs"
LAN_IP="${1:-$(ipconfig getifaddr en0)}"

if [[ -z "$LAN_IP" ]]; then
  print -u2 "ERROR: LAN IP not found. Pass it explicitly: $0 192.168.x.x"
  exit 1
fi

mkdir -p "$CERT_DIR"
openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 3650 \
  -keyout "$CERT_DIR/o6-lan-ca.key" \
  -out "$CERT_DIR/o6-lan-ca.crt" \
  -subj "/CN=O6 LAN Camera CA"
openssl req -newkey rsa:2048 -sha256 -nodes \
  -keyout "$CERT_DIR/o6-lan.key" \
  -out "$CERT_DIR/o6-lan.csr" \
  -subj "/CN=$LAN_IP"
openssl x509 -req -sha256 -days 365 \
  -in "$CERT_DIR/o6-lan.csr" \
  -CA "$CERT_DIR/o6-lan-ca.crt" \
  -CAkey "$CERT_DIR/o6-lan-ca.key" \
  -CAcreateserial \
  -out "$CERT_DIR/o6-lan.crt" \
  -extfile <(print "subjectAltName=IP:$LAN_IP,IP:127.0.0.1,DNS:localhost\nextendedKeyUsage=serverAuth\nbasicConstraints=CA:FALSE")
rm "$CERT_DIR/o6-lan.csr" "$CERT_DIR/o6-lan-ca.srl"
print "Created HTTPS certificate for $LAN_IP in $CERT_DIR"
print "Install o6-lan-ca.crt on the iPhone and enable full trust."
