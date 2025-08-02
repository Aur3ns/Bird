#!/usr/bin/env bash
set -euo pipefail

# Config
COMPOSE="docker compose"
KAFKA_SERVICE="kafka"
LOGSTASH_SERVICE="logstash"
ES_HOST="http://localhost:9200"
TOPIC="omnisec-logs"
ES_INDEX_PATTERN="logs-write*"
TIMEOUT_LOGSTASH=30  # en secondes
TIMEOUT_ES=30        # en secondes

# Génère un UUID pour tracer ce test
UUID=$(uuidgen)
PAYLOAD=$(jq -nc --arg ts "$(date -Iseconds)" --arg msg "test-$UUID" '{timestamp:$ts,level:"INFO",message:$msg}')

echo "→ Envoi dans Kafka : $PAYLOAD"
# On utilise -T pour ne pas réclamer de TTY
$COMPOSE exec -T $KAFKA_SERVICE \
  kafka-console-producer --broker-list kafka:9092 --topic $TOPIC <<EOF
$PAYLOAD
EOF

echo "→ En attente d'apparition dans les logs de Logstash (max ${TIMEOUT_LOGSTASH}s)…"
if timeout $TIMEOUT_LOGSTASH bash -c \
   "until $COMPOSE logs $LOGSTASH_SERVICE | grep -F -m1 \"$UUID\" >/dev/null; do sleep 1; done"; then
  echo "✔️ trouvé dans les logs Logstash"
else
  echo "❌ pas trouvé dans les logs Logstash au bout de ${TIMEOUT_LOGSTASH}s"
  exit 1
fi

echo "→ En attente d'indexation dans Elasticsearch (max ${TIMEOUT_ES}s)…"
# Poll Elasticsearch jusqu'à trouver le document
if timeout $TIMEOUT_ES bash -c \
   "until curl -s \"$ES_HOST/$ES_INDEX_PATTERN/_search?pretty&q=message:test-$UUID\" | grep -F '\"hits\"' -A2 | grep -q '\"value\" : [1-9]'; do sleep 1; done"; then
  echo "✔️ trouvé dans Elasticsearch"
else
  echo "❌ pas trouvé dans Elasticsearch au bout de ${TIMEOUT_ES}s"
  exit 1
fi

echo
echo "✅ TEST PIPELINE RÉUSSI (UUID=$UUID)"
