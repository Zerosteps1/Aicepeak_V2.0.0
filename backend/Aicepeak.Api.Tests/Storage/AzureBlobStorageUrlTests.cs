using Aicepeak.Api.Configuration;
using Aicepeak.Api.Storage.Azure;
using Microsoft.AspNetCore.WebUtilities;
using Microsoft.Extensions.Options;

namespace Aicepeak.Api.Tests.Storage;

/// <summary>
/// The Azure adapter offline: blob URLs, their strict parsing, and the fields of the signed upload URL (AC-1), using
/// Azurite's well-known development account, whose URLs are built and signed locally.
/// </summary>
public sealed class AzureBlobStorageUrlTests {
    private const string Endpoint = "http://127.0.0.1:10000/devstoreaccount1";
    private const string Space = "1b4e28ba-2fa1-41d2-883f-0016d3cca427";
    private const string Name = "0193a5b2-0000-7000-8000-000000000001/0193a5b2-0000-7000-8000-000000000002";

    private static readonly DateTimeOffset Expires = new(2026, 11, 19, 12, 15, 0, TimeSpan.Zero);

    private readonly AzureBlobStorage _storage = Storage("UseDevelopmentStorage=true");

    [Fact]
    public void GetUrl_IsEndpointSpaceAndName_WithoutQuery() {
        Assert.Equal($"{Endpoint}/{Space}/{Name}", _storage.GetUrl(Space, Name).AbsoluteUri);
    }

    [Fact]
    public void TryParseUrl_RoundTripsGetUrl() {
        Assert.True(_storage.TryParseUrl(_storage.GetUrl(Space, Name), out var space, out var name));
        Assert.Equal((Space, Name), (space, name));
    }

    [Theory]
    [InlineData($"{Endpoint}/{Space}/{Name}?sv=2025-01-05&sig=x")]
    [InlineData($"{Endpoint}/{Space}/{Name}?")]
    [InlineData($"{Endpoint}/{Space}/{Name}#fragment")]
    [InlineData($"https://127.0.0.1:10000/devstoreaccount1/{Space}/{Name}")]
    [InlineData($"http://localhost:10000/devstoreaccount1/{Space}/{Name}")]
    [InlineData($"http://127.0.0.1:10001/devstoreaccount1/{Space}/{Name}")]
    [InlineData($"http://127.0.0.1:10000/otheraccount/{Space}/{Name}")]
    [InlineData($"http://user@127.0.0.1:10000/devstoreaccount1/{Space}/{Name}")]
    [InlineData($"{Endpoint}/{Space}")]
    [InlineData($"{Endpoint}/{Space}/")]
    [InlineData($"{Endpoint}//{Name}")]
    [InlineData($"{Endpoint}/{Space}/0193a5b2-0000-7000-8000-000000000001%2F0193a5b2-0000-7000-8000-000000000002")]
    public void TryParseUrl_IsStrict(string url) {
        Assert.False(_storage.TryParseUrl(new Uri(url), out _, out _));
    }

    [Fact]
    public void UploadSas_AllowsOnlyCreatingThisBlob_UntilExpiry_WithoutStartTime() {
        var url = _storage.CreateUploadSasUri(Space, Name, Expires);
        var query = QueryHelpers.ParseQuery(url.Query);

        Assert.Equal($"{Endpoint}/{Space}/{Name}", url.GetLeftPart(UriPartial.Path));
        Assert.Equal("c", query["sp"]);
        Assert.Equal("b", query["sr"]);
        Assert.Equal("2026-11-19T12:15:00Z", query["se"]);
        Assert.False(query.ContainsKey("st"));
        Assert.True(query.ContainsKey("sig"));
        // Azurite's endpoint is HTTP; the signature then allows both.
        Assert.Equal("https,http", query["spr"]);
    }

    [Fact]
    public void UploadSas_ForAnHttpsEndpoint_AllowsHttpsOnly() {
        var storage = Storage("UseDevelopmentStorage=true;DevelopmentStorageProxyUri=https://storage.example.test");

        var url = storage.CreateUploadSasUri(Space, Name, Expires);

        Assert.Equal(Uri.UriSchemeHttps, url.Scheme);
        Assert.Equal("https", QueryHelpers.ParseQuery(url.Query)["spr"]);
    }

    [Theory]
    [InlineData("UseDevelopmentStorage=true", true)]
    [InlineData("BlobEndpoint=https://example.test/;SharedAccessSignature=sv=2025-01-05&sig=abc", false)]
    [InlineData("not a connection string", false)]
    [InlineData("", false)]
    public void CanSignUploadUrls_OnlyWithASharedKey(string connectionString, bool expected) {
        Assert.Equal(expected, AzureBlobStorage.CanSignUploadUrls(connectionString));
    }

    private static AzureBlobStorage Storage(string connectionString) =>
        new(Options.Create(new BlobStorageOptions { Provider = "azure", ConnectionString = connectionString }));
}
