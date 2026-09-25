class HealthController < ActionController::API
  def show
    render json: { ok: true }
  end
end
