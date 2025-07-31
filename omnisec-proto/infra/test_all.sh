#!/usr/bin/env bash
set -euo pipefail

# --- CONFIG ---
COMPOSE_PROJECT_DIR="."            # adapter si besoin
KAFKA_SVC="kafka"                  # nom du service Kafka dans docker-compose
LOGSTASH_SVC="logstash"            # nom du service Logstash
ES_URL="http://localhost:9200"     # URL d'Elasticsearch
KIBANA_URL="http://localhost:5601" # URL de Kibana

TOPIC="omnisec-logs"
GROUP="logstash-omnisec"
UUID=$(uuidgen)

# 1) Restart Logstash
echo "▶ Restarting Logstash..."
docker compose restart ${LOGSTASH_SVC}

# 2) Wait for pipeline to start
echo "▶ Waiting for Logstash pipeline to start..."
timeout 60 bash -c \
  "until docker compose logs ${LOGSTASH_SVC} | grep -q 'Pipeline started {\"pipeline.id\"=>\"main\"}'; do sleep 1; done"

# 3) Produce test event to Kafka
PAYLOAD="{\"timestamp\":\"$(date -Iseconds)\",\"level\":\"INFO\",\"message\":\"test-${UUID}\"}"
echo "▶ Producing test event to Kafka: $PAYLOAD"
docker compose exec -T ${KAFKA_SVC} \
  kafka-console-producer --broker-list kafka:9092 --topic ${TOPIC} <<< "${PAYLOAD}"

# 4) Wait for Logstash to log it
echo "▶ Waiting for Logstash to pick it up..."
timeout 30 bash -c \
  "until docker compose logs ${LOGSTASH_SVC} | grep -q 'test-${UUID}'; do sleep 1; done"

echo
echo "=== Logstash logs containing ‘${UUID}’ ==="
docker compose logs ${LOGSTASH_SVC} | grep "test-${UUID}" || echo "(aucune entrée trouvée)"

# 5) Query Elasticsearch
echo
echo "=== Elasticsearch search ==="
curl -s "${ES_URL}/logs-*/_search?pretty" \
  -H 'Content-Type: application/json' \
  -d '{
    "query": { "match": { "message": "test-'${UUID}'" } },
    "size": 5
  }'

# 6) List Kibana index-patterns logs-*
echo
echo "=== Kibana index-patterns matching logs-* ==="
curl -s -X GET "${KIBANA_URL}/api/saved_objects/_find?type=index-pattern&search=logs-*&search_fields=title" \
     -H "kbn-xsrf: true" | jq '.saved_objects[] | {id: .id, title: .attributes.title}'

echo
echo "✅ Script terminé (UUID=${UUID})"
