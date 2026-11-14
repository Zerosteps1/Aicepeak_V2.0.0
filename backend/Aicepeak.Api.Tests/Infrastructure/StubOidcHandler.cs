using System.Collections.Concurrent;
using System.Net;
using System.Text;
using System.Text.Json;
using Microsoft.IdentityModel.Tokens;

namespace Aicepeak.Api.Tests.Infrastructure;

/// <summary>
/// Stands in for Microsoft Entra ID as the JWT bearer metadata backchannel: serves an OIDC metadata document and the
/// public key of <see cref="TestTokens.SigningKey"/> under <c>https://oidc.test</c>, answers 404 to everything else and
/// records every requested URI. Nothing reaches the network.
/// </summary>
public sealed class StubOidcHandler : HttpMessageHandler {
    public const string MetadataAddress = "https://oidc.test/organizations/v2.0/.well-known/openid-configuration";
    public const string KeysAddress = "https://oidc.test/keys";

    private static readonly string Metadata = JsonSerializer.Serialize(new Dictionary<string, object> {
        ["issuer"] = "https://login.microsoftonline.com/{tenantid}/v2.0",
        ["jwks_uri"] = KeysAddress,
        ["authorization_endpoint"] = "https://oidc.test/organizations/oauth2/v2.0/authorize",
        ["token_endpoint"] = "https://oidc.test/organizations/oauth2/v2.0/token",
        ["id_token_signing_alg_values_supported"] = new[] { "RS256" },
    });

    private static readonly string Keys = CreateKeys();

    private readonly ConcurrentQueue<Uri> _requests = new();

    public IReadOnlyCollection<Uri> Requests => _requests;

    protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) {
        var uri = request.RequestUri!;
        _requests.Enqueue(uri);

        var body = uri.AbsoluteUri switch {
            MetadataAddress => Metadata,
            KeysAddress => Keys,
            _ => null,
        };
        var response = body is null
            ? new HttpResponseMessage(HttpStatusCode.NotFound)
            : new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(body, Encoding.UTF8, "application/json") };

        return Task.FromResult(response);
    }

    private static string CreateKeys() {
        var parameters = TestTokens.SigningKey.Rsa.ExportParameters(includePrivateParameters: false);
        var key = new Dictionary<string, string> {
            ["kty"] = "RSA",
            ["use"] = "sig",
            ["kid"] = TestTokens.KeyId,
            ["n"] = Base64UrlEncoder.Encode(parameters.Modulus),
            ["e"] = Base64UrlEncoder.Encode(parameters.Exponent),
        };

        return JsonSerializer.Serialize(new { keys = new[] { key } });
    }
}
