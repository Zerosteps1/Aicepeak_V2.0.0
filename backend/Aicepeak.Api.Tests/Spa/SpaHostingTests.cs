using System.Net;
using Aicepeak.Api.Tests.Infrastructure;

namespace Aicepeak.Api.Tests.Spa;

/// <summary>AC-7: the backend serves the built frontend from wwwroot, as laid out by <c>dotnet publish</c>.</summary>
public sealed class SpaHostingTests : IAsyncDisposable {
    private const string Marker = "spa-marker-3b8e";

    private readonly string _contentRoot = Directory.CreateTempSubdirectory("aicepeak-spa-").FullName;
    private readonly ApiFactory _factory;

    public SpaHostingTests() {
        var webRoot = Directory.CreateDirectory(Path.Combine(_contentRoot, "wwwroot", "assets")).Parent!.FullName;
        File.WriteAllText(Path.Combine(webRoot, "index.html"), $"<!doctype html><html><body>{Marker}</body></html>");
        File.WriteAllText(Path.Combine(webRoot, "assets", "app.js"), "console.log('app')");
        _factory = new ApiFactory(TestSettings.Production, TestSettings.UnreachableDatabase(), _contentRoot);
    }

    public async ValueTask DisposeAsync() {
        await _factory.DisposeAsync();
        Directory.Delete(_contentRoot, recursive: true);
    }

    [Theory]
    [InlineData("/")]
    [InlineData("/projects/42")]
    public async Task Root_AndClientRoutes_ServeIndexHtml(string path) {
        var response = await _factory.CreateClient().GetAsync(path, TestContext.Current.CancellationToken);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal("text/html", response.Content.Headers.ContentType?.MediaType);
        Assert.Contains(Marker, await response.Content.ReadAsStringAsync(TestContext.Current.CancellationToken));
    }

    [Theory]
    [InlineData("/")]
    [InlineData("/index.html")]
    [InlineData("/projects/42")]
    public async Task IndexHtml_IsRevalidated_SoRedeploysAreNotMaskedByCachedShell(string path) {
        var response = await _factory.CreateClient().GetAsync(path, TestContext.Current.CancellationToken);

        Assert.True(response.Headers.CacheControl?.NoCache, $"Cache-Control of {path}: {response.Headers.CacheControl}");
    }

    [Fact]
    public async Task StaticAsset_IsServed() {
        var response = await _factory.CreateClient().GetAsync("/assets/app.js", TestContext.Current.CancellationToken);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }

    [Theory]
    [InlineData("/assets/missing.js")]
    [InlineData("/api")]
    [InlineData("/api/nope")]
    [InlineData("/api/v1/nope")]
    public async Task MissingFilesAndUnknownApiRoutes_Return404_NotIndexHtml(string path) {
        var response = await _factory.CreateClient().GetAsync(path, TestContext.Current.CancellationToken);

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
        Assert.DoesNotContain(Marker, await response.Content.ReadAsStringAsync(TestContext.Current.CancellationToken));
    }
}
