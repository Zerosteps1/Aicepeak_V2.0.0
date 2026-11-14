using System.Net;
using Aicepeak.Api.Tests.Infrastructure;
using Microsoft.IdentityModel.Tokens;
using static Aicepeak.Api.Tests.Infrastructure.BearerRequests;

namespace Aicepeak.Api.Tests.Auth;

/// <summary>
/// AC-6, AC-7, AC-10, AC-17, AC-18 and AC-24 without a database. The database is unreachable, so a token that passes
/// every token check is still rejected, at the tenant allowlist; each test therefore asserts which check rejected the
/// token (<see cref="ApiFactory.AuthenticationFailures"/>). Signing keys come from <see cref="StubOidcHandler"/>.
/// </summary>
public sealed class EntraTokenValidationTests {
    [Theory]
    [InlineData("GET", ProtectedPath)]
    [InlineData("PUT", LoginPath)]
    public async Task AC06_MissingAuthorizationHeader_Returns401WithMessage(string method, string path) {
        await using var factory = CreateFactory();

        var response = await factory.CreateClient().SendAsync(new HttpMethod(method), path, token: null);

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        Assert.Equal("text/plain", response.Content.Headers.ContentType?.MediaType);
        Assert.Equal("utf-8", response.Content.Headers.ContentType?.CharSet);
        Assert.Equal("Authentication header missing", await response.Content.ReadAsStringAsync(TestContext.Current.CancellationToken));
        Assert.Empty(factory.AuthenticationFailures);
    }

    [Fact]
    public async Task AC06_NonBearerAuthorizationHeader_Returns401WithoutMessage() {
        await using var factory = CreateFactory();
        using var request = new HttpRequestMessage(HttpMethod.Get, ProtectedPath);
        request.Headers.TryAddWithoutValidation("Authorization", "Basic dXNlcjpwYXNz");

        var response = await factory.CreateClient().SendAsync(request, TestContext.Current.CancellationToken);

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        Assert.Equal("Bearer", response.Headers.WwwAuthenticate.ToString());
        Assert.Empty(await response.Content.ReadAsStringAsync(TestContext.Current.CancellationToken));
    }

    [Theory]
    [InlineData(TestSettings.Production, "/api/v1/health/alive", HttpStatusCode.ServiceUnavailable)]
    [InlineData(TestSettings.Production, "/api/v1/nope", HttpStatusCode.NotFound)]
    [InlineData(TestSettings.Production, "/openapi/v1.json", HttpStatusCode.NotFound)]
    [InlineData(TestSettings.Development, "/openapi/v1.json", HttpStatusCode.OK)]
    public async Task EndpointsOutsideTheProtectedApi_StayAnonymous(string environment, string path, HttpStatusCode expected) {
        await using var factory = CreateFactory(environment: environment);
        var client = factory.CreateClient();

        Assert.Equal(expected, (await client.SendAsync(HttpMethod.Get, path, token: null)).StatusCode);
        Assert.Equal(expected, (await client.SendAsync(HttpMethod.Get, path, "not-a-jwt")).StatusCode);
    }

    [Theory]
    [InlineData("signed-with-other-key", nameof(SecurityTokenInvalidSignatureException))]
    [InlineData("unsigned", nameof(SecurityTokenInvalidSignatureException))]
    [InlineData("signed-with-rs384", nameof(SecurityTokenInvalidSignatureException))]
    [InlineData("garbage", nameof(SecurityTokenMalformedException))]
    [InlineData("expired", nameof(SecurityTokenExpiredException))]
    public async Task AC07_InvalidOrExpiredToken_Returns401(string kind, string rejection) {
        var token = kind switch {
            "signed-with-other-key" => TestTokens.User().SignedWith(TestTokens.CreateKey(TestTokens.KeyId)).Build(),
            "unsigned" => TestTokens.User().SignedWith(null).Build(),
            "signed-with-rs384" => TestTokens.User().SignedWith(TestTokens.SigningKey, SecurityAlgorithms.RsaSha384).Build(),
            "garbage" => "not-a-jwt",
            "expired" => TestTokens.User().NotBefore(TimeSpan.FromHours(-2)).ExpiresIn(TimeSpan.FromHours(-1)).Build(),
            _ => throw new ArgumentOutOfRangeException(nameof(kind)),
        };

        await AssertRejectedAsync(token, rejection);
    }

    [Theory]
    [InlineData("personal-account", Rejections.PersonalAccount)]
    [InlineData("id-token-for-spa", nameof(SecurityTokenInvalidAudienceException))]
    [InlineData("id-token-for-api", Rejections.ClientNotAllowed)]
    [InlineData("wrong-aud", nameof(SecurityTokenInvalidAudienceException))]
    [InlineData("aud-with-trailing-slash", nameof(SecurityTokenInvalidAudienceException))]
    [InlineData("aud-array-including-ours", Rejections.NotSingleAudience)]
    [InlineData("ver-1.0", Rejections.NotV2)]
    [InlineData("no-ver", Rejections.NotV2)]
    [InlineData("azp-not-allowed", Rejections.ClientNotAllowed)]
    public async Task AC10_TokenNotIssuedForThisApi_Returns401(string kind, string rejection) {
        var token = kind switch {
            "personal-account" => TestTokens.User(TestTokens.PersonalAccountsTenant),
            // An ID token: issued to the SPA, without azp and scp.
            "id-token-for-spa" => IdToken().With("aud", TestTokens.ClientId),
            "id-token-for-api" => IdToken(),
            "wrong-aud" => TestTokens.User().With("aud", Guid.NewGuid().ToString()),
            "aud-with-trailing-slash" => TestTokens.User().With("aud", TestTokens.Audience + "/"),
            "aud-array-including-ours" => TestTokens.User().With("aud", new[] { Guid.NewGuid().ToString(), TestTokens.Audience }),
            "ver-1.0" => TestTokens.User().With("ver", "1.0"),
            "no-ver" => TestTokens.User().Without("ver"),
            "azp-not-allowed" => TestTokens.User().With("azp", Guid.NewGuid().ToString()),
            _ => throw new ArgumentOutOfRangeException(nameof(kind)),
        };

        await AssertRejectedAsync(token.Build(), rejection);
    }

    [Theory]
    [InlineData("other-tenant")]
    [InlineData("v1-issuer")]
    [InlineData("trailing-slash")]
    [InlineData("organizations")]
    [InlineData("no-iss")]
    public async Task AC17_IssuerIsNotV2IssuerOfTheTokensTenant_Returns401(string kind) {
        var tid = TestTokens.AllowedTenant;
        var token = kind switch {
            "other-tenant" => TestTokens.User().With("iss", TestTokens.Issuer(Guid.NewGuid())),
            "v1-issuer" => TestTokens.User().With("iss", $"https://sts.windows.net/{tid}/"),
            "trailing-slash" => TestTokens.User().With("iss", TestTokens.Issuer(tid) + "/"),
            "organizations" => TestTokens.User().With("iss", "https://login.microsoftonline.com/organizations/v2.0"),
            "no-iss" => TestTokens.User().Without("iss"),
            _ => throw new ArgumentOutOfRangeException(nameof(kind)),
        };

        await AssertRejectedAsync(token.Build(), nameof(SecurityTokenInvalidIssuerException));
    }

    [Theory]
    [InlineData("expired-6-minutes-ago", nameof(SecurityTokenExpiredException))]
    [InlineData("valid-in-6-minutes", nameof(SecurityTokenNotYetValidException))]
    [InlineData("no-exp", nameof(SecurityTokenNoExpirationException))]
    [InlineData("no-nbf", Rejections.NoNbf)]
    public async Task AC18_LifetimeOutsideFiveMinuteSkew_Returns401(string kind, string rejection) {
        await AssertRejectedAsync(LifetimeToken(kind).Build(), rejection);
    }

    [Theory]
    [InlineData("expired-4-minutes-ago")]
    [InlineData("valid-in-4-minutes")]
    public async Task AC18_LifetimeInsideFiveMinuteSkew_PassesEveryTokenCheck(string kind) {
        // Rejected only at the tenant allowlist, because the database is unreachable (LoginDatabaseTests: 200).
        await AssertRejectedAsync(LifetimeToken(kind).Build(), Rejections.AllowlistUnavailable);
    }

    [Fact]
    public async Task AC24_SigningKeys_ComeFromStubbedMetadata_AndNoOtherHostIsContacted() {
        await using var factory = CreateFactory();

        var response = await factory.CreateClient().SendAsync(HttpMethod.Get, ProtectedPath, TestTokens.User().Build());

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        // The signature was verified with the stub's key: the token got as far as the tenant allowlist.
        Assert.Equal(Rejections.AllowlistUnavailable, factory.SingleRejection());
        Assert.Contains(new Uri(StubOidcHandler.MetadataAddress), factory.Oidc.Requests);
        Assert.Contains(new Uri(StubOidcHandler.KeysAddress), factory.Oidc.Requests);
        Assert.All(factory.Oidc.Requests, uri => Assert.Equal("oidc.test", uri.Host));
    }

    [Fact]
    public async Task AC24_DefaultMetadataAddress_IsAnsweredByTheStub_NotByMicrosoft() {
        await using var factory = CreateFactory(settings => settings["ENTRA_METADATA_ADDRESS"] = "");

        var response = await factory.CreateClient().SendAsync(HttpMethod.Get, ProtectedPath, TestTokens.User().Build());

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        // The stub answers 404 to the real Entra address, so there are no signing keys.
        Assert.Equal(nameof(SecurityTokenSignatureKeyNotFoundException), factory.SingleRejection());
        Assert.NotEmpty(factory.Oidc.Requests);
        Assert.All(factory.Oidc.Requests, uri => Assert.Equal(
            "https://login.microsoftonline.com/organizations/v2.0/.well-known/openid-configuration", uri.AbsoluteUri));
    }

    [Theory]
    [InlineData("http://oidc.test/organizations/v2.0/.well-known/openid-configuration")]
    [InlineData("oidc.test/organizations/v2.0/.well-known/openid-configuration")]
    public async Task InvalidMetadataAddress_RejectsEveryToken_AndHealthIsUnchanged(string address) {
        await using var factory = CreateFactory(settings => settings["ENTRA_METADATA_ADDRESS"] = address);
        var client = factory.CreateClient();

        await AssertHealthIsUnchangedAsync(client);
        var response = await client.SendAsync(HttpMethod.Get, ProtectedPath, TestTokens.User().Build());

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        Assert.Equal(nameof(SecurityTokenSignatureKeyNotFoundException), factory.SingleRejection());
        Assert.Empty(factory.Oidc.Requests);
    }

    [Theory]
    [InlineData("ENTRA_AUDIENCE", "user", nameof(SecurityTokenInvalidAudienceException))]
    [InlineData("ENTRA_CLIENT_IDS", "user", Rejections.ClientNotAllowed)]
    [InlineData("ENTRA_SCOPE", "user", Rejections.MissingScope)]
    [InlineData("ENTRA_APP_ROLE", "app", Rejections.NotAnAppToken)]
    public async Task MissingEntraSetting_RejectsTokens_AndHealthIsUnchanged(string key, string tokenKind, string rejection) {
        await using var factory = CreateFactory(settings => settings[key] = "");
        var client = factory.CreateClient();
        var token = tokenKind == "app" ? TestTokens.App() : TestTokens.User();

        await AssertHealthIsUnchangedAsync(client);
        var response = await client.SendAsync(HttpMethod.Get, ProtectedPath, token.Build());

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        Assert.Equal(rejection, factory.SingleRejection());
    }

    [Fact]
    public async Task AllEntraSettingsMissing_AppStarts_RejectsTokens_AndHealthIsUnchanged() {
        await using var factory = CreateFactory(settings => {
            foreach (var key in settings.Keys.Where(key => key.StartsWith("ENTRA_", StringComparison.Ordinal)).ToList()) {
                settings[key] = "";
            }
        });
        var client = factory.CreateClient();

        await AssertHealthIsUnchangedAsync(client);
        var withToken = await client.SendAsync(HttpMethod.Get, ProtectedPath, TestTokens.User().Build());
        var withoutHeader = await client.SendAsync(HttpMethod.Put, LoginPath, token: null);

        Assert.Equal(HttpStatusCode.Unauthorized, withToken.StatusCode);
        Assert.Equal(HttpStatusCode.Unauthorized, withoutHeader.StatusCode);
    }

    private static ApiFactory CreateFactory(Action<Dictionary<string, string?>>? change = null, string environment = TestSettings.Production) {
        var settings = TestSettings.WithEntra(TestSettings.UnreachableDatabase());
        change?.Invoke(settings);
        return new ApiFactory(environment, settings);
    }

    /// <summary>GET on the protected test endpoint: 401, rejected for <paramref name="rejection"/>.</summary>
    private static async Task AssertRejectedAsync(string token, string rejection) {
        await using var factory = CreateFactory();

        var response = await factory.CreateClient().SendAsync(HttpMethod.Get, ProtectedPath, token);

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        // No error details for the caller (IncludeErrorDetails = false).
        Assert.Equal("Bearer", response.Headers.WwwAuthenticate.ToString());
        Assert.Equal(rejection, factory.SingleRejection());
    }

    /// <summary>The normal result for an unreachable database (see HealthAliveTests), not a 500.</summary>
    private static async Task AssertHealthIsUnchangedAsync(HttpClient client) {
        var response = await client.SendAsync(HttpMethod.Get, "/api/v1/health/alive", token: null);

        Assert.Equal(HttpStatusCode.ServiceUnavailable, response.StatusCode);
        var health = new HealthResponse(await response.Content.ReadAsStringAsync(TestContext.Current.CancellationToken));
        Assert.Equal("Healthy", health.ComponentStatus("configuration"));
        Assert.Equal("Unhealthy", health.ComponentStatus("database"));
    }

    private static TestTokens.Builder IdToken() =>
        TestTokens.User().Without("azp").Without("scp").With("nonce", "nonce-1");

    private static TestTokens.Builder LifetimeToken(string kind) => kind switch {
        "expired-6-minutes-ago" => TestTokens.User().NotBefore(TimeSpan.FromHours(-1)).ExpiresIn(TimeSpan.FromMinutes(-6)),
        "expired-4-minutes-ago" => TestTokens.User().NotBefore(TimeSpan.FromHours(-1)).ExpiresIn(TimeSpan.FromMinutes(-4)),
        "valid-in-6-minutes" => TestTokens.User().NotBefore(TimeSpan.FromMinutes(6)),
        "valid-in-4-minutes" => TestTokens.User().NotBefore(TimeSpan.FromMinutes(4)),
        "no-exp" => TestTokens.User().Without("exp"),
        "no-nbf" => TestTokens.User().Without("nbf"),
        _ => throw new ArgumentOutOfRangeException(nameof(kind)),
    };
}
