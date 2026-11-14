using System.Security.Cryptography;
using System.Text.Json;
using Microsoft.IdentityModel.JsonWebTokens;
using Microsoft.IdentityModel.Tokens;

namespace Aicepeak.Api.Tests.Infrastructure;

/// <summary>
/// Entra-like v2 access tokens, signed with an RSA key generated when the tests run (no key or token is committed).
/// The defaults are valid for <see cref="TestSettings.WithEntra"/> and <see cref="StubOidcHandler"/>; each override
/// changes one aspect.
/// </summary>
public static class TestTokens {
    public const string Audience = "3f0d6c2a-8b1e-4a57-9c3d-5e7f9a1b2c4d";
    public const string ClientId = "7a9c1e3f-5b2d-4c6e-8f0a-1b3d5f7a9c2e";
    public const string OtherClientId = "1e2d3c4b-5a69-4788-9a0b-c1d2e3f4a5b6";
    public const string Scope = "access_as_user";
    public const string AppRole = "Api.Access";
    public const string KeyId = "test-key";

    /// <summary>The tenant seeded by the migration.</summary>
    public static readonly Guid AllowedTenant = new("db760528-cb7c-455c-bd41-e50a38f6fd62");

    public static readonly Guid PersonalAccountsTenant = new("9188040d-6c67-4c5b-b112-36a304b66dad");

    /// <summary>A work tenant that is not allowed; <see cref="OtherTenantKey"/> is bound to its issuer.</summary>
    public static readonly Guid OtherTenant = new("5b0f7c3e-2d4a-4e61-9f8b-7c6d5e4f3a2b");

    /// <summary>The key whose public part <see cref="StubOidcHandler"/> serves.</summary>
    public static RsaSecurityKey SigningKey { get; } = CreateKey(KeyId);

    /// <summary>A key that <see cref="StubOidcHandler"/> serves bound to <see cref="OtherTenant"/>'s issuer only.</summary>
    public static RsaSecurityKey OtherTenantKey { get; } = CreateKey("other-tenant-key");

    public static RsaSecurityKey CreateKey(string keyId) => new(RSA.Create(2048)) { KeyId = keyId };

    public static string Issuer(Guid tenant) => $"https://login.microsoftonline.com/{tenant}/v2.0";

    /// <summary>A valid delegated (user) access token with the required scope.</summary>
    public static Builder User(Guid? tenant = null, Guid? oid = null) => new Builder(tenant ?? AllowedTenant, oid ?? Guid.NewGuid())
        .With("scp", Scope)
        .With("name", "Ada Lovelace")
        .With("preferred_username", "ada@example.test")
        .With("idtyp", "user");

    /// <summary>A valid app-only (client credentials) access token with the required role.</summary>
    public static Builder App(Guid? tenant = null) => new Builder(tenant ?? AllowedTenant, Guid.NewGuid())
        .With("roles", new[] { AppRole })
        .With("idtyp", "app");

    public sealed class Builder {
        private static readonly JsonWebTokenHandler Handler = new() { SetDefaultTimesOnTokenCreation = false };

        private readonly Dictionary<string, object> _claims;
        private SecurityKey? _key = SigningKey;
        private string _algorithm = SecurityAlgorithms.RsaSha256;

        internal Builder(Guid tenant, Guid oid) {
            var now = DateTimeOffset.UtcNow;
            _claims = new() {
                ["aud"] = Audience,
                ["iss"] = Issuer(tenant),
                ["iat"] = now.ToUnixTimeSeconds(),
                ["nbf"] = now.ToUnixTimeSeconds(),
                ["exp"] = now.AddHours(1).ToUnixTimeSeconds(),
                ["azp"] = ClientId,
                ["tid"] = tenant.ToString(),
                ["oid"] = oid.ToString(),
                ["ver"] = "2.0",
            };
        }

        public Builder With(string claim, object value) {
            _claims[claim] = value;
            return this;
        }

        public Builder Without(string claim) {
            _claims.Remove(claim);
            return this;
        }

        /// <summary><c>exp</c> at now plus <paramref name="offset"/>.</summary>
        public Builder ExpiresIn(TimeSpan offset) => With("exp", DateTimeOffset.UtcNow.Add(offset).ToUnixTimeSeconds());

        /// <summary><c>nbf</c> at now plus <paramref name="offset"/>.</summary>
        public Builder NotBefore(TimeSpan offset) => With("nbf", DateTimeOffset.UtcNow.Add(offset).ToUnixTimeSeconds());

        /// <summary>Signs with another key or algorithm; a <c>null</c> key creates an unsigned token (<c>alg: none</c>).</summary>
        public Builder SignedWith(SecurityKey? key, string algorithm = SecurityAlgorithms.RsaSha256) {
            _key = key;
            _algorithm = algorithm;
            return this;
        }

        public string Build() {
            var payload = JsonSerializer.Serialize(_claims);
            return _key is null
                ? Handler.CreateToken(payload)
                : Handler.CreateToken(payload, new SigningCredentials(_key, _algorithm));
        }
    }
}
