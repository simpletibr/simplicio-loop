defmodule AppWeb.Endpoint do
  use Phoenix.Endpoint, otp_app: :app

  plug AppWeb.Router
end
