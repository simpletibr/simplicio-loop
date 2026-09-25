import Vapor

struct HealthResponse: Content {
    let ok: Bool
}

let app = try await Application.make(.detect())
app.get("health") { _ in
    HealthResponse(ok: true)
}
try await app.execute()
