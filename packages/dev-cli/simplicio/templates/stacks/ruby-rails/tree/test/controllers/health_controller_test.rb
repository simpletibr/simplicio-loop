require "test_helper"

class HealthControllerTest < ActionDispatch::IntegrationTest
  test "health responds ok" do
    get "/health"

    assert_response :success
    assert_equal({ "ok" => true }, JSON.parse(response.body))
  end
end
