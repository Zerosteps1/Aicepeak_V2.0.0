namespace Aicepeak.Api.Auth;

/// <summary>
/// Microsoft Entra ID settings under the configuration keys <c>ENTRA_*</c>: environment variables, in Development also
/// <c>.env</c>. Missing or invalid values never stop the app; tokens are then rejected (see <c>AddEntraAuthentication</c>).
/// </summary>
public sealed class EntraOptions {
    public const string AudienceKey = "ENTRA_AUDIENCE";
    public const string ClientIdsKey = "ENTRA_CLIENT_IDS";
    public const string ScopeKey = "ENTRA_SCOPE";
    public const string AppRoleKey = "ENTRA_APP_ROLE";
    public const string MetadataAddressKey = "ENTRA_METADATA_ADDRESS";

    public const string DefaultMetadataAddress =
        "https://login.microsoftonline.com/organizations/v2.0/.well-known/openid-configuration";

    /// <summary>Client ID of the API registration, the <c>aud</c> of its v2 access tokens.</summary>
    [ConfigurationKeyName(AudienceKey)]
    public string? Audience { get; set; }

    /// <summary>Comma-separated client IDs that may call the API (<c>azp</c>).</summary>
    [ConfigurationKeyName(ClientIdsKey)]
    public string? ClientIds { get; set; }

    /// <summary>Delegated scope a user token must carry in <c>scp</c>.</summary>
    [ConfigurationKeyName(ScopeKey)]
    public string? Scope { get; set; }

    /// <summary>App role an app token must carry in <c>roles</c>.</summary>
    [ConfigurationKeyName(AppRoleKey)]
    public string? AppRole { get; set; }

    /// <summary>OIDC metadata document with the signing keys; empty means <see cref="DefaultMetadataAddress"/>.</summary>
    [ConfigurationKeyName(MetadataAddressKey)]
    public string? MetadataAddress { get; set; }

    public IReadOnlySet<string> AllowedClientIds =>
        (ClientIds ?? "").Split(',', StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries)
            .ToHashSet(StringComparer.Ordinal);

    /// <summary>The metadata address if it is an absolute https URI, otherwise <c>null</c> (no signing keys).</summary>
    public string? ValidMetadataAddress {
        get {
            var address = string.IsNullOrWhiteSpace(MetadataAddress) ? DefaultMetadataAddress : MetadataAddress.Trim();
            return Uri.TryCreate(address, UriKind.Absolute, out var uri) && uri.Scheme == Uri.UriSchemeHttps ? address : null;
        }
    }
}
