use anyhow::Result;
use chrono::Utc;
use futures::StreamExt;
use hostname::get as get_hostname;
use rdkafka::{
    config::ClientConfig,
    producer::{FutureProducer, FutureRecord},
};
use serde::Serialize;
use std::{env, io::SeekFrom, time::Duration};
use tokio::{
    fs::File,
    io::{AsyncBufReadExt, AsyncSeekExt, BufReader},
    time::sleep,
};

#[derive(Serialize)]
struct Event {
    timestamp: String,
    level:     String,
    message:   String,
    host:      String,
    service:   String,
}

async fn create_producer(brokers: &str) -> FutureProducer {
    loop {
        match ClientConfig::new()
            .set("bootstrap.servers", brokers)
            .set("message.timeout.ms", "5000")
            .create::<FutureProducer>()
        {
            Ok(p) => {
                eprintln!("✅ Kafka producer connected to {}", brokers);
                return p;
            }
            Err(err) => {
                eprintln!("❌ Kafka producer error {}. Retrying in 1s…", err);
                sleep(Duration::from_secs(1)).await;
            }
        }
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    // 1) Chemin du fichier
    let path = env::args()
        .nth(1)
        .unwrap_or_else(|| "src/logs/app.log".into());

    // 2) Récupère host & service
    let host = get_hostname()?
        .into_string()
        .unwrap_or_else(|_| "unknown-host".into());
    let service = env::var("SERVICE_NAME").unwrap_or_else(|_| "omnisec-agent".into());

    // 3) Ouvre et positionne à la fin
    let file = File::open(&path).await?;
    let mut reader = BufReader::new(file);
    reader.seek(SeekFrom::End(0)).await?;

    // 4) Crée le producer Kafka (retry)
    let brokers = "localhost:29092";
    let topic = "omnisec-logs";
    let producer = create_producer(brokers).await;

    // 5) Boucle de tail-f
    let mut lines = reader.lines();
    loop {
        match lines.next_line().await? {
            Some(line) => {
                let evt = Event {
                    timestamp: Utc::now().to_rfc3339(),
                    level:     "INFO".into(),
                    message:   line.clone(),
                    host:      host.clone(),
                    service:   service.clone(),
                };
                let payload = serde_json::to_string(&evt)?;
                eprintln!("→ publishing to Kafka: {}", payload);

                // Envoi asynchrone (on logue le résultat pour être sûr que Kafka a bien reçu)
                let record = FutureRecord::to(topic)
                    .payload(&payload)
                    .key(&evt.level);

                match producer.send(record, Duration::from_secs(1)).await {
                    Ok((partition, offset)) => 
                        eprintln!("✅ envoyé partition={} offset={}", partition, offset),
                    Err((e, _msg)) => 
                        eprintln!("❌ erreur d’envoi Kafka : {:?}", e),
                    }

            }
            
            None => {
                sleep(Duration::from_millis(200)).await;
            }
        }
    }
}
