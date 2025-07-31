#!/usr/bin/env bash
set -euo pipefail

# 1) UUID de test
UUID=$(uuidgen)
MSG='{"timestamp":"'"$(date -Iseconds)"'","level":"INFO","message":"test-'$UUID'"}'
echo "→ Produit dans Kafka : $MSG"

# 2) Envoi dans Kafka
docker compose exec -T kafka \
  kafka-console-producer --broker-list kafka:9092 --topic omnisec-logs <<EOF
$MSG
EOF

# 3) On laisse Logstash consommer
echo "→ En attente de Logstash…"
sleep 5

# 4) Extraction dans les logs Logstash
echo -e "\n=== Logs Logstash contenant ‘$UUID’ ==="
docker compose logs logstash --no-color | grep "$UUID" || echo "(aucune entrée trouvée)"

# 5) Requête Elasticsearch
echo -e "\n=== Recherche dans Elasticsearch ==="
curl -s 'http://localhost:9200/logs-*/_search?pretty' \
  -H 'Content-Type: application/json' \
  -d '{
    "query": { "match": { "message": "test-'$UUID'" } }
  }' | jq .

echo -e "\n✅ Test fini (UUID=$UUID)"
