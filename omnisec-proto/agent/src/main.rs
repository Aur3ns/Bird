use anyhow::Result;
use chrono::Utc;
use tokio::net::TcpStream;
use tokio::io::{AsyncWriteExt};
use serde::Serialize;

#[derive(Serialize)]
struct Event {
    timestamp: String,
    level: String,
    message: String,
}

#[tokio::main]
async fn main() -> Result<()> {
    // Création d'un événement d'exemple
    let evt = Event {
        timestamp: Utc::now().to_rfc3339(),
        level: "INFO".into(),
        message: "OmniSec agent started".into(),
    };
    let json = serde_json::to_string(&evt)?;

    // Envoi vers Logstash
    let mut stream = TcpStream::connect("127.0.0.1:5000").await?;
    stream.write_all(json.as_bytes()).await?;
    stream.write_all(b"\n").await?;
    Ok(())
}
