use nekonoverse_backend_rs::{build_router, config::Config, db, state::AppState, storage, valkey};

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env().unwrap_or_else(|_| "info".into()),
        )
        .init();

    let config = Config::from_env();

    // `app.main.lifespan`と同じくベストエフォート(失敗してもプロセス起動は続行する)。
    if let Err(err) = storage::ensure_bucket(&config).await {
        tracing::warn!(?err, "Could not ensure S3 bucket");
    }

    let db_pool = db::connect(&config).await?;
    let redis_conn = valkey::connect(&config).await?;

    let state = AppState {
        db: db_pool,
        redis: redis_conn,
        config: config.clone(),
    };
    let app = build_router(state);

    if let Some(uds_path) = &config.bind_uds {
        serve_uds(app, uds_path).await?;
    } else {
        serve_tcp(app, &config.bind_addr).await?;
    }

    Ok(())
}

async fn serve_tcp(app: axum::Router, addr: &str) -> anyhow::Result<()> {
    tracing::info!(%addr, "listening (tcp)");
    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;
    Ok(())
}

/// nginx との通信は本番では Unix Domain Socket 越し (`app-rs.sock`) のため、
/// axum 0.7 に組み込みの `Listener` 実装が無い UDS を hyper の accept ループで
/// 直接扱う。
async fn serve_uds(app: axum::Router, path: &str) -> anyhow::Result<()> {
    use hyper_util::rt::{TokioExecutor, TokioIo};
    use hyper_util::server::conn::auto::Builder;
    use hyper_util::service::TowerToHyperService;
    use std::os::unix::fs::PermissionsExt;
    use tower::Service;

    // 前回起動時のソケットファイルが残っていれば bind 前に消しておく。
    let _ = std::fs::remove_file(path);
    let listener = tokio::net::UnixListener::bind(path)?;
    // nginx (別 uid で動作) から接続できるよう world rw にする。Python 側の
    // `umask 0111 && uvicorn --uds ...` と同じ効果 (0666 = 実行ビットなし
    // の world read/write。ソケットに実行ビットは無意味なので問題ない)。
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o666))?;
    tracing::info!(%path, "listening (uds)");

    loop {
        let (stream, _addr) = listener.accept().await?;
        let io = TokioIo::new(stream);
        let mut app = app.clone();
        tokio::spawn(async move {
            let service = TowerToHyperService::new(tower::service_fn(move |req| app.call(req)));
            if let Err(err) = Builder::new(TokioExecutor::new())
                .serve_connection(io, service)
                .await
            {
                tracing::warn!(%err, "connection error");
            }
        });
    }
}
