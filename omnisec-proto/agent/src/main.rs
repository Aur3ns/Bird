use anyhow::Result;
use chrono::Utc;
use serde::Serialize;
use std::env;
use std::io::SeekFrom;
use tokio::{
    fs::File,
    io::{AsyncBufReadExt, AsyncSeekExt, BufReader},
    net::TcpStream,
};

#[derive(Serialize)]
struct Event {
    timestamp: String,
    level: String,
    message: String,
}

#[tokio::main]
async fn main() -> Result<()> {
    // 1) Récupère le chemin du fichier à tailer (ou un défaut)
    let path = env::args()
        .nth(1)
        .unwrap_or_else(|| "logs/app.log".to_string());

    // 2) Ouvre le fichier et se positionne à la fin
    let file = File::open(&path).await?;
    let mut reader = BufReader::new(file);
    reader.seek(SeekFrom::End(0)).await?;

    // 3) Pour chaque nouvelle ligne, envoie un Event JSON
    let mut lines = reader.lines();
    while let Some(line) = lines.next_line().await? {
        let evt = Event {
            timestamp: Utc::now().to_rfc3339(),
            level: "INFO".into(),
            message: line,
        };
        let json = serde_json::to_string(&evt)?;

        // 4) Connexion TCP à Logstash (port 5000)
        let mut stream = TcpStream::connect("127.0.0.1:5000").await?;
        stream.write_all(json.as_bytes()).await?;
        stream.write_all(b"\n").await?;
    }

    Ok(())
}
