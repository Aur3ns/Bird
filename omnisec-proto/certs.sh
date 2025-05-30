#!/usr/bin/env bash
set -euo pipefail

CERTS_DIR="infra/certs"
ES_IMAGE="docker.elastic.co/elasticsearch/elasticsearch:8.5.1"

echo "➡️  Suppression des anciens certificats et archives…"
rm -rf "$CERTS_DIR"/{ca*,elastic*,*.zip}

mkdir -p "$CERTS_DIR"

echo "1/4 Génération du CA…"
docker run --rm \
  -v "$(pwd)/infra/certs":/certs \
  $ES_IMAGE \
  /usr/share/elasticsearch/bin/elasticsearch-certutil ca \
    --pem \
    --out /certs/ca.zip

echo "2/4 Extraction et aplatissage du CA…"
unzip -o "$CERTS_DIR/ca.zip" -d "$CERTS_DIR"
mv "$CERTS_DIR"/ca/ca.crt "$CERTS_DIR"/ca.crt
mv "$CERTS_DIR"/ca/ca.key "$CERTS_DIR"/ca.key
rm -rf "$CERTS_DIR"/ca

echo "3/4 Génération du certificat Elasticsearch avec SAN…"
docker run --rm \
  -v "$(pwd)/infra/certs":/certs \
  $ES_IMAGE \
  /usr/share/elasticsearch/bin/elasticsearch-certutil cert \
    --name elastic \
    --ca-cert /certs/ca.crt \
    --ca-key  /certs/ca.key \
    --pem \
    --dns elasticsearch,localhost \
    --ip 127.0.0.1 \
    --out /certs/elastic.zip

echo "4/4 Extraction et aplatissage du certificat Elasticsearch…"
unzip -o "$CERTS_DIR/elastic.zip" -d "$CERTS_DIR"
mv "$CERTS_DIR"/elastic/elastic.crt "$CERTS_DIR"/elastic.crt
mv "$CERTS_DIR"/elastic/elastic.key "$CERTS_DIR"/elastic.key
rm -rf "$CERTS_DIR"/elastic

echo "✅ Certificats mis à jour :"
echo "   CA           -> $CERTS_DIR/ca.crt, $CERTS_DIR/ca.key"
echo "   Elasticsearch -> $CERTS_DIR/elastic.crt, $CERTS_DIR/elastic.key"
