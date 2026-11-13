using System.Net;
using Aicepeak.Api.Tests.Infrastructure;

namespace Aicepeak.Api.Tests.Frontend;

/// <summary>
/// AC-7 for <see cref="Aicepeak.Api.Frontend.FrontendHosting"/>: with a built frontend in <c>wwwroot</c> (the layout the
/// PublishFrontend target creates on <c>dotnet publish</c>; here a temp content root), <c>/</c> and client routes serve
/// index.html with <c>Cache-Control: no-cache</c>, static assets are served and stay cacheable, and missing files and
/// unknown <c>/api/*</c> routes stay 404. In development the Vite dev server serves the frontend instead; the publish
/// copy itself is not tested here.
/// </summary>
public sealed class FrontendHostingTests : IAsyncDisposable {
    private const string Marker = "index-marker-3b8e";

    private readonly string _contentRoot = Directory.CreateTempSubdirectory("aicepeak-frontend-").FullName;
    private readonly ApiFactory _factory;

    public FrontendHostingTests() {
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
    public async Task StaticAsset_IsServed_AndStaysCacheable() {
        var response = await _factory.CreateClient().GetAsync("/assets/app.js", TestContext.Current.CancellationToken);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.False(response.Headers.CacheControl?.NoCache ?? false, $"Cache-Control of /assets/app.js: {response.Headers.CacheControl}");
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
