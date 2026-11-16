using System.Net;
using Aicepeak.Api.Frontend;
using Aicepeak.Api.Tests.Infrastructure;

namespace Aicepeak.Api.Tests.Frontend;

/// <summary>
/// The frontend's Entra config is filled into index.html once at startup, from the <c>ENTRA_*</c> settings, and served
/// from memory for every page: one build for every environment.
/// </summary>
public sealed class FrontendConfigInjectionTests : IAsyncDisposable {
    private const string ExpectedConfig =
        "{\"clientId\":\"" + TestTokens.Audience + "\",\"apiScope\":\"api://" + TestTokens.Audience + "/" + TestTokens.Scope + "\"}";

    private readonly string _contentRoot = Directory.CreateTempSubdirectory("aicepeak-frontend-config-").FullName;
    private readonly List<ApiFactory> _factories = [];

    public FrontendConfigInjectionTests() {
        var webRoot = Directory.CreateDirectory(Path.Combine(_contentRoot, "wwwroot")).FullName;
        File.WriteAllText(Path.Combine(webRoot, "index.html"), Page(FrontendHosting.ConfigMarker));
    }

    public async ValueTask DisposeAsync() {
        foreach (var factory in _factories) {
            await factory.DisposeAsync();
        }

        Directory.Delete(_contentRoot, recursive: true);
    }

    [Theory]
    [InlineData("/")]
    [InlineData("/login")]
    [InlineData("/index.html")]
    [InlineData("/INDEX.HTML")]
    [InlineData("/projects/42")]
    public async Task Pages_CarryTheConfigFromTheEntraSettings(string path) {
        var client = CreateClient(TestSettings.WithEntra(TestSettings.UnreachableDatabase()));

        var response = await client.GetAsync(path, TestContext.Current.CancellationToken);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal("text/html", response.Content.Headers.ContentType?.MediaType);
        Assert.True(response.Headers.CacheControl?.NoCache, $"Cache-Control of {path}: {response.Headers.CacheControl}");
        var html = await response.Content.ReadAsStringAsync(TestContext.Current.CancellationToken);
        Assert.Equal(Page(ExpectedConfig), html);
    }

    [Fact]
    public async Task MissingEntraSettings_GiveNullConfig() {
        var settings = TestSettings.WithEntra(TestSettings.UnreachableDatabase());
        settings["ENTRA_SCOPE"] = "";
        var client = CreateClient(settings);

        var html = await client.GetStringAsync("/login", TestContext.Current.CancellationToken);

        Assert.Equal(Page("null"), html);
    }

    [Fact]
    public async Task ConfigValues_CannotCloseTheScriptElement() {
        var settings = TestSettings.WithEntra(TestSettings.UnreachableDatabase());
        settings["ENTRA_SCOPE"] = "x</script><script>alert(1)</script>";
        var client = CreateClient(settings);

        var html = await client.GetStringAsync("/login", TestContext.Current.CancellationToken);

        Assert.DoesNotContain("</script><script>alert", html);
        Assert.Contains("\\u003C/script\\u003E", html);
    }

    [Fact]
    public async Task IndexHtml_IsRenderedOnceAtStartup() {
        var client = CreateClient(TestSettings.WithEntra(TestSettings.UnreachableDatabase()));
        var first = await client.GetStringAsync("/", TestContext.Current.CancellationToken);

        await File.WriteAllTextAsync(Path.Combine(_contentRoot, "wwwroot", "index.html"), "changed on disk", TestContext.Current.CancellationToken);
        var second = await client.GetStringAsync("/", TestContext.Current.CancellationToken);

        Assert.Equal(Page(ExpectedConfig), first);
        Assert.Equal(first, second);
    }

    private static string Page(string config) =>
        $"<!doctype html><html><head><script>window.__AICEPEAK_CONFIG__ = {config};</script></head><body></body></html>";

    private HttpClient CreateClient(Dictionary<string, string?> settings) {
        var factory = new ApiFactory(TestSettings.Production, settings, _contentRoot);
        _factories.Add(factory);
        return factory.CreateClient();
    }
}
