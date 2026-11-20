using System.Net;
using Aicepeak.Api.Tests.Infrastructure;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.Extensions.DependencyInjection;

namespace Aicepeak.Api.Tests.Projects;

/// <summary>
/// AC-8 for the project endpoints without a database: they have no route constraints, so every request without a
/// valid token gets 401, whatever the IDs look like; an authenticated app token gets 401 too, before its tenant's
/// database is touched.
/// </summary>
public sealed class ProjectEndpointsAuthTests {
    public static TheoryData<string, string> Routes => new() {
        { "POST", "/api/v1/project" },
        { "GET", "/api/v1/project/0193a5b2-0000-7000-8000-000000000001" },
        { "GET", "/api/v1/project/not-a-guid" },
        { "PATCH", "/api/v1/project/not-a-guid" },
        { "POST", "/api/v1/project/not-a-guid/upload-url" },
        { "DELETE", "/api/v1/project/not-a-guid/document/also-not-a-guid" },
        { "GET", "/api/v1/project/not-a-guid/document-validation/sse" },
        { "GET", "/api/v1/project/not-a-guid/document-extraction/sse" },
    };

    [Theory]
    [MemberData(nameof(Routes))]
    public async Task AC08_WithoutToken_Returns401(string method, string path) {
        await using var factory = new ApiFactory(TestSettings.Production, TestSettings.WithEntra(TestSettings.UnreachableDatabase()));

        var response = await factory.CreateClient().SendAsync(new HttpMethod(method), path, token: null);

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Theory]
    [InlineData("POST", "/api/v1/project", "text/plain")]
    [InlineData("PATCH", "/api/v1/project/0193a5b2-0000-7000-8000-000000000001", "application/xml")]
    [InlineData("POST", "/api/v1/project/not-a-guid/upload-url", "text/plain")]
    public async Task AC08_WithoutToken_BodyThatIsNoJson_Returns401(string method, string path, string mediaType) {
        // The OpenAPI request bodies must not make routing pick another endpoint (415 or the API catch-all's 404) first.
        await using var factory = new ApiFactory(TestSettings.Production, TestSettings.WithEntra(TestSettings.UnreachableDatabase()));
        using var request = new HttpRequestMessage(new HttpMethod(method), path) { Content = new StringContent("name=x", null, mediaType) };

        var response = await factory.CreateClient().SendAsync(request, TestContext.Current.CancellationToken);

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Theory]
    [MemberData(nameof(Routes))]
    public async Task AC08_InvalidToken_Returns401(string method, string path) {
        await using var factory = new ApiFactory(TestSettings.Production, TestSettings.WithEntra(TestSettings.UnreachableDatabase()));
        var token = TestTokens.User().SignedWith(TestTokens.CreateKey(TestTokens.KeyId)).Build();

        var response = await factory.CreateClient().SendAsync(new HttpMethod(method), path, token);

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Theory]
    [MemberData(nameof(Routes))]
    public async Task AC08_AuthenticatedAppToken_Returns401_WithoutTouchingTheDatabase(string method, string path) {
        // The tenant allowlist needs the database; here every token that passes the token checks counts as allowed.
        await using var factory = new ApiFactory(
            TestSettings.Production,
            TestSettings.WithEntra(TestSettings.UnreachableDatabase()),
            configureServices: services => services.PostConfigure<JwtBearerOptions>(
                JwtBearerDefaults.AuthenticationScheme, options => options.Events.OnTokenValidated = _ => Task.CompletedTask));

        var response = await factory.CreateClient().SendAsync(new HttpMethod(method), path, TestTokens.App().Build());

        // Authenticated, then refused by the tenant filter; reaching the unreachable database would answer 500.
        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        Assert.Empty(factory.AuthenticationFailures);
    }
}
