require "rails"
require "action_controller/railtie"

module App
  class Application < Rails::Application
    config.load_defaults 7.1
  end
end
