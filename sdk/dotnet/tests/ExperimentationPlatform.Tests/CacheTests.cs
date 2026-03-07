using ExperimentationPlatform;
using Xunit;

namespace ExperimentationPlatform.Tests;

/// <summary>
/// Tests for <see cref="SdkCache{TValue}"/> — TTL, LRU eviction, thread safety, and core operations.
/// </summary>
public class CacheTests
{
    // -----------------------------------------------------------------------
    // Basic get/set
    // -----------------------------------------------------------------------

    [Fact]
    public void Get_MissingKey_ReturnsNull()
    {
        var cache = new SdkCache<string>();
        var result = cache.Get("nonexistent");
        Assert.Null(result);
    }

    [Fact]
    public void Get_AfterSet_ReturnsValue()
    {
        var cache = new SdkCache<string>(defaultTtl: TimeSpan.FromSeconds(60));
        cache.Set("key1", "hello");
        Assert.Equal("hello", cache.Get("key1"));
    }

    [Fact]
    public void Set_OverwritesExistingValue()
    {
        var cache = new SdkCache<string>(defaultTtl: TimeSpan.FromSeconds(60));
        cache.Set("key", "first");
        cache.Set("key", "second");
        Assert.Equal("second", cache.Get("key"));
    }

    // -----------------------------------------------------------------------
    // TTL expiration
    // -----------------------------------------------------------------------

    [Fact]
    public void Get_AfterTtlExpiry_ReturnsNull()
    {
        var cache = new SdkCache<string>();
        // Use a 1-second TTL.
        cache.Set("expiring-key", "value", TimeSpan.FromSeconds(1));

        // Value should exist immediately.
        Assert.Equal("value", cache.Get("expiring-key"));

        // Wait for expiry.
        Thread.Sleep(1100);

        Assert.Null(cache.Get("expiring-key"));
    }

    [Fact]
    public void Get_BeforeTtlExpiry_ReturnsValue()
    {
        var cache = new SdkCache<string>();
        cache.Set("alive-key", "alive", TimeSpan.FromSeconds(10));
        Thread.Sleep(100);
        Assert.Equal("alive", cache.Get("alive-key"));
    }

    // -----------------------------------------------------------------------
    // Delete
    // -----------------------------------------------------------------------

    [Fact]
    public void Delete_RemovesEntry()
    {
        var cache = new SdkCache<string>(defaultTtl: TimeSpan.FromSeconds(60));
        cache.Set("to-delete", "value");
        cache.Delete("to-delete");
        Assert.Null(cache.Get("to-delete"));
    }

    [Fact]
    public void Delete_NonExistentKey_DoesNotThrow()
    {
        var cache = new SdkCache<string>();
        var ex = Record.Exception(() => cache.Delete("ghost"));
        Assert.Null(ex);
    }

    // -----------------------------------------------------------------------
    // Clear
    // -----------------------------------------------------------------------

    [Fact]
    public void Clear_RemovesAllEntries()
    {
        var cache = new SdkCache<string>(defaultTtl: TimeSpan.FromSeconds(60));
        cache.Set("a", "1");
        cache.Set("b", "2");
        cache.Set("c", "3");

        cache.Clear();

        Assert.Equal(0, cache.Count);
        Assert.Null(cache.Get("a"));
        Assert.Null(cache.Get("b"));
        Assert.Null(cache.Get("c"));
    }

    // -----------------------------------------------------------------------
    // Count
    // -----------------------------------------------------------------------

    [Fact]
    public void Count_ReflectsNumberOfStoredEntries()
    {
        var cache = new SdkCache<int>(defaultTtl: TimeSpan.FromSeconds(60));
        Assert.Equal(0, cache.Count);

        cache.Set("x", 1);
        Assert.Equal(1, cache.Count);

        cache.Set("y", 2);
        Assert.Equal(2, cache.Count);

        cache.Delete("x");
        Assert.Equal(1, cache.Count);
    }

    // -----------------------------------------------------------------------
    // MaxSize / LRU eviction
    // -----------------------------------------------------------------------

    [Fact]
    public void Set_WhenAtMaxSize_EvictsOldestEntry()
    {
        var cache = new SdkCache<int>(maxSize: 3, defaultTtl: TimeSpan.FromSeconds(60));
        cache.Set("first", 1);
        cache.Set("second", 2);
        cache.Set("third", 3);

        // Adding a 4th entry should evict "first" (oldest).
        cache.Set("fourth", 4);

        Assert.Equal(3, cache.Count);
        Assert.Null(cache.Get("first"));   // evicted
        Assert.Equal(2, cache.Get("second"));
        Assert.Equal(3, cache.Get("third"));
        Assert.Equal(4, cache.Get("fourth"));
    }

    [Fact]
    public void Set_NeverExceedsMaxSize()
    {
        int maxSize = 5;
        var cache = new SdkCache<int>(maxSize: maxSize, defaultTtl: TimeSpan.FromSeconds(60));

        for (int i = 0; i < 20; i++)
            cache.Set($"key-{i}", i);

        Assert.Equal(maxSize, cache.Count);
    }

    // -----------------------------------------------------------------------
    // Default TTL from constructor
    // -----------------------------------------------------------------------

    [Fact]
    public void DefaultTtl_FromConstructor_IsApplied()
    {
        var cache = new SdkCache<string>(defaultTtl: TimeSpan.FromSeconds(1));
        cache.Set("auto-ttl", "expires-soon");

        Assert.Equal("expires-soon", cache.Get("auto-ttl"));

        Thread.Sleep(1100);

        Assert.Null(cache.Get("auto-ttl"));
    }

    // -----------------------------------------------------------------------
    // Thread safety
    // -----------------------------------------------------------------------

    [Fact]
    public void ThreadSafety_ConcurrentWritesAndReads_DoNotThrow()
    {
        var cache = new SdkCache<int>(maxSize: 500, defaultTtl: TimeSpan.FromSeconds(60));

        var tasks = new List<Task>();

        // 50 writer tasks.
        for (int i = 0; i < 50; i++)
        {
            int local = i;
            tasks.Add(Task.Run(() =>
            {
                for (int j = 0; j < 20; j++)
                    cache.Set($"key-{local}-{j}", local * 100 + j);
            }));
        }

        // 50 reader tasks.
        for (int i = 0; i < 50; i++)
        {
            int local = i;
            tasks.Add(Task.Run(() =>
            {
                for (int j = 0; j < 20; j++)
                    cache.Get($"key-{local}-{j}");
            }));
        }

        var ex = Record.Exception(() => Task.WaitAll(tasks.ToArray()));
        Assert.Null(ex);
    }

    [Fact]
    public void ThreadSafety_ConcurrentClearAndSet_DoNotThrow()
    {
        var cache = new SdkCache<int>(maxSize: 1000, defaultTtl: TimeSpan.FromSeconds(60));

        var tasks = new List<Task>
        {
            Task.Run(() => { for (int i = 0; i < 200; i++) cache.Set($"k{i}", i); }),
            Task.Run(() => { for (int i = 0; i < 10; i++) { Thread.Sleep(1); cache.Clear(); } }),
            Task.Run(() => { for (int i = 0; i < 200; i++) cache.Get($"k{i}"); })
        };

        var ex = Record.Exception(() => Task.WaitAll(tasks.ToArray()));
        Assert.Null(ex);
    }
}
