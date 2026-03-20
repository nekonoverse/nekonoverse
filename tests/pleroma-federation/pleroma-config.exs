import Config

config :pleroma, Pleroma.Web.Endpoint,
  url: [host: "pleroma", scheme: "https", port: 443],
  http: [ip: {0, 0, 0, 0}, port: 4000]

config :pleroma, Pleroma.Repo,
  adapter: Ecto.Adapters.Postgres,
  username: "pleroma",
  password: "testpass",
  database: "pleroma",
  hostname: "postgres-pl",
  pool_size: 10

config :pleroma, :instance,
  name: "Pleroma Test",
  email: "admin@pleroma",
  registrations_open: true,
  account_activation_required: false,
  federation_incoming_replies_max_depth: 100,
  allow_relay: true

config :pleroma, Pleroma.Captcha,
  enabled: false

config :pleroma, :media_proxy,
  enabled: false

config :pleroma, Pleroma.Upload,
  uploader: Pleroma.Uploaders.Local

# Disable TLS verification for self-signed certs in test
config :pleroma, :http,
  adapter: [
    ssl_options: [verify: :verify_none],
    tls_opts: [verify: :verify_none],
    pools: %{
      default: [
        conn_opts: [
          tls_opts: [verify: :verify_none],
          transport_opts: [verify: :verify_none]
        ]
      ]
    }
  ]

config :pleroma, :connections_pool,
  receive_connection_timeout: 15_000

config :pleroma, :hackney_opts,
  insecure: true

config :pleroma, :http_security,
  enabled: false
