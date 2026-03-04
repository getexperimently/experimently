import Foundation

/// URLSession-based HTTP client for communicating with the Experimentation Platform API.
///
/// All requests include an `X-API-Key` header for authentication.
/// Throws `ExperimentationError` on network, server, or decoding failures.
public class HTTPClient {
    private let session: URLSession
    private let baseURL: String
    private let apiKey: String
    private let timeout: TimeInterval

    private let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.keyEncodingStrategy = .convertToSnakeCase
        return e
    }()

    private let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    /// - Parameters:
    ///   - baseURL: The root URL of the API (e.g., `"http://localhost:8000"`).
    ///   - apiKey: API key sent in the `X-API-Key` request header.
    ///   - timeout: Request timeout in seconds (default: 10).
    ///   - session: URLSession to use. Inject a custom session for testing.
    public init(
        baseURL: String,
        apiKey: String,
        timeout: TimeInterval = 10.0,
        session: URLSession = .shared
    ) {
        self.baseURL = baseURL
        self.apiKey = apiKey
        self.timeout = timeout
        self.session = session
    }

    // MARK: - Async/Await Interface

    /// Performs a GET request and decodes the response body as `T`.
    ///
    /// - Parameters:
    ///   - path: API path relative to `baseURL` (e.g., `/api/v1/flags/my-flag`).
    ///   - type: The `Decodable` type to decode the response into.
    /// - Returns: A decoded instance of `T`.
    /// - Throws: `ExperimentationError.networkError`, `.serverError`, or `.decodingError`.
    public func get<T: Decodable>(_ path: String, as type: T.Type) async throws -> T {
        let request = try buildRequest(path, method: "GET")
        return try await perform(request, as: type)
    }

    /// Performs a POST request with a JSON-encoded body and decodes the response as `Response`.
    ///
    /// - Parameters:
    ///   - path: API path relative to `baseURL`.
    ///   - body: An `Encodable` value to send as the request body.
    ///   - type: The `Decodable` type to decode the response into.
    /// - Returns: A decoded instance of `Response`.
    /// - Throws: `ExperimentationError.networkError`, `.serverError`, or `.decodingError`.
    public func post<Body: Encodable, Response: Decodable>(
        _ path: String,
        body: Body,
        as type: Response.Type
    ) async throws -> Response {
        let bodyData = try encoder.encode(body)
        let request = try buildRequest(path, method: "POST", body: bodyData)
        return try await perform(request, as: type)
    }

    /// Performs a fire-and-forget POST for event tracking.
    ///
    /// This method launches a background URLSession data task and returns immediately.
    /// Errors are silently ignored; this is appropriate for best-effort analytics tracking.
    ///
    /// - Parameters:
    ///   - path: API path relative to `baseURL`.
    ///   - body: An `Encodable` value to send as the request body.
    public func postFireAndForget<Body: Encodable>(_ path: String, body: Body) {
        guard let bodyData = try? encoder.encode(body),
              let request = try? buildRequest(path, method: "POST", body: bodyData)
        else { return }

        session.dataTask(with: request).resume()
    }

    // MARK: - Private Helpers

    private func perform<T: Decodable>(_ request: URLRequest, as type: T.Type) async throws -> T {
        let data: Data
        let response: URLResponse

        do {
            (data, response) = try await session.data(for: request)
        } catch let urlError as URLError where urlError.code == .cancelled {
            throw ExperimentationError.cancelled
        } catch {
            throw ExperimentationError.networkError(error)
        }

        if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
            let message = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw ExperimentationError.serverError(http.statusCode, message)
        }

        do {
            return try decoder.decode(type, from: data)
        } catch {
            throw ExperimentationError.decodingError(error)
        }
    }

    internal func buildRequest(_ path: String, method: String, body: Data? = nil) throws -> URLRequest {
        let urlString = baseURL.hasSuffix("/")
            ? baseURL + path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
            : baseURL + path

        guard let url = URL(string: urlString) else {
            throw ExperimentationError.invalidConfig("Invalid URL: \(urlString)")
        }

        var request = URLRequest(url: url, timeoutInterval: timeout)
        request.httpMethod = method
        request.setValue(apiKey, forHTTPHeaderField: "X-API-Key")
        request.setValue("application/json", forHTTPHeaderField: "Accept")

        if let body = body {
            request.httpBody = body
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }

        return request
    }
}
