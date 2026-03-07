<?php

declare(strict_types=1);

namespace ExperimentationPlatform\Tests;

use ExperimentationPlatform\ExperimentationClient;
use ExperimentationPlatform\HttpClient;
use ExperimentationPlatform\SdkConfig;
use ExperimentationPlatform\Errors\ApiException;
use ExperimentationPlatform\Errors\AuthException;
use ExperimentationPlatform\Errors\NetworkException;
use PHPUnit\Framework\MockObject\MockObject;
use PHPUnit\Framework\TestCase;

/**
 * Unit tests for ExperimentationClient.
 *
 * HttpClient is injected via the constructor so we can mock it without real HTTP.
 */
class ExperimentationClientTest extends TestCase
{
    // -------------------------------------------------------------------------
    // Helpers
    // -------------------------------------------------------------------------

    private function makeConfig(): SdkConfig
    {
        return new SdkConfig(
            baseUrl: 'https://api.example.com',
            apiKey: 'test-api-key',
            cacheTtl: 300,
            timeout: 5,
        );
    }

    /**
     * Build a mock HttpClient.
     *
     * @return HttpClient&MockObject
     */
    private function makeMockHttp(): MockObject
    {
        return $this->createMock(HttpClient::class);
    }

    private function makeFlag(array $overrides = []): array
    {
        return array_merge([
            'key'                => 'dark-mode',
            'enabled'            => true,
            'rollout_percentage' => 100,
            'variants'           => [
                ['key' => 'control', 'value' => 'off'],
                ['key' => 'treatment', 'value' => 'on'],
            ],
        ], $overrides);
    }

    // -------------------------------------------------------------------------
    // evaluateFlag — API fetching
    // -------------------------------------------------------------------------

    public function testEvaluateFlagFetchesFromApi(): void
    {
        $http = $this->makeMockHttp();
        $http->expects($this->once())
            ->method('get')
            ->with($this->stringContains('dark-mode'))
            ->willReturn($this->makeFlag());

        $client = new ExperimentationClient($this->makeConfig(), $http);
        $result = $client->evaluateFlag('dark-mode', 'user-123');

        $this->assertIsArray($result);
        $this->assertArrayHasKey('enabled', $result);
        $this->assertArrayHasKey('variant', $result);
        $this->assertArrayHasKey('value', $result);
    }

    public function testEvaluateFlagCachesResult(): void
    {
        $http = $this->makeMockHttp();
        // HTTP must be called exactly ONCE even though we call evaluateFlag twice
        $http->expects($this->once())
            ->method('get')
            ->willReturn($this->makeFlag());

        $client = new ExperimentationClient($this->makeConfig(), $http);

        $client->evaluateFlag('dark-mode', 'user-123');
        $client->evaluateFlag('dark-mode', 'user-456'); // Should use cache — no second HTTP call
    }

    public function testEvaluateFlagReturnsEnabledTrueWhenUserInRollout(): void
    {
        $http = $this->makeMockHttp();
        $http->method('get')->willReturn($this->makeFlag(['rollout_percentage' => 100]));

        $client = new ExperimentationClient($this->makeConfig(), $http);
        $result = $client->evaluateFlag('dark-mode', 'user-123');

        $this->assertTrue($result['enabled']);
        $this->assertNotNull($result['variant']);
    }

    public function testEvaluateFlagReturnsEnabledFalseWhenUserNotInRollout(): void
    {
        // hashUser("user-123", "dark-mode") → some bucket; use 0% rollout to exclude everyone
        $http = $this->makeMockHttp();
        $http->method('get')->willReturn($this->makeFlag(['rollout_percentage' => 0]));

        $client = new ExperimentationClient($this->makeConfig(), $http);
        $result = $client->evaluateFlag('dark-mode', 'user-123');

        $this->assertFalse($result['enabled']);
        $this->assertNull($result['variant']);
    }

    public function testEvaluateFlagReturnsDefaultOnNetworkError(): void
    {
        $http = $this->makeMockHttp();
        $http->method('get')->willThrowException(new NetworkException('timeout'));

        $client = new ExperimentationClient($this->makeConfig(), $http);
        $result = $client->evaluateFlag('dark-mode', 'user-123', [], 'my-default');

        $this->assertFalse($result['enabled']);
        $this->assertNull($result['variant']);
        $this->assertSame('my-default', $result['value']);
    }

    public function testEvaluateFlagReturnsDefaultOnApiError(): void
    {
        $http = $this->makeMockHttp();
        $http->method('get')->willThrowException(new ApiException('Not Found', 404));

        $client = new ExperimentationClient($this->makeConfig(), $http);
        $result = $client->evaluateFlag('dark-mode', 'user-123', [], false);

        $this->assertFalse($result['enabled']);
        $this->assertSame(false, $result['value']);
    }

    public function testEvaluateFlagPassesAttributesWithoutCrashing(): void
    {
        $http = $this->makeMockHttp();
        $http->method('get')->willReturn($this->makeFlag());

        $client = new ExperimentationClient($this->makeConfig(), $http);
        $result = $client->evaluateFlag('dark-mode', 'user-123', ['country' => 'US', 'plan' => 'premium']);

        $this->assertIsArray($result);
    }

    // -------------------------------------------------------------------------
    // getAssignment
    // -------------------------------------------------------------------------

    public function testGetAssignmentReturnsAssignment(): void
    {
        $assignment = [
            'experiment_key' => 'checkout-v2',
            'user_id'        => 'user-123',
            'variant'        => 'treatment',
            'is_control'     => false,
        ];

        $http = $this->makeMockHttp();
        $http->expects($this->once())
            ->method('post')
            ->willReturn($assignment);

        $client = new ExperimentationClient($this->makeConfig(), $http);
        $result = $client->getAssignment('checkout-v2', 'user-123');

        $this->assertSame($assignment, $result);
    }

    public function testGetAssignmentReturnsNullOnNetworkError(): void
    {
        $http = $this->makeMockHttp();
        $http->method('post')->willThrowException(new NetworkException('timeout'));

        $client = new ExperimentationClient($this->makeConfig(), $http);
        $result = $client->getAssignment('checkout-v2', 'user-123');

        $this->assertNull($result);
    }

    public function testGetAssignmentReturnsNullOnApiError(): void
    {
        $http = $this->makeMockHttp();
        $http->method('post')->willThrowException(new ApiException('Not Found', 404));

        $client = new ExperimentationClient($this->makeConfig(), $http);
        $result = $client->getAssignment('checkout-v2', 'user-123');

        $this->assertNull($result);
    }

    public function testGetAssignmentCachesResult(): void
    {
        $assignment = ['variant' => 'control'];

        $http = $this->makeMockHttp();
        // Must be called only once despite two getAssignment calls
        $http->expects($this->once())
            ->method('post')
            ->willReturn($assignment);

        $client = new ExperimentationClient($this->makeConfig(), $http);

        $first  = $client->getAssignment('exp-key', 'user-123');
        $second = $client->getAssignment('exp-key', 'user-123');

        $this->assertSame($first, $second);
    }

    // -------------------------------------------------------------------------
    // track
    // -------------------------------------------------------------------------

    public function testTrackReturnsTrue(): void
    {
        $http = $this->makeMockHttp();
        $http->method('post')->willReturn(['success' => true]);

        $client = new ExperimentationClient($this->makeConfig(), $http);
        $result = $client->track('purchase', 'user-123', ['amount' => 99.99]);

        $this->assertTrue($result);
    }

    public function testTrackReturnsFalseOnNetworkError(): void
    {
        $http = $this->makeMockHttp();
        $http->method('post')->willThrowException(new NetworkException('timeout'));

        $client = new ExperimentationClient($this->makeConfig(), $http);
        $result = $client->track('purchase', 'user-123');

        $this->assertFalse($result);
    }

    public function testTrackReturnsFalseOnApiError(): void
    {
        $http = $this->makeMockHttp();
        $http->method('post')->willThrowException(new ApiException('Internal Server Error', 500));

    $client = new ExperimentationClient($this->makeConfig(), $http);
        $result = $client->track('purchase', 'user-123');

        $this->assertFalse($result);
    }

    public function testTrackNeverThrows(): void
    {
        $http = $this->makeMockHttp();
        $http->method('post')->willThrowException(new \RuntimeException('Unexpected error'));

        $client = new ExperimentationClient($this->makeConfig(), $http);

        // Must not throw even when unexpected exceptions occur
        $result = $client->track('crash-event', 'user-123');
        $this->assertFalse($result);
    }

    public function testTrackReturnsFalseOnAuthError(): void
    {
        $http = $this->makeMockHttp();
        $http->method('post')->willThrowException(new AuthException());

        $client = new ExperimentationClient($this->makeConfig(), $http);
        $result = $client->track('purchase', 'user-123');

        $this->assertFalse($result);
    }

    // -------------------------------------------------------------------------
    // Constructor — default HttpClient
    // -------------------------------------------------------------------------

    public function testConstructorCreatesDefaultHttpClientWhenNotProvided(): void
    {
        $config = $this->makeConfig();
        // Should not throw
        $client = new ExperimentationClient($config);
        $this->assertInstanceOf(ExperimentationClient::class, $client);
    }
}
