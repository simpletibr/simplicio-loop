import Config

config :app, AppWeb.Endpoint,
  url: [host: "localhost"],
  secret_key_base: String.duplicate("a", 64),
  render_errors: [formats: [json: AppWeb.ErrorJSON]],
  pubsub_server: App.PubSub
