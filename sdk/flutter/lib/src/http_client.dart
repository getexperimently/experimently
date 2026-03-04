/// Lightweight HTTP client wrapper around the `http` package.
library experimentation_sdk_http_client;

import 'dart:convert';
import 'package:http/http.dart' as http;

/// Wraps the `http` package to provide a simple JSON-oriented API with
/// configurable timeouts and API-key authentication.
class ApiHttpClient {
  final String apiKey;
  final String baseUrl;
  final Duration timeout;

  /// Underlying HTTP client; can be replaced in tests.
  final http.Client _client;

  ApiHttpClient({
    required this.apiKey,
    required this.baseUrl,
    required this.timeout,
    http.Client? httpClient,
  }) : _client = httpClient ?? http.Client();

  /// Performs a GET request and decodes the JSON response body.
  ///
  /// Throws [ApiException] on non-2xx responses or network errors.
  Future<Map<String, dynamic>> get(String path) async {
    final uri = Uri.parse('${baseUrl.replaceAll(RegExp(r'/$'), '')}$path');
    final headers = {
      'X-API-Key': apiKey,
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    };

    try {
      final response = await _client
          .get(uri, headers: headers)
          .timeout(timeout);

      if (response.statusCode >= 200 && response.statusCode < 300) {
        return json.decode(response.body) as Map<String, dynamic>;
      }

      throw ApiException(
        statusCode: response.statusCode,
        message: 'API error: ${response.statusCode}',
      );
    } on ApiException {
      rethrow;
    } catch (e) {
      throw ApiException(
        statusCode: 0,
        message: 'Network error: $e',
      );
    }
  }

  /// Performs a POST request with a JSON body.
  ///
  /// Returns the decoded response body. Throws [ApiException] on errors.
  Future<Map<String, dynamic>> post(
    String path,
    Map<String, dynamic> body,
  ) async {
    final uri = Uri.parse('${baseUrl.replaceAll(RegExp(r'/$'), '')}$path');
    final headers = {
      'X-API-Key': apiKey,
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    };

    try {
      final response = await _client
          .post(uri, headers: headers, body: json.encode(body))
          .timeout(timeout);

      if (response.statusCode >= 200 && response.statusCode < 300) {
        if (response.body.isEmpty) return {};
        return json.decode(response.body) as Map<String, dynamic>;
      }

      throw ApiException(
        statusCode: response.statusCode,
        message: 'API error: ${response.statusCode}',
      );
    } on ApiException {
      rethrow;
    } catch (e) {
      throw ApiException(
        statusCode: 0,
        message: 'Network error: $e',
      );
    }
  }

  /// Releases the underlying HTTP client resources.
  void close() {
    _client.close();
  }
}

/// Exception thrown by [ApiHttpClient] on non-2xx responses or network errors.
class ApiException implements Exception {
  final int statusCode;
  final String message;

  const ApiException({required this.statusCode, required this.message});

  @override
  String toString() => 'ApiException($statusCode): $message';
}
